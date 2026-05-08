"""Epic-level graph (Level 2): story loop + epic post-processing.

Iterates through all stories in a single epic, invoking the TDD
orchestrator for each story. After all stories complete, runs
epic-level post-processing: code review across all stories,
architect decision, fix cycle, regression tests, and full CI.
"""

from __future__ import annotations

import json
import logging
import operator
import os
import re
import time
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from src.audit_log.audit import get_logger
from src.intake.checkpoint import (
    clear_epic_phase_checkpoint,
    clear_phase_checkpoint,
    load_phase_checkpoint,
    save_epic_phase_checkpoint,
)
from src.intake.pause import is_pause_requested
from src.intake.review_sieve import (
    SieveResult,
    append_deferred_work,
    render_analysis_file,
    render_category_file,
    sieve_reviews,
)
from src.multi_agent.bmad_invoke import (
    TIMEOUT_LONG,
    TIMEOUT_MEDIUM,
    TOOLS_DEV,
    TOOLS_REVIEW_READONLY,
    invoke_bmad_agent,
    invoke_ci_with_fix,
    invoke_claude_cli,
)
from src.multi_agent.orchestrator import (
    OrchestratorState,
    _detect_project_type,
    _ensure_migrations,
    _run_bash,
    build_orchestrator,
    get_fix_pre_existing,
    resolve_ci_command,
)
from src.multi_agent.bmad_invoke import (
    get_rate_limit_sleep_seconds,
    reset_rate_limit_sleep_counter,
)
from src.pipeline_tracker import update_story_progress

# Threshold (in seconds of *actual work time*, excluding rate-limit sleeps)
# above which a completed story is flagged as slow. 45 min — most stories
# in the PawprintRecipes Epic 1+2 corpus completed in 7-30 min; a few heavy
# stories (OAuth, Docker scaffolding) hit 30-50 min legitimately. Past 45
# min the agent has likely thrashed in a CI-fix loop or against
# under-specified acceptance criteria, and the operator should know.
SLOW_STORY_WORK_SECONDS = 45 * 60

# deferred-work.md lives under the target repo's BMAD output tree; BMAD
# skills also append to this path at story level.
DEFERRED_WORK_RELATIVE_PATH = os.path.join(
    "_bmad-output", "implementation-artifacts", "deferred-work.md",
)

logger = logging.getLogger(__name__)

# Epic-level retry limit for fix cycle
MAX_EPIC_FIX_CYCLES = 2

# ---------------------------------------------------------------------------
# Per-node model configuration (epic-level)
# ---------------------------------------------------------------------------

_EPIC_MODEL_CONFIG: dict[str, str | None] = {
    "epic_review": "claude-sonnet-4-6",
    "epic_analysis": "claude-sonnet-4-6",
    "epic_fix_cat_a": "claude-sonnet-4-6",
    "epic_architect": "claude-opus-4-6",
    "epic_fix_dev": "claude-sonnet-4-6",
}


def set_epic_model_config(config: dict[str, str | None]) -> None:
    """Update per-node model overrides for epic-level nodes."""
    _EPIC_MODEL_CONFIG.update(config)


def _epic_model_for(node: str) -> str | None:
    """Return the model override for a given epic node, or None for default."""
    return _EPIC_MODEL_CONFIG.get(node)

# Epic-level review directories (separate from story-level)
EPIC_REVIEWS_DIR = "epic-reviews"

# All epic-reviews/ artifacts are epic-numbered so multiple epics can
# coexist in the directory without clobbering each other. When a later
# epic needs to reference earlier epic's findings, or a re-run has to
# recover work that was missed, the files are identified by epic number
# in their name rather than by position in time.
EPIC_FIX_PLAN_FILENAME_TEMPLATE = "epic-{epic_num}-fix-plan.md"
REVIEW_BMAD_FILENAME_TEMPLATE = "epic-{epic_num}-review-bmad.md"
REVIEW_CLAUDE_FILENAME_TEMPLATE = "epic-{epic_num}-review-claude.md"
ANALYSIS_FILENAME_TEMPLATE = "epic-{epic_num}-analysis.md"
CATEGORY_A_PLAN_FILENAME_TEMPLATE = "epic-{epic_num}-category-a-fix-plan.md"
CATEGORY_B_REVIEW_FILENAME_TEMPLATE = "epic-{epic_num}-category-b-architect-review.md"
CATEGORY_A_DONE_FILENAME_TEMPLATE = "epic-{epic_num}-category-a-fix-done.md"

# Minimum size (in characters) for a review file to be considered a
# real review rather than an empty stub or a preamble-only LLM failure.
# Used by collect_epic_reviews_node to reject half-written reviews,
# and by _run_review_sieve as its format-drift guard threshold.
REVIEW_MIN_CONTENT_CHARS = 1000


# ---------------------------------------------------------------------------
# State Schema
# ---------------------------------------------------------------------------


class EpicState(TypedDict, total=False):
    """State schema for the epic-level graph (Level 2).

    Manages story iteration within a single epic and epic-level
    post-processing (review, fix, regression, CI).
    """

    # Identity
    session_id: str
    target_dir: str
    epic_num: str
    epic_name: str

    # Story iteration
    stories: list[dict[str, Any]]
    story_index: int

    # Accumulated results
    story_results: Annotated[list[dict[str, Any]], operator.add]
    stories_completed: int
    stories_failed: int
    total_interventions: int

    # Files modified across all stories in this epic (for epic-level review)
    epic_files_modified: Annotated[list[str], operator.add]

    # Current story output
    current_story_status: str  # completed|failed
    current_story_error: str
    current_story_failed_phase: str  # orchestrator phase where the story failed
    current_story_retry_instruction: str  # set by intervention
    current_story_start_time: float  # time.time() captured at select_story_node;
                                     # finalize subtracts rate-limit sleep from
                                     # (now - this) to compute work_seconds.

    # Epic post-processing state
    epic_review_file_paths: Annotated[list[str], operator.add]
    # Story IDs in scope for epic-level code review — populated by
    # prepare_epic_reviews_node, consumed by route_to_epic_reviewers.
    # Excludes spike (first) + integration-polish (last) stories per the
    # BMAD methodology. Each entry: {story_id, story_name, task_id}.
    epic_review_stories: list[dict[str, str]]
    epic_fix_plan_path: str
    epic_fixes_needed: bool
    epic_fix_cycle: int
    epic_test_passed: bool
    epic_last_test_output: str
    epic_last_ci_output: str

    # Analysis phase outputs (Category A/B classification)
    category_a_fix_plan_path: str
    category_b_review_path: str
    analysis_path: str
    category_a_fixes_applied: bool
    has_category_b_items: bool

    # Control
    epic_status: str  # running|completed|failed|aborted
    error: str

    # Rebuild-level context (passed down from Level 1 for checkpointing)
    rebuild_epic_index: int
    rebuild_prior_completed: int
    rebuild_prior_failed: int
    rebuild_prior_interventions: int
    rebuild_prior_results: list[dict[str, Any]]

    # Phase-level resume for epic post-processing. Set by run_epic_node
    # when a stale epic-phase.json matches (session_id, epic_num).
    # Non-empty = jump past the story loop and earlier post-processing
    # phases directly to this phase. Empty = normal entry.
    resume_from_epic_phase: str


class EpicReviewNodeInput(TypedDict):
    """Input schema for epic-level review node via Send API.

    The reviewer is given a list of story IDs (with names) — not a flat
    file list. The BMAD code-review skill is self-driving from a story
    number: it reads the story spec, finds the dev agent's recorded file
    list, runs git diff for that story's commit, and verifies the story's
    acceptance criteria are met by the implementation. Pre-computing the
    file list externally would (a) duplicate work the agent does anyway,
    (b) strip away the per-story context the review needs, and (c) risk
    drifting from BMAD's own evolving review workflow. So we just hand
    over the IDs.
    """

    reviewer_type: str  # "bmad" or "claude"
    task_id: str
    session_id: str
    epic_num: str
    stories_to_review: list[dict[str, str]]  # each: story_id, story_name, task_id
    working_dir: str


# ---------------------------------------------------------------------------
# Story Loop Nodes
# ---------------------------------------------------------------------------


def select_story_node(state: EpicState) -> dict[str, Any]:
    """Build task description from the current story and prepare for orchestrator."""
    stories = state.get("stories", [])
    story_index = state.get("story_index", 0)
    epic_num = state.get("epic_num", "")
    epic_name = state.get("epic_name", "")

    story_entry = stories[story_index]
    story_id = story_entry.get("story_id", "")
    story_name = story_entry.get("story_name", "")
    description = story_entry.get("description", "")
    criteria = story_entry.get("acceptance_criteria", [])
    criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else ""

    task_description = (
        f"Story {story_id}: {story_name}\n"
        f"Epic {epic_num}: {epic_name}\n"
        f"{description}\n\n"
        f"Acceptance Criteria:\n{criteria_text}"
    )

    # Check if there's a retry instruction from intervention
    retry_instruction = state.get("current_story_retry_instruction", "")
    if retry_instruction:
        task_description += f"\n\nINTERVENTION FIX INSTRUCTION:\n{retry_instruction}"

    print(f"\n{'─'*60}")
    print(f"STORY {story_id}: {story_name} (Epic {epic_num})")
    print(f"{'─'*60}")

    update_story_progress(state.get("session_id", ""),
        epic=f"Epic {epic_num}: {epic_name}",
        story=f"Story {story_id}: {story_name}",
        story_index=state.get("rebuild_prior_completed", 0) + story_index,
    )

    # Per-story duration accounting: capture start time and zero the
    # rate-limit sleep counter so process_story_result_node can compute
    # actual work time (wall time minus any rate-limit sleeps that
    # accumulated during this story).
    reset_rate_limit_sleep_counter()

    return {
        "current_story_status": "",
        "current_story_error": "",
        "current_story_retry_instruction": "",
        "current_story_start_time": time.time(),
    }


def run_story_node(state: EpicState) -> dict[str, Any]:
    """Invoke the TDD orchestrator for the current story (wrapper around Level 3)."""
    session_id = state.get("session_id", "")
    target_dir = state.get("target_dir", "")
    epic_num = state.get("epic_num", "")
    epic_name = state.get("epic_name", "")
    stories = state.get("stories", [])
    story_index = state.get("story_index", 0)

    story_entry = stories[story_index]
    story_id = story_entry.get("story_id", "")
    story_name = story_entry.get("story_name", "")
    description = story_entry.get("description", "")
    criteria = story_entry.get("acceptance_criteria", [])
    criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else ""

    task_description = (
        f"Story {story_id}: {story_name}\n"
        f"Epic {epic_num}: {epic_name}\n"
        f"{description}\n\n"
        f"Acceptance Criteria:\n{criteria_text}"
    )

    # Apply retry instruction if present
    retry_instruction = state.get("current_story_retry_instruction", "")
    if retry_instruction:
        task_description += f"\n\nINTERVENTION FIX INSTRUCTION:\n{retry_instruction}"

    task_id = story_id
    if retry_instruction:
        task_id += "-retry"

    abs_target_dir = os.path.abspath(target_dir)

    # Phase-level resume: if a phase.json checkpoint exists from a
    # previous interrupted run of THIS exact story in THIS session,
    # pass the next unfinished phase down so the orchestrator graph
    # can skip already-completed phases. Any mismatch (different
    # session, different story, missing file) means no resume hint
    # and the mismatched file is cleared so it can't confuse later
    # stories in this run.
    resume_from_phase = ""
    ckpt = load_phase_checkpoint(abs_target_dir)
    if ckpt:
        ckpt_session = ckpt.get("session_id", "")
        ckpt_story = ckpt.get("story_id", "")
        if ckpt_session == session_id and ckpt_story == task_id:
            resume_from_phase = ckpt.get("next_phase", "") or ""
            if resume_from_phase:
                print(
                    f"    [run_story] Phase checkpoint found for {task_id}: "
                    f"resuming at {resume_from_phase}",
                )
        else:
            logger.info(
                "Stale phase checkpoint cleared (ckpt=%s/%s, current=%s/%s)",
                ckpt_session, ckpt_story, session_id, task_id,
            )
            clear_phase_checkpoint(abs_target_dir)

    compiled = build_orchestrator()

    initial_state: OrchestratorState = {
        "task_id": task_id,
        "task_description": task_description,
        "session_id": session_id,
        "context_files": [],
        "files_modified": [],
        "current_phase": "write_tests",
        "pipeline_status": "running",
        "test_cycle_count": 0,
        "ci_cycle_count": 0,
        "test_passed": False,
        "last_test_output": "",
        "last_ci_output": "",
        "has_review_issues": False,
        "review_file_path": "",
        "error_log": [],
        "error": "",
        "working_dir": abs_target_dir,
        "resume_from_phase": resume_from_phase,
    }

    try:
        result = compiled.invoke(initial_state)
        result = dict(result)
    except Exception as e:
        logger.exception("Orchestrator failed for %s: %s", task_id, e)
        result = {"pipeline_status": "failed", "error": str(e)}

    status = result.get("pipeline_status", "failed")
    files_modified = result.get("files_modified", [])

    return {
        "current_story_status": status,
        "current_story_error": result.get("error", ""),
        "current_story_failed_phase": result.get("current_phase", ""),
        "epic_files_modified": files_modified,
    }


def process_story_result_node(state: EpicState) -> dict[str, Any]:
    """Update counters and record the story result."""
    epic_num = state.get("epic_num", "")
    stories = state.get("stories", [])
    story_index = state.get("story_index", 0)
    status = state.get("current_story_status", "failed")

    story_entry = stories[story_index]
    story_id = story_entry.get("story_id", "")
    story_name = story_entry.get("story_name", "")

    stories_completed = state.get("stories_completed", 0)
    stories_failed = state.get("stories_failed", 0)

    if status == "completed":
        stories_completed += 1
    else:
        stories_failed += 1

    # Duration accounting: wall_seconds = total elapsed since select_story_node
    # captured the start time; sleep_seconds = time spent in rate-limit auto-
    # retry waits during this story; work_seconds = wall - sleep, which is
    # what we judge "slow" against. A story that took 2.5h wall time but
    # 30 min of work (because a 2h rate-limit window opened mid-story) is
    # not actually slow — the auto-retry handled it correctly. Without this
    # subtraction, every rate-limit hit would show as a slow-story flag.
    start_time = state.get("current_story_start_time", 0.0)
    sleep_seconds = get_rate_limit_sleep_seconds()
    if start_time > 0:
        wall_seconds = max(0.0, time.time() - start_time)
        work_seconds = max(0.0, wall_seconds - sleep_seconds)
    else:
        # Resume case: start_time wasn't set in this process. Fall back to
        # zero so we don't emit nonsense numbers (a fresh "now" minus 1970
        # would dwarf any real story).
        wall_seconds = 0.0
        work_seconds = 0.0
    is_slow = (
        status == "completed"
        and work_seconds > SLOW_STORY_WORK_SECONDS
    )

    result_entry: dict[str, Any] = {
        "epic": epic_num,
        "story": story_id,
        "story_name": story_name,
        "status": status,
        "interventions": 0,
        "wall_seconds": int(wall_seconds),
        "sleep_seconds": int(sleep_seconds),
        "work_seconds": int(work_seconds),
    }

    duration_summary = (
        f"work {int(work_seconds // 60)}m"
        + (f" (+ {int(sleep_seconds // 60)}m rate-limit sleep)" if sleep_seconds > 0 else "")
    )
    slow_flag = "  *** SLOW" if is_slow else ""
    print(
        f"\n    STORY RESULT: {story_id} ({story_name}) — {status} "
        f"[{duration_summary}]{slow_flag}",
    )
    if is_slow:
        print(
            f"    [slow-story] Story {story_id} took {int(work_seconds // 60)}m of "
            f"actual work (threshold {SLOW_STORY_WORK_SECONDS // 60}m). Likely "
            f"causes: CI-fix loop thrashing, under-specified acceptance criteria, "
            f"or context-bloat in dev_story prompt.",
        )

    global_completed = state.get("rebuild_prior_completed", 0) + stories_completed
    global_failed = state.get("rebuild_prior_failed", 0) + stories_failed
    total_interventions = (
        state.get("rebuild_prior_interventions", 0)
        + state.get("total_interventions", 0)
    )
    update_story_progress(
        state.get("session_id", ""),
        completed=global_completed,
        failed=global_failed,
        interventions=total_interventions,
        story_index=state.get("rebuild_prior_completed", 0) + story_index + 1,
        last_story_wall_seconds=int(wall_seconds),
        last_story_sleep_seconds=int(sleep_seconds),
        last_story_work_seconds=int(work_seconds),
        last_story_slow=is_slow,
    )

    updates: dict[str, Any] = {
        "story_results": [result_entry],
        "stories_completed": stories_completed,
        "stories_failed": stories_failed,
    }

    if status != "completed":
        logger.warning("Story %s (%s) failed — continuing to next story", story_id, story_name)

    # Rolling story-level checkpoint: if a hard kill happens before the
    # next story finishes, resume will skip already-completed stories.
    target_dir = state.get("target_dir", "")
    if status == "completed" and target_dir:
        epic_idx = state.get("rebuild_epic_index", 0)
        prior_completed = state.get("rebuild_prior_completed", 0)
        prior_failed = state.get("rebuild_prior_failed", 0)
        prior_interventions = state.get("rebuild_prior_interventions", 0)
        prior_results = state.get("rebuild_prior_results", [])

        all_results = prior_results + state.get("story_results", []) + [result_entry]

        resume_state = {
            "session_id": state.get("session_id", ""),
            "target_dir": target_dir,
            "resume_epic_index": epic_idx,
            "resume_story_index": story_index + 1,
            "resume_stories_completed": prior_completed + stories_completed,
            "resume_stories_failed": prior_failed + stories_failed,
            "resume_total_interventions": prior_interventions + state.get("total_interventions", 0),
            "resume_story_results": all_results,
        }
        session_file = os.path.join(target_dir, "checkpoints/session.json")
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(resume_state, f, indent=2)

    return updates


def advance_story_node(state: EpicState) -> dict[str, Any]:
    """Advance story_index to the next story."""
    return {
        "story_index": state.get("story_index", 0) + 1,
        "current_story_retry_instruction": "",
    }


def epic_paused_node(state: EpicState) -> dict[str, Any]:
    """Terminal node when a graceful pause is requested mid-epic."""
    epic_num = state.get("epic_num", "?")
    story_index = state.get("story_index", 0)
    completed = state.get("stories_completed", 0)
    total = len(state.get("stories", []))
    logger.info(
        "Epic %s paused after story %d/%d (completed: %d)",
        epic_num, story_index + 1, total, completed,
    )
    return {"epic_status": "paused"}


def epic_halt_node(state: EpicState) -> dict[str, Any]:
    """Terminal node when a story fails in an unrecoverable phase.

    Triggered by git_commit failures returning pipeline_status='failed'.
    Common causes:
      - Clean tree, dev_complete=False, and no prior 'story X-Y complete'
        commit found in git log → dev_story produced nothing (likely a
        pause-kill).
      - The actual `git commit` command failed (e.g. corrupted index,
        disk full, missing identity config).

    The specific reason lives in state['current_story_error'] and is
    printed on the line below the halt message. Pre-commit hook rejection
    no longer reaches this path: the factory commits with --no-verify;
    target-repo pre-commit hooks are for human/IDE commits only.
    """
    epic_num = state.get("epic_num", "?")
    stories = state.get("stories", [])
    story_index = state.get("story_index", 0)
    failed_phase = state.get("current_story_failed_phase", "?")
    error = state.get("current_story_error", "")

    story_entry = stories[story_index] if story_index < len(stories) else {}
    story_id = story_entry.get("story_id", "?")

    message = (
        f"Epic {epic_num} halted at story {story_id}: "
        f"phase={failed_phase} failed. "
        f"Fix the underlying issue in the target repo and resume."
    )
    logger.error(message)
    print(f"\n*** HALT: {message}")
    if error:
        print(f"    Error: {error[:500]}")

    return {
        "epic_status": "paused",
        "error": message,
    }


# ---------------------------------------------------------------------------
# Story Loop Routing
# ---------------------------------------------------------------------------


def route_after_story_result(state: EpicState) -> str:
    """Route after processing a story result.

    By default, advance to the next story — failed stories are recorded
    but never block the rest of the epic. The exception is a git_commit
    failure: that leaves the working tree dirty (dev files uncommitted)
    and would contaminate every subsequent story, so we halt the epic
    and let the operator fix the underlying issue (typically a
    pre-commit hook rejection) before resuming.
    """
    status = state.get("current_story_status", "")
    failed_phase = state.get("current_story_failed_phase", "")

    if status == "failed" and failed_phase == "git_commit":
        return "halt"

    return "next_story"


def route_next_story(state: EpicState) -> str:
    """Route to next story, epic post-processing, or pause.

    Called after advance_story_node has already incremented story_index,
    so story_index is the index of the *next* story to run.

    If a graceful pause has been requested (via Ctrl+C signal handler),
    returns "paused" instead of continuing to the next story.
    """
    if is_pause_requested():
        logger.info("Pause requested — stopping after completed story")
        return "paused"

    stories = state.get("stories", [])
    story_index = state.get("story_index", 0)

    if story_index < len(stories):
        return "more_stories"
    return "epic_done"


# ---------------------------------------------------------------------------
# Epic Post-Processing Nodes
# ---------------------------------------------------------------------------


def _ensure_epic_reviews_dir(working_dir: str | None = None) -> None:
    """Ensure the epic-reviews/ directory exists.

    Does NOT wipe existing contents — every artifact in this directory
    is named with an epic number (see :func:`_epic_artifact_path`), so
    running a later epic (or re-running an earlier one) cannot clobber
    a prior epic's output. Wiping would destroy that history.
    """
    reviews_dir = os.path.join(working_dir, EPIC_REVIEWS_DIR) if working_dir else EPIC_REVIEWS_DIR
    os.makedirs(reviews_dir, exist_ok=True)


def _reviews_path(filename: str, working_dir: str | None = None) -> str:
    reviews_dir = os.path.join(working_dir, EPIC_REVIEWS_DIR) if working_dir else EPIC_REVIEWS_DIR
    return os.path.join(reviews_dir, filename)


def _epic_artifact_path(
    template: str,
    epic_num: str | int,
    working_dir: str | None = None,
) -> str:
    """Resolve a templated epic-reviews/ filename to an absolute path.

    ``template`` must contain the ``{epic_num}`` placeholder — this is
    how every artifact in ``epic-reviews/`` ties itself to its source
    epic so a later epic's run can't overwrite it.
    """
    filename = template.format(epic_num=epic_num)
    return _reviews_path(filename, working_dir=working_dir)


def _epic_fix_plan_path(epic_num: str | int, working_dir: str | None = None) -> str:
    """Absolute path to the fix plan for a specific epic."""
    return _epic_artifact_path(EPIC_FIX_PLAN_FILENAME_TEMPLATE, epic_num, working_dir)


def _parse_fix_plan(content: str) -> tuple[bool, int]:
    """Parse an architect fix plan for the `fixes_needed` flag and the
    number of approved fixes.

    Returns (fixes_needed_flag, approved_fix_count). The flag defaults to
    True when the front matter is missing or malformed — failing loud
    rather than silently skipping fixes.
    """
    flag = True
    lines = content.splitlines()

    # YAML front matter: scan between the opening `---` and the next `---`.
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            key, sep, value = line.partition(":")
            if not sep:
                continue
            if key.strip().lower() == "fixes_needed":
                v = value.strip().lower()
                if v in ("false", "no", "0"):
                    flag = False
                elif v in ("true", "yes", "1"):
                    flag = True
                break

    # Count `### Fix …` headings inside the `## Approved Fixes` section only.
    approved_count = 0
    in_approved = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_approved = stripped.lower().startswith("## approved fixes")
            continue
        if in_approved and stripped.lower().startswith("### fix"):
            approved_count += 1

    return flag, approved_count


# Story-title patterns that mark a story as out-of-scope for epic-level
# code review.
#
# - "Spike" stories at the start of an epic are doc-only by BMAD convention
#   (see e.g. Epic 1 spec: "Story 1.1 is the doc-only Spike per brief §2.10").
#   They produce planning artifacts the reviewer doesn't need to gate on.
# - "Integration Polish" stories at the end of an epic don't add new feature
#   code — they tie the epic's stories together and stand up the operator
#   demo (Epic 1 spec: "Story 1.10 is the Integration Polish per brief §2.12").
#   Their code (Makefile glue, demo scaffolding, README updates) is already
#   covered by the per-story reviews of stories 2..N-1; including them in
#   the epic review just inflates the prompt without adding signal.
_SPIKE_TITLE_RE = re.compile(r"\bspike\b", re.IGNORECASE)
_POLISH_TITLE_RE = re.compile(r"\bintegration polish\b", re.IGNORECASE)


def _doc_only_task_ids(
    stories: list[dict[str, Any]],
    epic_num: str,
) -> set[str]:
    """Return the task_ids (e.g. {"1-1", "1-10"}) for stories whose titles
    mark them as doc-only spikes or integration-polish stories. These are
    omitted from the in-scope story list passed to the epic-level reviewer.
    """
    excluded: set[str] = set()
    for s in stories:
        name = s.get("story_name", "") or ""
        if _SPIKE_TITLE_RE.search(name) or _POLISH_TITLE_RE.search(name):
            sid = s.get("story_id", "")
            if sid:
                excluded.add(f"{epic_num}-{sid}")
    return excluded


def prepare_epic_reviews_node(state: EpicState) -> dict[str, Any]:
    """Compute the in-scope story list for epic-level review.

    Excludes doc-only spike stories (always first per BMAD methodology)
    and integration-polish stories (always last) — these are reviewed at
    most via story-level reviews; the polish story's "code" is glue and
    epic-level integration tests, which the demo run itself catches.

    We deliberately do NOT pre-compute file lists for the reviewers. The
    BMAD code-review workflow is self-driving from a story number — it
    reads the story spec, locates the dev's recorded file list, runs git
    diff against that story's commit, and verifies acceptance criteria.
    Handing it an externally-built file list duplicates that work, strips
    away the per-story context, and risks drifting from BMAD's own
    evolving review workflow.
    """
    working_dir = state.get("target_dir") or None
    epic_num = state.get("epic_num", "")
    stories = state.get("stories", [])
    _ensure_epic_reviews_dir(working_dir=working_dir)

    excluded = _doc_only_task_ids(stories, epic_num)
    in_scope: list[dict[str, str]] = []
    for s in stories:
        sid = s.get("story_id", "")
        if not sid:
            continue
        task_id = f"{epic_num}-{sid}"
        if task_id in excluded:
            continue
        in_scope.append({
            "story_id": sid,
            "story_name": s.get("story_name", ""),
            "task_id": task_id,
        })

    logger.info(
        "prepare_epic_reviews: epic=%s stories_in_scope=%d "
        "(excluded %d doc-only/polish: %s)",
        epic_num, len(in_scope), len(excluded),
        sorted(excluded) if excluded else "[]",
    )
    return {
        "epic_review_file_paths": [],
        "epic_review_stories": in_scope,
    }


def route_to_epic_reviewers(state: EpicState) -> list[Send]:
    """Fan-out to two parallel epic-level reviewers (BMAD + Claude) via Send API."""
    session_id = state.get("session_id", "")
    epic_num = state.get("epic_num", "")
    stories_to_review = state.get("epic_review_stories", [])
    working_dir = state.get("target_dir", "")

    if not stories_to_review:
        logger.warning(
            "No in-scope stories for Epic %s — skipping epic review", epic_num,
        )
        return []

    task_id = f"epic-{epic_num}-review"

    shared: dict[str, Any] = {
        "task_id": task_id,
        "session_id": session_id,
        "epic_num": epic_num,
        "stories_to_review": stories_to_review,
        "working_dir": working_dir,
    }

    return [
        Send("epic_review_node", {**shared, "reviewer_type": "bmad"}),
        Send("epic_review_node", {**shared, "reviewer_type": "claude"}),
    ]


def epic_review_node(state: EpicReviewNodeInput) -> dict[str, Any]:
    """Run a single epic-level reviewer (BMAD or Claude). Read-only.

    The node captures the agent's output and writes the review file
    itself — agents never have write access, preventing wrong-path bugs.
    """
    reviewer_type = state["reviewer_type"]
    task_id = state["task_id"]
    epic_num = state.get("epic_num", "")
    stories_to_review = state["stories_to_review"]
    working_dir = state.get("working_dir") or None

    stories_list = "\n".join(
        f"- {s['task_id']}: {s['story_name']}" for s in stories_to_review
    )
    story_ids = [s["task_id"] for s in stories_to_review]
    timestamp = datetime.now(UTC).isoformat()

    review_format = (
        f"Use this exact output format:\n\n"
        f"---\n"
        f"agent_role: reviewer\n"
        f"task_id: {task_id}\n"
        f"timestamp: {timestamp}\n"
        f"input_stories: [{', '.join(story_ids)}]\n"
        f"reviewer_type: {reviewer_type}\n"
        f"review_scope: epic\n"
        f"---\n\n"
        f"# Epic Code Review — {reviewer_type.upper()} Reviewer\n\n"
        f"## Summary\n"
        f"{{1-2 sentence overview}}\n\n"
        f"## Findings\n\n"
        f"### 1. {{Finding title}}\n"
        f"- **Story:** {{task_id}}\n"
        f"- **File:** {{relative path}}\n"
        f"- **Issue:** {{description}}\n"
        f"- **Severity:** {{critical|major|minor}}\n"
        f"- **Action:** {{recommended fix}}\n\n"
        f"Use severity levels: critical, major, minor only.\n"
        f"Output your review as your final response. Do NOT write any files."
    )

    if reviewer_type == "bmad":
        # Delegate to the bmad-code-review skill via the dev persona.
        # Intentionally minimal: do not prescribe the per-story workflow
        # (which files to read, how to diff, what gates to run). The
        # skill defines that and evolves independently — the BMAD
        # methodology owners improve the workflow on their cadence, and
        # any pre-processing we do here would race that. We just hand
        # over the story list and let the skill do its job.
        output_filename = REVIEW_BMAD_FILENAME_TEMPLATE.format(epic_num=epic_num)
        result = invoke_bmad_agent(
            bmad_agent="bmad-agent-dev",
            command=(
                f"Run the bmad-code-review skill across the following "
                f"stories from Epic {epic_num}. The skill defines the "
                f"review workflow — follow it as authored, do not "
                f"deviate.\n\n"
                f"Stories to review:\n{stories_list}\n\n"
                f"You're free to review the stories individually, in "
                f"batches, or all together. Within an epic, stories are "
                f"usually closely related; reviewing them holistically "
                f"often surfaces cross-story consistency issues (naming "
                f"drift, contract mismatches, integration gaps) that a "
                f"strict story-by-story pass would miss. Use your "
                f"judgment about how to group your review.\n\n"
                f"Consolidate findings into a single epic-level report "
                f"using the format below. Group findings by story and "
                f"add a final section for cross-story integration "
                f"issues.\n\n"
                f"{review_format}\n\n"
                f"OUTPUT HANDLING — READ CAREFULLY:\n"
                f"- Output your complete review as your FINAL message "
                f"to the console. The runtime captures your last console "
                f"output and writes it to the review file automatically. "
                f"You do NOT need to, and MUST NOT, write any file yourself.\n"
                f"- Do NOT call Write, Edit, or any other file-creation "
                f"tool. File writes are blocked in this environment.\n"
                f"- If you attempt a Write/Edit and it fails, STOP "
                f"immediately. Do NOT try workarounds like Bash heredocs, "
                f"cp, touch, printf, python, or node — they will all "
                f"fail. Proceed directly to outputting your full review "
                f"as your final console message."
            ),
            tools=TOOLS_REVIEW_READONLY,
            working_dir=working_dir,
            timeout=TIMEOUT_MEDIUM,
            model=_epic_model_for("epic_review"),
        )
    else:
        # Plain Claude review — no BMAD skill loaded, so we tell Claude
        # the same story list and ask it to do an analogous workflow per
        # story (read the story spec, find the commit, review the diff
        # against acceptance criteria) — keeping minimal prescription so
        # behavior stays comparable to the BMAD reviewer's output shape.
        output_filename = REVIEW_CLAUDE_FILENAME_TEMPLATE.format(epic_num=epic_num)
        prompt = (
            f"You are an expert code reviewer. Review the code changes for "
            f"the following Epic {epic_num} stories:\n\n"
            f"{stories_list}\n\n"
            f"You're free to review the stories individually, in batches, "
            f"or all together. Within an epic, stories are usually closely "
            f"related; reviewing them holistically often surfaces cross-"
            f"story consistency issues (naming drift, contract mismatches, "
            f"integration gaps) that a strict story-by-story pass would "
            f"miss. Use your judgment about how to group your review.\n\n"
            f"For each story you cover:\n"
            f"1. Read the story spec at "
            f"`_bmad-output/implementation-artifacts/<task_id>-<slug>.md` "
            f"(use Glob to resolve the slug if needed).\n"
            f"2. Locate the dev agent's recorded file list and the matching "
            f"commit (subject begins `story <task_id> complete`); inspect "
            f"the diff with `git show` or `git log -p --grep`.\n"
            f"3. Review against the story's acceptance criteria — verify "
            f"the goals were actually achieved, not just that the code is "
            f"well-styled. Also check for cross-story integration issues, "
            f"architectural coherence, correctness, edge cases, and "
            f"naming.\n\n"
            f"CRITICAL FIRST STEP: Read CLAUDE.md and "
            f"_bmad-output/planning-artifacts/coding-standards.md before "
            f"reviewing.\n\n"
            f"Consolidate findings into a single epic-level report. Group "
            f"findings by story and add a final section for cross-story "
            f"integration issues.\n\n"
            f"{review_format}"
        )
        result = invoke_claude_cli(
            prompt=prompt,
            tools=TOOLS_REVIEW_READONLY,
            working_dir=working_dir,
            timeout=TIMEOUT_MEDIUM,
            model=_epic_model_for("epic_review"),
            label="claude-review",
        )

    # Write the review file from captured output (agent is read-only)
    output_path = _reviews_path(output_filename, working_dir=working_dir)
    output_text = result.get("output", "")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output_text)
        logger.info("Epic %s review written to %s (%d chars)",
                     reviewer_type, output_path, len(output_text))
    except Exception:
        logger.exception("Failed to write %s review to %s", reviewer_type, output_path)

    return {"epic_review_file_paths": [output_path]}


def collect_epic_reviews_node(state: EpicState) -> dict[str, Any]:
    """Fan-in: validate both epic review files are present and substantive.

    The reviews phase is only marked complete (via phase checkpoint)
    when BOTH reviewer outputs exist and contain real content. An
    empty or near-empty file is a hard failure: re-saving the phase
    checkpoint on top of garbage would cause every future resume to
    skip past broken reviews into ``analyze_reviews``, which then
    parses nothing and trips the LLM fallback — or worse, writes
    fix plans from zero findings.

    Raises :class:`RuntimeError` when validation fails. The exception
    propagates up through ``run_epic_node`` in rebuild_graph, which
    catches it, marks the epic failed, and leaves epic-phase.json
    untouched so the next resume retries the reviews from scratch.
    """
    working_dir = state.get("target_dir") or None
    epic_num = state.get("epic_num", "")
    review_paths = [
        ("BMAD", _epic_artifact_path(REVIEW_BMAD_FILENAME_TEMPLATE, epic_num, working_dir)),
        ("Claude", _epic_artifact_path(REVIEW_CLAUDE_FILENAME_TEMPLATE, epic_num, working_dir)),
    ]
    valid_paths: list[str] = []
    problems: list[str] = []

    for reviewer, path in review_paths:
        if not os.path.exists(path):
            problems.append(f"{reviewer} review file missing: {path}")
            continue
        size = os.path.getsize(path)
        if size < REVIEW_MIN_CONTENT_CHARS:
            problems.append(
                f"{reviewer} review file too short "
                f"({size} bytes, need >= {REVIEW_MIN_CONTENT_CHARS}): {path}",
            )
            continue
        valid_paths.append(path)
        logger.info("Epic review file validated: %s (%d bytes)", path, size)

    if problems:
        message = (
            f"Epic {epic_num} review collection failed — "
            f"{len(problems)} reviewer(s) produced unusable output:\n  - "
            + "\n  - ".join(problems)
            + "\n\nThis usually means a reviewer LLM call aborted before "
            "writing its report. The epic_reviews phase checkpoint will "
            "NOT be saved; the next resume will re-run the reviews from "
            "scratch."
        )
        logger.error(message)
        raise RuntimeError(message)

    _save_epic_phase(state, "epic_reviews")
    return {"epic_review_file_paths": valid_paths}


def analyze_reviews_node(state: EpicState) -> dict[str, Any]:
    """Route reviewer findings into Category A / Category B / deferred buckets.

    Fast path: parse both review files deterministically and emit the
    three output files directly — no LLM, no re-analysis. Both the BMAD
    skill and the Claude reviewer already triage their own findings, so
    this step is clerical.

    Fallback: if the sieve can't parse either file (0 findings or an
    exception), invoke the legacy analyze-reviews agent. Belt and
    suspenders during transition.
    """
    working_dir = state.get("target_dir") or None
    review_paths = state.get("epic_review_file_paths", [])
    epic_num = state.get("epic_num", "")

    analysis_path = _epic_artifact_path(ANALYSIS_FILENAME_TEMPLATE, epic_num, working_dir)
    cat_a_path = _epic_artifact_path(CATEGORY_A_PLAN_FILENAME_TEMPLATE, epic_num, working_dir)
    cat_b_path = _epic_artifact_path(CATEGORY_B_REVIEW_FILENAME_TEMPLATE, epic_num, working_dir)

    bmad_path = _epic_artifact_path(REVIEW_BMAD_FILENAME_TEMPLATE, epic_num, working_dir)
    claude_path = _epic_artifact_path(REVIEW_CLAUDE_FILENAME_TEMPLATE, epic_num, working_dir)

    sieve_result = _run_review_sieve(
        bmad_path=bmad_path,
        claude_path=claude_path,
        epic_num=epic_num,
        analysis_path=analysis_path,
        cat_a_path=cat_a_path,
        cat_b_path=cat_b_path,
        working_dir=working_dir,
    )

    if sieve_result is not None:
        logger.info(
            "Review sieve: bmad=%d claude=%d cat_a=%d cat_b=%d defer=%d",
            len(sieve_result.bmad_findings),
            len(sieve_result.claude_findings),
            len(sieve_result.cat_a),
            len(sieve_result.cat_b),
            len(sieve_result.defer),
        )
        _save_epic_phase(state, "epic_analysis")
        return {
            "analysis_path": analysis_path,
            "category_a_fix_plan_path": cat_a_path,
            "category_b_review_path": cat_b_path,
            "has_category_b_items": bool(sieve_result.cat_b),
        }

    logger.warning(
        "Review sieve produced no findings — falling back to analyze-reviews agent",
    )
    fallback_result = _analyze_reviews_agent_fallback(
        review_paths=review_paths,
        analysis_path=analysis_path,
        cat_a_path=cat_a_path,
        cat_b_path=cat_b_path,
        working_dir=working_dir,
    )
    _save_epic_phase(state, "epic_analysis")
    return fallback_result


def _run_review_sieve(
    bmad_path: str,
    claude_path: str,
    epic_num: str,
    analysis_path: str,
    cat_a_path: str,
    cat_b_path: str,
    working_dir: str | None,
) -> SieveResult | None:
    """Run the deterministic sieve. Returns None when the caller should fall back."""
    try:
        with open(bmad_path, encoding="utf-8") as f:
            bmad_content = f.read()
    except Exception:
        logger.exception("Failed to read BMAD review file at %s", bmad_path)
        return None

    try:
        with open(claude_path, encoding="utf-8") as f:
            claude_content = f.read()
    except Exception:
        logger.exception("Failed to read Claude review file at %s", claude_path)
        return None

    result = sieve_reviews(bmad_content, claude_content)

    # Fallback guard: if either reviewer's file is substantial but the
    # sieve parsed zero findings from it, the format probably drifted.
    # Return None so the caller falls back to the LLM agent — safer than
    # proceeding with half-parsed results. Threshold matches
    # collect_epic_reviews_node's validation so both layers reason about
    # "real review vs empty stub" the same way.
    if len(bmad_content.strip()) > REVIEW_MIN_CONTENT_CHARS and not result.bmad_findings:
        logger.warning(
            "BMAD review is %d chars but sieve parsed 0 findings — "
            "format drift suspected, triggering LLM fallback",
            len(bmad_content),
        )
        return None
    if len(claude_content.strip()) > REVIEW_MIN_CONTENT_CHARS and not result.claude_findings:
        logger.warning(
            "Claude review is %d chars but sieve parsed 0 findings — "
            "format drift suspected, triggering LLM fallback",
            len(claude_content),
        )
        return None

    if not result.has_any_findings:
        return None

    cat_a_body = render_category_file(
        "Category A Fix Plan",
        epic_num,
        result.cat_a,
        empty_sentinel="No Category A items found.",
    )
    cat_b_body = render_category_file(
        "Category B — Architect Review",
        epic_num,
        result.cat_b,
        empty_sentinel="No Category B items found.",
    )
    analysis_body = render_analysis_file(
        epic_num, result, bmad_path, claude_path,
    )

    try:
        with open(cat_a_path, "w", encoding="utf-8") as f:
            f.write(cat_a_body)
        with open(cat_b_path, "w", encoding="utf-8") as f:
            f.write(cat_b_body)
        with open(analysis_path, "w", encoding="utf-8") as f:
            f.write(analysis_body)
    except Exception:
        logger.exception("Sieve failed to write category files")
        return None

    if result.defer:
        deferred_path = os.path.join(
            working_dir or ".", DEFERRED_WORK_RELATIVE_PATH,
        )
        try:
            append_deferred_work(deferred_path, epic_num, result.defer)
            logger.info(
                "Appended %d deferred items to %s", len(result.defer), deferred_path,
            )
        except Exception:
            logger.exception("Failed to append deferred items to %s", deferred_path)

    return result


def _analyze_reviews_agent_fallback(
    review_paths: list[str],
    analysis_path: str,
    cat_a_path: str,
    cat_b_path: str,
    working_dir: str | None,
) -> dict[str, Any]:
    """Legacy LLM-powered analyze-reviews agent, used only when the sieve fails."""
    review_files_str = ", ".join(f"`{p}`" for p in review_paths)

    prompt = (
        f"You are a code review analyst. Your job is to compare, deduplicate, "
        f"and classify review findings from two independent reviewers.\n\n"
        f"STEPS:\n"
        f"1. Read the review files: {review_files_str}\n"
        f"2. Create an agreement analysis:\n"
        f"   - What issues each reviewer caught\n"
        f"   - Which issues both reviewers agree on (higher confidence)\n"
        f"   - Unique findings per reviewer\n"
        f"   - Agreement rate\n"
        f"3. Deduplicate — merge equivalent findings across reviewers\n"
        f"4. Classify every unique finding as:\n"
        f"   - **Category A** (Clear Fix): Unambiguous, single correct fix, "
        f"no architectural decisions needed. Examples: typos, missing imports, "
        f"style violations, obvious bugs.\n"
        f"   - **Category B** (Architect Review): Multiple valid approaches, "
        f"security implications, API changes, cross-epic impact, design decisions.\n\n"
        f"5. Write THREE output files:\n\n"
        f"   File 1: `{analysis_path}`\n"
        f"   Full comparison table, agreement rate, all findings with classification.\n\n"
        f"   File 2: `{cat_a_path}`\n"
        f"   Category A issues only, with specific fix instructions for each.\n"
        f"   If there are NO Category A items, write a file with just:\n"
        f"   `No Category A items found.`\n\n"
        f"   File 3: `{cat_b_path}`\n"
        f"   Category B issues only, with context for architect review.\n"
        f"   If there are NO Category B items, write a file with just:\n"
        f"   `No Category B items found.`\n\n"
        f"Use Write tool to create these files. Do NOT modify any source code."
    )

    analyze_tools = "Read,Write,Glob,Grep,Task,TodoWrite"

    result = invoke_claude_cli(
        prompt=prompt,
        tools=analyze_tools,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        model=_epic_model_for("epic_analysis"),
        label="analyze-reviews",
    )

    logger.info("Review analysis (fallback agent) completed: success=%s", result.get("success"))

    has_cat_b = False
    if os.path.exists(cat_b_path):
        try:
            with open(cat_b_path, encoding="utf-8") as f:
                content = f.read()
            has_cat_b = (
                len(content.strip()) > 0
                and "no category b" not in content.lower()
            )
        except Exception:
            pass

    return {
        "analysis_path": analysis_path,
        "category_a_fix_plan_path": cat_a_path,
        "category_b_review_path": cat_b_path,
        "has_category_b_items": has_cat_b,
    }


def fix_category_a_node(state: EpicState) -> dict[str, Any]:
    """Apply Category A (obvious) fixes immediately via dev agent.

    Any fix that can't be applied cleanly gets appended to the
    Category B file for architect review.
    """
    working_dir = state.get("target_dir") or None
    epic_num = state.get("epic_num", "")
    cat_a_path = state.get(
        "category_a_fix_plan_path",
        _epic_artifact_path(CATEGORY_A_PLAN_FILENAME_TEMPLATE, epic_num, working_dir),
    )
    cat_b_path = state.get(
        "category_b_review_path",
        _epic_artifact_path(CATEGORY_B_REVIEW_FILENAME_TEMPLATE, epic_num, working_dir),
    )
    done_path = _epic_artifact_path(CATEGORY_A_DONE_FILENAME_TEMPLATE, epic_num, working_dir)

    # Skip if no Category A plan exists or is empty
    if not os.path.exists(cat_a_path):
        logger.info("No Category A fix plan found — skipping")
        _save_epic_phase(state, "epic_category_a")
        return {"category_a_fixes_applied": False}

    try:
        with open(cat_a_path, encoding="utf-8") as f:
            cat_a_content = f.read()
        if "no category a" in cat_a_content.lower():
            logger.info("No Category A items — skipping")
            _save_epic_phase(state, "epic_category_a")
            return {"category_a_fixes_applied": False}
    except Exception:
        _save_epic_phase(state, "epic_category_a")
        return {"category_a_fixes_applied": False}

    prompt = (
        f"You are a dev agent applying pre-approved code fixes.\n\n"
        f"CRITICAL FIRST STEP: Read CLAUDE.md and "
        f"_bmad-output/planning-artifacts/coding-standards.md.\n\n"
        f"FILE EDITING RULES:\n"
        f"- Use the Edit tool for all file modifications. It handles every "
        f"path, including paths with brackets like `[projectId]`.\n"
        f"- If Edit returns an error (e.g. old_string not found or not "
        f"unique), the file has likely changed since you last read it. "
        f"Re-Read the file, then retry Edit with the fresh content.\n"
        f"- Never shell out to edit files (no sed/tee/cat/powershell/node "
        f"writes). Always Edit or Write.\n\n"
        f"1. Read the fix plan at `{cat_a_path}`\n"
        f"2. Apply each fix precisely as described\n"
        f"3. If any fix CANNOT be applied cleanly (ambiguous, file changed, "
        f"multiple valid approaches), DO NOT attempt it — instead append it "
        f"to `{cat_b_path}` for architect review\n"
        f"4. Verify by running ONLY the specific test files you changed "
        f"(e.g. `npx vitest run src/path/to/file.test.ts`). Do NOT run "
        f"the full test suite — the pipeline runs full CI separately. "
        f"If a test times out, report it and move on.\n"
        f"5. Write an execution log to `{done_path}` listing each fix "
        f"attempted and its outcome (applied/skipped)\n"
    )

    result = invoke_claude_cli(
        prompt=prompt,
        tools=TOOLS_DEV,
        working_dir=working_dir,
        timeout=TIMEOUT_LONG,
        model=_epic_model_for("epic_fix_cat_a"),
        label="fix-cat-a",
    )

    logger.info("Category A fixes completed: success=%s", result.get("success"))

    # Re-check if Category B items changed (fixes may have been appended)
    has_cat_b = state.get("has_category_b_items", False)
    if os.path.exists(cat_b_path):
        try:
            with open(cat_b_path, encoding="utf-8") as f:
                content = f.read()
            has_cat_b = (
                len(content.strip()) > 0
                and "no category b" not in content.lower()
            )
        except Exception:
            pass

    _save_epic_phase(state, "epic_category_a")
    return {
        "category_a_fixes_applied": True,
        "has_category_b_items": has_cat_b,
        "epic_files_modified": result.get("files_modified", []),
    }


def route_after_category_a(state: EpicState) -> str:
    """Route after Category A fixes: to architect if Category B items exist."""
    if state.get("has_category_b_items", False):
        return "has_category_b"
    return "no_category_b"


def epic_architect_node(state: EpicState) -> dict[str, Any]:
    """Architect reviews Category B items and produces fix plan.

    Invoked via Claude CLI with --model for explicit model control.
    Also performs recurring pattern detection and CLAUDE.md updates.
    """
    epic_num = state.get("epic_num", "")
    epic_name = state.get("epic_name", "")
    cat_b_path = state.get(
        "category_b_review_path",
        _epic_artifact_path(
            CATEGORY_B_REVIEW_FILENAME_TEMPLATE, epic_num, state.get("target_dir"),
        ),
    )
    working_dir = state.get("target_dir") or None
    timestamp = datetime.now(UTC).isoformat()

    task_id = f"epic-{epic_num}-architect"
    fix_plan_full = _epic_fix_plan_path(epic_num, working_dir)

    prompt = (
        f"You are the architect for Epic {epic_num} ({epic_name}).\n\n"
        f"CRITICAL FIRST STEP: Read the project coding rules before evaluating:\n"
        f"- CLAUDE.md (project root)\n"
        f"- _bmad-output/planning-artifacts/coding-standards.md\n"
        f"- Every file under `lessons-learned/*.md` — these are auto-captured "
        f"lessons from this build's multi-cycle CI failures. Each one documents "
        f"a specific incident the dev agent had to recover from. They are "
        f"raw material for your recurring-pattern detection step (see step 5 "
        f"below). When you find a recurring pattern in the lessons, the rule "
        f"you append to CLAUDE.md should reference the matching lesson file "
        f"by name (e.g. \"see lessons-learned/006-...md\").\n\n"
        f"1. Read the Category B review items at `{cat_b_path}`\n"
        f"2. Read the source files mentioned in findings\n"
        f"3. For each finding: decide **fix** (with specific instructions) or "
        f"**dismiss** (with rationale)\n"
        f"4. Write a structured fix plan to `{fix_plan_full}` using this format:\n\n"
        f"```\n"
        f"---\n"
        f"agent_role: architect\n"
        f"task_id: {task_id}\n"
        f"timestamp: {timestamp}\n"
        f"input_files: [{cat_b_path}]\n"
        f"review_scope: epic\n"
        f"fixes_needed: true/false\n"
        f"---\n\n"
        f"# Epic Fix Plan\n\n"
        f"## Summary\n"
        f"{{overview: N findings reviewed, M approved for fix, K dismissed}}\n\n"
        f"## Approved Fixes\n\n"
        f"### Fix 1: {{title}}\n"
        f"- **Severity:** {{critical|major|minor}}\n"
        f"- **File:** {{path}}\n"
        f"- **Justification:** {{why this should be fixed}}\n"
        f"- **Fix Instructions:** {{specific, actionable steps}}\n\n"
        f"## Dismissed Findings\n\n"
        f"### Dismissed 1: {{title}}\n"
        f"- **Justification:** {{why dismissed}}\n"
        f"```\n\n"
        f"If there are NO fixes needed, set `fixes_needed: false` and leave "
        f"the Approved Fixes section empty.\n\n"
        f"5. RECURRING PATTERN DETECTION: Look across (a) ALL Category B "
        f"findings AND (b) every lesson under `lessons-learned/*.md` for "
        f"patterns indicating agents are making the same mistakes repeatedly.\n\n"
        f"If you identify recurring patterns (seen in 2+ stories OR explicitly "
        f"flagged by an existing lesson's Prevention Rules section), append "
        f"new rules to CLAUDE.md under `## Agent Coding Rules` (create section "
        f"if needed). Each rule: one actionable sentence, specific enough for "
        f"an agent to follow. When the rule is the consolidation of a "
        f"specific lesson, end the rule with `(see lessons-learned/<file>.md)` "
        f"so future readers can find the forensic record. Do NOT duplicate "
        f"existing rules in CLAUDE.md or coding-standards.md.\n"
    )

    # Architect tools: can read everything, write fix plan + CLAUDE.md
    architect_tools = "Read,Write,Edit,Glob,Grep,Task,TodoWrite"

    result = invoke_claude_cli(
        prompt=prompt,
        tools=architect_tools,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        model=_epic_model_for("epic_architect"),
        label="architect",
    )

    logger.info("Epic Architect completed: success=%s", result.get("success"))

    # Decide whether the fix node should run. Skip only if BOTH signals
    # agree there's nothing to do: the front-matter flag AND the approved
    # fix count. Either signal saying "work remains" routes to fix_node.
    fixes_needed = True
    if os.path.exists(fix_plan_full):
        try:
            with open(fix_plan_full, encoding="utf-8") as f:
                content = f.read()
            flag, approved_count = _parse_fix_plan(content)
            fixes_needed = flag and approved_count > 0
            logger.info(
                "Epic %s fix plan parsed: flag=%s approved_fixes=%d -> fixes_needed=%s",
                epic_num, flag, approved_count, fixes_needed,
            )
        except Exception:
            logger.exception("Failed to parse fix plan at %s", fix_plan_full)
    else:
        logger.warning("Architect did not write fix plan at %s", fix_plan_full)

    _save_epic_phase(state, "epic_architect")
    return {
        "epic_fix_plan_path": fix_plan_full,
        "epic_fixes_needed": fixes_needed,
    }


def route_after_epic_architect(state: EpicState) -> str:
    """Route: skip fix cycle if no fixes needed."""
    if state.get("epic_fixes_needed", False):
        return "needs_fix"
    return "no_fix"


def epic_fix_node(state: EpicState) -> dict[str, Any]:
    """Apply architect-approved fixes via dev agent (Claude CLI)."""
    epic_num = state.get("epic_num", "")
    working_dir = state.get("target_dir") or None
    fix_plan_path = (
        state.get("epic_fix_plan_path")
        or _epic_fix_plan_path(epic_num, working_dir)
    )
    epic_fix_cycle = state.get("epic_fix_cycle", 0)
    last_output = state.get("epic_last_ci_output", "")

    prompt = (
        f"You are a dev agent applying architect-approved fixes.\n\n"
        f"CRITICAL FIRST STEP: Read CLAUDE.md and "
        f"_bmad-output/planning-artifacts/coding-standards.md.\n\n"
        f"FILE EDITING RULES:\n"
        f"- Use the Edit tool for all file modifications. It handles every "
        f"path, including paths with brackets like `[projectId]`.\n"
        f"- If Edit returns an error (e.g. old_string not found or not "
        f"unique), the file has likely changed since you last read it. "
        f"Re-Read the file, then retry Edit with the fresh content.\n"
        f"- Never shell out to edit files (no sed/tee/cat/powershell/node "
        f"writes). Always Edit or Write.\n\n"
        f"1. Read the fix plan at `{fix_plan_path}`\n"
        f"2. For each approved fix: read the target file, make the surgical edit, verify\n"
        f"3. Do NOT attempt any fixes not in the plan — scope discipline is critical\n"
        f"4. Verify by running ONLY the specific test files you changed "
        f"(e.g. `npx vitest run src/path/to/file.test.ts`). Do NOT run "
        f"the full test suite — the pipeline runs full CI separately. "
        f"If a test times out, report it and move on.\n"
    )

    if epic_fix_cycle > 0 and last_output:
        prompt += (
            f"\nThis is fix cycle {epic_fix_cycle + 1}. Previous CI output:\n"
            f"```\n{last_output[:3000]}\n```\n"
            f"Focus on fixing the failures.\n"
        )

    result = invoke_claude_cli(
        prompt=prompt,
        tools=TOOLS_DEV,
        working_dir=working_dir,
        timeout=TIMEOUT_LONG,
        model=_epic_model_for("epic_fix_dev"),
        label="fix-architect",
    )

    logger.info("Epic Fix Dev completed: success=%s", result.get("success"))

    _save_epic_phase(state, "epic_fix")
    return {
        "epic_files_modified": result.get("files_modified", []),
    }


def epic_ci_node(state: EpicState) -> dict[str, Any]:
    """Run full CI with auto-fix retry loop (up to 4 attempts).

    Uses resolve_ci_command() with no story_id so the full CI pipeline
    runs (lint + typecheck + all tests), not just the test suite.
    """
    working_dir = state.get("target_dir") or None
    session_id = state.get("session_id", "")

    # Pre-CI: ensure migrations are up to date
    _ensure_migrations(working_dir)

    # Full CI (no story scoping) via the same fallback chain as per-story
    ci_command = resolve_ci_command(working_dir, story_id=None)

    epic_num = state.get("epic_num", "")
    result = invoke_ci_with_fix(
        ci_command=ci_command,
        working_dir=working_dir,
        max_attempts=4,
        scope_hint=f"epic {epic_num}" if epic_num else "",
        fix_pre_existing=get_fix_pre_existing(),
    )

    passed = result.get("passed", False)
    audit = get_logger(session_id)
    if audit:
        audit.log_bash(
            f"epic CI ({result.get('attempts', 0)} attempts)",
            "PASS" if passed else "FAIL",
        )

    if passed:
        _save_epic_phase(state, "epic_ci")

    return {
        "epic_test_passed": passed,
        "epic_last_ci_output": result.get("ci_output", ""),
        "epic_files_modified": result.get("files_modified", []),
    }


def epic_git_commit_node(state: EpicState) -> dict[str, Any]:
    """Git add + commit for the completed epic."""
    epic_num = state.get("epic_num", "")
    working_dir = state.get("target_dir") or None
    session_id = state.get("session_id", "")
    message = f"epic {epic_num} code review fixes"

    cwd = working_dir or "."

    # Remove stale index.lock
    lock_file = os.path.join(cwd, ".git", "index.lock")
    if os.path.exists(lock_file):
        logger.warning("Removing stale git index.lock")
        os.remove(lock_file)

    # Auto-format before commit to avoid CI churn from prettier failures
    if _detect_project_type(working_dir) == "node":
        fmt_ok, fmt_out = _run_bash(
            ["npx", "prettier", "--write", "."], cwd=working_dir, timeout=120,
        )
        if fmt_ok:
            print("    [epic_git_commit] prettier --write applied")
        else:
            logger.warning("prettier --write failed (non-blocking): %s", fmt_out[:200])

    commit_ok, commit_out = _run_bash(["git", "add", "-A"], cwd=working_dir)
    if commit_ok:
        # --no-verify skips target-repo pre-commit hooks; factory's run_ci with
        # fix_ci retry is the enforcement layer. Hooks exist for human/IDE commits.
        commit_ok, commit_out = _run_bash(
            ["git", "commit", "--no-verify", "-m", message], cwd=working_dir
        )

    audit = get_logger(session_id)
    if audit:
        audit.log_bash("git commit (epic)", "PASS" if commit_ok else "FAIL")

    if not commit_ok:
        logger.warning("Epic git commit failed: %s", commit_out[:200])

    if commit_ok:
        _save_epic_phase(state, "epic_git_commit")

    return {}


def route_after_epic_ci(state: EpicState) -> str:
    """Route after epic CI: pass → commit, fail → error."""
    if state.get("epic_test_passed", False):
        return "pass"
    return "error"


# Map of resume-phase name → target node in the epic graph. Jumping to
# a node also skips every earlier phase (including the story loop).
# "epic_reviews" is deliberately absent — the reviews phase includes
# parallel fan-out/fan-in that's hard to resume mid-flight, so a
# checkpoint at that phase just means "reviews were being collected."
# The safest resume target for that state is analyze_reviews (the
# review files on disk are the only durable artifact).
_EPIC_RESUME_TARGETS = {
    "epic_analysis": "analyze_reviews",
    "epic_category_a": "fix_category_a",
    "epic_architect": "epic_architect",
    "epic_fix": "epic_fix",
    "epic_ci": "epic_ci",
    "epic_git_commit": "epic_git_commit",
}


def _save_epic_phase(state: EpicState, phase: str) -> None:
    """Save an epic phase-level checkpoint after successful completion."""
    session_id = state.get("session_id", "")
    epic_num = state.get("epic_num", "")
    working_dir = state.get("target_dir") or "."
    if session_id and epic_num:
        save_epic_phase_checkpoint(session_id, working_dir, epic_num, phase)


def route_on_epic_entry(state: EpicState) -> str:
    """Route from START based on any epic-phase resume hint.

    When run_epic_node loaded a matching epic-phase.json, it sets
    resume_from_epic_phase to the next phase to run. Jump directly
    to the corresponding node, bypassing the story loop and any
    earlier post-processing phases.

    When no phase hint is present, check whether the incoming
    story_index is already past the end of the stories list — the
    save-side writes ``story_index + 1`` after every story, so a
    session paused immediately after the last story of an epic
    comes back with story_index == len(stories). Entering
    select_story in that state crashes on ``stories[story_index]``
    (IndexError). Route to prepare_epic_reviews instead: the story
    loop is already complete, post-processing either never started
    or wasn't saved, and re-running it is the correct recovery.

    Fall through to select_story for the normal entry.
    """
    phase = state.get("resume_from_epic_phase", "")
    target = _EPIC_RESUME_TARGETS.get(phase)
    if target:
        print(f"\n>>> [route_on_epic_entry] Epic phase-resume: jumping to {target}")
        return target

    stories = state.get("stories", [])
    story_index = state.get("story_index", 0)
    if stories and story_index >= len(stories):
        print(
            f"\n>>> [route_on_epic_entry] Story loop already complete "
            f"({story_index}/{len(stories)}) — jumping to prepare_epic_reviews",
        )
        return "prepare_epic_reviews"

    return "select_story"


def epic_error_node(state: EpicState) -> dict[str, Any]:
    """Mark epic as failed with error details."""
    epic_num = state.get("epic_num", "")
    last_ci = state.get("epic_last_ci_output", "")
    last_test = state.get("epic_last_test_output", "")

    error = (
        f"Epic {epic_num} post-processing failed.\n"
        f"Last CI output: {last_ci[:2000]}\n"
        f"Last test output: {last_test[:2000]}"
    )

    logger.error("Epic post-processing failed: Epic %s", epic_num)

    return {
        "epic_status": "failed",
        "error": error,
    }


def epic_complete_node(state: EpicState) -> dict[str, Any]:
    """Mark epic as completed."""
    working_dir = state.get("target_dir") or "."
    clear_epic_phase_checkpoint(working_dir)
    return {"epic_status": "completed"}


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------


def build_epic_graph() -> StateGraph:  # type: ignore[type-arg]
    """Build the epic-level graph (Level 2).

    Story loop:
    select_story → run_story → process_result → route
        → (failed) → END (aborted)
        → (success) → advance_story → route
            → more_stories → select_story
            → epic_done → prepare_epic_reviews

    Epic post-processing (after all stories):
    prepare_epic_reviews → epic_review (×2 parallel, BMAD + Claude) →
    collect_epic_reviews → analyze_reviews → fix_category_a → route
        → has_category_b → epic_architect → route
            → needs_fix → epic_fix → epic_ci → route
                → pass → epic_git_commit → epic_complete → END
                → error → epic_error → END
            → no_fix → epic_ci
        → no_category_b → epic_ci

    Returns:
        Uncompiled StateGraph.
    """
    graph = StateGraph(EpicState)

    # --- Story loop nodes ---
    graph.add_node("select_story", select_story_node)
    graph.add_node("run_story", run_story_node)
    graph.add_node("process_result", process_story_result_node)
    graph.add_node("advance_story", advance_story_node)
    graph.add_node("epic_paused", epic_paused_node)
    graph.add_node("epic_halt", epic_halt_node)

    # --- Epic post-processing nodes ---
    graph.add_node("prepare_epic_reviews", prepare_epic_reviews_node)
    graph.add_node("epic_review_node", epic_review_node)
    graph.add_node("collect_epic_reviews", collect_epic_reviews_node)
    graph.add_node("analyze_reviews", analyze_reviews_node)
    graph.add_node("fix_category_a", fix_category_a_node)
    graph.add_node("epic_architect", epic_architect_node)
    graph.add_node("epic_fix", epic_fix_node)
    graph.add_node("epic_ci", epic_ci_node)
    graph.add_node("epic_git_commit", epic_git_commit_node)
    graph.add_node("epic_error", epic_error_node)
    graph.add_node("epic_complete", epic_complete_node)

    # --- Story loop edges ---
    # Entry: if run_epic_node loaded a matching epic-phase.json, jump
    # directly to the next unfinished post-processing phase, skipping
    # the story loop. Or, if the incoming story_index is already past
    # the end of the stories list (the save-side writes story_index+1
    # after every story, so a session paused after the last story of
    # an epic comes back with story_index == len(stories)), skip the
    # loop and go straight to post-processing. Otherwise fall through
    # to the normal story-loop entry.
    graph.add_conditional_edges(
        START,
        route_on_epic_entry,
        {
            "select_story": "select_story",
            "prepare_epic_reviews": "prepare_epic_reviews",
            "analyze_reviews": "analyze_reviews",
            "fix_category_a": "fix_category_a",
            "epic_architect": "epic_architect",
            "epic_fix": "epic_fix",
            "epic_ci": "epic_ci",
            "epic_git_commit": "epic_git_commit",
        },
    )
    graph.add_edge("select_story", "run_story")
    graph.add_edge("run_story", "process_result")

    graph.add_conditional_edges(
        "process_result",
        route_after_story_result,
        {"next_story": "advance_story", "halt": "epic_halt"},
    )
    graph.add_edge("epic_halt", END)

    graph.add_conditional_edges(
        "advance_story",
        route_next_story,
        {
            "more_stories": "select_story",
            "epic_done": "prepare_epic_reviews",
            "paused": "epic_paused",
        },
    )
    graph.add_edge("epic_paused", END)

    # --- Epic post-processing edges ---
    # Fan-out to 2 parallel reviewers (BMAD + Claude)
    graph.add_conditional_edges("prepare_epic_reviews", route_to_epic_reviewers)
    # Fan-in
    graph.add_edge("epic_review_node", "collect_epic_reviews")
    # Analyze and classify findings
    graph.add_edge("collect_epic_reviews", "analyze_reviews")
    # Apply obvious fixes
    graph.add_edge("analyze_reviews", "fix_category_a")

    # Route after Category A: architect if Category B items exist, else CI
    graph.add_conditional_edges(
        "fix_category_a",
        route_after_category_a,
        {"has_category_b": "epic_architect", "no_category_b": "epic_ci"},
    )

    # Route after architect: fix if needed, else CI
    graph.add_conditional_edges(
        "epic_architect",
        route_after_epic_architect,
        {"needs_fix": "epic_fix", "no_fix": "epic_ci"},
    )

    graph.add_edge("epic_fix", "epic_ci")

    # Route after CI: pass → commit, fail → error
    graph.add_conditional_edges(
        "epic_ci",
        route_after_epic_ci,
        {"pass": "epic_git_commit", "error": "epic_error"},
    )

    graph.add_edge("epic_git_commit", "epic_complete")
    graph.add_edge("epic_complete", END)
    graph.add_edge("epic_error", END)

    return graph


def build_epic_runner(checkpointer: Any = None) -> CompiledStateGraph[Any]:
    """Build and compile the epic-level graph.

    Args:
        checkpointer: Optional LangGraph checkpointer for persistence.

    Returns:
        CompiledGraph ready for invocation.
    """
    graph = build_epic_graph()
    return graph.compile(checkpointer=checkpointer)

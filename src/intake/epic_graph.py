"""Epic-level graph (Level 2): story loop + epic post-processing.

Iterates through all stories in a single epic, invoking the TDD
orchestrator for each story. After all stories complete, runs
epic-level post-processing: code review across all stories,
architect decision, fix cycle, regression tests, and full CI.

Uses LangGraph interrupt() for human-in-the-loop intervention
when a story pipeline fails.
"""

from __future__ import annotations

import logging
import operator
import os
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from src.audit_log.audit import get_logger
from src.intake.pause import is_pause_requested
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
    _run_bash,
    build_orchestrator,
)

logger = logging.getLogger(__name__)

# Epic-level retry limit for fix cycle
MAX_EPIC_FIX_CYCLES = 2

# Epic-level review directories (separate from story-level)
EPIC_REVIEWS_DIR = "epic-reviews"
EPIC_FIX_PLAN_PATH = "epic-fix-plan.md"

# Review output filenames
REVIEW_BMAD_FILENAME = "epic-review-bmad.md"
REVIEW_CLAUDE_FILENAME = "epic-review-claude.md"
ANALYSIS_FILENAME = "analysis.md"
CATEGORY_A_PLAN_FILENAME = "category-a-fix-plan.md"
CATEGORY_B_REVIEW_FILENAME = "category-b-architect-review.md"
CATEGORY_A_DONE_FILENAME = "category-a-fix-done.md"


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
    current_story_retry_instruction: str  # set by intervention

    # Epic post-processing state
    epic_review_file_paths: Annotated[list[str], operator.add]
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


class EpicReviewNodeInput(TypedDict):
    """Input schema for epic-level review node via Send API."""

    reviewer_type: str  # "bmad" or "claude"
    task_id: str
    session_id: str
    files_to_review: list[str]
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

    return {
        "current_story_status": "",
        "current_story_error": "",
        "current_story_retry_instruction": "",
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

    result_entry = {
        "epic": epic_num,
        "story": story_id,
        "story_name": story_name,
        "status": status,
        "interventions": 0,
    }

    print(f"\n    STORY RESULT: {story_id} ({story_name}) — {status}")

    updates: dict[str, Any] = {
        "story_results": [result_entry],
        "stories_completed": stories_completed,
        "stories_failed": stories_failed,
    }

    if status != "completed":
        updates["epic_status"] = "aborted"
        updates["current_story_error"] = (
            f"Story {story_id} ({story_name}) failed — aborting epic and pipeline."
        )

    return updates


def handle_intervention_node(state: EpicState) -> dict[str, Any]:
    """Pause execution for human intervention using LangGraph interrupt().

    The graph checkpoints its state here. When resumed, the human's
    response determines whether to retry, skip, or abort.
    """
    epic_num = state.get("epic_num", "")
    stories = state.get("stories", [])
    story_index = state.get("story_index", 0)
    error = state.get("current_story_error", "Unknown failure")

    story_entry = stories[story_index]
    story_id = story_entry.get("story_id", "")

    # interrupt() pauses the graph and surfaces this data to the caller
    fix_instruction = interrupt({
        "type": "intervention_needed",
        "epic": epic_num,
        "story": story_id,
        "error": error,
    })

    total_interventions = state.get("total_interventions", 0) + 1

    # Process the human's response
    if fix_instruction is None:
        return {
            "epic_status": "aborted",
            "total_interventions": total_interventions,
        }

    if isinstance(fix_instruction, str) and fix_instruction.lower() == "skip":
        return {
            "total_interventions": total_interventions,
        }

    # Retry with fix instruction
    return {
        "current_story_retry_instruction": str(fix_instruction),
        "total_interventions": total_interventions,
    }


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
        epic_num, story_index, total, completed,
    )
    return {"epic_status": "paused"}


# ---------------------------------------------------------------------------
# Story Loop Routing
# ---------------------------------------------------------------------------


def route_after_story_result(state: EpicState) -> str:
    """Route after processing a story result: success → next, failure → abort.

    There is no retry or skip. A failed story likely has downstream
    dependencies, so the entire epic (and pipeline) must stop.
    """
    status = state.get("current_story_status", "failed")
    if status == "completed":
        return "next_story"
    return "aborted"


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
    """Ensure epic-reviews/ directory exists and is clean."""
    reviews_dir = os.path.join(working_dir, EPIC_REVIEWS_DIR) if working_dir else EPIC_REVIEWS_DIR
    if os.path.exists(reviews_dir):
        for entry in os.listdir(reviews_dir):
            if entry == ".gitkeep":
                continue
            entry_path = os.path.join(reviews_dir, entry)
            if os.path.isfile(entry_path):
                os.remove(entry_path)
    else:
        os.makedirs(reviews_dir, exist_ok=True)


def _reviews_path(filename: str, working_dir: str | None = None) -> str:
    reviews_dir = os.path.join(working_dir, EPIC_REVIEWS_DIR) if working_dir else EPIC_REVIEWS_DIR
    return os.path.join(reviews_dir, filename)


def prepare_epic_reviews_node(state: EpicState) -> dict[str, Any]:
    """Clean epic-reviews/ directory before spawning epic-level reviewers."""
    working_dir = state.get("target_dir") or None
    _ensure_epic_reviews_dir(working_dir=working_dir)
    return {"epic_review_file_paths": []}


def route_to_epic_reviewers(state: EpicState) -> list[Send]:
    """Fan-out to two parallel epic-level reviewers (BMAD + Claude) via Send API."""
    session_id = state.get("session_id", "")
    epic_num = state.get("epic_num", "")
    epic_files = state.get("epic_files_modified", [])
    working_dir = state.get("target_dir", "")

    unique_files = sorted(set(epic_files))

    if not unique_files:
        logger.warning("No files modified in Epic %s — skipping epic review", epic_num)
        return []

    task_id = f"epic-{epic_num}-review"

    shared: dict[str, Any] = {
        "task_id": task_id,
        "session_id": session_id,
        "files_to_review": unique_files,
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
    files_to_review = state["files_to_review"]
    working_dir = state.get("working_dir") or None

    files_list = "\n".join(f"- {f}" for f in files_to_review)
    timestamp = datetime.now(UTC).isoformat()

    review_format = (
        f"Use this exact output format:\n\n"
        f"---\n"
        f"agent_role: reviewer\n"
        f"task_id: {task_id}\n"
        f"timestamp: {timestamp}\n"
        f"input_files: [{', '.join(files_to_review)}]\n"
        f"reviewer_type: {reviewer_type}\n"
        f"review_scope: epic\n"
        f"---\n\n"
        f"# Epic Code Review — {reviewer_type.upper()} Reviewer\n\n"
        f"## Summary\n"
        f"{{1-2 sentence overview}}\n\n"
        f"## Findings\n\n"
        f"### 1. {{Finding title}}\n"
        f"- **File:** {{relative path}}\n"
        f"- **Issue:** {{description}}\n"
        f"- **Severity:** {{critical|major|minor}}\n"
        f"- **Action:** {{recommended fix}}\n\n"
        f"Use severity levels: critical, major, minor only.\n"
        f"Output your review as your final response. Do NOT write any files."
    )

    if reviewer_type == "bmad":
        # BMAD 3-layer adversarial review via bmad-code-review skill
        output_filename = REVIEW_BMAD_FILENAME
        result = invoke_bmad_agent(
            bmad_agent="bmad-code-review",
            command=(
                f"Review ALL code changes across this entire epic.\n\n"
                f"Files to review:\n{files_list}\n\n{review_format}"
            ),
            tools=TOOLS_REVIEW_READONLY,
            working_dir=working_dir,
            timeout=TIMEOUT_MEDIUM,
        )
    else:
        # Plain Claude review — integration, correctness, cross-story consistency
        output_filename = REVIEW_CLAUDE_FILENAME
        prompt = (
            f"You are an expert code reviewer. Review ALL code changes across "
            f"this entire epic for:\n"
            f"- Cross-story integration issues and inconsistencies\n"
            f"- Architectural coherence and code duplication between stories\n"
            f"- Correctness, spec violations, and edge cases\n"
            f"- Naming consistency and maintainability\n\n"
            f"CRITICAL FIRST STEP: Read CLAUDE.md and "
            f"_bmad-output/planning-artifacts/coding-standards.md before reviewing.\n\n"
            f"Files to review:\n{files_list}\n\n{review_format}"
        )
        result = invoke_claude_cli(
            prompt=prompt,
            tools=TOOLS_REVIEW_READONLY,
            working_dir=working_dir,
            timeout=TIMEOUT_MEDIUM,
            label=f"claude-review",
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
    """Fan-in: validate both epic review files exist."""
    working_dir = state.get("target_dir") or None
    review_paths = [
        _reviews_path(REVIEW_BMAD_FILENAME, working_dir=working_dir),
        _reviews_path(REVIEW_CLAUDE_FILENAME, working_dir=working_dir),
    ]
    valid_paths: list[str] = []

    for path in review_paths:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            valid_paths.append(path)
            logger.info("Epic review file validated: %s", path)
        else:
            logger.warning("Epic review file missing or empty: %s", path)

    return {"epic_review_file_paths": valid_paths}


def analyze_reviews_node(state: EpicState) -> dict[str, Any]:
    """Compare, deduplicate, and classify review findings as Category A or B.

    Invokes a dev-level Claude CLI agent to read both review files and
    produce: analysis.md, category-a-fix-plan.md, category-b-architect-review.md.
    """
    working_dir = state.get("target_dir") or None
    review_paths = state.get("epic_review_file_paths", [])
    epic_num = state.get("epic_num", "")

    analysis_path = _reviews_path(ANALYSIS_FILENAME, working_dir=working_dir)
    cat_a_path = _reviews_path(CATEGORY_A_PLAN_FILENAME, working_dir=working_dir)
    cat_b_path = _reviews_path(CATEGORY_B_REVIEW_FILENAME, working_dir=working_dir)

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

    # Analyze node uses dev-level tools for file writing but no code editing
    analyze_tools = "Read,Write,Glob,Grep,Task,TodoWrite"

    result = invoke_claude_cli(
        prompt=prompt,
        tools=analyze_tools,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        label="analyze-reviews",
    )

    logger.info("Review analysis completed: success=%s", result.get("success"))

    # Determine if Category B items exist
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
    cat_a_path = state.get(
        "category_a_fix_plan_path",
        _reviews_path(CATEGORY_A_PLAN_FILENAME, working_dir=working_dir),
    )
    cat_b_path = state.get(
        "category_b_review_path",
        _reviews_path(CATEGORY_B_REVIEW_FILENAME, working_dir=working_dir),
    )
    done_path = _reviews_path(CATEGORY_A_DONE_FILENAME, working_dir=working_dir)

    # Skip if no Category A plan exists or is empty
    if not os.path.exists(cat_a_path):
        logger.info("No Category A fix plan found — skipping")
        return {"category_a_fixes_applied": False}

    try:
        with open(cat_a_path, encoding="utf-8") as f:
            cat_a_content = f.read()
        if "no category a" in cat_a_content.lower():
            logger.info("No Category A items — skipping")
            return {"category_a_fixes_applied": False}
    except Exception:
        return {"category_a_fixes_applied": False}

    prompt = (
        f"You are a dev agent applying pre-approved code fixes.\n\n"
        f"CRITICAL FIRST STEP: Read CLAUDE.md and "
        f"_bmad-output/planning-artifacts/coding-standards.md.\n\n"
        f"1. Read the fix plan at `{cat_a_path}`\n"
        f"2. Apply each fix precisely as described\n"
        f"3. If any fix CANNOT be applied cleanly (ambiguous, file changed, "
        f"multiple valid approaches), DO NOT attempt it — instead append it "
        f"to `{cat_b_path}` for architect review\n"
        f"4. Run quick verification: `pytest` on relevant test files\n"
        f"5. Write an execution log to `{done_path}` listing each fix "
        f"attempted and its outcome (applied/skipped)\n"
    )

    result = invoke_claude_cli(
        prompt=prompt,
        tools=TOOLS_DEV,
        working_dir=working_dir,
        timeout=TIMEOUT_LONG,
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
        _reviews_path(CATEGORY_B_REVIEW_FILENAME, state.get("target_dir")),
    )
    epic_files = sorted(set(state.get("epic_files_modified", [])))
    working_dir = state.get("target_dir") or None
    timestamp = datetime.now(UTC).isoformat()

    task_id = f"epic-{epic_num}-architect"
    fix_plan_path = EPIC_FIX_PLAN_PATH
    fix_plan_full = os.path.join(working_dir, fix_plan_path) if working_dir else fix_plan_path

    prompt = (
        f"You are the architect for Epic {epic_num} ({epic_name}).\n\n"
        f"CRITICAL FIRST STEP: Read the project coding rules before evaluating:\n"
        f"- CLAUDE.md (project root)\n"
        f"- _bmad-output/planning-artifacts/coding-standards.md\n\n"
        f"1. Read the Category B review items at `{cat_b_path}`\n"
        f"2. Read the source files mentioned in findings\n"
        f"3. For each finding: decide **fix** (with specific instructions) or "
        f"**dismiss** (with rationale)\n"
        f"4. Write a structured fix plan to `{fix_plan_path}` using this format:\n\n"
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
        f"5. RECURRING PATTERN DETECTION: Look across ALL findings for patterns "
        f"that indicate agents are making the same mistakes repeatedly.\n\n"
        f"If you identify recurring patterns (seen in 2+ stories), append new "
        f"rules to CLAUDE.md under `## Agent Coding Rules` (create section if "
        f"needed). Each rule: one actionable sentence, specific enough for an "
        f"agent to follow. Do NOT duplicate existing rules in CLAUDE.md or "
        f"coding-standards.md.\n"
    )

    # Architect tools: can read everything, write fix plan + CLAUDE.md
    architect_tools = "Read,Write,Edit,Glob,Grep,Task,TodoWrite"

    result = invoke_claude_cli(
        prompt=prompt,
        tools=architect_tools,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        model="opus",
        label="architect",
    )

    logger.info("Epic Architect completed: success=%s", result.get("success"))

    # Check if fixes are needed by reading the fix plan
    fixes_needed = True
    if os.path.exists(fix_plan_full):
        try:
            with open(fix_plan_full, encoding="utf-8") as f:
                content = f.read()
            if "fixes_needed: false" in content.lower():
                fixes_needed = False
        except Exception:
            pass

    return {
        "epic_fix_plan_path": fix_plan_path,
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
    fix_plan_path = state.get("epic_fix_plan_path", EPIC_FIX_PLAN_PATH)
    epic_fix_cycle = state.get("epic_fix_cycle", 0)
    last_output = state.get("epic_last_ci_output", "")
    working_dir = state.get("target_dir") or None

    prompt = (
        f"You are a dev agent applying architect-approved fixes.\n\n"
        f"CRITICAL FIRST STEP: Read CLAUDE.md and "
        f"_bmad-output/planning-artifacts/coding-standards.md.\n\n"
        f"1. Read the fix plan at `{fix_plan_path}`\n"
        f"2. For each approved fix: read the target file, make the surgical edit, verify\n"
        f"3. Do NOT attempt any fixes not in the plan — scope discipline is critical\n"
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
        label="fix-architect",
    )

    logger.info("Epic Fix Dev completed: success=%s", result.get("success"))

    return {
        "epic_files_modified": result.get("files_modified", []),
    }


def epic_ci_node(state: EpicState) -> dict[str, Any]:
    """Run CI with auto-fix retry loop (up to 4 attempts)."""
    working_dir = state.get("target_dir") or None
    session_id = state.get("session_id", "")

    # Detect CI command: npm test if package.json, else pytest
    base = working_dir or "."
    if os.path.exists(os.path.join(base, "package.json")):
        ci_command = ["npm", "test"]
    else:
        ci_command = ["pytest", "tests/", "-v"]

    result = invoke_ci_with_fix(
        ci_command=ci_command,
        working_dir=working_dir,
        max_attempts=4,
    )

    passed = result.get("passed", False)
    audit = get_logger(session_id)
    if audit:
        audit.log_bash(
            f"epic CI ({result.get('attempts', 0)} attempts)",
            "PASS" if passed else "FAIL",
        )

    return {
        "epic_test_passed": passed,
        "epic_last_ci_output": result.get("ci_output", ""),
        "epic_files_modified": result.get("files_modified", []),
    }


def epic_git_commit_node(state: EpicState) -> dict[str, Any]:
    """Git add + commit for the completed epic."""
    epic_num = state.get("epic_num", "")
    epic_name = state.get("epic_name", "")
    working_dir = state.get("target_dir") or None
    session_id = state.get("session_id", "")
    message = f"epic {epic_num} code review fixes"

    cwd = working_dir or "."

    # Remove stale index.lock
    lock_file = os.path.join(cwd, ".git", "index.lock")
    if os.path.exists(lock_file):
        logger.warning("Removing stale git index.lock")
        os.remove(lock_file)

    commit_ok, commit_out = _run_bash(["git", "add", "-A"], cwd=working_dir)
    if commit_ok:
        commit_ok, commit_out = _run_bash(
            ["git", "commit", "-m", message], cwd=working_dir
        )

    audit = get_logger(session_id)
    if audit:
        audit.log_bash("git commit (epic)", "PASS" if commit_ok else "FAIL")

    if not commit_ok:
        logger.warning("Epic git commit failed: %s", commit_out[:200])

    return {}


def route_after_epic_ci(state: EpicState) -> str:
    """Route after epic CI: pass → commit, fail → error."""
    if state.get("epic_test_passed", False):
        return "pass"
    return "error"


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
    graph.add_edge(START, "select_story")
    graph.add_edge("select_story", "run_story")
    graph.add_edge("run_story", "process_result")

    graph.add_conditional_edges(
        "process_result",
        route_after_story_result,
        {"next_story": "advance_story", "aborted": END},
    )

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

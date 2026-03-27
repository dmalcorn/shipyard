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
from src.multi_agent.orchestrator import (
    OrchestratorState,
    _run_bash,
    _validate_review_file,
    build_orchestrator,
)
from src.multi_agent.spawn import run_sub_agent

logger = logging.getLogger(__name__)

# Epic-level retry limit for fix cycle
MAX_EPIC_FIX_CYCLES = 2

# Epic-level review directories (separate from story-level)
EPIC_REVIEWS_DIR = "epic-reviews"
EPIC_FIX_PLAN_PATH = "epic-fix-plan.md"

# Reviewer focus areas (same split as story-level but scoped to full epic)
EPIC_REVIEWER_1_FOCUS = (
    "Focus on cross-story integration issues, inconsistencies between stories, "
    "and correctness of the epic as a whole."
)
EPIC_REVIEWER_2_FOCUS = (
    "Focus on architectural coherence across all stories, code duplication "
    "between stories, naming consistency, and maintainability."
)


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

    # Control
    epic_status: str  # running|completed|failed|aborted
    error: str


class EpicReviewNodeInput(TypedDict):
    """Input schema for epic-level review node via Send API."""

    reviewer_id: int
    task_id: str
    session_id: str
    files_to_review: list[str]
    reviewer_focus: str
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
    """Route to next story or epic post-processing."""
    stories = state.get("stories", [])
    story_index = state.get("story_index", 0)

    if story_index + 1 < len(stories):
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


def _epic_review_file_path(reviewer_id: int, working_dir: str | None = None) -> str:
    reviews_dir = os.path.join(working_dir, EPIC_REVIEWS_DIR) if working_dir else EPIC_REVIEWS_DIR
    return os.path.join(reviews_dir, f"epic-review-agent-{reviewer_id}.md")


def prepare_epic_reviews_node(state: EpicState) -> dict[str, Any]:
    """Clean epic-reviews/ directory before spawning epic-level reviewers."""
    working_dir = state.get("target_dir") or None
    _ensure_epic_reviews_dir(working_dir=working_dir)
    return {"epic_review_file_paths": []}


def route_to_epic_reviewers(state: EpicState) -> list[Send]:
    """Fan-out to two parallel epic-level Review Agents via Send API."""
    session_id = state.get("session_id", "")
    epic_num = state.get("epic_num", "")
    epic_files = state.get("epic_files_modified", [])
    working_dir = state.get("target_dir", "")

    # Deduplicate files
    unique_files = sorted(set(epic_files))

    if not unique_files:
        logger.warning("No files modified in Epic %s — skipping epic review", epic_num)
        return []

    task_id = f"epic-{epic_num}-review"

    shared = EpicReviewNodeInput(
        reviewer_id=0,
        task_id=task_id,
        session_id=session_id,
        files_to_review=unique_files,
        reviewer_focus="",
        working_dir=working_dir,
    )

    return [
        Send(
            "epic_review_node",
            {**shared, "reviewer_id": 1, "reviewer_focus": EPIC_REVIEWER_1_FOCUS},
        ),
        Send(
            "epic_review_node",
            {**shared, "reviewer_id": 2, "reviewer_focus": EPIC_REVIEWER_2_FOCUS},
        ),
    ]


def epic_review_node(state: EpicReviewNodeInput) -> dict[str, Any]:
    """Spawn a Review Agent for epic-level code review."""
    reviewer_id = state["reviewer_id"]
    task_id = state["task_id"]
    session_id = state["session_id"]
    files_to_review = state["files_to_review"]
    reviewer_focus = state["reviewer_focus"]
    working_dir = state.get("working_dir") or None

    output_path = _epic_review_file_path(reviewer_id, working_dir=working_dir)
    timestamp = datetime.now(UTC).isoformat()

    task_description = (
        f"Review ALL code changes across this entire epic. {reviewer_focus}\n\n"
        f"Files to review (all stories in this epic):\n"
        + "\n".join(f"- {f}" for f in files_to_review)
        + f"\n\nCRITICAL: Write your findings to EXACTLY this path: `{output_path}`\n"
        f"Do NOT use any other path. The directory already exists.\n"
        f"Use this exact format:\n\n"
        f"```\n"
        f"---\n"
        f"agent_role: reviewer\n"
        f"task_id: {task_id}\n"
        f"timestamp: {timestamp}\n"
        f"input_files: [{', '.join(files_to_review)}]\n"
        f"reviewer_id: {reviewer_id}\n"
        f"review_scope: epic\n"
        f"---\n\n"
        f"# Epic Code Review — Agent {reviewer_id}\n\n"
        f"## Summary\n"
        f"{{1-2 sentence overview of review findings}}\n\n"
        f"## Findings\n\n"
        f"### 1. {{Finding title}}\n"
        f"- **File:** {{relative path}}\n"
        f"- **Issue:** {{description}}\n"
        f"- **Severity:** {{critical|major|minor}}\n"
        f"- **Action:** {{recommended fix}}\n"
        f"```\n\n"
        f"Use severity levels: critical, major, minor only."
    )

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="reviewer",
        task_description=task_description,
        current_phase="review",
        context_files=files_to_review,
        working_dir=working_dir,
    )

    logger.info("Epic Reviewer %d completed: %s",
                reviewer_id, result.get("final_message", "")[:100])

    return {"epic_review_file_paths": [output_path]}


def collect_epic_reviews_node(state: EpicState) -> dict[str, Any]:
    """Fan-in: validate both epic review files exist."""
    working_dir = state.get("target_dir") or None
    review_paths = [
        _epic_review_file_path(1, working_dir=working_dir),
        _epic_review_file_path(2, working_dir=working_dir),
    ]
    valid_paths: list[str] = []

    # Check expected paths, then search for files agents may have written elsewhere
    base = working_dir or "."
    alt_dirs = ["reviews", "review", "epic-review"]

    for path in review_paths:
        if _validate_review_file(path):
            valid_paths.append(path)
            logger.info("Epic review file validated: %s", path)
        else:
            # Search alternative dirs the agent might have used
            filename = os.path.basename(path)
            found = False
            for alt in alt_dirs:
                alt_path = os.path.join(base, alt, filename)
                if _validate_review_file(alt_path):
                    valid_paths.append(alt_path)
                    logger.info("Epic review file found at alt path: %s", alt_path)
                    found = True
                    break
            if not found:
                logger.warning("Epic review file missing or invalid: %s", path)

    return {"epic_review_file_paths": valid_paths}


def epic_architect_node(state: EpicState) -> dict[str, Any]:
    """Spawn Architect Agent to evaluate epic-level reviews and produce fix plan."""
    session_id = state.get("session_id", "")
    epic_num = state.get("epic_num", "")
    epic_name = state.get("epic_name", "")
    review_paths = state.get("epic_review_file_paths", [])
    epic_files = sorted(set(state.get("epic_files_modified", [])))
    working_dir = state.get("target_dir") or None
    timestamp = datetime.now(UTC).isoformat()

    task_id = f"epic-{epic_num}-architect"

    fix_plan_path = EPIC_FIX_PLAN_PATH
    fix_plan_full = os.path.join(working_dir, fix_plan_path) if working_dir else fix_plan_path

    task_description = (
        f"Evaluate the epic-level review findings and produce a fix plan.\n\n"
        f"This is an EPIC-LEVEL review covering all stories in Epic {epic_num} ({epic_name}).\n\n"
        f"CRITICAL FIRST STEP: Read the project coding rules before evaluating:\n"
        f"- CLAUDE.md (project root)\n"
        f"- _bmad-output/planning-artifacts/coding-standards.md\n\n"
        f"1. Read both review files: {review_paths}\n"
        f"2. Read the source files mentioned in findings\n"
        f"3. For each finding: decide fix or dismiss with justification\n"
        f"4. If there are NO fixes needed, write a fix plan with an empty "
        f"'Approved Fixes' section and set fixes_needed: false in frontmatter\n"
        f"5. Write a structured fix plan to `{fix_plan_path}` using this format:\n\n"
        f"```\n"
        f"---\n"
        f"agent_role: architect\n"
        f"task_id: {task_id}\n"
        f"timestamp: {timestamp}\n"
        f"input_files: {review_paths}\n"
        f"review_scope: epic\n"
        f"fixes_needed: true/false\n"
        f"---\n\n"
        f"# Epic Fix Plan\n\n"
        f"## Summary\n"
        f"{{overview: N findings reviewed, M approved for fix, K dismissed}}\n\n"
        f"## Approved Fixes\n\n"
        f"### Fix 1: {{title from finding}}\n"
        f"- **Source Finding:** Review Agent {{n}}, Finding #{{m}}\n"
        f"- **Severity:** {{critical|major|minor}}\n"
        f"- **File:** {{path}}\n"
        f"- **Justification:** {{why this should be fixed}}\n"
        f"- **Fix Instructions:** {{specific, actionable steps}}\n\n"
        f"## Dismissed Findings\n\n"
        f"### Dismissed 1: {{title from finding}}\n"
        f"- **Source Finding:** Review Agent {{n}}, Finding #{{m}}\n"
        f"- **Justification:** {{why dismissed}}\n"
        f"```\n\n"
        f"6. RECURRING PATTERN DETECTION: After completing the fix plan, look across "
        f"ALL findings for patterns that indicate agents are making the same mistakes "
        f"repeatedly. Examples: wrong import style, inconsistent naming, missing error "
        f"handling patterns, wrong test structure, ignoring project conventions.\n\n"
        f"If you identify recurring patterns, append new rules to CLAUDE.md under a "
        f"section called `## Agent Coding Rules` (create the section if it doesn't exist). "
        f"Each rule should be:\n"
        f"- One clear, actionable sentence\n"
        f"- Specific enough that an agent can follow it without judgment\n"
        f"- Referencing the pattern that triggered it (e.g., 'seen in 3/5 stories')\n\n"
        f"Only add rules for patterns seen in 2+ stories. Do NOT duplicate rules already "
        f"in CLAUDE.md or _bmad-output/planning-artifacts/coding-standards.md. "
        f"These rules persist across future epics, "
        f"so they must be general enough to apply going forward.\n"
    )

    context_files = review_paths + epic_files

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="architect",
        task_description=task_description,
        current_phase="architect",
        context_files=context_files,
        working_dir=working_dir,
    )

    logger.info("Epic Architect completed: %s", result.get("final_message", "")[:100])

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
    """Spawn Fix Dev Agent to execute epic-level fixes."""
    session_id = state.get("session_id", "")
    epic_num = state.get("epic_num", "")
    fix_plan_path = state.get("epic_fix_plan_path", EPIC_FIX_PLAN_PATH)
    epic_files = sorted(set(state.get("epic_files_modified", [])))
    epic_fix_cycle = state.get("epic_fix_cycle", 0)
    last_output = state.get("epic_last_ci_output", "")
    working_dir = state.get("target_dir") or None

    task_id = f"epic-{epic_num}-fix"

    task_description = (
        f"Execute the approved fixes from the epic-level fix plan.\n\n"
        f"1. Read the fix plan at `{fix_plan_path}`\n"
        f"2. For each approved fix: read the target file, make the surgical edit, verify\n"
        f"3. Do NOT attempt any fixes not in the plan — scope discipline is critical\n"
    )

    if epic_fix_cycle > 0 and last_output:
        task_description += (
            f"\nThis is fix cycle {epic_fix_cycle + 1}. Previous CI output:\n"
            f"```\n{last_output[:3000]}\n```\n"
            f"Focus on fixing the failures.\n"
        )

    context_files = [fix_plan_path] + epic_files

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="fix_dev",
        task_description=task_description,
        current_phase="fix",
        context_files=context_files,
        working_dir=working_dir,
    )

    logger.info("Epic Fix Dev completed: %s", result.get("final_message", "")[:100])

    return {
        "epic_files_modified": result.get("files_modified", []),
    }


def epic_post_fix_ci_node(state: EpicState) -> dict[str, Any]:
    """Run full CI after epic-level fixes."""
    session_id = state.get("session_id", "")
    working_dir = state.get("target_dir") or None
    epic_fix_cycle = state.get("epic_fix_cycle", 0) + 1

    passed, output = _run_bash(["bash", "scripts/local_ci.sh"], cwd=working_dir)

    audit = get_logger(session_id)
    if audit:
        audit.log_bash("scripts/local_ci.sh (epic post-fix)", "PASS" if passed else "FAIL")

    logger.info("Epic post-fix CI: cycle=%d passed=%s", epic_fix_cycle, passed)

    return {
        "epic_test_passed": passed,
        "epic_fix_cycle": epic_fix_cycle,
        "epic_last_ci_output": output,
    }


def route_after_epic_post_fix_ci(state: EpicState) -> str:
    """Route after epic post-fix CI: pass, retry (once), or error."""
    if state.get("epic_test_passed", False):
        return "pass"
    if state.get("epic_fix_cycle", 0) >= MAX_EPIC_FIX_CYCLES:
        return "error"
    return "retry"


def epic_regression_test_node(state: EpicState) -> dict[str, Any]:
    """Run full regression test suite after epic post-processing."""
    session_id = state.get("session_id", "")
    working_dir = state.get("target_dir") or None

    passed, output = _run_bash(["pytest", "tests/", "-v"], cwd=working_dir)

    audit = get_logger(session_id)
    if audit:
        audit.log_bash("pytest tests/ -v (epic regression)", "PASS" if passed else "FAIL")

    logger.info("Epic regression tests: passed=%s", passed)

    return {
        "epic_test_passed": passed,
        "epic_last_test_output": output,
    }


def epic_full_ci_node(state: EpicState) -> dict[str, Any]:
    """Run full CI suite as final epic gate."""
    session_id = state.get("session_id", "")
    working_dir = state.get("target_dir") or None

    passed, output = _run_bash(["bash", "scripts/local_ci.sh"], cwd=working_dir)

    audit = get_logger(session_id)
    if audit:
        audit.log_bash("scripts/local_ci.sh (epic final)", "PASS" if passed else "FAIL")

    logger.info("Epic full CI: passed=%s", passed)

    return {
        "epic_test_passed": passed,
        "epic_last_ci_output": output,
    }


def route_after_epic_final_ci(state: EpicState) -> str:
    """Route after epic final CI: pass or fail the epic."""
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
        → (failed) → handle_intervention → route
            → (retry) → run_story
            → (skip) → advance/done
            → (abort) → END
        → (success) → advance/done

    Epic post-processing (after all stories):
    prepare_epic_reviews → epic_review (×2 parallel) → collect →
    epic_architect → route
        → (needs fix) → epic_fix → epic_post_fix_ci → route
            → (pass) → regression
            → (retry) → epic_fix
            → (error) → epic_error
        → (no fix) → regression
    epic_regression_test → epic_full_ci → route
        → (pass) → epic_complete
        → (error) → epic_error

    Returns:
        Uncompiled StateGraph.
    """
    graph = StateGraph(EpicState)

    # --- Story loop nodes ---
    graph.add_node("select_story", select_story_node)
    graph.add_node("run_story", run_story_node)
    graph.add_node("process_result", process_story_result_node)
    graph.add_node("advance_story", advance_story_node)

    # --- Epic post-processing nodes ---
    graph.add_node("prepare_epic_reviews", prepare_epic_reviews_node)
    graph.add_node("epic_review_node", epic_review_node)
    graph.add_node("collect_epic_reviews", collect_epic_reviews_node)
    graph.add_node("epic_architect", epic_architect_node)
    graph.add_node("epic_fix", epic_fix_node)
    graph.add_node("epic_post_fix_ci", epic_post_fix_ci_node)
    graph.add_node("epic_regression_test", epic_regression_test_node)
    graph.add_node("epic_full_ci", epic_full_ci_node)
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

    # After advancing story index, check if more stories remain
    graph.add_conditional_edges(
        "advance_story",
        route_next_story,
        {"more_stories": "select_story", "epic_done": "prepare_epic_reviews"},
    )

    # --- Epic post-processing edges ---
    graph.add_conditional_edges("prepare_epic_reviews", route_to_epic_reviewers)
    graph.add_edge("epic_review_node", "collect_epic_reviews")
    graph.add_edge("collect_epic_reviews", "epic_architect")

    graph.add_conditional_edges(
        "epic_architect",
        route_after_epic_architect,
        {"needs_fix": "epic_fix", "no_fix": "epic_regression_test"},
    )

    graph.add_edge("epic_fix", "epic_post_fix_ci")

    graph.add_conditional_edges(
        "epic_post_fix_ci",
        route_after_epic_post_fix_ci,
        {"pass": "epic_regression_test", "retry": "epic_fix", "error": "epic_error"},
    )

    graph.add_edge("epic_regression_test", "epic_full_ci")

    graph.add_conditional_edges(
        "epic_full_ci",
        route_after_epic_final_ci,
        {"pass": "epic_complete", "error": "epic_error"},
    )

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

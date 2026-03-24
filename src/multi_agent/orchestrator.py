"""Full TDD orchestrator pipeline (Story 3.5).

Assembles the complete pipeline as a parent StateGraph:
Test Agent → Dev Agent → unit tests → CI → git snapshot →
2 Review Agents (parallel via Send) → Architect → Fix Dev →
unit tests → CI → system tests → final CI → git push.

Preserves the review/architect/fix pipeline from Stories 3.3-3.4.
Bash nodes (tests, CI, git) execute shell commands — no LLM invocation.
"""

from __future__ import annotations

import logging
import operator
import os
import subprocess
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.logging.audit import get_logger
from src.multi_agent.spawn import run_sub_agent

logger = logging.getLogger(__name__)

REVIEWS_DIR = "reviews"
FIX_PLAN_PATH = "fix-plan.md"

# Retry limits (Decision 4 from architecture doc)
MAX_EDIT_RETRIES = 3
MAX_TEST_CYCLES = 5
MAX_CI_CYCLES = 3

# Reviewer focus area prompts
REVIEWER_1_FOCUS = "Focus on correctness, logic errors, missing edge cases, and test coverage gaps."
REVIEWER_2_FOCUS = (
    "Focus on code style, architectural patterns, naming conventions, and maintainability."
)


# ---------------------------------------------------------------------------
# State Schemas
# ---------------------------------------------------------------------------


class OrchestratorState(TypedDict, total=False):
    """State schema for the full TDD orchestrator pipeline.

    Extends the original review-only state with pipeline-wide fields
    for the complete Test → Dev → CI → Review → Fix → Push flow.
    """

    # Task identity
    task_id: str
    task_description: str
    session_id: str

    # File tracking
    context_files: list[str]
    source_files: list[str]
    test_files: list[str]
    files_modified: Annotated[list[str], operator.add]

    # Pipeline phase tracking
    current_phase: str  # test|dev|unit_test|ci|git_snapshot|review|architect|fix|system_test|push
    pipeline_status: str  # running|completed|failed

    # Review pipeline state (Story 3.3-3.4)
    review_file_paths: list[str]
    fix_plan_path: str

    # Retry counters for circuit breaking
    test_cycle_count: int
    ci_cycle_count: int
    edit_retry_count: int

    # Test/CI output for retry context
    test_passed: bool
    last_test_output: str
    last_ci_output: str

    # Error accumulation
    error_log: Annotated[list[str], operator.add]
    error: str


class ReviewNodeInput(TypedDict):
    """Input schema for a single review node invocation via Send API."""

    reviewer_id: int
    task_id: str
    session_id: str
    source_files: list[str]
    test_files: list[str]
    reviewer_focus: str


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _ensure_reviews_dir() -> None:
    """Ensure reviews/ directory exists and is clean for a new pipeline run."""
    if os.path.exists(REVIEWS_DIR):
        for entry in os.listdir(REVIEWS_DIR):
            if entry == ".gitkeep":
                continue
            entry_path = os.path.join(REVIEWS_DIR, entry)
            if os.path.isfile(entry_path):
                os.remove(entry_path)
    else:
        os.makedirs(REVIEWS_DIR, exist_ok=True)
    gitkeep = os.path.join(REVIEWS_DIR, ".gitkeep")
    if not os.path.exists(gitkeep):
        with open(gitkeep, "w") as f:
            f.write("")


def _review_file_path(reviewer_id: int) -> str:
    """Return the file path for a reviewer's output."""
    return f"{REVIEWS_DIR}/review-agent-{reviewer_id}.md"


def _validate_review_file(file_path: str) -> bool:
    """Check that a review file exists and has YAML frontmatter."""
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        return content.startswith("---")
    except Exception as e:
        logger.warning("Failed to validate review file %s: %s", file_path, e)
        return False


def _run_bash(command: list[str], timeout: int = 300) -> tuple[bool, str]:
    """Execute a shell command and return (success, output).

    This is the shared execution path for all bash-based nodes.
    No LLM invocation — just command execution and result capture.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        if len(output) > 5000:
            output = output[:5000] + f"\n(truncated, {len(output)} chars total)"
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s: {' '.join(command)}"
    except Exception as e:
        return False, f"Command execution failed: {e}"


def _log_bash_to_audit(session_id: str, script_name: str, result: str) -> None:
    """Log bash execution to audit logger if session is active."""
    audit = get_logger(session_id)
    if audit:
        audit.log_bash(script_name, result)


# ---------------------------------------------------------------------------
# LLM Agent Nodes (spawn sub-agents)
# ---------------------------------------------------------------------------


def test_agent_node(state: OrchestratorState) -> dict[str, Any]:
    """Spawn Test Agent to write failing tests from the task spec (TDD red phase)."""
    task_id = state.get("task_id", "")
    session_id = state.get("session_id", "")
    task_description = state.get("task_description", "")
    context_files = state.get("context_files", [])

    task_instruction = (
        f"Write failing tests for the following feature spec. "
        f"Follow TDD red phase — tests MUST fail initially.\n\n"
        f"Feature spec:\n{task_description}\n\n"
        f"Write tests to `tests/` following existing patterns. "
        f"Use pytest. Every acceptance criterion must have at least one test."
    )

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="test",
        task_description=task_instruction,
        current_phase="test",
        context_files=context_files,
    )

    logger.info("Test Agent completed: %s", result.get("final_message", "")[:100])

    return {
        "current_phase": "test",
        "files_modified": result.get("files_modified", []),
    }


def dev_agent_node(state: OrchestratorState) -> dict[str, Any]:
    """Spawn Dev Agent to implement code that passes the tests (TDD green phase)."""
    task_id = state.get("task_id", "")
    session_id = state.get("session_id", "")
    task_description = state.get("task_description", "")
    context_files = state.get("context_files", [])
    last_test_output = state.get("last_test_output", "")
    test_cycle = state.get("test_cycle_count", 0)

    task_instruction = (
        f"Implement code to pass the tests. "
        f"Follow TDD green phase — make tests pass with minimal implementation.\n\n"
        f"Feature spec:\n{task_description}\n\n"
        f"Read the test files first to understand what's expected, then implement."
    )

    if test_cycle > 0 and last_test_output:
        task_instruction += (
            f"\n\nThis is retry {test_cycle}. Previous test output:\n"
            f"```\n{last_test_output[:3000]}\n```\n"
            f"Fix the failing tests."
        )

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="dev",
        task_description=task_instruction,
        current_phase="implementation",
        context_files=context_files,
    )

    logger.info("Dev Agent completed: %s", result.get("final_message", "")[:100])

    return {
        "current_phase": "dev",
        "files_modified": result.get("files_modified", []),
    }


def prepare_reviews_node(state: OrchestratorState) -> dict[str, Any]:
    """Clean reviews/ directory before spawning reviewers."""
    _ensure_reviews_dir()
    return {"current_phase": "review"}


def route_to_reviewers(state: OrchestratorState) -> list[Send]:
    """Return Send objects to fan-out to two parallel Review Agent instances."""
    task_id = state.get("task_id", "")
    session_id = state.get("session_id", "")
    source_files = state.get("source_files", [])
    test_files = state.get("test_files", [])

    return [
        Send(
            "review_node",
            ReviewNodeInput(
                reviewer_id=1,
                task_id=task_id,
                session_id=session_id,
                source_files=source_files,
                test_files=test_files,
                reviewer_focus=REVIEWER_1_FOCUS,
            ),
        ),
        Send(
            "review_node",
            ReviewNodeInput(
                reviewer_id=2,
                task_id=task_id,
                session_id=session_id,
                source_files=source_files,
                test_files=test_files,
                reviewer_focus=REVIEWER_2_FOCUS,
            ),
        ),
    ]


def review_node(state: ReviewNodeInput) -> dict[str, Any]:
    """Spawn a Review Agent subgraph for a single reviewer."""
    reviewer_id = state["reviewer_id"]
    task_id = state["task_id"]
    session_id = state["session_id"]
    source_files = state.get("source_files", [])
    test_files = state.get("test_files", [])
    reviewer_focus = state["reviewer_focus"]

    output_path = _review_file_path(reviewer_id)
    files_to_review = source_files + test_files
    timestamp = datetime.now(UTC).isoformat()

    task_description = (
        f"Review the code changes. {reviewer_focus}\n\n"
        f"Write your findings to `{output_path}` using this exact format:\n\n"
        f"```\n"
        f"---\n"
        f"agent_role: reviewer\n"
        f"task_id: {task_id}\n"
        f"timestamp: {timestamp}\n"
        f"input_files: {files_to_review}\n"
        f"reviewer_id: {reviewer_id}\n"
        f"---\n\n"
        f"# Code Review — Agent {reviewer_id}\n\n"
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
    )

    logger.info("Reviewer %d completed: %s", reviewer_id, result.get("final_message", "")[:100])

    return {"review_file_paths": [output_path]}


def collect_reviews(state: OrchestratorState) -> dict[str, Any]:
    """Fan-in node: validate both review files exist and update state."""
    review_paths = [_review_file_path(1), _review_file_path(2)]
    valid_paths: list[str] = []

    for path in review_paths:
        if _validate_review_file(path):
            valid_paths.append(path)
            logger.info("Review file validated: %s", path)
        else:
            logger.warning("Review file missing or invalid: %s", path)

    if len(valid_paths) < 2:
        return {
            "review_file_paths": valid_paths,
            "error": f"Expected 2 review files, found {len(valid_paths)} valid",
        }

    return {"review_file_paths": valid_paths}


def architect_node(state: OrchestratorState) -> dict[str, Any]:
    """Spawn Architect Agent to evaluate reviews and produce a fix plan."""
    task_id = state.get("task_id", "")
    session_id = state.get("session_id", "")
    source_files = state.get("source_files", [])
    review_paths = state.get("review_file_paths", [])
    timestamp = datetime.now(UTC).isoformat()

    task_description = (
        f"Evaluate the review findings and produce a fix plan.\n\n"
        f"1. Read both review files: {review_paths}\n"
        f"2. Read the source files mentioned in findings\n"
        f"3. For each finding: decide fix or dismiss with justification\n"
        f"4. Write a structured fix plan to `{FIX_PLAN_PATH}` using this format:\n\n"
        f"```\n"
        f"---\n"
        f"agent_role: architect\n"
        f"task_id: {task_id}\n"
        f"timestamp: {timestamp}\n"
        f"input_files: {review_paths}\n"
        f"---\n\n"
        f"# Fix Plan\n\n"
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
        f"```\n"
    )

    context_files = review_paths + source_files

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="architect",
        task_description=task_description,
        current_phase="review",
        context_files=context_files,
    )

    logger.info("Architect completed: %s", result.get("final_message", "")[:100])

    return {"fix_plan_path": FIX_PLAN_PATH, "current_phase": "architect"}


def fix_dev_node(state: OrchestratorState) -> dict[str, Any]:
    """Spawn a fresh Fix Dev Agent to execute the approved fixes."""
    task_id = state.get("task_id", "")
    session_id = state.get("session_id", "")
    fix_plan_path = state.get("fix_plan_path", FIX_PLAN_PATH)
    source_files = state.get("source_files", [])
    edit_retry = state.get("edit_retry_count", 0)
    last_test_output = state.get("last_test_output", "")

    task_description = (
        f"Execute the approved fixes from the fix plan.\n\n"
        f"1. Read the fix plan at `{fix_plan_path}`\n"
        f"2. For each approved fix: read the target file, make the surgical edit, verify\n"
        f"3. Do NOT attempt any fixes not in the plan — scope discipline is critical\n"
        f"4. Run `pytest tests/ -v` after all fixes to verify correctness\n"
    )

    if edit_retry > 0 and last_test_output:
        task_description += (
            f"\nThis is fix cycle {edit_retry + 1}. Previous test output:\n"
            f"```\n{last_test_output[:3000]}\n```\n"
            f"Focus on fixing the test failures.\n"
        )

    context_files = [fix_plan_path] + source_files

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="fix_dev",
        task_description=task_description,
        current_phase="fix",
        context_files=context_files,
    )

    logger.info("Fix Dev completed: %s", result.get("final_message", "")[:100])

    return {
        "current_phase": "fix",
        "files_modified": result.get("files_modified", []),
    }


# ---------------------------------------------------------------------------
# Bash-Based Nodes (NO LLM invocation — shell commands only)
# ---------------------------------------------------------------------------


def unit_test_node(state: OrchestratorState) -> dict[str, Any]:
    """Run pytest via bash. No LLM call."""
    session_id = state.get("session_id", "")
    test_cycle = state.get("test_cycle_count", 0) + 1

    passed, output = _run_bash(["pytest", "tests/", "-v"])
    _log_bash_to_audit(session_id, "pytest tests/ -v", "PASS" if passed else "FAIL")

    logger.info("Unit tests: cycle=%d passed=%s", test_cycle, passed)

    return {
        "test_passed": passed,
        "test_cycle_count": test_cycle,
        "last_test_output": output,
        "current_phase": "unit_test",
    }


def ci_node(state: OrchestratorState) -> dict[str, Any]:
    """Run local CI (ruff + mypy + pytest) via bash. No LLM call."""
    session_id = state.get("session_id", "")
    ci_cycle = state.get("ci_cycle_count", 0) + 1

    passed, output = _run_bash(["bash", "scripts/local_ci.sh"])
    _log_bash_to_audit(session_id, "scripts/local_ci.sh", "PASS" if passed else "FAIL")

    logger.info("CI: cycle=%d passed=%s", ci_cycle, passed)

    return {
        "test_passed": passed,
        "ci_cycle_count": ci_cycle,
        "last_ci_output": output,
        "current_phase": "ci",
    }


def git_snapshot_node(state: OrchestratorState) -> dict[str, Any]:
    """Create a git snapshot commit via bash. No LLM call."""
    task_id = state.get("task_id", "")
    session_id = state.get("session_id", "")
    message = f"snapshot: {task_id} — pre-review checkpoint"

    passed, output = _run_bash(["bash", "scripts/git_snapshot.sh", message])
    _log_bash_to_audit(session_id, "scripts/git_snapshot.sh", "PASS" if passed else "FAIL")

    if not passed:
        logger.warning("Git snapshot failed: %s", output[:200])

    return {"current_phase": "git_snapshot"}


def post_fix_test_node(state: OrchestratorState) -> dict[str, Any]:
    """Run pytest after fixes. Shares logic with unit_test_node."""
    session_id = state.get("session_id", "")
    test_cycle = state.get("test_cycle_count", 0) + 1

    passed, output = _run_bash(["pytest", "tests/", "-v"])
    _log_bash_to_audit(session_id, "pytest tests/ -v (post-fix)", "PASS" if passed else "FAIL")

    logger.info("Post-fix tests: cycle=%d passed=%s", test_cycle, passed)

    return {
        "test_passed": passed,
        "test_cycle_count": test_cycle,
        "last_test_output": output,
        "current_phase": "unit_test",
    }


def post_fix_ci_node(state: OrchestratorState) -> dict[str, Any]:
    """Run local CI after fixes pass. Shares logic with ci_node."""
    session_id = state.get("session_id", "")
    ci_cycle = state.get("ci_cycle_count", 0) + 1

    passed, output = _run_bash(["bash", "scripts/local_ci.sh"])
    _log_bash_to_audit(session_id, "scripts/local_ci.sh (post-fix)", "PASS" if passed else "FAIL")

    logger.info("Post-fix CI: cycle=%d passed=%s", ci_cycle, passed)

    return {
        "test_passed": passed,
        "ci_cycle_count": ci_cycle,
        "last_ci_output": output,
        "current_phase": "ci",
    }


def system_test_node(state: OrchestratorState) -> dict[str, Any]:
    """Run system/integration tests via bash. No LLM call."""
    session_id = state.get("session_id", "")
    test_cycle = state.get("test_cycle_count", 0) + 1

    passed, output = _run_bash(["pytest", "tests/", "-v", "-m", "system"])
    _log_bash_to_audit(session_id, "pytest -m system", "PASS" if passed else "FAIL")

    logger.info("System tests: cycle=%d passed=%s", test_cycle, passed)

    return {
        "test_passed": passed,
        "test_cycle_count": test_cycle,
        "last_test_output": output,
        "current_phase": "system_test",
    }


def final_ci_node(state: OrchestratorState) -> dict[str, Any]:
    """Final CI gate before push. No LLM call."""
    session_id = state.get("session_id", "")

    passed, output = _run_bash(["bash", "scripts/local_ci.sh"])
    _log_bash_to_audit(session_id, "scripts/local_ci.sh (final)", "PASS" if passed else "FAIL")

    logger.info("Final CI: passed=%s", passed)

    return {
        "test_passed": passed,
        "last_ci_output": output,
        "current_phase": "ci",
    }


def git_push_node(state: OrchestratorState) -> dict[str, Any]:
    """Git commit and push after all gates pass. No LLM call."""
    task_id = state.get("task_id", "")
    session_id = state.get("session_id", "")
    message = f"feat: {task_id} — implemented and reviewed"

    # Commit
    commit_ok, commit_out = _run_bash(["bash", "scripts/git_snapshot.sh", message])
    _log_bash_to_audit(session_id, "git commit", "PASS" if commit_ok else "FAIL")

    # Push
    push_ok, push_out = _run_bash(["git", "push"])
    _log_bash_to_audit(session_id, "git push", "PASS" if push_ok else "FAIL")

    if not push_ok:
        logger.error("Git push failed: %s", push_out[:200])
        return {
            "pipeline_status": "failed",
            "error": f"Git push failed: {push_out[:500]}",
            "current_phase": "push",
        }

    logger.info("Pipeline complete: committed and pushed %s", task_id)

    return {
        "pipeline_status": "completed",
        "current_phase": "push",
    }


# ---------------------------------------------------------------------------
# Error Handler Node
# ---------------------------------------------------------------------------


def error_handler_node(state: OrchestratorState) -> dict[str, Any]:
    """Produce a structured failure report when retry limits are exceeded."""
    task_id = state.get("task_id", "unknown")
    current_phase = state.get("current_phase", "unknown")
    edit_retries = state.get("edit_retry_count", 0)
    test_cycles = state.get("test_cycle_count", 0)
    ci_cycles = state.get("ci_cycle_count", 0)
    error_log = state.get("error_log", [])
    files_modified = state.get("files_modified", [])
    session_id = state.get("session_id", "")

    report = (
        f"# Pipeline Failure Report\n"
        f"## Task: {task_id}\n"
        f"## Failed Phase: {current_phase}\n"
        f"## Retry Counts: edit={edit_retries}/{MAX_EDIT_RETRIES}, "
        f"test={test_cycles}/{MAX_TEST_CYCLES}, CI={ci_cycles}/{MAX_CI_CYCLES}\n"
        f"## Error Log:\n"
    )

    if error_log:
        for entry in error_log:
            report += f"- {entry}\n"
    else:
        report += "- No errors captured\n"

    report += "## Files Modified:\n"
    if files_modified:
        for f in sorted(set(files_modified)):
            report += f"- {f}\n"
    else:
        report += "- None\n"

    logger.error("Pipeline failed at phase=%s for task=%s", current_phase, task_id)

    # Log to audit
    audit = get_logger(session_id)
    if audit:
        audit.log_bash("error_handler", f"FAILED at {current_phase}")

    return {
        "pipeline_status": "failed",
        "error": report,
    }


# ---------------------------------------------------------------------------
# Conditional Routing Functions
# ---------------------------------------------------------------------------


def route_after_unit_test(state: OrchestratorState) -> str:
    """Route after unit_test_node: pass → ci, fail → dev retry or error."""
    if state.get("test_passed", False):
        return "pass"
    if state.get("test_cycle_count", 0) >= MAX_TEST_CYCLES:
        return "error"
    return "retry"


def route_after_ci(state: OrchestratorState) -> str:
    """Route after ci_node: pass → git_snapshot, fail → dev retry or error."""
    if state.get("test_passed", False):
        return "pass"
    if state.get("ci_cycle_count", 0) >= MAX_CI_CYCLES:
        return "error"
    return "retry"


def route_after_post_fix_test(state: OrchestratorState) -> str:
    """Route after post_fix_test_node: pass → post_fix_ci, fail → fix retry or error."""
    if state.get("test_passed", False):
        return "pass"
    if state.get("test_cycle_count", 0) >= MAX_TEST_CYCLES:
        return "error"
    return "retry"


def route_after_post_fix_ci(state: OrchestratorState) -> str:
    """Route after post_fix_ci_node: pass → system_test, fail → fix retry or error."""
    if state.get("test_passed", False):
        return "pass"
    if state.get("ci_cycle_count", 0) >= MAX_CI_CYCLES:
        return "error"
    return "retry"


def route_after_system_test(state: OrchestratorState) -> str:
    """Route after system_test_node: pass → final_ci, fail → dev/fix or error."""
    if state.get("test_passed", False):
        return "pass"
    if state.get("test_cycle_count", 0) >= MAX_TEST_CYCLES:
        return "error"
    return "retry"


def route_after_final_ci(state: OrchestratorState) -> str:
    """Route after final_ci_node: pass → push, fail → error handler."""
    if state.get("test_passed", False):
        return "pass"
    return "error"


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------


def build_orchestrator_graph() -> StateGraph:  # type: ignore[type-arg]
    """Build the full TDD orchestrator pipeline as a StateGraph.

    Pipeline (happy path):
    test_agent → dev_agent → unit_test → ci → git_snapshot →
    prepare_reviews → (Send: review×2) → collect_reviews →
    architect → fix_dev → post_fix_test → post_fix_ci →
    system_test → final_ci → git_push

    Each failure point has conditional routing back to the appropriate
    agent for correction, governed by retry limits.

    Returns:
        Uncompiled StateGraph ready for .compile().
    """
    graph = StateGraph(OrchestratorState)

    # --- Add all nodes ---

    # Phase 1: TDD (Test Agent writes failing tests, Dev Agent implements)
    graph.add_node("test_agent", test_agent_node)
    graph.add_node("dev_agent", dev_agent_node)

    # Phase 2: Validation (bash — no LLM)
    graph.add_node("unit_test", unit_test_node)
    graph.add_node("ci", ci_node)
    graph.add_node("git_snapshot", git_snapshot_node)

    # Phase 3: Review (Send API parallel — Story 3.3)
    graph.add_node("prepare_reviews", prepare_reviews_node)
    graph.add_node("review_node", review_node)
    graph.add_node("collect_reviews", collect_reviews)

    # Phase 4: Architect decision + fix (Story 3.4)
    graph.add_node("architect_node", architect_node)
    graph.add_node("fix_dev_node", fix_dev_node)

    # Phase 5: Post-fix validation (bash — no LLM)
    graph.add_node("post_fix_test", post_fix_test_node)
    graph.add_node("post_fix_ci", post_fix_ci_node)

    # Phase 6: System tests + final gate (bash — no LLM)
    graph.add_node("system_test", system_test_node)
    graph.add_node("final_ci", final_ci_node)

    # Phase 7: Push
    graph.add_node("git_push", git_push_node)

    # Error handler
    graph.add_node("error_handler", error_handler_node)

    # --- Wire edges ---

    # Entry: start with Test Agent
    graph.add_edge(START, "test_agent")
    graph.add_edge("test_agent", "dev_agent")

    # Dev Agent → unit tests → conditional
    graph.add_edge("dev_agent", "unit_test")
    graph.add_conditional_edges(
        "unit_test",
        route_after_unit_test,
        {"pass": "ci", "retry": "dev_agent", "error": "error_handler"},
    )

    # CI → conditional
    graph.add_conditional_edges(
        "ci",
        route_after_ci,
        {"pass": "git_snapshot", "retry": "dev_agent", "error": "error_handler"},
    )

    # Git snapshot → review pipeline
    graph.add_edge("git_snapshot", "prepare_reviews")
    graph.add_conditional_edges("prepare_reviews", route_to_reviewers)
    graph.add_edge("review_node", "collect_reviews")
    graph.add_edge("collect_reviews", "architect_node")

    # Architect → Fix Dev → post-fix validation
    graph.add_edge("architect_node", "fix_dev_node")
    graph.add_edge("fix_dev_node", "post_fix_test")

    # Post-fix test → conditional
    graph.add_conditional_edges(
        "post_fix_test",
        route_after_post_fix_test,
        {"pass": "post_fix_ci", "retry": "fix_dev_node", "error": "error_handler"},
    )

    # Post-fix CI → conditional
    graph.add_conditional_edges(
        "post_fix_ci",
        route_after_post_fix_ci,
        {"pass": "system_test", "retry": "fix_dev_node", "error": "error_handler"},
    )

    # System tests → conditional
    graph.add_conditional_edges(
        "system_test",
        route_after_system_test,
        {"pass": "final_ci", "retry": "fix_dev_node", "error": "error_handler"},
    )

    # Final CI → conditional
    graph.add_conditional_edges(
        "final_ci",
        route_after_final_ci,
        {"pass": "git_push", "error": "error_handler"},
    )

    # Push → END
    graph.add_edge("git_push", END)

    # Error handler → END
    graph.add_edge("error_handler", END)

    return graph


def build_orchestrator(checkpointer: Any = None) -> Any:
    """Build and compile the full orchestrator pipeline.

    Args:
        checkpointer: Optional LangGraph checkpointer for persistence.
            If None, compiles without checkpointing.

    Returns:
        CompiledGraph ready for invocation.
    """
    graph = build_orchestrator_graph()
    return graph.compile(checkpointer=checkpointer)

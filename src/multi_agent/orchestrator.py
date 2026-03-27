"""Story orchestrator pipeline — redesigned.

Implements the per-story build pipeline as a LangGraph StateGraph,
matching the proven patterns from looper/build-loop.sh:

  create_story → write_tests → implement → run_tests → [pass] →
  code_review → run_ci → [pass] → git_commit → END

Key design principles:
  1. Bash first, LLM on failure — tests and CI run as bash nodes,
     LLM agents are only invoked when something fails.
  2. Invoke BMAD agents — LLM nodes call invoke_bmad_agent() with
     a BMAD agent name and command, not hand-crafted prompts.
  3. Scoped tool permissions — each phase gets only the tools it needs.

The heavy review pipeline (dual review + architect triage) lives in
epic_graph.py as post-epic processing, not here.
"""

from __future__ import annotations

import logging
import operator
import os
import re
import subprocess
from collections.abc import Mapping
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.audit_log.audit import get_logger
from src.multi_agent.bmad_invoke import (
    TOOLS_CI_FIX,
    TOOLS_CODE_REVIEW,
    TOOLS_DEV,
    TOOLS_SM,
    TOOLS_TEA,
    TOOLS_TEA_FIX,
    TIMEOUT_LONG,
    TIMEOUT_MEDIUM,
    TIMEOUT_SHORT,
    invoke_bmad_agent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Retry limits
MAX_TEST_CYCLES = 5
MAX_CI_CYCLES = 4


# ---------------------------------------------------------------------------
# State Schema
# ---------------------------------------------------------------------------


class OrchestratorState(TypedDict, total=False):
    """State schema for the story orchestrator pipeline."""

    # Task identity
    task_id: str
    task_description: str
    session_id: str

    # File tracking
    context_files: list[str]
    files_modified: Annotated[list[str], operator.add]

    # Pipeline phase tracking
    current_phase: str
    pipeline_status: str  # running|completed|failed

    # Retry counters
    test_cycle_count: int
    ci_cycle_count: int

    # Test/CI output for retry context
    test_passed: bool
    last_test_output: str
    last_ci_output: str

    # Review gate
    has_review_issues: bool
    review_file_path: str

    # Working directory (target project for rebuild mode)
    working_dir: str

    # Error accumulation
    error_log: Annotated[list[str], operator.add]
    error: str


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _get_working_dir(state: Mapping[str, Any]) -> str | None:
    """Extract working_dir from state, normalizing empty string to None."""
    return state.get("working_dir") or None


def _run_bash(command: list[str], timeout: int = 300, cwd: str | None = None) -> tuple[bool, str]:
    """Execute a shell command and return (success, output).

    No LLM invocation — just command execution and result capture.

    Args:
        command: Command and arguments to execute.
        timeout: Maximum execution time in seconds.
        cwd: Optional working directory for the subprocess.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        if len(output) > 5000:
            total = len(output)
            suffix = f"\n(truncated, {total} chars total)"
            output = output[: 5000 - len(suffix)] + suffix
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s: {' '.join(command)}"
    except Exception as e:
        return False, f"Command execution failed: {e}"


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


def _log_bash_to_audit(session_id: str, script_name: str, result: str) -> None:
    """Log bash execution to audit logger if session is active."""
    audit = get_logger(session_id)
    if audit:
        audit.log_bash(script_name, result)


# ---------------------------------------------------------------------------
# LLM Nodes — thin wrappers around invoke_bmad_agent()
# ---------------------------------------------------------------------------


def create_story_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD create-story agent to produce a story spec from the epic description."""
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    print(f"\n>>> [create_story] Invoking bmad-create-story: create story {task_id}")

    result = invoke_bmad_agent(
        bmad_agent="bmad-create-story",
        command=f"create story {task_id}",
        tools=TOOLS_SM,
        working_dir=working_dir,
        timeout=TIMEOUT_SHORT,
    )

    print(f"    [create_story] Done: success={result['success']}, files={result.get('files_modified', [])}")

    if not result["success"]:
        return {
            "current_phase": "create_story",
            "pipeline_status": "failed",
            "error": f"create_story failed (exit={result['exit_code']}): {result['output'][:500]}",
            "files_modified": result.get("files_modified", []),
        }

    return {
        "current_phase": "create_story",
        "files_modified": result.get("files_modified", []),
    }


def write_tests_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD TEA agent to write acceptance tests (TDD red phase)."""
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    print(f"\n>>> [write_tests] Invoking bmad-testarch-atdd: Create Failing Acceptance Tests for {task_id}")

    result = invoke_bmad_agent(
        bmad_agent="bmad-testarch-atdd",
        command=f"Create Failing Acceptance Tests for story {task_id}",
        tools=TOOLS_TEA,
        working_dir=working_dir,
        timeout=TIMEOUT_SHORT,
    )

    print(f"    [write_tests] Done: success={result['success']}, files={result.get('files_modified', [])}")

    if not result["success"]:
        return {
            "current_phase": "write_tests",
            "pipeline_status": "failed",
            "error": f"write_tests failed (exit={result['exit_code']}): {result['output'][:500]}",
            "files_modified": result.get("files_modified", []),
        }

    return {
        "current_phase": "write_tests",
        "files_modified": result.get("files_modified", []),
    }


def implement_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD DEV agent to implement code (TDD green phase)."""
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    last_test_output = state.get("last_test_output", "")
    test_cycle = state.get("test_cycle_count", 0)
    print(f"\n>>> [implement] Invoking bmad-dev-story: develop story {task_id} (cycle={test_cycle})")

    extra = ""
    if test_cycle > 0 and last_test_output:
        extra = (
            f"This is retry {test_cycle}. Previous test output:\n"
            f"```\n{last_test_output[:3000]}\n```\n"
            f"Fix the failing tests."
        )

    result = invoke_bmad_agent(
        bmad_agent="bmad-dev-story",
        command=f"develop story {task_id}",
        tools=TOOLS_DEV,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        extra_context=extra,
    )

    print(f"    [implement] Done: success={result['success']}, files={result.get('files_modified', [])}")

    if not result["success"]:
        return {
            "current_phase": "implement",
            "pipeline_status": "failed",
            "error": f"implement failed (exit={result['exit_code']}): {result['output'][:500]}",
            "files_modified": result.get("files_modified", []),
        }

    return {
        "current_phase": "implement",
        "files_modified": result.get("files_modified", []),
    }


def review_tests_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD TEA agent to review tests."""
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    print(f"\n>>> [test_review] Invoking bmad-qa RV for {task_id}")

    result = invoke_bmad_agent(
        bmad_agent="bmad-qa",
        command=f"review tests for story {task_id}",
        tools=TOOLS_TEA,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
    )

    print(f"    [test_review] Done: success={result['success']}")

    return {
        "current_phase": "test_review",
        "files_modified": result.get("files_modified", []),
    }


def fix_review_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD TEA agent to fix P1/P2 issues from test review."""
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    review_path = state.get("review_file_path", "")
    print(f"\n>>> [fix_review] Invoking bmad-qa to fix review issues for {task_id}")

    extra = ""
    if review_path:
        extra = (
            f"Read the test review file: {review_path}\n"
            f"Apply fixes for ALL 'Must Fix' (P1) and 'Should Fix' (P2) issues."
        )

    result = invoke_bmad_agent(
        bmad_agent="bmad-qa",
        command=f"Fix review issues for story {task_id}",
        tools=TOOLS_TEA_FIX,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        extra_context=extra,
    )

    print(f"    [fix_review] Done: success={result['success']}")

    return {
        "current_phase": "fix_review",
        "files_modified": result.get("files_modified", []),
    }


def code_review_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD DEV agent for code review with auto-fix."""
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    print(f"\n>>> [code_review] Invoking bmad-dev CR for {task_id}")

    result = invoke_bmad_agent(
        bmad_agent="bmad-dev",
        command=f"code review for story {task_id}",
        tools=TOOLS_CODE_REVIEW,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        extra_context=(
            "When the code review workflow asks what to do with issues, "
            "automatically choose to fix them. No waiting for user input."
        ),
    )

    print(f"    [code_review] Done: success={result['success']}")

    if not result["success"]:
        return {
            "current_phase": "code_review",
            "pipeline_status": "failed",
            "error": f"code_review failed (exit={result['exit_code']}): {result['output'][:500]}",
            "files_modified": result.get("files_modified", []),
        }

    return {
        "current_phase": "code_review",
        "files_modified": result.get("files_modified", []),
    }


def fix_ci_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD DEV agent to fix CI failures."""
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    last_ci_output = state.get("last_ci_output", "")
    print(f"\n>>> [fix_ci] Invoking bmad-dev to fix CI for {task_id}")

    extra = ""
    if last_ci_output:
        extra = (
            f"CI failed. Here is the CI output:\n\n"
            f"```\n{last_ci_output[:5000]}\n```\n\n"
            f"Fix all lint errors (ruff), type errors (mypy), and test failures."
        )

    result = invoke_bmad_agent(
        bmad_agent="bmad-dev",
        command=f"Fix CI failures for story {task_id}",
        tools=TOOLS_CI_FIX,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        extra_context=extra,
    )

    print(f"    [fix_ci] Done: success={result['success']}")

    return {
        "current_phase": "fix_ci",
        "files_modified": result.get("files_modified", []),
    }


# ---------------------------------------------------------------------------
# Bash Nodes (NO LLM invocation)
# ---------------------------------------------------------------------------


def _detect_test_command(working_dir: str | None) -> list[str]:
    """Detect the appropriate test command for the project type."""
    base = working_dir or "."
    if os.path.isfile(os.path.join(base, "package.json")):
        return ["npm", "test"]
    return ["pytest", "tests/", "-v"]


def run_tests_node(state: OrchestratorState) -> dict[str, Any]:
    """Run tests via bash, auto-detecting the test framework. No LLM call."""
    session_id = state.get("session_id", "")
    test_cycle = state.get("test_cycle_count", 0) + 1
    working_dir = _get_working_dir(state)

    # Auto-install npm dependencies if package.json exists but node_modules doesn't
    base = working_dir or "."
    if (
        os.path.isfile(os.path.join(base, "package.json"))
        and not os.path.isdir(os.path.join(base, "node_modules"))
    ):
        print(f"    [run_tests] node_modules missing — running npm install")
        _run_bash(["npm", "install"], cwd=working_dir)

    test_cmd = _detect_test_command(working_dir)
    print(f"\n>>> [run_tests] Running {' '.join(test_cmd)} (cycle={test_cycle})")

    passed, output = _run_bash(test_cmd, cwd=working_dir)
    _log_bash_to_audit(session_id, "pytest tests/ -v", "PASS" if passed else "FAIL")

    print(f"    [run_tests] Result: {'PASS' if passed else 'FAIL'} (cycle={test_cycle})")

    return {
        "test_passed": passed,
        "test_cycle_count": test_cycle,
        "last_test_output": output,
        "current_phase": "run_tests",
    }


def check_review_node(state: OrchestratorState) -> dict[str, Any]:
    """Parse test review output for P1/P2 actionable findings. No LLM call.

    Greps the review file for severity markers. If none found, the
    fix_review node is skipped entirely.
    """
    working_dir = _get_working_dir(state)

    # Try to find the most recent review file
    print(f"\n>>> [check_review] Scanning for review files...")
    review_path = _find_review_file(working_dir)
    if not review_path:
        logger.info("check_review: no review file found — skipping fix")
        return {"has_review_issues": False, "review_file_path": ""}

    try:
        with open(review_path, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.warning("check_review: failed to read %s: %s", review_path, e)
        return {"has_review_issues": False, "review_file_path": ""}

    has_issues = bool(re.search(
        r"(Severity.*P[12]|\*\*Must Fix\*\*|critical|high)",
        content, re.IGNORECASE,
    ))

    print(f"    [check_review] path={review_path} has_issues={has_issues}")

    return {
        "has_review_issues": has_issues,
        "review_file_path": review_path,
    }


def run_ci_node(state: OrchestratorState) -> dict[str, Any]:
    """Run local CI via bash. No LLM call."""
    session_id = state.get("session_id", "")
    ci_cycle = state.get("ci_cycle_count", 0) + 1
    working_dir = _get_working_dir(state)
    print(f"\n>>> [run_ci] Running CI (cycle={ci_cycle})")

    # Auto-install npm dependencies if package.json exists but node_modules doesn't
    base = working_dir or "."
    if (
        os.path.isfile(os.path.join(base, "package.json"))
        and not os.path.isdir(os.path.join(base, "node_modules"))
    ):
        print(f"    [run_ci] node_modules missing — running npm install")
        _run_bash(["npm", "install"], cwd=working_dir)

    # Use local_ci.sh if available, otherwise detect test framework
    ci_script = os.path.join(working_dir, "scripts", "local_ci.sh") if working_dir else "scripts/local_ci.sh"
    if os.path.isfile(ci_script):
        ci_cmd = ["bash", "scripts/local_ci.sh"]
    else:
        ci_cmd = _detect_test_command(working_dir)
    print(f"    Running: {' '.join(ci_cmd)}")
    passed, output = _run_bash(ci_cmd, cwd=working_dir)

    _log_bash_to_audit(session_id, "local_ci", "PASS" if passed else "FAIL")

    print(f"    [run_ci] Result: {'PASS' if passed else 'FAIL'} (cycle={ci_cycle})")

    return {
        "test_passed": passed,
        "ci_cycle_count": ci_cycle,
        "last_ci_output": output,
        "current_phase": "run_ci",
    }


def git_commit_node(state: OrchestratorState) -> dict[str, Any]:
    """Git add + commit after all gates pass. No LLM call."""
    task_id = state.get("task_id", "")
    session_id = state.get("session_id", "")
    cwd = _get_working_dir(state)
    message = f"story {task_id} complete"
    print(f"\n>>> [git_commit] Committing: {message}")

    # Remove stale index.lock (left by killed processes / containers)
    lock_file = os.path.join(cwd, ".git", "index.lock")
    if os.path.exists(lock_file):
        logger.warning("Removing stale git index.lock")
        os.remove(lock_file)

    commit_ok, commit_out = _run_bash(["git", "add", "-A"], cwd=cwd)
    if commit_ok:
        commit_ok, commit_out = _run_bash(["git", "commit", "-m", message], cwd=cwd)
    _log_bash_to_audit(session_id, "git commit", "PASS" if commit_ok else "FAIL")

    if not commit_ok:
        logger.warning("git_commit failed: %s", commit_out[:200])
        return {
            "pipeline_status": "failed",
            "error": f"Git commit failed: {commit_out[:500]}",
            "current_phase": "git_commit",
        }

    print(f"    [git_commit] SUCCESS: committed {task_id}")

    return {
        "pipeline_status": "completed",
        "current_phase": "git_commit",
    }


# ---------------------------------------------------------------------------
# Error Handler
# ---------------------------------------------------------------------------


def error_handler_node(state: OrchestratorState) -> dict[str, Any]:
    """Produce a structured failure report when retry limits are exceeded."""
    task_id = state.get("task_id", "unknown")
    current_phase = state.get("current_phase", "unknown")
    test_cycles = state.get("test_cycle_count", 0)
    ci_cycles = state.get("ci_cycle_count", 0)
    error_log = state.get("error_log", [])
    files_modified = state.get("files_modified", [])
    session_id = state.get("session_id", "")

    report = (
        f"# Pipeline Failure Report\n"
        f"## Task: {task_id}\n"
        f"## Failed Phase: {current_phase}\n"
        f"## Retry Counts: test={test_cycles}/{MAX_TEST_CYCLES}, "
        f"CI={ci_cycles}/{MAX_CI_CYCLES}\n"
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

    audit = get_logger(session_id)
    if audit:
        audit.log_bash("error_handler", f"FAILED at {current_phase}")

    return {
        "pipeline_status": "failed",
        "error": report,
    }


# ---------------------------------------------------------------------------
# Conditional Routing
# ---------------------------------------------------------------------------


def route_after_llm_node(state: OrchestratorState) -> str:
    """Route after any LLM node: success → continue, failure → error."""
    if state.get("pipeline_status") == "failed":
        return "error"
    return "continue"


def route_after_tests(state: OrchestratorState) -> str:
    """Route after run_tests: pass → test_review, fail → implement retry or error."""
    if state.get("test_passed", False):
        return "pass"
    if state.get("test_cycle_count", 0) >= MAX_TEST_CYCLES:
        return "error"
    return "retry"


def route_after_check_review(state: OrchestratorState) -> str:
    """Route after check_review: issues → fix_review, clean → code_review."""
    if state.get("has_review_issues", False):
        return "fix"
    return "skip"


def route_after_ci(state: OrchestratorState) -> str:
    """Route after run_ci: pass → git_commit, fail → fix_ci or error."""
    if state.get("test_passed", False):
        return "pass"
    if state.get("ci_cycle_count", 0) >= MAX_CI_CYCLES:
        return "error"
    return "retry"


# ---------------------------------------------------------------------------
# Helper: find review file
# ---------------------------------------------------------------------------


def _find_review_file(working_dir: str | None) -> str | None:
    """Find the most recently written test review file."""
    search_dirs = []
    base = working_dir or "."

    # Check common locations where TEA agent writes reviews
    for subdir in ["_bmad-output/test-artifacts/test-reviews",
                   "_bmad-output/test-artifacts",
                   "reviews"]:
        candidate = os.path.join(base, subdir)
        if os.path.isdir(candidate):
            search_dirs.append(candidate)

    for search_dir in search_dirs:
        try:
            files = [
                os.path.join(search_dir, f)
                for f in os.listdir(search_dir)
                if f.endswith(".md") and "review" in f.lower()
            ]
            if files:
                # Return most recently modified
                return max(files, key=os.path.getmtime)
        except OSError:
            continue

    return None


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------


def build_orchestrator_graph() -> StateGraph:  # type: ignore[type-arg]
    """Build the story orchestrator pipeline as a StateGraph.

    Pipeline (happy path):
    create_story → write_tests → implement → run_tests → test_review →
    check_review → code_review → run_ci → git_commit

    Failure routing:
    - run_tests fail → implement retry (up to MAX_TEST_CYCLES)
    - check_review has P1/P2 → fix_review → code_review
    - run_ci fail → fix_ci → run_ci retry (up to MAX_CI_CYCLES)

    Returns:
        Uncompiled StateGraph ready for .compile().
    """
    graph = StateGraph(OrchestratorState)

    # --- LLM nodes (BMAD agent invocations) ---
    graph.add_node("create_story", create_story_node)
    graph.add_node("write_tests", write_tests_node)
    graph.add_node("implement", implement_node)
    graph.add_node("code_review", code_review_node)
    graph.add_node("fix_ci", fix_ci_node)

    # --- Bash nodes (no LLM) ---
    graph.add_node("run_ci", run_ci_node)
    graph.add_node("git_commit", git_commit_node)

    # --- Error handler ---
    graph.add_node("error_handler", error_handler_node)

    # --- Edges ---

    # Entry: create story spec (fail → error, success → write tests)
    graph.add_edge(START, "create_story")
    graph.add_conditional_edges(
        "create_story",
        route_after_llm_node,
        {"continue": "write_tests", "error": "error_handler"},
    )
    graph.add_conditional_edges(
        "write_tests",
        route_after_llm_node,
        {"continue": "implement", "error": "error_handler"},
    )

    # Implement → code review (fail → error)
    graph.add_conditional_edges(
        "implement",
        route_after_llm_node,
        {"continue": "code_review", "error": "error_handler"},
    )

    # Code review → CI (fail → error)
    graph.add_conditional_edges(
        "code_review",
        route_after_llm_node,
        {"continue": "run_ci", "error": "error_handler"},
    )
    graph.add_conditional_edges(
        "run_ci",
        route_after_ci,
        {"pass": "git_commit", "retry": "fix_ci", "error": "error_handler"},
    )

    # Fix CI → re-run CI
    graph.add_edge("fix_ci", "run_ci")

    # Terminal nodes
    graph.add_edge("git_commit", END)
    graph.add_edge("error_handler", END)

    return graph


def build_orchestrator(checkpointer: Any = None) -> CompiledStateGraph[Any]:
    """Build and compile the story orchestrator pipeline.

    Args:
        checkpointer: Optional LangGraph checkpointer for persistence.
            If None, compiles without checkpointing.

    Returns:
        CompiledGraph ready for invocation.
    """
    graph = build_orchestrator_graph()
    return graph.compile(checkpointer=checkpointer)

"""Story orchestrator pipeline.

Implements the per-story build pipeline as a LangGraph StateGraph:

  check_story → check_dev → [dev_story] → code_review →
  run_ci → [fix_ci] → git_commit → END

The dev_story node combines story creation and implementation into a
single BMAD dev agent invocation. This mirrors the upstream BMAD v6.3.0
change where the SM agent was removed and the dev agent handles both
story creation (CS) and development (DS). The combined invocation reads
planning artifacts once and carries context forward, improving coherence
and reducing redundant token consumption.

Key design principles:
  1. Bash first, LLM on failure — CI runs as bash nodes,
     LLM agents are only invoked when something fails.
  2. Invoke BMAD agents — LLM nodes call invoke_bmad_agent() with
     a BMAD agent name and command, not hand-crafted prompts.
  3. Scoped tool permissions — each phase gets only the tools it needs.
  4. Per-node model selection — each node can use a different model
     via set_model_config().
  5. Phase-level checkpoints — each completed phase is recorded to
     checkpoints/phase.json for crash recovery.

The heavy review pipeline (dual review + architect triage) lives in
epic_graph.py as post-epic processing, not here.
"""

from __future__ import annotations

import logging
import operator
import os
import re
import shlex
import subprocess
from collections.abc import Mapping
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.audit_log.audit import get_logger
from src.intake.checkpoint import clear_phase_checkpoint, save_phase_checkpoint
from src.multi_agent.bmad_invoke import (
    TIMEOUT_LONG,
    TIMEOUT_MEDIUM,
    TOOLS_CI_FIX,
    TOOLS_CI_GENERATE,
    TOOLS_CODE_REVIEW,
    TOOLS_DEV,
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
# Per-node model configuration
# ---------------------------------------------------------------------------

# Default model overrides per node. None = use CLI default.
# Override via set_model_config() (called from factory.yaml loader).
_MODEL_CONFIG: dict[str, str | None] = {
    "dev_story": "claude-sonnet-4-6",
    "code_review": "claude-sonnet-4-6",
    "fix_ci": "claude-sonnet-4-6",
}


def set_model_config(config: dict[str, str | None]) -> None:
    """Update per-node model overrides from external config."""
    _MODEL_CONFIG.update(config)


# ---------------------------------------------------------------------------
# Story-level review toggle
# ---------------------------------------------------------------------------

_STORY_REVIEWS_ENABLED: bool = True


def get_story_reviews_enabled() -> bool:
    """Return whether story-level code reviews are enabled."""
    return _STORY_REVIEWS_ENABLED


def set_story_reviews_enabled(enabled: bool) -> None:
    """Enable or disable story-level code reviews."""
    global _STORY_REVIEWS_ENABLED  # noqa: PLW0603
    _STORY_REVIEWS_ENABLED = enabled


# ---------------------------------------------------------------------------
# Story-level CI toggle
# ---------------------------------------------------------------------------

_STORY_CI_ENABLED: bool = True
_FIX_PRE_EXISTING: bool = True


def get_story_ci_enabled() -> bool:
    """Return whether story-level CI runs are enabled."""
    return _STORY_CI_ENABLED


def set_story_ci_enabled(enabled: bool) -> None:
    """Enable or disable story-level CI runs."""
    global _STORY_CI_ENABLED  # noqa: PLW0603
    _STORY_CI_ENABLED = enabled


def get_fix_pre_existing() -> bool:
    """Return whether CI fix agents should fix pre-existing errors.

    When True (greenfield default), CI-fix agents fix any failure
    reported by CI regardless of whether the current story/epic
    introduced it. When False (brownfield-rebuild mode), a scope
    constraint tells the fix agent to ignore pre-existing failures.
    """
    return _FIX_PRE_EXISTING


def set_fix_pre_existing(enabled: bool) -> None:
    """Enable or disable fixing pre-existing CI errors."""
    global _FIX_PRE_EXISTING  # noqa: PLW0603
    _FIX_PRE_EXISTING = enabled


def _model_for(node: str) -> str | None:
    """Return the model override for a given node, or None for default."""
    return _MODEL_CONFIG.get(node)


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

    # Story existence check
    story_exists: bool
    dev_complete: bool

    # Review gate
    has_review_issues: bool
    review_file_path: str

    # Working directory (target project for rebuild mode)
    working_dir: str

    # Phase-level resume: set by the epic graph when a stale phase.json
    # matches (session_id, task_id) of the story about to run. When
    # non-empty, the entry router jumps the pipeline directly to that
    # phase instead of starting at check_story. Empty string = normal
    # entry (default).
    resume_from_phase: str

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
        # subprocess.run can leave stdout/stderr as None in rare Windows
        # edge cases (large output + encoding path). Coerce to "" so the
        # len() check below never raises TypeError and bubbles up as a
        # misleading "Command execution failed" string to downstream
        # fix_ci agents.
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        output = stdout + ("\n" + stderr if stderr else "")
        if len(output) > 5000:
            total = len(output)
            marker = f"[truncated: showing last 5000 of {total} chars]\n"
            output = marker + output[-(5000 - len(marker)):]
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


def _save_phase(state: Mapping[str, Any], phase: str) -> None:
    """Save a phase-level checkpoint after successful completion."""
    session_id = state.get("session_id", "")
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state) or "."
    if session_id and task_id:
        save_phase_checkpoint(session_id, working_dir, task_id, phase)


def _log_bash_to_audit(session_id: str, script_name: str, result: str) -> None:
    """Log bash execution to audit logger if session is active."""
    audit = get_logger(session_id)
    if audit:
        audit.log_bash(script_name, result)


# ---------------------------------------------------------------------------
# LLM Nodes — thin wrappers around invoke_bmad_agent()
# ---------------------------------------------------------------------------


def _find_story_status(working_dir: str, task_id: str) -> str | None:
    """Find a story file for the given task_id and return its Status value, or None."""
    impl_dir = os.path.join(working_dir, "_bmad-output", "implementation-artifacts")
    prefix = f"{task_id}-"
    if not os.path.isdir(impl_dir):
        return None
    for fname in os.listdir(impl_dir):
        if fname.startswith(prefix) and fname.endswith(".md"):
            # Verify the character after the task_id digits is not another digit
            rest = fname[len(prefix):]
            if rest and rest[0].isdigit():
                continue
            fpath = os.path.join(impl_dir, fname)
            with open(fpath, encoding="utf-8") as f:
                content = f.read(500)  # Only need the header
            for line in content.splitlines():
                if line.startswith("Status:"):
                    return line.split(":", 1)[1].strip()
    return None


def check_story_exists_node(state: OrchestratorState) -> dict[str, Any]:
    """Non-LLM check: does a story file already exist?

    Determines what the dev_story node needs to do:
    - No story file → create + implement (full run)
    - Story exists with ready-for-dev → implement only (skip creation)
    - Story exists with review/done → skip dev_story entirely
    """
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    status = _find_story_status(working_dir, task_id)

    if status in ("review", "done"):
        print(f"\n>>> [check_story] Story {task_id} has status '{status}' — skipping dev_story")
        return {"story_exists": True, "dev_complete": True, "current_phase": "check_story"}

    if status == "ready-for-dev":
        print(f"\n>>> [check_story] Story {task_id} exists "
              f"with status 'ready-for-dev' — dev_story will implement only")
        return {"story_exists": True, "dev_complete": False, "current_phase": "check_story"}

    print(f"\n>>> [check_story] Story {task_id} not found or "
          f"status '{status}' — dev_story will create + implement")
    return {"story_exists": False, "dev_complete": False, "current_phase": "check_story"}


def route_after_story_check(state: OrchestratorState) -> str:
    """Route based on story status: skip dev entirely, or run dev_story."""
    if state.get("dev_complete"):
        return "skip"
    return "dev"


# Valid phase-resume targets for the entry router. dev_story is
# deliberately not a target: the story-status gate in
# check_story_exists_node handles that case by reading the story
# file's actual status rather than trusting a checkpoint.
_RESUME_ENTRY_PHASES = {"code_review", "run_ci", "git_commit"}


def route_on_entry(state: OrchestratorState) -> str:
    """Route from START based on any phase-resume hint in state.

    When the epic graph loaded a matching phase.json, it sets
    resume_from_phase to the next phase to run. Jump there directly,
    skipping phases that already completed in a prior session.

    Fall through to the normal check_story entry when no resume hint
    is present or the hint isn't a valid resume target.
    """
    phase = state.get("resume_from_phase", "")
    if phase in _RESUME_ENTRY_PHASES:
        print(f"\n>>> [route_on_entry] Phase-resume: jumping to {phase}")
        return phase
    return "check_story"


def dev_story_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD dev agent to create the story spec and implement it.

    Combines the former create_story + implement into a single agent
    invocation. The dev agent reads planning artifacts once, creates the
    story file (CS), then immediately implements it (DS) — carrying full
    context forward without re-reading.

    When the story file already exists (story_exists=True), tells the
    agent to skip creation and proceed directly to implementation.
    """
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    story_exists = state.get("story_exists", False)
    last_test_output = state.get("last_test_output", "")
    test_cycle = state.get("test_cycle_count", 0)

    if story_exists:
        # Story already created — implement only
        command = f"DS for story {task_id}"
        print(f"\n>>> [dev_story] Story exists — invoking bmad-agent-dev: "
              f"DS for {task_id} (cycle={test_cycle})")
    else:
        # Full flow — create then implement in one session
        command = f"CS for story {task_id}, then DS for the same story"
        print(f"\n>>> [dev_story] Invoking bmad-agent-dev: CS + DS for {task_id}")

    extra = ""
    if test_cycle > 0 and last_test_output:
        extra = (
            f"This is retry {test_cycle}. Previous test output:\n"
            f"```\n{last_test_output[:3000]}\n```\n"
            f"Fix the failing tests."
        )

    result = invoke_bmad_agent(
        bmad_agent="bmad-agent-dev",
        command=command,
        tools=TOOLS_DEV,
        working_dir=working_dir,
        timeout=TIMEOUT_LONG,
        extra_context=extra,
        model=_model_for("dev_story"),
    )

    print(f"    [dev_story] Done: success={result['success']}, "
          f"files={result.get('files_modified', [])}")

    if not result["success"]:
        return {
            "current_phase": "dev_story",
            "pipeline_status": "failed",
            "error": f"dev_story failed (exit={result['exit_code']}): {result['output'][:500]}",
            "files_modified": result.get("files_modified", []),
        }

    _save_phase(state, "dev_story")
    return {
        "current_phase": "dev_story",
        "files_modified": result.get("files_modified", []),
    }


def code_review_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD DEV agent for code review with auto-fix."""
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)

    if not _STORY_REVIEWS_ENABLED:
        print(f"\n>>> [code_review] Skipped for {task_id} (story reviews disabled)")
        _save_phase(state, "code_review")
        return {"current_phase": "code_review"}

    print(f"\n>>> [code_review] Invoking bmad-agent-dev CR for {task_id}")

    result = invoke_bmad_agent(
        bmad_agent="bmad-agent-dev",
        command=f"code review for story {task_id}",
        tools=TOOLS_CODE_REVIEW,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        model=_model_for("code_review"),
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

    _save_phase(state, "code_review")
    return {
        "current_phase": "code_review",
        "files_modified": result.get("files_modified", []),
    }


def fix_ci_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD DEV agent to fix CI failures."""
    task_id = state.get("task_id", "")
    working_dir = _get_working_dir(state)
    last_ci_output = state.get("last_ci_output", "")
    print(f"\n>>> [fix_ci] Invoking bmad-agent-dev to fix CI for {task_id}")

    extra = ""
    if last_ci_output:
        extra = (
            f"CI failed. Here is the CI output:\n\n"
            f"```\n{last_ci_output[:5000]}\n```\n\n"
            f"Fix all errors reported by the CI pipeline — this may "
            f"include lint errors, type-check errors, security scan "
            f"findings, and test failures. Read the output carefully "
            f"to determine which tools reported issues."
        )
        if not _FIX_PRE_EXISTING:
            extra += (
                f"\n\nIMPORTANT SCOPE CONSTRAINT: Fix every failure "
                f"caused by story {task_id}. This includes:\n"
                f"  - Failures in files you created or modified for "
                f"this story.\n"
                f"  - Failures in OTHER files (tests, route handlers, "
                f"queries) that became broken because of a "
                f"type/schema/signature change introduced by "
                f"story {task_id}. These are downstream effects of "
                f"your work — they are IN SCOPE and you must fix "
                f"them, even when the failing file lives outside the "
                f"story's primary area.\n\n"
                f"Do NOT fix failures that are unrelated to story "
                f"{task_id}'s changes — a test that was already "
                f"failing before this story started, in code you did "
                f"not touch, with errors unrelated to your type or "
                f"schema changes.\n\n"
                f"Rule of thumb: if the error message mentions a "
                f"field, column, type, interface, or function that "
                f"YOU added or modified in story {task_id}, it IS in "
                f"scope — fix it. A typecheck run like `tsc --noEmit` "
                f"is global: adding a required column to a shared "
                f"type will surface errors in every test mock that "
                f"constructs an object of that type. All of those "
                f"are yours to fix."
            )

    result = invoke_bmad_agent(
        bmad_agent="bmad-agent-dev",
        command=f"Fix CI failures for story {task_id}",
        tools=TOOLS_CI_FIX,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        extra_context=extra,
        model=_model_for("fix_ci"),
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
    project_type = _detect_project_type(working_dir)
    test_commands: dict[str, list[str]] = {
        "python": ["pytest", "tests/", "-v"],
        "node": ["npm", "test"],
        "rust": ["cargo", "test"],
        "go": ["go", "test", "./..."],
    }
    return test_commands.get(project_type, ["pytest", "tests/", "-v"])


def _ensure_dependencies(working_dir: str | None) -> None:
    """Auto-install missing dependencies based on project type.

    Runs the appropriate package-manager install command if dependency
    artifacts are missing (e.g. node_modules, .venv). Safe to call
    multiple times — each check is idempotent.
    """
    base = working_dir or "."
    project_type = _detect_project_type(working_dir)

    if project_type == "node":
        if (
            os.path.isfile(os.path.join(base, "package.json"))
            and not os.path.isdir(os.path.join(base, "node_modules"))
        ):
            print("    [deps] node_modules missing — running npm install")
            _run_bash(["bash", "-c", "npm install"], cwd=working_dir)

    elif project_type == "python":
        req_file = os.path.join(base, "requirements.txt")
        req_dev = os.path.join(base, "requirements-dev.txt")
        if os.path.isfile(req_dev):
            print("    [deps] Installing from requirements-dev.txt")
            _run_bash(
                ["python", "-m", "pip", "install", "-r", req_dev, "--quiet"],
                cwd=working_dir,
            )
        elif os.path.isfile(req_file):
            print("    [deps] Installing from requirements.txt")
            _run_bash(
                ["python", "-m", "pip", "install", "-r", req_file, "--quiet"],
                cwd=working_dir,
            )

    elif project_type == "rust":
        # cargo build/test auto-downloads deps, but fetch is faster for pre-warming
        cargo_lock = os.path.join(base, "Cargo.lock")
        if os.path.isfile(os.path.join(base, "Cargo.toml")) and not os.path.isfile(cargo_lock):
            print("    [deps] Cargo.lock missing — running cargo fetch")
            _run_bash(["cargo", "fetch"], cwd=working_dir)

    elif project_type == "go":
        go_sum = os.path.join(base, "go.sum")
        if os.path.isfile(os.path.join(base, "go.mod")) and not os.path.isfile(go_sum):
            print("    [deps] go.sum missing — running go mod download")
            _run_bash(["go", "mod", "download"], cwd=working_dir)


# Migration framework detection: (marker_file, check_command, generate_command, label)
# check_command returns exit 0 if migrations are up-to-date, non-zero if pending.
# generate_command auto-creates any missing migration files.
_MIGRATION_FRAMEWORKS: list[tuple[str, list[str], list[str], str]] = [
    # Django — manage.py in project root or common subdirs
    (
        "manage.py",
        ["python", "manage.py", "makemigrations", "--check", "--dry-run"],
        ["python", "manage.py", "makemigrations"],
        "Django",
    ),
    # Alembic (Flask / FastAPI / SQLAlchemy)
    (
        "alembic.ini",
        ["alembic", "check"],
        ["alembic", "revision", "--autogenerate", "-m", "auto"],
        "Alembic",
    ),
    # Prisma (Node.js)
    (
        "prisma/schema.prisma",
        ["npx", "prisma", "migrate", "status"],
        ["npx", "prisma", "migrate", "dev", "--name", "auto"],
        "Prisma",
    ),
    # Diesel (Rust)
    (
        "diesel.toml",
        ["diesel", "migration", "pending"],
        ["diesel", "migration", "run"],
        "Diesel",
    ),
]


def _ensure_migrations(working_dir: str | None) -> None:
    """Check for pending database migrations and auto-generate if needed.

    Detects the migration framework from marker files, runs the check
    command, and auto-generates migrations when they're out of date.
    Also searches common subdirectories (e.g. backend/) for the marker
    file, since many projects nest the app server.
    """
    base = working_dir or "."

    for marker, check_cmd, generate_cmd, label in _MIGRATION_FRAMEWORKS:
        # Search project root and one level of common subdirs
        search_dirs = [base]
        for subdir in ("backend", "server", "api", "app", "src"):
            candidate = os.path.join(base, subdir)
            if os.path.isdir(candidate):
                search_dirs.append(candidate)

        for search_dir in search_dirs:
            marker_path = os.path.join(search_dir, marker)
            if not os.path.isfile(marker_path):
                continue

            print(f"    [migrations] {label} detected in {search_dir}")
            passed, output = _run_bash(check_cmd, cwd=search_dir)

            if passed:
                print(f"    [migrations] {label} migrations up to date")
            else:
                print("    [migrations] Pending migrations — auto-generating...")
                gen_passed, gen_output = _run_bash(generate_cmd, cwd=search_dir)
                if gen_passed:
                    print(f"    [migrations] {label} migrations generated")
                    # Stage the generated migration files
                    _run_bash(["git", "add", "-A"], cwd=search_dir)
                else:
                    print("    [migrations] WARNING: auto-generate failed")
                    logger.warning(
                        "Migration auto-generate failed for %s in %s: %s",
                        label, search_dir, gen_output[:500],
                    )

            # Only handle the first matching framework per project
            return


def _makefile_has_target(makefile_path: str, target: str) -> bool:
    """Check whether a Makefile declares the given target."""
    try:
        with open(makefile_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith(f"{target}:") or line.startswith(f".PHONY: {target}"):
                    return True
    except Exception:
        pass
    return False


def _detect_project_type(working_dir: str | None) -> str:
    """Detect project type from marker files, falling back to architecture.md."""
    base = working_dir or "."
    markers = {
        "python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"],
        "node": ["package.json"],
        "rust": ["Cargo.toml"],
        "go": ["go.mod"],
    }
    for project_type, files in markers.items():
        for marker in files:
            if os.path.isfile(os.path.join(base, marker)):
                return project_type

    # Fallback: scan for architecture.md and infer type from its content.
    # This handles empty/fresh directories where only planning artifacts exist.
    return _detect_type_from_architecture_md(base)


def _detect_type_from_architecture_md(base: str) -> str:
    """Walk *base* looking for architecture.md; infer project type from content."""
    arch_path = None
    for root, _dirs, filenames in os.walk(base):
        for fname in filenames:
            if fname.lower() == "architecture.md":
                arch_path = os.path.join(root, fname)
                break
        if arch_path:
            break

    if not arch_path:
        return "unknown"

    try:
        with open(arch_path, encoding="utf-8") as fh:
            content = fh.read().lower()
    except OSError:
        return "unknown"

    # Order matters: check most-distinctive keywords first.
    # Each entry is (type_key, list_of_indicator_patterns).
    stack_signals: list[tuple[str, list[str]]] = [
        ("rust", ["cargo.toml", "tokio", "axum", "rocket", "serde"]),
        ("go", ["go mod", "go module", "goroutine", "gin", "echo framework"]),
        ("python", [
            "fastapi", "django", "flask", "langgraph", "pyproject",
            "pip install", "pytest", "python",
        ]),
        ("node", [
            "package.json", "pnpm", "npm", "yarn", "express",
            "react", "next.js", "vite", "typescript",
        ]),
    ]

    for project_type, keywords in stack_signals:
        if any(kw in content for kw in keywords):
            return project_type

    return "unknown"


# CI script templates per project type.
# Each template is a complete, runnable bash script that the target project
# can later customise. The script must accept --story STORY and --quick flags
# for compatibility with the per-story pipeline.
_CI_TEMPLATES: dict[str, str] = {
    "python": """\
#!/usr/bin/env bash
# Auto-generated CI script (Python project) — customise as needed.
set -euo pipefail

STORY_FILTER=""
QUICK_MODE=false
TEST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --story)  STORY_FILTER="$2"; shift 2 ;;
        --quick)  QUICK_MODE=true; shift ;;
        --test)   TEST_ONLY=true; shift ;;
        *)        shift ;;
    esac
done

# --- Lint ---
if ! $TEST_ONLY; then
    echo "=== lint ==="
    if command -v ruff &>/dev/null; then
        python -m ruff check .
        python -m ruff format --check .
    fi

    echo "=== typecheck ==="
    if command -v mypy &>/dev/null; then
        python -m mypy .
    fi
fi

# --- Tests ---
echo "=== tests ==="
if [ -n "$STORY_FILTER" ]; then
    PATTERN=$(echo "$STORY_FILTER" | tr '-' '_')
    python -m pytest tests/ -v -k "story_${PATTERN}" || python -m pytest tests/ -v
elif $QUICK_MODE; then
    python -m pytest tests/ -x -q
else
    python -m pytest tests/ -v
fi

echo "=== All checks passed ==="
""",
    "node": """\
#!/usr/bin/env bash
# Auto-generated CI script (Node.js project) — customise as needed.
set -euo pipefail

STORY_FILTER=""
QUICK_MODE=false
TEST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --story)  STORY_FILTER="$2"; shift 2 ;;
        --quick)  QUICK_MODE=true; shift ;;
        --test)   TEST_ONLY=true; shift ;;
        *)        shift ;;
    esac
done

# --- Lint ---
if ! $TEST_ONLY; then
    echo "=== lint ==="
    if [ -f .eslintrc* ] || grep -q '"eslint"' package.json 2>/dev/null; then
        npx eslint . || true
    fi

    echo "=== typecheck ==="
    if [ -f tsconfig.json ]; then
        npx tsc --noEmit || true
    fi
fi

# --- Tests ---
echo "=== tests ==="
npm test

echo "=== All checks passed ==="
""",
    "rust": """\
#!/usr/bin/env bash
# Auto-generated CI script (Rust project) — customise as needed.
set -euo pipefail

echo "=== lint ==="
cargo clippy -- -D warnings

echo "=== tests ==="
cargo test

echo "=== All checks passed ==="
""",
    "go": """\
#!/usr/bin/env bash
# Auto-generated CI script (Go project) — customise as needed.
set -euo pipefail

STORY_FILTER=""
QUICK_MODE=false
TEST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --story)  STORY_FILTER="$2"; shift 2 ;;
        --quick)  QUICK_MODE=true; shift ;;
        --test)   TEST_ONLY=true; shift ;;
        *)        shift ;;
    esac
done

# --- Lint ---
if ! $TEST_ONLY; then
    echo "=== lint ==="
    if command -v golangci-lint &>/dev/null; then
        golangci-lint run ./...
    else
        go vet ./...
    fi
fi

# --- Tests ---
echo "=== tests ==="
if [ -n "$STORY_FILTER" ]; then
    PATTERN=$(echo "$STORY_FILTER" | tr '-' '_')
    # Attempt story-scoped tests; fall back to full suite if no matches
    MATCHED=$(go test ./... -list "Story${PATTERN}|Test.*${PATTERN}" 2>/dev/null \
        | grep -c "^Test" || true)
    if [ "$MATCHED" -gt 0 ]; then
        echo "  Running $MATCHED story-scoped test(s)..."
        go test ./... -run "Story${PATTERN}|Test.*${PATTERN}" -v
    else
        echo "  No tests matched story filter '${STORY_FILTER}', running full suite..."
        go test ./...
    fi
elif $QUICK_MODE; then
    go test ./... -failfast
else
    go test ./...
fi

echo "=== All checks passed ==="
""",
    "unknown": """\
#!/usr/bin/env bash
# Auto-generated CI script (unknown project type) — customise as needed.
set -euo pipefail
echo "WARNING: Could not detect project type. Add your CI commands here."
echo "=== All checks passed ==="
""",
}


def generate_ci_script(working_dir: str | None) -> str:
    """Generate scripts/ci.sh by invoking bmad-agent-architect on the approved tech stack.

    Reads _bmad-output/approved-tech-stack.md from the target project directory
    and asks the architect agent to produce a comprehensive CI script covering
    every stack, subdirectory, and test framework listed in the document.

    Falls back to the static template scaffolding if the tech stack file is
    missing or the architect invocation fails.

    Args:
        working_dir: Target project root (None = cwd).

    Returns:
        Absolute path to the generated scripts/ci.sh.

    Raises:
        FileNotFoundError: If _bmad-output/approved-tech-stack.md does not exist.
    """
    base = working_dir or "."

    # If scripts/ci.sh already exists, leave it alone — the user pre-created it.
    existing_ci = os.path.join(base, "scripts", "ci.sh")
    if os.path.isfile(existing_ci):
        logger.info("CI script already exists at %s, skipping generation", existing_ci)
        print(f"    [ci] Found existing {existing_ci} — skipping generation")
        return existing_ci

    tech_stack_path = os.path.join(base, "_bmad-output", "approved-tech-stack.md")

    if not os.path.isfile(tech_stack_path):
        msg = (
            f"Cannot generate CI script: {tech_stack_path} not found. "
            f"Create _bmad-output/approved-tech-stack.md in the target project "
            f"before running the pipeline. This file should list every technology, "
            f"test framework, and build tool the project uses."
        )
        logger.error(msg)
        print(f"\n    [ci] ERROR: {msg}")
        raise FileNotFoundError(msg)

    # Read the tech stack so we can include it in the architect prompt
    with open(tech_stack_path, encoding="utf-8") as f:
        tech_stack_content = f.read()

    # Scan for subdirectories with their own package manifests to give the
    # architect awareness of the project layout
    layout_hints: list[str] = []
    for entry in sorted(os.listdir(base)):
        entry_path = os.path.join(base, entry)
        if not os.path.isdir(entry_path) or entry.startswith((".", "_", "node_modules")):
            continue
        markers = ["go.mod", "package.json", "pyproject.toml", "Cargo.toml",
                    "requirements.txt", "setup.py"]
        for marker in markers:
            if os.path.isfile(os.path.join(entry_path, marker)):
                layout_hints.append(f"  {entry}/{marker}")
    # Also check root-level markers
    for marker in ["go.mod", "package.json", "pyproject.toml", "Cargo.toml",
                    "requirements.txt"]:
        if os.path.isfile(os.path.join(base, marker)):
            layout_hints.append(f"  ./{marker} (root)")

    layout_section = "\n".join(layout_hints) if layout_hints else "  (no markers found)"

    architect_prompt = (
        "Analyze the approved tech stack document below and generate a comprehensive "
        "bash CI script that will be saved as scripts/ci.sh.\n\n"
        "GUARDRAILS — strictly follow these rules:\n"
        "- ONLY include checks for technologies explicitly listed in the approved "
        "tech stack document. Do NOT add tools, linters, or checks that are not in "
        "the document.\n"
        "- Use the project layout hints below to determine which subdirectory each "
        "stack lives in (e.g. Go code in api/, Node code in web/).\n"
        "- If a technology is listed but no matching directory exists yet (empty project), "
        "wrap that section in an existence check (e.g. if [ -d api ]; then ...).\n"
        "- The script MUST use 'set -euo pipefail' and fail fast on any error.\n"
        "- The script MUST support these flags: --story FILTER, --quick, --test-only.\n"
        "- STORY SCOPING: When --story is provided (e.g. --story 2-1), attempt to run "
        "only that story's tests. Use the best available mechanism for each stack:\n"
        "  * Python/pytest: -k 'story_2_1' (convert hyphens to underscores)\n"
        "  * Go: -run 'Story2_1|Test.*2_1' regex filter\n"
        "  * Node/Vitest: --grep or file glob matching the story ID\n"
        "  If story-scoped filtering fails or matches zero tests, ALWAYS fall back to "
        "running the full test suite — never exit with an error just because no tests "
        "matched the story filter. Lint, typecheck, and build always run on the full "
        "codebase regardless of --story.\n"
        "- For --test-only mode, skip lint/typecheck/build and only run tests.\n"
        "- For --quick mode, run tests with fail-fast (-x or equivalent).\n"
        "- Include these phases in order: install deps → lint → typecheck → test → build.\n"
        "- Skip install if dependencies are already present (node_modules exists, etc.).\n"
        "- For tests that need infrastructure (Playwright, testcontainers), add a skip "
        "message rather than failing.\n"
        "- End with 'echo \"=== All checks passed ===\"' on success.\n"
        "- Output ONLY the script content in a single fenced code block. No explanation.\n\n"
        f"PROJECT LAYOUT:\n{layout_section}\n\n"
        f"APPROVED TECH STACK:\n```\n{tech_stack_content}\n```"
    )

    print("\n    [ci] Invoking bmad-agent-architect to generate CI script...")
    result = invoke_bmad_agent(
        bmad_agent="bmad-agent-architect",
        command=architect_prompt,
        tools=TOOLS_CI_GENERATE,
        working_dir=working_dir,
        timeout=TIMEOUT_MEDIUM,
        model="sonnet",
    )

    if not result.get("success"):
        logger.warning(
            "Architect CI generation failed (exit=%s), falling back to static template",
            result.get("exit_code"),
        )
        print("    [ci] WARN: Architect failed, falling back to static template")
        return _scaffold_ci_script_static(working_dir)

    # Extract the script from the architect's output — look for a fenced code block
    output = result.get("output", "")
    script_content = _extract_script_from_output(output)

    if not script_content:
        logger.warning("Could not extract script from architect output, falling back")
        print("    [ci] WARN: Could not parse architect output, falling back to static template")
        return _scaffold_ci_script_static(working_dir)

    # Write the script
    scripts_dir = os.path.join(base, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    ci_path = os.path.join(scripts_dir, "ci.sh")
    with open(ci_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(script_content)
    os.chmod(ci_path, 0o755)

    logger.info("Generated CI script at %s via bmad-agent-architect", ci_path)
    print("    [ci] Generated scripts/ci.sh via bmad-agent-architect")
    return ci_path


def _extract_script_from_output(output: str) -> str | None:
    """Extract a bash script from fenced code blocks in LLM output."""
    # Try ```bash ... ``` first, then generic ``` ... ```
    patterns = [
        r"```(?:bash|sh)\s*\n(.*?)```",
        r"```\s*\n(.*?)```",
    ]
    for pattern in patterns:
        match = re.search(pattern, output, re.DOTALL)
        if match:
            script = match.group(1).strip()
            if script.startswith("#!/"):
                return script + "\n"
    return None


def _scaffold_ci_script_static(working_dir: str | None) -> str:
    """Fallback: generate a default scripts/ci.sh from static templates.

    Used when the architect-based generation is unavailable (no tech stack
    file or architect failure).

    Returns the absolute path to the created script.
    """
    base = working_dir or "."
    project_type = _detect_project_type(working_dir)
    template = _CI_TEMPLATES.get(project_type, _CI_TEMPLATES["unknown"])

    scripts_dir = os.path.join(base, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    ci_path = os.path.join(scripts_dir, "ci.sh")
    with open(ci_path, "w", encoding="utf-8") as f:
        f.write(template)
    os.chmod(ci_path, 0o755)

    logger.info("Scaffolded CI script at %s (type=%s)", ci_path, project_type)
    print(f"    [ci] Scaffolded scripts/ci.sh for {project_type} project (static fallback)")
    return ci_path


def resolve_ci_command(
    working_dir: str | None,
    *,
    story_id: str | None = None,
) -> list[str]:
    """Resolve the CI command for a target project.

    Fallback chain:
      1. scripts/ci.sh exists             → bash scripts/ci.sh [--story ID]
      2. Makefile with ci / ci-story target → make ci[-story STORY=ID]
      3. Neither exists                    → scaffold scripts/ci.sh, then use it

    Args:
        working_dir: Target project root (None = cwd).
        story_id: Optional story identifier for scoped CI (e.g. "0-3").
                  When None, runs the full (epic-level) CI.

    Returns:
        Command as a list of strings suitable for subprocess.
    """
    base = working_dir or "."
    story_label = f" (story={story_id})" if story_id else " (full suite)"

    # --- 1. scripts/ci.sh ---
    ci_script = os.path.join(base, "scripts", "ci.sh")
    if os.path.isfile(ci_script):
        cmd = ["bash", "scripts/ci.sh"]
        if story_id:
            cmd += ["--story", story_id]
        logger.info("CI resolution: found %s, using it%s", ci_script, story_label)
        print(f"    [ci] Found {ci_script} — using it{story_label}")
        return cmd

    # --- 2. Makefile targets ---
    makefile = os.path.join(base, "Makefile")
    if os.path.isfile(makefile):
        if story_id and _makefile_has_target(makefile, "ci-story"):
            logger.info("CI resolution: found %s ci-story target%s", makefile, story_label)
            print(f"    [ci] Found {makefile} ci-story target — using make{story_label}")
            return ["make", "ci-story", f"STORY={story_id}"]
        if _makefile_has_target(makefile, "ci"):
            logger.info("CI resolution: found %s ci target%s", makefile, story_label)
            print(f"    [ci] Found {makefile} ci target — using make{story_label}")
            return ["make", "ci"]

    # --- 3. Scaffold a default CI script (static fallback) ---
    logger.warning(
        "CI resolution: searched for %s and %s — neither found, scaffolding static fallback",
        ci_script, makefile,
    )
    print(
        f"    [ci] WARN: Searched for {ci_script} and {makefile} — "
        f"neither found, scaffolding static fallback{story_label}"
    )
    _scaffold_ci_script_static(working_dir)
    cmd = ["bash", "scripts/ci.sh"]
    if story_id:
        cmd += ["--story", story_id]
    return cmd


def run_tests_node(state: OrchestratorState) -> dict[str, Any]:
    """Run tests via bash, auto-detecting the test framework. No LLM call."""
    session_id = state.get("session_id", "")
    test_cycle = state.get("test_cycle_count", 0) + 1
    working_dir = _get_working_dir(state)

    _ensure_dependencies(working_dir)

    test_cmd = _detect_test_command(working_dir)
    print(f"\n>>> [run_tests] Running {' '.join(test_cmd)} (cycle={test_cycle})")

    passed, output = _run_bash(test_cmd, cwd=working_dir)
    _log_bash_to_audit(session_id, " ".join(test_cmd), "PASS" if passed else "FAIL")

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
    print("\n>>> [check_review] Scanning for review files...")
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
    """Run local CI via bash. No LLM call.

    Uses resolve_ci_command() to find or scaffold the CI script.
    Per-story scope: passes task_id as story filter so only the
    current story's tests run (lint/typecheck still run fully).
    """
    session_id = state.get("session_id", "")
    ci_cycle = state.get("ci_cycle_count", 0) + 1
    working_dir = _get_working_dir(state)
    task_id = state.get("task_id", "")

    if not _STORY_CI_ENABLED:
        print(f"\n>>> [run_ci] Skipped for {task_id} (story CI disabled)")
        return {
            "test_passed": True,
            "ci_cycle_count": ci_cycle,
            "last_ci_output": "",
            "current_phase": "run_ci",
        }

    print(f"\n>>> [run_ci] Running CI (cycle={ci_cycle})")

    _ensure_dependencies(working_dir)
    _ensure_migrations(working_dir)

    # Resolve CI command via fallback chain (script → Makefile → scaffold)
    # Pass task_id as story_id for per-story scoping
    ci_cmd = resolve_ci_command(working_dir, story_id=task_id or None)
    print(f"    Running: {' '.join(ci_cmd)}")

    # Tee CI output to a durable log file. If subprocess stdout capture
    # ever returns None (rare Windows edge case with large output),
    # the file still contains the full run so we can feed real errors
    # to fix_ci instead of a misleading "NoneType has no len" message.
    log_dir_abs = os.path.join(working_dir or ".", "checkpoints")
    os.makedirs(log_dir_abs, exist_ok=True)
    # Relative path (cwd=working_dir, forward slashes for bash on Windows)
    log_rel = f"checkpoints/ci-{task_id}-cycle-{ci_cycle}.log"
    log_abs = os.path.join(working_dir or ".", log_rel.replace("/", os.sep))
    inner = " ".join(shlex.quote(c) for c in ci_cmd)
    tee_cmd = [
        "bash", "-c",
        f"set -o pipefail; {inner} 2>&1 | tee {shlex.quote(log_rel)}",
    ]
    passed, output = _run_bash(tee_cmd, cwd=working_dir)

    # Fall back to the log file if capture returned empty or the
    # "Command execution failed: object of type 'NoneType'..." guard
    # message, so fix_ci always sees real CI output.
    needs_file_fallback = (
        not output.strip()
        or "object of type 'NoneType'" in output
    )
    if needs_file_fallback and os.path.isfile(log_abs):
        try:
            with open(log_abs, encoding="utf-8", errors="replace") as f:
                file_output = f.read()
            if file_output.strip():
                if len(file_output) > 5000:
                    marker = f"[truncated: last 5000 of {len(file_output)} chars]\n"
                    file_output = marker + file_output[-(5000 - len(marker)):]
                output = file_output
        except OSError:
            pass

    _log_bash_to_audit(session_id, "ci", "PASS" if passed else "FAIL")

    print(f"    [run_ci] Result: {'PASS' if passed else 'FAIL'} (cycle={ci_cycle})")

    if passed:
        _save_phase(state, "run_ci")

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

    # If the tree is already clean, the story's changes may have been
    # committed by a prior run (legitimate resume) OR dev_story produced
    # nothing (bug / pause-kill). Distinguish by checking git log for an
    # actual "story {task_id} complete" commit — if none exists, the
    # clean tree means no work was ever done, and we must fail.
    _, status_out = _run_bash(["git", "status", "--porcelain"], cwd=cwd)
    if not status_out.strip():
        base_task_id = task_id.replace("-retry", "")
        expected_msg = f"story {base_task_id} complete"
        _, log_out = _run_bash(
            ["git", "log", "-50", "--format=%s"],
            cwd=cwd,
        )
        prior_commit_found = any(
            line.strip() == expected_msg
            for line in log_out.splitlines()
        )
        if prior_commit_found:
            print(f"    [git_commit] Tree is clean — found prior '{expected_msg}' commit, skipping")
            clear_phase_checkpoint(_get_working_dir(state) or ".")
            return {
                "pipeline_status": "completed",
                "current_phase": "git_commit",
            }
        print(
            f"    [git_commit] Tree is clean AND no prior "
            f"'{expected_msg}' commit — dev_story produced nothing",
        )
        return {
            "pipeline_status": "failed",
            "error": (
                f"No changes to commit for story {task_id} and no prior "
                f"'{expected_msg}' commit found — dev_story silently did "
                f"no work (likely pause-kill)"
            ),
            "current_phase": "git_commit",
        }

    # Auto-generate a Drizzle migration when the story modified schema.ts
    # but didn't produce a matching drizzle/*.sql file. Without this, the
    # dev agent can silently introduce columns/tables that exist in
    # schema.ts (and in app code) but not in any migration — queries work
    # locally against a pushed DB but fail in prod because migrate-db.ts
    # has nothing to apply. Hit this twice on the chat2diagram run
    # (enabled_skill_packs, comparison_jobs + comparison_results).
    cwd_str = cwd or "."
    if _detect_project_type(cwd) == "node":
        drizzle_cfg_exists = any(
            os.path.isfile(os.path.join(cwd_str, f))
            for f in ("drizzle.config.ts", "drizzle.config.js", "drizzle.config.mjs")
        )
        if drizzle_cfg_exists:
            _, diff_out = _run_bash(
                ["git", "diff", "--name-only", "HEAD"], cwd=cwd,
            )
            changed = [ln.strip() for ln in diff_out.splitlines() if ln.strip()]
            schema_touched = any(
                f.endswith("schema.ts") and f.startswith("src/") for f in changed
            )
            # Only generate if the story touched schema AND didn't already
            # add a new migration .sql file (some stories do it properly).
            new_migration_added = any(
                f.startswith("drizzle/") and f.endswith(".sql") for f in changed
            )
            if schema_touched and not new_migration_added:
                safe_name = re.sub(r"[^a-z0-9_]+", "_", f"story_{task_id}".lower()).strip("_")
                print(
                    f"    [git_commit] schema.ts modified with no new migration — "
                    f"running drizzle-kit generate --name={safe_name}"
                )
                gen_ok, gen_out = _run_bash(
                    ["bash", "-c", f"npx drizzle-kit generate --name={shlex.quote(safe_name)}"],
                    cwd=cwd,
                    timeout=180,
                )
                if gen_ok:
                    print("    [git_commit] drizzle-kit generate succeeded")
                else:
                    logger.warning(
                        "drizzle-kit generate failed (non-blocking): %s",
                        gen_out[:500],
                    )

    # Auto-format and auto-fix before commit to avoid pre-commit hook
    # rejections from prettier/eslint. Both are non-blocking — if they
    # fail here, the hook may still catch genuine issues.
    # On Windows, `npx` is a .cmd shim that subprocess.run can't resolve
    # without a shell, so route through `bash -c` (same runtime used for
    # scripts/ci.sh elsewhere in the pipeline).
    if _detect_project_type(cwd) == "node":
        fmt_ok, fmt_out = _run_bash(
            ["bash", "-c", "npx prettier --write ."], cwd=cwd, timeout=120,
        )
        if fmt_ok:
            print("    [git_commit] prettier --write applied")
        else:
            logger.warning("prettier --write failed (non-blocking): %s", fmt_out[:200])

        lint_ok, lint_out = _run_bash(
            ["bash", "-c", "npx eslint --fix ."], cwd=cwd, timeout=300,
        )
        if lint_ok:
            print("    [git_commit] eslint --fix applied")
        else:
            logger.warning("eslint --fix failed (non-blocking): %s", lint_out[:200])

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

    # Story complete — clear phase checkpoint
    working_dir = _get_working_dir(state) or "."
    clear_phase_checkpoint(working_dir)

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
    check_story → [dev_story] → code_review → run_ci → git_commit
    (dev_story creates + implements in one invocation; skipped if status is review/done)

    Failure routing:
    - check_review has P1/P2 → fix_review → code_review
    - run_ci fail → fix_ci → run_ci retry (up to MAX_CI_CYCLES)

    Returns:
        Uncompiled StateGraph ready for .compile().
    """
    graph = StateGraph(OrchestratorState)

    # --- Non-LLM check nodes ---
    graph.add_node("check_story", check_story_exists_node)

    # --- LLM nodes (BMAD agent invocations) ---
    graph.add_node("dev_story", dev_story_node)
    graph.add_node("code_review", code_review_node)
    graph.add_node("fix_ci", fix_ci_node)

    # --- Bash nodes (no LLM) ---
    graph.add_node("run_ci", run_ci_node)
    graph.add_node("git_commit", git_commit_node)

    # --- Error handler ---
    graph.add_node("error_handler", error_handler_node)

    # --- Edges ---

    # Entry: if the epic graph loaded a phase.json matching this story,
    # jump directly to the next unfinished phase (code_review / run_ci /
    # git_commit). Otherwise fall through to check_story for the normal
    # story-status gate.
    graph.add_conditional_edges(
        START,
        route_on_entry,
        {
            "check_story": "check_story",
            "code_review": "code_review",
            "run_ci": "run_ci",
            "git_commit": "git_commit",
        },
    )
    graph.add_conditional_edges(
        "check_story",
        route_after_story_check,
        {"skip": "code_review", "dev": "dev_story"},
    )

    # Dev story (create + implement) → code review (fail → error)
    graph.add_conditional_edges(
        "dev_story",
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

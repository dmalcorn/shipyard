"""Rebuild graph (Level 1): outer epic loop.

Loads the backlog from epics.md, initializes the target project, then
iterates through each epic by invoking the EpicGraph (Level 2) as a
wrapper node. After each epic completes, tags the git repo and advances
to the next epic. Writes a final rebuild-status.md summary when all
epics are done.

Uses SQLite checkpointing so the rebuild can resume from the last
completed epic after a crash.
"""

from __future__ import annotations

import json
import logging
import operator
import os
import shutil
import sqlite3
import subprocess
import time
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.intake.backlog import load_backlog
from src.intake.checkpoint import (
    clear_batch_phase_checkpoint,
    clear_epic_phase_checkpoint,
    load_batch_phase_checkpoint,
    load_epic_phase_checkpoint,
)
from src.intake.cost_tracker import get_invocation_count, get_total_cost
from src.intake.epic_graph import EpicState, build_epic_runner
from src.intake.pause import is_pause_requested
from src.multi_agent.orchestrator import (
    _detect_project_type,
    generate_ci_script,
    get_batch_reviews_enabled,
    get_story_ci_enabled,
    set_batch_reviews_enabled,
    set_story_ci_enabled,
)
from src.pipeline_tracker import update_story_progress

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State Schema
# ---------------------------------------------------------------------------


class RebuildState(TypedDict, total=False):
    """State schema for the rebuild graph (Level 1).

    Manages epic iteration and accumulates results from all epics.
    """

    # Identity
    session_id: str
    target_dir: str

    # Epic iteration
    epics: list[dict[str, Any]]  # [{name: str, stories: [dict]}, ...]
    epic_index: int
    total_stories: int

    # Accumulated across all epics
    all_story_results: Annotated[list[dict[str, Any]], operator.add]
    stories_completed: int
    stories_failed: int
    total_interventions: int

    # Current epic output
    current_epic_status: str  # completed|failed|aborted
    current_epic_error: str
    current_epic_failed: int  # failures from just this epic, not cumulative

    # Control
    pipeline_status: str  # running|completed|failed|aborted|paused
    error: str
    start_time: float

    # Resume support — when set, load_backlog preserves these values
    resume_epic_index: int
    resume_story_index: int
    resume_stories_completed: int
    resume_stories_failed: int
    resume_total_interventions: int
    resume_story_results: list[dict[str, Any]]

    # Batch-pipeline resume support. The rolling session.json
    # checkpoint persists these so a hard kill mid-batch resumes with
    # the correct counter and pending-batch story-id list.
    resume_stories_in_current_batch: int
    resume_current_batch_story_ids: list[str]
    resume_batch_num: int


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


_VERSION_SUBCOMMAND_TOOLS = {"go"}


def _tool_version(tool: str) -> str | None:
    """Get a tool's version string, or None if not installed."""
    path = shutil.which(tool)
    if not path:
        return None
    try:
        # Most tools use --version, but some (e.g. go) use a subcommand
        flag = "version" if tool in _VERSION_SUBCOMMAND_TOOLS else "--version"
        result = subprocess.run(
            [tool, flag],
            capture_output=True, text=True, timeout=10,
        )
        version = (result.stdout or result.stderr).strip().splitlines()[0]
        return version
    except Exception:
        return "(version unknown)"


def _check_tools(
    tools: list[str],
    *,
    required: bool,
    label: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Check a list of CLI tools and record errors or warnings."""
    for tool in tools:
        version = _tool_version(tool)
        if not version:
            msg = f"'{tool}' not found on PATH ({label})"
            if required:
                errors.append(msg)
                print(f"  FAIL: {tool} ({label})")
            else:
                warnings.append(f"'{tool}' not found — CI may be limited")
                print(f"  WARN: {tool} not found ({label})")
        else:
            print(f"  OK:   {tool} — {version}")


def _auto_install_python_deps(target_dir: str, tools: list[str]) -> list[str]:
    """Attempt to pip-install missing Python tools. Returns still-missing tools."""
    missing = [t for t in tools if not shutil.which(t)]
    if not missing:
        return []

    req_file = os.path.join(target_dir, "requirements-dev.txt")
    if os.path.isfile(req_file):
        print(f"  INFO: Missing {', '.join(missing)} — installing from requirements-dev.txt...")
        install_result = subprocess.run(
            ["python", "-m", "pip", "install", "-r", req_file, "--quiet"],
            capture_output=True, text=True, timeout=120,
        )
        if install_result.returncode == 0:
            print("  OK:   pip install succeeded")
        else:
            print(f"  WARN: pip install failed: {install_result.stderr[:200]}")
    else:
        print(f"  INFO: Missing {', '.join(missing)} — attempting pip install...")
        subprocess.run(
            ["python", "-m", "pip", "install", *missing, "--quiet"],
            capture_output=True, text=True, timeout=120,
        )

    return [t for t in tools if not shutil.which(t)]


# Per-project-type tool requirements.
# "runtime" = hard requirement (errors), "dev" = soft (warnings).
_PROJECT_TOOL_REQS: dict[str, dict[str, list[str]]] = {
    "python": {
        "runtime": ["python"],
        "dev": ["ruff", "mypy", "pytest"],
    },
    "node": {
        "runtime": ["node", "npm"],
        "dev": ["npx"],
    },
    "rust": {
        "runtime": ["rustc", "cargo"],
        "dev": [],
    },
    "go": {
        "runtime": ["go"],
        "dev": ["golangci-lint"],
    },
}


def preflight_check_node(state: RebuildState) -> dict[str, Any]:
    """Verify required tools are installed before starting the pipeline.

    Uses _detect_project_type() to determine the target project's stack,
    then checks for the appropriate runtime and dev tools. Python projects
    get an auto-install attempt for missing dev tools.

    Skipped on resume — preflight was already validated on the original run.
    """
    is_resume = (
        state.get("resume_epic_index", 0) > 0
        or state.get("resume_story_index", 0) > 0
    )
    if is_resume:
        print("\n--- Preflight Check (skipped — resuming) ---\n")
        return {}

    target_dir = state.get("target_dir", "")
    errors: list[str] = []
    warnings: list[str] = []

    print("\n--- Preflight Check ---")

    # Always required: claude, git
    _check_tools(
        ["claude", "git"], required=True,
        label="always required", errors=errors, warnings=warnings,
    )

    # Optional: make (in BMAD agent tool allowlist but only invoked if
    # the target project has a Makefile)
    _check_tools(
        ["make"], required=False,
        label="BMAD agent tools (optional)", errors=errors, warnings=warnings,
    )

    # Detect project type and check appropriate tools
    project_type = _detect_project_type(target_dir or None)
    print(f"  INFO: Detected project type: {project_type}")

    reqs = _PROJECT_TOOL_REQS.get(project_type)
    if reqs:
        _check_tools(
            reqs["runtime"], required=True,
            label=f"{project_type} project", errors=errors, warnings=warnings,
        )

        # For Python projects, attempt auto-install of missing dev tools
        if project_type == "python" and target_dir:
            still_missing = _auto_install_python_deps(target_dir, reqs["dev"])
            for tool in reqs["dev"]:
                if tool in still_missing:
                    warnings.append(f"'{tool}' not found — CI may be limited")
                    print(f"  WARN: {tool} not found (optional, used by CI)")
                else:
                    version = _tool_version(tool)
                    print(f"  OK:   {tool} — {version or 'installed'}")
        elif reqs["dev"]:
            _check_tools(
                reqs["dev"], required=False,
                label=f"{project_type} dev tool", errors=errors, warnings=warnings,
            )
    else:
        # Unknown project type — check if any runtime is available
        has_any = False
        for ptype, preqs in _PROJECT_TOOL_REQS.items():
            if all(shutil.which(t) for t in preqs["runtime"]):
                print(f"  OK:   {ptype} runtime available")
                has_any = True
        if not has_any:
            errors.append("No recognized runtime found on PATH")
            print("  FAIL: no recognized runtime (python, node, rustc, go)")

    if errors:
        msg = "Preflight failed:\n" + "\n".join(f"  - {e}" for e in errors)
        print(f"\n*** ABORT: {msg}")
        return {"pipeline_status": "failed", "error": msg}

    if warnings:
        for w in warnings:
            print(f"  note: {w}")

    print("--- Preflight OK ---\n")
    return {}


def _prompt_story_reviews() -> None:
    """Ask the operator whether to run mid-epic batch code reviews.

    Skips the prompt if reviews were already disabled via --no-story-reviews
    or factory.yaml (the CLI sets the flag before the graph runs).
    The CLI flag and config key keep their original ``story``-flavoured
    names for backwards compatibility, but they now gate the batch
    pipeline (per-story review was removed in the batch-review redesign).
    """
    if not get_batch_reviews_enabled():
        print("  Story-batch code reviews: DISABLED (set by CLI/config)")
        return
    try:
        answer = input("\nRun story-batch code reviews? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        answer = ""
    if answer in ("n", "no"):
        set_batch_reviews_enabled(False)
        print("  Story-batch code reviews: DISABLED (epic-end review still active)")
    else:
        print("  Story-batch code reviews: ENABLED")


def _prompt_story_ci() -> None:
    """Ask the operator whether to run story-level CI.

    Skips the prompt if CI was already disabled via --no-story-ci
    or factory.yaml (the CLI sets the flag before the graph runs).
    """
    if not get_story_ci_enabled():
        print("  Story-level CI runs: DISABLED (set by CLI/config)")
        return
    try:
        answer = input("Run story-level CI? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt, OSError):
        answer = ""
    if answer in ("n", "no"):
        set_story_ci_enabled(False)
        print("  Story-level CI runs: DISABLED (commits proceed without CI gate)")
    else:
        print("  Story-level CI runs: ENABLED")


def load_backlog_node(state: RebuildState) -> dict[str, Any]:
    """Parse epics source (single-file or sharded form) and group stories by epic."""
    target_dir = state.get("target_dir", "")

    # Verify either single-file or sharded epics source exists. backlog.py
    # supports both forms; this is just a fast-fail check before invoking it.
    planning_dir = os.path.join(target_dir, "_bmad-output", "planning-artifacts")
    epics_md = os.path.join(planning_dir, "epics.md")
    epics_dir = os.path.join(planning_dir, "epics")

    if not (os.path.isfile(epics_md) or os.path.isdir(epics_dir)):
        print(f"\n*** ABORT: No epics source found in {planning_dir}")
        print("    BMAD agents require ONE of:")
        print(f"      {planning_dir}/epics.md           (single-file form)")
        print(f"      {planning_dir}/epics/             (sharded BMAD form)")
        print("    Place one there and re-run.")
        return {
            "pipeline_status": "failed",
            "error": (
                f"No epics source in {planning_dir} "
                "(expected epics.md or epics/ directory). "
                "BMAD agents cannot operate without it."
            ),
        }

    backlog = load_backlog(target_dir)

    # Group by epic number, preserving order
    groups: dict[str, dict[str, Any]] = {}
    for entry in backlog:
        epic_num = str(entry.get("epic_num", ""))
        if epic_num not in groups:
            groups[epic_num] = {
                "epic_num": epic_num,
                "epic_name": str(entry.get("epic_name", "")),
                "stories": [],
            }
        groups[epic_num]["stories"].append(entry)

    epics = list(groups.values())

    total_stories = sum(len(e["stories"]) for e in epics)

    # Check for resume fields — if present, restore progress counters
    resume_epic_index = state.get("resume_epic_index", 0)
    resume_story_index = state.get("resume_story_index", 0)
    is_resume = resume_epic_index > 0 or resume_story_index > 0

    if is_resume:
        print(f"\n{'='*60}")
        print(f"RESUME: Loaded {len(epics)} epics, {total_stories} stories")
        print(f"  Resuming from epic {resume_epic_index + 1}, story {resume_story_index + 1} "
              f"({state.get('resume_stories_completed', 0)} stories already done)")
        for e in epics:
            print(f"  Epic {e['epic_num']}: {e['epic_name']} ({len(e['stories'])} stories)")
        print(f"{'='*60}")

        _prompt_story_reviews()
        _prompt_story_ci()

        update_story_progress(state.get("session_id", ""),
            total_stories=total_stories,
            completed=state.get("resume_stories_completed", 0),
            failed=state.get("resume_stories_failed", 0),
            interventions=state.get("resume_total_interventions", 0),
        )

        return {
            "epics": epics,
            "epic_index": resume_epic_index,
            "total_stories": total_stories,
            "all_story_results": state.get("resume_story_results", []),
            "stories_completed": state.get("resume_stories_completed", 0),
            "stories_failed": state.get("resume_stories_failed", 0),
            "total_interventions": state.get("resume_total_interventions", 0),
            "resume_story_index": resume_story_index,
            # Forward batch-resume fields so run_epic_node can seed
            # EpicState with them on the first epic after resume.
            "resume_stories_in_current_batch": state.get(
                "resume_stories_in_current_batch", 0,
            ),
            "resume_current_batch_story_ids": state.get(
                "resume_current_batch_story_ids", [],
            ),
            "resume_batch_num": state.get("resume_batch_num", 0),
            "pipeline_status": "running",
            "start_time": time.time(),
        }

    print(f"\n{'='*60}")
    print(f"REBUILD: Loaded {len(epics)} epics, {total_stories} stories")
    for e in epics:
        print(f"  Epic {e['epic_num']}: {e['epic_name']} ({len(e['stories'])} stories)")
    print(f"{'='*60}")

    _prompt_story_reviews()
    _prompt_story_ci()

    update_story_progress(state.get("session_id", ""),
        total_stories=total_stories,
        completed=0,
        failed=0,
        interventions=0,
    )

    return {
        "epics": epics,
        "epic_index": 0,
        "total_stories": total_stories,
        "all_story_results": [],
        "stories_completed": 0,
        "stories_failed": 0,
        "total_interventions": 0,
        "pipeline_status": "running",
        "start_time": time.time(),
    }


def _redact_url(url: str) -> str:
    """Redact credentials from a git URL for safe logging.

    Turns https://token@github.com/... into https://***@github.com/...
    """
    import re
    return re.sub(r"(https?://)([^@]+)@", r"\1***@", url)


def _push_to_remotes(target_dir: str) -> None:
    """Push to origin (which may have multiple push URLs) with tags.

    Failures are logged as warnings, never fatal.
    """
    # Detect current branch, then push branch + tags in one command.
    branch_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=target_dir, capture_output=True, text=True,
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

    # GIT_TERMINAL_PROMPT=0 prevents git from hanging when credentials
    # are missing (e.g. inside Docker with plain HTTPS URLs).
    push_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        ["git", "push", "origin", branch, "--tags"],
        cwd=target_dir,
        capture_output=True,
        text=True,
        env=push_env,
    )
    if result.returncode != 0:
        logger.warning("git push to origin failed (exit %d)", result.returncode)
    else:
        logger.info("Pushed to origin")


def init_project_node(state: RebuildState) -> dict[str, Any]:
    """Initialize the target project directory with git repo and scaffold."""
    target_dir = state.get("target_dir", "")
    os.makedirs(target_dir, exist_ok=True)

    git_dir = os.path.join(target_dir, ".git")
    if not os.path.exists(git_dir):
        subprocess.run(
            ["git", "init"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        git_name = os.environ.get("GIT_AUTHOR_NAME", "Shipyard Pipeline")
        git_email = os.environ.get("GIT_AUTHOR_EMAIL", "shipyard@pipeline.local")
        subprocess.run(
            ["git", "config", "user.name", git_name],
            cwd=target_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", git_email],
            cwd=target_dir,
            capture_output=True,
            check=True,
        )

        gitignore_path = os.path.join(target_dir, ".gitignore")
        if not os.path.exists(gitignore_path):
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(
                    # Common
                    ".env\n*.log\n.DS_Store\n"
                    # Python
                    "__pycache__/\n*.pyc\n.venv/\n*.egg-info/\n"
                    "dist/\nhtmlcov/\n.coverage\n"
                    # Node
                    "node_modules/\n"
                    # Rust
                    "target/\n"
                    # Go
                    "vendor/\n"
                )

        readme_path = os.path.join(target_dir, "README.md")
        if not os.path.exists(readme_path):
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write("# Target Project\n\nGenerated by Shipyard.\n")

        claude_md_path = os.path.join(target_dir, "CLAUDE.md")
        if not os.path.exists(claude_md_path):
            with open(claude_md_path, "w", encoding="utf-8") as f:
                f.write(
                    "# Project Rules\n\n"
                    "## Working Directory\n\n"
                    "All work must be done within this project directory. "
                    "Do NOT read, search, or reference files outside of this directory. "
                    "All source documents, planning artifacts, and BMAD outputs "
                    "are located under `_bmad-output/` within this project.\n\n"
                    "## Coding Standards\n\n"
                    "Before writing or modifying code, read the coding standards at "
                    "`_bmad-output/planning-artifacts/coding-standards.md`. "
                    "All code must follow these conventions.\n"
                )

        subprocess.run(
            ["git", "add", "."],
            cwd=target_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "chore: initial project scaffold"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=True,
        )

    # Generate CI script from approved tech stack (architect-powered)
    try:
        generate_ci_script(target_dir)
        # Only commit if the CI script was newly generated (not pre-existing)
        add_result = subprocess.run(
            ["git", "add", "scripts/ci.sh"],
            cwd=target_dir, capture_output=True, text=True,
        )
        if add_result.returncode == 0:
            # Check if there's actually anything staged before committing
            diff_result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=target_dir, capture_output=True,
            )
            if diff_result.returncode != 0:
                # There are staged changes — commit them
                subprocess.run(
                    ["git", "commit", "-m", "chore: generate CI script from approved tech stack"],
                    cwd=target_dir, capture_output=True, text=True, check=True,
                )
            else:
                logger.info("CI script unchanged — nothing to commit")
                print("    [ci] CI script already up to date — nothing to commit")
    except FileNotFoundError:
        # approved-tech-stack.md missing — generate_ci_script already logged the error
        return {
            "pipeline_status": "failed",
            "error_message": (
                "Missing _bmad-output/approved-tech-stack.md in target project. "
                "Create this file before running the pipeline."
            ),
        }
    except Exception as e:
        logger.warning("CI script setup issue, continuing without it: %s", e)
        print(f"    [init] CI script setup skipped: {e}")

    # Configure origin with multiple push URLs (idempotent — safe on resume)
    push_urls = [
        url for url in [
            os.environ.get("GIT_REMOTE_ORIGIN", ""),
            os.environ.get("GIT_REMOTE_MIRROR", ""),
        ] if url
    ]
    if push_urls:
        subprocess.run(
            ["git", "remote", "remove", "origin"],
            cwd=target_dir, capture_output=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", push_urls[0]],
            cwd=target_dir, capture_output=True, check=True,
        )
        for url in push_urls[1:]:
            subprocess.run(
                ["git", "remote", "set-url", "--add", "--push", "origin", url],
                cwd=target_dir, capture_output=True, check=True,
            )
        # set-url --add --push doesn't include the original, so re-add it
        subprocess.run(
            ["git", "remote", "set-url", "--add", "--push", "origin", push_urls[0]],
            cwd=target_dir, capture_output=True, check=True,
        )
        logger.info("Configured origin with %d push URL(s)", len(push_urls))

    # Push initial scaffold
    _push_to_remotes(target_dir)

    return {}


def select_epic_node(state: RebuildState) -> dict[str, Any]:
    """Prepare state for the current epic.

    If `epic_index` is already past the last epic (e.g. the user
    re-runs --resume against a session whose final state advanced
    past the last epic on completion), short-circuit cleanly via
    `current_epic_status='all_done'` so route_after_epic ends the
    run instead of `epics[N]` raising IndexError.
    """
    epics = state.get("epics", [])
    epic_index = state.get("epic_index", 0)

    if epic_index >= len(epics):
        print(f"\n{'='*60}")
        print(f"All {len(epics)} epics already complete — nothing to do.")
        print(f"{'='*60}")
        return {
            "current_epic_status": "all_done",
            "current_epic_error": "",
        }

    epic = epics[epic_index]

    print(f"\n{'='*60}")
    print(f"EPIC {epic['epic_num']}: {epic.get('epic_name', '')} ({epic_index + 1}/{len(epics)})")
    print(f"{'='*60}")

    update_story_progress(state.get("session_id", ""),
        epic=f"Epic {epic['epic_num']}: {epic.get('epic_name', '')}",
    )

    return {
        "current_epic_status": "",
        "current_epic_error": "",
    }


def run_epic_node(state: RebuildState) -> dict[str, Any]:
    """Invoke the EpicGraph (Level 2) for the current epic.

    This is a wrapper node — it builds EpicState from RebuildState,
    invokes the compiled epic graph, and maps the results back.
    """
    session_id = state.get("session_id", "")
    target_dir = state.get("target_dir", "")
    epics = state.get("epics", [])
    epic_index = state.get("epic_index", 0)

    # Sibling guard to select_epic_node: if select_epic_node short-
    # circuited because epic_index is past the end, skip cleanly here
    # too so route_after_epic can end the run.
    if epic_index >= len(epics):
        return {}

    epic = epics[epic_index]

    # Determine starting story index — non-zero when resuming mid-epic
    resume_story_index = state.get("resume_story_index", 0)
    # Only apply resume_story_index to the first epic after resume;
    # subsequent epics always start from story 0.
    start_story = resume_story_index if resume_story_index > 0 else 0

    # Epic phase-level resume: if an epic-phase.json from a prior run
    # of this exact (session_id, epic_num) exists, pass the next
    # unfinished post-processing phase down so the epic graph can skip
    # the story loop and earlier post-processing. Stale checkpoints
    # (different session or different epic) are cleared so they can't
    # confuse later epics in this run.
    abs_target_dir = os.path.abspath(target_dir)
    resume_from_epic_phase = ""
    epic_ckpt = load_epic_phase_checkpoint(abs_target_dir)
    if epic_ckpt:
        ckpt_session = epic_ckpt.get("session_id", "")
        ckpt_epic = epic_ckpt.get("epic_num", "")
        if ckpt_session == session_id and ckpt_epic == epic["epic_num"]:
            resume_from_epic_phase = epic_ckpt.get("next_phase", "") or ""
            if resume_from_epic_phase:
                print(
                    f"    [run_epic] Epic phase checkpoint found for "
                    f"epic {epic['epic_num']}: resuming at "
                    f"{resume_from_epic_phase}",
                )
        else:
            logger.info(
                "Stale epic-phase checkpoint cleared "
                "(ckpt=%s/epic-%s, current=%s/epic-%s)",
                ckpt_session, ckpt_epic, session_id, epic["epic_num"],
            )
            clear_epic_phase_checkpoint(abs_target_dir)

    # Mid-epic batch phase resume: if a batch-phase.json from a prior
    # run of this exact (session_id, epic_num) exists, pass the next
    # unfinished batch phase down. Takes precedence over the epic-end
    # resume — a halt mid-batch must re-enter the batch pipeline before
    # the epic-end review runs. Stale checkpoints get cleared.
    resume_from_batch_phase = ""
    resume_batch_num_ckpt = 0
    batch_ckpt = load_batch_phase_checkpoint(abs_target_dir)
    if batch_ckpt:
        ckpt_session = batch_ckpt.get("session_id", "")
        ckpt_epic = batch_ckpt.get("epic_num", "")
        if ckpt_session == session_id and ckpt_epic == epic["epic_num"]:
            resume_from_batch_phase = batch_ckpt.get("next_phase", "") or ""
            resume_batch_num_ckpt = int(batch_ckpt.get("batch_num", 0))
            if resume_from_batch_phase:
                print(
                    f"    [run_epic] Batch phase checkpoint found for "
                    f"epic {epic['epic_num']} batch {resume_batch_num_ckpt}: "
                    f"resuming at {resume_from_batch_phase}",
                )
        else:
            logger.info(
                "Stale batch-phase checkpoint cleared "
                "(ckpt=%s/epic-%s, current=%s/epic-%s)",
                ckpt_session, ckpt_epic, session_id, epic["epic_num"],
            )
            clear_batch_phase_checkpoint(abs_target_dir)

    # Seed batch-pipeline state from session.json. Only the first epic
    # after a resume gets these values — subsequent epics start clean.
    is_first_epic_after_resume = (
        epic_index == state.get("resume_epic_index", 0)
        and state.get("resume_story_index", 0) > 0
    )
    if is_first_epic_after_resume:
        seed_stories_in_current_batch = state.get("resume_stories_in_current_batch", 0)
        seed_current_batch_story_ids = list(state.get("resume_current_batch_story_ids", []))
        seed_batch_num = max(
            state.get("resume_batch_num", 0),
            resume_batch_num_ckpt,
        )
    else:
        seed_stories_in_current_batch = 0
        seed_current_batch_story_ids = []
        seed_batch_num = 0

    epic_input: EpicState = {
        "session_id": session_id,
        "target_dir": abs_target_dir,
        "epic_num": epic["epic_num"],
        "epic_name": epic["epic_name"],
        "stories": epic["stories"],
        "story_index": start_story,
        "story_results": [],
        "stories_completed": 0,
        "stories_failed": 0,
        "total_interventions": 0,
        "epic_files_modified": [],
        "current_story_status": "",
        "current_story_error": "",
        "current_story_failed_phase": "",
        "current_story_retry_instruction": "",
        "epic_review_file_paths": [],
        "epic_fix_plan_path": "",
        "epic_fixes_needed": False,
        "epic_fix_cycle": 0,
        "epic_test_passed": False,
        "epic_last_test_output": "",
        "epic_last_ci_output": "",
        # Batch-review state. ``batch_num`` is seeded from session.json
        # / batch-phase.json on the first epic after a resume, otherwise
        # starts at 0 and is bumped to 1 inside ``prepare_batch_review_node``
        # before the first batch fires (per design doc edge case 5 —
        # avoids off-by-one on the first batch's filenames).
        "stories_in_current_batch": seed_stories_in_current_batch,
        "current_batch_story_ids": seed_current_batch_story_ids,
        "batch_num": seed_batch_num,
        "batch_review_stories": [],
        "batch_review_file_path": "",
        "batch_fix_plan_path": "",
        "batch_fixes_needed": False,
        "batch_test_passed": False,
        "batch_last_ci_output": "",
        "epic_status": "running",
        "error": "",
        # Rebuild-level context for story-level checkpointing
        "rebuild_epic_index": epic_index,
        "rebuild_prior_completed": state.get("stories_completed", 0),
        "rebuild_prior_failed": state.get("stories_failed", 0),
        "rebuild_prior_interventions": state.get("total_interventions", 0),
        "rebuild_prior_results": state.get("all_story_results", []),
        "resume_from_epic_phase": resume_from_epic_phase,
        "resume_from_batch_phase": resume_from_batch_phase,
    }

    compiled_epic = build_epic_runner()

    try:
        result = compiled_epic.invoke(epic_input)
        result = dict(result)
    except Exception as e:
        logger.exception(
            "Epic graph failed for epic %s: %s",
            epic.get("epic_num", "?"),
            e,
        )
        # An unhandled exception here means a crash inside the epic
        # graph (e.g. a UnicodeEncodeError in select_story_node, an
        # OSError on a checkpoint write, a langgraph internal error).
        # The legacy behavior was to mark the epic ``failed`` and
        # advance to the next epic — which on 2026-05-09 cascaded a
        # single tee-induced encoding crash through 11 epics in 17
        # seconds, advancing session.json to resume_epic_index=17 and
        # silently destroying recoverable state.
        #
        # ``epic_status="paused"`` makes ``route_after_epic`` (in this
        # same module) terminate the run cleanly so the operator gets a
        # chance to investigate before any more state mutates. The
        # halt message is printed prominently so it stands out among
        # the captured stack trace above.
        epic_num = epic.get("epic_num", "?")
        halt_message = (
            f"Epic {epic_num} graph crashed with an unhandled exception. "
            f"Run halted to preserve state. Investigate the traceback "
            f"above, fix the underlying issue, and resume."
        )
        print(f"\n*** HALT: {halt_message}")
        print(f"    Exception: {type(e).__name__}: {str(e)[:500]}")
        result = {
            "epic_status": "paused",
            "error": halt_message,
            "story_results": [],
            "stories_completed": 0,
            "stories_failed": 0,
            "total_interventions": 0,
        }

    epic_status = result.get("epic_status", "failed")
    story_results = result.get("story_results", [])
    epic_completed = result.get("stories_completed", 0)
    epic_failed = result.get("stories_failed", 0)
    epic_interventions = result.get("total_interventions", 0)

    return {
        "current_epic_status": epic_status,
        "current_epic_error": result.get("error", ""),
        "current_epic_failed": epic_failed,
        "all_story_results": story_results,
        "stories_completed": state.get("stories_completed", 0) + epic_completed,
        "stories_failed": state.get("stories_failed", 0) + epic_failed,
        "total_interventions": state.get("total_interventions", 0) + epic_interventions,
        # Clear resume_story_index so subsequent epics start from story 0
        "resume_story_index": 0,
    }


def tag_epic_node(state: RebuildState) -> dict[str, Any]:
    """Create a git tag marking epic completion — only when all stories passed."""
    target_dir = state.get("target_dir", "")
    epics = state.get("epics", [])
    epic_index = state.get("epic_index", 0)
    epic_num = epics[epic_index]["epic_num"]
    epic_status = state.get("current_epic_status", "")
    epic_failed = state.get("current_epic_failed", 0)

    # Only tag if the epic genuinely completed with no failures
    if epic_status not in ("completed", "running") or epic_failed > 0:
        reason = epic_status if epic_status else "unknown status"
        if epic_failed > 0:
            reason = f"{epic_failed} story(ies) failed"
        logger.info(
            "Skipping epic-%s-complete tag — epic not fully successful (%s)",
            epic_num, reason,
        )
        print(f"    [tag] Skipping epic-{epic_num}-complete tag — {reason}")
        _push_to_remotes(target_dir)
        return {}

    tag_name = f"epic-{epic_num}-complete"
    result = subprocess.run(
        ["git", "tag", tag_name],
        cwd=target_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("Git tag '%s' failed: %s", tag_name, result.stderr.strip())
    else:
        logger.info("Tagged epic completion: %s", tag_name)

    _push_to_remotes(target_dir)

    return {}


def write_status_node(state: RebuildState) -> dict[str, Any]:
    """Write rebuild-status.md and a rolling checkpoint after each epic.

    The rolling checkpoint ensures that even a hard kill (SIGKILL, Docker
    stop, power loss) loses at most the current epic — not all progress.
    """
    target_dir = state.get("target_dir", "")
    story_results = state.get("all_story_results", [])
    total_stories = state.get("total_stories", 0)
    total_interventions = state.get("total_interventions", 0)

    _write_rebuild_status(
        target_dir=target_dir,
        story_results=story_results,
        total_stories=total_stories,
        total_interventions=total_interventions,
    )

    # Rolling checkpoint: save resume state so a hard kill doesn't lose
    # all progress.  Only advance past the current epic if it was NOT
    # interrupted by pause/Ctrl+C — otherwise the resume would skip
    # stories that were never attempted.
    epic_index = state.get("epic_index", 0)
    epic_status = state.get("current_epic_status", "")

    if epic_status == "paused" or is_pause_requested():
        # Paused mid-epic: stay on the same epic. The per-story rolling
        # checkpoint (in process_story_result_node) already recorded
        # the correct resume_story_index for completed stories.
        logger.info("Skipping epic-level checkpoint — epic was paused/interrupted")
    else:
        # Epic ran to completion (possibly with failures): advance to next epic
        resume_state = {
            "session_id": state.get("session_id", ""),
            "target_dir": target_dir,
            "resume_epic_index": epic_index + 1,  # next epic to run
            "resume_story_index": 0,  # next epic starts from story 0
            "resume_stories_completed": state.get("stories_completed", 0),
            "resume_stories_failed": state.get("stories_failed", 0),
            "resume_total_interventions": total_interventions,
            "resume_story_results": story_results,
        }
        session_file = os.path.join(target_dir, "checkpoints", "session.json")
        os.makedirs(os.path.dirname(session_file), exist_ok=True)
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(resume_state, f, indent=2)

    return {}


def advance_epic_node(state: RebuildState) -> dict[str, Any]:
    """Advance epic_index to the next epic."""
    return {"epic_index": state.get("epic_index", 0) + 1}


def write_paused_node(state: RebuildState) -> dict[str, Any]:
    """Write rebuild-status.md and save resume state for clean resume."""
    target_dir = state.get("target_dir", "")
    story_results = state.get("all_story_results", [])
    total_stories = state.get("total_stories", 0)
    total_interventions = state.get("total_interventions", 0)
    start_time = state.get("start_time", time.time())
    elapsed = time.time() - start_time

    _write_rebuild_status(
        target_dir=target_dir,
        story_results=story_results,
        total_stories=total_stories,
        total_interventions=total_interventions,
        elapsed_seconds=elapsed,
    )

    epics = state.get("epics", [])
    epic_index = state.get("epic_index", 0)

    # Note: session.json is NOT written here — the rolling checkpoints
    # in process_story_result_node (per-story) and write_status_node
    # (per-epic) keep it up-to-date with finer granularity.

    logger.info(
        "Pipeline paused at epic %d/%d. Resume with --resume to continue.",
        epic_index + 1, len(epics),
    )
    print(f"\n*** PAUSED at epic {epic_index + 1}/{len(epics)}.")
    print("    Resume with: python -m src.main --rebuild <target_dir> --resume")

    return {"pipeline_status": "paused"}


def write_final_node(state: RebuildState) -> dict[str, Any]:
    """Write final rebuild-status.md with timing and set terminal status."""
    target_dir = state.get("target_dir", "")
    story_results = state.get("all_story_results", [])
    total_stories = state.get("total_stories", 0)
    total_interventions = state.get("total_interventions", 0)
    start_time = state.get("start_time", time.time())
    stories_failed = state.get("stories_failed", 0)

    elapsed = time.time() - start_time

    _write_rebuild_status(
        target_dir=target_dir,
        story_results=story_results,
        total_stories=total_stories,
        total_interventions=total_interventions,
        elapsed_seconds=elapsed,
        is_final=True,
    )

    status = "completed" if stories_failed == 0 else "failed"
    if state.get("current_epic_status") == "aborted":
        status = "aborted"

    logger.info("Rebuild %s: %d/%d stories completed in %.1f minutes",
                status, state.get("stories_completed", 0), total_stories, elapsed / 60)

    return {
        "pipeline_status": status,
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_load_backlog(state: RebuildState) -> str:
    """Route after load_backlog: abort if epics file missing."""
    if state.get("pipeline_status") == "failed":
        return "abort"
    return "continue"


def route_after_epic(state: RebuildState) -> str:
    """Route after epic completes: more epics, paused, or done.

    Failed stories never halt the pipeline — they are recorded and
    the next epic proceeds. Only an explicit pause (Ctrl+C) stops.
    """
    epic_status = state.get("current_epic_status", "")

    if epic_status == "paused" or is_pause_requested():
        return "paused"

    epics = state.get("epics", [])
    epic_index = state.get("epic_index", 0)

    if epic_index + 1 < len(epics):
        return "more_epics"

    return "all_done"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_rebuild_status(
    target_dir: str,
    story_results: list[dict[str, Any]],
    total_stories: int,
    total_interventions: int,
    elapsed_seconds: float | None = None,
    is_final: bool = False,
) -> None:
    """Write rebuild-status.md to the target directory."""
    completed = sum(1 for r in story_results if r.get("status") == "completed")
    failed = sum(1 for r in story_results if r.get("status") != "completed")

    lines = ["# Ship App Rebuild Status\n"]

    current_epic = ""
    for result in story_results:
        epic = result.get("epic", "")
        if epic != current_epic:
            lines.append(f"\n## Epic {epic}\n")
            current_epic = epic

        story_id = result.get("story", "?")
        story_name = result.get("story_name", "")
        status = result.get("status", "unknown")
        interventions = result.get("interventions", 0)
        suffix = f" (intervention #{interventions})" if interventions > 0 else ""
        label = f"{story_id}: {story_name}" if story_name else story_id
        lines.append(f"- Story {label} — {status}{suffix}")

    lines.append("\n## Summary\n")
    lines.append(f"Stories completed: {completed}/{total_stories}")
    lines.append(f"Stories failed: {failed}")
    lines.append(f"Interventions: {total_interventions}")

    if is_final and elapsed_seconds is not None:
        minutes = elapsed_seconds / 60
        lines.append(f"Total time: {minutes:.1f} minutes")

    cost = get_total_cost()
    invocations = get_invocation_count()
    if cost > 0:
        lines.append(f"Cost: ${cost:.2f} ({invocations} LLM calls)")

    status_path = os.path.join(target_dir, "rebuild-status.md")
    with open(status_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------


def build_rebuild_graph() -> StateGraph:  # type: ignore[type-arg]
    """Build the rebuild graph (Level 1).

    Flow:
    preflight_check → load_backlog → init_project → select_epic → run_epic →
    tag_epic → write_status → route
        → (more_epics) → advance_epic → select_epic
        → (aborted) → write_final → END
        → (all_done) → write_final → END

    Returns:
        Uncompiled StateGraph.
    """
    graph = StateGraph(RebuildState)

    # Nodes
    graph.add_node("preflight_check", preflight_check_node)
    graph.add_node("load_backlog", load_backlog_node)
    graph.add_node("init_project", init_project_node)
    graph.add_node("select_epic", select_epic_node)
    graph.add_node("run_epic", run_epic_node)
    graph.add_node("tag_epic", tag_epic_node)
    graph.add_node("write_status", write_status_node)
    graph.add_node("advance_epic", advance_epic_node)
    graph.add_node("write_paused", write_paused_node)
    graph.add_node("write_final", write_final_node)

    # Edges
    graph.add_edge(START, "preflight_check")
    graph.add_conditional_edges(
        "preflight_check",
        route_after_load_backlog,  # reuse: checks pipeline_status == "failed"
        {"continue": "load_backlog", "abort": "write_final"},
    )
    graph.add_conditional_edges(
        "load_backlog",
        route_after_load_backlog,
        {"continue": "init_project", "abort": "write_final"},
    )
    graph.add_edge("init_project", "select_epic")
    graph.add_edge("select_epic", "run_epic")
    graph.add_edge("run_epic", "tag_epic")
    graph.add_edge("tag_epic", "write_status")

    graph.add_conditional_edges(
        "write_status",
        route_after_epic,
        {
            "more_epics": "advance_epic",
            "paused": "write_paused",
            "all_done": "write_final",
        },
    )
    graph.add_edge("write_paused", END)

    graph.add_edge("advance_epic", "select_epic")
    graph.add_edge("write_final", END)

    return graph


def build_rebuild(
    checkpoints_db: str = "checkpoints/rebuild.db",
) -> CompiledStateGraph[Any]:
    """Build and compile the rebuild graph with SQLite checkpointing.

    Args:
        checkpoints_db: Path to SQLite database for checkpointing.

    Returns:
        CompiledGraph ready for invocation.
    """
    graph = build_rebuild_graph()
    os.makedirs(os.path.dirname(checkpoints_db), exist_ok=True)
    conn = sqlite3.connect(checkpoints_db, check_same_thread=False)
    memory = SqliteSaver(conn)
    return graph.compile(checkpointer=memory)

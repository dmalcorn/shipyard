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
from src.intake.cost_tracker import get_invocation_count, get_total_cost
from src.intake.epic_graph import EpicState, build_epic_runner
from src.intake.pause import is_pause_requested
from src.multi_agent.orchestrator import _detect_project_type

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

    # Control
    pipeline_status: str  # running|completed|failed|aborted|paused
    error: str
    start_time: float

    # Resume support — when set, load_backlog preserves these values
    resume_epic_index: int
    resume_stories_completed: int
    resume_stories_failed: int
    resume_total_interventions: int
    resume_story_results: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _tool_version(tool: str) -> str | None:
    """Get a tool's version string, or None if not installed."""
    path = shutil.which(tool)
    if not path:
        return None
    try:
        result = subprocess.run(
            [tool, "--version"],
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
            print(f"  OK:   pip install succeeded")
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
    """
    target_dir = state.get("target_dir", "")
    errors: list[str] = []
    warnings: list[str] = []

    print("\n--- Preflight Check ---")

    # Always required: claude, git
    _check_tools(
        ["claude", "git"], required=True,
        label="always required", errors=errors, warnings=warnings,
    )

    # Always required: make (used by BMAD agent tool permissions)
    _check_tools(
        ["make"], required=True,
        label="required by BMAD agent tools", errors=errors, warnings=warnings,
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
            print(f"  FAIL: no recognized runtime (python, node, rustc, go)")

    if errors:
        msg = "Preflight failed:\n" + "\n".join(f"  - {e}" for e in errors)
        print(f"\n*** ABORT: {msg}")
        return {"pipeline_status": "failed", "error": msg}

    if warnings:
        for w in warnings:
            print(f"  note: {w}")

    print("--- Preflight OK ---\n")
    return {}


def load_backlog_node(state: RebuildState) -> dict[str, Any]:
    """Parse epics.md and group stories by epic."""
    target_dir = state.get("target_dir", "")

    # Verify epics file exists in planning-artifacts where BMAD agents expect it
    planning_dir = os.path.join(target_dir, "_bmad-output", "planning-artifacts")
    epics_candidates = [
        f for f in os.listdir(planning_dir)
        if "epic" in f.lower() and f.endswith(".md")
    ] if os.path.isdir(planning_dir) else []

    if not epics_candidates:
        print(f"\n*** ABORT: No epics file found in {planning_dir}")
        print(f"    BMAD agents require an epics file at:")
        print(f"    {planning_dir}/epics.md")
        print(f"    Place your epics file there and re-run.")
        return {
            "pipeline_status": "failed",
            "error": f"No epics file in {planning_dir}. BMAD agents cannot operate without it.",
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
    is_resume = resume_epic_index > 0

    if is_resume:
        print(f"\n{'='*60}")
        print(f"RESUME: Loaded {len(epics)} epics, {total_stories} stories")
        print(f"  Resuming from epic index {resume_epic_index} "
              f"({state.get('resume_stories_completed', 0)} stories already done)")
        for e in epics:
            print(f"  Epic {e['epic_num']}: {e['epic_name']} ({len(e['stories'])} stories)")
        print(f"{'='*60}")

        return {
            "epics": epics,
            "epic_index": resume_epic_index,
            "total_stories": total_stories,
            "all_story_results": state.get("resume_story_results", []),
            "stories_completed": state.get("resume_stories_completed", 0),
            "stories_failed": state.get("resume_stories_failed", 0),
            "total_interventions": state.get("resume_total_interventions", 0),
            "pipeline_status": "running",
            "start_time": time.time(),
        }

    print(f"\n{'='*60}")
    print(f"REBUILD: Loaded {len(epics)} epics, {total_stories} stories")
    for e in epics:
        print(f"  Epic {e['epic_num']}: {e['epic_name']} ({len(e['stories'])} stories)")
    print(f"{'='*60}")

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
        subprocess.run(
            ["git", "config", "user.name", "Shipyard"],
            cwd=target_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "shipyard@localhost"],
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

    return {}


def select_epic_node(state: RebuildState) -> dict[str, Any]:
    """Prepare state for the current epic."""
    epics = state.get("epics", [])
    epic_index = state.get("epic_index", 0)
    epic = epics[epic_index]

    print(f"\n{'='*60}")
    print(f"EPIC {epic['epic_num']}: {epic.get('epic_name', '')} ({epic_index + 1}/{len(epics)})")
    print(f"{'='*60}")

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
    epic = epics[epic_index]

    epic_input: EpicState = {
        "session_id": session_id,
        "target_dir": os.path.abspath(target_dir),
        "epic_num": epic["epic_num"],
        "epic_name": epic["epic_name"],
        "stories": epic["stories"],
        "story_index": 0,
        "story_results": [],
        "stories_completed": 0,
        "stories_failed": 0,
        "total_interventions": 0,
        "epic_files_modified": [],
        "current_story_status": "",
        "current_story_error": "",
        "current_story_retry_instruction": "",
        "epic_review_file_paths": [],
        "epic_fix_plan_path": "",
        "epic_fixes_needed": False,
        "epic_fix_cycle": 0,
        "epic_test_passed": False,
        "epic_last_test_output": "",
        "epic_last_ci_output": "",
        "epic_status": "running",
        "error": "",
    }

    compiled_epic = build_epic_runner()

    try:
        result = compiled_epic.invoke(epic_input)
        result = dict(result)
    except Exception as e:
        logger.exception("Epic graph failed for %s: %s", epic["name"], e)
        result = {
            "epic_status": "failed",
            "error": str(e),
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
        "all_story_results": story_results,
        "stories_completed": state.get("stories_completed", 0) + epic_completed,
        "stories_failed": state.get("stories_failed", 0) + epic_failed,
        "total_interventions": state.get("total_interventions", 0) + epic_interventions,
    }


def tag_epic_node(state: RebuildState) -> dict[str, Any]:
    """Create a git tag marking epic completion."""
    target_dir = state.get("target_dir", "")
    epics = state.get("epics", [])
    epic_index = state.get("epic_index", 0)
    epic_num = epics[epic_index]["epic_num"]

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

    return {}


def write_status_node(state: RebuildState) -> dict[str, Any]:
    """Write rebuild-status.md after the current epic."""
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
    epic_status = state.get("current_epic_status", "")

    # If pause happened mid-epic, the current epic is incomplete.
    # On resume, we re-run the current epic from scratch (the completed
    # stories within it are idempotent via git — already committed).
    # If pause happened between epics, advance past the completed one.
    if epic_status == "paused":
        resume_epic_index = epic_index  # Re-run current epic
    else:
        resume_epic_index = epic_index + 1  # Current epic finished; start next

    # Save resume state to session file
    resume_state = {
        "session_id": state.get("session_id", ""),
        "target_dir": target_dir,
        "resume_epic_index": resume_epic_index,
        "resume_stories_completed": state.get("stories_completed", 0),
        "resume_stories_failed": state.get("stories_failed", 0),
        "resume_total_interventions": total_interventions,
        "resume_story_results": story_results,
    }
    session_file = "checkpoints/session.json"
    os.makedirs(os.path.dirname(session_file), exist_ok=True)
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(resume_state, f, indent=2)

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
    """Route after epic completes: more epics, aborted, paused, or done."""
    epic_status = state.get("current_epic_status", "")

    if epic_status == "aborted":
        return "aborted"

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
            "aborted": "write_final",
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

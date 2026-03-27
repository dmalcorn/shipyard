"""Autonomous rebuild loop for target projects.

Thin wrapper around the rebuild graph (Level 1) and epic graph (Level 2).
Preserves the original run_rebuild() interface for backwards compatibility
with src/main.py and the FastAPI endpoints.

The actual graph logic lives in:
- src/intake/rebuild_graph.py (Level 1: epic loop)
- src/intake/epic_graph.py (Level 2: story loop + epic post-processing)
- src/multi_agent/orchestrator.py (Level 3: per-story TDD pipeline)
"""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any

from src.intake.backlog import load_backlog
from src.intake.cost_tracker import get_invocation_count, get_total_cost, reset as reset_cost
from src.intake.intervention_log import InterventionLogger
from src.intake.rebuild_graph import RebuildState, build_rebuild
from src.pipeline_tracker import (
    advance_stage,
    complete_pipeline,
    fail_pipeline,
    start_pipeline,
)
from src.web_relay import get_relay, init_relay, stop_relay

logger = logging.getLogger(__name__)

DEFAULT_TARGET_DIR = "./target/"


# ---------------------------------------------------------------------------
# Print interceptor — tees print() output to the web relay
# ---------------------------------------------------------------------------


class _RelayWriter(io.TextIOBase):
    """Wraps stdout to tee every print() line to the web relay."""

    def __init__(self, original: Any) -> None:
        self._original = original

    def write(self, text: str) -> int:
        self._original.write(text)
        relay = get_relay()
        if relay and text.strip():
            relay.push(text.rstrip("\n"))
        return len(text)

    def flush(self) -> None:
        self._original.flush()

    # Forward attributes so logging/subprocess still work
    @property
    def encoding(self) -> str:
        return getattr(self._original, "encoding", "utf-8")

    def fileno(self) -> int:
        return self._original.fileno()

    def isatty(self) -> bool:
        return self._original.isatty()


class _RelayLoggingHandler(logging.Handler):
    """Sends logging records to the web relay."""

    def emit(self, record: logging.LogRecord) -> None:
        relay = get_relay()
        if relay:
            msg = self.format(record)
            event_type = "error" if record.levelno >= logging.ERROR else "log"
            relay.push(msg, event_type=event_type)


def run_rebuild(
    target_dir: str,
    session_id: str,
    on_intervention: Callable[[str], str | None] | None = None,
    intervention_logger: InterventionLogger | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Run the full rebuild loop over the target project's backlog.

    Loads the backlog from {target_dir}/epics.md, then invokes the
    rebuild graph which iterates through epics and stories using
    LangGraph with SQLite checkpointing.

    Args:
        target_dir: Path to the target project directory.
        session_id: Session ID for trace linking.
        on_intervention: Optional callback for intervention handling.
            Note: With the graph-based flow, interventions use LangGraph's
            interrupt() pattern. This callback is kept for CLI compatibility.
        intervention_logger: Optional InterventionLogger for auto-recovery tracking.
        resume: If True, attempt to resume from the last checkpoint for
            this session_id instead of starting from scratch.

    Returns:
        Dict with keys: stories_completed, stories_failed, interventions,
        total_stories, elapsed_seconds, pipeline_status.
    """
    start_time = time.time()
    reset_cost()
    start_pipeline(session_id, "rebuild")

    # Start web relay (if configured via env vars)
    relay = init_relay(session_id, pipeline_type="rebuild")

    # Tee stdout to relay so all print() output is captured
    original_stdout = sys.stdout
    relay_handler: _RelayLoggingHandler | None = None
    if relay:
        sys.stdout = _RelayWriter(original_stdout)  # type: ignore[assignment]
        relay_handler = _RelayLoggingHandler()
        fmt = logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
        relay_handler.setFormatter(fmt)
        logging.getLogger().addHandler(relay_handler)
        if resume:
            relay.push("--- Pipeline resumed ---", event_type="stage")
        relay.push_stage("loading_backlog")

    try:
        return _run_rebuild_core(session_id, target_dir, start_time, resume=resume)
    finally:
        # Always restore stdout and clean up relay
        sys.stdout = original_stdout
        if relay_handler:
            logging.getLogger().removeHandler(relay_handler)


def _load_resume_state() -> dict[str, Any] | None:
    """Load resume state from the session file, or None if not found."""
    session_file = "checkpoints/session.json"
    if not os.path.isfile(session_file):
        return None
    try:
        with open(session_file, encoding="utf-8") as f:
            data = json.load(f)
        # Only valid if it has resume fields
        if data.get("resume_epic_index", 0) > 0:
            return data
        return None
    except (json.JSONDecodeError, OSError):
        return None


def _run_rebuild_core(
    session_id: str,
    target_dir: str,
    start_time: float,
    resume: bool = False,
) -> dict[str, Any]:
    """Core rebuild logic. Relay teardown handled by caller."""
    # Pre-flight check: does the backlog exist?
    advance_stage(session_id, "loading_backlog")
    try:
        backlog = load_backlog(target_dir)
    except FileNotFoundError as e:
        logger.error("Backlog not found: %s", e)
        fail_pipeline(session_id, str(e))
        stop_relay("failed")
        return {
            "stories_completed": 0,
            "stories_failed": 0,
            "interventions": 0,
            "total_stories": 0,
            "elapsed_seconds": 0.0,
            "error": str(e),
        }
    if not backlog:
        complete_pipeline(session_id)
        stop_relay("completed")
        return {
            "stories_completed": 0,
            "stories_failed": 0,
            "interventions": 0,
            "total_stories": 0,
            "elapsed_seconds": 0.0,
        }

    # Build initial state — inject resume fields if resuming
    advance_stage(session_id, "init_project")

    initial_state: RebuildState = {
        "session_id": session_id,
        "target_dir": target_dir,
        "epics": [],
        "epic_index": 0,
        "total_stories": 0,
        "all_story_results": [],
        "stories_completed": 0,
        "stories_failed": 0,
        "total_interventions": 0,
        "current_epic_status": "",
        "current_epic_error": "",
        "pipeline_status": "running",
        "error": "",
        "start_time": start_time,
    }

    if resume:
        resume_data = _load_resume_state()
        if resume_data:
            initial_state["resume_epic_index"] = resume_data.get(
                "resume_epic_index", 0,
            )
            initial_state["resume_stories_completed"] = resume_data.get(
                "resume_stories_completed", 0,
            )
            initial_state["resume_stories_failed"] = resume_data.get(
                "resume_stories_failed", 0,
            )
            initial_state["resume_total_interventions"] = resume_data.get(
                "resume_total_interventions", 0,
            )
            initial_state["resume_story_results"] = resume_data.get(
                "resume_story_results", [],
            )
            logger.info(
                "Resume state loaded: starting at epic index %d, %d stories already done",
                initial_state["resume_epic_index"],
                initial_state["resume_stories_completed"],
            )
        else:
            logger.info("No resume state found — starting from the beginning.")

    try:
        # Use a fresh thread_id each invocation so LangGraph doesn't
        # try to replay from a completed graph's checkpoint.
        compiled = build_rebuild()
        thread_id = str(uuid.uuid4())
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        result = compiled.invoke(initial_state, config=config)  # type: ignore[call-overload]
        result = dict(result)
    except subprocess.CalledProcessError as e:
        logger.error("Git initialization failed: %s", e)
        fail_pipeline(session_id, str(e))
        stop_relay("failed")
        return {
            "stories_completed": 0,
            "stories_failed": 0,
            "interventions": 0,
            "total_stories": 0,
            "elapsed_seconds": 0.0,
            "error": f"Git initialization failed: {e}",
        }
    except Exception as e:
        logger.exception("Rebuild graph failed: %s", e)
        fail_pipeline(session_id, str(e))
        stop_relay("failed")
        return {
            "stories_completed": 0,
            "stories_failed": 0,
            "interventions": 0,
            "total_stories": 0,
            "elapsed_seconds": time.time() - start_time,
            "error": str(e),
        }

    return _build_result(result, session_id, start_time)


def _build_result(
    result: dict[str, Any],
    session_id: str,
    start_time: float,
) -> dict[str, Any]:
    """Build the return dict from graph result, updating pipeline tracker."""
    elapsed = time.time() - start_time
    stories_failed = result.get("stories_failed", 0)
    pipeline_status = result.get("pipeline_status", "unknown")

    if pipeline_status == "paused":
        # Don't mark as failed/completed — it will be resumed
        relay = get_relay()
        if relay:
            relay.push("--- Pipeline paused ---", event_type="stage")
        stop_relay("paused")
    elif stories_failed > 0:
        fail_pipeline(session_id, f"{stories_failed} stories failed")
        stop_relay("failed")
    else:
        complete_pipeline(session_id)
        stop_relay("completed")

    return {
        "stories_completed": result.get("stories_completed", 0),
        "stories_failed": stories_failed,
        "interventions": result.get("total_interventions", 0),
        "total_stories": result.get("total_stories", 0),
        "elapsed_seconds": elapsed,
        "pipeline_status": pipeline_status,
        "total_cost_usd": get_total_cost(),
        "llm_invocations": get_invocation_count(),
    }


# ---------------------------------------------------------------------------
# Legacy helpers — kept for test compatibility
# ---------------------------------------------------------------------------


def _group_by_epic(
    backlog: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group backlog entries by epic number, preserving order."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in backlog:
        epic_num = str(entry.get("epic_num", ""))
        if epic_num not in groups:
            groups[epic_num] = []
        groups[epic_num].append(entry)
    return list(groups.items())


def _init_target_project(target_dir: str) -> None:
    """Initialize the target project directory with git repo and scaffold."""
    os.makedirs(target_dir, exist_ok=True)

    git_dir = os.path.join(target_dir, ".git")
    if not os.path.exists(git_dir):
        try:
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

            readme_path = os.path.join(target_dir, "README.md")
            if not os.path.exists(readme_path):
                with open(readme_path, "w", encoding="utf-8") as f:
                    f.write("# Target Project\n\nGenerated by Shipyard.\n")

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
        except subprocess.CalledProcessError as e:
            logger.error("Git initialization failed: %s", e.stderr or e)
            raise


def _git_tag_epic(target_dir: str, epic_name: str) -> None:
    """Create a git tag marking epic completion."""
    tag_name = f"epic-{epic_name}-complete"
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


def _write_rebuild_status(
    target_dir: str,
    story_results: list[dict[str, Any]],
    total_stories: int,
    total_interventions: int,
    elapsed_seconds: float | None = None,
    is_final: bool = False,
) -> None:
    """Write rebuild-status.md to the target directory."""
    completed = sum(1 for r in story_results if r["status"] == "completed")
    failed = sum(1 for r in story_results if r["status"] != "completed")

    lines = ["# Ship App Rebuild Status\n"]

    current_epic = ""
    for result in story_results:
        epic = result.get("epic", "")
        if epic != current_epic:
            lines.append(f"\n## Epic {epic}\n")
            current_epic = epic

        story_id = result.get("story", "?")
        story_name = result.get("story_name", "")
        status = result["status"]
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

    status_path = os.path.join(target_dir, "rebuild-status.md")
    with open(status_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _detect_auto_recovery(
    result: dict[str, Any],
    intervention_logger: InterventionLogger,
    epic_name: str,
    story_name: str,
) -> None:
    """Log auto-recovery if the pipeline succeeded after retries."""
    test_cycles = result.get("test_cycle_count", 0)
    ci_cycles = result.get("ci_cycle_count", 0)
    edit_retries = result.get("edit_retry_count", 0)

    if test_cycles > 1:
        intervention_logger.log_auto_recovery(
            epic=epic_name,
            story=story_name,
            phase="unit_test",
            what_failed=f"Unit tests failed on cycle 1 (total cycles: {test_cycles})",
            how_recovered=f"Agent fixed the issue and tests passed on cycle {test_cycles}",
        )
    if ci_cycles > 1:
        intervention_logger.log_auto_recovery(
            epic=epic_name,
            story=story_name,
            phase="ci",
            what_failed=f"CI checks failed on cycle 1 (total cycles: {ci_cycles})",
            how_recovered=f"Agent fixed the issue and CI passed on cycle {ci_cycles}",
        )
    if edit_retries > 1:
        intervention_logger.log_auto_recovery(
            epic=epic_name,
            story=story_name,
            phase="dev",
            what_failed=f"Edit failed on attempt 1 (total attempts: {edit_retries})",
            how_recovered=f"Agent resolved the edit issue on attempt {edit_retries}",
        )


def _run_story_pipeline(
    target_dir: str,
    session_id: str,
    task_id: str,
    task_description: str,
    compiled: Any | None = None,
) -> dict[str, Any]:
    """Invoke the TDD orchestrator for a single story.

    Legacy helper kept for test compatibility. The graph-based flow
    uses epic_graph.run_story_node() instead.
    """
    from src.multi_agent.orchestrator import OrchestratorState, build_orchestrator

    if compiled is None:
        compiled = build_orchestrator()

    abs_target_dir = os.path.abspath(target_dir)

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
        return dict(result)
    except Exception as e:
        logger.exception("Pipeline failed for %s: %s", task_id, e)
        return {"pipeline_status": "failed", "error": str(e)}

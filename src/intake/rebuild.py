"""Autonomous rebuild loop for target projects.

Iterates over the generated backlog, invoking the TDD orchestrator pipeline
for each story. Handles intervention detection, progress tracking, git
tagging, and project initialization.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Callable
from typing import Any

from src.intake.backlog import load_backlog
from src.intake.intervention_log import InterventionLogger

logger = logging.getLogger(__name__)

DEFAULT_TARGET_DIR = "./target/"


def run_rebuild(
    target_dir: str,
    session_id: str,
    on_intervention: Callable[[str], str | None] | None = None,
    intervention_logger: InterventionLogger | None = None,
) -> dict[str, Any]:
    """Run the full rebuild loop over the target project's backlog.

    Loads the backlog from {target_dir}/epics.md, initializes the target
    project, then invokes the TDD orchestrator for each story. Tracks
    progress in {target_dir}/rebuild-status.md.

    Args:
        target_dir: Path to the target project directory.
        session_id: Session ID for trace linking.
        on_intervention: Optional callback for intervention handling.
            Signature: (failure_report: str) -> str | None
            Returns fix instruction or None to skip.
        intervention_logger: Optional InterventionLogger for auto-recovery tracking.

    Returns:
        Dict with keys: stories_completed, stories_failed, interventions,
        total_stories, elapsed_seconds.
    """
    start_time = time.time()

    # Load backlog
    try:
        backlog = load_backlog(target_dir)
    except FileNotFoundError as e:
        logger.error("Backlog not found: %s", e)
        return {
            "stories_completed": 0,
            "stories_failed": 0,
            "interventions": 0,
            "total_stories": 0,
            "elapsed_seconds": 0.0,
            "error": str(e),
        }
    if not backlog:
        return {
            "stories_completed": 0,
            "stories_failed": 0,
            "interventions": 0,
            "total_stories": 0,
            "elapsed_seconds": 0.0,
        }

    # Initialize the target project
    _init_target_project(target_dir)

    # Group stories by epic
    epics = _group_by_epic(backlog)

    stories_completed = 0
    stories_failed = 0
    total_interventions = 0
    story_results: list[dict[str, Any]] = []

    for epic_name, stories in epics:
        for story_entry in stories:
            story_name = story_entry["story"]
            description = story_entry["description"]
            criteria = story_entry.get("acceptance_criteria", [])
            criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else ""

            task_description = (
                f"Story: {story_name}\n"
                f"Epic: {epic_name}\n"
                f"{description}\n\n"
                f"Acceptance Criteria:\n{criteria_text}"
            )

            logger.info("Starting story: %s (epic: %s)", story_name, epic_name)

            # Invoke the orchestrator pipeline
            result = _run_story_pipeline(
                target_dir=target_dir,
                session_id=session_id,
                task_id=f"{epic_name}-{story_name}".replace(" ", "-").lower(),
                task_description=task_description,
            )

            status = result.get("pipeline_status", "failed")
            intervention_count = 0

            # Auto-recovery detection: pipeline succeeded but had retries
            if status == "completed" and intervention_logger:
                _detect_auto_recovery(result, intervention_logger, epic_name, story_name)

            # Intervention loop
            if status == "failed" and on_intervention:
                error = result.get("error", "Unknown failure")
                fix_instruction = on_intervention(error)
                intervention_count += 1
                total_interventions += 1

                if fix_instruction and fix_instruction.lower() != "skip":
                    # Retry with fix instruction appended
                    retry_description = (
                        f"{task_description}\n\nINTERVENTION FIX INSTRUCTION:\n{fix_instruction}"
                    )
                    result = _run_story_pipeline(
                        target_dir=target_dir,
                        session_id=session_id,
                        task_id=f"{epic_name}-{story_name}-retry".replace(" ", "-").lower(),
                        task_description=retry_description,
                    )
                    status = result.get("pipeline_status", "failed")

            if status == "completed":
                stories_completed += 1
            else:
                stories_failed += 1

            story_results.append(
                {
                    "epic": epic_name,
                    "story": story_name,
                    "status": status,
                    "interventions": intervention_count,
                }
            )

            # Update progress file
            _write_rebuild_status(
                target_dir=target_dir,
                story_results=story_results,
                total_stories=len(backlog),
                total_interventions=total_interventions,
            )

        # Tag epic completion
        _git_tag_epic(target_dir, epic_name)

    elapsed = time.time() - start_time

    # Write final summary
    _write_rebuild_status(
        target_dir=target_dir,
        story_results=story_results,
        total_stories=len(backlog),
        total_interventions=total_interventions,
        elapsed_seconds=elapsed,
        is_final=True,
    )

    return {
        "stories_completed": stories_completed,
        "stories_failed": stories_failed,
        "interventions": total_interventions,
        "total_stories": len(backlog),
        "elapsed_seconds": elapsed,
    }


def _detect_auto_recovery(
    result: dict[str, Any],
    intervention_logger: InterventionLogger,
    epic_name: str,
    story_name: str,
) -> None:
    """Log auto-recovery if the pipeline succeeded after retries.

    Checks test_cycle_count, ci_cycle_count, and edit_retry_count in the
    orchestrator result. If any count > 1, the agent recovered from a failure
    without human help.

    Args:
        result: Orchestrator result dict with retry counts.
        intervention_logger: Logger to record auto-recoveries.
        epic_name: Current epic name.
        story_name: Current story name.
    """
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
) -> dict[str, Any]:
    """Invoke the TDD orchestrator for a single story.

    Args:
        target_dir: Target project directory (working_dir for tools).
        session_id: Session ID for trace linking.
        task_id: Unique task identifier.
        task_description: Full story description with acceptance criteria.

    Returns:
        Orchestrator result dict with pipeline_status.
    """
    from src.multi_agent.orchestrator import OrchestratorState, build_orchestrator

    compiled = build_orchestrator()

    initial_state: OrchestratorState = {
        "task_id": task_id,
        "task_description": task_description,
        "session_id": session_id,
        "context_files": [],
        "source_files": [],
        "test_files": [],
        "files_modified": [],
        "current_phase": "test",
        "pipeline_status": "running",
        "review_file_paths": [],
        "fix_plan_path": "",
        "test_cycle_count": 0,
        "ci_cycle_count": 0,
        "edit_retry_count": 0,
        "test_passed": False,
        "last_test_output": "",
        "last_ci_output": "",
        "error_log": [],
        "error": "",
    }

    try:
        result = compiled.invoke(initial_state)
        return dict(result)
    except Exception as e:
        logger.exception("Pipeline failed for %s: %s", task_id, e)
        return {"pipeline_status": "failed", "error": str(e)}


def _init_target_project(target_dir: str) -> None:
    """Initialize the target project directory with git repo and scaffold.

    Args:
        target_dir: Path to the target project directory.
    """
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

            # Set local git config for environments without global config
            subprocess.run(
                ["git", "config", "user.name", "Shipyard"],
                cwd=target_dir,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "shipyard@localhost"],
                cwd=target_dir,
                capture_output=True,
            )

            # Create minimal scaffold
            readme_path = os.path.join(target_dir, "README.md")
            if not os.path.exists(readme_path):
                with open(readme_path, "w", encoding="utf-8") as f:
                    f.write("# Target Project\n\nGenerated by Shipyard.\n")

            # Initial commit
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
    """Create a git tag marking epic completion.

    Args:
        target_dir: Target project directory.
        epic_name: Epic name for the tag.
    """
    tag_name = f"epic-{epic_name.replace(' ', '-').lower()}-complete"
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


def _group_by_epic(
    backlog: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group backlog entries by epic name, preserving order.

    Args:
        backlog: Parsed backlog entries.

    Returns:
        List of (epic_name, stories) tuples.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in backlog:
        epic = str(entry.get("epic", ""))
        if epic not in groups:
            groups[epic] = []
        groups[epic].append(entry)
    return list(groups.items())


def _write_rebuild_status(
    target_dir: str,
    story_results: list[dict[str, Any]],
    total_stories: int,
    total_interventions: int,
    elapsed_seconds: float | None = None,
    is_final: bool = False,
) -> None:
    """Write rebuild-status.md to the target directory.

    Args:
        target_dir: Target project directory.
        story_results: List of story result dicts.
        total_stories: Total number of stories in backlog.
        total_interventions: Total intervention count.
        elapsed_seconds: Total elapsed time (only for final).
        is_final: Whether this is the final status update.
    """
    completed = sum(1 for r in story_results if r["status"] == "completed")
    failed = sum(1 for r in story_results if r["status"] != "completed")

    lines = ["# Ship App Rebuild Status\n"]

    # Group results by epic
    current_epic = ""
    for result in story_results:
        epic = result["epic"]
        if epic != current_epic:
            lines.append(f"\n## Epic: {epic}\n")
            current_epic = epic

        status = result["status"]
        interventions = result.get("interventions", 0)
        suffix = f" (intervention #{interventions})" if interventions > 0 else ""
        lines.append(f"- Story: {result['story']} — {status}{suffix}")

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

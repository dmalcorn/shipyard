"""Phase-level checkpoint storage for pipeline resume.

Enables resume from the exact phase within a story or epic
post-processing chain. Written by the pipeline code (not agents)
after each successful phase, so it is always reliable.

Session-level checkpoints are stored in checkpoints/session.json
(existing mechanism in rebuild_graph.py). This module adds:
  - checkpoints/phase.json — per-story phase progress
  - checkpoints/epic-phase.json — epic post-processing progress
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase-level checkpoint (per-story granularity)
# ---------------------------------------------------------------------------

# Ordered list of phases in the orchestrator pipeline.
# Must match the node names in orchestrator.py's build_orchestrator_graph().
PHASE_ORDER = [
    "dev_story",
    "code_review",
    "run_ci",
    "git_commit",
]


def save_phase_checkpoint(
    session_id: str,
    target_dir: str,
    story_id: str,
    completed_phase: str,
) -> None:
    """Record that a phase completed successfully for the current story.

    Args:
        session_id: Pipeline session ID.
        target_dir: Absolute path to the target project directory.
        story_id: Story identifier (e.g. "2-6").
        completed_phase: The phase that just completed (e.g. "code_review").
    """
    phase_file = os.path.join(target_dir, "checkpoints", "phase.json")
    os.makedirs(os.path.dirname(phase_file), exist_ok=True)

    data: dict[str, str] = {
        "session_id": session_id,
        "story_id": story_id,
        "completed_phase": completed_phase,
    }

    # Determine next phase for convenience
    try:
        idx = PHASE_ORDER.index(completed_phase)
        if idx + 1 < len(PHASE_ORDER):
            data["next_phase"] = PHASE_ORDER[idx + 1]
        else:
            data["next_phase"] = ""  # story complete
    except ValueError:
        data["next_phase"] = ""

    with open(phase_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    logger.debug(
        "Phase checkpoint saved: story=%s, completed=%s, next=%s",
        story_id, completed_phase, data.get("next_phase", ""),
    )


def load_phase_checkpoint(target_dir: str) -> dict[str, Any] | None:
    """Load the phase-level checkpoint for the current story.

    Returns:
        Dict with keys: session_id, story_id, completed_phase, next_phase.
        Returns None if no phase checkpoint exists.
    """
    phase_file = os.path.join(target_dir, "checkpoints", "phase.json")
    if not os.path.isfile(phase_file):
        return None
    try:
        with open(phase_file, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read phase checkpoint %s: %s", phase_file, e)
        return None


def clear_phase_checkpoint(target_dir: str) -> None:
    """Remove the phase checkpoint file (e.g. when a story completes)."""
    phase_file = os.path.join(target_dir, "checkpoints", "phase.json")
    if os.path.isfile(phase_file):
        os.remove(phase_file)
        logger.debug("Phase checkpoint cleared: %s", phase_file)


# ---------------------------------------------------------------------------
# Epic-level phase checkpoint (post-processing granularity)
# ---------------------------------------------------------------------------

# Ordered list of epic post-processing phases.
# These run AFTER all stories in an epic complete.
EPIC_PHASE_ORDER = [
    "epic_reviews",      # parallel BMAD + Claude reviews, collection
    "epic_analysis",     # analyze & classify findings (Category A/B)
    "epic_category_a",   # apply Category A (obvious) fixes
    "epic_architect",    # architect reviews Category B items
    "epic_fix",          # apply architect-approved fixes
    "epic_ci",           # full CI run
    "epic_git_commit",   # commit epic review fixes
]


def save_epic_phase_checkpoint(
    session_id: str,
    target_dir: str,
    epic_num: str,
    completed_phase: str,
) -> None:
    """Record that an epic post-processing phase completed successfully.

    Stored in a separate file (epic-phase.json) from the story-level
    phase.json so they don't conflict.

    Args:
        session_id: Pipeline session ID.
        target_dir: Absolute path to the target project directory.
        epic_num: Epic identifier (e.g. "2").
        completed_phase: The epic phase that just completed.
    """
    phase_file = os.path.join(target_dir, "checkpoints", "epic-phase.json")
    os.makedirs(os.path.dirname(phase_file), exist_ok=True)

    data: dict[str, str] = {
        "session_id": session_id,
        "epic_num": epic_num,
        "completed_phase": completed_phase,
    }

    try:
        idx = EPIC_PHASE_ORDER.index(completed_phase)
        if idx + 1 < len(EPIC_PHASE_ORDER):
            data["next_phase"] = EPIC_PHASE_ORDER[idx + 1]
        else:
            data["next_phase"] = ""  # epic post-processing complete
    except ValueError:
        data["next_phase"] = ""

    with open(phase_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    logger.debug(
        "Epic phase checkpoint saved: epic=%s, completed=%s, next=%s",
        epic_num, completed_phase, data.get("next_phase", ""),
    )


def load_epic_phase_checkpoint(target_dir: str) -> dict[str, Any] | None:
    """Load the epic-level phase checkpoint.

    Returns:
        Dict with keys: session_id, epic_num, completed_phase, next_phase.
        Returns None if no epic phase checkpoint exists.
    """
    phase_file = os.path.join(target_dir, "checkpoints", "epic-phase.json")
    if not os.path.isfile(phase_file):
        return None
    try:
        with open(phase_file, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read epic phase checkpoint %s: %s", phase_file, e)
        return None


def clear_epic_phase_checkpoint(target_dir: str) -> None:
    """Remove the epic phase checkpoint (e.g. when epic completes)."""
    phase_file = os.path.join(target_dir, "checkpoints", "epic-phase.json")
    if os.path.isfile(phase_file):
        os.remove(phase_file)
        logger.debug("Epic phase checkpoint cleared: %s", phase_file)

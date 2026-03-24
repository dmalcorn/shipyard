"""In-memory pipeline stage tracker for real-time dashboard updates.

Tracks the current stage of running pipelines (intake, rebuild, instruct)
so the dashboard can poll for real server-side state instead of guessing.
Safe with single-worker uvicorn (module-level dict, no locking needed).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineStage:
    """Tracks the current stage of a running pipeline."""

    pipeline_type: str
    stages: list[str]
    current_stage: str = ""
    status: str = "running"
    error: str = ""
    started_at: float = field(default_factory=time.time)
    story_progress: dict[str, Any] = field(default_factory=dict)

    @property
    def stage_index(self) -> int:
        """Zero-based index of the current stage."""
        if self.current_stage in self.stages:
            return self.stages.index(self.current_stage)
        return -1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the status endpoint."""
        return {
            "pipeline": self.pipeline_type,
            "stage": self.current_stage,
            "stage_index": self.stage_index,
            "total_stages": len(self.stages),
            "stages": self.stages,
            "status": self.status,
            "error": self.error,
            "story_progress": self.story_progress,
            "elapsed_seconds": round(time.time() - self.started_at, 1),
        }


# Module-level dict — safe with single-worker uvicorn
_stages: dict[str, PipelineStage] = {}

# Stage definitions per pipeline type
INSTRUCT_STAGES = ["user_input", "agent_node", "should_continue", "tool_calls", "response"]
INTAKE_STAGES = ["reading_specs", "summarizing", "generating_backlog", "writing_output", "complete"]
REBUILD_STAGES = ["loading_backlog", "init_project", "tdd_pipeline", "testing", "reviewing", "git_tag", "complete"]


def start_pipeline(session_id: str, pipeline_type: str) -> PipelineStage:
    """Register a new pipeline run and set it to its first stage.

    Args:
        session_id: Unique session identifier.
        pipeline_type: One of 'instruct', 'intake', 'rebuild'.

    Returns:
        The created PipelineStage instance.
    """
    stage_map = {
        "instruct": INSTRUCT_STAGES,
        "intake": INTAKE_STAGES,
        "rebuild": REBUILD_STAGES,
    }
    stages = stage_map.get(pipeline_type, [])
    entry = PipelineStage(
        pipeline_type=pipeline_type,
        stages=list(stages),
        current_stage=stages[0] if stages else "",
    )
    _stages[session_id] = entry
    return entry


def advance_stage(session_id: str, stage_name: str) -> None:
    """Move a pipeline to a specific stage.

    Args:
        session_id: Session to update.
        stage_name: The stage name to advance to.
    """
    entry = _stages.get(session_id)
    if entry:
        entry.current_stage = stage_name


def update_story_progress(session_id: str, **kwargs: Any) -> None:
    """Update the story_progress metadata for a rebuild pipeline.

    Args:
        session_id: Session to update.
        **kwargs: Arbitrary key-value pairs (epic, story, index, total, etc.).
    """
    entry = _stages.get(session_id)
    if entry:
        entry.story_progress.update(kwargs)


def complete_pipeline(session_id: str) -> None:
    """Mark a pipeline as completed.

    Args:
        session_id: Session to complete.
    """
    entry = _stages.get(session_id)
    if entry:
        entry.status = "completed"
        # Set to last stage
        if entry.stages:
            entry.current_stage = entry.stages[-1]


def fail_pipeline(session_id: str, error: str = "") -> None:
    """Mark a pipeline as failed.

    Args:
        session_id: Session to fail.
        error: Error message describing the failure.
    """
    entry = _stages.get(session_id)
    if entry:
        entry.status = "failed"
        entry.error = error


def get_stage(session_id: str) -> dict[str, Any] | None:
    """Get the current stage info for a session.

    Args:
        session_id: Session to query.

    Returns:
        Dict with stage info, or None if session not found.
    """
    entry = _stages.get(session_id)
    if entry:
        return entry.to_dict()
    return None

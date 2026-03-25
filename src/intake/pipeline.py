"""Two-stage intake pipeline: spec ingestion → backlog generation.

Reads target project specifications, summarizes them via an LLM agent,
then generates a prioritized epics-and-stories backlog. Output is written
to the target directory as spec-summary.md and epics.md.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.intake.spec_reader import read_project_specs
from src.multi_agent.spawn import run_sub_agent
from src.pipeline_tracker import advance_stage, complete_pipeline, fail_pipeline, start_pipeline

logger = logging.getLogger(__name__)


class IntakeState(TypedDict, total=False):
    """State schema for the intake pipeline."""

    task_id: str
    session_id: str
    spec_dir: str
    raw_specs: str
    spec_summary: str
    epics_and_stories: str
    output_dir: str
    pipeline_status: str  # running|completed|failed
    error: str


# ---------------------------------------------------------------------------
# Pipeline Nodes
# ---------------------------------------------------------------------------


def read_specs_node(state: IntakeState) -> dict[str, Any]:
    """Read project specs from the spec directory."""
    advance_stage(state.get("session_id", ""), "reading_specs")
    spec_dir = state.get("spec_dir", "")
    if not spec_dir:
        return {"pipeline_status": "failed", "error": "No spec_dir provided"}

    try:
        raw_specs = read_project_specs(spec_dir)
    except (FileNotFoundError, NotADirectoryError) as e:
        return {"pipeline_status": "failed", "error": str(e)}

    if not raw_specs.strip():
        return {"pipeline_status": "failed", "error": "No spec files found in directory"}

    return {"raw_specs": raw_specs, "pipeline_status": "running"}


def intake_specs_node(state: IntakeState) -> dict[str, Any]:
    """Spawn a Dev Agent to summarize project specifications."""
    session_id = state.get("session_id", "")
    advance_stage(session_id, "summarizing")
    task_id = state.get("task_id", "")
    raw_specs = state.get("raw_specs", "")

    task_description = (
        "Read and summarize these project specifications into a structured spec summary. "
        "Identify: features, tech stack, architecture, key behaviors, and acceptance criteria.\n\n"
        f"Project Specifications:\n{raw_specs}"
    )

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="dev",
        task_description=task_description,
        current_phase="implementation",
    )

    spec_summary = result.get("final_message", "")
    logger.info("Intake specs node completed: %d chars", len(spec_summary))

    return {"spec_summary": spec_summary}


def create_backlog_node(state: IntakeState) -> dict[str, Any]:
    """Spawn a Dev Agent to create epics and stories from the spec summary."""
    session_id = state.get("session_id", "")
    advance_stage(session_id, "generating_backlog")
    task_id = state.get("task_id", "")
    spec_summary = state.get("spec_summary", "")

    task_description = (
        "From this spec summary, create a prioritized backlog of epics and stories. "
        "Each story must have: user story statement, acceptance criteria (BDD Given/When/Then), "
        "and technical notes.\n\n"
        "Use this EXACT markdown format for the output:\n\n"
        "## Epic 1: {Title}\n\n"
        "### Story 1.1: {Title}\n"
        "**As a** {role}, **I want** {goal}, **so that** {benefit}.\n\n"
        "**Acceptance Criteria:**\n"
        "- **Given** {context} **When** {action} **Then** {outcome}\n\n"
        "**Technical Notes:**\n"
        "- {note}\n\n"
        "---\n\n"
        f"Spec Summary:\n{spec_summary}"
    )

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="dev",
        task_description=task_description,
        current_phase="implementation",
    )

    epics_and_stories = result.get("final_message", "")
    logger.info("Create backlog node completed: %d chars", len(epics_and_stories))

    return {"epics_and_stories": epics_and_stories}


def output_node(state: IntakeState) -> dict[str, Any]:
    """Write spec summary and epics to the output directory."""
    # Preserve earlier failure status (last-write-wins protection)
    if state.get("pipeline_status") == "failed":
        return {"pipeline_status": "failed", "error": state.get("error", "Earlier stage failed")}

    advance_stage(state.get("session_id", ""), "writing_output")
    output_dir = state.get("output_dir", "")
    spec_summary = state.get("spec_summary", "")
    epics_and_stories = state.get("epics_and_stories", "")

    if not output_dir:
        return {"pipeline_status": "failed", "error": "No output_dir provided"}

    if not spec_summary.strip() or not epics_and_stories.strip():
        return {
            "pipeline_status": "failed",
            "error": "Intake produced empty spec summary or backlog",
        }

    try:
        os.makedirs(output_dir, exist_ok=True)

        spec_path = os.path.join(output_dir, "spec-summary.md")
        epics_path = os.path.join(output_dir, "epics.md")

        # Build YAML frontmatter per coding-standards.md
        spec_files = state.get("spec_dir", "")
        frontmatter = (
            "---\n"
            "agent_role: intake\n"
            f"task_id: {state.get('session_id', 'unknown')}\n"
            f"timestamp: {datetime.now(UTC).isoformat()}\n"
            f"input_files: [{spec_files}]\n"
            "---\n\n"
        )

        with open(spec_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + spec_summary)

        with open(epics_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + epics_and_stories)
    except OSError as e:
        return {"pipeline_status": "failed", "error": f"Failed to write output: {e}"}

    logger.info("Intake output written to %s", output_dir)

    return {"pipeline_status": "completed"}


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------


def build_intake_graph() -> StateGraph:  # type: ignore[type-arg]  # LangGraph StateGraph generic not stable across versions
    """Build the two-stage intake pipeline as a StateGraph.

    Flow: read_specs → intake_specs → create_backlog → output → END

    Returns:
        Uncompiled StateGraph ready for .compile().
    """
    graph = StateGraph(IntakeState)

    graph.add_node("read_specs", read_specs_node)
    graph.add_node("intake_specs", intake_specs_node)
    graph.add_node("create_backlog", create_backlog_node)
    graph.add_node("output", output_node)

    graph.add_edge(START, "read_specs")
    graph.add_edge("read_specs", "intake_specs")
    graph.add_edge("intake_specs", "create_backlog")
    graph.add_edge("create_backlog", "output")
    graph.add_edge("output", END)

    return graph


def run_intake_pipeline(
    spec_dir: str,
    output_dir: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Run the complete intake pipeline.

    Args:
        spec_dir: Path to directory containing project specifications.
        output_dir: Path to directory where output files will be written.
        session_id: Optional session ID. Generated if not provided.

    Returns:
        Final pipeline state dict with pipeline_status and output paths.
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    task_id = f"intake-{session_id[:8]}"

    start_pipeline(session_id, "intake")

    graph = build_intake_graph()
    compiled = graph.compile()

    initial_state: IntakeState = {
        "task_id": task_id,
        "session_id": session_id,
        "spec_dir": spec_dir,
        "output_dir": output_dir,
        "pipeline_status": "running",
    }

    try:
        result = compiled.invoke(initial_state)  # type: ignore[arg-type]  # LangGraph Pregel generic not stable across versions
    except Exception as e:
        logger.error("Pipeline execution failed: %s", e)
        fail_pipeline(session_id, str(e))
        return {"pipeline_status": "failed", "error": str(e)}

    result_dict = dict(result)

    if result_dict.get("pipeline_status") == "completed":
        complete_pipeline(session_id)
    else:
        fail_pipeline(session_id, result_dict.get("error", ""))

    return result_dict

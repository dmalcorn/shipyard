"""Entry point: FastAPI server + CLI mode switch.

Provides HTTP API via FastAPI and an interactive CLI mode. Both modes
share the same compiled LangGraph agent and SQLite checkpointing.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import uuid
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from src.agent.graph import create_agent, create_trace_config
from src.intake.intervention_log import (
    InterventionLogger,
    cli_intervention_prompt,
    process_api_intervention,
)
from src.intake.pipeline import run_intake_pipeline
from src.intake.rebuild import run_rebuild
from src.audit_log.audit import AuditLogger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment & graph initialization
# ---------------------------------------------------------------------------

load_dotenv()

# Ensure checkpoints directory exists
os.makedirs("checkpoints", exist_ok=True)

# Module-level compiled graph — shared by both server and CLI
graph = create_agent()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class InstructRequest(BaseModel):
    """Request body for the /instruct endpoint."""

    message: str
    session_id: str | None = None


class InstructResponse(BaseModel):
    """Response body for the /instruct endpoint."""

    session_id: str
    response: str
    messages_count: int


class IntakeRequest(BaseModel):
    """Request body for the /intake endpoint."""

    spec_dir: str
    session_id: str | None = None
    target_dir: str = "./target/"


class IntakeResponse(BaseModel):
    """Response body for the /intake endpoint."""

    session_id: str
    pipeline_status: str
    output_dir: str
    error: str = ""


class RebuildRequest(BaseModel):
    """Request body for the /rebuild endpoint."""

    target_dir: str
    session_id: str | None = None


class RebuildResponse(BaseModel):
    """Response body for the /rebuild endpoint."""

    session_id: str
    stories_completed: int
    stories_failed: int
    interventions: int
    total_stories: int
    status: str


class InterventionRequest(BaseModel):
    """Request body for the /rebuild/intervene endpoint."""

    session_id: str
    what_broke: str
    what_developer_did: str
    agent_limitation: str
    action: Literal["fix", "skip", "abort"]


class InterventionResponse(BaseModel):
    """Response body for the /rebuild/intervene endpoint."""

    session_id: str
    action: Literal["fix", "skip", "abort"]
    logged: bool


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Shipyard", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/instruct", response_model=InstructResponse)
def instruct(request: InstructRequest) -> InstructResponse:
    """Process an instruction through the agent graph.

    Args:
        request: The instruction request containing a message and optional session_id.

    Returns:
        InstructResponse with session_id, agent response text, and message count.
    """
    session_id = request.session_id or str(uuid.uuid4())
    config = create_trace_config(session_id=session_id, task_id=session_id)

    audit = AuditLogger(session_id=session_id, task_description=request.message)
    audit.start_session()

    try:
        result = graph.invoke(
            {
                "messages": [HumanMessage(content=request.message)],
                "task_id": session_id,
            },
            config=config,
        )
    finally:
        audit.end_session()

    response_text = _extract_response(result)
    messages_count = len(result.get("messages", []))

    return InstructResponse(
        session_id=session_id,
        response=response_text,
        messages_count=messages_count,
    )


@app.post("/intake", response_model=IntakeResponse)
def intake(request: IntakeRequest) -> IntakeResponse:
    """Run the spec intake pipeline on a target project's documentation.

    Args:
        request: The intake request with spec_dir and optional session_id/target_dir.

    Returns:
        IntakeResponse with pipeline status and output directory.
    """
    session_id = request.session_id or str(uuid.uuid4())
    output_dir = request.target_dir

    result = run_intake_pipeline(
        spec_dir=request.spec_dir,
        output_dir=output_dir,
        session_id=session_id,
    )

    return IntakeResponse(
        session_id=session_id,
        pipeline_status=result.get("pipeline_status", "unknown"),
        output_dir=output_dir,
        error=result.get("error", ""),
    )


@app.post("/rebuild", response_model=RebuildResponse)
def rebuild(request: RebuildRequest) -> RebuildResponse:
    """Run the autonomous rebuild loop on a target project.

    Args:
        request: The rebuild request with target_dir and optional session_id.

    Returns:
        RebuildResponse with completion stats.
    """
    session_id = request.session_id or str(uuid.uuid4())

    result = run_rebuild(
        target_dir=request.target_dir,
        session_id=session_id,
    )

    total = result.get("total_stories", 0)
    completed = result.get("stories_completed", 0)
    status = "completed" if completed == total and total > 0 else "partial"
    if total == 0:
        status = "empty"

    return RebuildResponse(
        session_id=session_id,
        stories_completed=completed,
        stories_failed=result.get("stories_failed", 0),
        interventions=result.get("interventions", 0),
        total_stories=total,
        status=status,
    )


# Module-level dict to hold active intervention loggers per session
_intervention_loggers: dict[str, InterventionLogger] = {}


@app.post("/rebuild/intervene", response_model=InterventionResponse)
def rebuild_intervene(request: InterventionRequest) -> InterventionResponse:
    """Process a human intervention during an active rebuild session.

    Args:
        request: The intervention request with session_id and intervention details.

    Returns:
        InterventionResponse confirming the action taken.
    """
    intervention_logger = _intervention_loggers.get(request.session_id)
    if not intervention_logger:
        # Create a logger if one doesn't exist for this session
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", request.session_id)
        intervention_logger = InterventionLogger(log_path=f"./target/intervention-log-{safe_id}.md")
        _intervention_loggers[request.session_id] = intervention_logger

    action = request.action  # Already validated by Pydantic Literal type

    process_api_intervention(
        logger=intervention_logger,
        epic="",
        story="",
        phase="pipeline",
        failure_report="",
        retry_counts="",
        what_broke=request.what_broke,
        what_developer_did=request.what_developer_did,
        agent_limitation=request.agent_limitation,
        action=action,
    )

    return InterventionResponse(
        session_id=request.session_id,
        action=action,
        logged=True,
    )


def _extract_response(result: dict[str, Any]) -> str:
    """Extract the final AI response text from graph invocation result."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, list):
                return " ".join(
                    block.get("text", "") for block in content if isinstance(block, dict)
                )
            return str(content)
    return ""


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------


def _run_cli() -> None:
    """Run the interactive CLI loop."""
    session_id = str(uuid.uuid4())

    audit = AuditLogger(session_id=session_id, task_description="Interactive CLI session")
    audit.start_session()

    print(f"Shipyard CLI (session: {session_id})")
    print('Type "exit" or "quit" to stop.\n')

    try:
        while True:
            try:
                user_input = input(">>> ")
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye.")
                break

            stripped = user_input.strip()
            if not stripped:
                continue
            if stripped.lower() in ("exit", "quit"):
                print("Goodbye.")
                break

            # Each turn gets a fresh thread_id so the checkpointer doesn't
            # accumulate messages from prior turns.  The session_id is kept
            # constant for audit logging and LangSmith trace grouping.
            turn_id = str(uuid.uuid4())
            turn_config = create_trace_config(session_id=turn_id, task_id=session_id)

            result = graph.invoke(
                {
                    "messages": [HumanMessage(content=stripped)],
                    "task_id": session_id,
                },
                config=turn_config,
            )

            response_text = _extract_response(result)
            if response_text:
                print(response_text)
    finally:
        audit.end_session()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _run_rebuild_cli(target_dir: str) -> None:
    """Run the rebuild loop from CLI with interactive intervention."""
    session_id = str(uuid.uuid4())
    log_path = os.path.join(target_dir, "intervention-log.md")
    intervention_logger = InterventionLogger(log_path=log_path)

    print(f"Shipyard Rebuild (session: {session_id})")
    print(f"Target dir: {target_dir}")
    print(f"Intervention log: {log_path}")

    def cli_intervention(failure_report: str) -> str | None:
        """Prompt user for structured intervention on pipeline failure."""
        action, fix_instruction = cli_intervention_prompt(
            logger=intervention_logger,
            epic="",
            story="",
            phase="pipeline",
            failure_report=failure_report,
            retry_counts="",
        )
        if action == "abort":
            return None
        if action == "skip":
            return "skip"
        return fix_instruction if fix_instruction else "retry"

    result = run_rebuild(
        target_dir=target_dir,
        session_id=session_id,
        on_intervention=cli_intervention,
        intervention_logger=intervention_logger,
    )

    print("\nRebuild complete.")
    print(f"  Stories: {result['stories_completed']}/{result['total_stories']} completed")
    print(f"  Failed: {result['stories_failed']}")
    print(f"  Interventions: {result['interventions']}")
    print(f"  Time: {result['elapsed_seconds'] / 60:.1f} minutes")


def _run_intake(spec_dir: str, target_dir: str) -> None:
    """Run the intake pipeline from CLI."""
    session_id = str(uuid.uuid4())
    print(f"Shipyard Intake (session: {session_id})")
    print(f"Spec dir: {spec_dir}")
    print(f"Target dir: {target_dir}")

    result = run_intake_pipeline(
        spec_dir=spec_dir,
        output_dir=target_dir,
        session_id=session_id,
    )

    status = result.get("pipeline_status", "unknown")
    if status == "completed":
        print(f"\nIntake completed. Output written to {target_dir}/")
        print(f"  - {target_dir}/spec-summary.md")
        print(f"  - {target_dir}/epics.md")
    else:
        error = result.get("error", "Unknown error")
        print(f"\nIntake failed: {error}")


def main() -> None:
    """Route to CLI mode, intake mode, or start the FastAPI server."""
    parser = argparse.ArgumentParser(description="Shipyard agent server")
    parser.add_argument("--cli", action="store_true", help="Run interactive CLI mode")
    parser.add_argument(
        "--intake",
        metavar="SPEC_DIR",
        help="Run intake pipeline on a spec directory",
    )
    parser.add_argument(
        "--rebuild",
        metavar="TARGET_DIR",
        help="Run autonomous rebuild on a target project",
    )
    parser.add_argument(
        "--target-dir",
        default="./target/",
        help="Target output directory (default: ./target/)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    if args.rebuild:
        _run_rebuild_cli(args.rebuild)
    elif args.intake:
        _run_intake(args.intake, args.target_dir)
    elif args.cli:
        _run_cli()
    else:
        import uvicorn

        uvicorn.run("src.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()

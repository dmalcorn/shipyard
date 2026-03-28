"""Entry point: FastAPI server + CLI mode switch.

Provides HTTP API via FastAPI and an interactive CLI mode. Both modes
share the same compiled LangGraph agent and SQLite checkpointing.
The server also exposes monitoring endpoints for the public dashboard.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.agent.graph import create_agent, create_trace_config
from src.audit_log.audit import AuditLogger
from src.intake.intervention_log import (
    InterventionLogger,
    cli_intervention_prompt,
    process_api_intervention,
)
from src.intake.pipeline import run_intake_pipeline
from src.intake.rebuild import run_rebuild
from src.log_relay import (
    create_session,
    end_session,
    ensure_schema,
    get_active_session,
    get_session_logs,
    list_sessions,
    store_events,
)
from src.pipeline_tracker import (
    advance_stage,
    complete_pipeline,
    fail_pipeline,
    get_stage,
    start_pipeline,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment & graph initialization
# ---------------------------------------------------------------------------

load_dotenv()

# Ensure checkpoints directory exists
os.makedirs("checkpoints", exist_ok=True)

# Module-level compiled graph — shared by both server and CLI
graph = create_agent()

# Shared secret for authenticating event push requests
_RELAY_KEY = os.environ.get("SHIPYARD_RELAY_KEY", "")

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


class EventPushRequest(BaseModel):
    """Request body for pushing log events from the local pipeline."""

    session_id: str
    events: list[dict[str, Any]]


class SessionStartRequest(BaseModel):
    """Request body to register a new pipeline session."""

    session_id: str
    pipeline_type: str = "rebuild"


class SessionEndRequest(BaseModel):
    """Request body to mark a session as finished."""

    session_id: str
    status: str = "completed"


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Initialize Postgres schema on startup if DATABASE_URL is set."""
    if os.environ.get("DATABASE_URL"):
        try:
            ensure_schema()
            logger.info("Postgres schema initialized")
        except Exception as e:
            logger.warning("Could not initialize Postgres schema: %s", e)
    yield


app = FastAPI(title="Shipyard", version="0.1.0", lifespan=_lifespan)

# Allow the dashboard to make requests from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _verify_relay_key(authorization: str | None) -> None:
    """Verify the Bearer token matches the configured relay key."""
    if not _RELAY_KEY:
        raise HTTPException(status_code=503, detail="Relay key not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token != _RELAY_KEY:
        raise HTTPException(status_code=403, detail="Invalid relay key")

# ---------------------------------------------------------------------------
# Static files & dashboard
# ---------------------------------------------------------------------------

_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/")
async def dashboard() -> FileResponse:
    """Serve the Shipyard dashboard."""
    return FileResponse(str(_static_dir / "index.html"))


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/pipeline/{session_id}/stage")
async def pipeline_stage(session_id: str) -> dict[str, Any]:
    """Poll the current stage of a running pipeline.

    Args:
        session_id: The session ID to query.

    Returns:
        Dict with pipeline type, current stage, status, and progress info.
    """
    stage = get_stage(session_id)
    if not stage:
        return {"status": "unknown", "error": "No such session"}
    return stage


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

    start_pipeline(session_id, "instruct")
    advance_stage(session_id, "agent_node")

    audit = AuditLogger(session_id=session_id, task_description=request.message)
    audit.start_session()

    try:
        advance_stage(session_id, "should_continue")
        result = graph.invoke(
            {
                "messages": [HumanMessage(content=request.message)],
                "task_id": session_id,
            },
            config=config,
        )
        advance_stage(session_id, "response")
        complete_pipeline(session_id)
    except Exception:
        fail_pipeline(session_id, "Agent invocation failed")
        raise
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
_MAX_LOGGERS = 100


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
        # Evict oldest entry if at capacity
        if len(_intervention_loggers) >= _MAX_LOGGERS:
            oldest_key = next(iter(_intervention_loggers))
            del _intervention_loggers[oldest_key]
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


# ---------------------------------------------------------------------------
# Monitoring API — public dashboard endpoints
# ---------------------------------------------------------------------------


@app.post("/api/sessions/start")
async def api_session_start(
    request: SessionStartRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Register a new pipeline session (called by local relay)."""
    _verify_relay_key(authorization)
    create_session(request.session_id, request.pipeline_type)
    return {"status": "created", "session_id": request.session_id}


@app.post("/api/sessions/end")
async def api_session_end(
    request: SessionEndRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Mark a session as completed or failed (called by local relay)."""
    _verify_relay_key(authorization)
    end_session(request.session_id, request.status)
    return {"status": "ended", "session_id": request.session_id}


@app.post("/api/events")
async def api_push_events(
    request: EventPushRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Receive log events from the local pipeline runner."""
    _verify_relay_key(authorization)
    count = store_events(request.session_id, request.events)
    return {"stored": count}


@app.get("/api/sessions")
async def api_list_sessions() -> list[dict[str, Any]]:
    """List recent pipeline sessions (public, read-only)."""
    if not os.environ.get("DATABASE_URL"):
        return []
    return list_sessions()


@app.get("/api/active")
async def api_active_session() -> dict[str, Any]:
    """Get the currently running session, if any (public, read-only)."""
    if not os.environ.get("DATABASE_URL"):
        return {"active": None}
    session = get_active_session()
    return {"active": session}


@app.get("/api/logs/{session_id}")
async def api_get_logs(session_id: str, after_id: int = 0) -> dict[str, Any]:
    """Fetch log events for a session (public, read-only).

    Args:
        session_id: Session to query.
        after_id: Only return events after this ID (for incremental polling).

    Returns:
        Dict with events list and the latest event ID.
    """
    if not os.environ.get("DATABASE_URL"):
        return {"events": [], "latest_id": 0}
    events = get_session_logs(session_id, after_id=after_id)
    latest_id = events[-1]["id"] if events else after_id
    return {"events": events, "latest_id": latest_id}


@app.get("/api/stream/{session_id}")
async def api_stream_logs(session_id: str) -> EventSourceResponse:
    """SSE endpoint for live-streaming log events to the browser.

    Args:
        session_id: Session to stream.

    Returns:
        Server-Sent Events stream of log lines.
    """

    async def event_generator() -> Any:
        last_id = 0
        while True:
            events = get_session_logs(session_id, after_id=last_id)
            for ev in events:
                last_id = ev["id"]
                yield {
                    "event": ev["event_type"],
                    "data": ev["text"],
                    "id": str(ev["id"]),
                }
            # Check if session has ended
            active = get_active_session()
            if not active or active["session_id"] != session_id:
                # Send a final "done" event so the browser knows to stop
                yield {"event": "done", "data": "session ended"}
                break
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())


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
            # accumulate messages from prior turns and each turn produces
            # its own independent LangSmith trace.
            turn_id = str(uuid.uuid4())
            turn_config = create_trace_config(session_id=turn_id, task_id=turn_id)
            # Give the trace a human-readable name (truncated instruction)
            turn_config["run_name"] = f"cli: {stripped[:60]}"

            result = graph.invoke(
                {
                    "messages": [HumanMessage(content=stripped)],
                    "task_id": turn_id,
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


SESSION_FILENAME = "checkpoints/session.json"


def _session_path(target_dir: str) -> str:
    """Return the absolute path to the session file inside the target dir."""
    return os.path.join(target_dir, SESSION_FILENAME)


def _save_session(session_id: str, target_dir: str) -> None:
    """Persist session_id to disk so --resume can find it."""
    path = _session_path(target_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"session_id": session_id, "target_dir": target_dir}, f)


def _load_session(target_dir: str) -> dict[str, str] | None:
    """Load the most recent session from disk, or None if not found."""
    path = _session_path(target_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _run_rebuild_cli(target_dir: str, resume: bool = False) -> None:
    """Run the rebuild loop from CLI with interactive intervention."""
    from src.intake.pause import request_pause, reset_pause

    # Configure console logging so pipeline progress is visible
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Reset pause flag from any previous run in this process
    reset_pause()

    # Session management: resume existing or start fresh
    if resume:
        saved = _load_session(target_dir)
        if saved and saved.get("session_id"):
            session_id = saved["session_id"]
            print(f"Resuming session: {session_id}")
            # Don't overwrite session file — it contains resume state
        else:
            print("No previous session found — starting fresh.")
            resume = False
            session_id = str(uuid.uuid4())
            _save_session(session_id, target_dir)
    else:
        session_id = str(uuid.uuid4())
        _save_session(session_id, target_dir)

    log_path = os.path.join(target_dir, "intervention-log.md")
    intervention_logger = InterventionLogger(log_path=log_path)

    print(f"Shipyard Rebuild (session: {session_id})")
    print(f"Target dir: {target_dir}")
    print(f"Intervention log: {log_path}")
    print("Press Ctrl+C once to pause after the current story finishes.")

    # --- Graceful pause signal handler ---
    _ctrl_c_count = 0

    def _handle_sigint(signum: int, frame: Any) -> None:
        nonlocal _ctrl_c_count
        _ctrl_c_count += 1
        if _ctrl_c_count == 1:
            print("\n*** Pause requested — will stop after the current story finishes.")
            print("    Press Ctrl+C again to force-quit immediately.")
            request_pause()
        else:
            print("\n*** Force-quitting.")
            raise SystemExit(1)

    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handle_sigint)

    try:
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
            resume=resume,
        )

        status = result.get("pipeline_status", "unknown")
        cost = result.get("total_cost_usd", 0.0)
        invocations = result.get("llm_invocations", 0)

        if status == "paused":
            print("\nRebuild paused.")
            print(f"  Stories so far: {result['stories_completed']}/{result['total_stories']}")
            print(f"  Cost so far: ${cost:.2f} ({invocations} LLM calls)")
            print(f"  To resume: python -m src.main --rebuild {target_dir} --resume")
        else:
            print("\nRebuild complete.")
            print(f"  Stories: {result['stories_completed']}/{result['total_stories']} completed")
            print(f"  Failed: {result['stories_failed']}")
            print(f"  Interventions: {result['interventions']}")
            print(f"  Time: {result['elapsed_seconds'] / 60:.1f} minutes")
            print(f"  Cost: ${cost:.2f} ({invocations} LLM calls)")
    finally:
        signal.signal(signal.SIGINT, original_handler)


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
        "--resume",
        action="store_true",
        help="Resume a previously paused rebuild from its last checkpoint",
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
        _run_rebuild_cli(args.rebuild, resume=args.resume)
    elif args.intake:
        _run_intake(args.intake, args.target_dir)
    elif args.cli:
        _run_cli()
    else:
        import uvicorn

        uvicorn.run("src.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()

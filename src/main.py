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
import sys
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
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.audit_log.audit import AuditLogger
from src.intake.intervention_log import (
    InterventionLogger,
    cli_intervention_prompt,
    process_api_intervention,
)
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
# Environment
# ---------------------------------------------------------------------------

load_dotenv()

# Shared secret for authenticating event push requests
_RELAY_KEY = os.environ.get("SHIPYARD_RELAY_KEY", "")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


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
async def api_stream_logs(session_id: str, after_id: int = 0) -> EventSourceResponse:
    """SSE endpoint for live-streaming log events to the browser.

    Args:
        session_id: Session to stream.
        after_id: Only stream events after this ID (skip historical backfill).

    Returns:
        Server-Sent Events stream of log lines.
    """

    async def event_generator() -> Any:
        last_id = after_id
        while True:
            events = get_session_logs(session_id, after_id=last_id)
            for ev in events:
                last_id = ev["id"]
                data = ev["text"]
                if ev.get("metadata"):
                    data = json.dumps({"text": ev["text"], "metadata": ev["metadata"]})
                yield {
                    "event": ev["event_type"],
                    "data": data,
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


def _run_rebuild_cli(
    target_dir: str,
    resume: bool = False,
    *,
    skip_story_reviews: bool = False,
    skip_story_ci: bool = False,
) -> None:
    """Run the rebuild loop from CLI with interactive intervention."""
    from src.config import (
        get_ci_config,
        get_langsmith_project,
        get_model_config,
        get_reviews_config,
        get_target_dir,
        load_factory_config,
        save_ci_fix_pre_existing,
    )
    from src.intake.epic_graph import set_epic_model_config
    from src.intake.pause import request_pause, reset_pause
    from src.multi_agent.orchestrator import (
        set_ci_bash_timeout,
        set_epic_ci_bash_timeout,
        set_fix_pre_existing,
        set_model_config,
        set_story_ci_enabled,
        set_story_reviews_enabled,
    )

    # Normalize path to OS-native format (resolves mixed separators from
    # MINGW64 bash on Windows where CLI gives forward slashes but
    # os.path.join appends backslashes).
    target_dir = os.path.normpath(os.path.abspath(target_dir))

    # Configure console logging so pipeline progress is visible
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Load factory.yaml and apply configuration
    config = load_factory_config()
    model_config = get_model_config(config)
    if model_config:
        set_model_config(model_config)
        set_epic_model_config(model_config)
        print(f"  Model overrides: {
            {k: v for k, v in model_config.items() if v}
        }")

    # Apply review configuration (CLI flag overrides factory.yaml)
    reviews_config = get_reviews_config(config)
    if skip_story_reviews or not reviews_config.get("story_level", True):
        set_story_reviews_enabled(False)
        print("  Story-level code reviews: DISABLED (epic reviews still active)")

    # Apply CI configuration (CLI flag overrides factory.yaml)
    ci_config = get_ci_config(config)
    if skip_story_ci or not ci_config.get("story_level", True):
        set_story_ci_enabled(False)
        print("  Story-level CI runs: DISABLED (commits proceed without CI gate)")

    # CI bash timeouts (story = single-story scope; epic = full consolidated suite)
    story_ci_timeout = int(ci_config.get("bash_timeout_seconds", 300))
    epic_ci_timeout = int(ci_config.get("epic_bash_timeout_seconds", 1800))
    set_ci_bash_timeout(story_ci_timeout)
    set_epic_ci_bash_timeout(epic_ci_timeout)
    print(
        f"  CI bash timeouts: story={story_ci_timeout}s, "
        f"epic={epic_ci_timeout}s"
    )

    # Prompt for CI-fix scope behavior (greenfield default: fix everything).
    # YAML value is the default; operator is prompted every run so the
    # setting stays visible. Non-TTY runs skip the prompt and use YAML.
    yaml_fix_default = bool(ci_config.get("fix_pre_existing_errors", True))
    fix_pre_existing = yaml_fix_default
    if sys.stdin.isatty():
        default_char = "Y" if yaml_fix_default else "N"
        other_char = "n" if yaml_fix_default else "y"
        answer = input(
            f"  Fix pre-existing errors found in CI "
            f"(not just ones introduced by the current story/epic)? "
            f"[{default_char}/{other_char}]: "
        ).strip().lower()
        if answer in ("y", "yes"):
            fix_pre_existing = True
        elif answer in ("n", "no"):
            fix_pre_existing = False
    set_fix_pre_existing(fix_pre_existing)
    print(
        f"  Fix pre-existing CI errors: "
        f"{'YES (greenfield)' if fix_pre_existing else 'NO (brownfield scope-constrained)'}"
    )
    if fix_pre_existing != yaml_fix_default:
        save_ci_fix_pre_existing(fix_pre_existing)

    ls_project = get_langsmith_project(config)
    if ls_project and not os.environ.get("LANGCHAIN_PROJECT"):
        os.environ["LANGCHAIN_PROJECT"] = ls_project

    # Use factory.yaml target_dir as fallback if CLI arg is a default
    if target_dir == "./target/" and config:
        yaml_target = get_target_dir(config)
        if yaml_target != "./target/":
            target_dir = yaml_target
            print(f"  Target dir from factory.yaml: {target_dir}")

    # Validate the target dir exists on disk. The most common failure mode
    # here is bash (MINGW64) eating backslashes from an unquoted Windows
    # path on the CLI: e.g. `--rebuild C:\alcorn\AI\Foo` collapses to
    # `C:alcornAIFoo`, which os.path.abspath then resolves against shipyard's
    # CWD — running silently against a non-existent path. Fail loudly with
    # a useful hint so the operator catches it immediately.
    if not os.path.isdir(target_dir):
        yaml_target = get_target_dir(config) if config else "./target/"
        if yaml_target != "./target/" and os.path.isdir(yaml_target):
            print(
                f"  WARNING: --rebuild target dir does not exist: {target_dir}\n"
                f"           Falling back to factory.yaml target.dir: {yaml_target}",
            )
            target_dir = yaml_target
        else:
            print(
                f"\nERROR: --rebuild target dir does not exist on disk:\n"
                f"  {target_dir}\n\n"
                f"On Windows + bash (MINGW64), unquoted backslashes are stripped "
                f"as escape characters. Quote the path or use forward slashes:\n"
                f'  python -m src.main --rebuild "C:/alcorn/AI/Foo" --resume',
            )
            raise SystemExit(2)

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
        # Check if a checkpoint with progress exists — warn before overwriting
        session_file = os.path.join(target_dir, "checkpoints/session.json")
        if os.path.isfile(session_file):
            try:
                with open(session_file, encoding="utf-8") as f:
                    existing = json.load(f)
                has_progress = (
                    existing.get("resume_epic_index", 0) > 0
                    or existing.get("resume_story_index", 0) > 0
                )
                if has_progress:
                    backup = session_file + ".bak"
                    import shutil
                    shutil.copy2(session_file, backup)
                    print(f"WARNING: Existing checkpoint with progress backed up to {backup}")
                    print("         Use --resume to continue from where you left off.")
            except (json.JSONDecodeError, OSError):
                pass
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
            print("\n*** Force-quitting — killing all subprocesses...")
            from src.intake.pause import request_force_quit
            from src.multi_agent.proc_registry import kill_all
            from src.web_relay import stop_relay
            request_force_quit()
            kill_all()
            # Mark the relay session as paused BEFORE exiting —
            # without this the session stays "running" in Postgres
            # and the dashboard cycles endlessly trying to reconnect.
            stop_relay("paused")
            raise SystemExit(1)

    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handle_sigint)

    # In Docker, Ctrl+C sends SIGTERM to PID 1, not SIGINT.
    original_sigterm = None
    if hasattr(signal, "SIGTERM"):
        original_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, _handle_sigint)

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
        signal.signal(signal.SIGINT, original_sigint)
        if original_sigterm is not None:
            signal.signal(signal.SIGTERM, original_sigterm)


def main() -> None:
    """Route to CLI mode, intake mode, or start the FastAPI server."""
    parser = argparse.ArgumentParser(description="Shipyard agent server")
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
        "--no-story-reviews",
        action="store_true",
        help="Skip story-level code reviews (epic reviews still run)",
    )
    parser.add_argument(
        "--no-story-ci",
        action="store_true",
        help="Skip story-level CI runs (commits proceed without CI gate)",
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
        _run_rebuild_cli(
            args.rebuild,
            resume=args.resume,
            skip_story_reviews=args.no_story_reviews,
            skip_story_ci=args.no_story_ci,
        )
    else:
        import uvicorn

        uvicorn.run("src.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()

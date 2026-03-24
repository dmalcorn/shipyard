"""Entry point: FastAPI server + CLI mode switch.

Provides HTTP API via FastAPI and an interactive CLI mode. Both modes
share the same compiled LangGraph agent and SQLite checkpointing.
"""

from __future__ import annotations

import argparse
import logging
import os
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from src.agent.graph import create_agent, create_trace_config
from src.logging.audit import AuditLogger

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
    config = create_trace_config(session_id=session_id, task_id=session_id)

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

            result = graph.invoke(
                {
                    "messages": [HumanMessage(content=stripped)],
                    "task_id": session_id,
                },
                config=config,
            )

            response_text = _extract_response(result)
            if response_text:
                print(response_text)
    finally:
        audit.end_session()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Route to CLI mode or start the FastAPI server."""
    parser = argparse.ArgumentParser(description="Shipyard agent server")
    parser.add_argument("--cli", action="store_true", help="Run interactive CLI mode")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8000, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    if args.cli:
        _run_cli()
    else:
        import uvicorn

        uvicorn.run("src.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()

"""StateGraph definition and compilation for the core agent loop.

Builds the ReAct loop: agent_node → should_continue → tool_node → agent_node,
with SQLite checkpointing for session persistence.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from src.agent.nodes import agent_node, error_handler, should_continue, tool_node
from src.agent.state import AgentState
from src.multi_agent.roles import build_trace_config

CHECKPOINTS_DB = "checkpoints/shipyard.db"


def _build_graph() -> StateGraph:  # type: ignore[type-arg]
    """Build the core agent graph (without compiling)."""
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("error_handler", error_handler)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END,
            "error": "error_handler",
        },
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("error_handler", END)
    return graph


def create_agent(checkpoints_db: str = CHECKPOINTS_DB) -> Any:
    """Build and compile the core agent graph with SQLite checkpointing.

    Args:
        checkpoints_db: Path to the SQLite database for state checkpointing.

    Returns:
        Compiled LangGraph graph ready for invocation.
    """
    graph = _build_graph()
    conn = sqlite3.connect(checkpoints_db, check_same_thread=False)
    memory = SqliteSaver(conn)
    return graph.compile(checkpointer=memory)


def create_trace_config(
    session_id: str,
    agent_role: str = "dev",
    task_id: str = "",
    model_tier: str = "sonnet",
    phase: str = "implementation",
    parent_session: str | None = None,
) -> dict[str, Any]:
    """Build a LangGraph invocation config with LangSmith trace metadata.

    Convenience wrapper around build_trace_config with sensible defaults
    for the single-agent MVP (role=dev, tier=sonnet, phase=implementation).

    Args:
        session_id: Unique session identifier, used as thread_id.
        agent_role: One of dev, test, reviewer, architect, fix_dev.
        task_id: Task identifier (e.g. "story-42").
        model_tier: One of haiku, sonnet, opus.
        phase: One of test, implementation, review, fix, ci.
        parent_session: Optional parent session ID for sub-agent linking.

    Returns:
        Config dict ready to pass to graph.invoke() / graph.stream().
    """
    return build_trace_config(
        session_id=session_id,
        agent_role=agent_role,
        task_id=task_id,
        model_tier=model_tier,
        phase=phase,
        parent_session=parent_session,
    )

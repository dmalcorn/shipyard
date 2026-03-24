"""Sub-agent spawning via LangGraph subgraphs.

Creates isolated sub-agent graphs with fresh context, role-specific tools,
and LangSmith trace linking back to the parent session.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.context.injection import build_system_prompt, inject_task_context
from src.multi_agent.roles import MODEL_IDS, get_role, get_tools_for_role

logger = logging.getLogger(__name__)

MAX_RETRIES = 50
CHECKPOINTS_DB = "checkpoints/shipyard.db"


def _should_continue(state: AgentState) -> str:
    """Route after agent node: continue to tools, end, or error on retry cap."""
    if not state.get("messages"):
        return "end"
    retry_count = state.get("retry_count", 0)
    if retry_count >= MAX_RETRIES:
        return "error"
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "end"


def _make_error_handler(state: AgentState) -> dict[str, Any]:
    """Append error message when sub-agent exceeds turn limit."""
    return {"messages": [AIMessage(content=f"ERROR: Sub-agent exceeded {MAX_RETRIES} turns.")]}


def create_agent_subgraph(
    role: str,
    task_description: str,
    context_files: list[str] | None = None,
    checkpoints_db: str = CHECKPOINTS_DB,
) -> tuple[Any, dict[str, Any]]:
    """Create a compiled sub-agent subgraph with fresh context.

    Builds a 2-node StateGraph (agent_node + tool_node) with the role's
    tool subset, model tier, and system prompt. Returns the compiled graph
    and the initial state for invocation.

    Args:
        role: Agent role identifier (dev, test, reviewer, architect, fix_dev).
        task_description: Task instruction for the sub-agent.
        context_files: Optional file paths to inject as Layer 2 context.
        checkpoints_db: Path to SQLite database for checkpointing.

    Returns:
        Tuple of (compiled_graph, initial_state_dict).
    """
    role_config = get_role(role)
    model_id = MODEL_IDS[role_config.model_tier]
    tools = get_tools_for_role(role)

    # Build LLM with role's tools bound
    llm = ChatAnthropic(model=model_id, temperature=0)  # type: ignore[call-arg]
    llm_with_tools = llm.bind_tools(tools)

    # Build system prompt (Layer 1)
    system_prompt = build_system_prompt(role_config.system_prompt_key, context_files)

    # Agent node: calls LLM and increments retry_count
    def agent_node(state: AgentState) -> dict[str, Any]:
        """Call the LLM with current messages and bound tools."""
        messages = state["messages"]
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt), *messages]
        response = llm_with_tools.invoke(messages)
        retry_count = state.get("retry_count", 0) + 1
        return {"messages": [response], "retry_count": retry_count}

    # Tool node
    tool_node = ToolNode(tools)

    # Build graph
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("error_handler", _make_error_handler)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", "end": END, "error": "error_handler"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("error_handler", END)

    # Compile with checkpointing
    conn = sqlite3.connect(checkpoints_db, check_same_thread=False)
    memory = SqliteSaver(conn)
    compiled = graph.compile(checkpointer=memory)

    # Build fresh initial state (context isolation — AC#2)
    task_messages = inject_task_context(task_description, context_files)
    initial_state: dict[str, Any] = {
        "messages": task_messages,
        "task_id": "",
        "retry_count": 0,
        "current_phase": "",
        "agent_role": role,
        "files_modified": [],
    }

    return compiled, initial_state


def run_sub_agent(
    parent_session_id: str,
    task_id: str,
    role: str,
    task_description: str,
    current_phase: str,
    context_files: list[str] | None = None,
    checkpoints_db: str = CHECKPOINTS_DB,
) -> dict[str, Any]:
    """Spawn and run a sub-agent, returning state updates for the parent.

    Creates a subgraph via create_agent_subgraph(), invokes it with fresh
    context and trace metadata linked to the parent session, then reads
    output files from the filesystem.

    Args:
        parent_session_id: Parent orchestrator's session ID for trace linking.
        task_id: Task identifier (e.g. "story-42").
        role: Agent role identifier (dev, test, reviewer, architect, fix_dev).
        task_description: Task instruction for the sub-agent.
        current_phase: Current pipeline phase (test, implementation, review, fix, ci).
        context_files: Optional file paths to inject as context.
        checkpoints_db: Path to SQLite database for checkpointing.

    Returns:
        Dict with keys: files_modified (list[str]), final_message (str).
    """
    role_config = get_role(role)

    # Create subgraph and initial state
    compiled, initial_state = create_agent_subgraph(
        role=role,
        task_description=task_description,
        context_files=context_files,
        checkpoints_db=checkpoints_db,
    )

    # Set task metadata in initial state
    sub_thread_id = f"{parent_session_id}-{role}-{int(time.time())}"
    initial_state["task_id"] = task_id
    initial_state["current_phase"] = current_phase

    # Build config with trace metadata (AC#4 — parent_session linking)
    config: dict[str, Any] = {
        "configurable": {"thread_id": sub_thread_id},
        "metadata": {
            "agent_role": role,
            "task_id": task_id,
            "model_tier": role_config.model_tier,
            "phase": current_phase,
            "parent_session": parent_session_id,
        },
    }

    # Invoke the sub-agent
    logger.info("Spawning sub-agent: role=%s thread=%s", role, sub_thread_id)
    final_state = compiled.invoke(initial_state, config=config)

    # Extract results
    files_modified = final_state.get("files_modified", [])
    messages = final_state.get("messages", [])
    final_message = ""
    if messages:
        last = messages[-1]
        if hasattr(last, "content"):
            final_message = str(last.content)

    logger.info("Sub-agent done: role=%s files=%d", role, len(files_modified))

    return {
        "files_modified": files_modified,
        "final_message": final_message,
    }

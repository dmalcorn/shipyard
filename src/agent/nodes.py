"""Node functions for the core agent ReAct loop.

Provides the agent node (LLM reasoning), tool node (tool execution),
and conditional routing logic.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.audit_log.audit import get_logger
from src.context.injection import build_system_prompt
from src.tools import tools

logger = logging.getLogger(__name__)

MAX_RETRIES = 50
DEFAULT_MODEL = "claude-sonnet-4-6"

FALLBACK_SYSTEM_PROMPT = (
    "You are Shipyard, an autonomous coding agent. You read codebases, reason about "
    "changes, and make targeted surgical edits using the tools provided. "
    "Always read a file before editing it. Use exact string matching for edits. "
    "If an edit fails, re-read the file and retry with corrected anchors."
)

# Pre-built tool node handles tool call dispatch automatically
_tool_node_inner = ToolNode(tools)


def agent_node(state: AgentState) -> dict[str, Any]:
    """Call the LLM with the current messages and bound tools.

    Builds a role-aware system prompt via the context injection system.
    Increments retry_count on each invocation to enforce the global turn cap.
    """
    model = ChatAnthropic(model=DEFAULT_MODEL).bind_tools(tools)  # type: ignore[call-arg]

    # Build role-aware system prompt (Layer 1 context injection)
    agent_role = state.get("agent_role", "dev")
    context_files: list[str] | None = state.get("context_files")  # type: ignore[assignment]
    try:
        system_prompt = build_system_prompt(agent_role, context_files)
    except ValueError:
        logger.warning("Unknown role %r, using fallback prompt", agent_role)
        system_prompt = FALLBACK_SYSTEM_PROMPT

    messages = state["messages"]
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt), *messages]

    response = model.invoke(messages)

    retry_count = state.get("retry_count", 0) + 1
    logger.info("Agent turn %d (max %d)", retry_count, MAX_RETRIES)

    # Audit: log agent start on first turn
    task_id = state.get("task_id", "")
    audit = get_logger(task_id)
    if audit and retry_count == 1:
        audit.log_agent_start(str(agent_role), DEFAULT_MODEL)

    return {"messages": [response], "retry_count": retry_count}


def tool_node(state: AgentState) -> dict[str, Any]:
    """Execute tools and log each call to the audit logger."""
    result: dict[str, Any] = _tool_node_inner.invoke(state)

    # Audit: log each tool call (non-blocking — must not lose tool results)
    try:
        task_id = state.get("task_id", "")
        audit = get_logger(task_id)
        if audit:
            last_msg = state["messages"][-1]
            if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                for tc in last_msg.tool_calls:
                    tool_name = tc.get("name", "unknown")
                    file_path = tc.get("args", {}).get("file_path")
                    # Determine result prefix from tool messages
                    result_prefix = "SUCCESS"
                    tool_messages = result.get("messages", [])
                    for tm in tool_messages:
                        if hasattr(tm, "tool_call_id") and tm.tool_call_id == tc.get("id"):
                            content = str(getattr(tm, "content", ""))
                            if content.startswith("ERROR"):
                                result_prefix = "ERROR"
                            break
                    audit.log_tool_call(tool_name, file_path, result_prefix)
    except Exception as e:
        logger.warning("Audit logging failed in tool_node: %s", e)

    return result


def error_handler(state: AgentState) -> dict[str, Any]:
    """Append an error message when the agent exceeds the maximum turn limit."""
    msg = f"ERROR: Agent exceeded maximum turn limit ({MAX_RETRIES}). Task terminated."
    return {"messages": [AIMessage(content=msg)]}


def should_continue(state: AgentState) -> Literal["tools", "end", "error"]:
    """Route after the agent node: continue to tools, end, or error on retry cap."""
    if not state.get("messages"):
        return "end"

    retry_count = state.get("retry_count", 0)
    if retry_count >= MAX_RETRIES:
        logger.error("Retry limit reached (%d turns). Stopping.", retry_count)
        return "error"

    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    return "end"

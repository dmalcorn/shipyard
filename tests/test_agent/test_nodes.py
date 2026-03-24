"""Tests for agent node functions — specifically should_continue routing."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from src.agent.nodes import MAX_RETRIES, error_handler, should_continue
from src.agent.state import AgentState


class TestShouldContinue:
    """Verify routing logic for the conditional edge."""

    def _make_state(
        self,
        last_message: AIMessage | HumanMessage,
        retry_count: int = 0,
    ) -> AgentState:
        return {
            "messages": [last_message],
            "task_id": "test-1",
            "retry_count": retry_count,
            "current_phase": "dev",
            "agent_role": "dev",
            "files_modified": [],
        }

    def test_routes_to_tools_when_tool_calls_present(self) -> None:
        """AI message with tool_calls → route to 'tools'."""
        ai_msg = AIMessage(
            content="I'll read the file.",
            tool_calls=[{"id": "1", "name": "read_file", "args": {"file_path": "foo.py"}}],
        )
        state = self._make_state(ai_msg)
        assert should_continue(state) == "tools"

    def test_routes_to_end_when_no_tool_calls(self) -> None:
        """AI message without tool_calls → route to 'end'."""
        ai_msg = AIMessage(content="Done. The file has been edited.")
        state = self._make_state(ai_msg)
        assert should_continue(state) == "end"

    def test_routes_to_error_when_retry_exceeded(self) -> None:
        """Retry count at or above MAX_RETRIES → route to 'error'."""
        ai_msg = AIMessage(
            content="Still going.",
            tool_calls=[{"id": "1", "name": "read_file", "args": {"file_path": "foo.py"}}],
        )
        state = self._make_state(ai_msg, retry_count=MAX_RETRIES)
        assert should_continue(state) == "error"

    def test_routes_to_error_above_max(self) -> None:
        """Retry count above MAX_RETRIES also routes to error."""
        ai_msg = AIMessage(content="Done.")
        state = self._make_state(ai_msg, retry_count=MAX_RETRIES + 5)
        assert should_continue(state) == "error"

    def test_routes_to_end_on_empty_messages(self) -> None:
        """Empty messages list → route to 'end'."""
        state: AgentState = {
            "messages": [],
            "task_id": "test-1",
            "retry_count": 0,
            "current_phase": "dev",
            "agent_role": "dev",
            "files_modified": [],
        }
        assert should_continue(state) == "end"


class TestErrorHandler:
    """Verify error_handler appends termination message."""

    def test_error_handler_returns_error_message(self) -> None:
        state: AgentState = {
            "messages": [],
            "task_id": "test-1",
            "retry_count": MAX_RETRIES,
            "current_phase": "dev",
            "agent_role": "dev",
            "files_modified": [],
        }
        result = error_handler(state)
        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, AIMessage)
        assert "ERROR" in msg.content
        assert "maximum turn limit" in msg.content

"""Tests for AgentState schema."""

from __future__ import annotations

import operator
from typing import get_type_hints

from src.agent.state import AgentState


class TestAgentState:
    """Verify AgentState has all required fields with correct types."""

    def test_has_required_fields(self) -> None:
        """AgentState includes all fields from the architecture spec."""
        hints = get_type_hints(AgentState, include_extras=True)
        assert "task_id" in hints
        assert "retry_count" in hints
        assert "current_phase" in hints
        assert "agent_role" in hints
        assert "files_modified" in hints
        # messages comes from MessagesState
        assert "messages" in hints

    def test_files_modified_uses_add_reducer(self) -> None:
        """files_modified must use operator.add for append semantics."""
        hints = get_type_hints(AgentState, include_extras=True)
        fm_hint = hints["files_modified"]
        # Annotated types have __metadata__
        assert hasattr(fm_hint, "__metadata__"), "files_modified should be Annotated"
        assert fm_hint.__metadata__[0] is operator.add

    def test_state_instantiation(self) -> None:
        """AgentState can be instantiated as a TypedDict."""
        state: AgentState = {
            "messages": [],
            "task_id": "test-1",
            "retry_count": 0,
            "current_phase": "dev",
            "agent_role": "dev",
            "files_modified": [],
        }
        assert state["task_id"] == "test-1"
        assert state["retry_count"] == 0
        assert state["files_modified"] == []

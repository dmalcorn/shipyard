"""Tests for sub-agent spawning in src/multi_agent/spawn.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.multi_agent.roles import get_tools_for_role
from src.multi_agent.spawn import (
    MAX_LLM_TURNS,
    _should_continue,
    create_agent_subgraph,
    run_sub_agent,
)


@pytest.fixture
def checkpoints_db(tmp_path: Path) -> str:
    """Provide a temporary SQLite database path for checkpointing."""
    return str(tmp_path / "test_checkpoints.db")


class TestCreateAgentSubgraph:
    """Tests for create_agent_subgraph() factory."""

    def test_returns_compiled_graph_state_and_conn(self, checkpoints_db: str) -> None:
        """Factory returns a tuple of (compiled_graph, initial_state, connection)."""
        graph, state, conn = create_agent_subgraph(
            role="dev",
            task_description="Write hello world",
            checkpoints_db=checkpoints_db,
        )
        try:
            assert graph is not None
            assert isinstance(state, dict)
            assert conn is not None
        finally:
            conn.close()

    def test_dev_agent_tool_count(self, checkpoints_db: str) -> None:
        """Dev Agent subgraph has 6 tools bound."""
        _, _, conn = create_agent_subgraph(
            role="dev",
            task_description="task",
            checkpoints_db=checkpoints_db,
        )
        conn.close()
        # The compiled graph's nodes include 'tools' which wraps the ToolNode
        # We verify by checking the tool count via the role config
        tools = get_tools_for_role("dev")
        assert len(tools) == 6

    def test_reviewer_agent_tool_count(self, checkpoints_db: str) -> None:
        """Reviewer Agent subgraph has 4 tools bound."""
        _, _, conn = create_agent_subgraph(
            role="reviewer",
            task_description="review code",
            checkpoints_db=checkpoints_db,
        )
        conn.close()

        tools = get_tools_for_role("reviewer")
        assert len(tools) == 4

    def test_initial_state_has_fresh_messages(self, checkpoints_db: str) -> None:
        """Sub-agent receives fresh messages, not parent history."""
        _, state, conn = create_agent_subgraph(
            role="dev",
            task_description="Implement feature X",
            checkpoints_db=checkpoints_db,
        )
        conn.close()
        messages = state["messages"]
        # Should have exactly 1 HumanMessage from inject_task_context
        assert len(messages) == 1
        assert "Implement feature X" in str(messages[0].content)

    def test_initial_state_has_zero_retry_count(self, checkpoints_db: str) -> None:
        """Sub-agent starts with retry_count=0."""
        _, state, conn = create_agent_subgraph(
            role="dev",
            task_description="task",
            checkpoints_db=checkpoints_db,
        )
        conn.close()
        assert state["retry_count"] == 0

    def test_initial_state_has_role(self, checkpoints_db: str) -> None:
        """Sub-agent state has the correct agent_role."""
        _, state, conn = create_agent_subgraph(
            role="reviewer",
            task_description="task",
            checkpoints_db=checkpoints_db,
        )
        conn.close()
        assert state["agent_role"] == "reviewer"

    def test_initial_state_empty_files_modified(self, checkpoints_db: str) -> None:
        """Sub-agent starts with empty files_modified list."""
        _, state, conn = create_agent_subgraph(
            role="dev",
            task_description="task",
            checkpoints_db=checkpoints_db,
        )
        conn.close()
        assert state["files_modified"] == []

    def test_context_files_injected(self, checkpoints_db: str, tmp_path: Path) -> None:
        """Context files are included in the initial messages."""
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("# Context\nSome important info")

        _, state, conn = create_agent_subgraph(
            role="dev",
            task_description="Use the context",
            context_files=[str(ctx_file)],
            checkpoints_db=checkpoints_db,
        )
        conn.close()
        msg_content = str(state["messages"][0].content)
        assert "Some important info" in msg_content

    def test_invalid_role_raises(self, checkpoints_db: str) -> None:
        """Invalid role raises ValueError."""
        with pytest.raises(ValueError, match="Unknown role"):
            create_agent_subgraph(
                role="invalid",
                task_description="task",
                checkpoints_db=checkpoints_db,
            )

    def test_no_parent_messages_shared(self, checkpoints_db: str) -> None:
        """Sub-agent does not receive parent message history."""
        _, state, conn = create_agent_subgraph(
            role="test",
            task_description="Write tests for foo",
            checkpoints_db=checkpoints_db,
        )
        conn.close()
        # Only the task instruction message, no prior conversation
        assert len(state["messages"]) == 1
        assert "Write tests for foo" in str(state["messages"][0].content)


class TestShouldContinue:
    """Tests for the _should_continue routing function."""

    def test_empty_messages_returns_end(self) -> None:
        """No messages -> end."""
        state: dict[str, Any] = {"messages": [], "retry_count": 0}
        assert _should_continue(state) == "end"  # type: ignore[arg-type]

    def test_retry_exceeded_returns_error(self) -> None:
        """Retry count at max -> error."""
        state: dict[str, Any] = {
            "messages": [AIMessage(content="done")],
            "retry_count": MAX_LLM_TURNS,
        }
        assert _should_continue(state) == "error"  # type: ignore[arg-type]

    def test_tool_calls_returns_tools(self) -> None:
        """AI message with tool calls -> tools."""
        msg = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "1"}])
        state: dict[str, Any] = {"messages": [msg], "retry_count": 0}
        assert _should_continue(state) == "tools"  # type: ignore[arg-type]

    def test_no_tool_calls_returns_end(self) -> None:
        """AI message without tool calls -> end."""
        state: dict[str, Any] = {"messages": [AIMessage(content="all done")], "retry_count": 0}
        assert _should_continue(state) == "end"  # type: ignore[arg-type]


class TestRunSubAgent:
    """Tests for run_sub_agent() orchestrator wrapper."""

    def test_config_includes_parent_session(self, checkpoints_db: str) -> None:
        """Sub-agent config includes parent_session metadata for trace linking."""
        captured_config: dict[str, Any] = {}

        def mock_invoke(
            state: dict[str, Any],
            config: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            captured_config.update(config or {})
            return {
                "messages": [],
                "files_modified": [],
                "retry_count": 1,
                "task_id": "t",
                "current_phase": "test",
                "agent_role": "dev",
            }

        with patch("src.multi_agent.spawn.create_agent_subgraph") as mock_create:
            mock_graph = MagicMock()
            mock_graph.invoke = mock_invoke
            mock_conn = MagicMock()
            mock_create.return_value = (
                mock_graph,
                {
                    "messages": [],
                    "task_id": "",
                    "retry_count": 0,
                    "current_phase": "",
                    "agent_role": "dev",
                    "files_modified": [],
                },
                mock_conn,
            )

            run_sub_agent(
                parent_session_id="parent-123",
                task_id="story-1",
                role="dev",
                task_description="Do stuff",
                current_phase="implementation",
                checkpoints_db=checkpoints_db,
            )

        assert captured_config["metadata"]["parent_session"] == "parent-123"
        assert captured_config["metadata"]["agent_role"] == "dev"
        assert captured_config["metadata"]["task_id"] == "story-1"
        assert captured_config["metadata"]["phase"] == "implementation"
        mock_conn.close.assert_called_once()

    def test_sub_agent_thread_id_distinct_from_parent(self, checkpoints_db: str) -> None:
        """Sub-agent gets its own unique thread_id."""
        captured_config: dict[str, Any] = {}

        def mock_invoke(
            state: dict[str, Any],
            config: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            captured_config.update(config or {})
            return {
                "messages": [],
                "files_modified": [],
                "retry_count": 1,
                "task_id": "t",
                "current_phase": "test",
                "agent_role": "dev",
            }

        with patch("src.multi_agent.spawn.create_agent_subgraph") as mock_create:
            mock_graph = MagicMock()
            mock_graph.invoke = mock_invoke
            mock_conn = MagicMock()
            mock_create.return_value = (
                mock_graph,
                {
                    "messages": [],
                    "task_id": "",
                    "retry_count": 0,
                    "current_phase": "",
                    "agent_role": "dev",
                    "files_modified": [],
                },
                mock_conn,
            )

            run_sub_agent(
                parent_session_id="parent-123",
                task_id="story-1",
                role="dev",
                task_description="Do stuff",
                current_phase="implementation",
                checkpoints_db=checkpoints_db,
            )

        thread_id = captured_config["configurable"]["thread_id"]
        assert thread_id != "parent-123"
        assert thread_id.startswith("parent-123-dev-")

    def test_returns_files_modified(self, checkpoints_db: str) -> None:
        """run_sub_agent returns files_modified from sub-agent state."""
        with patch("src.multi_agent.spawn.create_agent_subgraph") as mock_create:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = {
                "messages": [],
                "files_modified": ["src/foo.py", "src/bar.py"],
                "retry_count": 3,
                "task_id": "t",
                "current_phase": "implementation",
                "agent_role": "dev",
            }
            mock_conn = MagicMock()
            mock_create.return_value = (
                mock_graph,
                {
                    "messages": [],
                    "task_id": "",
                    "retry_count": 0,
                    "current_phase": "",
                    "agent_role": "dev",
                    "files_modified": [],
                },
                mock_conn,
            )

            result = run_sub_agent(
                parent_session_id="p",
                task_id="t",
                role="dev",
                task_description="task",
                current_phase="implementation",
                checkpoints_db=checkpoints_db,
            )

        assert result["files_modified"] == ["src/foo.py", "src/bar.py"]

    def test_returns_final_message(self, checkpoints_db: str) -> None:
        """run_sub_agent extracts final message content."""
        with patch("src.multi_agent.spawn.create_agent_subgraph") as mock_create:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = {
                "messages": [AIMessage(content="All done, 3 files modified.")],
                "files_modified": [],
                "retry_count": 2,
                "task_id": "t",
                "current_phase": "implementation",
                "agent_role": "dev",
            }
            mock_conn = MagicMock()
            mock_create.return_value = (
                mock_graph,
                {
                    "messages": [],
                    "task_id": "",
                    "retry_count": 0,
                    "current_phase": "",
                    "agent_role": "dev",
                    "files_modified": [],
                },
                mock_conn,
            )

            result = run_sub_agent(
                parent_session_id="p",
                task_id="t",
                role="dev",
                task_description="task",
                current_phase="implementation",
                checkpoints_db=checkpoints_db,
            )

        assert "All done" in result["final_message"]

    def test_model_tier_in_metadata(self, checkpoints_db: str) -> None:
        """Config metadata includes correct model_tier for the role."""
        captured_config: dict[str, Any] = {}

        def mock_invoke(
            state: dict[str, Any],
            config: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            captured_config.update(config or {})
            return {
                "messages": [],
                "files_modified": [],
                "retry_count": 1,
                "task_id": "t",
                "current_phase": "review",
                "agent_role": "architect",
            }

        with patch("src.multi_agent.spawn.create_agent_subgraph") as mock_create:
            mock_graph = MagicMock()
            mock_graph.invoke = mock_invoke
            mock_conn = MagicMock()
            mock_create.return_value = (
                mock_graph,
                {
                    "messages": [],
                    "task_id": "",
                    "retry_count": 0,
                    "current_phase": "",
                    "agent_role": "architect",
                    "files_modified": [],
                },
                mock_conn,
            )

            run_sub_agent(
                parent_session_id="p",
                task_id="t",
                role="architect",
                task_description="triage reviews",
                current_phase="architect",
                checkpoints_db=checkpoints_db,
            )

        assert captured_config["metadata"]["model_tier"] == "opus"

    def test_connection_closed_after_invoke(self, checkpoints_db: str) -> None:
        """SQLite connection is closed after sub-agent completes."""
        with patch("src.multi_agent.spawn.create_agent_subgraph") as mock_create:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = {
                "messages": [],
                "files_modified": [],
                "retry_count": 1,
                "task_id": "t",
                "current_phase": "test",
                "agent_role": "dev",
            }
            mock_conn = MagicMock()
            mock_create.return_value = (
                mock_graph,
                {
                    "messages": [],
                    "task_id": "",
                    "retry_count": 0,
                    "current_phase": "",
                    "agent_role": "dev",
                    "files_modified": [],
                },
                mock_conn,
            )

            run_sub_agent(
                parent_session_id="p",
                task_id="t",
                role="dev",
                task_description="task",
                current_phase="implementation",
                checkpoints_db=checkpoints_db,
            )

        mock_conn.close.assert_called_once()


class TestSpawnWorkingDirThreading:
    """Tests that spawn.py passes working_dir to build_system_prompt and inject_task_context."""

    @patch("src.multi_agent.spawn.inject_task_context")
    @patch("src.multi_agent.spawn.build_system_prompt")
    @patch("src.multi_agent.spawn.ChatAnthropic")
    @patch("src.multi_agent.spawn.SqliteSaver")
    @patch("src.multi_agent.spawn.sqlite3.connect")
    def test_working_dir_passed_to_build_system_prompt(
        self,
        mock_connect: MagicMock,
        mock_saver: MagicMock,
        mock_chat: MagicMock,
        mock_build_prompt: MagicMock,
        mock_inject: MagicMock,
        checkpoints_db: str,
    ) -> None:
        """create_agent_subgraph passes working_dir to build_system_prompt."""
        mock_connect.return_value = MagicMock()
        mock_saver.return_value = InMemorySaver()
        mock_build_prompt.return_value = "system prompt"
        mock_inject.return_value = []
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_chat.return_value = mock_llm

        _, _, conn = create_agent_subgraph(
            role="dev",
            task_description="task",
            checkpoints_db=checkpoints_db,
            working_dir="/my/target",
        )
        conn.close()

        mock_build_prompt.assert_called_once()
        assert mock_build_prompt.call_args.kwargs.get("working_dir") == "/my/target"

    @patch("src.multi_agent.spawn.inject_task_context")
    @patch("src.multi_agent.spawn.build_system_prompt")
    @patch("src.multi_agent.spawn.ChatAnthropic")
    @patch("src.multi_agent.spawn.SqliteSaver")
    @patch("src.multi_agent.spawn.sqlite3.connect")
    def test_working_dir_passed_to_inject_task_context(
        self,
        mock_connect: MagicMock,
        mock_saver: MagicMock,
        mock_chat: MagicMock,
        mock_build_prompt: MagicMock,
        mock_inject: MagicMock,
        checkpoints_db: str,
    ) -> None:
        """create_agent_subgraph passes working_dir to inject_task_context."""
        mock_connect.return_value = MagicMock()
        mock_saver.return_value = InMemorySaver()
        mock_build_prompt.return_value = "system prompt"
        mock_inject.return_value = []
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_chat.return_value = mock_llm

        _, _, conn = create_agent_subgraph(
            role="dev",
            task_description="task",
            checkpoints_db=checkpoints_db,
            working_dir="/my/target",
        )
        conn.close()

        mock_inject.assert_called_once()
        assert mock_inject.call_args.kwargs.get("working_dir") == "/my/target"

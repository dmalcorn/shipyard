"""Tests for sub-agent spawning in src/multi_agent/spawn.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.multi_agent.spawn import (
    MAX_RETRIES,
    _should_continue,
    create_agent_subgraph,
    run_sub_agent,
)


@pytest.fixture
def checkpoints_db(tmp_path: object) -> str:
    """Provide a temporary SQLite database path for checkpointing."""
    return str(tmp_path / "test_checkpoints.db")  # type: ignore[operator]


class TestCreateAgentSubgraph:
    """Tests for create_agent_subgraph() factory."""

    def test_returns_compiled_graph_and_state(self, checkpoints_db: str) -> None:
        """Factory returns a tuple of (compiled_graph, initial_state)."""
        graph, state = create_agent_subgraph(
            role="dev",
            task_description="Write hello world",
            checkpoints_db=checkpoints_db,
        )
        assert graph is not None
        assert isinstance(state, dict)

    def test_dev_agent_tool_count(self, checkpoints_db: str) -> None:
        """Dev Agent subgraph has 6 tools bound."""
        graph, _ = create_agent_subgraph(
            role="dev",
            task_description="task",
            checkpoints_db=checkpoints_db,
        )
        # The compiled graph's nodes include 'tools' which wraps the ToolNode
        # We verify by checking the tool count via the role config
        from src.multi_agent.roles import get_tools_for_role

        tools = get_tools_for_role("dev")
        assert len(tools) == 6

    def test_reviewer_agent_tool_count(self, checkpoints_db: str) -> None:
        """Reviewer Agent subgraph has 4 tools bound."""
        graph, _ = create_agent_subgraph(
            role="reviewer",
            task_description="review code",
            checkpoints_db=checkpoints_db,
        )
        from src.multi_agent.roles import get_tools_for_role

        tools = get_tools_for_role("reviewer")
        assert len(tools) == 4

    def test_initial_state_has_fresh_messages(self, checkpoints_db: str) -> None:
        """Sub-agent receives fresh messages, not parent history."""
        _, state = create_agent_subgraph(
            role="dev",
            task_description="Implement feature X",
            checkpoints_db=checkpoints_db,
        )
        messages = state["messages"]
        # Should have exactly 1 HumanMessage from inject_task_context
        assert len(messages) == 1
        assert "Implement feature X" in str(messages[0].content)

    def test_initial_state_has_zero_retry_count(self, checkpoints_db: str) -> None:
        """Sub-agent starts with retry_count=0."""
        _, state = create_agent_subgraph(
            role="dev",
            task_description="task",
            checkpoints_db=checkpoints_db,
        )
        assert state["retry_count"] == 0

    def test_initial_state_has_role(self, checkpoints_db: str) -> None:
        """Sub-agent state has the correct agent_role."""
        _, state = create_agent_subgraph(
            role="reviewer",
            task_description="task",
            checkpoints_db=checkpoints_db,
        )
        assert state["agent_role"] == "reviewer"

    def test_initial_state_empty_files_modified(self, checkpoints_db: str) -> None:
        """Sub-agent starts with empty files_modified list."""
        _, state = create_agent_subgraph(
            role="dev",
            task_description="task",
            checkpoints_db=checkpoints_db,
        )
        assert state["files_modified"] == []

    def test_context_files_injected(self, checkpoints_db: str, tmp_path: object) -> None:
        """Context files are included in the initial messages."""
        ctx_file = tmp_path / "context.md"  # type: ignore[operator]
        ctx_file.write_text("# Context\nSome important info")

        _, state = create_agent_subgraph(
            role="dev",
            task_description="Use the context",
            context_files=[str(ctx_file)],
            checkpoints_db=checkpoints_db,
        )
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
        _, state = create_agent_subgraph(
            role="test",
            task_description="Write tests for foo",
            checkpoints_db=checkpoints_db,
        )
        # Only the task instruction message, no prior conversation
        assert len(state["messages"]) == 1
        assert "Write tests for foo" in str(state["messages"][0].content)


class TestShouldContinue:
    """Tests for the _should_continue routing function."""

    def test_empty_messages_returns_end(self) -> None:
        """No messages → end."""
        state: dict = {"messages": [], "retry_count": 0}
        assert _should_continue(state) == "end"  # type: ignore[arg-type]

    def test_retry_exceeded_returns_error(self) -> None:
        """Retry count at max → error."""
        from langchain_core.messages import AIMessage

        state: dict = {
            "messages": [AIMessage(content="done")],
            "retry_count": MAX_RETRIES,
        }
        assert _should_continue(state) == "error"  # type: ignore[arg-type]

    def test_tool_calls_returns_tools(self) -> None:
        """AI message with tool calls → tools."""
        from langchain_core.messages import AIMessage

        msg = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "1"}])
        state: dict = {"messages": [msg], "retry_count": 0}
        assert _should_continue(state) == "tools"  # type: ignore[arg-type]

    def test_no_tool_calls_returns_end(self) -> None:
        """AI message without tool calls → end."""
        from langchain_core.messages import AIMessage

        state: dict = {"messages": [AIMessage(content="all done")], "retry_count": 0}
        assert _should_continue(state) == "end"  # type: ignore[arg-type]


class TestRunSubAgent:
    """Tests for run_sub_agent() orchestrator wrapper."""

    def test_config_includes_parent_session(self, checkpoints_db: str) -> None:
        """Sub-agent config includes parent_session metadata for trace linking."""
        captured_config: dict = {}

        def mock_invoke(state: dict, config: dict | None = None) -> dict:
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

    def test_sub_agent_thread_id_distinct_from_parent(self, checkpoints_db: str) -> None:
        """Sub-agent gets its own unique thread_id."""
        captured_config: dict = {}

        def mock_invoke(state: dict, config: dict | None = None) -> dict:
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
        from langchain_core.messages import AIMessage

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
        captured_config: dict = {}

        def mock_invoke(state: dict, config: dict | None = None) -> dict:
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
            )

            run_sub_agent(
                parent_session_id="p",
                task_id="t",
                role="architect",
                task_description="triage reviews",
                current_phase="review",
                checkpoints_db=checkpoints_db,
            )

        assert captured_config["metadata"]["model_tier"] == "opus"

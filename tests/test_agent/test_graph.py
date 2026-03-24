"""Tests for graph compilation and structure."""

from __future__ import annotations

import os

from src.agent.graph import create_agent, create_trace_config


class TestGraphStructure:
    """Verify the graph compiles and has correct topology."""

    def test_graph_compiles(self, tmp_path: os.PathLike[str]) -> None:
        """create_agent returns a compiled graph without errors."""
        db_path = os.path.join(tmp_path, "test.db")
        graph = create_agent(checkpoints_db=db_path)
        assert graph is not None

    def test_graph_has_expected_nodes(self, tmp_path: os.PathLike[str]) -> None:
        """Graph contains 'agent' and 'tools' nodes."""
        db_path = os.path.join(tmp_path, "test.db")
        graph = create_agent(checkpoints_db=db_path)
        node_names = set(graph.get_graph().nodes.keys())
        assert "agent" in node_names
        assert "tools" in node_names

    def test_graph_has_start_and_end(self, tmp_path: os.PathLike[str]) -> None:
        """Graph has __start__ and __end__ nodes."""
        db_path = os.path.join(tmp_path, "test.db")
        graph = create_agent(checkpoints_db=db_path)
        node_names = set(graph.get_graph().nodes.keys())
        assert "__start__" in node_names
        assert "__end__" in node_names


class TestCreateTraceConfig:
    """Verify create_trace_config builds correct LangSmith config dicts."""

    def test_returns_configurable_and_metadata(self) -> None:
        """Config has both configurable and metadata keys."""
        config = create_trace_config(session_id="s1", task_id="t1")
        assert "configurable" in config
        assert "metadata" in config

    def test_default_agent_role_and_phase(self) -> None:
        """Defaults to agent_role=dev, model_tier=sonnet, phase=implementation."""
        config = create_trace_config(session_id="s1", task_id="t1")
        meta = config["metadata"]
        assert meta["agent_role"] == "dev"
        assert meta["model_tier"] == "sonnet"
        assert meta["phase"] == "implementation"

    def test_custom_values_passed_through(self) -> None:
        """Custom agent_role, model_tier, phase are passed through."""
        config = create_trace_config(
            session_id="s1",
            task_id="t1",
            agent_role="reviewer",
            model_tier="opus",
            phase="review",
        )
        meta = config["metadata"]
        assert meta["agent_role"] == "reviewer"
        assert meta["model_tier"] == "opus"
        assert meta["phase"] == "review"

    def test_parent_session_forwarded(self) -> None:
        """parent_session is included when provided."""
        config = create_trace_config(session_id="child", task_id="t1", parent_session="parent")
        assert config["metadata"]["parent_session"] == "parent"

    def test_thread_id_set(self) -> None:
        """configurable.thread_id matches session_id."""
        config = create_trace_config(session_id="sess-abc", task_id="t1")
        assert config["configurable"]["thread_id"] == "sess-abc"

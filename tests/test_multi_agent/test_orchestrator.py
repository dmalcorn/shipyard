"""Tests for the redesigned story orchestrator pipeline.

Tests cover:
- OrchestratorState schema fields
- Pipeline node count and edge connections
- Bash nodes do NOT invoke LLM
- Conditional routing: test fail → implement retry
- Conditional routing: CI fail → fix_ci retry
- Retry limit exceeded → error handler
- Error handler produces structured failure report
- Graph compiles and runs
- LLM nodes invoke BMAD agents via invoke_bmad_agent
- Bash nodes pass working_dir
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import src.multi_agent.orchestrator as orch_module
from src.multi_agent.orchestrator import (
    MAX_CI_CYCLES,
    MAX_TEST_CYCLES,
    OrchestratorState,
    _get_working_dir,
    build_orchestrator,
    build_orchestrator_graph,
    code_review_node,
    error_handler_node,
    fix_ci_node,
    git_commit_node,
    implement_node,
    route_after_ci,
    route_after_tests,
    run_ci_node,
    run_tests_node,
    write_tests_node,
)


# ---------------------------------------------------------------------------
# State Schema Tests
# ---------------------------------------------------------------------------


class TestOrchestratorState:
    """Tests for OrchestratorState TypedDict schema."""

    def test_has_task_identity_fields(self) -> None:
        state: OrchestratorState = {
            "task_id": "2-1",
            "task_description": "Build feature X",
            "session_id": "sess-1",
        }
        assert state["task_id"] == "2-1"
        assert state["task_description"] == "Build feature X"
        assert state["session_id"] == "sess-1"

    def test_has_retry_counters(self) -> None:
        state: OrchestratorState = {
            "test_cycle_count": 2,
            "ci_cycle_count": 1,
        }
        assert state["test_cycle_count"] == 2
        assert state["ci_cycle_count"] == 1

    def test_has_pipeline_tracking_fields(self) -> None:
        state: OrchestratorState = {
            "current_phase": "run_tests",
            "pipeline_status": "running",
            "error_log": ["test failed"],
        }
        assert state["current_phase"] == "run_tests"
        assert state["pipeline_status"] == "running"

    def test_has_review_gate_fields(self) -> None:
        state: OrchestratorState = {
            "has_review_issues": True,
            "review_file_path": "reviews/test-review.md",
        }
        assert state["has_review_issues"] is True
        assert state["review_file_path"] == "reviews/test-review.md"

    def test_has_test_output_fields(self) -> None:
        state: OrchestratorState = {
            "test_passed": False,
            "last_test_output": "FAILED test_foo",
            "last_ci_output": "ruff error",
        }
        assert state["last_test_output"] == "FAILED test_foo"
        assert state["last_ci_output"] == "ruff error"

    def test_retry_limits_are_defined(self) -> None:
        assert MAX_TEST_CYCLES == 5
        assert MAX_CI_CYCLES == 4


# ---------------------------------------------------------------------------
# Graph Structure Tests
# ---------------------------------------------------------------------------


class TestBuildOrchestratorGraph:
    """Tests for build_orchestrator_graph construction."""

    def test_graph_has_all_pipeline_nodes(self) -> None:
        graph = build_orchestrator_graph()
        node_names = set(graph.nodes.keys())
        expected = {
            "write_tests",
            "implement",
            "code_review",
            "run_ci",
            "fix_ci",
            "git_commit",
            "error_handler",
        }
        assert expected.issubset(node_names), f"Missing: {expected - node_names}"

    def test_node_count(self) -> None:
        """Graph has exactly 8 nodes."""
        graph = build_orchestrator_graph()
        assert len(graph.nodes) == 8

    def test_graph_compiles(self) -> None:
        graph = build_orchestrator_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_build_orchestrator_returns_compiled(self) -> None:
        compiled = build_orchestrator()
        assert compiled is not None


# ---------------------------------------------------------------------------
# Bash Node Tests
# ---------------------------------------------------------------------------


class TestBashNodes:
    """Bash nodes call shell commands, never LLM."""

    @patch("src.multi_agent.orchestrator._run_bash", return_value=(True, "ok"))
    def test_run_tests_node_calls_test_command(self, mock_bash: MagicMock) -> None:
        state: OrchestratorState = {"session_id": "s1", "test_cycle_count": 0}
        result = run_tests_node(state)
        mock_bash.assert_called()
        assert result["test_passed"] is True
        assert result["test_cycle_count"] == 1

    @patch("src.multi_agent.orchestrator._run_bash", return_value=(True, "ok"))
    def test_run_ci_node_calls_ci(self, mock_bash: MagicMock) -> None:
        state: OrchestratorState = {"session_id": "s1", "ci_cycle_count": 0}
        result = run_ci_node(state)
        mock_bash.assert_called()
        assert result["test_passed"] is True
        assert result["ci_cycle_count"] == 1

    @patch("src.multi_agent.orchestrator._run_bash", return_value=(True, "ok"))
    def test_git_commit_node_commits(self, mock_bash: MagicMock) -> None:
        state: OrchestratorState = {"task_id": "2-1", "session_id": "s1", "working_dir": "/tmp/test"}
        result = git_commit_node(state)
        assert result["pipeline_status"] == "completed"

    @patch("src.multi_agent.orchestrator._run_bash", return_value=(False, "error"))
    def test_git_commit_failure_reports_error(self, mock_bash: MagicMock) -> None:
        state: OrchestratorState = {"task_id": "2-1", "session_id": "s1", "working_dir": "/tmp/test"}
        result = git_commit_node(state)
        assert result["pipeline_status"] == "failed"
        assert "error" in result

    def test_bash_nodes_do_not_invoke_llm(self) -> None:
        """Verify bash nodes never import or call invoke_bmad_agent."""
        import inspect
        bash_nodes = [run_tests_node, run_ci_node, git_commit_node]
        for node_fn in bash_nodes:
            source = inspect.getsource(node_fn)
            assert "invoke_bmad_agent" not in source, (
                f"{node_fn.__name__} should not reference invoke_bmad_agent"
            )


# ---------------------------------------------------------------------------
# Routing Tests
# ---------------------------------------------------------------------------


class TestRouteAfterTests:
    """Conditional routing after run_tests."""

    def test_pass_on_success(self) -> None:
        state: OrchestratorState = {"test_passed": True}
        assert route_after_tests(state) == "pass"

    def test_retry_on_failure_under_limit(self) -> None:
        state: OrchestratorState = {"test_passed": False, "test_cycle_count": 1}
        assert route_after_tests(state) == "retry"

    def test_error_on_limit_exceeded(self) -> None:
        state: OrchestratorState = {
            "test_passed": False,
            "test_cycle_count": MAX_TEST_CYCLES,
        }
        assert route_after_tests(state) == "error"


class TestRouteAfterCI:
    """Conditional routing after run_ci."""

    def test_pass_on_success(self) -> None:
        state: OrchestratorState = {"test_passed": True}
        assert route_after_ci(state) == "pass"

    def test_retry_on_failure_under_limit(self) -> None:
        state: OrchestratorState = {"test_passed": False, "ci_cycle_count": 1}
        assert route_after_ci(state) == "retry"

    def test_error_on_limit_exceeded(self) -> None:
        state: OrchestratorState = {
            "test_passed": False,
            "ci_cycle_count": MAX_CI_CYCLES,
        }
        assert route_after_ci(state) == "error"


# ---------------------------------------------------------------------------
# Error Handler Tests
# ---------------------------------------------------------------------------


class TestErrorHandler:
    """Error handler produces structured failure report."""

    def test_produces_failure_report_format(self) -> None:
        state: OrchestratorState = {
            "task_id": "2-1",
            "current_phase": "run_tests",
            "test_cycle_count": 5,
            "ci_cycle_count": 0,
            "error_log": ["run_tests: Tests failed (cycle 5)"],
            "files_modified": ["src/app.py"],
            "session_id": "s1",
        }
        result = error_handler_node(state)
        assert result["pipeline_status"] == "failed"
        assert "2-1" in result["error"]
        assert "run_tests" in result["error"]

    def test_empty_error_log(self) -> None:
        state: OrchestratorState = {
            "task_id": "2-1",
            "current_phase": "run_ci",
            "error_log": [],
            "session_id": "",
        }
        result = error_handler_node(state)
        assert "No errors captured" in result["error"]

    def test_empty_files_modified(self) -> None:
        state: OrchestratorState = {
            "task_id": "2-1",
            "current_phase": "run_ci",
            "files_modified": [],
            "session_id": "",
        }
        result = error_handler_node(state)
        assert "None" in result["error"]


# ---------------------------------------------------------------------------
# LLM Node Tests (mock invoke_bmad_agent)
# ---------------------------------------------------------------------------


class TestLLMNodes:
    """LLM nodes invoke BMAD agents via invoke_bmad_agent."""

    @patch("src.multi_agent.orchestrator.invoke_bmad_agent")
    def test_write_tests_invokes_qa_agent(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = {"success": True, "files_modified": ["tests/test_app.py"], "output": "ok"}
        state: OrchestratorState = {"task_id": "2-1"}
        result = write_tests_node(state)
        mock_invoke.assert_called_once()
        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["bmad_agent"] == "bmad-testarch-atdd"
        assert "Acceptance Tests" in call_kwargs[1]["command"]
        assert result["current_phase"] == "write_tests"

    @patch("src.multi_agent.orchestrator.invoke_bmad_agent")
    def test_implement_invokes_dev_agent(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = {"success": True, "files_modified": ["src/app.py"], "output": "ok"}
        state: OrchestratorState = {"task_id": "2-1"}
        result = implement_node(state)
        mock_invoke.assert_called_once()
        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["bmad_agent"] == "bmad-dev-story"
        assert "develop story" in call_kwargs[1]["command"]
        assert result["current_phase"] == "implement"

    @patch("src.multi_agent.orchestrator.invoke_bmad_agent")
    def test_implement_includes_test_output_on_retry(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = {"success": True, "files_modified": [], "output": "ok"}
        state: OrchestratorState = {
            "task_id": "2-1",
            "test_cycle_count": 2,
            "last_test_output": "FAILED test_foo - AssertionError",
        }
        implement_node(state)
        call_kwargs = mock_invoke.call_args
        assert "retry 2" in call_kwargs[1]["extra_context"]
        assert "FAILED test_foo" in call_kwargs[1]["extra_context"]

    @patch("src.multi_agent.orchestrator.invoke_bmad_agent")
    def test_code_review_invokes_dev_agent(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = {"success": True, "files_modified": [], "output": "ok"}
        state: OrchestratorState = {"task_id": "2-1"}
        result = code_review_node(state)
        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["bmad_agent"] == "bmad-dev"
        assert "code review" in call_kwargs[1]["command"]
        assert result["current_phase"] == "code_review"

    @patch("src.multi_agent.orchestrator.invoke_bmad_agent")
    def test_fix_ci_invokes_dev_agent_with_output(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = {"success": True, "files_modified": ["src/fix.py"], "output": "ok"}
        state: OrchestratorState = {
            "task_id": "2-1",
            "last_ci_output": "ruff: E501 line too long",
        }
        result = fix_ci_node(state)
        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["bmad_agent"] == "bmad-dev"
        assert "ruff: E501" in call_kwargs[1]["extra_context"]
        assert result["current_phase"] == "fix_ci"

# ---------------------------------------------------------------------------
# Working Dir Tests
# ---------------------------------------------------------------------------


class TestGetWorkingDir:
    """_get_working_dir helper."""

    def test_returns_none_for_missing_key(self) -> None:
        assert _get_working_dir({}) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _get_working_dir({"working_dir": ""}) is None

    def test_returns_value_when_set(self) -> None:
        assert _get_working_dir({"working_dir": "/tmp/proj"}) == "/tmp/proj"

    def test_returns_none_for_none_value(self) -> None:
        assert _get_working_dir({"working_dir": None}) is None


class TestBashNodesPassWorkingDir:
    """Bash nodes pass working_dir as cwd to _run_bash."""

    @patch("src.multi_agent.orchestrator._run_bash", return_value=(True, "ok"))
    def test_run_tests_passes_cwd(self, mock_bash: MagicMock) -> None:
        state: OrchestratorState = {
            "session_id": "s1",
            "test_cycle_count": 0,
            "working_dir": "/tmp/proj",
        }
        run_tests_node(state)
        _, kwargs = mock_bash.call_args
        assert kwargs["cwd"] == "/tmp/proj"

    @patch("src.multi_agent.orchestrator._run_bash", return_value=(True, "ok"))
    def test_run_ci_passes_cwd(self, mock_bash: MagicMock) -> None:
        state: OrchestratorState = {
            "session_id": "s1",
            "ci_cycle_count": 0,
            "working_dir": "/tmp/proj",
        }
        run_ci_node(state)
        _, kwargs = mock_bash.call_args
        assert kwargs["cwd"] == "/tmp/proj"

    @patch("src.multi_agent.orchestrator._run_bash", return_value=(True, "ok"))
    def test_bash_nodes_none_cwd_without_working_dir(self, mock_bash: MagicMock) -> None:
        state: OrchestratorState = {"session_id": "s1", "test_cycle_count": 0}
        run_tests_node(state)
        _, kwargs = mock_bash.call_args
        assert kwargs["cwd"] is None


class TestLLMNodesPassWorkingDir:
    """LLM nodes pass working_dir to invoke_bmad_agent."""

    @patch("src.multi_agent.orchestrator.invoke_bmad_agent")
    def test_implement_passes_working_dir(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = {"success": True, "files_modified": [], "output": "ok"}
        state: OrchestratorState = {"task_id": "2-1", "working_dir": "/tmp/proj"}
        implement_node(state)
        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["working_dir"] == "/tmp/proj"

    @patch("src.multi_agent.orchestrator.invoke_bmad_agent")
    def test_write_tests_passes_working_dir(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = {"success": True, "files_modified": [], "output": "ok"}
        state: OrchestratorState = {"task_id": "2-1", "working_dir": "/tmp/proj"}
        write_tests_node(state)
        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["working_dir"] == "/tmp/proj"

    @patch("src.multi_agent.orchestrator.invoke_bmad_agent")
    def test_code_review_passes_working_dir(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = {"success": True, "files_modified": [], "output": "ok"}
        state: OrchestratorState = {"task_id": "2-1", "working_dir": "/tmp/proj"}
        code_review_node(state)
        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["working_dir"] == "/tmp/proj"

    @patch("src.multi_agent.orchestrator.invoke_bmad_agent")
    def test_llm_nodes_none_working_dir_when_absent(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = {"success": True, "files_modified": [], "output": "ok"}
        state: OrchestratorState = {"task_id": "2-1"}
        implement_node(state)
        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1]["working_dir"] is None

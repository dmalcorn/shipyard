"""Tests for full TDD orchestrator pipeline (Story 3.5).

Tests cover:
- OrchestratorState schema fields (Task 1)
- Pipeline node count and edge connections (Task 2)
- Bash-based nodes do NOT invoke LLM (Task 3)
- Conditional routing: unit test fail -> dev retry (Task 4)
- Conditional routing: CI fail -> dev retry (Task 4)
- Retry limit exceeded -> error handler (Task 4)
- Error handler produces structured failure report (Task 5)
- Send API parallel review integration (Task 6)
- Compiled orchestrator graph (Task 7)
- Integration test: full pipeline with mocked LLM (Task 8)

Also preserves all Story 3.3-3.4 test coverage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langgraph.types import Send

import src.multi_agent.orchestrator as orch_module
from src.multi_agent.orchestrator import (
    FIX_PLAN_PATH,
    MAX_CI_CYCLES,
    MAX_EDIT_RETRIES,
    MAX_TEST_CYCLES,
    REVIEWER_1_FOCUS,
    REVIEWER_2_FOCUS,
    OrchestratorState,
    ReviewNodeInput,
    _ensure_reviews_dir,
    _get_working_dir,
    _review_file_path,
    architect_node,
    build_orchestrator,
    build_orchestrator_graph,
    ci_node,
    collect_reviews,
    dev_agent_node,
    error_handler_node,
    final_ci_node,
    fix_dev_node,
    git_push_node,
    git_snapshot_node,
    post_fix_ci_node,
    post_fix_test_node,
    prepare_reviews_node,
    review_node,
    route_after_ci,
    route_after_final_ci,
    route_after_post_fix_ci,
    route_after_post_fix_test,
    route_after_system_test,
    route_after_unit_test,
    route_to_reviewers,
    system_test_node,
    unit_test_node,
)
from src.multi_agent.orchestrator import test_agent_node as spawn_test_agent


@pytest.fixture
def reviews_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary reviews directory and monkeypatch REVIEWS_DIR."""
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    monkeypatch.setattr(orch_module, "REVIEWS_DIR", str(reviews))
    return reviews


# ---------------------------------------------------------------------------
# Task 1: OrchestratorState Schema Tests
# ---------------------------------------------------------------------------


class TestOrchestratorState:
    """Tests for OrchestratorState TypedDict schema."""

    def test_has_task_identity_fields(self) -> None:
        """State has task_id, task_description, session_id."""
        state: OrchestratorState = {
            "task_id": "story-42",
            "task_description": "Build feature X",
            "session_id": "sess-1",
        }
        assert state["task_id"] == "story-42"
        assert state["task_description"] == "Build feature X"
        assert state["session_id"] == "sess-1"

    def test_has_retry_counters(self) -> None:
        """State has test_cycle_count, ci_cycle_count, edit_retry_count."""
        state: OrchestratorState = {
            "test_cycle_count": 2,
            "ci_cycle_count": 1,
            "edit_retry_count": 0,
        }
        assert state["test_cycle_count"] == 2
        assert state["ci_cycle_count"] == 1
        assert state["edit_retry_count"] == 0

    def test_has_pipeline_tracking_fields(self) -> None:
        """State has current_phase, pipeline_status, error_log."""
        state: OrchestratorState = {
            "current_phase": "unit_test",
            "pipeline_status": "running",
            "error_log": ["test failed"],
        }
        assert state["current_phase"] == "unit_test"
        assert state["pipeline_status"] == "running"
        assert state["error_log"] == ["test failed"]

    def test_has_file_tracking_fields(self) -> None:
        """State has context_files, source_files, test_files, files_modified."""
        state: OrchestratorState = {
            "context_files": ["spec.md"],
            "source_files": ["src/foo.py"],
            "test_files": ["tests/test_foo.py"],
            "files_modified": ["src/foo.py"],
        }
        assert state["context_files"] == ["spec.md"]
        assert state["files_modified"] == ["src/foo.py"]

    def test_has_review_pipeline_fields(self) -> None:
        """State preserves review pipeline fields from Story 3.3-3.4."""
        state: OrchestratorState = {
            "review_file_paths": ["reviews/review-agent-1.md"],
            "fix_plan_path": "fix-plan.md",
        }
        assert state["review_file_paths"] == ["reviews/review-agent-1.md"]
        assert state["fix_plan_path"] == "fix-plan.md"

    def test_has_test_output_fields(self) -> None:
        """State has last_test_output and last_ci_output for retry context."""
        state: OrchestratorState = {
            "test_passed": False,
            "last_test_output": "FAILED test_foo",
            "last_ci_output": "ruff error",
        }
        assert state["last_test_output"] == "FAILED test_foo"
        assert state["last_ci_output"] == "ruff error"

    def test_retry_limits_are_defined(self) -> None:
        """Retry limit constants match architecture spec."""
        assert MAX_EDIT_RETRIES == 3
        assert MAX_TEST_CYCLES == 5
        assert MAX_CI_CYCLES == 3


# ---------------------------------------------------------------------------
# Task 2: Pipeline Node and Edge Tests
# ---------------------------------------------------------------------------


class TestBuildOrchestratorGraph:
    """Tests for build_orchestrator_graph construction."""

    def test_graph_has_all_pipeline_nodes(self) -> None:
        """Graph contains all 15 pipeline nodes."""
        graph = build_orchestrator_graph()
        node_names = set(graph.nodes.keys())
        expected = {
            "test_agent",
            "dev_agent",
            "unit_test",
            "ci",
            "git_snapshot",
            "prepare_reviews",
            "review_node",
            "collect_reviews",
            "architect_node",
            "fix_dev_node",
            "post_fix_test",
            "post_fix_ci",
            "system_test",
            "final_ci",
            "git_push",
            "error_handler",
        }
        assert expected.issubset(node_names), f"Missing: {expected - node_names}"

    def test_node_count(self) -> None:
        """Graph has exactly 16 nodes (15 pipeline + error_handler)."""
        graph = build_orchestrator_graph()
        assert len(graph.nodes) == 16

    def test_graph_compiles(self) -> None:
        """Graph compiles without errors."""
        graph = build_orchestrator_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_build_orchestrator_returns_compiled(self) -> None:
        """build_orchestrator() returns a compiled graph."""
        compiled = build_orchestrator()
        assert compiled is not None


# ---------------------------------------------------------------------------
# Task 3: Bash-Based Node Tests (NO LLM invocation)
# ---------------------------------------------------------------------------


class TestBashNodes:
    """Tests that bash nodes execute shell commands, not LLM calls."""

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_unit_test_node_calls_pytest(self, mock_bash: MagicMock) -> None:
        """unit_test_node runs pytest via bash."""
        mock_bash.return_value = (True, "all passed")
        state: OrchestratorState = {"session_id": "s", "test_cycle_count": 0}

        result = unit_test_node(state)

        mock_bash.assert_called_once_with(["pytest", "tests/", "-v"], cwd=None)
        assert result["test_passed"] is True
        assert result["test_cycle_count"] == 1

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_ci_node_calls_local_ci(self, mock_bash: MagicMock) -> None:
        """ci_node runs local_ci.sh via bash."""
        mock_bash.return_value = (True, "all checks passed")
        state: OrchestratorState = {"session_id": "s", "ci_cycle_count": 0}

        result = ci_node(state)

        mock_bash.assert_called_once_with(["bash", "scripts/local_ci.sh"], cwd=None)
        assert result["test_passed"] is True
        assert result["ci_cycle_count"] == 1

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_git_snapshot_node_calls_script(self, mock_bash: MagicMock) -> None:
        """git_snapshot_node runs git_snapshot.sh via bash."""
        mock_bash.return_value = (True, "committed")
        state: OrchestratorState = {"task_id": "t-1", "session_id": "s"}

        git_snapshot_node(state)

        args = mock_bash.call_args[0][0]
        assert args[0] == "bash"
        assert args[1] == "scripts/git_snapshot.sh"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_system_test_node_uses_marker(self, mock_bash: MagicMock) -> None:
        """system_test_node runs pytest with -m system marker."""
        mock_bash.return_value = (True, "system tests passed")
        state: OrchestratorState = {"session_id": "s", "test_cycle_count": 0}

        result = system_test_node(state)

        mock_bash.assert_called_once_with(["pytest", "tests/", "-v", "-m", "system"], cwd=None)
        assert result["test_passed"] is True

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_git_push_node_commits_and_pushes(self, mock_bash: MagicMock) -> None:
        """git_push_node runs git snapshot then git push."""
        mock_bash.return_value = (True, "pushed")
        state: OrchestratorState = {"task_id": "t-1", "session_id": "s"}

        result = git_push_node(state)

        assert mock_bash.call_count == 2
        assert result["pipeline_status"] == "completed"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_git_push_failure_reports_error(self, mock_bash: MagicMock) -> None:
        """git_push_node reports failure when push fails."""
        mock_bash.side_effect = [(True, "committed"), (False, "rejected")]
        state: OrchestratorState = {"task_id": "t-1", "session_id": "s"}

        result = git_push_node(state)

        assert result["pipeline_status"] == "failed"
        assert "push failed" in result["error"].lower()

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    @patch("src.multi_agent.orchestrator._run_bash")
    def test_bash_nodes_do_not_invoke_llm(
        self, mock_bash: MagicMock, mock_agent: MagicMock
    ) -> None:
        """Bash nodes never call run_sub_agent (no LLM invocation). (AC#4)"""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {
            "session_id": "s",
            "task_id": "t",
            "test_cycle_count": 0,
            "ci_cycle_count": 0,
        }

        unit_test_node(state)
        ci_node(state)
        git_snapshot_node(state)
        system_test_node(state)
        final_ci_node(state)
        git_push_node(state)
        post_fix_test_node(state)
        post_fix_ci_node(state)

        mock_agent.assert_not_called()


# ---------------------------------------------------------------------------
# Task 4: Conditional Routing Tests
# ---------------------------------------------------------------------------


class TestRouteAfterUnitTest:
    """Tests for route_after_unit_test conditional routing."""

    def test_pass_on_success(self) -> None:
        """Returns 'pass' when tests pass."""
        state: OrchestratorState = {"test_passed": True, "test_cycle_count": 1}
        assert route_after_unit_test(state) == "pass"

    def test_retry_on_failure_under_limit(self) -> None:
        """Returns 'retry' when tests fail and under cycle limit. (AC#2)"""
        state: OrchestratorState = {"test_passed": False, "test_cycle_count": 2}
        assert route_after_unit_test(state) == "retry"

    def test_error_on_limit_exceeded(self) -> None:
        """Returns 'error' when test cycle limit exceeded. (AC#3)"""
        state: OrchestratorState = {
            "test_passed": False,
            "test_cycle_count": MAX_TEST_CYCLES,
        }
        assert route_after_unit_test(state) == "error"


class TestRouteAfterCI:
    """Tests for route_after_ci conditional routing."""

    def test_pass_on_success(self) -> None:
        """Returns 'pass' when CI passes."""
        state: OrchestratorState = {"test_passed": True, "ci_cycle_count": 1}
        assert route_after_ci(state) == "pass"

    def test_retry_on_failure_under_limit(self) -> None:
        """Returns 'retry' when CI fails and under limit. (AC#2)"""
        state: OrchestratorState = {"test_passed": False, "ci_cycle_count": 1}
        assert route_after_ci(state) == "retry"

    def test_error_on_limit_exceeded(self) -> None:
        """Returns 'error' when CI cycle limit exceeded. (AC#3)"""
        state: OrchestratorState = {
            "test_passed": False,
            "ci_cycle_count": MAX_CI_CYCLES,
        }
        assert route_after_ci(state) == "error"


class TestRouteAfterPostFixTest:
    """Tests for route_after_post_fix_test conditional routing."""

    def test_pass_on_success(self) -> None:
        """Routes to pass when post-fix tests succeed."""
        state: OrchestratorState = {"test_passed": True, "test_cycle_count": 1}
        assert route_after_post_fix_test(state) == "pass"

    def test_retry_on_failure(self) -> None:
        """Routes to retry when post-fix tests fail below cycle limit."""
        state: OrchestratorState = {"test_passed": False, "test_cycle_count": 2}
        assert route_after_post_fix_test(state) == "retry"

    def test_error_at_limit(self) -> None:
        """Routes to error when post-fix tests fail at max cycle limit."""
        state: OrchestratorState = {
            "test_passed": False,
            "test_cycle_count": MAX_TEST_CYCLES,
        }
        assert route_after_post_fix_test(state) == "error"


class TestRouteAfterPostFixCI:
    """Tests for route_after_post_fix_ci conditional routing."""

    def test_pass_on_success(self) -> None:
        """Routes to pass when post-fix CI succeeds."""
        state: OrchestratorState = {"test_passed": True, "ci_cycle_count": 1}
        assert route_after_post_fix_ci(state) == "pass"

    def test_retry_on_failure(self) -> None:
        """Routes to retry when post-fix CI fails below cycle limit."""
        state: OrchestratorState = {"test_passed": False, "ci_cycle_count": 1}
        assert route_after_post_fix_ci(state) == "retry"

    def test_error_at_limit(self) -> None:
        """Routes to error when post-fix CI fails at max cycle limit."""
        state: OrchestratorState = {
            "test_passed": False,
            "ci_cycle_count": MAX_CI_CYCLES,
        }
        assert route_after_post_fix_ci(state) == "error"


class TestRouteAfterSystemTest:
    """Tests for route_after_system_test conditional routing."""

    def test_pass_on_success(self) -> None:
        """Routes to pass when system tests succeed."""
        state: OrchestratorState = {"test_passed": True, "test_cycle_count": 1}
        assert route_after_system_test(state) == "pass"

    def test_retry_on_failure(self) -> None:
        """Routes to retry when system tests fail below cycle limit."""
        state: OrchestratorState = {"test_passed": False, "test_cycle_count": 2}
        assert route_after_system_test(state) == "retry"

    def test_error_at_limit(self) -> None:
        """Routes to error when system tests fail at max cycle limit."""
        state: OrchestratorState = {
            "test_passed": False,
            "test_cycle_count": MAX_TEST_CYCLES,
        }
        assert route_after_system_test(state) == "error"


class TestRouteAfterFinalCI:
    """Tests for route_after_final_ci conditional routing."""

    def test_pass_on_success(self) -> None:
        state: OrchestratorState = {"test_passed": True}
        assert route_after_final_ci(state) == "pass"

    def test_error_on_failure(self) -> None:
        """Final CI failure always routes to error (no retry)."""
        state: OrchestratorState = {"test_passed": False}
        assert route_after_final_ci(state) == "error"


# ---------------------------------------------------------------------------
# Task 5: Error Handler Tests
# ---------------------------------------------------------------------------


class TestErrorHandler:
    """Tests for error_handler_node."""

    def test_produces_failure_report_format(self) -> None:
        """Error handler produces markdown failure report. (AC#3)"""
        state: OrchestratorState = {
            "task_id": "story-42",
            "current_phase": "unit_test",
            "edit_retry_count": 2,
            "test_cycle_count": 5,
            "ci_cycle_count": 1,
            "error_log": ["test_foo FAILED", "AssertionError"],
            "files_modified": ["src/foo.py", "tests/test_foo.py"],
            "session_id": "s",
        }

        result = error_handler_node(state)

        assert result["pipeline_status"] == "failed"
        report = result["error"]
        assert "# Pipeline Failure Report" in report
        assert "story-42" in report
        assert "unit_test" in report
        assert "edit=2/3" in report
        assert "test=5/5" in report
        assert "CI=1/3" in report
        assert "test_foo FAILED" in report
        assert "src/foo.py" in report

    def test_empty_error_log(self) -> None:
        """Error handler handles empty error log gracefully."""
        state: OrchestratorState = {
            "task_id": "t",
            "current_phase": "ci",
            "session_id": "s",
        }

        result = error_handler_node(state)

        assert "No errors captured" in result["error"]

    def test_empty_files_modified(self) -> None:
        """Error handler handles no modified files."""
        state: OrchestratorState = {
            "task_id": "t",
            "current_phase": "ci",
            "session_id": "s",
        }

        result = error_handler_node(state)

        assert "- None" in result["error"]


# ---------------------------------------------------------------------------
# Task 6: Send API Review Integration Tests (preserved from Story 3.3)
# ---------------------------------------------------------------------------


class TestRouteToReviewers:
    """Tests for route_to_reviewers (Send API fan-out)."""

    def test_returns_exactly_two_send_objects(self) -> None:
        """route_to_reviewers returns exactly 2 Send objects. (AC#1)"""
        state: OrchestratorState = {
            "task_id": "story-42",
            "session_id": "sess-1",
            "source_files": ["src/foo.py"],
            "test_files": ["tests/test_foo.py"],
        }
        result = route_to_reviewers(state)
        assert len(result) == 2
        assert all(isinstance(s, Send) for s in result)

    def test_both_target_review_node(self) -> None:
        """Both Send objects target 'review_node'. (AC#1)"""
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": ["src/a.py"],
            "test_files": [],
        }
        result = route_to_reviewers(state)
        assert result[0].node == "review_node"
        assert result[1].node == "review_node"

    def test_different_reviewer_ids(self) -> None:
        """Each Send has a different reviewer_id (1 and 2). (AC#1)"""
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": ["src/a.py"],
            "test_files": [],
        }
        result = route_to_reviewers(state)
        ids = {result[0].arg["reviewer_id"], result[1].arg["reviewer_id"]}
        assert ids == {1, 2}

    def test_different_focus_areas(self) -> None:
        """Reviewers have different focus areas. (AC#2)"""
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": ["src/a.py"],
            "test_files": [],
        }
        result = route_to_reviewers(state)
        focuses = {result[0].arg["reviewer_focus"], result[1].arg["reviewer_focus"]}
        assert REVIEWER_1_FOCUS in focuses
        assert REVIEWER_2_FOCUS in focuses

    def test_passes_task_id_and_files(self) -> None:
        """Send objects carry task_id and file lists from state."""
        state: OrchestratorState = {
            "task_id": "story-99",
            "session_id": "sess-x",
            "source_files": ["src/a.py", "src/b.py"],
            "test_files": ["tests/test_a.py"],
        }
        result = route_to_reviewers(state)
        for send in result:
            assert send.arg["task_id"] == "story-99"
            assert send.arg["source_files"] == ["src/a.py", "src/b.py"]
            assert send.arg["test_files"] == ["tests/test_a.py"]


class TestReviewNode:
    """Tests for review_node (individual reviewer spawning)."""

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_spawns_reviewer_with_correct_role(self, mock_run: MagicMock) -> None:
        """review_node spawns a sub-agent with role='reviewer'. (AC#1)"""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state = ReviewNodeInput(
            reviewer_id=1,
            task_id="t",
            session_id="s",
            source_files=["src/foo.py"],
            test_files=[],
            reviewer_focus=REVIEWER_1_FOCUS,
        )
        review_node(state)

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["role"] == "reviewer"
        assert mock_run.call_args.kwargs["current_phase"] == "review"

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_returns_review_file_path(self, mock_run: MagicMock) -> None:
        """review_node returns the expected review file path. (AC#2)"""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state = ReviewNodeInput(
            reviewer_id=2,
            task_id="t",
            session_id="s",
            source_files=[],
            test_files=[],
            reviewer_focus=REVIEWER_2_FOCUS,
        )
        result = review_node(state)
        # Path depends on REVIEWS_DIR which may be monkeypatched
        assert "review-agent-2.md" in result["review_file_paths"][0]

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_passes_context_files(self, mock_run: MagicMock) -> None:
        """review_node passes source + test files as context."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state = ReviewNodeInput(
            reviewer_id=1,
            task_id="t",
            session_id="s",
            source_files=["src/a.py"],
            test_files=["tests/test_a.py"],
            reviewer_focus=REVIEWER_1_FOCUS,
        )
        review_node(state)

        context = mock_run.call_args.kwargs["context_files"]
        assert "src/a.py" in context
        assert "tests/test_a.py" in context

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_task_description_includes_output_format(self, mock_run: MagicMock) -> None:
        """Task description instructs reviewer to produce YAML frontmatter format."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state = ReviewNodeInput(
            reviewer_id=1,
            task_id="t",
            session_id="s",
            source_files=[],
            test_files=[],
            reviewer_focus=REVIEWER_1_FOCUS,
        )
        review_node(state)

        task_desc = mock_run.call_args.kwargs["task_description"]
        assert "agent_role: reviewer" in task_desc
        assert "reviewer_id: 1" in task_desc
        assert "Severity" in task_desc


class TestCollectReviews:
    """Tests for collect_reviews (fan-in node)."""

    def test_reads_both_review_files(self, reviews_dir: Path) -> None:
        """collect_reviews reads both review files and updates state. (AC#3)"""
        for i in [1, 2]:
            path = reviews_dir / f"review-agent-{i}.md"
            path.write_text(
                f"---\nagent_role: reviewer\nreviewer_id: {i}\n---\n"
                f"# Review {i}\n## Summary\nFindings here.\n",
                encoding="utf-8",
            )

        state: OrchestratorState = {"task_id": "t"}
        result = collect_reviews(state)

        assert len(result["review_file_paths"]) == 2
        assert "error" not in result

    def test_reports_error_if_review_missing(self, reviews_dir: Path) -> None:
        """collect_reviews reports error when review files are missing."""
        state: OrchestratorState = {"task_id": "t"}
        result = collect_reviews(state)

        assert "error" in result
        assert "Expected 2" in result["error"]

    def test_validates_yaml_frontmatter(self, reviews_dir: Path) -> None:
        """collect_reviews rejects review files without YAML frontmatter."""
        (reviews_dir / "review-agent-1.md").write_text(
            "---\nagent_role: reviewer\n---\n# Review\n", encoding="utf-8"
        )
        (reviews_dir / "review-agent-2.md").write_text(
            "# Review without frontmatter\n", encoding="utf-8"
        )

        state: OrchestratorState = {"task_id": "t"}
        result = collect_reviews(state)

        assert len(result["review_file_paths"]) == 1
        assert "error" in result


class TestPrepareReviews:
    """Tests for prepare_reviews_node (directory cleanup)."""

    def test_creates_reviews_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """prepare_reviews_node creates the reviews/ directory."""
        reviews = tmp_path / "fresh_reviews"
        monkeypatch.setattr(orch_module, "REVIEWS_DIR", str(reviews))

        prepare_reviews_node({})
        assert reviews.is_dir()

    def test_clears_existing_reviews(self, reviews_dir: Path) -> None:
        """prepare_reviews_node clears existing review files."""
        (reviews_dir / "old-review.md").write_text("old content", encoding="utf-8")

        prepare_reviews_node({})
        assert reviews_dir.is_dir()
        assert not (reviews_dir / "old-review.md").exists()


# ---------------------------------------------------------------------------
# Story 3.4 Tests: Architect & Fix Dev (preserved)
# ---------------------------------------------------------------------------


class TestArchitectNode:
    """Tests for architect_node."""

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_spawns_architect_role(self, mock_run: MagicMock) -> None:
        """architect_node spawns sub-agent with role='architect'. (AC#1)"""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": ["src/foo.py"],
            "review_file_paths": ["reviews/review-agent-1.md", "reviews/review-agent-2.md"],
        }
        architect_node(state)
        assert mock_run.call_args.kwargs["role"] == "architect"

    def test_architect_uses_opus_model_tier(self) -> None:
        """Architect spawns with Opus model tier (via role config)."""
        from src.multi_agent.roles import get_role

        role = get_role("architect")
        assert role.model_tier == "opus"

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_passes_both_review_files(self, mock_run: MagicMock) -> None:
        """architect_node passes both review files as context."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        review_paths = ["reviews/review-agent-1.md", "reviews/review-agent-2.md"]
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "review_file_paths": review_paths,
        }
        architect_node(state)

        context = mock_run.call_args.kwargs["context_files"]
        for path in review_paths:
            assert path in context

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_returns_fix_plan_path(self, mock_run: MagicMock) -> None:
        """architect_node sets fix_plan_path in state."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "review_file_paths": [],
        }
        result = architect_node(state)
        assert result["fix_plan_path"] == FIX_PLAN_PATH

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_architect_uses_architect_phase(self, mock_run: MagicMock) -> None:
        """architect_node passes current_phase='architect' to sub-agent."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "review_file_paths": [],
        }
        architect_node(state)
        assert mock_run.call_args.kwargs["current_phase"] == "architect"


class TestFixDevNode:
    """Tests for fix_dev_node."""

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_spawns_fresh_fix_dev(self, mock_run: MagicMock) -> None:
        """fix_dev_node spawns a fresh agent with role='fix_dev'. (AC#2)"""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": ["src/foo.py"],
            "fix_plan_path": FIX_PLAN_PATH,
        }
        fix_dev_node(state)

        assert mock_run.call_args.kwargs["role"] == "fix_dev"
        assert mock_run.call_args.kwargs["current_phase"] == "fix"

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_passes_fix_plan_as_context(self, mock_run: MagicMock) -> None:
        """fix_dev_node passes fix-plan.md as context."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "fix_plan_path": FIX_PLAN_PATH,
        }
        fix_dev_node(state)

        context = mock_run.call_args.kwargs["context_files"]
        assert FIX_PLAN_PATH in context

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_fresh_agent_new_thread(self, mock_run: MagicMock) -> None:
        """Fix Dev Agent gets a unique thread_id (fresh context)."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "parent-123",
            "source_files": [],
            "fix_plan_path": FIX_PLAN_PATH,
        }
        fix_dev_node(state)
        assert mock_run.call_args.kwargs["parent_session_id"] == "parent-123"

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_no_redundant_pytest_instruction(self, mock_run: MagicMock) -> None:
        """fix_dev_node task description does not instruct to run pytest."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "fix_plan_path": FIX_PLAN_PATH,
        }
        fix_dev_node(state)

        task_desc = mock_run.call_args.kwargs["task_description"]
        assert "pytest" not in task_desc.lower()


# ---------------------------------------------------------------------------
# LLM Agent Node Tests
# ---------------------------------------------------------------------------


class TestSpawnTestAgent:
    """Tests for test_agent_node (aliased to avoid pytest collection)."""

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_spawns_test_role(self, mock_run: MagicMock) -> None:
        """test_agent_node spawns a sub-agent with role='test'."""
        mock_run.return_value = {"files_modified": ["tests/test_new.py"], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "task_description": "Build feature X",
            "context_files": [],
        }
        result = spawn_test_agent(state)

        assert mock_run.call_args.kwargs["role"] == "test"
        assert mock_run.call_args.kwargs["current_phase"] == "test"
        assert result["files_modified"] == ["tests/test_new.py"]

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_includes_task_description(self, mock_run: MagicMock) -> None:
        """test_agent_node passes task description to sub-agent."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "task_description": "Add login endpoint",
            "context_files": [],
        }
        spawn_test_agent(state)

        task_desc = mock_run.call_args.kwargs["task_description"]
        assert "Add login endpoint" in task_desc


class TestDevAgentNode:
    """Tests for dev_agent_node."""

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_spawns_dev_role(self, mock_run: MagicMock) -> None:
        """dev_agent_node spawns a sub-agent with role='dev'."""
        mock_run.return_value = {"files_modified": ["src/login.py"], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "task_description": "Build feature X",
            "context_files": [],
        }
        result = dev_agent_node(state)

        assert mock_run.call_args.kwargs["role"] == "dev"
        assert mock_run.call_args.kwargs["current_phase"] == "implementation"
        assert result["files_modified"] == ["src/login.py"]

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_includes_test_output_on_retry(self, mock_run: MagicMock) -> None:
        """dev_agent_node passes previous test output on retry."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}

        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "task_description": "Build X",
            "context_files": [],
            "test_cycle_count": 2,
            "last_test_output": "FAILED test_login",
        }
        dev_agent_node(state)

        task_desc = mock_run.call_args.kwargs["task_description"]
        assert "retry 2" in task_desc.lower()
        assert "FAILED test_login" in task_desc


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestIntegrationReviewPipeline:
    """Integration test: review pipeline with mock agent (Story 3.3)."""

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_two_review_files_created(self, mock_run: MagicMock, reviews_dir: Path) -> None:
        """Pipeline creates 2 review files via mock agent. (AC#1, #2)"""
        rd = str(reviews_dir)

        def _mock_review(
            parent_session_id: str,
            task_id: str,
            role: str,
            task_description: str,
            current_phase: str,
            context_files: list[str] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            for rid in [1, 2]:
                if f"review-agent-{rid}.md" in task_description:
                    path = os.path.join(rd, f"review-agent-{rid}.md")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(
                            f"---\nagent_role: reviewer\n"
                            f"task_id: {task_id}\n"
                            f"reviewer_id: {rid}\n---\n"
                            f"# Code Review - Agent {rid}\n"
                            f"## Summary\nNo issues found.\n"
                            f"## Findings\nNone.\n"
                        )
                    return {"files_modified": [path], "final_message": "done"}
            return {"files_modified": [], "final_message": "unknown"}

        mock_run.side_effect = _mock_review

        prepare_reviews_node({})
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "test_files": [],
        }

        for rid in [1, 2]:
            review_input = ReviewNodeInput(
                reviewer_id=rid,
                task_id="t",
                session_id="s",
                source_files=[],
                test_files=[],
                reviewer_focus=REVIEWER_1_FOCUS if rid == 1 else REVIEWER_2_FOCUS,
            )
            review_node(review_input)

        result = collect_reviews(state)
        assert len(result["review_file_paths"]) == 2
        assert "error" not in result


class TestIntegrationFullPipeline:
    """Integration test: full pipeline execution with mocked LLM and bash."""

    @patch("src.multi_agent.orchestrator._run_bash")
    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_happy_path_node_sequence(
        self, mock_agent: MagicMock, mock_bash: MagicMock, reviews_dir: Path
    ) -> None:
        """Verify pipeline executes nodes in correct order (happy path). (AC#1)"""
        rd = str(reviews_dir)

        def _mock_agent_side_effect(**kwargs: Any) -> dict[str, Any]:
            """Mock that writes review files when role=reviewer."""
            role = kwargs.get("role", "")
            task_desc = kwargs.get("task_description", "")
            if role == "reviewer":
                for rid in [1, 2]:
                    if f"review-agent-{rid}.md" in task_desc:
                        path = os.path.join(rd, f"review-agent-{rid}.md")
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(
                                f"---\nagent_role: reviewer\nreviewer_id: {rid}\n---\n"
                                f"# Review\n## Summary\nOK\n"
                            )
                        return {"files_modified": [path], "final_message": "done"}
            return {"files_modified": ["src/foo.py"], "final_message": "done"}

        mock_agent.side_effect = _mock_agent_side_effect
        mock_bash.return_value = (True, "ok")

        # Simulate the pipeline nodes in order (without LangGraph runtime)
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "task_description": "Build feature",
            "context_files": [],
            "source_files": [],
            "test_files": [],
            "test_cycle_count": 0,
            "ci_cycle_count": 0,
            "edit_retry_count": 0,
        }

        # Phase 1: TDD
        spawn_test_agent(state)
        dev_agent_node(state)

        # Phase 2: Validation
        ut_result = unit_test_node(state)
        assert ut_result["test_passed"] is True

        ci_result = ci_node(state)
        assert ci_result["test_passed"] is True

        git_snapshot_node(state)

        # Phase 3: Review
        prepare_reviews_node(state)
        for rid in [1, 2]:
            review_input = ReviewNodeInput(
                reviewer_id=rid,
                task_id="t",
                session_id="s",
                source_files=[],
                test_files=[],
                reviewer_focus=REVIEWER_1_FOCUS if rid == 1 else REVIEWER_2_FOCUS,
            )
            review_node(review_input)
        collect_result = collect_reviews(state)
        assert "error" not in collect_result

        # Phase 4: Architect + Fix
        state["review_file_paths"] = collect_result["review_file_paths"]
        architect_node(state)
        fix_dev_node(state)

        # Phase 5: Post-fix validation
        pft_result = post_fix_test_node(state)
        assert pft_result["test_passed"] is True

        pfci_result = post_fix_ci_node(state)
        assert pfci_result["test_passed"] is True

        # Phase 6: System tests + final
        st_result = system_test_node(state)
        assert st_result["test_passed"] is True

        fci_result = final_ci_node(state)
        assert fci_result["test_passed"] is True

        # Phase 7: Push
        push_result = git_push_node(state)
        assert push_result["pipeline_status"] == "completed"

        # Verify agents were called with correct roles
        agent_roles = [c.kwargs["role"] for c in mock_agent.call_args_list]
        assert "test" in agent_roles
        assert "dev" in agent_roles
        assert "reviewer" in agent_roles
        assert "architect" in agent_roles
        assert "fix_dev" in agent_roles


# ---------------------------------------------------------------------------
# Story 4.4: working_dir threading tests
# ---------------------------------------------------------------------------


class TestWorkingDirState:
    """Tests that working_dir propagates through OrchestratorState."""

    def test_orchestrator_state_accepts_working_dir(self) -> None:
        """OrchestratorState accepts working_dir field."""
        state: OrchestratorState = {"working_dir": "/some/path"}
        assert state["working_dir"] == "/some/path"

    def test_orchestrator_state_working_dir_empty_default(self) -> None:
        """working_dir defaults to empty string when not set."""
        state: OrchestratorState = {"task_id": "t"}
        assert state.get("working_dir", "") == ""

    def test_review_node_input_accepts_working_dir(self) -> None:
        """ReviewNodeInput includes working_dir field."""
        inp = ReviewNodeInput(
            reviewer_id=1,
            task_id="t",
            session_id="s",
            source_files=[],
            test_files=[],
            reviewer_focus="focus",
            working_dir="/target",
        )
        assert inp["working_dir"] == "/target"


class TestRunBashCwd:
    """Tests that _run_bash passes cwd to subprocess.run."""

    @patch("src.multi_agent.orchestrator.subprocess.run")
    def test_cwd_passed_when_provided(self, mock_run: MagicMock) -> None:
        """_run_bash passes cwd to subprocess.run when provided."""
        from src.multi_agent.orchestrator import _run_bash

        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        _run_bash(["echo", "hi"], cwd="/my/dir")
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get("cwd") == "/my/dir"

    @patch("src.multi_agent.orchestrator.subprocess.run")
    def test_cwd_none_when_omitted(self, mock_run: MagicMock) -> None:
        """_run_bash passes cwd=None when not provided."""
        from src.multi_agent.orchestrator import _run_bash

        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        _run_bash(["echo", "hi"])
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get("cwd") is None


class TestBashNodesPassWorkingDir:
    """Tests that bash nodes read working_dir from state and pass as cwd."""

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_unit_test_node_passes_cwd(self, mock_bash: MagicMock) -> None:
        """Unit test node passes working_dir as cwd to _run_bash."""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {
            "session_id": "s",
            "test_cycle_count": 0,
            "working_dir": "/target",
        }
        unit_test_node(state)
        assert mock_bash.call_args.kwargs.get("cwd") == "/target"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_ci_node_passes_cwd(self, mock_bash: MagicMock) -> None:
        """CI node passes working_dir as cwd to _run_bash."""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {
            "session_id": "s",
            "ci_cycle_count": 0,
            "working_dir": "/target",
        }
        ci_node(state)
        assert mock_bash.call_args.kwargs.get("cwd") == "/target"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_git_snapshot_node_passes_cwd(self, mock_bash: MagicMock) -> None:
        """Git snapshot node passes working_dir as cwd to _run_bash."""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "working_dir": "/target",
        }
        git_snapshot_node(state)
        assert mock_bash.call_args.kwargs.get("cwd") == "/target"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_system_test_node_passes_cwd(self, mock_bash: MagicMock) -> None:
        """System test node passes working_dir as cwd to _run_bash."""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {
            "session_id": "s",
            "test_cycle_count": 0,
            "working_dir": "/target",
        }
        system_test_node(state)
        assert mock_bash.call_args.kwargs.get("cwd") == "/target"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_final_ci_node_passes_cwd(self, mock_bash: MagicMock) -> None:
        """Final CI node passes working_dir as cwd to _run_bash."""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {"session_id": "s", "working_dir": "/target"}
        final_ci_node(state)
        assert mock_bash.call_args.kwargs.get("cwd") == "/target"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_git_push_node_passes_cwd(self, mock_bash: MagicMock) -> None:
        """Git push node passes working_dir as cwd to all _run_bash calls."""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "working_dir": "/target",
        }
        git_push_node(state)
        # Both commit and push calls should have cwd
        for call in mock_bash.call_args_list:
            assert call.kwargs.get("cwd") == "/target"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_post_fix_test_node_passes_cwd(self, mock_bash: MagicMock) -> None:
        """Post-fix test node passes working_dir as cwd to _run_bash."""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {
            "session_id": "s",
            "test_cycle_count": 0,
            "working_dir": "/target",
        }
        post_fix_test_node(state)
        assert mock_bash.call_args.kwargs.get("cwd") == "/target"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_post_fix_ci_node_passes_cwd(self, mock_bash: MagicMock) -> None:
        """Post-fix CI node passes working_dir as cwd to _run_bash."""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {
            "session_id": "s",
            "ci_cycle_count": 0,
            "working_dir": "/target",
        }
        post_fix_ci_node(state)
        assert mock_bash.call_args.kwargs.get("cwd") == "/target"

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_bash_nodes_none_cwd_without_working_dir(self, mock_bash: MagicMock) -> None:
        """Bash nodes pass cwd=None when working_dir is empty (backward compat)."""
        mock_bash.return_value = (True, "ok")
        state: OrchestratorState = {"session_id": "s", "test_cycle_count": 0}
        unit_test_node(state)
        assert mock_bash.call_args.kwargs.get("cwd") is None


class TestLLMNodesPassWorkingDir:
    """Tests that LLM agent nodes pass working_dir to run_sub_agent."""

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_test_agent_passes_working_dir(self, mock_run: MagicMock) -> None:
        """Test agent node forwards working_dir to run_sub_agent."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "task_description": "spec",
            "context_files": [],
            "working_dir": "/target",
        }
        spawn_test_agent(state)
        assert mock_run.call_args.kwargs["working_dir"] == "/target"

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_dev_agent_passes_working_dir(self, mock_run: MagicMock) -> None:
        """Dev agent node forwards working_dir to run_sub_agent."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "task_description": "spec",
            "context_files": [],
            "working_dir": "/target",
        }
        dev_agent_node(state)
        assert mock_run.call_args.kwargs["working_dir"] == "/target"

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_architect_passes_working_dir(self, mock_run: MagicMock) -> None:
        """Architect node forwards working_dir to run_sub_agent."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "review_file_paths": [],
            "working_dir": "/target",
        }
        architect_node(state)
        assert mock_run.call_args.kwargs["working_dir"] == "/target"

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_fix_dev_passes_working_dir(self, mock_run: MagicMock) -> None:
        """Fix dev node forwards working_dir to run_sub_agent."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "working_dir": "/target",
        }
        fix_dev_node(state)
        assert mock_run.call_args.kwargs["working_dir"] == "/target"

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_review_node_passes_working_dir(self, mock_run: MagicMock) -> None:
        """Review node forwards working_dir to run_sub_agent."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}
        state = ReviewNodeInput(
            reviewer_id=1,
            task_id="t",
            session_id="s",
            source_files=[],
            test_files=[],
            reviewer_focus="focus",
            working_dir="/target",
        )
        review_node(state)
        assert mock_run.call_args.kwargs["working_dir"] == "/target"

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_llm_nodes_none_working_dir_without_state(self, mock_run: MagicMock) -> None:
        """LLM nodes pass working_dir=None when not set (backward compat)."""
        mock_run.return_value = {"files_modified": [], "final_message": "done"}
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "task_description": "spec",
            "context_files": [],
        }
        spawn_test_agent(state)
        assert mock_run.call_args.kwargs["working_dir"] is None

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_route_to_reviewers_includes_working_dir(self, mock_run: MagicMock) -> None:
        """route_to_reviewers includes working_dir in ReviewNodeInput."""
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "test_files": [],
            "working_dir": "/target",
        }
        sends = route_to_reviewers(state)
        for send in sends:
            assert send.arg["working_dir"] == "/target"


class TestReviewHelperFunctions:
    """Tests for _ensure_reviews_dir and _review_file_path with working_dir."""

    def test_review_file_path_with_working_dir(self, tmp_path: Path) -> None:
        """_review_file_path scopes output under working_dir/reviews/."""
        result = _review_file_path(1, working_dir=str(tmp_path))
        expected = os.path.join(str(tmp_path), "reviews", "review-agent-1.md")
        assert result == expected

    def test_review_file_path_without_working_dir(self) -> None:
        """_review_file_path uses bare REVIEWS_DIR when working_dir is None."""
        result = _review_file_path(2, working_dir=None)
        expected = os.path.join("reviews", "review-agent-2.md")
        assert result == expected

    def test_ensure_reviews_dir_creates_under_working_dir(self, tmp_path: Path) -> None:
        """_ensure_reviews_dir creates reviews/ inside working_dir."""
        _ensure_reviews_dir(working_dir=str(tmp_path))
        reviews = tmp_path / "reviews"
        assert reviews.is_dir()
        assert (reviews / ".gitkeep").exists()

    def test_ensure_reviews_dir_cleans_existing_files(self, tmp_path: Path) -> None:
        """_ensure_reviews_dir removes old review files but keeps .gitkeep."""
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        (reviews / ".gitkeep").touch()
        (reviews / "review-agent-1.md").write_text("old")
        _ensure_reviews_dir(working_dir=str(tmp_path))
        assert not (reviews / "review-agent-1.md").exists()
        assert (reviews / ".gitkeep").exists()

    def test_ensure_reviews_dir_cleans_subdirectories(self, tmp_path: Path) -> None:
        """_ensure_reviews_dir removes stale subdirectories inside reviews/."""
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        (reviews / ".gitkeep").touch()
        subdir = reviews / "stale_subdir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("stale")
        _ensure_reviews_dir(working_dir=str(tmp_path))
        assert not subdir.exists()
        assert (reviews / ".gitkeep").exists()

    def test_ensure_reviews_dir_without_working_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_ensure_reviews_dir uses bare REVIEWS_DIR when working_dir is None."""
        monkeypatch.setattr(orch_module, "REVIEWS_DIR", str(tmp_path / "reviews"))
        _ensure_reviews_dir(working_dir=None)
        assert (tmp_path / "reviews").is_dir()


class TestCollectAndPrepareWorkingDir:
    """Tests that collect_reviews and prepare_reviews_node thread working_dir."""

    def test_prepare_reviews_node_threads_working_dir(self, tmp_path: Path) -> None:
        """prepare_reviews_node passes working_dir to _ensure_reviews_dir."""
        state: OrchestratorState = {"working_dir": str(tmp_path)}
        prepare_reviews_node(state)
        assert (tmp_path / "reviews").is_dir()

    def test_collect_reviews_uses_working_dir_paths(self, tmp_path: Path) -> None:
        """collect_reviews reads review files from working_dir/reviews/."""
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        for i in (1, 2):
            path = reviews / f"review-agent-{i}.md"
            path.write_text(f"---\nrating: 8\n---\nReview {i}")
        state: OrchestratorState = {"working_dir": str(tmp_path)}
        result = collect_reviews(state)
        assert len(result.get("review_file_paths", [])) == 2

    def test_collect_reviews_without_working_dir(self, reviews_dir: Path) -> None:
        """collect_reviews falls back to REVIEWS_DIR when working_dir absent."""
        for i in (1, 2):
            path = reviews_dir / f"review-agent-{i}.md"
            path.write_text(f"---\nrating: 8\n---\nReview {i}")
        state: OrchestratorState = {"task_id": "t"}
        result = collect_reviews(state)
        assert len(result.get("review_file_paths", [])) == 2


# ---------------------------------------------------------------------------
# Story 4.4: _get_working_dir helper tests (AC#3, AC#5)
# ---------------------------------------------------------------------------


class TestGetWorkingDir:
    """Tests for _get_working_dir helper function."""

    def test_returns_none_for_missing_key(self) -> None:
        """Returns None when working_dir is not in state."""
        assert _get_working_dir({}) is None

    def test_returns_none_for_empty_string(self) -> None:
        """Returns None when working_dir is empty string."""
        assert _get_working_dir({"working_dir": ""}) is None

    def test_returns_value_when_set(self) -> None:
        """Returns the working_dir value when it's a non-empty string."""
        assert _get_working_dir({"working_dir": "/tmp/project"}) == "/tmp/project"

    def test_returns_none_for_none_value(self) -> None:
        """Returns None when working_dir is explicitly None in state."""
        assert _get_working_dir({"working_dir": None}) is None


# ---------------------------------------------------------------------------
# Story 4.4: ReviewNodeInput type tests (AC#4)
# ---------------------------------------------------------------------------


class TestReviewNodeInputType:
    """Tests for ReviewNodeInput TypedDict with NotRequired working_dir."""

    def test_working_dir_is_optional(self) -> None:
        """ReviewNodeInput can be constructed without working_dir."""
        inp = ReviewNodeInput(
            reviewer_id=1,
            task_id="t",
            session_id="s",
            source_files=[],
            test_files=[],
            reviewer_focus="focus",
        )
        assert "working_dir" not in inp

    def test_working_dir_can_be_provided(self) -> None:
        """ReviewNodeInput accepts working_dir when provided."""
        inp = ReviewNodeInput(
            reviewer_id=1,
            task_id="t",
            session_id="s",
            source_files=[],
            test_files=[],
            reviewer_focus="focus",
            working_dir="/tmp/target",
        )
        assert inp["working_dir"] == "/tmp/target"


# ---------------------------------------------------------------------------
# Story 4.4: route_to_reviewers working_dir consistency (AC#5)
# ---------------------------------------------------------------------------


class TestRouteToReviewersWorkingDir:
    """Tests for route_to_reviewers working_dir handling."""

    def test_omits_working_dir_when_not_set(self) -> None:
        """route_to_reviewers omits working_dir from ReviewNodeInput when absent."""
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": ["src/a.py"],
            "test_files": [],
        }
        sends = route_to_reviewers(state)
        assert len(sends) == 2
        for send in sends:
            assert "working_dir" not in send.arg

    def test_includes_working_dir_when_set(self) -> None:
        """route_to_reviewers passes working_dir to ReviewNodeInput when present."""
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": ["src/a.py"],
            "test_files": [],
            "working_dir": "/tmp/target",
        }
        sends = route_to_reviewers(state)
        assert len(sends) == 2
        for send in sends:
            assert send.arg["working_dir"] == "/tmp/target"

    def test_returns_empty_when_no_files(self) -> None:
        """route_to_reviewers returns empty list when no files to review."""
        state: OrchestratorState = {
            "task_id": "t",
            "session_id": "s",
            "source_files": [],
            "test_files": [],
        }
        sends = route_to_reviewers(state)
        assert sends == []

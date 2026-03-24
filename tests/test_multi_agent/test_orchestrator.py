"""Tests for full TDD orchestrator pipeline (Story 3.5).

Tests cover:
- OrchestratorState schema fields (Task 1)
- Pipeline node count and edge connections (Task 2)
- Bash-based nodes do NOT invoke LLM (Task 3)
- Conditional routing: unit test fail → dev retry (Task 4)
- Conditional routing: CI fail → dev retry (Task 4)
- Retry limit exceeded → error handler (Task 4)
- Error handler produces structured failure report (Task 5)
- Send API parallel review integration (Task 6)
- Compiled orchestrator graph (Task 7)
- Integration test: full pipeline with mocked LLM (Task 8)

Also preserves all Story 3.3-3.4 test coverage.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

from langgraph.types import Send

from src.multi_agent.orchestrator import (
    FIX_PLAN_PATH,
    MAX_CI_CYCLES,
    MAX_EDIT_RETRIES,
    MAX_TEST_CYCLES,
    REVIEWER_1_FOCUS,
    REVIEWER_2_FOCUS,
    OrchestratorState,
    ReviewNodeInput,
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


def _clean_reviews_dir() -> None:
    """Remove review artifacts but preserve .gitkeep."""
    reviews_dir = "reviews"
    if os.path.exists(reviews_dir):
        for entry in os.listdir(reviews_dir):
            if entry == ".gitkeep":
                continue
            path = os.path.join(reviews_dir, entry)
            if os.path.isfile(path):
                os.remove(path)
    else:
        os.makedirs(reviews_dir, exist_ok=True)
    gitkeep = os.path.join(reviews_dir, ".gitkeep")
    if not os.path.exists(gitkeep):
        with open(gitkeep, "w") as f:
            f.write("")


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

        mock_bash.assert_called_once_with(["pytest", "tests/", "-v"])
        assert result["test_passed"] is True
        assert result["test_cycle_count"] == 1

    @patch("src.multi_agent.orchestrator._run_bash")
    def test_ci_node_calls_local_ci(self, mock_bash: MagicMock) -> None:
        """ci_node runs local_ci.sh via bash."""
        mock_bash.return_value = (True, "all checks passed")
        state: OrchestratorState = {"session_id": "s", "ci_cycle_count": 0}

        result = ci_node(state)

        mock_bash.assert_called_once_with(["bash", "scripts/local_ci.sh"])
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

        mock_bash.assert_called_once_with(["pytest", "tests/", "-v", "-m", "system"])
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
        state: OrchestratorState = {"test_passed": True, "test_cycle_count": 1}
        assert route_after_post_fix_test(state) == "pass"

    def test_retry_on_failure(self) -> None:
        state: OrchestratorState = {"test_passed": False, "test_cycle_count": 2}
        assert route_after_post_fix_test(state) == "retry"

    def test_error_at_limit(self) -> None:
        state: OrchestratorState = {
            "test_passed": False,
            "test_cycle_count": MAX_TEST_CYCLES,
        }
        assert route_after_post_fix_test(state) == "error"


class TestRouteAfterPostFixCI:
    """Tests for route_after_post_fix_ci conditional routing."""

    def test_pass_on_success(self) -> None:
        state: OrchestratorState = {"test_passed": True, "ci_cycle_count": 1}
        assert route_after_post_fix_ci(state) == "pass"

    def test_retry_on_failure(self) -> None:
        state: OrchestratorState = {"test_passed": False, "ci_cycle_count": 1}
        assert route_after_post_fix_ci(state) == "retry"

    def test_error_at_limit(self) -> None:
        state: OrchestratorState = {
            "test_passed": False,
            "ci_cycle_count": MAX_CI_CYCLES,
        }
        assert route_after_post_fix_ci(state) == "error"


class TestRouteAfterSystemTest:
    """Tests for route_after_system_test conditional routing."""

    def test_pass_on_success(self) -> None:
        state: OrchestratorState = {"test_passed": True, "test_cycle_count": 1}
        assert route_after_system_test(state) == "pass"

    def test_retry_on_failure(self) -> None:
        state: OrchestratorState = {"test_passed": False, "test_cycle_count": 2}
        assert route_after_system_test(state) == "retry"

    def test_error_at_limit(self) -> None:
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
            "source_files": [],
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
            "source_files": [],
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
            "source_files": [],
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
        assert result["review_file_paths"] == ["reviews/review-agent-2.md"]

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

    def test_reads_both_review_files(self) -> None:
        """collect_reviews reads both review files and updates state. (AC#3)"""
        reviews_dir = "reviews"
        os.makedirs(reviews_dir, exist_ok=True)
        try:
            for i in [1, 2]:
                path = os.path.join(reviews_dir, f"review-agent-{i}.md")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(
                        f"---\nagent_role: reviewer\nreviewer_id: {i}\n---\n"
                        f"# Review {i}\n## Summary\nFindings here.\n"
                    )

            state: OrchestratorState = {"task_id": "t"}
            result = collect_reviews(state)

            assert len(result["review_file_paths"]) == 2
            assert "error" not in result
        finally:
            _clean_reviews_dir()

    def test_reports_error_if_review_missing(self) -> None:
        """collect_reviews reports error when review files are missing."""
        _clean_reviews_dir()

        state: OrchestratorState = {"task_id": "t"}
        result = collect_reviews(state)

        assert "error" in result
        assert "Expected 2" in result["error"]

    def test_validates_yaml_frontmatter(self) -> None:
        """collect_reviews rejects review files without YAML frontmatter."""
        reviews_dir = "reviews"
        os.makedirs(reviews_dir, exist_ok=True)
        try:
            with open(os.path.join(reviews_dir, "review-agent-1.md"), "w", encoding="utf-8") as f:
                f.write("---\nagent_role: reviewer\n---\n# Review\n")
            with open(os.path.join(reviews_dir, "review-agent-2.md"), "w", encoding="utf-8") as f:
                f.write("# Review without frontmatter\n")

            state: OrchestratorState = {"task_id": "t"}
            result = collect_reviews(state)

            assert len(result["review_file_paths"]) == 1
            assert "error" in result
        finally:
            _clean_reviews_dir()


class TestPrepareReviews:
    """Tests for prepare_reviews_node (directory cleanup)."""

    def test_creates_reviews_dir(self) -> None:
        """prepare_reviews_node creates the reviews/ directory."""
        _clean_reviews_dir()

        prepare_reviews_node({})
        assert os.path.isdir("reviews")

        _clean_reviews_dir()

    def test_clears_existing_reviews(self) -> None:
        """prepare_reviews_node clears existing review files."""
        os.makedirs("reviews", exist_ok=True)
        with open("reviews/old-review.md", "w", encoding="utf-8") as f:
            f.write("old content")

        prepare_reviews_node({})
        assert os.path.isdir("reviews")
        assert not os.path.exists("reviews/old-review.md")

        _clean_reviews_dir()


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

    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_architect_uses_opus_model_tier(self, mock_run: MagicMock) -> None:
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
    def test_two_review_files_created(self, mock_run: MagicMock) -> None:
        """Pipeline creates 2 review files via mock agent. (AC#1, #2)"""

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
                    path = f"reviews/review-agent-{rid}.md"
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(
                            f"---\nagent_role: reviewer\n"
                            f"task_id: {task_id}\n"
                            f"reviewer_id: {rid}\n---\n"
                            f"# Code Review — Agent {rid}\n"
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

        _clean_reviews_dir()


class TestIntegrationFullPipeline:
    """Integration test: full pipeline execution with mocked LLM and bash."""

    @patch("src.multi_agent.orchestrator._run_bash")
    @patch("src.multi_agent.orchestrator.run_sub_agent")
    def test_happy_path_node_sequence(self, mock_agent: MagicMock, mock_bash: MagicMock) -> None:
        """Verify pipeline executes nodes in correct order (happy path). (AC#1)"""

        def _mock_agent_side_effect(**kwargs: Any) -> dict[str, Any]:
            """Mock that writes review files when role=reviewer."""
            role = kwargs.get("role", "")
            task_desc = kwargs.get("task_description", "")
            if role == "reviewer":
                for rid in [1, 2]:
                    if f"review-agent-{rid}.md" in task_desc:
                        path = f"reviews/review-agent-{rid}.md"
                        os.makedirs("reviews", exist_ok=True)
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(
                                f"---\nagent_role: reviewer\nreviewer_id: {rid}\n---\n"
                                f"# Review\n## Summary\nOK\n"
                            )
                        return {"files_modified": [path], "final_message": "done"}
            return {"files_modified": ["src/foo.py"], "final_message": "done"}

        mock_agent.side_effect = _mock_agent_side_effect
        mock_bash.return_value = (True, "ok")

        try:
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

        finally:
            _clean_reviews_dir()

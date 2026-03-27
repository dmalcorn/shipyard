"""Tests for src/intake/epic_graph.py — epic-level graph (Level 2)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.intake.epic_graph import (
    EpicState,
    advance_story_node,
    build_epic_graph,
    epic_complete_node,
    epic_error_node,
    process_story_result_node,
    route_after_category_a,
    route_after_epic_architect,
    route_after_epic_ci,
    route_after_story_result,
    route_next_story,
    select_story_node,
)


# ---------------------------------------------------------------------------
# Story loop node tests
# ---------------------------------------------------------------------------


class TestSelectStoryNode:
    """select_story_node builds task description from current story."""

    def test_builds_task_description(self) -> None:
        state: EpicState = {
            "stories": [
                {
                    "story": "Login",
                    "description": "**As a** user, **I want** to log in",
                    "acceptance_criteria": ["Given creds When submit Then auth"],
                },
            ],
            "story_index": 0,
            "epic_name": "Auth",
            "current_story_retry_instruction": "",
        }
        result = select_story_node(state)
        assert result["current_story_status"] == ""
        assert result["current_story_error"] == ""


class TestProcessStoryResultNode:
    """process_story_result_node updates counters correctly."""

    def test_completed_story(self) -> None:
        state: EpicState = {
            "epic_name": "Auth",
            "stories": [{"story": "Login"}],
            "story_index": 0,
            "current_story_status": "completed",
            "stories_completed": 0,
            "stories_failed": 0,
        }
        result = process_story_result_node(state)
        assert result["stories_completed"] == 1
        assert result["stories_failed"] == 0
        assert result["story_results"][0]["status"] == "completed"

    def test_failed_story_aborts(self) -> None:
        state: EpicState = {
            "epic_name": "Auth",
            "stories": [{"story": "Login"}],
            "story_index": 0,
            "current_story_status": "failed",
            "stories_completed": 1,
            "stories_failed": 0,
        }
        result = process_story_result_node(state)
        assert result["stories_completed"] == 1
        assert result["stories_failed"] == 1
        assert result["epic_status"] == "aborted"
        assert "aborting" in result["current_story_error"].lower()


class TestAdvanceStoryNode:
    """advance_story_node increments index."""

    def test_increments(self) -> None:
        result = advance_story_node({"story_index": 2})
        assert result["story_index"] == 3
        assert result["current_story_retry_instruction"] == ""


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------


class TestRouteAfterStoryResult:
    """route_after_story_result routes based on story status."""

    def test_completed(self) -> None:
        assert route_after_story_result({"current_story_status": "completed"}) == "next_story"

    def test_failed_aborts(self) -> None:
        assert route_after_story_result({"current_story_status": "failed"}) == "aborted"


class TestRouteNextStory:
    """route_next_story checks if more stories remain."""

    def test_more_stories(self) -> None:
        state: EpicState = {
            "stories": [{"story": "A"}, {"story": "B"}],
            "story_index": 0,
        }
        assert route_next_story(state) == "more_stories"

    def test_epic_done(self) -> None:
        state: EpicState = {
            "stories": [{"story": "A"}],
            "story_index": 0,
        }
        assert route_next_story(state) == "epic_done"


class TestRouteAfterCategoryA:
    """route_after_category_a checks Category B items."""

    def test_has_category_b(self) -> None:
        assert route_after_category_a({"has_category_b_items": True}) == "has_category_b"

    def test_no_category_b(self) -> None:
        assert route_after_category_a({"has_category_b_items": False}) == "no_category_b"


class TestRouteAfterEpicArchitect:
    """route_after_epic_architect checks if fixes are needed."""

    def test_needs_fix(self) -> None:
        assert route_after_epic_architect({"epic_fixes_needed": True}) == "needs_fix"

    def test_no_fix(self) -> None:
        assert route_after_epic_architect({"epic_fixes_needed": False}) == "no_fix"


class TestRouteAfterEpicCi:
    """route_after_epic_ci routes pass or error."""

    def test_pass(self) -> None:
        assert route_after_epic_ci({"epic_test_passed": True}) == "pass"

    def test_error(self) -> None:
        assert route_after_epic_ci({"epic_test_passed": False}) == "error"


# ---------------------------------------------------------------------------
# Terminal node tests
# ---------------------------------------------------------------------------


class TestEpicCompleteNode:
    """epic_complete_node sets status."""

    def test_sets_completed(self) -> None:
        result = epic_complete_node({})
        assert result["epic_status"] == "completed"


class TestEpicErrorNode:
    """epic_error_node sets status and error."""

    def test_sets_failed(self) -> None:
        state: EpicState = {
            "epic_num": "1",
            "epic_name": "Auth",
            "epic_last_ci_output": "ruff failed",
            "epic_last_test_output": "2 tests failed",
        }
        result = epic_error_node(state)
        assert result["epic_status"] == "failed"
        assert "Epic 1" in result["error"]


# ---------------------------------------------------------------------------
# Graph structure test
# ---------------------------------------------------------------------------


class TestBuildEpicGraph:
    """build_epic_graph() produces a valid graph."""

    def test_graph_compiles(self) -> None:
        """Graph compiles without errors."""
        graph = build_epic_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_has_expected_nodes(self) -> None:
        """Graph contains all expected nodes."""
        graph = build_epic_graph()
        node_names = set(graph.nodes.keys())
        expected = {
            "select_story", "run_story", "process_result", "advance_story",
            "prepare_epic_reviews", "epic_review_node", "collect_epic_reviews",
            "analyze_reviews", "fix_category_a",
            "epic_architect", "epic_fix", "epic_ci",
            "epic_git_commit", "epic_error", "epic_complete",
        }
        assert expected.issubset(node_names), f"Missing: {expected - node_names}"

"""Tests for src/multi_agent/orchestrator.py."""

from __future__ import annotations

from src.multi_agent.orchestrator import error_handler_node


class TestErrorHandlerNode:
    """error_handler_node builds the operator-facing Pipeline Failure Report.

    Regression coverage for Epic 8 story 8-6 (2026-05-15): error_log is
    declared in state but no node currently appends to it — run_ci and
    fix_ci only write last_ci_output. Without a fallback, the halt
    message rendered "No errors captured", leaving the operator (and
    every architect-driven fix cycle that followed) blind to the actual
    test-runner failure.
    """

    def test_falls_back_to_last_ci_output_when_error_log_empty(self) -> None:
        # The realistic Epic 8 8-6 shape: run_ci exhausted MAX_CI_CYCLES
        # with a captured tsc error in last_ci_output but nothing in
        # error_log. The report should include the actual error text.
        state = {
            "task_id": "8-6",
            "current_phase": "run_ci",
            "test_cycle_count": 0,
            "ci_cycle_count": 4,
            "error_log": [],
            "last_ci_output": (
                "ShoppingListItemRow.test.tsx(98,50): "
                "error TS2304: Cannot find name 'vi'.\n"
                "  1 failed\n"
            ),
            "files_modified": [],
            "session_id": "",
        }
        result = error_handler_node(state)
        assert result["pipeline_status"] == "failed"
        assert "TS2304" in result["error"]
        assert "Cannot find name 'vi'" in result["error"]
        assert "No errors captured" not in result["error"]

    def test_uses_error_log_when_present(self) -> None:
        # error_log takes precedence if any node ever populates it —
        # the fallback only fires when error_log is empty.
        state = {
            "task_id": "8-6",
            "current_phase": "run_ci",
            "test_cycle_count": 0,
            "ci_cycle_count": 4,
            "error_log": ["structured entry A", "structured entry B"],
            "last_ci_output": "tail content should be ignored",
            "files_modified": [],
            "session_id": "",
        }
        result = error_handler_node(state)
        assert "structured entry A" in result["error"]
        assert "structured entry B" in result["error"]
        assert "tail content should be ignored" not in result["error"]

    def test_shows_no_errors_captured_when_both_empty(self) -> None:
        # Original behaviour when neither source is available — keeps
        # the existing string so operators recognise the "shipyard
        # genuinely has nothing to show" case vs the fallback case.
        state = {
            "task_id": "8-6",
            "current_phase": "run_ci",
            "test_cycle_count": 0,
            "ci_cycle_count": 4,
            "error_log": [],
            "last_ci_output": "",
            "files_modified": [],
            "session_id": "",
        }
        result = error_handler_node(state)
        assert "No errors captured" in result["error"]

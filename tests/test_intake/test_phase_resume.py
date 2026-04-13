"""Phase-level resume tests for the story and epic graphs.

Exercises the entry-router fix: a matching phase.json / epic-phase.json
should cause the respective graph to skip every upstream node and
jump directly to the next unfinished phase. Mismatched checkpoints
must be cleared rather than silently applied to a different story or
epic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.intake.checkpoint import (
    load_epic_phase_checkpoint,
    load_phase_checkpoint,
    save_epic_phase_checkpoint,
    save_phase_checkpoint,
)
from src.intake.epic_graph import (
    _EPIC_RESUME_TARGETS,
    REVIEW_BMAD_FILENAME_TEMPLATE,
    REVIEW_CLAUDE_FILENAME_TEMPLATE,
    REVIEW_MIN_CONTENT_CHARS,
    _epic_artifact_path,
    build_epic_runner,
    collect_epic_reviews_node,
    route_on_epic_entry,
)
from src.multi_agent.orchestrator import (
    _RESUME_ENTRY_PHASES,
    build_orchestrator_graph,
    route_on_entry,
)

# ---------------------------------------------------------------------------
# Router unit tests
# ---------------------------------------------------------------------------


class TestStoryRouter:
    """route_on_entry selects check_story unless a valid phase hint is set."""

    def test_no_hint_falls_through_to_check_story(self) -> None:
        assert route_on_entry({}) == "check_story"
        assert route_on_entry({"resume_from_phase": ""}) == "check_story"

    @pytest.mark.parametrize("phase", ["code_review", "run_ci", "git_commit"])
    def test_valid_phase_hints_are_honoured(self, phase: str) -> None:
        assert route_on_entry({"resume_from_phase": phase}) == phase

    def test_dev_story_is_not_a_resume_target(self) -> None:
        # dev_story is intentionally excluded — the story-status gate in
        # check_story_exists_node handles that case correctly.
        assert route_on_entry({"resume_from_phase": "dev_story"}) == "check_story"

    def test_unknown_phase_falls_through(self) -> None:
        assert route_on_entry({"resume_from_phase": "garbage"}) == "check_story"

    def test_resume_entry_phases_set_matches_router(self) -> None:
        for p in _RESUME_ENTRY_PHASES:
            assert route_on_entry({"resume_from_phase": p}) == p


class TestEpicRouter:
    """route_on_epic_entry selects select_story unless a valid hint is set."""

    def test_no_hint_falls_through_to_select_story(self) -> None:
        assert route_on_epic_entry({}) == "select_story"

    @pytest.mark.parametrize(
        "phase,target",
        list(_EPIC_RESUME_TARGETS.items()),
    )
    def test_valid_phase_routes_to_node(self, phase: str, target: str) -> None:
        assert route_on_epic_entry({"resume_from_epic_phase": phase}) == target

    def test_epic_reviews_is_not_a_resume_target(self) -> None:
        # epic_reviews involves parallel fan-out/fan-in that's hard to
        # re-enter mid-flight; the router deliberately drops it.
        assert (
            route_on_epic_entry({"resume_from_epic_phase": "epic_reviews"})
            == "select_story"
        )

    def test_unknown_phase_falls_through(self) -> None:
        assert (
            route_on_epic_entry({"resume_from_epic_phase": "nonsense"})
            == "select_story"
        )

    def test_story_index_past_end_routes_to_prepare_epic_reviews(self) -> None:
        # Repro for the bug where resume-after-last-story crashed at
        # stories[story_index] in select_story_node. The save-side
        # writes story_index+1 after every story, so a session paused
        # right after the last story comes back with
        # story_index == len(stories).
        state = {
            "stories": [{"story_id": "6-1"}, {"story_id": "6-2"}, {"story_id": "6-3"}],
            "story_index": 3,
        }
        assert route_on_epic_entry(state) == "prepare_epic_reviews"

    def test_phase_hint_beats_story_index_past_end(self) -> None:
        # If both signals fire, the phase hint wins — it means
        # post-processing actually made progress in the prior run.
        state = {
            "stories": [{"story_id": "6-1"}],
            "story_index": 1,
            "resume_from_epic_phase": "epic_ci",
        }
        assert route_on_epic_entry(state) == "epic_ci"

    def test_empty_stories_list_does_not_short_circuit(self) -> None:
        # An empty stories list with story_index=0 should NOT route
        # to prepare_epic_reviews (we'd be skipping a non-existent
        # story loop AND hitting a new branch with zero validation).
        # Fall through to select_story for the normal error path.
        assert route_on_epic_entry({"stories": [], "story_index": 0}) == "select_story"


# ---------------------------------------------------------------------------
# End-to-end: phase resume actually skips upstream graph nodes
# ---------------------------------------------------------------------------


def _make_story_state(resume_phase: str = "") -> dict[str, Any]:
    return {
        "task_id": "t1",
        "session_id": "s1",
        "context_files": [],
        "files_modified": [],
        "test_cycle_count": 0,
        "ci_cycle_count": 0,
        "test_passed": False,
        "last_test_output": "",
        "last_ci_output": "",
        "error_log": [],
        "resume_from_phase": resume_phase,
    }


class TestStoryGraphResumeE2E:
    """With mocked nodes, resume hints must skip upstream nodes entirely."""

    @patch("src.multi_agent.orchestrator.git_commit_node")
    @patch("src.multi_agent.orchestrator.run_ci_node")
    @patch("src.multi_agent.orchestrator.code_review_node")
    @patch("src.multi_agent.orchestrator.dev_story_node")
    @patch("src.multi_agent.orchestrator.check_story_exists_node")
    def test_resume_at_run_ci_skips_upstream_nodes(
        self,
        mock_check: MagicMock,
        mock_dev: MagicMock,
        mock_review: MagicMock,
        mock_ci: MagicMock,
        mock_commit: MagicMock,
    ) -> None:
        mock_ci.return_value = {
            "test_passed": True,
            "ci_cycle_count": 1,
            "last_ci_output": "",
            "current_phase": "run_ci",
        }
        mock_commit.return_value = {
            "pipeline_status": "completed",
            "current_phase": "git_commit",
        }

        graph = build_orchestrator_graph().compile()
        graph.invoke(_make_story_state("run_ci"))

        assert not mock_check.called, "check_story must not run on resume"
        assert not mock_dev.called, "dev_story must not run on resume-to-run_ci"
        assert not mock_review.called, "code_review must be skipped"
        assert mock_ci.called, "run_ci must execute"
        assert mock_commit.called, "git_commit must execute after CI passes"

    @patch("src.multi_agent.orchestrator.git_commit_node")
    @patch("src.multi_agent.orchestrator.run_ci_node")
    @patch("src.multi_agent.orchestrator.code_review_node")
    @patch("src.multi_agent.orchestrator.dev_story_node")
    @patch("src.multi_agent.orchestrator.check_story_exists_node")
    def test_resume_at_git_commit_only_runs_commit(
        self,
        mock_check: MagicMock,
        mock_dev: MagicMock,
        mock_review: MagicMock,
        mock_ci: MagicMock,
        mock_commit: MagicMock,
    ) -> None:
        mock_commit.return_value = {
            "pipeline_status": "completed",
            "current_phase": "git_commit",
        }

        graph = build_orchestrator_graph().compile()
        graph.invoke(_make_story_state("git_commit"))

        assert not mock_check.called
        assert not mock_dev.called
        assert not mock_review.called
        assert not mock_ci.called, (
            "run_ci must NOT re-run when resuming at git_commit"
        )
        assert mock_commit.called

    @patch("src.multi_agent.orchestrator.git_commit_node")
    @patch("src.multi_agent.orchestrator.run_ci_node")
    @patch("src.multi_agent.orchestrator.code_review_node")
    @patch("src.multi_agent.orchestrator.dev_story_node")
    @patch("src.multi_agent.orchestrator.check_story_exists_node")
    def test_no_hint_runs_check_story_path(
        self,
        mock_check: MagicMock,
        mock_dev: MagicMock,
        mock_review: MagicMock,
        mock_ci: MagicMock,
        mock_commit: MagicMock,
    ) -> None:
        mock_check.return_value = {
            "story_exists": True,
            "dev_complete": True,  # skip dev_story via story-status gate
            "current_phase": "check_story",
        }
        mock_review.return_value = {"current_phase": "code_review"}
        mock_ci.return_value = {
            "test_passed": True,
            "ci_cycle_count": 1,
            "last_ci_output": "",
            "current_phase": "run_ci",
        }
        mock_commit.return_value = {
            "pipeline_status": "completed",
            "current_phase": "git_commit",
        }

        graph = build_orchestrator_graph().compile()
        graph.invoke(_make_story_state(""))

        assert mock_check.called, "check_story must run when no hint present"
        assert mock_review.called
        assert mock_ci.called
        assert mock_commit.called


# ---------------------------------------------------------------------------
# Phase checkpoint staleness handling
# ---------------------------------------------------------------------------


class TestStalePhaseCheckpoint:
    """run_story_node must clear checkpoints that don't match current story."""

    def test_matching_checkpoint_returns_next_phase(self, tmp_path: Path) -> None:
        save_phase_checkpoint("s1", str(tmp_path), "5-5", "code_review")
        ckpt = load_phase_checkpoint(str(tmp_path))
        assert ckpt is not None
        assert ckpt["next_phase"] == "run_ci"
        assert ckpt["story_id"] == "5-5"
        assert ckpt["session_id"] == "s1"

    def test_stale_session_id_is_detected(self, tmp_path: Path) -> None:
        save_phase_checkpoint("old-session", str(tmp_path), "5-5", "code_review")
        ckpt = load_phase_checkpoint(str(tmp_path))
        assert ckpt is not None
        # Caller in run_story_node compares session_id explicitly.
        assert ckpt["session_id"] != "new-session"

    def test_stale_story_id_is_detected(self, tmp_path: Path) -> None:
        save_phase_checkpoint("s1", str(tmp_path), "5-5", "run_ci")
        ckpt = load_phase_checkpoint(str(tmp_path))
        assert ckpt is not None
        assert ckpt["story_id"] != "5-6"

    def test_missing_checkpoint_returns_none(self, tmp_path: Path) -> None:
        assert load_phase_checkpoint(str(tmp_path)) is None

    def test_phase_after_git_commit_has_empty_next(self, tmp_path: Path) -> None:
        save_phase_checkpoint("s1", str(tmp_path), "5-5", "git_commit")
        ckpt = load_phase_checkpoint(str(tmp_path))
        assert ckpt is not None
        assert ckpt["next_phase"] == "", (
            "git_commit is terminal — next_phase must be empty"
        )


class TestStaleEpicPhaseCheckpoint:
    """run_epic_node must clear checkpoints that don't match current epic."""

    def test_matching_epic_checkpoint_returns_next_phase(
        self, tmp_path: Path,
    ) -> None:
        save_epic_phase_checkpoint("s1", str(tmp_path), "5", "epic_analysis")
        ckpt = load_epic_phase_checkpoint(str(tmp_path))
        assert ckpt is not None
        assert ckpt["next_phase"] == "epic_category_a"
        assert ckpt["epic_num"] == "5"

    def test_stale_epic_num_is_detected(self, tmp_path: Path) -> None:
        save_epic_phase_checkpoint("s1", str(tmp_path), "4", "epic_ci")
        ckpt = load_epic_phase_checkpoint(str(tmp_path))
        assert ckpt is not None
        assert ckpt["epic_num"] != "5"

    def test_missing_epic_checkpoint_returns_none(self, tmp_path: Path) -> None:
        assert load_epic_phase_checkpoint(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# End-to-end: epic graph phase resume
# ---------------------------------------------------------------------------


def _epic_state(resume_phase: str = "") -> dict[str, Any]:
    return {
        "session_id": "s1",
        "target_dir": ".",
        "epic_num": "5",
        "epic_name": "e5",
        "stories": [],
        "story_index": 0,
        "story_results": [],
        "stories_completed": 0,
        "stories_failed": 0,
        "total_interventions": 0,
        "epic_files_modified": [],
        "current_story_status": "",
        "current_story_error": "",
        "current_story_failed_phase": "",
        "current_story_retry_instruction": "",
        "epic_review_file_paths": [],
        "epic_fix_plan_path": "",
        "epic_fixes_needed": False,
        "epic_fix_cycle": 0,
        "epic_test_passed": False,
        "epic_last_test_output": "",
        "epic_last_ci_output": "",
        "epic_status": "running",
        "error": "",
        "rebuild_epic_index": 0,
        "rebuild_prior_completed": 0,
        "rebuild_prior_failed": 0,
        "rebuild_prior_interventions": 0,
        "rebuild_prior_results": [],
        "resume_from_epic_phase": resume_phase,
    }


def _stubs() -> dict[str, MagicMock]:
    names = [
        "select_story_node", "run_story_node", "process_story_result_node",
        "advance_story_node", "epic_paused_node", "epic_halt_node",
        "prepare_epic_reviews_node", "collect_epic_reviews_node",
        "analyze_reviews_node", "fix_category_a_node",
        "epic_architect_node", "epic_fix_node", "epic_ci_node",
        "epic_git_commit_node", "epic_error_node", "epic_complete_node",
    ]
    stubs = {n: MagicMock(return_value={}, __name__=n) for n in names}
    # Return values that route forward through the happy path.
    stubs["epic_ci_node"].return_value = {"epic_test_passed": True}
    stubs["epic_architect_node"].return_value = {"epic_fixes_needed": False}
    stubs["fix_category_a_node"].return_value = {"has_category_b_items": False}
    return stubs


class TestEpicGraphResumeE2E:
    """Hints must skip upstream post-processing nodes and the story loop."""

    def test_resume_at_epic_ci_skips_earlier_phases(self) -> None:
        stubs = _stubs()
        with patch.multiple("src.intake.epic_graph", **stubs):
            build_epic_runner().invoke(_epic_state("epic_ci"))

        called = {n.replace("_node", "") for n, m in stubs.items() if m.called}
        assert "select_story" not in called
        assert "run_story" not in called
        assert "prepare_epic_reviews" not in called
        assert "analyze_reviews" not in called
        assert "fix_category_a" not in called
        assert "epic_architect" not in called
        assert "epic_fix" not in called
        assert "epic_ci" in called
        assert "epic_git_commit" in called
        assert "epic_complete" in called

    def test_resume_at_epic_git_commit_only_finalises(self) -> None:
        stubs = _stubs()
        with patch.multiple("src.intake.epic_graph", **stubs):
            build_epic_runner().invoke(_epic_state("epic_git_commit"))

        called = {n.replace("_node", "") for n, m in stubs.items() if m.called}
        assert "epic_ci" not in called, (
            "epic_ci must not re-run when resuming at epic_git_commit"
        )
        assert "epic_git_commit" in called
        assert "epic_complete" in called

    def _write_review(
        self, target_dir: Path, template: str, epic_num: str, content: str,
    ) -> Path:
        path = Path(_epic_artifact_path(template, epic_num, str(target_dir)))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_collect_epic_reviews_saves_checkpoint_on_success(
        self, tmp_path: Path,
    ) -> None:
        """Both reviews full-size → phase checkpoint gets written."""
        epic_num = "7"
        self._write_review(
            tmp_path, REVIEW_BMAD_FILENAME_TEMPLATE, epic_num,
            "x" * (REVIEW_MIN_CONTENT_CHARS + 100),
        )
        self._write_review(
            tmp_path, REVIEW_CLAUDE_FILENAME_TEMPLATE, epic_num,
            "y" * (REVIEW_MIN_CONTENT_CHARS + 100),
        )
        state: dict = {
            "session_id": "s1",
            "target_dir": str(tmp_path),
            "epic_num": epic_num,
        }
        result = collect_epic_reviews_node(state)  # type: ignore[arg-type]
        assert len(result["epic_review_file_paths"]) == 2
        # Phase checkpoint written → next resume would skip to analyze.
        assert load_epic_phase_checkpoint(str(tmp_path)) is not None
        assert (
            load_epic_phase_checkpoint(str(tmp_path))["completed_phase"]
            == "epic_reviews"
        )

    def test_collect_epic_reviews_raises_on_empty_claude_file(
        self, tmp_path: Path,
    ) -> None:
        """The exact bug from the chat2bpmn run: 55-byte bmad + 0-byte
        claude used to save ``epic_reviews`` as completed, causing the
        next resume to skip straight into a broken analyze_reviews."""
        epic_num = "6"
        self._write_review(
            tmp_path, REVIEW_BMAD_FILENAME_TEMPLATE, epic_num, "x" * 55,
        )
        self._write_review(
            tmp_path, REVIEW_CLAUDE_FILENAME_TEMPLATE, epic_num, "",
        )
        state: dict = {
            "session_id": "s1",
            "target_dir": str(tmp_path),
            "epic_num": epic_num,
        }
        with pytest.raises(RuntimeError) as exc:
            collect_epic_reviews_node(state)  # type: ignore[arg-type]

        msg = str(exc.value)
        assert "BMAD" in msg
        assert "Claude" in msg
        assert "too short" in msg
        # No checkpoint saved — next resume will re-run the reviews.
        assert load_epic_phase_checkpoint(str(tmp_path)) is None

    def test_collect_epic_reviews_raises_on_missing_files(
        self, tmp_path: Path,
    ) -> None:
        state: dict = {
            "session_id": "s1",
            "target_dir": str(tmp_path),
            "epic_num": "8",
        }
        with pytest.raises(RuntimeError, match="missing"):
            collect_epic_reviews_node(state)  # type: ignore[arg-type]
        assert load_epic_phase_checkpoint(str(tmp_path)) is None

    def test_collect_epic_reviews_raises_on_single_too_short_file(
        self, tmp_path: Path,
    ) -> None:
        """One reviewer produced a real review; the other wrote a
        preamble-sized stub. Still a failure — we require both."""
        epic_num = "9"
        self._write_review(
            tmp_path, REVIEW_BMAD_FILENAME_TEMPLATE, epic_num,
            "x" * (REVIEW_MIN_CONTENT_CHARS + 500),
        )
        self._write_review(
            tmp_path, REVIEW_CLAUDE_FILENAME_TEMPLATE, epic_num,
            "tiny stub",
        )
        state: dict = {
            "session_id": "s1",
            "target_dir": str(tmp_path),
            "epic_num": epic_num,
        }
        with pytest.raises(RuntimeError) as exc:
            collect_epic_reviews_node(state)  # type: ignore[arg-type]
        # Error mentions the reviewer that failed, not the one that
        # produced a valid file.
        assert "Claude review file too short" in str(exc.value)
        assert "BMAD review file too short" not in str(exc.value)
        assert load_epic_phase_checkpoint(str(tmp_path)) is None

    def test_collect_epic_reviews_threshold_matches_sieve(self) -> None:
        """Both layers must use the same "real review" threshold —
        otherwise the sieve's format-drift fallback fires on reviews
        collect_epic_reviews already accepted (or vice versa)."""
        assert REVIEW_MIN_CONTENT_CHARS == 1000

    def test_no_hint_enters_story_loop(self) -> None:
        stubs = _stubs()
        with patch.multiple("src.intake.epic_graph", **stubs):
            build_epic_runner().invoke(_epic_state(""))

        called = {n.replace("_node", "") for n, m in stubs.items() if m.called}
        assert "select_story" in called, (
            "normal entry must hit the story loop"
        )

    def test_story_index_past_end_skips_loop_and_runs_reviews(self) -> None:
        """Resume-after-last-story regression: router must skip the
        story loop entirely and start at prepare_epic_reviews. Before
        this fix, select_story_node crashed at
        ``stories[story_index]`` with IndexError."""
        stubs = _stubs()
        # Session was paused right after the last story (6-3) of a
        # 3-story epic, so story_index == len(stories) == 3.
        state = _epic_state("")
        state["stories"] = [
            {"story_id": "6-1", "story_name": "one",
             "description": "", "acceptance_criteria": []},
            {"story_id": "6-2", "story_name": "two",
             "description": "", "acceptance_criteria": []},
            {"story_id": "6-3", "story_name": "three",
             "description": "", "acceptance_criteria": []},
        ]
        state["story_index"] = 3

        with patch.multiple("src.intake.epic_graph", **stubs):
            build_epic_runner().invoke(state)

        called = {n.replace("_node", "") for n, m in stubs.items() if m.called}
        assert "select_story" not in called, (
            "must NOT enter select_story — would crash on stories[3]"
        )
        assert "run_story" not in called
        assert "prepare_epic_reviews" in called, (
            "must enter epic post-processing from the start"
        )

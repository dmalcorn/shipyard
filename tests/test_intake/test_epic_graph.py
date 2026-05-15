"""Tests for src/intake/epic_graph.py — epic-level graph (Level 2)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.intake.epic_graph import (
    EpicState,
    _compose_task_id,
    _extract_ci_failure_excerpt,
    advance_story_node,
    analyze_reviews_node,
    batch_commit_node,
    build_epic_graph,
    epic_complete_node,
    epic_halt_node,
    prepare_batch_review_node,
    prepare_epic_reviews_node,
    process_story_result_node,
    route_after_batch_architect,
    route_after_batch_ci,
    route_after_category_a,
    route_after_epic_architect,
    route_after_epic_ci,
    route_after_story_result,
    route_next_story,
    select_story_node,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "review_sieve"


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

    def test_failed_story_continues(self) -> None:
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
        # Failed stories are recorded but never abort the epic
        assert "epic_status" not in result

    def test_completed_story_increments_batch_counter(self) -> None:
        # Only completed stories count toward the batch trigger — failed
        # stories' work is uncommitted, so there's nothing to review.
        # ``story_id`` is in the realistic ``load_backlog`` form (already
        # epic-prefixed) — the _compose_task_id helper detects this and
        # avoids the doubled-prefix "6-6-3" bug.
        state: EpicState = {
            "epic_num": "6",
            "epic_name": "Auth",
            "stories": [{"story_id": "6-3", "story_name": "Login"}],
            "story_index": 0,
            "current_story_status": "completed",
            "stories_completed": 0,
            "stories_failed": 0,
            "stories_in_current_batch": 2,
            "current_batch_story_ids": ["6-1", "6-2"],
        }
        result = process_story_result_node(state)
        assert result["stories_in_current_batch"] == 3
        assert result["current_batch_story_ids"] == ["6-1", "6-2", "6-3"]

    def test_failed_story_does_not_increment_batch_counter(self) -> None:
        state: EpicState = {
            "epic_num": "6",
            "epic_name": "Auth",
            "stories": [{"story_id": "3", "story_name": "Login"}],
            "story_index": 0,
            "current_story_status": "failed",
            "stories_completed": 0,
            "stories_failed": 0,
            "stories_in_current_batch": 2,
            "current_batch_story_ids": ["6-1", "6-2"],
        }
        result = process_story_result_node(state)
        assert "stories_in_current_batch" not in result
        assert "current_batch_story_ids" not in result

    def test_spike_completion_does_not_increment_batch_counter(self) -> None:
        # Doc-only spike stories shouldn't count toward the batch
        # trigger — including their task_ids in current_batch_story_ids
        # mis-frames the batch reviewer (observed Epic 7 batch-1 on
        # 2026-05-09: spike's `safety-conventions.md` was the first
        # file the reviewer loaded, all 11 findings landed on the spec).
        state: EpicState = {
            "epic_num": "7",
            "epic_name": "Safety & Toxic Ingredient Guardrails",
            "stories": [{"story_id": "7-1", "story_name": "Safety Patterns Spike"}],
            "story_index": 0,
            "current_story_status": "completed",
            "stories_completed": 0,
            "stories_failed": 0,
            "stories_in_current_batch": 0,
            "current_batch_story_ids": [],
        }
        result = process_story_result_node(state)
        # stories_completed still bumps (the global counter cares about
        # all completions, not just countable ones)
        assert result["stories_completed"] == 1
        # But the batch counter does NOT bump
        assert "stories_in_current_batch" not in result
        assert "current_batch_story_ids" not in result

    def test_polish_completion_does_not_increment_batch_counter(self) -> None:
        state: EpicState = {
            "epic_num": "7",
            "epic_name": "Safety & Toxic Ingredient Guardrails",
            "stories": [
                {
                    "story_id": "7-8",
                    "story_name": "Integration Polish for safety browse + detail flow",
                },
            ],
            "story_index": 0,
            "current_story_status": "completed",
            "stories_completed": 7,
            "stories_failed": 0,
            "stories_in_current_batch": 1,
            "current_batch_story_ids": ["7-7"],
        }
        result = process_story_result_node(state)
        assert result["stories_completed"] == 8
        # Polish is the last story by convention; it doesn't increment
        # the batch counter (route_next_story will see story_index >=
        # len(stories) and route to epic_done before any batch fires).
        assert "stories_in_current_batch" not in result
        assert "current_batch_story_ids" not in result

    def test_spike_match_is_case_insensitive(self) -> None:
        # _SPIKE_TITLE_RE uses re.IGNORECASE, so "spike", "Spike",
        # "SPIKE" all match. Sanity-check the path.
        state: EpicState = {
            "epic_num": "7",
            "epic_name": "x",
            "stories": [{"story_id": "7-1", "story_name": "Architecture spike outcomes"}],
            "story_index": 0,
            "current_story_status": "completed",
            "stories_completed": 0,
            "stories_failed": 0,
            "stories_in_current_batch": 0,
            "current_batch_story_ids": [],
        }
        result = process_story_result_node(state)
        assert "stories_in_current_batch" not in result


class TestAdvanceStoryNode:
    """advance_story_node increments index."""

    def test_increments(self) -> None:
        result = advance_story_node({"story_index": 2})
        assert result["story_index"] == 3
        assert result["current_story_retry_instruction"] == ""


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------


class TestComposeTaskId:
    """_compose_task_id idempotently combines epic_num + story_id.

    Regression: load_backlog stores story_id as ``"7-1"`` (already
    epic-prefixed), so a naive ``f"{epic_num}-{story_id}"`` produced
    ``"7-7-1"`` in the BMAD reviewer's input_stories list during the
    first PawprintRecipes batch review on 2026-05-09.
    """

    def test_already_prefixed_returns_unchanged(self) -> None:
        # The realistic load_backlog case
        assert _compose_task_id("7", "7-1") == "7-1"
        assert _compose_task_id("11", "11-3") == "11-3"

    def test_unprefixed_gets_prefix(self) -> None:
        # Defensive: if a caller hands a bare story_id, still works
        assert _compose_task_id("7", "1") == "7-1"
        assert _compose_task_id("6", "3") == "6-3"

    def test_empty_epic_num_returns_story_id(self) -> None:
        assert _compose_task_id("", "1") == "1"
        assert _compose_task_id("", "7-1") == "7-1"

    def test_does_not_match_partial_epic_prefix(self) -> None:
        # Epic 1 should NOT match a story_id starting with "11-" — the
        # check is `startswith(f"{epic_num}-")` so the trailing dash
        # disambiguates "1-" vs "11-".
        assert _compose_task_id("1", "11-3") == "1-11-3"
        assert _compose_task_id("11", "1-3") == "11-1-3"


class TestRouteAfterStoryResult:
    """route_after_story_result routes based on story status."""

    def test_completed(self) -> None:
        assert route_after_story_result({"current_story_status": "completed"}) == "next_story"

    def test_failed_run_ci_halts(self) -> None:
        # run_ci exhaustion (4 cycles) leaves a dirty tree — halt so the
        # operator can investigate before downstream stories are poisoned.
        state: EpicState = {
            "current_story_status": "failed",
            "current_story_failed_phase": "run_ci",
        }
        assert route_after_story_result(state) == "halt"

    def test_failed_dev_story_continues(self) -> None:
        # Transient failures in non-tree-mutating phases still advance.
        state: EpicState = {
            "current_story_status": "failed",
            "current_story_failed_phase": "dev_story",
        }
        assert route_after_story_result(state) == "next_story"

    def test_failed_git_commit_halts(self) -> None:
        state: EpicState = {
            "current_story_status": "failed",
            "current_story_failed_phase": "git_commit",
        }
        assert route_after_story_result(state) == "halt"

    def test_completed_story_never_halts(self) -> None:
        # current_story_failed_phase may linger from prior state; a
        # completed story should still advance regardless.
        state: EpicState = {
            "current_story_status": "completed",
            "current_story_failed_phase": "git_commit",
        }
        assert route_after_story_result(state) == "next_story"


class TestRouteNextStory:
    """route_next_story checks if more stories remain or a batch should fire."""

    def test_more_stories(self) -> None:
        # After advance_story_node: story_index is 1, 2 stories remain
        state: EpicState = {
            "stories": [{"story": "A"}, {"story": "B"}],
            "story_index": 1,
        }
        assert route_next_story(state) == "more_stories"

    def test_epic_done(self) -> None:
        # After advance_story_node: story_index is 1, only 1 story total
        state: EpicState = {
            "stories": [{"story": "A"}],
            "story_index": 1,
        }
        assert route_next_story(state) == "epic_done"

    def test_batch_boundary_fires_at_threshold(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("src.intake.epic_graph.get_story_batch_size", lambda: 4)
        state: EpicState = {
            "stories": [{"story": str(i)} for i in range(8)],
            "story_index": 4,  # 4 completed; 4 remain
            "stories_in_current_batch": 4,
        }
        assert route_next_story(state) == "batch_boundary"

    def test_batch_below_threshold_returns_more_stories(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("src.intake.epic_graph.get_story_batch_size", lambda: 4)
        state: EpicState = {
            "stories": [{"story": str(i)} for i in range(8)],
            "story_index": 3,
            "stories_in_current_batch": 3,
        }
        assert route_next_story(state) == "more_stories"

    def test_batch_size_zero_disables_trigger(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("src.intake.epic_graph.get_story_batch_size", lambda: 0)
        state: EpicState = {
            "stories": [{"story": str(i)} for i in range(8)],
            "story_index": 4,
            "stories_in_current_batch": 99,  # would normally fire
        }
        assert route_next_story(state) == "more_stories"

    def test_master_toggle_disables_trigger(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Step 13a: any of the three opt-out paths (CLI flag, config key,
        # interactive prompt) flips _BATCH_REVIEWS_ENABLED to False, which
        # suppresses the batch pipeline entirely regardless of size config.
        monkeypatch.setattr("src.intake.epic_graph.get_story_batch_size", lambda: 4)
        monkeypatch.setattr("src.intake.epic_graph.get_batch_reviews_enabled", lambda: False)
        state: EpicState = {
            "stories": [{"story": str(i)} for i in range(8)],
            "story_index": 4,
            "stories_in_current_batch": 4,  # would fire if toggle were on
        }
        assert route_next_story(state) == "more_stories"

    def test_batch_aligned_epic_end_short_circuits_to_epic_done(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Edge case 4 in the design doc: epic_size % batch_size == 0
        # must NOT fire a redundant final batch — epic-end review covers
        # the remaining stories anyway.
        monkeypatch.setattr("src.intake.epic_graph.get_story_batch_size", lambda: 4)
        state: EpicState = {
            "stories": [{"story": str(i)} for i in range(8)],
            "story_index": 8,  # all stories done
            "stories_in_current_batch": 4,
        }
        assert route_next_story(state) == "epic_done"

    def test_eight_story_epic_with_batch_size_four_fires_once(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 8-story epic, batch_size=4 → exactly one batch (after story 4).
        monkeypatch.setattr("src.intake.epic_graph.get_story_batch_size", lambda: 4)

        # After story 4: batch_boundary
        assert route_next_story({
            "stories": [{"story": str(i)} for i in range(8)],
            "story_index": 4,
            "stories_in_current_batch": 4,
        }) == "batch_boundary"

        # After story 8 with reset counter: epic_done (no second batch).
        assert route_next_story({
            "stories": [{"story": str(i)} for i in range(8)],
            "story_index": 8,
            "stories_in_current_batch": 4,  # would fire if any stories remained
        }) == "epic_done"

    def test_eleven_story_epic_with_batch_size_four_fires_twice(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 11-story epic, batch_size=4 → two batches (after 4 and 8).
        # Stories 9, 10, 11 fold into the epic-end review (no third batch).
        monkeypatch.setattr("src.intake.epic_graph.get_story_batch_size", lambda: 4)

        # After story 4: batch_boundary
        assert route_next_story({
            "stories": [{"story": str(i)} for i in range(11)],
            "story_index": 4,
            "stories_in_current_batch": 4,
        }) == "batch_boundary"

        # After story 8: batch_boundary (counter reset to 0 after first
        # batch, then accumulated to 4 again across stories 5-8).
        assert route_next_story({
            "stories": [{"story": str(i)} for i in range(11)],
            "story_index": 8,
            "stories_in_current_batch": 4,
        }) == "batch_boundary"

        # After story 11: epic_done (counter reset, only 3 stories
        # accumulated, below threshold AND no stories remain).
        assert route_next_story({
            "stories": [{"story": str(i)} for i in range(11)],
            "story_index": 11,
            "stories_in_current_batch": 3,
        }) == "epic_done"


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
    """route_after_epic_ci routes pass or halt (no longer 'error')."""

    def test_pass(self) -> None:
        assert route_after_epic_ci({"epic_test_passed": True}) == "pass"

    def test_halt_on_fail(self) -> None:
        # Replaced the legacy "error" return — failures now route to
        # epic_halt so the run stops with state preserved for operator
        # inspection instead of silently advancing to the next epic.
        assert route_after_epic_ci({"epic_test_passed": False}) == "halt"

    def test_default_unset_routes_to_halt(self) -> None:
        # Defensive: an unset epic_test_passed routes to halt (safer
        # than silently committing on missing CI signal).
        assert route_after_epic_ci({}) == "halt"


# ---------------------------------------------------------------------------
# Terminal node tests
# ---------------------------------------------------------------------------


class TestEpicCompleteNode:
    """epic_complete_node sets status."""

    def test_sets_completed(self) -> None:
        result = epic_complete_node({})
        assert result["epic_status"] == "completed"


class TestEpicHaltNode:
    """epic_halt_node renders scope-specific halt messages."""

    def test_epic_ci_failure_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Exhausted epic-CI failure produces a halt that names the epic
        # explicitly and tells the operator to fix and resume.
        state: EpicState = {
            "epic_num": "6",
            "current_story_failed_phase": "epic_ci",
            "current_story_error": "ruff failed: 12 errors",
        }
        result = epic_halt_node(state)
        captured = capsys.readouterr()
        assert "Epic 6 CI failed" in result["error"]
        assert "Epic 6 CI failed" in captured.out
        assert result["epic_status"] == "paused"

    def test_batch_ci_failure_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        state: EpicState = {
            "epic_num": "6",
            "batch_num": 2,
            "current_story_failed_phase": "batch_ci",
            "current_story_error": "ruff failed",
        }
        result = epic_halt_node(state)
        captured = capsys.readouterr()
        assert "Epic 6 batch 2 CI failed" in captured.out
        assert result["epic_status"] == "paused"

    def test_story_phase_failure_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        state: EpicState = {
            "epic_num": "6",
            "stories": [{"story_id": "3", "story_name": "Login"}],
            "story_index": 0,
            "current_story_failed_phase": "git_commit",
            "current_story_error": "index lock",
        }
        result = epic_halt_node(state)
        captured = capsys.readouterr()
        assert "halted at story 3" in captured.out
        assert "phase=git_commit" in captured.out
        assert result["epic_status"] == "paused"


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
        """Graph contains all expected nodes (story loop + epic-end + batch)."""
        graph = build_epic_graph()
        node_names = set(graph.nodes.keys())
        expected = {
            # Story loop
            "select_story", "run_story", "process_result", "advance_story",
            "epic_paused", "epic_halt",
            # Epic-end pipeline (epic_error_node removed 2026-05-09 —
            # CI failure now routes to epic_halt for operator handoff)
            "prepare_epic_reviews", "epic_review_node", "collect_epic_reviews",
            "analyze_reviews", "fix_category_a",
            "epic_architect", "epic_fix", "epic_ci",
            "epic_git_commit", "epic_complete",
            # Mid-epic batch pipeline (Group 3)
            "prepare_batch_review", "batch_review", "analyze_batch_review",
            "fix_batch_category_a", "batch_architect", "batch_fix",
            "batch_ci", "batch_commit",
        }
        assert expected.issubset(node_names), f"Missing: {expected - node_names}"

    def test_batch_pipeline_linear_edges_wired(self) -> None:
        """Linear edges in the mid-epic batch path point at the right targets."""
        graph = build_epic_graph()
        edges = graph.edges
        # Linear (unconditional) edges in the batch pipeline.
        assert ("prepare_batch_review", "batch_review") in edges
        assert ("batch_review", "analyze_batch_review") in edges
        assert ("analyze_batch_review", "fix_batch_category_a") in edges
        assert ("batch_fix", "batch_ci") in edges
        # After a successful batch commit, the loop resumes at select_story.
        assert ("batch_commit", "select_story") in edges

    def test_batch_pipeline_conditional_branches_wired(self) -> None:
        """Conditional routers in the batch path are registered."""
        graph = build_epic_graph()
        # ``branches`` is a dict[node_name -> {branch_id -> Branch}].
        branches = graph.branches
        # advance_story has the new "batch_boundary" branch destination.
        advance_branch_targets: set[str] = set()
        for branch in branches.get("advance_story", {}).values():
            ends = branch.ends or {}
            advance_branch_targets.update(ends.values())
        assert "prepare_batch_review" in advance_branch_targets

        # fix_batch_category_a routes through the shared route_after_category_a
        # router but with the batch pipeline's edge map (architect / ci targets).
        fbca_targets: set[str] = set()
        for branch in branches.get("fix_batch_category_a", {}).values():
            ends = branch.ends or {}
            fbca_targets.update(ends.values())
        assert "batch_architect" in fbca_targets
        assert "batch_ci" in fbca_targets

        # batch_architect routes via route_after_batch_architect.
        ba_targets: set[str] = set()
        for branch in branches.get("batch_architect", {}).values():
            ends = branch.ends or {}
            ba_targets.update(ends.values())
        assert "batch_fix" in ba_targets
        assert "batch_ci" in ba_targets

        # batch_ci routes pass→batch_commit, halt→epic_halt.
        bci_targets: set[str] = set()
        for branch in branches.get("batch_ci", {}).values():
            ends = branch.ends or {}
            bci_targets.update(ends.values())
        assert "batch_commit" in bci_targets
        assert "epic_halt" in bci_targets


# ---------------------------------------------------------------------------
# prepare_epic_reviews_node — directory preservation
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> None:
    """Run a git command in ``cwd``, asserting success."""
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
    )


@pytest.fixture
def epic_repo(tmp_path: Path) -> Path:
    """Create a tiny git repo with commits that mimic the story-loop pattern."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)

    def commit(message: str, files: list[str]) -> None:
        for path in files:
            p = repo / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"// {message}\n", encoding="utf-8")
        _git(["add", "-A"], repo)
        _git(["commit", "-q", "-m", message], repo)

    commit("chore: initial", ["README.md"])
    commit("story 3-1 complete", ["src/a.ts", "src/b.ts"])
    commit("chore: update rebuild status", ["rebuild-status.md"])
    commit("story 3-2 complete", ["src/c.ts"])
    commit("story 3-3 complete", ["src/a.ts", "src/d.ts"])  # re-touches a.ts
    commit("story 4-1 complete", ["src/other.ts"])  # different epic
    return repo


class TestPrepareEpicReviewsNode:
    """prepare_epic_reviews_node directory-preservation behavior."""

    def test_preserves_prior_epic_files_in_reviews_dir(
        self, epic_repo: Path,
    ) -> None:
        """Per-epic filenames mean ``prepare_epic_reviews_node`` must NOT
        wipe the directory — an earlier epic's outputs must survive."""
        reviews_dir = epic_repo / "epic-reviews"
        reviews_dir.mkdir()
        # Simulate an Epic 2 artifact already on disk.
        prior = reviews_dir / "epic-2-analysis.md"
        prior.write_text("epic 2 analysis content", encoding="utf-8")

        # Run prepare for Epic 3.
        prepare_epic_reviews_node({
            "target_dir": str(epic_repo),
            "epic_num": "3",
        })

        # Epic 2's file is still there.
        assert prior.exists()
        assert prior.read_text(encoding="utf-8") == "epic 2 analysis content"


# ---------------------------------------------------------------------------
# analyze_reviews_node — end-to-end template resolution
# ---------------------------------------------------------------------------


def _seed_review_files(
    target_dir: Path, epic_num: str, bmad: str, claude: str,
) -> tuple[Path, Path]:
    """Write BMAD and Claude review fixtures at the epic-numbered paths."""
    reviews_dir = target_dir / "epic-reviews"
    reviews_dir.mkdir(exist_ok=True)
    bmad_path = reviews_dir / f"epic-{epic_num}-review-bmad.md"
    claude_path = reviews_dir / f"epic-{epic_num}-review-claude.md"
    bmad_path.write_text(bmad, encoding="utf-8")
    claude_path.write_text(claude, encoding="utf-8")
    return bmad_path, claude_path


@pytest.fixture
def epic3_bmad() -> str:
    return (FIXTURES_DIR / "epic-3-review-bmad.md").read_text(encoding="utf-8")


@pytest.fixture
def epic3_claude() -> str:
    return (FIXTURES_DIR / "epic-3-review-claude.md").read_text(encoding="utf-8")


class TestAnalyzeReviewsNodeFilenameResolution:
    """Exercise the full sieve write path with a real tmp directory.

    The node reads two review files and writes three: analysis,
    category-A, category-B. Every path must carry the epic number so
    multiple epics can coexist under the same ``epic-reviews/`` dir.
    """

    def test_writes_epic_numbered_artifacts(
        self, tmp_path: Path, epic3_bmad: str, epic3_claude: str,
    ) -> None:
        # Seed Epic 7's reviews with Epic 3's fixture content — it parses
        # cleanly, so the sieve succeeds and we never hit the LLM fallback.
        _seed_review_files(tmp_path, "7", epic3_bmad, epic3_claude)

        result = analyze_reviews_node({
            "target_dir": str(tmp_path),
            "epic_num": "7",
            "epic_review_file_paths": [],
        })

        reviews_dir = tmp_path / "epic-reviews"
        expected_analysis = reviews_dir / "epic-7-analysis.md"
        expected_cat_a = reviews_dir / "epic-7-category-a-fix-plan.md"
        expected_cat_b = reviews_dir / "epic-7-category-b-architect-review.md"

        # Files landed at the epic-numbered paths.
        assert expected_analysis.exists()
        assert expected_cat_a.exists()
        assert expected_cat_b.exists()

        # State reflects the same epic-numbered paths.
        assert result["analysis_path"] == str(expected_analysis)
        assert result["category_a_fix_plan_path"] == str(expected_cat_a)
        assert result["category_b_review_path"] == str(expected_cat_b)
        assert result["has_category_b_items"] is True  # Epic 3 fixture has 2

        # Sieve analysis file references "Epic 7" in the title.
        assert "Epic 7" in expected_analysis.read_text(encoding="utf-8")

        # No unqualified filenames were created.
        for legacy in (
            "analysis.md",
            "category-a-fix-plan.md",
            "category-b-architect-review.md",
            "epic-review-bmad.md",
            "epic-review-claude.md",
        ):
            assert not (reviews_dir / legacy).exists(), (
                f"unexpected legacy filename {legacy}"
            )

    def test_multiple_epics_coexist_without_clobber(
        self, tmp_path: Path, epic3_bmad: str, epic3_claude: str,
    ) -> None:
        """Running analyze for Epic 4 then Epic 5 leaves both sets intact."""
        _seed_review_files(tmp_path, "4", epic3_bmad, epic3_claude)
        analyze_reviews_node({
            "target_dir": str(tmp_path),
            "epic_num": "4",
            "epic_review_file_paths": [],
        })

        _seed_review_files(tmp_path, "5", epic3_bmad, epic3_claude)
        analyze_reviews_node({
            "target_dir": str(tmp_path),
            "epic_num": "5",
            "epic_review_file_paths": [],
        })

        reviews_dir = tmp_path / "epic-reviews"
        for epic in ("4", "5"):
            assert (reviews_dir / f"epic-{epic}-review-bmad.md").exists()
            assert (reviews_dir / f"epic-{epic}-review-claude.md").exists()
            assert (reviews_dir / f"epic-{epic}-analysis.md").exists()
            assert (reviews_dir / f"epic-{epic}-category-a-fix-plan.md").exists()
            assert (
                reviews_dir / f"epic-{epic}-category-b-architect-review.md"
            ).exists()

        # Each epic's analysis file names its own epic, confirming no
        # file was silently overwritten by the other epic's run.
        assert "Epic 4" in (
            reviews_dir / "epic-4-analysis.md"
        ).read_text(encoding="utf-8")
        assert "Epic 5" in (
            reviews_dir / "epic-5-analysis.md"
        ).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Mid-epic batch nodes (Group 3 + 4)
# ---------------------------------------------------------------------------


class TestPrepareBatchReviewNode:
    """prepare_batch_review_node increments batch_num and builds story payload."""

    def test_first_batch_increments_batch_num_to_one(self, tmp_path: Path) -> None:
        # Edge case 5: batch_num initialized to 0 in run_epic_node, bumped
        # to 1 here so the first batch's filenames carry "batch-1".
        state: EpicState = {
            "target_dir": str(tmp_path),
            "epic_num": "6",
            "stories": [
                {"story_id": "1", "story_name": "Login"},
                {"story_id": "2", "story_name": "Logout"},
            ],
            "current_batch_story_ids": ["6-1", "6-2"],
            "batch_num": 0,
        }
        result = prepare_batch_review_node(state)
        assert result["batch_num"] == 1
        assert len(result["batch_review_stories"]) == 2
        assert result["batch_review_stories"][0]["task_id"] == "6-1"
        assert result["batch_review_stories"][0]["story_name"] == "Login"
        assert result["batch_review_stories"][1]["task_id"] == "6-2"

    def test_second_batch_increments_batch_num_to_two(self, tmp_path: Path) -> None:
        state: EpicState = {
            "target_dir": str(tmp_path),
            "epic_num": "6",
            "stories": [
                {"story_id": str(i), "story_name": f"Story {i}"} for i in range(1, 9)
            ],
            "current_batch_story_ids": ["6-5", "6-6", "6-7", "6-8"],
            "batch_num": 1,
        }
        result = prepare_batch_review_node(state)
        assert result["batch_num"] == 2
        assert {s["task_id"] for s in result["batch_review_stories"]} == {
            "6-5", "6-6", "6-7", "6-8",
        }

    def test_pending_task_id_not_in_stories_logged_and_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        state: EpicState = {
            "target_dir": str(tmp_path),
            "epic_num": "6",
            "stories": [{"story_id": "1", "story_name": "Login"}],
            "current_batch_story_ids": ["6-1", "6-99"],  # 6-99 doesn't exist
            "batch_num": 0,
        }
        with caplog.at_level(logging.WARNING, logger="src.intake.epic_graph"):
            result = prepare_batch_review_node(state)
        assert len(result["batch_review_stories"]) == 1
        assert result["batch_review_stories"][0]["task_id"] == "6-1"
        assert any("6-99" in r.message for r in caplog.records)

    def test_resets_per_batch_output_fields(self, tmp_path: Path) -> None:
        # Each new batch starts fresh — leftover state from a prior batch
        # (review file path, fix plan path, ci result) must not leak.
        state: EpicState = {
            "target_dir": str(tmp_path),
            "epic_num": "6",
            "stories": [{"story_id": "1", "story_name": "Login"}],
            "current_batch_story_ids": ["6-1"],
            "batch_num": 1,
        }
        result = prepare_batch_review_node(state)
        assert result["batch_review_file_path"] == ""
        assert result["batch_fix_plan_path"] == ""
        assert result["batch_fixes_needed"] is False
        assert result["batch_test_passed"] is False
        assert result["batch_last_ci_output"] == ""


class TestBatchCommitNode:
    """batch_commit_node resets batch counters so the next batch starts fresh."""

    def test_resets_batch_counter_after_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stub out the actual git commit — we're testing the reset logic.
        monkeypatch.setattr(
            "src.intake.epic_graph._commit_review_fixes",
            lambda state, *, commit_message, audit_label: True,
        )
        state: EpicState = {
            "target_dir": str(tmp_path),
            "epic_num": "6",
            "batch_num": 2,
            "stories_in_current_batch": 4,
            "current_batch_story_ids": ["6-5", "6-6", "6-7", "6-8"],
        }
        result = batch_commit_node(state)
        assert result["stories_in_current_batch"] == 0
        assert result["current_batch_story_ids"] == []
        # batch_num is NOT reset — it monotonically increases for filename
        # disambiguation across batches in the same epic.
        assert "batch_num" not in result


class TestRouteAfterBatchArchitect:
    """route_after_batch_architect routes by batch_fixes_needed (not epic_)."""

    def test_needs_fix(self) -> None:
        assert route_after_batch_architect({"batch_fixes_needed": True}) == "needs_fix"

    def test_no_fix(self) -> None:
        assert route_after_batch_architect({"batch_fixes_needed": False}) == "no_fix"

    def test_does_not_read_epic_fixes_needed(self) -> None:
        # The epic-end and batch architect must not share state — a batch
        # with no fixes must skip batch_fix even if epic_fixes_needed is
        # set to True from a prior epic-end run.
        state = {"batch_fixes_needed": False, "epic_fixes_needed": True}
        assert route_after_batch_architect(state) == "no_fix"


class TestRouteAfterBatchCi:
    """route_after_batch_ci routes by batch_test_passed."""

    def test_pass(self) -> None:
        assert route_after_batch_ci({"batch_test_passed": True}) == "pass"

    def test_halt(self) -> None:
        assert route_after_batch_ci({"batch_test_passed": False}) == "halt"

    def test_default_unset_routes_to_halt(self) -> None:
        # Defensive: an unset batch_test_passed routes to halt (safer
        # than silently committing on missing CI signal).
        assert route_after_batch_ci({}) == "halt"


class TestExtractCiFailureExcerpt:
    """_extract_ci_failure_excerpt anchors on test-runner failure summaries.

    Regression coverage for Epic 7 batch 1 (2026-05-14): the prior
    ``output[-2000:]`` slice surfaced late-flushed React act() warnings
    in the operator-facing halt message while the real Playwright
    Phase 4 failure summary sat ~85 KB earlier in the log.
    """

    def test_empty_returns_empty(self) -> None:
        assert _extract_ci_failure_excerpt("") == ""

    def test_short_output_returned_verbatim(self) -> None:
        out = "short ci log\nno failures\n"
        assert _extract_ci_failure_excerpt(out) == out

    def test_anchors_on_playwright_failed_summary(self) -> None:
        # Playwright-style log: failure summary followed by ~50 KB of
        # late-flushed stderr noise. The naive tail-slice misses the
        # failure; the helper should keep it.
        failure_block = (
            "=== Phase 4: E2E tests (Playwright) ===\n"
            "  1) browse.spec.ts:106 sort dropdown changes URL\n"
            "    Error: expect(page).toHaveURL failed\n"
            "  3 failed\n"
            "    [chromium] browse.spec.ts:103\n"
            "    [chromium] compare.spec.ts:136\n"
            "    [chromium] detail-why-this-recipe-snapshot.spec.ts:11\n"
        )
        noise = "An update to X was not wrapped in act(...).\n" * 2000
        out = failure_block + noise
        excerpt = _extract_ci_failure_excerpt(out)
        assert "3 failed" in excerpt
        assert "browse.spec.ts:106" in excerpt

    def test_anchors_on_pytest_failed_summary(self) -> None:
        out = (
            "x" * 5000
            + "\n=========== 2 failed, 102 passed in 12.34s ===========\n"
            + "y" * 5000
        )
        excerpt = _extract_ci_failure_excerpt(out)
        assert "2 failed" in excerpt

    def test_zero_failed_is_not_anchored(self) -> None:
        # "0 failed" in a passing summary must not be treated as a
        # failure anchor — the regex requires [1-9]\d*.
        out = (
            "real failure earlier: 5 failed\n"
            + "x" * 5000
            + "\nTests  0 failed | 462 passed\n"
        )
        excerpt = _extract_ci_failure_excerpt(out)
        assert "5 failed" in excerpt

    def test_falls_back_to_tail_when_no_anchor(self) -> None:
        # No failure marker → preserve the prior behaviour (tail slice)
        # so unfamiliar test runners still produce a useful excerpt.
        out = "x" * 4000 + "\ndistinctive-tail-marker\n"
        excerpt = _extract_ci_failure_excerpt(out)
        assert "distinctive-tail-marker" in excerpt
        assert len(excerpt) <= 2000

    def test_excerpt_capped_at_max_chars(self) -> None:
        # Leading newline before the failure block ensures the regex's
        # ``\b`` matches at "3" — without it, the surrounding ``x``
        # padding is a word char and no boundary exists.
        failure_block = "\n3 failed test_a test_b test_c\n"
        out = "x" * 5000 + failure_block + "y" * 5000
        excerpt = _extract_ci_failure_excerpt(out, max_chars=500)
        # Allow the truncation prefix/suffix overhead.
        assert len(excerpt) <= 500 + len("[...truncated]\n[...truncated]") + 2
        assert "3 failed" in excerpt

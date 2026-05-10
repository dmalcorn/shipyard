"""Tests for src/intake/rebuild_graph.py — rebuild graph (Level 1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.intake.rebuild_graph import (
    RebuildState,
    _write_rebuild_status,
    advance_epic_node,
    build_rebuild_graph,
    load_backlog_node,
    route_after_epic,
    select_epic_node,
    tag_epic_node,
    write_final_node,
)

SAMPLE_EPICS = """\
## Epic 1: Auth

### Story 1.1: Login
**As a** user, **I want** to log in, **so that** I can access my account.

**Acceptance Criteria:**
- **Given** valid creds **When** I submit **Then** I am authenticated

### Story 1.2: Register
**As a** user, **I want** to register, **so that** I can create an account.

**Acceptance Criteria:**
- **Given** valid details **When** I submit **Then** account is created

## Epic 2: Dashboard

### Story 2.1: View Dashboard
**As a** user, **I want** a dashboard, **so that** I can view data.

**Acceptance Criteria:**
- **Given** I am logged in **When** I navigate to dashboard **Then** I see data
"""


class TestLoadBacklogNode:
    """load_backlog_node parses epics.md into grouped epics."""

    def test_loads_and_groups(self, tmp_path: Path) -> None:
        pa = tmp_path / "_bmad-output" / "planning-artifacts"
        pa.mkdir(parents=True)
        (pa / "epics.md").write_text(SAMPLE_EPICS, encoding="utf-8")
        state: RebuildState = {"target_dir": str(tmp_path)}

        result = load_backlog_node(state)

        assert len(result["epics"]) == 2
        assert result["epics"][0]["epic_num"] == "1"
        assert result["epics"][0]["epic_name"] == "Auth"
        assert len(result["epics"][0]["stories"]) == 2
        assert result["epics"][1]["epic_num"] == "2"
        assert result["epics"][1]["epic_name"] == "Dashboard"
        assert len(result["epics"][1]["stories"]) == 1
        assert result["total_stories"] == 3
        assert result["epic_index"] == 0

    def test_missing_file_returns_failed(self, tmp_path: Path) -> None:
        """Returns failed status when planning-artifacts dir has no epics file."""
        state: RebuildState = {"target_dir": str(tmp_path)}
        result = load_backlog_node(state)
        assert result["pipeline_status"] == "failed"
        assert "epics" in result.get("error", "").lower()


class TestSelectEpicNode:
    """select_epic_node prepares state for current epic."""

    def test_clears_status(self) -> None:
        state: RebuildState = {
            "epics": [{"epic_num": "1", "epic_name": "Auth", "stories": []}],
            "epic_index": 0,
        }
        result = select_epic_node(state)
        assert result["current_epic_status"] == ""
        assert result["current_epic_error"] == ""


class TestAdvanceEpicNode:
    """advance_epic_node increments index."""

    def test_increments(self) -> None:
        result = advance_epic_node({"epic_index": 1})
        assert result["epic_index"] == 2


class TestRouteAfterEpic:
    """route_after_epic routes based on epic status and remaining epics."""

    def test_aborted_continues(self) -> None:
        """A failed epic still advances to the next epic — never halts."""
        state: RebuildState = {
            "current_epic_status": "aborted",
            "epics": [{"epic_num": "1"}, {"epic_num": "2"}],
            "epic_index": 0,
        }
        assert route_after_epic(state) == "more_epics"

    def test_more_epics(self) -> None:
        state: RebuildState = {
            "current_epic_status": "completed",
            "epics": [{"epic_num": "1"}, {"epic_num": "2"}],
            "epic_index": 0,
        }
        assert route_after_epic(state) == "more_epics"

    def test_all_done(self) -> None:
        state: RebuildState = {
            "current_epic_status": "completed",
            "epics": [{"epic_num": "1"}],
            "epic_index": 0,
        }
        assert route_after_epic(state) == "all_done"


class TestTagEpicNode:
    """tag_epic_node creates git tags."""

    def test_creates_tag(self, tmp_path: Path) -> None:
        import subprocess

        target = str(tmp_path)
        subprocess.run(["git", "init"], cwd=target, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=target, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=target, capture_output=True,
        )
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=target, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=target, capture_output=True,
        )

        state: RebuildState = {
            "target_dir": target,
            "epics": [{"epic_num": "1", "epic_name": "Authentication", "stories": []}],
            "epic_index": 0,
            "current_epic_status": "completed",
            "current_epic_failed": 0,
        }
        tag_epic_node(state)

        result = subprocess.run(
            ["git", "tag", "-l"],
            cwd=target,
            capture_output=True,
            text=True,
        )
        assert "epic-1-complete" in result.stdout

    def test_tags_even_when_prior_epics_had_failures(self, tmp_path: Path) -> None:
        """Regression: cumulative stories_failed from earlier epics must not
        block the current epic's tag. Only the current epic's failures should."""
        import subprocess

        target = str(tmp_path)
        subprocess.run(["git", "init"], cwd=target, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=target, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=target, capture_output=True,
        )
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=target, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=target, capture_output=True,
        )

        state: RebuildState = {
            "target_dir": target,
            "epics": [
                {"epic_num": "1", "epic_name": "First", "stories": []},
                {"epic_num": "2", "epic_name": "Second", "stories": []},
            ],
            "epic_index": 1,
            "current_epic_status": "completed",
            "current_epic_failed": 0,
            "stories_failed": 3,  # cumulative from earlier epics
        }
        tag_epic_node(state)

        result = subprocess.run(
            ["git", "tag", "-l"],
            cwd=target,
            capture_output=True,
            text=True,
        )
        assert "epic-2-complete" in result.stdout


class TestWriteRebuildStatus:
    """_write_rebuild_status writes progress file."""

    def test_writes_status(self, tmp_path: Path) -> None:
        results: list[dict[str, Any]] = [
            {
                "epic": "1", "story": "1-1", "story_name": "Login",
                "status": "completed", "interventions": 0,
            },
            {
                "epic": "1", "story": "1-2", "story_name": "Register",
                "status": "failed", "interventions": 1,
            },
        ]
        _write_rebuild_status(
            target_dir=str(tmp_path),
            story_results=results,
            total_stories=3,
            total_interventions=1,
        )
        content = (tmp_path / "rebuild-status.md").read_text(encoding="utf-8")
        assert "Stories completed: 1/3" in content
        assert "Interventions: 1" in content

    def test_final_includes_time(self, tmp_path: Path) -> None:
        _write_rebuild_status(
            target_dir=str(tmp_path),
            story_results=[],
            total_stories=0,
            total_interventions=0,
            elapsed_seconds=120.0,
            is_final=True,
        )
        content = (tmp_path / "rebuild-status.md").read_text(encoding="utf-8")
        assert "Total time: 2.0 minutes" in content


class TestWriteFinalNode:
    """write_final_node writes final status with timing."""

    def test_completed(self, tmp_path: Path) -> None:
        import time

        state: RebuildState = {
            "target_dir": str(tmp_path),
            "all_story_results": [
                {"epic": "1", "story": "1-1", "status": "completed"},
            ],
            "total_stories": 1,
            "total_interventions": 0,
            "start_time": time.time() - 60,
            "stories_completed": 1,
            "stories_failed": 0,
            "current_epic_status": "completed",
        }
        result = write_final_node(state)
        assert result["pipeline_status"] == "completed"

    def test_failed(self, tmp_path: Path) -> None:
        import time

        state: RebuildState = {
            "target_dir": str(tmp_path),
            "all_story_results": [],
            "total_stories": 1,
            "total_interventions": 0,
            "start_time": time.time(),
            "stories_completed": 0,
            "stories_failed": 1,
            "current_epic_status": "completed",
        }
        result = write_final_node(state)
        assert result["pipeline_status"] == "failed"


class TestBuildRebuildGraph:
    """build_rebuild_graph produces a valid graph."""

    def test_graph_compiles(self) -> None:
        graph = build_rebuild_graph()
        compiled = graph.compile()
        assert compiled is not None


class TestPromptStoryReviews:
    """The renamed batch-review toggle prompt at startup (Step 13a).

    The prompt text now says "story-batch" rather than "story-level" but
    the underlying CLI flag (--no-story-reviews) and config key
    (reviews.story_level) keep their backwards-compatible names.
    """

    def test_disabled_state_branch_skips_input(
        self, monkeypatch: Any, capsys: Any,
    ) -> None:
        from src.intake.rebuild_graph import _prompt_story_reviews
        from src.multi_agent.orchestrator import (
            get_batch_reviews_enabled,
            set_batch_reviews_enabled,
        )

        # Pre-disable (simulates --no-story-reviews or factory.yaml).
        original = get_batch_reviews_enabled()
        try:
            set_batch_reviews_enabled(False)
            # If the prompt tried to call input(), this monkeypatch would
            # raise; verifying it's never called confirms the disabled
            # branch short-circuits the input() call.
            def _fail_on_input(_prompt: str = "") -> str:
                raise AssertionError("input() must NOT be called when toggle is off")

            monkeypatch.setattr("builtins.input", _fail_on_input)
            _prompt_story_reviews()
            captured = capsys.readouterr().out
            assert "Story-batch code reviews: DISABLED" in captured
        finally:
            set_batch_reviews_enabled(original)

    def test_enabled_state_yes_keeps_toggle_on(
        self, monkeypatch: Any, capsys: Any,
    ) -> None:
        from src.intake.rebuild_graph import _prompt_story_reviews
        from src.multi_agent.orchestrator import (
            get_batch_reviews_enabled,
            set_batch_reviews_enabled,
        )

        original = get_batch_reviews_enabled()
        try:
            set_batch_reviews_enabled(True)
            monkeypatch.setattr("builtins.input", lambda _prompt="": "")
            _prompt_story_reviews()
            assert get_batch_reviews_enabled() is True
            captured = capsys.readouterr().out
            assert "Story-batch code reviews: ENABLED" in captured
        finally:
            set_batch_reviews_enabled(original)

    def test_enabled_state_n_disables_toggle(
        self, monkeypatch: Any, capsys: Any,
    ) -> None:
        from src.intake.rebuild_graph import _prompt_story_reviews
        from src.multi_agent.orchestrator import (
            get_batch_reviews_enabled,
            set_batch_reviews_enabled,
        )

        original = get_batch_reviews_enabled()
        try:
            set_batch_reviews_enabled(True)
            monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
            _prompt_story_reviews()
            assert get_batch_reviews_enabled() is False
            captured = capsys.readouterr().out
            assert "Story-batch code reviews: DISABLED" in captured
            assert "epic-end review still active" in captured
        finally:
            set_batch_reviews_enabled(original)

"""Tests for src/intake/rebuild.py — autonomous rebuild loop."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from src.intake.intervention_log import InterventionLogger
from src.intake.rebuild import (
    _detect_auto_recovery,
    _git_tag_epic,
    _group_by_epic,
    _init_target_project,
    _write_rebuild_status,
    run_rebuild,
)

SAMPLE_EPICS = """\
## Epic 1: Auth

### Story 1.1: Login
**As a** user, **I want** to log in, **so that** I can access my account.

**Acceptance Criteria:**
- **Given** valid creds **When** I submit **Then** I am authenticated

**Technical Notes:**
- Use bcrypt

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


class TestRunRebuild:
    """run_rebuild() iterates over backlog and invokes orchestrator."""

    @patch("src.intake.rebuild._run_story_pipeline")
    @patch("src.intake.rebuild._git_tag_epic")
    @patch("src.intake.rebuild._init_target_project")
    def test_runs_all_stories(
        self,
        mock_init: MagicMock,
        mock_tag: MagicMock,
        mock_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Invokes pipeline for each story in the backlog."""
        (tmp_path / "epics.md").write_text(SAMPLE_EPICS, encoding="utf-8")
        mock_pipeline.return_value = {"pipeline_status": "completed"}

        result = run_rebuild(
            target_dir=str(tmp_path),
            session_id="test-session",
        )

        assert result["total_stories"] == 3
        assert result["stories_completed"] == 3
        assert result["stories_failed"] == 0
        assert mock_pipeline.call_count == 3

    @patch("src.intake.rebuild._run_story_pipeline")
    @patch("src.intake.rebuild._git_tag_epic")
    @patch("src.intake.rebuild._init_target_project")
    def test_tracks_failures(
        self,
        mock_init: MagicMock,
        mock_tag: MagicMock,
        mock_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Counts failed stories correctly."""
        (tmp_path / "epics.md").write_text(SAMPLE_EPICS, encoding="utf-8")
        mock_pipeline.side_effect = [
            {"pipeline_status": "completed"},
            {"pipeline_status": "failed", "error": "test failure"},
            {"pipeline_status": "completed"},
        ]

        result = run_rebuild(
            target_dir=str(tmp_path),
            session_id="test-session",
        )

        assert result["stories_completed"] == 2
        assert result["stories_failed"] == 1

    @patch("src.intake.rebuild._run_story_pipeline")
    @patch("src.intake.rebuild._git_tag_epic")
    @patch("src.intake.rebuild._init_target_project")
    def test_intervention_callback(
        self,
        mock_init: MagicMock,
        mock_tag: MagicMock,
        mock_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Calls intervention callback on failure and retries."""
        (tmp_path / "epics.md").write_text(SAMPLE_EPICS, encoding="utf-8")
        # First story fails, retry succeeds. Others pass.
        mock_pipeline.side_effect = [
            {"pipeline_status": "failed", "error": "test broke"},
            {"pipeline_status": "completed"},  # retry
            {"pipeline_status": "completed"},
            {"pipeline_status": "completed"},
        ]

        intervention_cb = MagicMock(return_value="fix the test")

        result = run_rebuild(
            target_dir=str(tmp_path),
            session_id="test-session",
            on_intervention=intervention_cb,
        )

        assert result["interventions"] == 1
        assert result["stories_completed"] == 3
        intervention_cb.assert_called_once()

    @patch("src.intake.rebuild._run_story_pipeline")
    @patch("src.intake.rebuild._git_tag_epic")
    @patch("src.intake.rebuild._init_target_project")
    def test_writes_rebuild_status(
        self,
        mock_init: MagicMock,
        mock_tag: MagicMock,
        mock_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Updates rebuild-status.md after each story."""
        (tmp_path / "epics.md").write_text(SAMPLE_EPICS, encoding="utf-8")
        mock_pipeline.return_value = {"pipeline_status": "completed"}

        run_rebuild(target_dir=str(tmp_path), session_id="test-session")

        status_path = tmp_path / "rebuild-status.md"
        assert status_path.exists()
        content = status_path.read_text(encoding="utf-8")
        assert "Stories completed: 3/3" in content
        assert "Total time:" in content  # Final summary

    @patch("src.intake.rebuild._run_story_pipeline")
    @patch("src.intake.rebuild._git_tag_epic")
    @patch("src.intake.rebuild._init_target_project")
    def test_tags_epic_completion(
        self,
        mock_init: MagicMock,
        mock_tag: MagicMock,
        mock_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Tags git after each epic completes."""
        (tmp_path / "epics.md").write_text(SAMPLE_EPICS, encoding="utf-8")
        mock_pipeline.return_value = {"pipeline_status": "completed"}

        run_rebuild(target_dir=str(tmp_path), session_id="test-session")

        assert mock_tag.call_count == 2  # 2 epics

    def test_empty_backlog(self, tmp_path: Path) -> None:
        """Returns zeroed stats for empty backlog."""
        (tmp_path / "epics.md").write_text("", encoding="utf-8")

        result = run_rebuild(target_dir=str(tmp_path), session_id="test-session")

        assert result["total_stories"] == 0
        assert result["stories_completed"] == 0

    def test_missing_backlog_file(self, tmp_path: Path) -> None:
        """Returns error when epics.md is missing, without raising."""
        result = run_rebuild(target_dir=str(tmp_path), session_id="test-session")
        assert result["total_stories"] == 0
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestInitTargetProject:
    """_init_target_project() creates git repo and scaffold."""

    def test_creates_git_repo(self, tmp_path: Path) -> None:
        """Initializes a git repository in the target directory."""
        target = str(tmp_path / "project")
        _init_target_project(target)
        assert (tmp_path / "project" / ".git").exists()

    def test_creates_readme(self, tmp_path: Path) -> None:
        """Creates README.md scaffold."""
        target = str(tmp_path / "project")
        _init_target_project(target)
        readme = tmp_path / "project" / "README.md"
        assert readme.exists()
        assert "Shipyard" in readme.read_text(encoding="utf-8")

    def test_creates_initial_commit(self, tmp_path: Path) -> None:
        """Creates an initial git commit."""
        import subprocess

        target = str(tmp_path / "project")
        _init_target_project(target)
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=target,
            capture_output=True,
            text=True,
        )
        assert "initial project scaffold" in result.stdout

    def test_idempotent_on_existing_repo(self, tmp_path: Path) -> None:
        """Does not reinitialize if .git already exists."""
        import subprocess

        target = str(tmp_path / "project")
        os.makedirs(target, exist_ok=True)
        subprocess.run(["git", "init"], cwd=target, capture_output=True)
        (Path(target) / "existing.txt").write_text("existing", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=target, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "existing commit"],
            cwd=target,
            capture_output=True,
        )

        _init_target_project(target)

        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=target,
            capture_output=True,
            text=True,
        )
        # Should still have the existing commit, not overwritten
        assert "existing commit" in result.stdout


class TestGitTagEpic:
    """_git_tag_epic() creates a git tag in the target directory."""

    def test_creates_tag(self, tmp_path: Path) -> None:
        """Creates expected git tag."""
        import subprocess

        target = str(tmp_path)
        subprocess.run(["git", "init"], cwd=target, capture_output=True)
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=target, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=target, capture_output=True)

        _git_tag_epic(target, "Authentication")

        result = subprocess.run(
            ["git", "tag", "-l"],
            cwd=target,
            capture_output=True,
            text=True,
        )
        assert "epic-authentication-complete" in result.stdout


class TestGroupByEpic:
    """_group_by_epic() groups backlog entries by epic."""

    def test_groups_correctly(self) -> None:
        """Groups entries maintaining epic order."""
        backlog: list[dict[str, Any]] = [
            {"epic": "Auth", "story": "Login"},
            {"epic": "Auth", "story": "Register"},
            {"epic": "Dashboard", "story": "View"},
        ]
        result = _group_by_epic(backlog)
        assert len(result) == 2
        assert result[0][0] == "Auth"
        assert len(result[0][1]) == 2
        assert result[1][0] == "Dashboard"

    def test_empty_backlog(self) -> None:
        """Returns empty list for empty backlog."""
        assert _group_by_epic([]) == []

    def test_non_contiguous_epics(self) -> None:
        """Groups non-contiguous entries for the same epic into one group."""
        backlog: list[dict[str, Any]] = [
            {"epic": "Auth", "story": "Login"},
            {"epic": "Dashboard", "story": "View"},
            {"epic": "Auth", "story": "Register"},
        ]
        result = _group_by_epic(backlog)
        assert len(result) == 2
        auth_group = [g for g in result if g[0] == "Auth"]
        assert len(auth_group) == 1
        assert len(auth_group[0][1]) == 2


class TestWriteRebuildStatus:
    """_write_rebuild_status() writes progress file."""

    def test_writes_status_file(self, tmp_path: Path) -> None:
        """Creates rebuild-status.md with correct content."""
        results: list[dict[str, Any]] = [
            {"epic": "Auth", "story": "Login", "status": "completed", "interventions": 0},
            {"epic": "Auth", "story": "Register", "status": "failed", "interventions": 1},
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
        assert "intervention #1" in content

    def test_final_includes_time(self, tmp_path: Path) -> None:
        """Final status includes total time."""
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


class TestDetectAutoRecovery:
    """_detect_auto_recovery() logs auto-recoveries from retry counts."""

    def test_test_cycle_triggers_recovery(self, tmp_path: Path) -> None:
        """test_cycle_count > 1 triggers log_auto_recovery."""
        il = InterventionLogger(log_path=str(tmp_path / "log.md"))
        result: dict[str, Any] = {"test_cycle_count": 3, "ci_cycle_count": 0, "edit_retry_count": 0}
        _detect_auto_recovery(result, il, "Epic 1", "Story 1.1")
        assert il.get_summary()["total_auto_recoveries"] == 1

    def test_no_recovery_when_counts_low(self, tmp_path: Path) -> None:
        """Counts <= 1 do not trigger auto-recovery logging."""
        il = InterventionLogger(log_path=str(tmp_path / "log.md"))
        result: dict[str, Any] = {"test_cycle_count": 1, "ci_cycle_count": 0, "edit_retry_count": 0}
        _detect_auto_recovery(result, il, "Epic 1", "Story 1.1")
        assert il.get_summary()["total_auto_recoveries"] == 0

    def test_multiple_cycle_types(self, tmp_path: Path) -> None:
        """Multiple cycle types each trigger independently."""
        il = InterventionLogger(log_path=str(tmp_path / "log.md"))
        result: dict[str, Any] = {"test_cycle_count": 2, "ci_cycle_count": 3, "edit_retry_count": 2}
        _detect_auto_recovery(result, il, "Epic 1", "Story 1.1")
        assert il.get_summary()["total_auto_recoveries"] == 3

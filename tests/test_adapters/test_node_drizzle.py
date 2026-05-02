"""Tests for src.adapters.node_drizzle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.adapters.node_drizzle import NodeDrizzleAdapter


@pytest.fixture
def fake_node_project(tmp_path: Path) -> Path:
    """A directory with package.json + drizzle.config.ts but nothing else."""
    (tmp_path / "package.json").write_text('{"name": "fake"}')
    (tmp_path / "drizzle.config.ts").write_text(
        "export default { schema: './src/lib/db/schema.ts' }",
    )
    return tmp_path


@pytest.fixture
def fake_plain_node(tmp_path: Path) -> Path:
    """A Node project without Drizzle."""
    (tmp_path / "package.json").write_text('{"name": "plain"}')
    return tmp_path


class TestDetect:
    def test_detects_when_package_json_present(self, fake_node_project: Path) -> None:
        adapter = NodeDrizzleAdapter(cwd=str(fake_node_project))
        assert adapter.detect() is True

    def test_returns_false_when_package_json_missing(self, tmp_path: Path) -> None:
        adapter = NodeDrizzleAdapter(cwd=str(tmp_path))
        assert adapter.detect() is False


class TestHasDrizzleConfig:
    def test_true_when_drizzle_config_ts(self, fake_node_project: Path) -> None:
        adapter = NodeDrizzleAdapter(cwd=str(fake_node_project))
        assert adapter._has_drizzle_config() is True

    def test_false_when_only_package_json(self, fake_plain_node: Path) -> None:
        adapter = NodeDrizzleAdapter(cwd=str(fake_plain_node))
        assert adapter._has_drizzle_config() is False


class TestAutogenMigrationSkipReasons:
    """Verify the schema-drift hook is conservative — only fires when
    every precondition is met."""

    def test_skip_when_no_drizzle_config(self, fake_plain_node: Path) -> None:
        adapter = NodeDrizzleAdapter(cwd=str(fake_plain_node))
        ok, _ = adapter.autogen_migration_if_schema_touched(
            "1-1", ["src/lib/db/schema.ts"], False,
        )
        assert ok is True  # treated as a no-op (success)

    def test_skip_when_already_added_migration(self, fake_node_project: Path) -> None:
        adapter = NodeDrizzleAdapter(cwd=str(fake_node_project))
        with patch("src.adapters.node_drizzle._run_bash") as mock_run:
            ok, msg = adapter.autogen_migration_if_schema_touched(
                "1-1", ["src/lib/db/schema.ts"], True,
            )
        # When already_added_migration=True, no subprocess should run
        assert mock_run.call_count == 0
        assert ok is True
        assert "already added" in msg

    def test_skip_when_schema_not_touched(self, fake_node_project: Path) -> None:
        adapter = NodeDrizzleAdapter(cwd=str(fake_node_project))
        with patch("src.adapters.node_drizzle._run_bash") as mock_run:
            ok, _ = adapter.autogen_migration_if_schema_touched(
                "1-1", ["src/lib/auth/login.ts", "package.json"], False,
            )
        assert mock_run.call_count == 0
        assert ok is True

    def test_runs_drizzle_kit_when_schema_touched_no_migration(
        self, fake_node_project: Path,
    ) -> None:
        adapter = NodeDrizzleAdapter(cwd=str(fake_node_project))
        with patch("src.adapters.node_drizzle._run_bash", return_value=(True, "ok")) as mock_run:
            ok, _ = adapter.autogen_migration_if_schema_touched(
                "1-1", ["src/lib/db/schema.ts"], False,
            )
        assert ok is True
        # Confirms drizzle-kit was actually invoked, with the story id in the name
        assert mock_run.call_count == 1
        cmd = mock_run.call_args[0][0]
        assert "drizzle-kit" in " ".join(cmd)
        assert "story_1_1" in " ".join(cmd)


class TestPathScoping:
    """Verify paths are correctly filtered and re-based for adapters
    whose cwd is a subdirectory of the repo root."""

    def test_root_cwd_no_filtering(self, tmp_path: Path) -> None:
        # Make tmp_path look like the repo root by creating .git
        (tmp_path / ".git").mkdir()
        adapter = NodeDrizzleAdapter(cwd=str(tmp_path))
        prefix = adapter._cwd_relative_prefix()
        assert prefix == ""
        scoped = adapter._scope_paths(["src/foo.ts", "package.json"], prefix)
        assert scoped == ["src/foo.ts", "package.json"]

    def test_subdir_cwd_filters_and_rebases(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "frontend").mkdir()
        adapter = NodeDrizzleAdapter(cwd=str(tmp_path / "frontend"))
        prefix = adapter._cwd_relative_prefix()
        assert prefix == "frontend/"
        # backend/foo.py is outside this adapter's cwd — filtered out
        # frontend/src/foo.ts is inside — rebased to "src/foo.ts"
        scoped = adapter._scope_paths(
            ["frontend/src/foo.ts", "backend/models.py", "frontend/package.json"],
            prefix,
        )
        assert scoped == ["src/foo.ts", "package.json"]

"""Tests for src.adapters registry + load_adapters."""

from __future__ import annotations

import os

import pytest

from src.adapters import ADAPTERS, load_adapters
from src.adapters.base import normalize_stacks


class TestNormalizeStacks:
    def test_string_form_promoted(self) -> None:
        assert normalize_stacks(["node_drizzle"]) == [
            {"name": "node_drizzle", "dir": "."},
        ]

    def test_dict_form_passes_through(self) -> None:
        assert normalize_stacks([{"name": "django", "dir": "backend"}]) == [
            {"name": "django", "dir": "backend"},
        ]

    def test_dict_form_dir_defaults_to_root(self) -> None:
        assert normalize_stacks([{"name": "django"}]) == [
            {"name": "django", "dir": "."},
        ]

    def test_mixed_string_and_dict(self) -> None:
        assert normalize_stacks([
            "node_drizzle",
            {"name": "django", "dir": "backend"},
        ]) == [
            {"name": "node_drizzle", "dir": "."},
            {"name": "django", "dir": "backend"},
        ]

    def test_empty_list(self) -> None:
        assert normalize_stacks([]) == []

    def test_dict_missing_name_raises(self) -> None:
        with pytest.raises(ValueError, match="missing 'name'"):
            normalize_stacks([{"dir": "backend"}])

    def test_invalid_entry_type_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a string or dict"):
            normalize_stacks([42])  # type: ignore[list-item]


class TestLoadAdaptersRegistry:
    def test_default_adapters_registered(self) -> None:
        # Don't lock the exact set — just confirm the three we shipped exist.
        assert "node_drizzle" in ADAPTERS
        assert "node" in ADAPTERS
        assert "django" in ADAPTERS

    def test_backward_compat_default(self) -> None:
        """factory.yaml without target.stacks defaults to ['node_drizzle']."""
        adapters = load_adapters("/some/path", {})
        assert len(adapters) == 1
        assert adapters[0].name == "node_drizzle"

    def test_missing_target_stacks_logs_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The fallback to ['node_drizzle'] now logs at WARNING — the silent
        fallback masked real misconfigurations on Django/multi-stack targets."""
        import logging
        with caplog.at_level(logging.WARNING, logger="src.adapters"):
            load_adapters("/some/path", {})
        assert "No 'target.stacks'" in caplog.text
        # Confirm it's a WARNING, not INFO
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("target.stacks" in r.message for r in warnings)

    def test_marker_file_missing_logs_warning(
        self, tmp_path: pytest.TempPathFactory, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Loading django adapter at a cwd without manage.py should warn —
        the operator almost certainly mis-configured target.stacks."""
        import logging
        # tmp_path fixture from pytest itself, not TempPathFactory
        target = tmp_path  # type: ignore[assignment]
        with caplog.at_level(logging.WARNING, logger="src.adapters"):
            adapters = load_adapters(
                str(target),
                {"target": {"stacks": [{"name": "django", "dir": "nonexistent"}]}},
            )
        assert len(adapters) == 1  # adapter still loaded
        assert "marker files were not found" in caplog.text

    def test_marker_file_present_no_warning(
        self, tmp_path: pytest.TempPathFactory, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When marker IS present, no marker-missing warning is logged."""
        import logging
        target = tmp_path  # type: ignore[assignment]
        # Create the django marker
        backend = target / "backend"  # type: ignore[operator]
        backend.mkdir()
        (backend / "manage.py").write_text("# stub", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="src.adapters"):
            adapters = load_adapters(
                str(target),
                {"target": {"stacks": [{"name": "django", "dir": "backend"}]}},
            )
        assert len(adapters) == 1
        assert "marker files were not found" not in caplog.text

    def test_unknown_adapter_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        adapters = load_adapters(
            "/some/path",
            {"target": {"stacks": ["this_adapter_does_not_exist"]}},
        )
        assert adapters == []
        assert "Unknown adapter" in caplog.text

    def test_multi_stack_with_subdirs(self) -> None:
        adapters = load_adapters(
            "/proj",
            {"target": {"stacks": [
                {"name": "django", "dir": "backend"},
                {"name": "node", "dir": "frontend"},
            ]}},
        )
        assert len(adapters) == 2
        names = [a.name for a in adapters]
        assert names == ["django", "node"]
        # cwd is target_dir + dir, normalized
        assert adapters[0].cwd == os.path.normpath(os.path.join("/proj", "backend"))
        assert adapters[1].cwd == os.path.normpath(os.path.join("/proj", "frontend"))

    def test_single_stack_string_form(self) -> None:
        adapters = load_adapters(
            "/proj",
            {"target": {"stacks": ["node_drizzle"]}},
        )
        assert len(adapters) == 1
        assert adapters[0].name == "node_drizzle"
        # When dir is "." the cwd equals target_dir
        assert adapters[0].cwd == os.path.normpath("/proj")

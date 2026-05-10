"""Tests for src/config.py."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from src.config import get_story_batch_size, load_factory_config


class TestGetStoryBatchSize:
    def test_default_when_review_section_missing(self) -> None:
        assert get_story_batch_size({}) == 4

    def test_default_when_review_key_missing(self) -> None:
        assert get_story_batch_size({"review": {}}) == 4

    def test_explicit_value(self) -> None:
        assert get_story_batch_size({"review": {"story_batch_size": 6}}) == 6

    def test_explicit_zero_disables(self) -> None:
        assert get_story_batch_size({"review": {"story_batch_size": 0}}) == 0

    def test_negative_value_clamped_to_zero(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert get_story_batch_size({"review": {"story_batch_size": -3}}) == 0
        assert any("clamping to 0" in r.message for r in caplog.records)

    def test_non_integer_value_uses_fallback(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING):
            value = get_story_batch_size({"review": {"story_batch_size": "abc"}})
        assert value == 4
        assert any("not an integer" in r.message for r in caplog.records)

    def test_review_section_not_a_dict_returns_fallback(self) -> None:
        assert get_story_batch_size({"review": "not a dict"}) == 4

    def test_string_integer_coerces(self) -> None:
        # YAML might emit a string in some configs; int(str) should still work.
        assert get_story_batch_size({"review": {"story_batch_size": "8"}}) == 8

    def test_custom_fallback(self) -> None:
        assert get_story_batch_size({}, fallback=10) == 10

    def test_custom_fallback_used_on_invalid(self) -> None:
        assert (
            get_story_batch_size({"review": {"story_batch_size": object()}}, fallback=2)
            == 2
        )

    def test_loads_factory_yaml_when_config_is_none(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        yaml_path = tmp_path / "factory.yaml"
        yaml_path.write_text(
            yaml.safe_dump({"review": {"story_batch_size": 7}}),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        assert get_story_batch_size() == 7

    def test_no_factory_yaml_returns_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert get_story_batch_size() == 4

    def test_mid_run_value_change_picked_up(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Edge case 9 from the design doc: operator edits factory.yaml
        # mid-run; the next call returns the new value.
        yaml_path = tmp_path / "factory.yaml"
        monkeypatch.chdir(tmp_path)

        yaml_path.write_text(
            yaml.safe_dump({"review": {"story_batch_size": 4}}),
            encoding="utf-8",
        )
        assert get_story_batch_size() == 4

        yaml_path.write_text(
            yaml.safe_dump({"review": {"story_batch_size": 0}}),
            encoding="utf-8",
        )
        assert get_story_batch_size() == 0


class TestLoadFactoryConfigSmoke:
    """Quick coverage for load_factory_config so test_config.py
    isn't single-function. Mirrors the no-file branch."""

    def test_missing_file_returns_empty_dict(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert load_factory_config() == {}

    def test_non_mapping_root_returns_empty_dict(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "factory.yaml"
        path.write_text("just a scalar string\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert load_factory_config() == {}

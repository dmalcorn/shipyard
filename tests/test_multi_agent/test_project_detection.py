"""Tests for project-type detection in multi_agent.orchestrator.

The detector is invoked from both the rebuild preflight (for tool-availability
checks) and CI-script generation. False positives mean wrong tools get
warned about and wrong defaults get picked.

The 2026-05-06 regression: Django/Python architecture.md got classified as
Go because the Go signal list contained the substring "gin" (which matches
"engine", "logging", "originally", "begin", etc. inside common English
words) AND Go was ordered before Python in the signal list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.multi_agent.orchestrator import (
    _detect_project_type,
)


def _write_architecture_md(target_dir: Path, content: str) -> None:
    """Place an architecture.md inside the standard planning-artifacts subdir."""
    pa = target_dir / "_bmad-output" / "planning-artifacts"
    pa.mkdir(parents=True, exist_ok=True)
    (pa / "architecture.md").write_text(content, encoding="utf-8")


class TestMarkerFileDetection:
    """When a marker file is present, it wins regardless of architecture.md."""

    def test_python_via_pyproject(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        assert _detect_project_type(str(tmp_path)) == "python"

    def test_node_via_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        assert _detect_project_type(str(tmp_path)) == "node"

    def test_rust_via_cargo_toml(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("", encoding="utf-8")
        assert _detect_project_type(str(tmp_path)) == "rust"

    def test_go_via_go_mod(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example", encoding="utf-8")
        assert _detect_project_type(str(tmp_path)) == "go"


class TestArchitectureMdFallback:
    """When no marker files exist, infer from architecture.md content."""

    def test_django_architecture_classified_as_python(self, tmp_path: Path) -> None:
        """Regression: Django/Python project must NOT be classified as Go.

        The original bug: the Go signal list contained 'gin', which matches
        as a substring inside 'engine', 'logging', 'beginning' etc. — all
        common in any architecture doc. PawprintRecipes (Django + Next.js)
        was misclassified as Go on 2026-05-06.
        """
        # This content is representative of PawprintRecipes' architecture.md:
        # mentions Django, has the words 'engine'/'logging' that contain 'gin'.
        content = """\
# Architecture

The backend uses Django 6.0.2 with the recipe engine doing structured logging.
Models live under backend/<app>/models.py. Migration ordering matters.

The web frontend is Next.js 15.x with TypeScript. We use pytest for backend
tests and vitest for web tests.
"""
        _write_architecture_md(tmp_path, content)
        assert _detect_project_type(str(tmp_path)) == "python"

    def test_pure_django_classified_as_python(self, tmp_path: Path) -> None:
        _write_architecture_md(tmp_path, "Django + DRF stack with pytest.")
        assert _detect_project_type(str(tmp_path)) == "python"

    def test_pure_fastapi_classified_as_python(self, tmp_path: Path) -> None:
        _write_architecture_md(tmp_path, "FastAPI service. Uses ruff + mypy.")
        assert _detect_project_type(str(tmp_path)) == "python"

    def test_nextjs_classified_as_node(self, tmp_path: Path) -> None:
        _write_architecture_md(
            tmp_path, "Next.js 15 with TypeScript and Playwright."
        )
        assert _detect_project_type(str(tmp_path)) == "node"

    def test_rust_classified_as_rust(self, tmp_path: Path) -> None:
        _write_architecture_md(
            tmp_path, "Rust service using Tokio runtime and Axum framework."
        )
        assert _detect_project_type(str(tmp_path)) == "rust"

    def test_go_classified_as_go(self, tmp_path: Path) -> None:
        _write_architecture_md(
            tmp_path, "Go service. Uses goroutines and the Echo framework."
        )
        assert _detect_project_type(str(tmp_path)) == "go"

    def test_unknown_when_no_signals(self, tmp_path: Path) -> None:
        _write_architecture_md(tmp_path, "A generic architecture document.")
        assert _detect_project_type(str(tmp_path)) == "unknown"

    def test_unknown_when_no_architecture_file(self, tmp_path: Path) -> None:
        # Empty directory → no marker, no architecture.md → "unknown"
        assert _detect_project_type(str(tmp_path)) == "unknown"


class TestNoFalsePositiveSubstrings:
    """Specific regressions for words that previously triggered false matches."""

    @pytest.mark.parametrize(
        "trigger_word",
        [
            "engine",        # contains "gin"
            "logging",       # contains "gin"
            "originally",    # contains "gin"
            "imagine",       # contains "gin"
            "beginning",     # contains "gin"
            "engineering",   # contains "gin"
        ],
    )
    def test_word_containing_gin_does_not_classify_as_go(
        self, tmp_path: Path, trigger_word: str
    ) -> None:
        _write_architecture_md(
            tmp_path, f"This project does {trigger_word} of work."
        )
        assert _detect_project_type(str(tmp_path)) != "go"

    def test_django_models_does_not_classify_as_go(self, tmp_path: Path) -> None:
        """'django models' contains the substring 'go mod' if both present."""
        _write_architecture_md(
            tmp_path, "Django models live in backend/app/models.py."
        )
        assert _detect_project_type(str(tmp_path)) == "python"

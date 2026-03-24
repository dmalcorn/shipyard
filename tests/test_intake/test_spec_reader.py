"""Tests for src/intake/spec_reader.py — project spec ingestion."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.intake.spec_reader import MAX_FILE_CHARS, SUPPORTED_EXTENSIONS, read_project_specs


class TestReadProjectSpecs:
    """read_project_specs() reads and concatenates spec files."""

    def test_reads_markdown_files(self, tmp_path: Path) -> None:
        """Reads .md files and includes file path headers."""
        (tmp_path / "readme.md").write_text("# Hello", encoding="utf-8")
        result = read_project_specs(str(tmp_path))
        assert "## File: readme.md" in result
        assert "# Hello" in result

    def test_reads_multiple_file_types(self, tmp_path: Path) -> None:
        """Reads .md, .txt, .py, .json, .yaml files."""
        (tmp_path / "spec.md").write_text("spec", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("notes", encoding="utf-8")
        (tmp_path / "config.yaml").write_text("key: val", encoding="utf-8")
        (tmp_path / "app.py").write_text("print('hi')", encoding="utf-8")
        (tmp_path / "data.json").write_text("{}", encoding="utf-8")
        result = read_project_specs(str(tmp_path))
        assert "## File: spec.md" in result
        assert "## File: notes.txt" in result
        assert "## File: config.yaml" in result
        assert "## File: app.py" in result
        assert "## File: data.json" in result

    def test_ignores_unsupported_extensions(self, tmp_path: Path) -> None:
        """Skips .png, .exe, and other non-supported files."""
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "spec.md").write_text("spec", encoding="utf-8")
        result = read_project_specs(str(tmp_path))
        assert "image.png" not in result
        assert "spec.md" in result

    def test_reads_subdirectories_recursively(self, tmp_path: Path) -> None:
        """Recursively reads files from subdirectories."""
        sub = tmp_path / "docs" / "api"
        sub.mkdir(parents=True)
        (sub / "endpoints.md").write_text("GET /health", encoding="utf-8")
        result = read_project_specs(str(tmp_path))
        assert "docs" in result
        assert "endpoints.md" in result
        assert "GET /health" in result

    def test_truncates_large_files(self, tmp_path: Path) -> None:
        """Files exceeding MAX_FILE_CHARS are truncated."""
        large_content = "x" * (MAX_FILE_CHARS + 1000)
        (tmp_path / "big.md").write_text(large_content, encoding="utf-8")
        result = read_project_specs(str(tmp_path))
        assert "(truncated," in result
        assert "chars total)" in result

    def test_raises_on_missing_directory(self) -> None:
        """Raises FileNotFoundError for nonexistent directory."""
        with pytest.raises(FileNotFoundError, match="Spec directory not found"):
            read_project_specs("/nonexistent/path/12345")

    def test_raises_on_file_instead_of_directory(self, tmp_path: Path) -> None:
        """Raises NotADirectoryError when given a file path."""
        f = tmp_path / "file.txt"
        f.write_text("hi", encoding="utf-8")
        with pytest.raises(NotADirectoryError, match="Not a directory"):
            read_project_specs(str(f))

    def test_returns_empty_string_for_empty_dir(self, tmp_path: Path) -> None:
        """Returns empty string for directory with no supported files."""
        result = read_project_specs(str(tmp_path))
        assert result == ""

    def test_supported_extensions_includes_yml(self) -> None:
        """Both .yaml and .yml are supported."""
        assert ".yaml" in SUPPORTED_EXTENSIONS
        assert ".yml" in SUPPORTED_EXTENSIONS

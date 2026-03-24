"""Tests for search tools (list_files, search_files)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from langchain_core.tools import BaseTool

from src.tools.search import list_files, search_files


class TestListFiles:
    """Tests for list_files tool."""

    def test_list_matching_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        (tmp_path / "c.txt").write_text("z")
        result = list_files.invoke({"pattern": "*.py", "path": str(tmp_path)})
        assert result.startswith("SUCCESS:")
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_list_no_matches(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x")
        result = list_files.invoke({"pattern": "*.py", "path": str(tmp_path)})
        assert result.startswith("SUCCESS:")
        assert "No files matching" in result

    def test_list_recursive_glob(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.py").write_text("x")
        result = list_files.invoke({"pattern": "**/*.py", "path": str(tmp_path)})
        assert result.startswith("SUCCESS:")
        assert "deep.py" in result

    def test_list_excludes_directories(self, tmp_path: Path) -> None:
        (tmp_path / "real_file.py").write_text("x")
        (tmp_path / "a_directory.py").mkdir()
        result = list_files.invoke({"pattern": "*.py", "path": str(tmp_path)})
        assert result.startswith("SUCCESS:")
        assert "real_file.py" in result
        assert "a_directory.py" not in result

    def test_list_truncates_large_output(self, tmp_path: Path) -> None:
        # Create enough files that full paths exceed 5000 chars total
        # Each full path is ~80+ chars (tmp_path + filename), so 100 files suffices
        for i in range(100):
            name = f"file_{i:04d}_{'a' * 60}.txt"
            (tmp_path / name).write_text("x")
        result = list_files.invoke({"pattern": "*.txt", "path": str(tmp_path)})
        assert result.startswith("SUCCESS:")
        assert "truncated" in result
        assert "chars total" in result

    def test_list_nonexistent_path_returns_no_matches(self) -> None:
        result = list_files.invoke({"pattern": "*.py", "path": "/nonexistent/path/xyz"})
        assert result.startswith("SUCCESS:")
        assert "No files matching" in result

    def test_list_exception_returns_error(self) -> None:
        with patch("src.tools.search.Path.glob", side_effect=OSError("mock error")):
            result = list_files.invoke({"pattern": "*.py", "path": "."})
        assert result.startswith("ERROR:")

    def test_list_files_is_tool(self) -> None:
        assert isinstance(list_files, BaseTool)


class TestSearchFiles:
    """Tests for search_files tool."""

    def test_search_matching_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    return 42\ndef world():\n")
        result = search_files.invoke({"pattern": "def \\w+", "path": str(tmp_path)})
        assert result.startswith("SUCCESS:")
        assert "code.py:1:" in result
        assert "code.py:3:" in result

    def test_search_no_matches(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("hello world\n")
        result = search_files.invoke({"pattern": "zzz_not_here", "path": str(tmp_path)})
        assert result.startswith("SUCCESS:")
        assert "No matches" in result

    def test_search_skips_binary_files(self, tmp_path: Path) -> None:
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")
        result = search_files.invoke({"pattern": ".*", "path": str(tmp_path)})
        assert result.startswith("SUCCESS:")
        assert "binary.bin" not in result

    def test_search_invalid_regex(self) -> None:
        result = search_files.invoke({"pattern": "[invalid", "path": "."})
        assert result.startswith("ERROR:")
        assert "Invalid regex" in result

    def test_search_empty_pattern_returns_error(self) -> None:
        result = search_files.invoke({"pattern": "", "path": "."})
        assert result.startswith("ERROR:")
        assert "Empty search pattern" in result

    def test_search_whitespace_pattern_returns_error(self) -> None:
        result = search_files.invoke({"pattern": "   ", "path": "."})
        assert result.startswith("ERROR:")
        assert "Empty search pattern" in result

    def test_search_truncates_large_output(self, tmp_path: Path) -> None:
        # Write enough matching lines to guarantee >5000 chars output
        f = tmp_path / "big.py"
        lines = [f"line_{i:04d} = 'match_target_string_padded'" for i in range(500)]
        f.write_text("\n".join(lines))
        result = search_files.invoke({"pattern": "match_target", "path": str(tmp_path)})
        assert result.startswith("SUCCESS:")
        assert "truncated" in result
        assert "chars total" in result

    def test_search_exception_returns_error(self) -> None:
        result = search_files.invoke({"pattern": "test", "path": "/nonexistent/path/xyz"})
        assert result.startswith("ERROR:") or "No matches" in result

    def test_search_files_is_tool(self) -> None:
        assert isinstance(search_files, BaseTool)

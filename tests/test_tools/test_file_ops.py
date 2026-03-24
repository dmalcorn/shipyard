"""Tests for file operation tools (read_file, edit_file, write_file)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.tools import BaseTool

from src.tools.file_ops import edit_file, read_file, write_file


@pytest.fixture(autouse=True)
def _sandbox_to_tmp(tmp_path: Path) -> Generator[None]:
    """Patch _PROJECT_ROOT so tools accept tmp_path as a valid sandbox."""
    with patch("src.tools.file_ops._PROJECT_ROOT", tmp_path):
        yield


class TestPathSandbox:
    """Verify path traversal protection (P1)."""

    def test_read_rejects_path_outside_project(self, tmp_path: Path) -> None:
        result = read_file.invoke({"file_path": "/etc/passwd"})
        assert result.startswith("ERROR:")
        assert "outside" in result

    def test_edit_rejects_path_outside_project(self, tmp_path: Path) -> None:
        result = edit_file.invoke(
            {
                "file_path": "/etc/passwd",
                "old_string": "root",
                "new_string": "hacked",
            }
        )
        assert result.startswith("ERROR:")
        assert "outside" in result

    def test_write_rejects_path_outside_project(self, tmp_path: Path) -> None:
        result = write_file.invoke({"file_path": "/tmp/escape.txt", "content": "bad"})
        assert result.startswith("ERROR:")
        assert "outside" in result

    def test_read_rejects_traversal_attack(self, tmp_path: Path) -> None:
        result = read_file.invoke({"file_path": str(tmp_path / ".." / ".." / "etc" / "passwd")})
        assert result.startswith("ERROR:")
        assert "outside" in result


class TestEditEmptyOldString:
    """Verify empty old_string guard (P3)."""

    def test_edit_rejects_empty_old_string(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("content")
        result = edit_file.invoke(
            {
                "file_path": str(f),
                "old_string": "",
                "new_string": "injected",
            }
        )
        assert result.startswith("ERROR:")
        assert "empty" in result.lower()
        assert f.read_text() == "content"


class TestReadFile:
    """Tests for read_file tool."""

    def test_read_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        result = read_file.invoke({"file_path": str(f)})
        assert result.startswith("SUCCESS:")
        assert "hello world" in result

    def test_read_file_not_found(self, tmp_path: Path) -> None:
        result = read_file.invoke({"file_path": str(tmp_path / "nope.txt")})
        assert result.startswith("ERROR:")
        assert "not found" in result.lower()

    def test_read_exactly_5000_chars_not_truncated(self, tmp_path: Path) -> None:
        f = tmp_path / "exact.txt"
        f.write_text("x" * 5000)
        result = read_file.invoke({"file_path": str(f)})
        assert result.startswith("SUCCESS:")
        assert "truncated" not in result

    def test_read_general_exception(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.txt"
        f.write_text("data")
        with patch("builtins.open", side_effect=PermissionError("denied")):
            result = read_file.invoke({"file_path": str(f)})
        assert result.startswith("ERROR:")
        assert "denied" in result

    def test_read_truncates_at_5000_chars(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        content = "x" * 6000
        f.write_text(content)
        result = read_file.invoke({"file_path": str(f)})
        assert result.startswith("SUCCESS:")
        assert "truncated" in result
        assert "6000" in result
        assert len(result.split("SUCCESS: ")[1].split("\n\n(truncated")[0]) == 5000


class TestEditFile:
    """Tests for edit_file tool."""

    def test_edit_single_match(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    return 'hi'\n")
        result = edit_file.invoke(
            {
                "file_path": str(f),
                "old_string": "return 'hi'",
                "new_string": "return 'hello'",
            }
        )
        assert result.startswith("SUCCESS:")
        assert f.read_text() == "def hello():\n    return 'hello'\n"

    def test_edit_no_match(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    pass\n")
        result = edit_file.invoke(
            {
                "file_path": str(f),
                "old_string": "not here",
                "new_string": "replacement",
            }
        )
        assert result.startswith("ERROR:")
        assert "not found" in result
        assert "Re-read" in result

    def test_edit_multiple_matches(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("aaa\naaa\naaa\n")
        result = edit_file.invoke(
            {
                "file_path": str(f),
                "old_string": "aaa",
                "new_string": "bbb",
            }
        )
        assert result.startswith("ERROR:")
        assert "3 times" in result
        assert "context" in result.lower()

    def test_edit_file_not_found(self, tmp_path: Path) -> None:
        result = edit_file.invoke(
            {
                "file_path": str(tmp_path / "nope.txt"),
                "old_string": "x",
                "new_string": "y",
            }
        )
        assert result.startswith("ERROR:")
        assert "not found" in result.lower()
        assert "list_files" in result

    def test_edit_general_exception(self, tmp_path: Path) -> None:
        f = tmp_path / "data.txt"
        f.write_text("hello world")
        with patch("builtins.open", side_effect=PermissionError("read denied")):
            result = edit_file.invoke(
                {
                    "file_path": str(f),
                    "old_string": "hello",
                    "new_string": "goodbye",
                }
            )
        assert result.startswith("ERROR:")
        assert "read denied" in result


class TestWriteFile:
    """Tests for write_file tool."""

    def test_write_new_file(self, tmp_path: Path) -> None:
        f = tmp_path / "out.txt"
        result = write_file.invoke({"file_path": str(f), "content": "hello"})
        assert result.startswith("SUCCESS:")
        assert "5 chars" in result
        assert f.read_text() == "hello"

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        f = tmp_path / "a" / "b" / "c" / "deep.txt"
        result = write_file.invoke({"file_path": str(f), "content": "nested"})
        assert result.startswith("SUCCESS:")
        assert f.read_text() == "nested"

    def test_write_overwrites_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "exist.txt"
        f.write_text("old")
        result = write_file.invoke({"file_path": str(f), "content": "new"})
        assert result.startswith("SUCCESS:")
        assert f.read_text() == "new"

    def test_write_exception_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "fail.txt"
        with patch("builtins.open", side_effect=PermissionError("write denied")):
            result = write_file.invoke({"file_path": str(f), "content": "data"})
        assert result.startswith("ERROR:")
        assert "write denied" in result


class TestToolDecorators:
    """Verify all tools are properly decorated with @tool."""

    def test_read_file_is_tool(self) -> None:
        assert isinstance(read_file, BaseTool)

    def test_edit_file_is_tool(self) -> None:
        assert isinstance(edit_file, BaseTool)

    def test_write_file_is_tool(self) -> None:
        assert isinstance(write_file, BaseTool)

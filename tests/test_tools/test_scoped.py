"""Tests for src/tools/scoped.py — working-directory-scoped tools."""

from __future__ import annotations

from pathlib import Path

from src.tools.scoped import get_scoped_tools


class TestScopedTools:
    """get_scoped_tools() creates tools scoped to a working directory."""

    def test_returns_all_tool_names(self, tmp_path: Path) -> None:
        """Returns dict with all 6 tool names."""
        tools = get_scoped_tools(str(tmp_path))
        assert set(tools.keys()) == {
            "read_file",
            "edit_file",
            "write_file",
            "list_files",
            "search_files",
            "run_command",
        }


class TestScopedReadFile:
    """Scoped read_file operates within the working directory."""

    def test_reads_file_in_scope(self, tmp_path: Path) -> None:
        """Reads a file relative to the working directory."""
        (tmp_path / "hello.txt").write_text("world", encoding="utf-8")
        tools = get_scoped_tools(str(tmp_path))
        result = tools["read_file"].invoke({"file_path": "hello.txt"})
        assert "SUCCESS" in result
        assert "world" in result

    def test_rejects_path_outside_scope(self, tmp_path: Path) -> None:
        """Returns error for paths that escape the scoped directory."""
        tools = get_scoped_tools(str(tmp_path))
        result = tools["read_file"].invoke({"file_path": "../../etc/passwd"})
        assert "ERROR" in result

    def test_handles_missing_file(self, tmp_path: Path) -> None:
        """Returns error for nonexistent file."""
        tools = get_scoped_tools(str(tmp_path))
        result = tools["read_file"].invoke({"file_path": "missing.txt"})
        assert "ERROR" in result
        assert "not found" in result.lower()


class TestScopedWriteFile:
    """Scoped write_file creates files within the working directory."""

    def test_writes_file_in_scope(self, tmp_path: Path) -> None:
        """Creates a file relative to the working directory."""
        tools = get_scoped_tools(str(tmp_path))
        result = tools["write_file"].invoke({"file_path": "output.txt", "content": "hello"})
        assert "SUCCESS" in result
        assert (tmp_path / "output.txt").read_text(encoding="utf-8") == "hello"

    def test_creates_subdirectories(self, tmp_path: Path) -> None:
        """Creates parent directories as needed."""
        tools = get_scoped_tools(str(tmp_path))
        result = tools["write_file"].invoke({"file_path": "sub/dir/file.txt", "content": "nested"})
        assert "SUCCESS" in result
        assert (tmp_path / "sub" / "dir" / "file.txt").exists()

    def test_rejects_path_outside_scope(self, tmp_path: Path) -> None:
        """Returns error for paths that escape the scoped directory."""
        tools = get_scoped_tools(str(tmp_path))
        result = tools["write_file"].invoke({"file_path": "../../escape.txt", "content": "bad"})
        assert "ERROR" in result


class TestScopedEditFile:
    """Scoped edit_file modifies files within the working directory."""

    def test_edits_file_in_scope(self, tmp_path: Path) -> None:
        """Edits a file relative to the working directory."""
        (tmp_path / "code.py").write_text("old_value = 1", encoding="utf-8")
        tools = get_scoped_tools(str(tmp_path))
        result = tools["edit_file"].invoke(
            {
                "file_path": "code.py",
                "old_string": "old_value = 1",
                "new_string": "new_value = 2",
            }
        )
        assert "SUCCESS" in result
        assert (tmp_path / "code.py").read_text(encoding="utf-8") == "new_value = 2"


class TestScopedRunCommand:
    """Scoped run_command executes in the working directory."""

    def test_runs_in_working_dir(self, tmp_path: Path) -> None:
        """Command runs with cwd set to the scoped directory."""
        (tmp_path / "marker.txt").write_text("found", encoding="utf-8")
        tools = get_scoped_tools(str(tmp_path))
        result = tools["run_command"].invoke({"command": "ls marker.txt || dir marker.txt"})
        assert "marker" in result.lower() or "SUCCESS" in result


class TestScopedListFiles:
    """Scoped list_files searches within the working directory."""

    def test_lists_files_in_scope(self, tmp_path: Path) -> None:
        """Lists files relative to the working directory."""
        (tmp_path / "a.py").write_text("", encoding="utf-8")
        (tmp_path / "b.py").write_text("", encoding="utf-8")
        tools = get_scoped_tools(str(tmp_path))
        result = tools["list_files"].invoke({"pattern": "*.py"})
        assert "SUCCESS" in result
        assert "a.py" in result
        assert "b.py" in result

    def test_rejects_path_escape(self, tmp_path: Path) -> None:
        """Returns error for paths that escape the scoped directory."""
        tools = get_scoped_tools(str(tmp_path))
        result = tools["list_files"].invoke({"pattern": "*", "path": str(tmp_path.parent)})
        assert "ERROR" in result


class TestScopedSearchFiles:
    """Scoped search_files searches file contents in scope."""

    def test_searches_content(self, tmp_path: Path) -> None:
        """Finds pattern matches in files within scope."""
        (tmp_path / "code.py").write_text("def hello():\n    pass\n", encoding="utf-8")
        tools = get_scoped_tools(str(tmp_path))
        result = tools["search_files"].invoke({"pattern": "def hello"})
        assert "SUCCESS" in result
        assert "hello" in result

    def test_rejects_path_escape(self, tmp_path: Path) -> None:
        """Returns error for paths that escape the scoped directory."""
        tools = get_scoped_tools(str(tmp_path))
        result = tools["search_files"].invoke({"pattern": "test", "path": str(tmp_path.parent)})
        assert "ERROR" in result

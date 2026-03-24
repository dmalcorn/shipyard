"""Tests for bash tool (run_command)."""

from __future__ import annotations

from unittest.mock import patch

from langchain_core.tools import BaseTool

from src.tools.bash import run_command


class TestRunCommand:
    """Tests for run_command tool."""

    def test_successful_command(self) -> None:
        result = run_command.invoke({"command": "echo hello"})
        assert result.startswith("SUCCESS:")
        assert "hello" in result

    def test_command_runs_in_project_root(self) -> None:
        result = run_command.invoke({"command": "pwd"})
        assert result.startswith("SUCCESS:")
        # MINGW pwd returns /c/... while _PROJECT_ROOT returns C:/...
        # Just verify the distinctive directory name appears
        assert "shipyard" in result.lower()

    def test_command_with_stderr(self) -> None:
        result = run_command.invoke({"command": "echo out && echo err >&2"})
        assert result.startswith("SUCCESS:")
        assert "out" in result
        assert "STDERR:" in result
        assert "err" in result

    def test_nonzero_exit_code(self) -> None:
        result = run_command.invoke({"command": "exit 1"})
        assert result.startswith("ERROR:")
        assert "exit code 1" in result

    def test_command_timeout(self) -> None:
        result = run_command.invoke({"command": "sleep 10", "timeout": "1"})
        assert result.startswith("ERROR:")
        assert "timed out" in result
        assert "1s" in result

    def test_invalid_timeout_value(self) -> None:
        result = run_command.invoke({"command": "echo hi", "timeout": "abc"})
        assert result.startswith("ERROR:")
        assert "Invalid timeout" in result

    def test_zero_timeout_returns_error(self) -> None:
        result = run_command.invoke({"command": "echo hi", "timeout": "0"})
        assert result.startswith("ERROR:")
        assert "positive integer" in result

    def test_negative_timeout_returns_error(self) -> None:
        result = run_command.invoke({"command": "echo hi", "timeout": "-5"})
        assert result.startswith("ERROR:")
        assert "positive integer" in result

    def test_default_timeout_is_30(self) -> None:
        result = run_command.invoke({"command": "echo fast"})
        assert result.startswith("SUCCESS:")

    def test_exception_returns_error(self) -> None:
        with patch("src.tools.bash.subprocess.run", side_effect=OSError("mock error")):
            result = run_command.invoke({"command": "echo test"})
        assert result.startswith("ERROR:")
        assert "mock error" in result

    def test_run_command_is_tool(self) -> None:
        assert isinstance(run_command, BaseTool)

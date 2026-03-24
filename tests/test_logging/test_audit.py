"""Tests for the markdown audit logger."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.audit_log.audit import AuditLogger, _active_loggers, get_logger


class TestSessionLifecycle:
    """Task 1: Session creation and lifecycle management."""

    def test_start_session_creates_file(self, tmp_path: Path) -> None:
        """start_session() creates logs/session-{id}.md."""
        logger = AuditLogger(
            session_id="abc-123",
            task_description="Test task",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()

        log_file = tmp_path / "logs" / "session-abc-123.md"
        assert log_file.exists()

    def test_start_session_writes_header(self, tmp_path: Path) -> None:
        """Header line matches: [Session {id}] {timestamp} — Task: "{description}"."""
        logger = AuditLogger(
            session_id="abc-123",
            task_description="Fix the bug",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()

        content = (tmp_path / "logs" / "session-abc-123.md").read_text(encoding="utf-8")
        assert "[Session abc-123]" in content
        assert 'Task: "Fix the bug"' in content

    def test_start_session_iso8601_timestamp(self, tmp_path: Path) -> None:
        """Timestamp in header is ISO 8601 format."""
        logger = AuditLogger(
            session_id="ts-test",
            task_description="Timestamp check",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()

        content = (tmp_path / "logs" / "session-ts-test.md").read_text(encoding="utf-8")
        # ISO 8601: YYYY-MM-DDTHH:MM:SS
        assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", content)

    def test_start_session_creates_logs_dir(self, tmp_path: Path) -> None:
        """logs/ directory is created if it doesn't exist."""
        logs_dir = tmp_path / "nonexistent" / "logs"
        logger = AuditLogger(
            session_id="dir-test",
            task_description="Dir creation",
            logs_dir=logs_dir,
        )
        logger.start_session()
        assert logs_dir.exists()


class TestAgentEventLogging:
    """Task 2: Agent event logging methods."""

    def test_log_agent_start(self, tmp_path: Path) -> None:
        """log_agent_start appends tree-format agent start line."""
        logger = AuditLogger(
            session_id="agent-test",
            task_description="Agent logging",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_agent_start("dev", "claude-sonnet-4-6")

        content = (tmp_path / "logs" / "session-agent-test.md").read_text(encoding="utf-8")
        assert "├─ [dev - claude-sonnet-4-6] Started" in content

    def test_log_tool_call(self, tmp_path: Path) -> None:
        """log_tool_call appends tree-format tool entry."""
        logger = AuditLogger(
            session_id="tool-test",
            task_description="Tool logging",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_agent_start("dev", "claude-sonnet-4-6")
        logger.log_tool_call("Read", "src/main.py", "SUCCESS")

        content = (tmp_path / "logs" / "session-tool-test.md").read_text(encoding="utf-8")
        assert "│  ├─ Read: src/main.py (SUCCESS)" in content

    def test_log_tool_call_no_file(self, tmp_path: Path) -> None:
        """log_tool_call with no file path omits file."""
        logger = AuditLogger(
            session_id="nf-test",
            task_description="No file",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_agent_start("dev", "claude-sonnet-4-6")
        logger.log_tool_call("Search", None, "SUCCESS")

        content = (tmp_path / "logs" / "session-nf-test.md").read_text(encoding="utf-8")
        assert "│  ├─ Search: (SUCCESS)" in content

    def test_log_agent_done(self, tmp_path: Path) -> None:
        """log_agent_done appends done marker."""
        logger = AuditLogger(
            session_id="done-test",
            task_description="Done logging",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_agent_start("dev", "claude-sonnet-4-6")
        logger.log_agent_done()

        content = (tmp_path / "logs" / "session-done-test.md").read_text(encoding="utf-8")
        assert "│  └─ Done" in content

    def test_log_bash(self, tmp_path: Path) -> None:
        """log_bash appends bash execution entry."""
        logger = AuditLogger(
            session_id="bash-test",
            task_description="Bash logging",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_bash("local_ci.sh", "All checks passed")

        content = (tmp_path / "logs" / "session-bash-test.md").read_text(encoding="utf-8")
        assert "├─ [Bash] local_ci.sh" in content
        assert "│  └─ All checks passed" in content


class TestSessionFinalization:
    """Task 3: Session finalization with summary counts."""

    def test_end_session_summary(self, tmp_path: Path) -> None:
        """end_session writes summary line with correct counts."""
        logger = AuditLogger(
            session_id="fin-test",
            task_description="Finalization",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_agent_start("dev", "claude-sonnet-4-6")
        logger.log_tool_call("Read", "src/main.py", "SUCCESS")
        logger.log_tool_call("Edit", "src/main.py", "SUCCESS")
        logger.log_agent_done()
        logger.log_bash("test.sh", "OK")
        logger.end_session()

        content = (tmp_path / "logs" / "session-fin-test.md").read_text(encoding="utf-8")
        assert "└─ [Session Complete] Total: 1 agents, 1 scripts, 1 files touched" in content

    def test_end_session_multiple_agents(self, tmp_path: Path) -> None:
        """Counts multiple agents correctly."""
        logger = AuditLogger(
            session_id="multi-test",
            task_description="Multi agent",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_agent_start("dev", "claude-sonnet-4-6")
        logger.log_tool_call("Read", "a.py", "SUCCESS")
        logger.log_agent_done()
        logger.log_agent_start("reviewer", "claude-sonnet-4-6")
        logger.log_tool_call("Read", "b.py", "SUCCESS")
        logger.log_agent_done()
        logger.end_session()

        content = (tmp_path / "logs" / "session-multi-test.md").read_text(encoding="utf-8")
        assert "2 agents" in content
        assert "2 files touched" in content

    def test_files_touched_deduplication(self, tmp_path: Path) -> None:
        """Same file touched multiple times counts as 1."""
        logger = AuditLogger(
            session_id="dedup-test",
            task_description="Dedup",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_agent_start("dev", "claude-sonnet-4-6")
        logger.log_tool_call("Read", "src/main.py", "SUCCESS")
        logger.log_tool_call("Edit", "src/main.py", "SUCCESS")
        logger.log_agent_done()
        logger.end_session()

        content = (tmp_path / "logs" / "session-dedup-test.md").read_text(encoding="utf-8")
        assert "1 files touched" in content


class TestTreeFormat:
    """Task 4: Verify tree-style format matches Decision 6."""

    def test_full_session_tree_format(self, tmp_path: Path) -> None:
        """Full session output matches the Decision 6 reference format."""
        logger = AuditLogger(
            session_id="tree-test",
            task_description="Implement feature X",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_agent_start("dev", "claude-sonnet-4-6")
        logger.log_tool_call("Read", "src/main.py", "SUCCESS")
        logger.log_tool_call("Edit", "src/main.py", "SUCCESS")
        logger.log_agent_done()
        logger.log_bash("local_ci.sh", "All checks passed")
        logger.end_session()

        content = (tmp_path / "logs" / "session-tree-test.md").read_text(encoding="utf-8")
        lines = content.strip().split("\n")

        # Header line
        assert lines[0].startswith("[Session tree-test]")
        # Blank separator with │
        assert lines[1] == "│"
        # Agent start
        assert "├─ [dev - claude-sonnet-4-6] Started" in lines[2]
        # Tool calls indented under agent
        assert "│  ├─ Read: src/main.py (SUCCESS)" in lines[3]
        assert "│  ├─ Edit: src/main.py (SUCCESS)" in lines[4]
        # Agent done
        assert "│  └─ Done" in lines[5]
        # Blank separator
        assert lines[6] == "│"
        # Bash
        assert "├─ [Bash] local_ci.sh" in lines[7]
        assert "│  └─ All checks passed" in lines[8]
        # Blank separator
        assert lines[9] == "│"
        # Session complete
        assert lines[10].startswith("└─ [Session Complete]")

    def test_log_is_valid_markdown(self, tmp_path: Path) -> None:
        """Output file is valid markdown (no HTML artifacts, proper encoding)."""
        logger = AuditLogger(
            session_id="md-test",
            task_description="Markdown check",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.log_agent_start("dev", "claude-sonnet-4-6")
        logger.log_agent_done()
        logger.end_session()

        content = (tmp_path / "logs" / "session-md-test.md").read_text(encoding="utf-8")
        # Verify markdown structure
        assert content.startswith("[Session")  # header line
        assert "└─ [Session Complete]" in content  # summary present
        assert "├─" in content  # tree structure present
        # Ensure no HTML was accidentally generated
        assert "<html" not in content.lower()


class TestGetLogger:
    """Tests for get_logger() and _active_loggers lifecycle."""

    def test_get_logger_returns_none_before_start(self, tmp_path: Path) -> None:
        """get_logger returns None before start_session is called."""
        AuditLogger(
            session_id="pre-start",
            task_description="Not started",
            logs_dir=tmp_path / "logs",
        )
        assert get_logger("pre-start") is None

    def test_get_logger_returns_logger_after_start(self, tmp_path: Path) -> None:
        """get_logger returns the logger instance after start_session."""
        logger = AuditLogger(
            session_id="active-sess",
            task_description="Active session",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        try:
            result = get_logger("active-sess")
            assert result is logger
        finally:
            logger.end_session()

    def test_get_logger_returns_none_after_end(self, tmp_path: Path) -> None:
        """get_logger returns None after end_session cleans up."""
        logger = AuditLogger(
            session_id="ended-sess",
            task_description="Ended session",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        logger.end_session()
        assert get_logger("ended-sess") is None

    def test_get_logger_with_unknown_session(self) -> None:
        """get_logger returns None for an unknown session_id."""
        assert get_logger("nonexistent-session-id") is None

    def test_active_loggers_empty_after_end(self, tmp_path: Path) -> None:
        """_active_loggers does not contain session_id after end_session."""
        logger = AuditLogger(
            session_id="cleanup-test",
            task_description="Cleanup test",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        assert "cleanup-test" in _active_loggers
        logger.end_session()
        assert "cleanup-test" not in _active_loggers


class TestSessionGuard:
    """Tests for A-01 (session_id sanitization) and A-04 (start guard)."""

    def test_sanitize_path_traversal(self, tmp_path: Path) -> None:
        """session_id with path traversal characters is sanitized."""
        logger = AuditLogger(
            session_id="../../etc/passwd",
            task_description="Path traversal attempt",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        # Should not contain path separators
        assert ".." not in str(logger._log_path.name)
        assert "/" not in str(logger._log_path.name)
        logger.end_session()

    def test_sanitize_windows_chars(self, tmp_path: Path) -> None:
        """session_id with Windows-invalid characters is sanitized."""
        logger = AuditLogger(
            session_id="foo:bar*baz",
            task_description="Windows chars",
            logs_dir=tmp_path / "logs",
        )
        logger.start_session()
        assert ":" not in str(logger._log_path.name)
        assert "*" not in str(logger._log_path.name)
        logger.end_session()

    def test_sanitize_empty_raises(self) -> None:
        """Empty session_id after sanitization raises ValueError."""
        with pytest.raises(ValueError, match="empty string"):
            AuditLogger(
                session_id="...",
                task_description="All dots",
            )

    def test_log_tool_call_before_start_no_error(self, tmp_path: Path) -> None:
        """Calling log methods before start_session does not raise."""
        logger = AuditLogger(
            session_id="no-start",
            task_description="No start",
            logs_dir=tmp_path / "logs",
        )
        # Should not raise — silently skipped
        logger.log_tool_call("Read", "src/main.py", "SUCCESS")
        logger.log_agent_start("dev", "claude-sonnet-4-6")
        logger.log_agent_done()

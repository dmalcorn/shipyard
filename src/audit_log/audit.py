"""Markdown audit logger for agent sessions.

Creates portable tree-style trace artifacts at logs/session-{id}.md,
matching the Decision 6 format from the architecture doc.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path


def _sanitize_session_id(session_id: str) -> str:
    """Sanitize session_id for safe use in file paths."""
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
    if not sanitized:
        raise ValueError(f"session_id produces empty string after sanitization: {session_id!r}")
    return sanitized


# Module-level session registry — maps session_id to active AuditLogger
_active_loggers: dict[str, AuditLogger] = {}


def get_logger(session_id: str) -> AuditLogger | None:
    """Retrieve the active audit logger for a session, if any."""
    return _active_loggers.get(session_id)


class AuditLogger:
    """Logs agent actions to a markdown file using tree-style formatting.

    Each session produces a single markdown file at logs/session-{session_id}.md
    with a structured trace of agent actions, tool calls, and outcomes.

    Args:
        session_id: Unique session identifier.
        task_description: Human-readable description of the session's task.
        logs_dir: Directory for log files. Defaults to logs/ in the project root.
    """

    def __init__(
        self,
        session_id: str,
        task_description: str,
        logs_dir: Path | None = None,
    ) -> None:
        self._session_id = _sanitize_session_id(session_id)
        self._task_description = task_description
        self._logs_dir = logs_dir or Path("logs")
        self._log_path = self._logs_dir / f"session-{self._session_id}.md"
        self._started = False

        # Counters for session summary
        self._agent_count = 0
        self._script_count = 0
        self._files_touched: set[str] = set()

    def start_session(self) -> None:
        """Create the log file with the session header line."""
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        header = f'[Session {self._session_id}] {timestamp} — Task: "{self._task_description}"'
        self._write(header)
        self._started = True
        _active_loggers[self._session_id] = self

    def log_agent_start(self, agent_role: str, model: str) -> None:
        """Append an agent start entry.

        Args:
            agent_role: Role identifier (dev, test, reviewer, architect).
            model: Model name used by the agent.
        """
        self._agent_count += 1
        self._append("│")
        self._append(f"├─ [{agent_role} - {model}] Started")

    def log_tool_call(self, tool_name: str, file_path: str | None, result_prefix: str) -> None:
        """Append a tool call entry under the current agent.

        Args:
            tool_name: Name of the tool invoked.
            file_path: File path operated on, or None if not applicable.
            result_prefix: SUCCESS or ERROR.
        """
        if file_path:
            self._files_touched.add(file_path)
            self._append(f"│  ├─ {tool_name}: {file_path} ({result_prefix})")
        else:
            self._append(f"│  ├─ {tool_name}: ({result_prefix})")

    def log_agent_done(self) -> None:
        """Append the agent completion marker."""
        self._append("│  └─ Done")

    def log_bash(self, script_name: str, result: str) -> None:
        """Append a bash script execution entry.

        Args:
            script_name: Name of the script executed.
            result: Result description string.
        """
        self._script_count += 1
        self._append("│")
        self._append(f"├─ [Bash] {script_name}")
        self._append(f"│  └─ {result}")

    def end_session(self) -> None:
        """Finalize the session with a summary line."""
        files_count = len(self._files_touched)
        self._append("│")
        self._append(
            f"└─ [Session Complete] Total: {self._agent_count} agents, "
            f"{self._script_count} scripts, {files_count} files touched"
        )
        _active_loggers.pop(self._session_id, None)

    def _write(self, text: str) -> None:
        """Write initial content to the log file."""
        self._log_path.write_text(text + "\n", encoding="utf-8")

    def _append(self, text: str) -> None:
        """Append a line to the log file."""
        if not self._started:
            return  # silently skip — session not initialized
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

"""Shell command execution tool for running build, test, and lint operations.

Used by: Dev agent role.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Project root is two levels up from this file (src/tools/bash.py -> project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@tool
def run_command(command: str, timeout: str = "30") -> str:
    """Execute a shell command with a configurable timeout. Used by: Dev."""
    try:
        timeout_secs = int(timeout)
    except ValueError:
        return f"ERROR: Invalid timeout value '{timeout}'. Provide an integer number of seconds."

    if timeout_secs <= 0:
        return "ERROR: Timeout must be a positive integer. Provide seconds > 0."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_secs,
            cwd=str(_PROJECT_ROOT),
        )
        if result.returncode != 0:
            if result.stderr and len(result.stderr) > 500:
                total = len(result.stderr)
                stderr_snippet = f"{result.stderr[:500]} (truncated, {total} chars total)"
            else:
                stderr_snippet = result.stderr or "(no stderr)"
            logger.error("Command failed (exit %d): %s", result.returncode, command)
            return f"ERROR: Command failed with exit code {result.returncode}: {stderr_snippet}"
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR: {result.stderr}"
        total = len(output)
        if total > 5000:
            return f"SUCCESS: {output[:5000]}\n\n(truncated, {total} chars total)"
        return f"SUCCESS: {output}"
    except subprocess.TimeoutExpired:
        logger.error("Command timed out after %ds: %s", timeout_secs, command)
        return (
            f"ERROR: Command timed out after {timeout_secs}s. "
            "Consider increasing timeout or breaking into smaller steps."
        )
    except Exception as e:
        logger.exception("run_command failed: %s", command)
        return f"ERROR: Failed to execute command: {e}. Verify the command syntax."

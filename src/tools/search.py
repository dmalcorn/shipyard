"""Search tools for finding files by pattern and searching file contents.

Used by: Dev, Reviewer, and Architect agent roles.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def list_files(pattern: str, path: str = ".") -> str:
    """List files matching a glob pattern. Used by: Dev, Reviewer, Architect."""
    try:
        matches = sorted(str(p) for p in Path(path).glob(pattern) if p.is_file())
        if not matches:
            return f"SUCCESS: No files matching '{pattern}' found in {path}"
        result = "\n".join(matches)
        total = len(result)
        if total > 5000:
            return f"SUCCESS: {result[:5000]}\n\n(truncated, {total} chars total)"
        return f"SUCCESS: {result}"
    except Exception as e:
        logger.exception("list_files failed for pattern '%s' in %s", pattern, path)
        return (
            f"ERROR: Failed to list files with pattern '{pattern}' in {path}: {e}. "
            "Verify the pattern syntax and path exist."
        )


@tool
def search_files(pattern: str, path: str = ".") -> str:
    """Search file contents for a regex pattern. Used by: Dev, Reviewer, Architect."""
    if not pattern.strip():
        return "ERROR: Empty search pattern. Provide a regex pattern to search for."

    try:
        regex = re.compile(pattern)

        matches: list[str] = []
        for root, _dirs, files in os.walk(path):
            for filename in sorted(files):
                file_path = os.path.join(root, filename)
                try:
                    with open(file_path, encoding="utf-8") as f:
                        for line_num, line in enumerate(f, 1):
                            if regex.search(line):
                                matches.append(f"{file_path}:{line_num}: {line.rstrip()}")
                except (UnicodeDecodeError, PermissionError):
                    continue

        if not matches:
            return f"SUCCESS: No matches for '{pattern}' in {path}"
        result = "\n".join(matches)
        total = len(result)
        if total > 5000:
            return f"SUCCESS: {result[:5000]}\n\n(truncated, {total} chars total)"
        return f"SUCCESS: {result}"
    except re.error as e:
        return f"ERROR: Invalid regex pattern '{pattern}': {e}. Fix the regex syntax and retry."
    except Exception as e:
        logger.exception("search_files failed for pattern '%s' in %s", pattern, path)
        return (
            f"ERROR: Failed to search for '{pattern}' in {path}: {e}. "
            "Verify the path exists and is accessible."
        )

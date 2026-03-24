"""File operation tools for reading, editing, and writing files.

Used by: Dev, Reviewer, and Architect agent roles.
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Project root is two levels up from this file (src/tools/file_ops.py -> project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_path(file_path: str) -> Path:
    """Resolve file_path against project root if relative, else resolve absolute."""
    p = Path(file_path)
    if not p.is_absolute():
        return (_PROJECT_ROOT / p).resolve()
    return p.resolve()


def _validate_path(file_path: str) -> Path | str:
    """Validate that file_path resolves within the project root.

    Returns:
        Resolved Path on success, or an ERROR string if the path is invalid.
    """
    try:
        resolved = _resolve_path(file_path)
    except (OSError, ValueError) as e:
        return f"ERROR: Invalid path: {file_path}. {e}"
    if not resolved.is_relative_to(_PROJECT_ROOT):
        logger.warning("Path sandbox violation: %s", file_path)
        return (
            f"ERROR: Path {file_path} resolves outside the project directory. "
            "All file operations must stay within the project root."
        )
    return resolved


@tool
def read_file(file_path: str) -> str:
    """Read the contents of a file at the given path. Used by: Dev, Reviewer, Architect."""
    try:
        resolved = _validate_path(file_path)
        if isinstance(resolved, str):
            return resolved
        with open(resolved, encoding="utf-8") as f:
            content = f.read()
        total = len(content)
        if total > 5000:
            return f"SUCCESS: {content[:5000]}\n\n(truncated, {total} chars total)"
        return f"SUCCESS: {content}"
    except FileNotFoundError:
        return f"ERROR: File not found: {file_path}. Use list_files to discover available files."
    except Exception as e:
        logger.exception("read_file failed for %s", file_path)
        return f"ERROR: Failed to read {file_path}: {e}"


@tool
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace an exact string match in a file. Used by: Dev, Architect."""
    try:
        resolved = _validate_path(file_path)
        if isinstance(resolved, str):
            return resolved
        if not old_string:
            return "ERROR: old_string must not be empty. Provide the exact text to replace."
        if old_string == new_string:
            return "ERROR: old_string and new_string are identical. No edit needed."
        with open(resolved, encoding="utf-8") as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            return (
                f"ERROR: old_string not found in {file_path}. "
                "Re-read the file to get current contents."
            )
        if count > 1:
            return (
                f"ERROR: old_string found {count} times in {file_path}. "
                "Provide more surrounding context to make the match unique."
            )
        new_content = content.replace(old_string, new_string, 1)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"SUCCESS: Edited {file_path}"
    except FileNotFoundError:
        return f"ERROR: File not found: {file_path}. Use list_files to discover available files."
    except Exception as e:
        logger.exception("edit_file failed for %s", file_path)
        return f"ERROR: Failed to edit {file_path}: {e}"


@tool
def write_file(file_path: str, content: str) -> str:
    """Create or overwrite a file with the given content. Used by: Dev, Architect."""
    try:
        resolved = _validate_path(file_path)
        if isinstance(resolved, str):
            return resolved
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return f"SUCCESS: Wrote {len(content)} chars to {file_path}"
    except Exception as e:
        logger.exception("write_file failed for %s", file_path)
        return f"ERROR: Failed to write {file_path}: {e}"

"""Path-restricted tool factories for role-based write permissions.

Creates wrapper tools that enforce write path restrictions per agent role.
Uses the tool factory pattern: create_restricted_write_file(allowed) returns
a @tool-decorated function with the restriction baked in.
"""

from __future__ import annotations

import posixpath

from langchain_core.tools import BaseTool, tool

from src.tools.file_ops import edit_file as base_edit_file
from src.tools.file_ops import write_file as base_write_file

PERMISSION_DENIED_MSG = (
    "ERROR: Permission denied: {role} agents cannot write outside allowed paths. "
    "Write to {allowed} directory only."
)


def is_path_allowed(file_path: str, allowed_prefixes: tuple[str, ...]) -> bool:
    """Check if file_path starts with one of the allowed prefixes."""
    # Normalize to forward slashes and resolve traversal sequences
    normalized = posixpath.normpath(file_path.replace("\\", "/"))
    # Reject any path that escapes project root
    if normalized.startswith("..") or normalized.startswith("/"):
        return False
    # Strip leading ./ that normpath may produce
    if normalized.startswith("./"):
        normalized = normalized[2:]
    # Case-insensitive comparison for Windows compatibility
    norm_lower = normalized.lower()
    for prefix in allowed_prefixes:
        raw_prefix = prefix.replace("\\", "/")
        norm_prefix = raw_prefix.rstrip("/")
        prefix_lower = norm_prefix.lower()
        is_dir_prefix = raw_prefix.endswith("/")
        # Exact file match for non-directory prefixes (e.g., "fix-plan.md")
        if not is_dir_prefix and norm_lower == prefix_lower:
            return True
        # Directory prefix match — must contain a path component after the prefix
        if norm_lower.startswith(prefix_lower + "/"):
            return True
    return False


def _format_allowed(allowed_prefixes: tuple[str, ...]) -> str:
    """Format allowed prefixes for error messages."""
    return ", ".join(p for p in allowed_prefixes)


def create_restricted_write_file(role_name: str, allowed_prefixes: tuple[str, ...]) -> BaseTool:
    """Create a write_file tool restricted to allowed path prefixes.

    Args:
        role_name: Role name for error messages (e.g., "Review").
        allowed_prefixes: Tuple of allowed path prefixes (e.g., ("reviews/",)).

    Returns:
        A @tool-decorated function with write path restrictions.
    """
    allowed_desc = _format_allowed(allowed_prefixes)

    @tool
    def write_file(file_path: str, content: str) -> str:
        """Create or overwrite a file (path-restricted). Used by: Reviewer, Test, Architect."""
        if not is_path_allowed(file_path, allowed_prefixes):
            return PERMISSION_DENIED_MSG.format(role=role_name, allowed=allowed_desc)
        try:
            result: str = base_write_file.invoke({"file_path": file_path, "content": content})
            return result
        except Exception as e:
            return f"ERROR: Failed to write {file_path}: {e}"

    return write_file


def create_restricted_edit_file(role_name: str, allowed_prefixes: tuple[str, ...]) -> BaseTool:
    """Create an edit_file tool restricted to allowed path prefixes.

    Args:
        role_name: Role name for error messages (e.g., "Review").
        allowed_prefixes: Tuple of allowed path prefixes (e.g., ("reviews/",)).

    Returns:
        A @tool-decorated function with edit path restrictions.
    """
    allowed_desc = _format_allowed(allowed_prefixes)

    @tool
    def edit_file(file_path: str, old_string: str, new_string: str) -> str:
        """Replace an exact string match (path-restricted). Used by: Test, Architect."""
        if not is_path_allowed(file_path, allowed_prefixes):
            return PERMISSION_DENIED_MSG.format(role=role_name, allowed=allowed_desc)
        try:
            result: str = base_edit_file.invoke(
                {"file_path": file_path, "old_string": old_string, "new_string": new_string}
            )
            return result
        except Exception as e:
            return f"ERROR: Failed to edit {file_path}: {e}"

    return edit_file

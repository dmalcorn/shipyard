"""Path-restricted tool factories for role-based write permissions.

Creates wrapper tools that enforce write path restrictions per agent role.
Uses the tool factory pattern: create_restricted_write_file(allowed) returns
a @tool-decorated function with the restriction baked in.
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool, tool

from src.tools.file_ops import edit_file as base_edit_file
from src.tools.file_ops import write_file as base_write_file

logger = logging.getLogger(__name__)

PERMISSION_DENIED_MSG = (
    "ERROR: Permission denied: {role} agents cannot edit source files. Write to {allowed} only."
)


def _is_path_allowed(file_path: str, allowed_prefixes: tuple[str, ...]) -> bool:
    """Check if file_path starts with one of the allowed prefixes."""
    # Normalize to forward slashes for consistent matching
    normalized = file_path.replace("\\", "/").lstrip("./")
    for prefix in allowed_prefixes:
        norm_prefix = prefix.replace("\\", "/").rstrip("/")
        # Exact file match (e.g., "fix-plan.md")
        if "/" not in norm_prefix and normalized == norm_prefix:
            return True
        # Directory prefix match (e.g., "reviews/")
        if normalized.startswith(norm_prefix.rstrip("/") + "/") or normalized == norm_prefix:
            return True
    return False


def _format_allowed(allowed_prefixes: tuple[str, ...]) -> str:
    """Format allowed prefixes for error messages."""
    return ", ".join(f"{p}" for p in allowed_prefixes)


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
        """Create or overwrite a file with the given content. Used by: Dev, Architect."""
        if not _is_path_allowed(file_path, allowed_prefixes):
            return PERMISSION_DENIED_MSG.format(role=role_name, allowed=allowed_desc)
        result: str = base_write_file.invoke({"file_path": file_path, "content": content})
        return result

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
        """Replace an exact string match in a file. Used by: Dev, Architect."""
        if not _is_path_allowed(file_path, allowed_prefixes):
            return PERMISSION_DENIED_MSG.format(role=role_name, allowed=allowed_desc)
        result: str = base_edit_file.invoke(
            {"file_path": file_path, "old_string": old_string, "new_string": new_string}
        )
        return result

    return edit_file

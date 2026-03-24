"""Working-directory-scoped tools for rebuild mode.

Creates file and bash tools that operate relative to a specified working
directory instead of the project root. Used when Shipyard rebuilds a
target project to ensure tool calls stay within the target directory.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from langchain_core.tools import BaseTool, tool

logger = logging.getLogger(__name__)


def get_scoped_tools(working_dir: str) -> dict[str, BaseTool]:
    """Create tools scoped to the given working directory.

    Args:
        working_dir: Absolute or relative path to the target working directory.

    Returns:
        Dict mapping tool names to scoped BaseTool instances.
    """
    root = Path(working_dir).resolve()

    def _resolve(file_path: str) -> Path:
        """Resolve file_path relative to the scoped root."""
        p = Path(file_path)
        if not p.is_absolute():
            return (root / p).resolve()
        return p.resolve()

    def _validate(file_path: str) -> Path | str:
        """Validate path stays within the scoped root."""
        try:
            resolved = _resolve(file_path)
        except (OSError, ValueError) as e:
            return f"ERROR: Invalid path: {file_path}. {e}"
        if not resolved.is_relative_to(root):
            return (
                f"ERROR: Path {file_path} resolves outside the target directory {root}. "
                "All file operations must stay within the target project."
            )
        return resolved

    @tool
    def read_file(file_path: str) -> str:
        """Read the contents of a file at the given path. Used by: Dev, Reviewer, Architect."""
        try:
            resolved = _validate(file_path)
            if isinstance(resolved, str):
                return resolved
            with open(resolved, encoding="utf-8") as f:
                content = f.read()
            total = len(content)
            if total > 5000:
                return f"SUCCESS: {content[:5000]}\n\n(truncated, {total} chars total)"
            return f"SUCCESS: {content}"
        except FileNotFoundError:
            return (
                f"ERROR: File not found: {file_path}. Use list_files to discover available files."
            )
        except Exception as e:
            return f"ERROR: Failed to read {file_path}: {e}"

    @tool
    def edit_file(file_path: str, old_string: str, new_string: str) -> str:
        """Replace an exact string match in a file. Used by: Dev, Architect."""
        try:
            resolved = _validate(file_path)
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
            return (
                f"ERROR: File not found: {file_path}. Use list_files to discover available files."
            )
        except Exception as e:
            return f"ERROR: Failed to edit {file_path}: {e}"

    @tool
    def write_file(file_path: str, content: str) -> str:
        """Create or overwrite a file with the given content. Used by: Dev, Architect."""
        try:
            resolved = _validate(file_path)
            if isinstance(resolved, str):
                return resolved
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            return f"SUCCESS: Wrote {len(content)} chars to {file_path}"
        except Exception as e:
            return f"ERROR: Failed to write {file_path}: {e}"

    @tool
    def list_files(pattern: str, path: str = ".") -> str:
        """List files matching a glob pattern. Used by: All roles."""
        try:
            search_root = _validate(path)
            if isinstance(search_root, str):
                return search_root
            if not search_root.exists():
                return f"ERROR: Path not found: {path}"
            matches = sorted(
                str(p.relative_to(root)) for p in search_root.glob(pattern) if p.is_file()
            )
            if not matches:
                return f"SUCCESS: No files matching '{pattern}' in {path}"
            return "SUCCESS: " + "\n".join(matches)
        except Exception as e:
            return f"ERROR: Failed to list files: {e}"

    @tool
    def search_files(pattern: str, path: str = ".") -> str:
        """Search file contents using regex. Used by: All roles."""
        try:
            search_root = _validate(path)
            if isinstance(search_root, str):
                return search_root
            if not search_root.exists():
                return f"ERROR: Path not found: {path}"
            regex = re.compile(pattern)
            results: list[str] = []
            for file_path_obj in sorted(search_root.rglob("*")):
                if not file_path_obj.is_file():
                    continue
                try:
                    text = file_path_obj.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel = file_path_obj.relative_to(root)
                        results.append(f"{rel}:{i}: {line}")
            if not results:
                return f"SUCCESS: No matches for '{pattern}' in {path}"
            output = "\n".join(results)
            if len(output) > 5000:
                return f"SUCCESS: {output[:5000]}\n\n(truncated)"
            return f"SUCCESS: {output}"
        except Exception as e:
            return f"ERROR: Search failed: {e}"

    @tool
    def run_command(command: str, timeout: str = "30") -> str:
        """Execute a shell command in the target project directory. Used by: Dev."""
        try:
            timeout_secs = int(timeout)
        except ValueError:
            return (
                f"ERROR: Invalid timeout value '{timeout}'. Provide an integer number of seconds."
            )
        if timeout_secs <= 0:
            return "ERROR: Timeout must be a positive integer. Provide seconds > 0."
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout_secs,
                cwd=str(root),
            )
            if result.returncode != 0:
                stderr = result.stderr or "(no stderr)"
                if len(stderr) > 500:
                    stderr = f"{stderr[:500]} (truncated, {len(stderr)} chars total)"
                return f"ERROR: Command failed with exit code {result.returncode}: {stderr}"
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR: {result.stderr}"
            if len(output) > 5000:
                return f"SUCCESS: {output[:5000]}\n\n(truncated, {len(output)} chars total)"
            return f"SUCCESS: {output}"
        except subprocess.TimeoutExpired:
            return f"ERROR: Command timed out after {timeout_secs}s."
        except Exception as e:
            return f"ERROR: Failed to execute command: {e}."

    return {
        "read_file": read_file,
        "edit_file": edit_file,
        "write_file": write_file,
        "list_files": list_files,
        "search_files": search_files,
        "run_command": run_command,
    }

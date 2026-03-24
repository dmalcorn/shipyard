"""Project specification reader for the intake pipeline.

Recursively reads documentation files from a target project directory
and produces a concatenated spec string for LLM consumption.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = frozenset({".md", ".txt", ".py", ".json", ".yaml", ".yml"})
MAX_FILE_CHARS = 5000


def read_project_specs(spec_dir: str) -> str:
    """Recursively read all spec files from a directory.

    Reads .md, .txt, .py, .json, .yaml, .yml files and concatenates them
    with clear file path headers. Individual files exceeding MAX_FILE_CHARS
    are truncated per the tool contract.

    Args:
        spec_dir: Path to the directory containing project specs.

    Returns:
        Combined spec text as a single string with file path headers.

    Raises:
        FileNotFoundError: If spec_dir does not exist.
        NotADirectoryError: If spec_dir is not a directory.
    """
    spec_path = Path(spec_dir).resolve()

    if not spec_path.exists():
        raise FileNotFoundError(f"Spec directory not found: {spec_dir}")
    if not spec_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {spec_dir}")

    parts: list[str] = []

    for file_path in sorted(spec_path.rglob("*")):
        if not file_path.is_file() or file_path.is_symlink():
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        relative = file_path.relative_to(spec_path).as_posix()
        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            logger.warning("Skipping unreadable file %s: %s", relative, e)
            continue

        if len(content) > MAX_FILE_CHARS:
            suffix = f"\n\n(truncated, {len(content)} chars total)"
            content = content[: MAX_FILE_CHARS - len(suffix)] + suffix

        parts.append(f"## File: {relative}\n{content}")

    return "\n\n".join(parts)

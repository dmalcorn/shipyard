"""Context injection functions for the 3-layer context system.

Layer 1: Always-present role description + coding standards in system prompt.
Layer 2: Task-specific file contents passed per instruction.
Layer 3: On-demand via Read/Grep/Glob tools (no code needed — tools handle it).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from langchain_core.messages import BaseMessage, HumanMessage

from src.agent.prompts import get_prompt

logger = logging.getLogger(__name__)

CODING_STANDARDS_PATH = str(Path(__file__).resolve().parent.parent.parent / "coding-standards.md")


def _read_file_safe(file_path: str, working_dir: str | None = None) -> str | None:
    """Read a file and return its contents, or None on failure.

    Args:
        file_path: Path to the file to read.
        working_dir: Optional directory to resolve relative paths against.
    """
    resolved = file_path
    if working_dir and not os.path.isabs(file_path):
        resolved = os.path.join(working_dir, file_path)
    try:
        with open(resolved, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.warning("Failed to read context file %s: %s", resolved, e)
        return None


def build_system_prompt(
    role: str,
    context_files: list[str] | None = None,
    working_dir: str | None = None,
) -> str:
    """Build a system prompt with Layer 1 context for the given agent role.

    Assembles the role-specific prompt template and always injects the
    coding standards. Additional context files are appended if provided.

    Args:
        role: Agent role identifier (dev, test, reviewer, architect).
        context_files: Optional list of file paths to include as Layer 1 context.
        working_dir: Optional directory to resolve relative context file paths against.

    Returns:
        Complete system prompt string with role description and injected context.
    """
    parts: list[str] = []

    # Role-specific prompt template
    parts.append(get_prompt(role))

    # Always inject coding standards (Layer 1)
    # Look in target workspace first, then fall back to shipyard project root
    standards = None
    if working_dir:
        workspace_standards = os.path.join(
            working_dir, "_bmad-output", "planning-artifacts", "coding-standards.md"
        )
        standards = _read_file_safe(workspace_standards)
    if not standards:
        standards = _read_file_safe(CODING_STANDARDS_PATH)
    if standards:
        parts.append(f"## Coding Standards\n{standards}")
    else:
        logger.warning("Coding standards not found at %s", CODING_STANDARDS_PATH)

    # Additional Layer 1 context files
    if context_files:
        for file_path in context_files:
            content = _read_file_safe(file_path, working_dir=working_dir)
            if content:
                basename = os.path.basename(file_path)
                parts.append(f"## Context: {basename}\n{content}")
            else:
                parts.append(f"## Context: {file_path}\n(file not available)")

    return "\n\n".join(parts)


def inject_task_context(
    instruction: str,
    context_files: list[str] | None = None,
    working_dir: str | None = None,
) -> list[BaseMessage]:
    """Build Layer 2 task context messages from instruction and context files.

    Reads each context file and prepends its content to the instruction,
    formatted as a HumanMessage suitable for the agent's message list.

    Args:
        instruction: The task instruction text.
        context_files: Optional list of file paths to include as task context.
        working_dir: Optional directory to resolve relative context file paths against.

    Returns:
        A list containing a single HumanMessage with context and instruction.
    """
    parts: list[str] = []

    if context_files:
        for file_path in context_files:
            content = _read_file_safe(file_path, working_dir=working_dir)
            if content:
                basename = os.path.basename(file_path)
                parts.append(f"## Context: {basename}\n{content}")
            else:
                parts.append(f"## Context: {file_path}\n(file not available)")

    parts.append(f"## Instruction\n{instruction}")

    return [HumanMessage(content="\n\n".join(parts))]

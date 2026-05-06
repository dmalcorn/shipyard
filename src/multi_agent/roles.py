"""Agent role definitions, tool subsets, and trace metadata helpers.

Defines AgentRole dataclass and role constants (DEV_ROLE, TEST_ROLE, etc.)
that map each agent to its model ID, tool permissions, and system prompt.
Also provides build_trace_config() for LangSmith observability (Pattern 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_AGENT_ROLES = frozenset({"dev", "test", "reviewer", "architect", "fix_dev"})
VALID_MODEL_IDS = frozenset({"claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"})
VALID_PHASES = frozenset(
    {
        "test",
        "implementation",
        "review",
        "fix",
        "ci",
        "architect",
        "post_fix_test",
        "post_fix_ci",
    }
)


@dataclass(frozen=True)
class AgentRole:
    """Configuration for a single agent role.

    Attributes:
        name: Role identifier (dev, test, reviewer, architect, fix_dev).
        model_id: Anthropic API model alias (e.g. "claude-sonnet-4-6").
        tools: Tuple of tool names this role can use.
        system_prompt_key: Key for get_prompt() in src.agent.prompts.
        write_restrictions: Tuple of allowed write path prefixes. Empty = unrestricted.
    """

    name: str
    model_id: str
    tools: tuple[str, ...] = ()
    system_prompt_key: str = ""
    write_restrictions: tuple[str, ...] = ()


DEV_ROLE = AgentRole(
    name="dev",
    model_id="claude-sonnet-4-6",
    tools=("read_file", "edit_file", "write_file", "list_files", "search_files", "run_command"),
    system_prompt_key="dev",
    write_restrictions=(),  # unrestricted
)

TEST_ROLE = AgentRole(
    name="test",
    model_id="claude-sonnet-4-6",
    tools=("read_file", "write_file", "list_files", "search_files", "run_command"),
    system_prompt_key="test",
    write_restrictions=("tests/",),
)

REVIEWER_ROLE = AgentRole(
    name="reviewer",
    model_id="claude-sonnet-4-6",
    tools=("read_file", "list_files", "search_files", "write_file"),
    system_prompt_key="reviewer",
    write_restrictions=("reviews/",),
)

ARCHITECT_ROLE = AgentRole(
    name="architect",
    model_id="claude-opus-4-6",
    tools=("read_file", "list_files", "search_files", "write_file"),
    system_prompt_key="architect",
    write_restrictions=("reviews/", "fix-plan.md"),
)

FIX_DEV_ROLE = AgentRole(
    name="fix_dev",
    model_id="claude-sonnet-4-6",
    tools=("read_file", "edit_file", "write_file", "list_files", "search_files", "run_command"),
    system_prompt_key="fix_dev",
    write_restrictions=(),  # unrestricted
)

ROLES: dict[str, AgentRole] = {
    "dev": DEV_ROLE,
    "test": TEST_ROLE,
    "reviewer": REVIEWER_ROLE,
    "architect": ARCHITECT_ROLE,
    "fix_dev": FIX_DEV_ROLE,
}


def get_role(name: str) -> AgentRole:
    """Return the AgentRole for the given role name.

    Args:
        name: Role identifier (dev, test, reviewer, architect, fix_dev).

    Returns:
        AgentRole instance.

    Raises:
        ValueError: If the role name is not recognized.
    """
    role = ROLES.get(name)
    if role is None:
        raise ValueError(f"Unknown role: {name!r}. Valid roles: {', '.join(sorted(ROLES))}")
    return role


def build_trace_config(
    session_id: str,
    agent_role: str,
    task_id: str,
    model_id: str,
    phase: str,
    parent_session: str | None = None,
) -> dict[str, Any]:
    """Build a LangGraph config dict with LangSmith trace metadata.

    Args:
        session_id: Unique session identifier, used as thread_id for checkpointing.
        agent_role: One of dev, test, reviewer, architect, fix_dev.
        task_id: Task identifier (e.g. "story-42").
        model_id: Anthropic API model alias (e.g. "claude-sonnet-4-6").
        phase: One of test, implementation, review, fix, ci.
        parent_session: Optional parent session ID for sub-agent linking.

    Returns:
        Config dict with configurable.thread_id and metadata fields.

    Raises:
        ValueError: If agent_role, model_id, or phase is not in the allowed set.
    """
    if agent_role not in VALID_AGENT_ROLES:
        msg = f"agent_role must be one of {sorted(VALID_AGENT_ROLES)}, got {agent_role!r}"
        raise ValueError(msg)
    if model_id not in VALID_MODEL_IDS:
        msg = f"model_id must be one of {sorted(VALID_MODEL_IDS)}, got {model_id!r}"
        raise ValueError(msg)
    if phase not in VALID_PHASES:
        msg = f"phase must be one of {sorted(VALID_PHASES)}, got {phase!r}"
        raise ValueError(msg)

    metadata: dict[str, str] = {
        "agent_role": agent_role,
        "task_id": task_id,
        "model_id": model_id,
        "phase": phase,
    }
    if parent_session:
        metadata["parent_session"] = parent_session

    return {
        "configurable": {"thread_id": session_id},
        "metadata": metadata,
    }

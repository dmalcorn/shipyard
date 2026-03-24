"""Agent role definitions, tool subsets, and trace metadata helpers.

Defines AgentRole dataclass and role constants (DEV_ROLE, TEST_ROLE, etc.)
that map each agent to its model tier, tool permissions, and system prompt.
Also provides build_trace_config() for LangSmith observability (Pattern 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool

VALID_AGENT_ROLES = frozenset({"dev", "test", "reviewer", "architect", "fix_dev"})
VALID_MODEL_TIERS = frozenset({"haiku", "sonnet", "opus"})
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

# Model IDs per tier
MODEL_IDS: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}


@dataclass(frozen=True)
class AgentRole:
    """Configuration for a single agent role.

    Attributes:
        name: Role identifier (dev, test, reviewer, architect, fix_dev).
        model_tier: Model tier key (haiku, sonnet, opus).
        tools: Tuple of tool names this role can use.
        system_prompt_key: Key for get_prompt() in src.agent.prompts.
        write_restrictions: Tuple of allowed write path prefixes. Empty = unrestricted.
    """

    name: str
    model_tier: str
    tools: tuple[str, ...] = ()
    system_prompt_key: str = ""
    write_restrictions: tuple[str, ...] = ()


DEV_ROLE = AgentRole(
    name="dev",
    model_tier="sonnet",
    tools=("read_file", "edit_file", "write_file", "list_files", "search_files", "run_command"),
    system_prompt_key="dev",
    write_restrictions=(),  # unrestricted
)

TEST_ROLE = AgentRole(
    name="test",
    model_tier="sonnet",
    tools=("read_file", "write_file", "list_files", "search_files", "run_command"),
    system_prompt_key="test",
    write_restrictions=("tests/",),
)

REVIEWER_ROLE = AgentRole(
    name="reviewer",
    model_tier="sonnet",
    tools=("read_file", "list_files", "search_files", "write_file"),
    system_prompt_key="reviewer",
    write_restrictions=("reviews/",),
)

ARCHITECT_ROLE = AgentRole(
    name="architect",
    model_tier="opus",
    tools=("read_file", "list_files", "search_files", "write_file"),
    system_prompt_key="architect",
    write_restrictions=("reviews/", "fix-plan.md"),
)

FIX_DEV_ROLE = AgentRole(
    name="fix_dev",
    model_tier="sonnet",
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


def get_tools_for_role(role: str, working_dir: str | None = None) -> list[BaseTool]:
    """Return the correct tool list for the given agent role.

    For roles with write_restrictions, wraps write_file and edit_file with
    path-restricted versions. Unrestricted roles get the base tools directly.

    When working_dir is provided, file and bash tools are wrapped to operate
    relative to that directory instead of the project root.

    Args:
        role: Agent role identifier (dev, test, reviewer, architect, fix_dev).
        working_dir: Optional working directory for tool operations.

    Returns:
        List of BaseTool instances for the role.
    """
    from src.tools import tools_by_name
    from src.tools.restricted import create_restricted_edit_file, create_restricted_write_file

    role_config = get_role(role)

    # If working_dir is set, get working-dir-scoped tools
    if working_dir is not None:
        from src.tools.scoped import get_scoped_tools

        scoped = get_scoped_tools(working_dir)
        result: list[BaseTool] = []
        for tool_name in role_config.tools:
            if tool_name in scoped:
                result.append(scoped[tool_name])
            else:
                result.append(tools_by_name[tool_name])
        return result

    result = []

    for tool_name in role_config.tools:
        if role_config.write_restrictions:
            # Swap write_file/edit_file with restricted versions
            # Use title-case role name for user-facing error messages
            display_name = role_config.name.replace("_", " ").title()
            if tool_name == "write_file":
                result.append(
                    create_restricted_write_file(display_name, role_config.write_restrictions)
                )
                continue
            if tool_name == "edit_file":
                result.append(
                    create_restricted_edit_file(display_name, role_config.write_restrictions)
                )
                continue
        try:
            result.append(tools_by_name[tool_name])
        except KeyError:
            raise ValueError(
                f"Tool {tool_name!r} referenced by role {role!r} not found in registered tools. "
                f"Available: {', '.join(sorted(tools_by_name))}"
            ) from None

    return result


def build_trace_config(
    session_id: str,
    agent_role: str,
    task_id: str,
    model_tier: str,
    phase: str,
    parent_session: str | None = None,
) -> dict[str, Any]:
    """Build a LangGraph config dict with LangSmith trace metadata.

    Args:
        session_id: Unique session identifier, used as thread_id for checkpointing.
        agent_role: One of dev, test, reviewer, architect, fix_dev.
        task_id: Task identifier (e.g. "story-42").
        model_tier: One of haiku, sonnet, opus.
        phase: One of test, implementation, review, fix, ci.
        parent_session: Optional parent session ID for sub-agent linking.

    Returns:
        Config dict with configurable.thread_id and metadata fields.

    Raises:
        ValueError: If agent_role, model_tier, or phase is not in the allowed set.
    """
    if agent_role not in VALID_AGENT_ROLES:
        msg = f"agent_role must be one of {sorted(VALID_AGENT_ROLES)}, got {agent_role!r}"
        raise ValueError(msg)
    if model_tier not in VALID_MODEL_TIERS:
        msg = f"model_tier must be one of {sorted(VALID_MODEL_TIERS)}, got {model_tier!r}"
        raise ValueError(msg)
    if phase not in VALID_PHASES:
        msg = f"phase must be one of {sorted(VALID_PHASES)}, got {phase!r}"
        raise ValueError(msg)

    metadata: dict[str, str] = {
        "agent_role": agent_role,
        "task_id": task_id,
        "model_tier": model_tier,
        "phase": phase,
    }
    if parent_session:
        metadata["parent_session"] = parent_session

    return {
        "configurable": {"thread_id": session_id},
        "metadata": metadata,
    }

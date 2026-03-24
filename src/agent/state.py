"""Agent state schema for the core LangGraph agent loop.

Extends MessagesState with custom fields for task tracking, retry limits,
and multi-agent coordination.
"""

from __future__ import annotations

import operator
from typing import Annotated

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """State schema for the Shipyard agent graph.

    Extends MessagesState (which provides `messages`) with fields for
    task tracking, agent role identification, and file modification tracking.
    """

    task_id: str
    retry_count: int
    current_phase: str  # "test", "implementation", "review", "fix", "ci"
    agent_role: str  # "dev", "test", "reviewer", "architect", "fix_dev"
    files_modified: Annotated[list[str], operator.add]

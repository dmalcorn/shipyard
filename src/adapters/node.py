"""Plain Node adapter — Next.js / React / TypeScript without Drizzle.

For projects where the frontend lives in a Node directory but doesn't
own its own database (typical multi-stack monorepo where a backend
in a sibling directory owns persistence).

Differs from ``node_drizzle`` only by skipping the Drizzle schema-drift
protection — autoformat / lint-fix / install behavior is identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.adapters.node_drizzle import NodeDrizzleAdapter


@dataclass
class NodeAdapter(NodeDrizzleAdapter):
    """Subclasses NodeDrizzle and disables the Drizzle-specific hook."""

    name: str = "node"

    def autogen_migration_if_schema_touched(
        self,
        task_id: str,
        changed_files: list[str],
        already_added_migration: bool,
    ) -> tuple[bool, str]:
        return True, ""


def make(ctx: dict[str, Any]) -> NodeAdapter:
    return NodeAdapter(cwd=ctx["cwd"])

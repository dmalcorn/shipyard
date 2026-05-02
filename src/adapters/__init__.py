"""Stack adapter registry + factory.

Adapters encapsulate stack-specific behavior (autoformat, lint-fix,
schema-drift protection) so the factory's orchestrator stays
stack-agnostic. See ``base.py`` for the protocol every adapter
implements.

Usage from orchestrator code:

    from src.adapters import load_adapters
    adapters = load_adapters(target_dir, factory_config)
    for a in adapters:
        ok, out = a.autoformat()
        ...

Adding a new adapter:
1. Create ``src/adapters/<name>.py`` with a class implementing the
   ``StackAdapter`` protocol from ``base.py`` plus a module-level
   ``make(ctx)`` factory function.
2. Register it in the ``ADAPTERS`` dict below.
3. Operators reference it from ``factory.yaml`` under ``target.stacks``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.adapters.base import AdapterContext, StackAdapter, normalize_stacks
from src.adapters.django import make as make_django
from src.adapters.node import make as make_node
from src.adapters.node_drizzle import make as make_node_drizzle

logger = logging.getLogger(__name__)


# Registry: stack name -> factory callable. Factory takes a context dict
# (at least ``cwd``) and returns a StackAdapter-conforming instance.
ADAPTERS: dict[str, Any] = {
    "node_drizzle": make_node_drizzle,
    "node":         make_node,
    "django":       make_django,
}


def load_adapters(
    target_dir: str,
    config: dict[str, Any],
) -> list[StackAdapter]:
    """Load configured adapters for the given target directory.

    Reads ``config["target"]["stacks"]`` (set by ``factory.yaml``).
    Falls back to ``["node_drizzle"]`` if the key is missing — preserves
    backward compatibility with chat2diagram-era factory.yaml files
    that predate multi-stack support.
    """
    raw_stacks = config.get("target", {}).get("stacks")
    if not raw_stacks:
        logger.info(
            "No 'target.stacks' in factory.yaml — defaulting to ['node_drizzle'] "
            "for backward compatibility. Set 'target.stacks: [<adapter-name>]' "
            "explicitly to silence this message.",
        )
        raw_stacks = ["node_drizzle"]

    normalized = normalize_stacks(raw_stacks)
    adapters: list[StackAdapter] = []
    for entry in normalized:
        name = entry["name"]
        sub = entry["dir"]
        if name not in ADAPTERS:
            logger.error(
                "Unknown adapter %r — known adapters: %s. Skipping this stack.",
                name, sorted(ADAPTERS.keys()),
            )
            continue
        cwd = os.path.normpath(os.path.join(target_dir, sub))
        ctx: dict[str, Any] = {
            "cwd": cwd,
            "target_dir": target_dir,
            "name": name,
        }
        adapter = ADAPTERS[name](ctx)
        adapters.append(adapter)
        logger.info(
            "Loaded adapter %s with cwd=%s",
            name, cwd,
        )
    return adapters


__all__ = [
    "ADAPTERS",
    "AdapterContext",
    "StackAdapter",
    "load_adapters",
    "normalize_stacks",
]

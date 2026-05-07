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
        # Loud — silent fallback to node_drizzle has caused real problems
        # (e.g., Django targets where eslint runs at project root and fails
        # because eslint.config lives in a subdir). Operators should set
        # target.stacks explicitly.
        logger.warning(
            "No 'target.stacks' in factory.yaml — defaulting to ['node_drizzle'] "
            "for backward compatibility. This is almost certainly wrong for any "
            "non-Drizzle target and will cause autoformat/lint to run at the "
            "project root. Set 'target.stacks: [<adapter-name>]' explicitly.",
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

        # Marker check — if the adapter's expected marker file (manage.py for
        # django, package.json for node*) isn't in cwd, the operator has almost
        # certainly mis-configured target.stacks. Lint/format will fail
        # downstream as a "non-blocking" warning that masks the real cause;
        # surface it loudly here instead.
        if not adapter.detect():
            logger.warning(
                "Adapter %r loaded with cwd=%s but its marker files were not "
                "found there — autoformat/lint will run against the wrong "
                "directory. Verify 'target.stacks' in factory.yaml points "
                "this adapter at the right subdir.",
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

"""Thread-safe cost accumulator for rebuild pipeline runs.

Automatically summed by _print_stream_event in bmad_invoke.py
whenever a Claude CLI result event reports total_cost_usd.
Read the running total at any point via get_total_cost().
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_total_cost: float = 0.0
_invocation_count: int = 0


def add_cost(cost_usd: float) -> None:
    """Add a single invocation's cost to the running total."""
    global _total_cost, _invocation_count
    with _lock:
        _total_cost += cost_usd
        _invocation_count += 1


def get_total_cost() -> float:
    """Return the accumulated cost in USD."""
    with _lock:
        return _total_cost


def get_invocation_count() -> int:
    """Return the number of Claude CLI invocations tracked."""
    with _lock:
        return _invocation_count


def reset() -> None:
    """Reset counters. Called at the start of a new run."""
    global _total_cost, _invocation_count
    with _lock:
        _total_cost = 0.0
        _invocation_count = 0

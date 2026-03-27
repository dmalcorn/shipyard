"""Graceful pause flag for the rebuild pipeline.

A shared module-level flag that signal handlers set and graph routing
functions check. When the flag is set, the pipeline finishes the
current story, then exits cleanly with a "paused" status.
"""

from __future__ import annotations

import threading

_pause_lock = threading.Lock()
_pause_requested = False


def request_pause() -> None:
    """Set the pause flag. Called by the signal handler."""
    global _pause_requested
    with _pause_lock:
        _pause_requested = True


def is_pause_requested() -> bool:
    """Check whether a graceful pause has been requested."""
    with _pause_lock:
        return _pause_requested


def reset_pause() -> None:
    """Clear the pause flag. Called at the start of a new run."""
    global _pause_requested
    with _pause_lock:
        _pause_requested = False

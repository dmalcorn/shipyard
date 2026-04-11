"""Graceful pause and force-quit flags for the rebuild pipeline.

A shared module-level flag system that signal handlers set and graph
routing functions check. Supports two levels of shutdown:

  1. First Ctrl+C: pause flag — finish current story, then exit cleanly.
  2. Second Ctrl+C: force-quit flag — kill all subprocesses immediately.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_pause_requested = False
_force_quit_requested = False

# Event that watchdog threads wait on to kill subprocesses
force_quit_event = threading.Event()


def request_pause() -> None:
    """Set the pause flag. Called by the signal handler on first Ctrl+C."""
    global _pause_requested
    with _lock:
        _pause_requested = True


def request_force_quit() -> None:
    """Set the force-quit flag. Called by the signal handler on second Ctrl+C."""
    global _force_quit_requested
    with _lock:
        _force_quit_requested = True
    force_quit_event.set()


def is_pause_requested() -> bool:
    """Check whether a graceful pause has been requested."""
    with _lock:
        return _pause_requested


def is_force_quit_requested() -> bool:
    """Check whether a force-quit has been requested."""
    with _lock:
        return _force_quit_requested


def reset_pause() -> None:
    """Clear all flags. Called at the start of a new run."""
    global _pause_requested, _force_quit_requested
    with _lock:
        _pause_requested = False
        _force_quit_requested = False
    force_quit_event.clear()

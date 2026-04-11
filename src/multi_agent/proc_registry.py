"""Global subprocess registry for reliable cleanup on shutdown.

Tracks all active child processes (Claude CLI, bash commands) so the
signal handler can kill them immediately on force-quit. Uses only
threading primitives — fully cross-platform (Windows, Linux, macOS).
"""

from __future__ import annotations

import logging
import subprocess
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_active: dict[int, subprocess.Popen[str]] = {}


def register(proc: subprocess.Popen[str]) -> None:
    """Add a subprocess to the registry."""
    with _lock:
        _active[proc.pid] = proc


def unregister(proc: subprocess.Popen[str]) -> None:
    """Remove a subprocess from the registry."""
    with _lock:
        _active.pop(proc.pid, None)


def kill_all() -> None:
    """Terminate then kill every registered subprocess.

    Calls terminate() first for a graceful window, then kill() to
    ensure the process is dead. Safe to call multiple times.
    Works on all platforms: terminate/kill use TerminateProcess on
    Windows and SIGTERM/SIGKILL on Unix.
    """
    with _lock:
        procs = list(_active.values())
        _active.clear()

    for proc in procs:
        try:
            proc.terminate()
        except OSError:
            pass

    # Give processes a brief moment to respond to terminate
    for proc in procs:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except OSError:
                pass
        except OSError:
            pass


def active_count() -> int:
    """Return the number of currently registered subprocesses."""
    with _lock:
        return len(_active)

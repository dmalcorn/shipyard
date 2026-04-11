"""Local pipeline push hook for streaming log events to the public dashboard.

When SHIPYARD_RELAY_URL is set, log events from the local pipeline are
batched and POSTed to the Railway-hosted server for public display.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Read at call time via _get_relay_config(), not import time, so that
# load_dotenv() in main.py has a chance to populate the environment first.
BATCH_INTERVAL_SECONDS = 1.5
MAX_BATCH_SIZE = 50


def _get_relay_config() -> tuple[str, str]:
    """Return (RELAY_URL, RELAY_KEY) from the environment at call time."""
    return (
        os.environ.get("SHIPYARD_RELAY_URL", ""),
        os.environ.get("SHIPYARD_RELAY_KEY", ""),
    )


# ---------------------------------------------------------------------------
# Relay client
# ---------------------------------------------------------------------------


class WebRelay:
    """Buffers log events and pushes them to the public dashboard server.

    Args:
        relay_url: Base URL of the public server (e.g. https://shipyard-xxx.up.railway.app).
        relay_key: Shared secret for authenticating push requests.
        session_id: Pipeline session ID.
        pipeline_type: Type of pipeline being run.
    """

    def __init__(
        self,
        relay_url: str,
        relay_key: str,
        session_id: str,
        pipeline_type: str = "rebuild",
    ) -> None:
        self._url = relay_url.rstrip("/")
        self._key = relay_key
        self._session_id = session_id
        self._pipeline_type = pipeline_type
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Register the session on the server and start the flush thread."""
        self._post("/api/sessions/start", {
            "session_id": self._session_id,
            "pipeline_type": self._pipeline_type,
        })
        self._running = True
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()
        atexit.register(self.stop)
        logger.info("WebRelay started for session %s -> %s", self._session_id, self._url)

    def stop(self, status: str = "completed") -> None:
        """Flush remaining events and mark the session as ended."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._flush()
        self._post("/api/sessions/end", {
            "session_id": self._session_id,
            "status": status,
        })
        logger.info("WebRelay stopped for session %s (status=%s)", self._session_id, status)

    def push(
        self, text: str, event_type: str = "log", metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a log event to the buffer."""
        with self._lock:
            self._buffer.append({
                "event_type": event_type,
                "text": text,
                "metadata": metadata or {},
            })

    def push_stage(self, stage: str, metadata: dict[str, Any] | None = None) -> None:
        """Push a stage-change event."""
        self.push(stage, event_type="stage", metadata=metadata or {})

    # -- internal --

    def _flush_loop(self) -> None:
        """Background thread: flush buffer at regular intervals."""
        while self._running:
            time.sleep(BATCH_INTERVAL_SECONDS)
            self._flush()

    def _flush(self) -> None:
        """Send buffered events to the server."""
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:MAX_BATCH_SIZE]
            self._buffer = self._buffer[MAX_BATCH_SIZE:]

        self._post("/api/events", {
            "session_id": self._session_id,
            "events": batch,
        })

    def _post(self, path: str, payload: dict[str, Any]) -> None:
        """HTTP POST to the relay server."""
        url = self._url + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except urllib.error.URLError as e:
            logger.warning("WebRelay POST %s failed: %s", path, e)
        except Exception as e:
            logger.warning("WebRelay POST %s error: %s", path, e)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_relay: WebRelay | None = None


def get_relay() -> WebRelay | None:
    """Return the active relay instance, or None if relay is not configured."""
    return _relay


def _close_stale_sessions(relay_url: str, relay_key: str) -> None:
    """Close any sessions stuck in 'running' status from prior crashed runs.

    Without this, the dashboard locks onto a dead session and ignores
    the new one. Safe to call every startup — it's a no-op when there
    are no stale sessions.
    """
    try:
        req = urllib.request.Request(
            relay_url.rstrip("/") + "/api/sessions", method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            sessions = json.loads(resp.read().decode())
        stale = [s for s in sessions if s.get("status") == "running"]
        for s in stale:
            data = json.dumps({
                "session_id": s["session_id"], "status": "completed",
            }).encode("utf-8")
            end_req = urllib.request.Request(
                relay_url.rstrip("/") + "/api/sessions/end",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {relay_key}",
                },
                method="POST",
            )
            urllib.request.urlopen(end_req, timeout=5).read()
            logger.info("Closed stale relay session: %s", s["session_id"][:20])
    except Exception as e:
        logger.debug("Stale session cleanup skipped: %s", e)


def init_relay(session_id: str, pipeline_type: str = "rebuild") -> WebRelay | None:
    """Initialize and start the relay if SHIPYARD_RELAY_URL is set.

    Args:
        session_id: Pipeline session ID.
        pipeline_type: Type of pipeline being run.

    Returns:
        The WebRelay instance, or None if not configured.
    """
    global _relay
    relay_url, relay_key = _get_relay_config()
    if not relay_url or not relay_key:
        logger.info("WebRelay not configured (SHIPYARD_RELAY_URL / SHIPYARD_RELAY_KEY not set)")
        return None

    # Clean up sessions left in 'running' state by prior crashed runs
    _close_stale_sessions(relay_url, relay_key)

    _relay = WebRelay(
        relay_url=relay_url,
        relay_key=relay_key,
        session_id=session_id,
        pipeline_type=pipeline_type,
    )
    _relay.start()
    return _relay


def stop_relay(status: str = "completed") -> None:
    """Stop the active relay and flush remaining events."""
    global _relay
    if _relay:
        _relay.stop(status=status)
        _relay = None

"""Postgres-backed log storage for the public monitoring dashboard.

Stores pipeline log events pushed from the local rebuild runner and
serves them to browser clients via the FastAPI endpoints in main.py.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at     TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running',
    pipeline_type TEXT NOT NULL DEFAULT 'rebuild'
);

CREATE TABLE IF NOT EXISTS log_events (
    id           SERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type   TEXT NOT NULL,
    text         TEXT NOT NULL DEFAULT '',
    metadata     JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_log_events_session
    ON log_events(session_id, id);
"""

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _get_database_url() -> str:
    """Read DATABASE_URL from environment."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return url


def get_connection() -> PgConnection:
    """Open a new Postgres connection from DATABASE_URL."""
    return psycopg2.connect(_get_database_url())


def ensure_schema() -> None:
    """Create tables and indexes if they don't exist."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session operations
# ---------------------------------------------------------------------------


@dataclass
class SessionInfo:
    """Summary of a pipeline session."""

    session_id: str
    started_at: str
    ended_at: str | None
    status: str
    pipeline_type: str
    event_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "pipeline_type": self.pipeline_type,
            "event_count": self.event_count,
        }


def create_session(session_id: str, pipeline_type: str = "rebuild") -> None:
    """Register a new pipeline session."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO sessions (session_id, pipeline_type)
                   VALUES (%s, %s)
                   ON CONFLICT (session_id) DO UPDATE
                   SET status = 'running', started_at = NOW(), ended_at = NULL""",
                (session_id, pipeline_type),
            )
        conn.commit()
    finally:
        conn.close()


def end_session(session_id: str, status: str = "completed") -> None:
    """Mark a session as finished."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE sessions SET status = %s, ended_at = NOW()
                   WHERE session_id = %s""",
                (status, session_id),
            )
        conn.commit()
    finally:
        conn.close()


def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    """List recent sessions, newest first."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT s.session_id, s.started_at, s.ended_at, s.status,
                          s.pipeline_type, COUNT(e.id) AS event_count
                   FROM sessions s
                   LEFT JOIN log_events e ON e.session_id = s.session_id
                   GROUP BY s.session_id
                   ORDER BY s.started_at DESC
                   LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
        return [
            {
                "session_id": r["session_id"],
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "ended_at": r["ended_at"].isoformat() if r["ended_at"] else None,
                "status": r["status"],
                "pipeline_type": r["pipeline_type"],
                "event_count": r["event_count"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_active_session() -> dict[str, Any] | None:
    """Return the currently running session, if any."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT session_id, started_at, status, pipeline_type
                   FROM sessions
                   WHERE status = 'running'
                   ORDER BY started_at DESC
                   LIMIT 1"""
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "session_id": row["session_id"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "status": row["status"],
            "pipeline_type": row["pipeline_type"],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Event operations
# ---------------------------------------------------------------------------


def store_events(session_id: str, events: list[dict[str, Any]]) -> int:
    """Bulk-insert log events for a session.

    Args:
        session_id: The session these events belong to.
        events: List of dicts with keys: event_type, text, metadata (optional).

    Returns:
        Number of events inserted.
    """
    if not events:
        return 0
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            values = []
            for ev in events:
                values.append((
                    session_id,
                    ev.get("event_type", "log"),
                    ev.get("text", ""),
                    json.dumps(ev.get("metadata", {})),
                ))
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO log_events (session_id, event_type, text, metadata)
                   VALUES %s""",
                values,
                template="(%s, %s, %s, %s)",
            )
        conn.commit()
        return len(values)
    finally:
        conn.close()


def get_session_logs(session_id: str, after_id: int = 0) -> list[dict[str, Any]]:
    """Fetch log events for a session, optionally after a given ID.

    Args:
        session_id: Session to query.
        after_id: Only return events with id > after_id (for live polling).

    Returns:
        List of event dicts ordered by id.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, event_type, text, metadata, created_at
                   FROM log_events
                   WHERE session_id = %s AND id > %s
                   ORDER BY id ASC""",
                (session_id, after_id),
            )
            rows = cur.fetchall()
        return [
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "text": r["text"],
                "metadata": r["metadata"] if isinstance(r["metadata"], dict) else {},
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_latest_event_id(session_id: str) -> int:
    """Return the highest event ID for a session, or 0 if none."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(id), 0) FROM log_events WHERE session_id = %s",
                (session_id,),
            )
            result = cur.fetchone()
        return result[0] if result else 0
    finally:
        conn.close()

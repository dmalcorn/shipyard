# Shipyard API Reference

HTTP endpoints exposed by the Shipyard FastAPI server. Verified against [src/main.py](../src/main.py) as of the most recent commit.

Run the server with:

```bash
uvicorn src.main:app --reload --port 8000
```

The server hosts the public-facing relay/dashboard endpoints (used by the [Command Bridge](../README.md#public-monitoring-dashboard-command-bridge)) and one operator endpoint (`/rebuild/intervene`) for human interventions during a build. Builds themselves are kicked off locally via `bash scripts/preflight.sh <target>`, not through HTTP.

## Pipeline endpoints

### `GET /`

Serves the Shipyard dashboard HTML at `src/static/index.html`. Open `http://localhost:8000/` in a browser to see the live pipeline view.

### `GET /health`

Health check. Returns `{"status": "ok"}`. Used by Railway's deployment health probe.

### `GET /pipeline/{session_id}/stage`

Poll the current stage of a running pipeline. Used by the dashboard flow graph.

**Response (running):**

```json
{
  "pipeline": "rebuild",
  "stage": "story_4_2",
  "stage_index": 12,
  "total_stages": 101,
  "stages": ["...current stage list..."],
  "status": "running",
  "error": "",
  "story_progress": {
    "epic": "Epic 4: Auth flows",
    "story": "Story 4.2: Password reset",
    "story_index": 12
  },
  "elapsed_seconds": 1842.7
}
```

**Response (unknown session):**

```json
{"status": "unknown", "error": "No such session"}
```

### `POST /rebuild/intervene`

Submit a human intervention during an active rebuild session when the pipeline encounters a failure it can't auto-recover.

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | Yes | Active rebuild session ID |
| `what_broke` | string | Yes | Description of the failure |
| `what_developer_did` | string | Yes | What the operator did to fix it |
| `agent_limitation` | string | Yes | Why the agent could not handle it |
| `action` | string | Yes | One of: `fix`, `skip`, `abort` |

The operator's intervention is recorded in the per-session intervention log and counted toward the rebuild's `interventions` total.

## Relay endpoints (Command Bridge dashboard)

These power the public [monitoring dashboard](../README.md#public-monitoring-dashboard-command-bridge). Write endpoints require `Authorization: Bearer <SHIPYARD_RELAY_KEY>`. Read endpoints are public — no auth needed.

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/sessions/start` | POST | Yes | Register a new pipeline session |
| `/api/sessions/end` | POST | Yes | Mark a session as completed/failed |
| `/api/events` | POST | Yes | Push a batch of log events from the local pipeline |
| `/api/sessions` | GET | No | List recent pipeline sessions (newest first) |
| `/api/active` | GET | No | Get the currently running session, if any |
| `/api/logs/{session_id}` | GET | No | Fetch log events for a session. Supports `?after_id=N` for incremental polling. |
| `/api/stream/{session_id}` | GET | No | SSE stream of live log events |

For programmatic log extraction, use the `?after_id=N` paging on `/api/logs/{session_id}` rather than dumping the full session in one request — large sessions can have 30,000+ events. See [scripts/extract_log.py](../scripts/extract_log.py) for the canonical extraction loop, and [How-to-extract-db-logs.md](How-to-extract-db-logs.md) for the full extraction recipe including direct DB access for maintenance.

## See also

- [factory-replication-guide.md](factory-replication-guide.md) — how to set up Shipyard from zero, including the four authentications and the host-vs-Docker decision
- [How-to-extract-db-logs.md](How-to-extract-db-logs.md) — pulling pipeline logs off the relay (REST API + direct DB access for maintenance)
- [railway-setup-guide.md](railway-setup-guide.md) — provisioning a target's Railway infrastructure (Postgres, Mailpit, app service) with the single-attempt-then-verify protocol

# How to Extract Pipeline Logs from the Railway Database

## Architecture

The rebuild pipeline does **not** write logs directly to the Railway Postgres database. Instead, it sends events to a **relay service** over HTTP.

```
Docker pipeline  -->  SHIPYARD_RELAY_URL (HTTP POST)  -->  Relay service (FastAPI)  -->  Postgres (log_events / sessions tables)
```

- **Relay service URL**: `https://shipyard-production-29ae.up.railway.app`
- **Relay auth key**: set in `.env` as `SHIPYARD_RELAY_KEY`
- **Railway project**: `perceptive-adventure` (ID `0f7bb362-3853-4e22-b0ab-f7f6f07312ae`)
- **Database**: the same Railway Postgres instance that hosts the PMO app tables, but the pipeline logs live in separate tables (`sessions` and `log_events`) created by `src/log_relay.py:ensure_schema()`

## Why direct database access is difficult

The Postgres public URL (`gondola.proxy.rlwy.net:15911`) connects to the database, but the `log_events` table may not appear if `ensure_schema()` hasn't been run from outside Railway. The relay service handles schema creation internally when it starts up.

Even when connecting directly, the PMO app has its own `sessions` table (columns: token, data, expiry) which is **different** from the pipeline `sessions` table (columns: session_id, started_at, ended_at, status, pipeline_type). Don't confuse them.

## The easy way: use the relay's REST API

The relay service exposes public read-only endpoints. No auth required for GET requests.

### List all sessions

```
GET https://shipyard-production-29ae.up.railway.app/api/sessions
```

Returns JSON array of sessions with `session_id`, `started_at`, `ended_at`, `status`, `pipeline_type`, and `event_count`.

### Fetch logs for a session

```
GET https://shipyard-production-29ae.up.railway.app/api/logs/{session_id}?after_id=0
```

Returns `{"events": [...], "latest_id": N}`. Each event has `id`, `event_type`, `text`, `metadata`, and `created_at`.

The `after_id` parameter supports incremental fetching -- set it to the `latest_id` from the previous response to get only new events. For a full dump, use `after_id=0` (the default).

### Other useful endpoints

- `GET /api/active` — returns the currently running session (if any)
- `GET /api/stream/{session_id}` — SSE endpoint for live-streaming logs

## Extraction script

Save this as a standalone Python script. No dependencies beyond the standard library.

```python
import urllib.request, json, sys

base_url = "https://shipyard-production-29ae.up.railway.app"
session_id = sys.argv[1]
output_file = sys.argv[2]

all_events = []
after_id = 0

while True:
    url = f"{base_url}/api/logs/{session_id}?after_id={after_id}"
    resp = urllib.request.urlopen(urllib.request.Request(url), timeout=120)
    data = json.loads(resp.read())
    events = data.get("events", [])
    if not events:
        break
    all_events.extend(events)
    after_id = data.get("latest_id", events[-1]["id"])
    print(f"  Fetched {len(all_events)} events (latest_id: {after_id})")

with open(output_file, 'w', encoding='utf-8') as f:
    json.dump({"session_id": session_id, "event_count": len(all_events), "events": all_events}, f, indent=2)

print(f"Done: {len(all_events)} events written to {output_file}")
```

Usage:

```bash
python extract_log.py "manual-resume-2026-03-28" output.json
```

## Source code reference

- Relay API routes: `src/main.py` (lines ~400-470)
- Database schema and query functions: `src/log_relay.py`
- Relay URL and key config: `.env` (`SHIPYARD_RELAY_URL`, `SHIPYARD_RELAY_KEY`)

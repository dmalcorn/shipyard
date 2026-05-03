# How to Extract Pipeline Logs from the Railway Database

## Architecture

The rebuild pipeline does **not** write logs directly to the Railway Postgres database. Instead, it sends events to a **relay service** over HTTP.

```
Docker pipeline  -->  SHIPYARD_RELAY_URL (HTTP POST)  -->  Relay service (FastAPI)  -->  Postgres (log_events / sessions tables)
```

- **Relay service URL**: `https://shipyard-production-29ae.up.railway.app`
- **Relay auth key**: set in `.env` as `SHIPYARD_RELAY_KEY`
- **Railway project**: `clever-freedom` (ID `1a26fa7a-949c-4aab-8467-697ef8799b95`)
- **Railway services**: `shipyard` (the FastAPI relay) + `Postgres` (the database)
- **Database**: a dedicated Postgres instance for the relay; pipeline logs live in `sessions` and `log_events` tables created by `src/log_relay.py:ensure_schema()` on relay startup

## Why direct database access used to be difficult

The Postgres public URL (`gondola.proxy.rlwy.net:15911`) connects to the database, but the `log_events` table may not appear if `ensure_schema()` hasn't been run from outside Railway. The relay service handles schema creation internally when it starts up.

Historically the relay shared a database with another app, and that app had its own `sessions` table (columns: `token, data, expiry`) which collided in name with the pipeline `sessions` table (columns: `session_id, started_at, ended_at, status, pipeline_type`). The relay now lives in its own dedicated Postgres instance under `clever-freedom`, so this confusion no longer applies — every table you see in this database belongs to the relay.

## Direct DB access via Railway CLI (for maintenance)

For read-only log queries, prefer the REST API below — it requires no auth and no DB knowledge. Use direct DB access only when you need to:

- Run a `TRUNCATE` to clean up between projects (e.g., wiping old chat2diagram sessions before starting a new build)
- Inspect schema or run an ad-hoc `SELECT` that the REST API doesn't expose
- Apply a manual data fix the relay's API doesn't support

### Auth handoff: how Claude gets DB access

The Railway CLI is the cleanest path. Auth is per-machine, not per-shell:

1. **Operator** (one-time per host, in any VS Code terminal): runs `railway login`. Browser OAuth completes; token is written to `~/.railway/config.json`.
2. **Operator** confirms with `railway whoami`. Should show the logged-in email.
3. **Claude** (or any subsequent shell on the host) inherits the token. Claude can then run any `railway *` command.

When Claude reports `Unauthorized. Please run 'railway login' again.`, that's always the operator's cue — Claude can't drive the interactive browser flow. See [railway-setup-guide.md](railway-setup-guide.md#prerequisites) for the canonical version of this section.

### Connecting to the relay's Postgres

```bash
railway link --project clever-freedom        # interactive: pick environment 'production'
railway connect Postgres                     # opens an interactive psql shell
```

Inside `psql`:

```sql
-- Inspect the schema
\dt
-- expected: log_events, sessions

-- Count rows
SELECT COUNT(*) FROM sessions;
SELECT COUNT(*) FROM log_events;

-- Look at most-recent sessions
SELECT session_id, started_at, ended_at, status, pipeline_type
FROM sessions
ORDER BY started_at DESC
LIMIT 10;
```

### Maintenance: TRUNCATE between projects

When kicking off a new factory target (e.g., the next project after chat2diagram), the dashboard's session dropdown gets cluttered with old runs. After archiving anything you want to keep via the REST API + `scripts/extract_log.py`, wipe the relay clean:

```sql
TRUNCATE TABLE log_events, sessions RESTART IDENTITY CASCADE;
```

- `RESTART IDENTITY` resets the `log_events.id` SERIAL sequence to 1 — next event lands at id=1, clean numbering for the new project.
- `CASCADE` handles the FK from `log_events.session_id` → `sessions.session_id` without complaint.

**Always archive before truncating.** The relay DB is the only authoritative copy of session events. Once truncated, the data is gone — there is no Railway-side backup. Run the extraction script in this doc against every session_id you want to keep, and confirm files exist on disk before running TRUNCATE.

### Anti-patterns

- **Connecting via the public proxy hostname** (`gondola.proxy.rlwy.net:15911`) when the CLI works — the proxy adds latency, exposes credentials in shell history, and breaks if the proxy port number changes (Railway rotates these). `railway connect` always resolves to the current internal endpoint.
- **Running `DELETE FROM sessions` without first deleting `log_events`** — fails with FK violation. Use `TRUNCATE ... CASCADE` or delete log_events first.
- **Using the `railway run` command to inject DATABASE_URL into a local `psql`** — works on Mac/Linux, brittle on Windows due to shell variable expansion differences. `railway connect` is cross-platform.

### Troubleshooting recipe: when `railway connect` won't work (Windows)

The first time we ran a relay TRUNCATE end-to-end we hit five separate snags. Captured here so the next agent doesn't have to rediscover them.

**1. `psql` not installed locally.** `railway connect Postgres` requires the `psql` client binary on the operator's machine. On a typical Windows host it isn't present, and the CLI fails with:

```
psql must be installed to continue
```

**Fix:** skip `railway connect`. Use `psycopg2` (already installed for the relay's own use, since it's in `requirements.txt`). Pattern:

```bash
DB_URL=$(railway variables --service Postgres --kv 2>/dev/null | grep "^DATABASE_PUBLIC_URL=" | cut -d= -f2-)
DATABASE_URL="$DB_URL" python -c "
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
conn.autocommit = True
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM public.sessions')
print('sessions:', cur.fetchone()[0])
conn.close()
"
```

**2. The internal hostname (`postgres.railway.internal`) doesn't resolve from outside Railway.** The Postgres service exposes two URLs: `DATABASE_URL` (uses `postgres.railway.internal:5432`, Railway-network-only) and `DATABASE_PUBLIC_URL` (uses `<region>.proxy.rlwy.net:NNNN`, public-internet-reachable). From the operator's laptop, only the public URL works. Symptom if you grab the wrong one:

```
psycopg2.OperationalError: could not translate host name "postgres.railway.internal" to address
```

**Fix:** always grep for `^DATABASE_PUBLIC_URL=`, never plain `^DATABASE_URL=`.

**3. `railway variables --kv` output contains resolved secrets in cleartext.** The `--kv` flag dumps every variable in `KEY=value` form, including resolved passwords. A naive regex to print "just the host" can leak the password — we did this once and the postgres password ended up in the conversation log, requiring an immediate rotation.

**Fix:** never echo `--kv` output to stdout, even after attempted redaction. Always capture directly into a shell variable (`X=$(railway variables ... --kv | grep ...)`) and use `${#X}` (length only) if you need to confirm extraction worked. Treat the value as write-only.

**4. Connection pooler / replica routing inconsistency.** Railway's Postgres is fronted by a pooler. We saw this surreal sequence in one session:

- Connection 1: queried `information_schema.tables` filtered by schema → returned 17 rows, `sessions`/`log_events` not among them
- Connection 2 (seconds later, same DATABASE_PUBLIC_URL): queried `information_schema.tables` filtered by table-name pattern → returned `public.sessions` + `public.log_events` cleanly
- Connection 3: ran `TRUNCATE TABLE public.log_events, public.sessions ...` → failed with `relation "public.log_events" does not exist`
- Connection 4 (immediately after): saw the tables again

Plausible cause: the pooler routed different connections to different replica nodes with different schema cache states. Whatever the mechanism, the fix is what worked:

**Fix:** do the visibility check + the destructive op in **one** connection. The same psycopg2 session that runs `SELECT COUNT(*)` runs the `TRUNCATE` immediately after — no closing and reopening between them.

```python
conn = psycopg2.connect(os.environ['DATABASE_URL'])
conn.autocommit = True
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM public.sessions')   # confirm visibility
print('pre:', cur.fetchone()[0])
cur.execute('TRUNCATE TABLE public.log_events, public.sessions RESTART IDENTITY CASCADE')
cur.execute('SELECT COUNT(*) FROM public.sessions')   # verify post
print('post:', cur.fetchone()[0])
```

**5. psycopg2 doesn't autocommit by default.** Without `conn.autocommit = True`, a `TRUNCATE` runs inside an implicit transaction; if the script exits without `conn.commit()`, the DDL rolls back silently. Setting `autocommit = True` makes each statement commit immediately.

**6. Windows console can't print Unicode by default.** `print(' → ')` blows up with `UnicodeEncodeError: 'charmap' codec can't encode character '→'`. Stay ASCII-only in print statements run from the Bash/PowerShell terminal — `->` instead of `→`, `OK` instead of `✓`.

After working through these, the end-to-end TRUNCATE recipe that worked is:

```bash
DB_URL=$(railway variables --service Postgres --kv 2>/dev/null | grep "^DATABASE_PUBLIC_URL=" | cut -d= -f2-)
DATABASE_URL="$DB_URL" python -c "
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
conn.autocommit = True
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM public.sessions')
print('pre sessions:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM public.log_events')
print('pre log_events:', cur.fetchone()[0])
cur.execute('TRUNCATE TABLE public.log_events, public.sessions RESTART IDENTITY CASCADE')
cur.execute('SELECT COUNT(*) FROM public.sessions')
print('post sessions:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM public.log_events')
print('post log_events:', cur.fetchone()[0])
conn.close()
"
curl -sf "https://shipyard-production-29ae.up.railway.app/api/sessions" | python -c "import json,sys; print('API:', len(json.load(sys.stdin)), 'sessions')"
```

### Rotating the Postgres password

Railway's dashboard does **not** have a "regenerate" button. The "Generate" button on a variable opens a *Variable Generator* dialog that produces a generator function (`${{ secret(32, "abc...XYZ") }}`) intended to populate new environments cloned from the current one. It doesn't replace the *current* environment's value — it just shows you a fresh random string at the top of the dialog you can copy.

**Manual rotation procedure** (after a leak, or routine):

1. Open Railway dashboard → `clever-freedom` → Postgres service → Variables tab.
2. Click **Generate** next to `POSTGRES_PASSWORD` to get a fresh random string. Copy the value displayed at the top of the dialog (e.g., `AOUqKpbjyaEnTYeIoTrIWglYySnZybtX`). Close the dialog without saving the generator function (unless you want clones to use this generator pattern — separate concern).
3. Edit `POSTGRES_PASSWORD` directly and paste the new value. Save. Railway restarts the Postgres container with the new password.
4. **Update every dependent service.** Any service that references the password as a *resolved* string needs to be updated. Check the `shipyard` service's `DATABASE_URL`:
   - If it's a reference variable like `${{Postgres.DATABASE_URL}}`, Railway resolves it at deploy time and it auto-updates on the next redeploy — no manual edit needed.
   - If it's a resolved string like `postgresql://postgres:OLDPASSWORD@postgres.railway.internal:5432/railway`, replace it. **Better: convert it to a reference variable** while you're there: `DATABASE_URL=${{Postgres.DATABASE_URL}}`. After that, future rotations propagate automatically. See [railway-setup-guide.md](railway-setup-guide.md#6-set-app-service-environment-variables) for the reference-variable pattern.
5. Run `railway redeploy --service shipyard --yes` (or via dashboard) to pick up the new value.
6. Verify with `curl -sf https://shipyard-production-29ae.up.railway.app/health` (or `/api/sessions`) — a 200 response confirms the relay reconnected to Postgres with the new password.

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

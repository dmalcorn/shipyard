# How to Capture Console Messages Locally

**Status:** Reference doc. Not implemented as of 2026-05-08 — captures findings from a log-infrastructure audit so the decision can be made later.

## Why this exists

Shipyard streams every stdout line and every Python `logging` record from a factory run to a Railway-hosted relay (Postgres `log_events` table). That relay is the **only complete, replayable archive of console output**. If Railway has an outage mid-run, or if the relay handler hits an exception, the full chronological console stream for that window is lost — the shell's terminal scrollback is the only other live witness, and it dies the moment the terminal closes.

The local files that exist (intervention log, audit log, rebuild-status, checkpoints) are **purpose-built fragments**, not console mirrors. They capture specific event categories, not the raw stream the user watches.

This doc maps the current state and the options for adding a local mirror.

## Current state — where console output goes

### Full preservation (canonical)

| Sink | What it captures | Notes |
|---|---|---|
| **Railway Postgres** (`log_events` table via `src/log_relay.py` + `src/web_relay.py`) | Every stdout line and every `logging` record | Sole complete archive. Retrieval: `scripts/extract_log.py`. Authoritative source for "what did the run print?" |

### Partial / event-specific local files (all untracked in git)

| Path | Captures | Format | Scope |
|---|---|---|---|
| `{target}/intervention-log.md` | Human interventions only — written when a human steps in to fix something the agent couldn't | Markdown | Per-target |
| `logs/session-{session_id}.md` (in shipyard root) | Agent start/end events, tool calls, script executions, file-touch counts (Decision-6 audit format) | Markdown tree-style | Per-shipyard-run |
| `{target}/rebuild-status.md` | Summary metrics: stories completed/failed, timing, cost, intervention counts | Markdown | Per-target |
| `{target}/checkpoints/*.{db,json}` | LangGraph state for resume (`rebuild.db` SQLite + `session.json`, `phase.json`, `epic-phase.json`) | SQLite + JSON | Per-target |

### Stdout is not file-logged

`src/main.py` calls `logging.basicConfig(...)` without a `FileHandler` — only stdout (which the relay handler tees to Railway) and the relay sink. The shell's terminal scrollback is the only other live witness during a run.

## What's missing

A local file that captures the same stream the relay sees. If you have one, you can:
- Replay a run after closing the terminal, without depending on Railway being up.
- Survive relay-side outages (Railway hiccups, auth breaks, schema migrations).
- `grep` historical runs without round-tripping through `scripts/extract_log.py`.
- Diff "what the user saw" against "what the relay archived" if those ever diverge.

## Options when you decide to add local capture

Three approaches, each with different tradeoffs.

### Option A — Shell-level `tee`

Wrap the entry point at the shell:

```bash
mkdir -p logs/console
python -m src.main "$@" 2>&1 | tee "logs/console/run-$(date +%Y%m%d-%H%M%S).log"
```

**Pros:** Zero code change. Captures literally everything the terminal sees, including subprocess output that bypasses Python's `logging`. Works with any shell.

**Cons:** Requires the user (or a shipyard wrapper script) to remember the redirect. Anything launched in detached mode (e.g. background graph runs not started via this command) won't be captured.

**When to pick:** You want the cheapest possible safety net and run shipyard interactively from a known shell command.

### Option B — Add a `FileHandler` next to the relay handler

In whichever module sets up logging (currently `src/main.py:408` — `logging.basicConfig()`), also attach a rotating file handler:

```python
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

log_dir = Path("logs/console")
log_dir.mkdir(parents=True, exist_ok=True)
file_handler = RotatingFileHandler(
    log_dir / f"run-{session_id}.log",
    maxBytes=50 * 1024 * 1024,
    backupCount=5,
)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
logging.getLogger().addHandler(file_handler)
```

**Pros:** No shell-level cooperation needed. Survives detached/background runs. Automatic rotation prevents disk fill.

**Cons:** Captures only what flows through Python `logging` — not raw `print()` calls, not subprocess stdout that the factory shells out to. Shipyard uses both `logger.info(...)` AND `print(...)` AND `_run_bash(...)` whose subprocess output is captured into a string variable, not logged. So a `FileHandler` would miss everything that doesn't go through `logging`.

**When to pick:** Never alone. Useful only as a complement to Option A or C.

### Option C — Tee inside `_RelayWriter` / `_RelayLoggingHandler`

The relay code already intercepts every stdout write and every `logging` record (in `src/web_relay.py`). Add a local file write at the same point:

```python
# inside _RelayWriter.write() in src/web_relay.py
def write(self, data):
    self._original_stdout.write(data)
    self._post_to_relay(data)
    if self._local_mirror:           # new
        self._local_mirror.write(data)
        self._local_mirror.flush()
```

**Pros:** Captures exactly what the relay captures — by definition, no drift. Survives relay outages because the local write happens before the network call. One source of truth for both archives.

**Cons:** Requires editing the relay client. Bigger change than Option A. Need to handle file rotation, fsync, and the failure mode where disk fills before relay does.

**When to pick:** You want belt-and-suspenders — the relay is your primary archive but the local file is your insurance against Railway outages, and you want zero capture drift between them.

## Recommendation when the decision is made

Default to **Option A (shell `tee`)**. It's a one-line change to whatever launches shipyard, zero code change, captures everything (including subprocess output the relay client doesn't see), and gives you a per-run timestamped file in `logs/console/`. Add `logs/console/` to `.gitignore` if it isn't already covered.

If you ever find yourself reaching for Option C, it means Option A failed you in a specific way — at that point write down which way and pick C with eyes open. Don't pre-engineer C.

## Open questions to resolve before implementing

1. **Retention.** Do you want a per-run file forever (cheap, but `logs/console/` grows unbounded), or a rotation policy (annoying when you need an old run)? Default suggestion: keep forever, rely on disk being cheap; sweep manually if it ever matters.

2. **Sensitive content.** Are there secrets or tokens that flow through console output? The Railway relay already sees them — adding a local file doesn't change the threat model, but it does add a *second* place they live, on a machine that may be less locked down than Railway. Worth thinking about before adopting Option B/C, less relevant for Option A (which only captures what you'd see in your terminal anyway).

3. **Capture scope.** Should each child agent (BMAD agents, Claude Code subprocess, Cursor, etc.) get its own file, or should they all flow into one big file per run? The relay already interleaves them — if local files match, they should too. Option A naturally produces one file per run; B and C give you flexibility.

## Pointers (current code, for the future implementer)

- Relay client and stdout teeing: `src/log_relay.py`, `src/web_relay.py`
- Logging setup: `src/main.py` (around `logging.basicConfig()`)
- Existing partial sinks (so you know what's already covered):
  - `src/intake/intervention_log.py`
  - `src/audit_log/audit.py` (writes `logs/session-{id}.md`)
  - `src/intake/checkpoint.py`
  - `src/intake/rebuild_graph.py` (writes `rebuild-status.md`)
- Retrieval from Railway: `scripts/extract_log.py`

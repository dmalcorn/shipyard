# scripts/log_analysis/

Canned analyses over relay log dumps. Each script answers a specific question we asked repeatedly during the chat2diagram build's debugging sessions; codifying them here so the next build's debugging starts from a higher floor.

## Workflow

1. Pull the dump (full or incremental):
   ```bash
   # Full:
   python scripts/extract_log.py <session_id> /tmp/dump.json
   # Incremental (resumes from last seen event id):
   python scripts/extract_log.py <session_id> /tmp/dump.json --incremental
   ```
2. Run any analysis against it:
   ```bash
   python -m scripts.log_analysis.cost_by_story /tmp/dump.json
   python -m scripts.log_analysis.failure_patterns /tmp/dump.json
   python -m scripts.log_analysis.phase_durations /tmp/dump.json
   python -m scripts.log_analysis.auth_halt_check /tmp/dump.json
   ```

## What each script answers

| Script | Question | Useful when |
|---|---|---|
| `cost_by_story.py` | How much did each story cost? | Spotting expensive stories, comparing runs |
| `failure_patterns.py` | Which stories needed >1 CI cycle? Did any give up? How long did each cycle take? | Diagnosing stuck stories, evaluating fix_ci tuning |
| `phase_durations.py` | Where did wall-clock time go? Per-story phase breakdown + global totals | Capacity planning, spotting unusual phase ratios |
| `auth_halt_check.py` | Did rate-limit / auth-failure messages appear? Did the halt detection fire? | Validating commit `d88ce0d`, finding new auth message variants Anthropic introduces |

## Adding a new analysis

Each script is ~80-150 lines, self-contained. Pattern:

1. `argparse` for `<dump.json>` arg
2. Load the dump, iterate `events`
3. Match per-event regex patterns against `text`
4. Track state (current story, current phase, etc.) as you go
5. Print a focused report on stdout

Avoid `--` flags beyond the dump path; analyses should be batch-runnable in shell pipelines without ceremony.

## Anti-patterns to avoid in new scripts

- **Don't** use Unicode characters in output (em-dash, arrows, etc.). Windows default `cp1252` console can't print them. Use ASCII (`-`, `*`, `>>`, etc.).
- **Don't** silently skip events that don't match expected patterns — at minimum, count them and report at the end.
- **Don't** load the full dump into memory if you only need streaming aggregates — these dumps can hit 100K events on long runs.

## See also

- `scripts/extract_log.py` — pulls dumps from the relay; supports `--incremental` for live monitoring
- `gauntlet_docs/How-to-extract-db-logs.md` — relay architecture and the broader log-extraction workflow
- `gauntlet_docs/factory-lessons-from-chat2diagram.md` — the analyses these scripts came from, codified into recovery patterns

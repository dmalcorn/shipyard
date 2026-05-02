# Factory Lessons from the chat2diagram Build

A retrospective on the chat2diagram factory rebuild that ran 2026-04-24 → 2026-04-25. Captures both the architectural patterns that worked unusually well and the failure modes we hit and hardened against. Companion to [factory-replication-guide.md](factory-replication-guide.md), which is the forward-looking how-to.

**Raw event logs from this build** are archived at `c:/alcorn/Gauntlet/8-Capstone/factory/chat2diagram-relay-archive/` (sibling to shipyard, outside any git repo). 5 session JSONs + a manifest + a per-session breakdown — see that directory's [README.md](../../chat2diagram-relay-archive/README.md) for what each session covers and how to load them. Every claim in this lessons doc is backed by events in those files; if a future analysis disagrees with something here, the archive is the tiebreaker.

**Execution context for this build**: the factory ran in **host mode end-to-end** — `python -m src.main --rebuild …` invoked directly on the operator's Windows laptop, with target builds (`npm`, `npx`, `vitest`, `tsc`, `drizzle-kit`, `next build`) running as host bash subprocesses of the factory. **No Docker was involved in the build of the source code.** The chat2diagram Dockerfile is for production deployment to Railway only. The `docker-compose.rebuild.yml` Docker-mode option exists in shipyard but was not used. See [factory-replication-guide.md](factory-replication-guide.md#where-things-actually-run--the-host-vs-docker-question) for the full execution-context map across all four runtime contexts (factory build, target dev, target CI, target production). Several of the hardenings shipped during this run (Windows shim wrap in `a43564b`, husky pre-commit fixes) only matter in host mode — a Docker-mode build of the same target wouldn't have hit those bugs but might surface different ones.

---

## Run summary

| Metric | Value |
|---|---|
| Stories planned | 101 (across Epic 1–17) |
| Stories landed | 101 (all 17 epics tagged on GitHub) |
| Wall-clock window | ~30h elapsed (with two rate-limit pauses requiring manual recovery) |
| Sessions | 3 distinct relay sessions due to two auth interruptions |
| Manual interventions | ~6 — all schema/bookkeeping recoveries, none code |
| Factory commits made during the run | 7 (hardenings from observed failure modes) |
| Final state | Every story committed, every epic tagged |

The notable thing about the run wasn't that everything went smoothly — it didn't. It's that **every interruption surfaced a real factory weakness, and we patched the factory live during the run**. By the time Epic 17 finished, the factory was meaningfully harder than when Epic 12 started.

---

## Architectural patterns that worked

### Three repos, three concerns

The single most important design decision: factory, target, and relay are three independent git repos. The factory only ever touches the target via subprocess calls scoped to `cwd=target_dir`. There is no symlink, no shared module, no embedded library. The factory commits *as* the target repo's git user (configured in target's `.git/config` or via `GIT_AUTHOR_*`), pushes via target's `origin` remote, and tags using target's tag namespace.

Practically this means:
- A bug fix to the factory lands as a shipyard commit, not as part of any story commit on the target
- The target can be cloned, audited, and deployed by anyone without the factory existing
- A future operator could rerun the factory against a different target without forking shipyard
- The relay can be restarted, redeployed, or replaced without disturbing either repo

The architecture mirrored what the operator wants: clean separation between the tool, the artifact, and the observability layer.

### Phase-level checkpointing

`checkpoints/session.json` tracks epic+story progress (rolling, written after each completed story). `checkpoints/phase.json` tracks mid-story phase (written after each phase completes within a story). On `--resume`, the orchestrator's `route_on_entry` reads phase.json and jumps directly to the next un-completed phase, skipping check_story / dev_story / code_review / etc. that already finished.

This let us Ctrl+C and resume mid-story multiple times without re-running expensive dev_story invocations. Specifically: when we killed the pipeline mid-fix_ci on story 12-1 to push a code fix, the resume jumped straight to `run_ci` for that story — no $1.95 dev_story redo.

### The relay log as forensic playback

Every event the factory emits — every Bash invocation, every BMAD agent call, every node transition, every phase transition — flows over HTTP to the relay's Postgres in real time. The dashboard streams it live (SSE), and `scripts/extract_log.py` pulls the full event history for any session afterward.

This was the lever that made the next pattern possible.

### Continuous improvement loop driven by log analysis

The actual workflow we used multiple times during the run:

1. Operator notices something off (build slow, story failing, dashboard quiet)
2. `python scripts/extract_log.py <session_id> /tmp/dump.json`
3. Quick Python script over the JSON: filter for the suspicious window, look at message patterns
4. Identify the root cause from agent output, exit codes, or absent events
5. Patch the factory in shipyard, commit + push
6. Manually fix any data-side damage (session.json, prod DB, etc.)
7. `python -m src.main --rebuild <target> --resume` — new factory process loads the patched code, picks up via phase/session checkpoints, continues

This loop ran six times during the run. Each iteration of it ended in a shipyard commit. The fact that we could observe the bug, fix it, and have the next resume pick up the fix on the same target build — without losing already-completed work — is what made the run survivable.

### Defensive migrate-db on prod deploys

After the schema-drift incident on Epic 13, we rewrote `scripts/migrate-db.ts` (target-side, not factory-side) to tolerate `42P07 / 42701 / 42710 / 23505` Postgres errors during migration application. The reasoning: when prod DB is patched manually to unstick a broken deploy, subsequent deploys see `CREATE TABLE` against an existing table and fail. The defensive migrator logs those as warnings, records the migration as applied, and continues.

This is a target-repo concern, but the pattern generalizes: **any migrator running in CI against a long-lived database should treat "object already exists" as a successful idempotent outcome, not a fatal error.**

---

## Recovery patterns we developed

These are operator-side procedures, not factory features. Together they cover every failure mode we hit.

### Auth cascade recovery

**Symptom**: every BMAD agent invocation returns in 1–2 seconds with `1 turn / $0.00`. Pipeline marks each story "failed" and races through the remaining backlog at ~2s per story.

**Cause**: the Claude Code CLI lost access mid-run — either subscription expired, org access revoked, or the 5-hour usage window hit its limit. The CLI returns with the failure message in stdout but exit code 0 sometimes, which the factory used to misread.

**Fix in the factory** (commit `d88ce0d`): `bmad_invoke.py` now scans agent output for three telltale strings:
- `does not have access to Claude`
- `You've hit your limit`
- `Please login again or contact your administrator`

…and force-quits the pipeline immediately on first detection. Same recovery path as a manual Ctrl+C: kills subprocesses, marks relay session paused, exits with code 2.

**Manual recovery if you hit this on an older shipyard**: see [factory-replication-guide.md#rate-limits](factory-replication-guide.md#rate-limits--subscription-expiry) for resume steps. Edit `session.json` to revert the bogus "failed" entries, generate a fresh `session_id`, wait for the auth window to lift, resume.

### Schema drift / missing migration

**Symptom**: deployed app shows "Server Components render error", Railway logs show `column "X" does not exist` (Postgres 42703).

**Cause**: dev agent added a column to `schema.ts` but didn't run `drizzle-kit generate`. App code queries the column, prod DB doesn't have it, render fails.

**Fix in the factory** (commit `f7e0b76`): `git_commit_node` now detects when the story modified `schema.ts` but didn't add a new `drizzle/*.sql`. If so, runs `npx drizzle-kit generate --name=story_<task_id>` before staging. The fresh migration file lands in the same commit as the story's code.

**Manual recovery**: in the Railway Postgres Data tab, run the equivalent ALTER TABLE / CREATE TABLE statements with `IF NOT EXISTS` clauses. We did this twice during the run — for `enabled_skill_packs` (story 14-3) and for `comparison_jobs` + `comparison_results` (stories 15-3/4/5).

### Migration tracking corruption

**Symptom**: Railway deploy says `[migrate-db] no pending migrations`, but the prod DB is missing columns the journal claims are applied.

**Cause**: `migrate-db.ts`'s bootstrap path pre-seeded `__drizzle_migrations` with hashes for migrations whose DDL was never actually run (the bootstrap code assumed "users table exists therefore all migrations applied" — which is wrong if the schema was previously synced via `drizzle-kit push` for only a subset of migrations).

**Fix in the target** (defensive `migrate-db.ts`): tolerate "already exists" errors during migration application, record each as applied, continue. This means even if the tracking table and the actual schema diverge, the next deploy reconciles quietly.

**Manual recovery**: in the Railway Postgres Data tab, apply the missing DDL with `IF NOT EXISTS` guards, then `INSERT INTO drizzle.__drizzle_migrations` with the SHA-256 hashes of the migration SQL files (computable via `python -c "import hashlib; print(hashlib.sha256(open('drizzle/0007_X.sql','rb').read()).hexdigest())"`).

### Bogus story-failure entries from auth cascade

**Symptom**: 8+ stories appear as "failed" in `resume_story_results` — but the failures all happened in the same minute and have suspiciously identical timing.

**Cause**: pre-`d88ce0d` factory cascading through stories during an auth blackout, marking each "failed" because the agent returned in 1 turn with no work done.

**Manual recovery**: edit `session.json` to flip those entries to "completed" if their code was actually committed (check `git log` for `story X-Y complete`), or drop them entirely if no work landed. We did this three times during the run via small Python scripts under `C:/Users/<user>/AppData/Local/Temp/`.

### Out-of-band epic tag

**Symptom**: All stories in an epic committed cleanly to git, but the epic-completion tag is missing because the post-epic review chain hit an auth issue before the tag step.

**Manual recovery**:
```bash
cd /target
git tag epic-<N>-complete <last-story-N-commit-sha>
git push origin epic-<N>-complete
```

We did this for `epic-13-complete`, `epic-15-complete`, and `epic-16-complete`.

### No-op resume

**Symptom**: Operator runs `--resume` against a finished pipeline (e.g. to verify "is this done?") and gets `IndexError: list index out of range`.

**Fix in the factory** (commit `45ea98b`): `select_epic_node` and `run_epic_node` now detect `epic_index >= len(epics)` and short-circuit cleanly via the existing `route_after_epic` "all_done" path. Resume on a finished pipeline now prints `All N epics already complete — nothing to do.` and exits.

---

## Factory hardenings shipped during this run

Six commits to shipyard during the chat2diagram build:

| SHA | Title | Trigger |
|---|---|---|
| `d33be06` | Retarget factory to chat2diagram; default CI scope to brownfield | Initial setup |
| `a43564b` | Wrap npx/npm in bash -c; expand fix_ci scope to downstream type breakage | Windows shim error + 13-2/13-6 cascade fixes |
| `c96db6d` | run_ci tee output to disk; guard _run_bash against None streams | 14-2 stuck on `NoneType has no len()` masquerading as CI output |
| `f7e0b76` | Auto-generate Drizzle migration when story touched schema.ts | Story 14-3 missed generating, broke prod twice |
| `d88ce0d` | Halt pipeline on Anthropic auth/rate-limit signals | Two cascading auth blackouts cost ~$25 in cleanup time |
| `45ea98b` | Handle --resume against an already-complete pipeline | Operator's "is it done?" check crashed |

Plus one in the target repo: `2c31777` (chat2diagram) made `migrate-db.ts` tolerant of "already exists" errors.

Each was small (under 100 lines), single-purpose, and triggered by an actual incident. None were speculative.

---

## What I'd carry forward

Things that worked well enough that I'd repeat them on the next factory run:

1. **Keep the factory as a separate repo.** The temptation to vendor it inside the target ("just for this project") is real and wrong. Cross-repo subprocess scoping is the entire reason these patterns work.

2. **Deploy a relay before kicking off a long build.** The first factory run at scale without a relay is going to need one mid-build, by which point you've lost the early-build observability. Ten minutes of Railway setup pays for itself in hour one.

3. **Treat the relay log as the canonical record.** During the run we used `extract_log.py` more than `git log` — every weird behavior left a trace in the relay log, and the relay log preserves *intermediate* state (agent output, exit codes) that git history doesn't.

4. **Fix the factory live, in shipyard, and resume.** Don't try to work around factory bugs in target code. The factory is supposed to be the durable artifact; targets come and go. Every fix that makes it into shipyard helps every future build.

5. **Manual recovery is a feature, not a failure.** `session.json` and the `__drizzle_migrations` table are both human-editable. Treat them that way. The recovery scripts under `C:/Users/<user>/AppData/Local/Temp/` from this run are reusable templates, not one-offs.

---

## Outstanding issues / future work

Open items at the end of this run, ranked by impact:

- **Snapshot files** (`drizzle/meta/0005_snapshot.json` … `0015_snapshot.json`) are missing for the stories whose dev agent didn't run `drizzle-kit generate` — manual ones we created via SQL never produced the corresponding snapshot. A first invocation of `drizzle-kit generate` on a fresh schema diff would produce a surprising catch-up migration. **Mitigation**: when next operator goes to add migrations, regenerate snapshots first via a no-op `drizzle-kit generate` (or scripted equivalent).

- **Resume timing UX**. The operator currently has to compute "rate limit lifts at 7:10 PM Central + I'm in UTC". The relay could surface a parsed `resets <time>` from the agent output so the dashboard shows "resume after HH:MM UTC" instead of forcing arithmetic.

- **`.env` variables set against stale state**. `GIT_REMOTE_ORIGIN` left over from a prior project will silently rewrite the new target's origin remote on `init_project_node`. Either clear `.env` between projects or add a sanity check that warns when `GIT_REMOTE_ORIGIN` doesn't match `factory.yaml#github.target_remote_url`.

- **Schema-drift audit script**. The Python audit we ran ad-hoc to find which `schema.ts` columns had no matching migration would be useful as a `scripts/audit_schema.py`. Not blocking — useful as a pre-deploy lint.

- **Multi-ORM support for the auto-migrator**. The schema.ts auto-generate fix (`f7e0b76`) is hard-wired to Drizzle. Prisma / TypeORM / SQLAlchemy projects would need parallel logic. Easy to add as needed; no other ORM ran through this factory yet.

- **`__drizzle_migrations` insert blocked by Railway Data tab**. We hit a UI quirk where INSERTs into the `drizzle` schema rolled back silently. Workaround was breaking the script into smaller chunks. Doesn't affect production, but worth knowing.

- **Host-vs-Docker confusion**. Multiple times during the build the operator asked "wait, is this running in Docker?" Plausible question — `chat2diagram/Dockerfile` exists, the relay runs in containers on Railway, and shipyard *has* a `docker-compose.rebuild.yml`. The actual answer for this build was "host mode end-to-end, no operator-side containers," but it wasn't easy to confirm without grepping logs for Windows-specific errors. **Mitigation already landed**: the host-vs-Docker section in the replication guide spells this out with a per-context execution table. Future ambiguity should be cheaper to resolve.

Each of these is a single small commit's worth of work, not a structural rewrite. The factory's core loop is healthy.

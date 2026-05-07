# How to Set Up the Factory Harness for a New Target

Pre-flight checklist for everything that must be in place **before** running:

```bash
python -m src.main --rebuild /path/to/<target>
```

This document is the single ordered runbook. It pulls together what the deeper guides cover separately, and tracks the live status of the next target in this repo: **PawprintRecipes** (located at `c:\alcorn\AI\PawprintRecipes-wrapper\PawprintRecipes`).

> **Deeper references** — don't duplicate, cite:
> - [factory-replication-guide.md](../gauntlet_docs/factory-replication-guide.md) — host-vs-Docker, the four authentications, gotchas
> - [railway-setup-guide.md](../gauntlet_docs/railway-setup-guide.md) — Postgres / Mailpit / app service provisioning, single-attempt-then-verify
> - [git-remote-setup-guide.md](../gauntlet_docs/git-remote-setup-guide.md) — branch / PAT / Railway-deploy-branch alignment
> - [targetsetup/local-dev-docker-guide.md](../targetsetup/local-dev-docker-guide.md) — three-container local dev (app + db + mailpit)
> - [targetsetup/ci-script-specification.md](../targetsetup/ci-script-specification.md) — what `scripts/ci.sh` must accept and emit

---

## 1. Three repos, three responsibilities

```
shipyard/                      <target>/                     shipyard-relay (Railway)
(this repo — factory)          (the build product)           (live dashboard + logs)

drives the build  ────────▶    receives commits / tags
                                                              receives HTTP events ◀────
```

The factory and the target are **separate directories on disk**. The target lives outside `shipyard/`. The relay is shared infrastructure (`clever-freedom` Railway project, `shipyard-production-29ae`) — never touched per-target. See [factory-replication-guide.md §Architecture at a glance](../gauntlet_docs/factory-replication-guide.md).

---

## 2. Host tools — what must be installed

Validate each on the host before going further:

```bash
python --version          # ≥ 3.13
node --version            # ≥ 22 (only if target is JS/TS)
git --version
bash --version            # Git Bash on Windows
docker --version          # Docker Desktop, for the target's local dev stack
docker compose version
claude --version          # Claude Code CLI, on PATH
railway --version         # ≥ 4.x
gh --version              # optional but useful
```

If anything is missing, install before continuing. The factory shells out to all of these via `subprocess.run` — there is no graceful degradation.

---

## 3. The four authentications

Conflating these is the single most common setup mistake. Each lives in a different place.

| # | Auth | Lives in | How verified |
|---|---|---|---|
| 1 | Claude Code CLI | host user account (browser OAuth) | `claude --print "ready"` |
| 2 | GitHub (target push) | Git Credential Manager **or** PAT in shipyard `.env` | `git ls-remote <url>` succeeds |
| 3 | Railway | `~/.railway/config.json` (browser OAuth) | `railway whoami` |
| 4 | LangSmith | `LANGCHAIN_API_KEY` in shipyard `.env` | trace appears at smith.langchain.com |

Full details in [factory-replication-guide.md §The four authentications](../gauntlet_docs/factory-replication-guide.md). For non-interactive Docker-mode runs, GitHub auth must be embedded as a PAT — see [git-remote-setup-guide.md](../gauntlet_docs/git-remote-setup-guide.md).

---

## 4. Target repo state — required files

The factory enforces these exact paths and filenames. If they're missing or named something else, the run will either crash or silently use wrong defaults.

| Path (under target root) | Required? | What the factory does with it |
|---|---|---|
| `.git/` | required (factory will `git init` if absent, but pre-creating with the right `.gitignore` is cleaner) | runs `git init`, commits per story, pushes per epic |
| `_bmad-output/planning-artifacts/epics.md` | **required** | parsed into the backlog ([backlog.py:41](../src/intake/backlog.py)) |
| `_bmad-output/planning-artifacts/prd.md` | required by BMAD agents | read by dev / architect via Claude CLI |
| `_bmad-output/planning-artifacts/architecture.md` | required by BMAD agents | read by dev / architect |
| `_bmad-output/planning-artifacts/coding-standards.md` | recommended | injected as Layer 1 context ([injection.py:69](../src/context/injection.py)). If missing, agents miss the coding standards layer — silent quality hit, not a crash. |
| `_bmad-output/approved-tech-stack.md` | required **only if no `scripts/ci.sh` exists** | source for auto-generated CI script. If `scripts/ci.sh` already exists, factory skips generation ([orchestrator.py:1093](../src/multi_agent/orchestrator.py)) |
| `scripts/ci.sh` | required (auto-generated if missing AND `approved-tech-stack.md` exists) | invoked at every CI gate; must accept `--story X_Y`, `--epic N`, etc. per [ci-script-specification.md](../targetsetup/ci-script-specification.md) |
| `CLAUDE.md` | recommended | per-target rules + lessons-learned Tier 2; loaded by every Claude CLI invocation |
| `Dockerfile` (production) + `docker-compose.yml` (local dev) | recommended | three-container topology per [local-dev-docker-guide.md](../targetsetup/local-dev-docker-guide.md). Required if the target's CI script invokes `docker compose exec`. |
| `.gitignore` covering `.env`, `.env.docker`, `node_modules/`, `__pycache__/`, etc. | recommended | prevents committing secrets and build junk |

### 4.1 The `scripts/ci.sh` bootstrap problem (read before kickoff)

**The trap:** the factory invokes `scripts/ci.sh` at every story-level CI gate. Most BMAD plans dedicate one story late in epic 1 to the canonical CI implementation per [ci-script-specification.md](../targetsetup/ci-script-specification.md) — Story 1.9 in PawprintRecipes, equivalents elsewhere. That story is far down the epic: stories 1.1 through 1.8 must run their CI gates *first*, against whatever ci.sh exists at kickoff.

A stub or absent ci.sh causes every early story to fail CI, burn fix_ci retries, and fail the story. The chat2diagram build hit a milder version of this and lost ~$25 to fix_ci spinning before the operator caught on. PawprintRecipes' first kickoff (2026-05-06) hit a sharper version — every story 1.1 onward failed CI because the stub referenced a docker-compose file that wouldn't exist until Story 1.2.

**The fix:** pre-write a *bootstrap* ci.sh before kickoff that does the minimum needed to keep early stories passing CI. Story 1.9 will replace it with the canonical version when its turn comes.

#### What the bootstrap ci.sh must do

1. **Accept the factory's flags**: `--story X-Y`, `--quick`, `--test-only`. The factory's `run_ci_node` always passes `--story X-Y`. Unknown flags MUST exit non-zero.
2. **Phase 0 — doc-only short-circuit**: detect via `git diff --name-only HEAD` plus `git ls-files --others --exclude-standard`. If every changed/new path is under `_bmad-output/`, `docs/`, `lessons-learned/`, `epic-reviews/`, `targetsetup/`, or root `*.md`, exit 0 in <2s. This makes Story 1.1 (typically a doc-only spike) pass cleanly without doing any work.
3. **Skip-when-missing for every other phase**: wrap each phase in `if [ -d <stack-dir> ]; then ...; fi` so missing tooling, missing source dirs, and missing config files all produce a friendly skip instead of a crash. Each phase activates progressively as later stories add their parts of the codebase.
4. **A clear `# WILL BE REPLACED BY STORY 1.9` header comment** so when the dev agent runs that story it knows to fully replace the script rather than extend it.

The Phase 0 logic is stack-agnostic — copy verbatim from either reference example below. The skip-when-missing pattern is also stack-agnostic.

#### Reference implementations

| Project | Stack | Lines | Path |
|---|---|---|---|
| **chat2diagram** | Next.js + Drizzle + Postgres | 174 | `chat2diagram/scripts/ci.sh` |
| **PawprintRecipes** | Django + Next.js + Django staff + Postgres + Redis + Celery + Mailpit | ~210 | `PawprintRecipes/scripts/ci.sh` |

Pick the closer match, copy, and adapt.

#### What changes per stack

Phase 0 (doc short-circuit) and the flag parsing are universal. Phase 1 (lint + typecheck) and Phase 3 (tests) are where each stack diverges:

| Stack | Phase 1 — lint + typecheck | Phase 3 — story-scoped tests | Phase 4 — e2e |
|---|---|---|---|
| **Node-only** | `npx eslint .` + `npx tsc --noEmit` + `npx prettier --check` | `npx vitest run --passWithNoTests -t "story_X_Y\|Story_X_Y\|X-Y"` with full-suite fallback if zero matched | `npx playwright test --grep "story.X_Y"` |
| **Python-only** | `ruff check <src>` + `mypy <src>` | `pytest -k "story_X_Y or Story_X_Y" <src>` — treat exit 5 (no tests collected) as success in `--story` mode | n/a or `pytest -m e2e` |
| **Go-only** | `golangci-lint run` + `go vet ./...` | `go test -run "Story_X_Y" ./...` (Go's `-run` is regex over test names) | n/a or separate `go test ./e2e/...` |
| **Django + Next.js** | `ruff` + `mypy` on `backend/` and `staff/`; `eslint` + `tsc` on `web/` | `pytest -k` on backend, `vitest -t` on web (each phase wrapped in dir-exists check) | `playwright test` against `docker-compose.test.yml` |
| **Mixed (other)** | union of the above | union of the above | whichever frontend has e2e |

Each story-scoped test runner MUST have a **full-suite fallback when zero tests match the filter** — otherwise stories whose tests don't yet exist silently get green-lit. PawprintRecipes' ci.sh uses `pytest` exit-5 detection for backend and `vitest --reporter=json` parse-and-check for web.

#### Phase 0 skeleton (copy verbatim)

```bash
#!/usr/bin/env bash
# CI script for <project> — bootstrap version. WILL BE REPLACED BY STORY 1.9.
set -euo pipefail

STORY_FILTER=""; QUICK_MODE=false; TEST_ONLY=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --story)     STORY_FILTER="$2"; shift 2 ;;
        --quick)     QUICK_MODE=true; shift ;;
        --test-only) TEST_ONLY=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# Phase 0: doc-only short-circuit — works in any stack
if [ -n "$STORY_FILTER" ] && [ -d .git ]; then
    CHANGED=$({
        git diff --name-only HEAD 2>/dev/null || true
        git ls-files --others --exclude-standard 2>/dev/null || true
    } | sort -u)
    if [ -n "$CHANGED" ]; then
        CODE_FILES=$(echo "$CHANGED" | grep -Ev '^(_bmad-output/|docs/|lessons-learned/|epic-reviews/|targetsetup/|[^/]*\.md$)' || true)
        if [ -z "$CODE_FILES" ]; then
            echo "=== Story $STORY_FILTER is documentation-only — short-circuiting ==="
            exit 0
        fi
    fi
fi

# Stack-specific phases follow — each wrapped in 'if [ -d <dir> ]; then ...; fi'
# See PawprintRecipes/scripts/ci.sh for the full Django + Next.js pattern.
```

This skeleton plus the matching reference implementation is enough to keep every early story passing CI until Story 1.9 (or its equivalent) replaces it.

---

## 5. Railway provisioning — per-target staging

Per-target Railway project (separate from the shared shipyard relay). Use the **single-attempt-then-verify** discipline religiously — `railway add` is not idempotent and silent output is normal. Full procedure: [railway-setup-guide.md](../gauntlet_docs/railway-setup-guide.md).

Minimum services to stand up per target:

| Service | Purpose | Created via |
|---|---|---|
| `Postgres` | UAT database | `railway add --database postgres` |
| `mailpit` | UAT email capture (web UI on port 8025) | `railway add --image axllent/mailpit:latest --service mailpit` |
| `<TargetName>` | the app itself | `railway add --service <TargetName>` (link to GitHub repo from dashboard) |

Then the app-service env vars (use `${{Postgres.DATABASE_URL}}` reference variables — never resolved strings) per [railway-setup-guide.md §6](../gauntlet_docs/railway-setup-guide.md).

> ⚠️ Current Railway CLI is linked to project `chat2bpmn`. Before provisioning PawprintRecipes, run `railway init --name PawprintRecipes` (or `railway link --project PawprintRecipes` if already created from the dashboard).

---

## 6. Per-target config — `factory.yaml` and `.env`

Each target keeps its own `factory.yaml` and `.env`. Operator-level secrets (LangSmith API key, relay key, git identity) live in **one** file at `shipyard/.env.shared`. The pre-flight script (§9) stages these into `shipyard/factory.yaml` and `shipyard/.env` for the duration of a run, then removes them on exit. This is what makes interleaved multi-target builds safe — see §10.

### File layout

```
shipyard/
├── .env.shared              # operator secrets (gitignored, persistent)
├── .env.shared.example      # template for .env.shared
├── .env.target.example      # template for <target>/.env
├── factory.yaml.example     # template for <target>/factory.yaml
├── scripts/preflight.sh     # the wrapper that stages everything

<target>/
├── factory.yaml             # per-target factory config (committed in target repo)
└── .env                     # per-target env vars (gitignored in target repo)
```

### `shipyard/.env.shared` — operator-level

```ini
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
SHIPYARD_RELAY_URL=https://shipyard-production-29ae.up.railway.app
SHIPYARD_RELAY_KEY=<shared-secret>
GIT_AUTHOR_NAME=<Your Name>
GIT_AUTHOR_EMAIL=<your@email>
```

These don't change per target. Lives in shipyard root, gitignored.

### `<target>/.env` — target-level

```ini
LANGCHAIN_PROJECT=<TargetName>
GIT_REMOTE_ORIGIN=https://<github-pat>@github.com/<user>/<repo>.git
GIT_REMOTE_MIRROR=
```

Lives in the target repo, gitignored there. Pre-flight concatenates this with `.env.shared` to build `shipyard/.env`.

> ⚠️ `GIT_REMOTE_ORIGIN` is rewritten into the target's `origin` remote on every run by `init_project_node`. The per-target layout is what stops a stale chat2diagram value from clobbering PawprintRecipes' remote (and vice versa).

### `<target>/factory.yaml`

Same shape as before, but lives in the target repo. Copy from [`factory.yaml.example`](../factory.yaml.example) and fill in. Per-node model selections can vary per target — see [cost-analysis.md](../gauntlet_docs/cost-analysis.md).

If the operator answers the brownfield/greenfield prompt at runtime, `save_ci_fix_pre_existing()` mutates the staged file; pre-flight detects that and copies it back to `<target>/factory.yaml` on exit so the answer persists.

---

## 7. Pre-flight smoke tests (run by `preflight.sh` automatically)

The preflight script runs the smoke tests for you. Listed here for reference and for the case where you want to run them manually first:

```bash
# 1. Claude Code reachable
claude --print "ready" --output-format text

# 2. Factory imports cleanly
cd shipyard && python -c "from src.main import main; print('ok')"

# 3. Relay healthy
curl -sf https://shipyard-production-29ae.up.railway.app/health

# 4. Target git remote authenticates without prompting
git ls-remote $GIT_REMOTE_ORIGIN | head -3

# 5. Railway project has Postgres, mailpit, and the app service (run manually before first build)
railway status --json | python -c "import json,sys; print(sorted(s['name'] for s in json.load(sys.stdin).get('services', [])))"

# 6. Local dev stack is up (if target uses Docker dev — recommended)
cd <target-dir> && docker compose ps
```

Items 1–4 are checked by `preflight.sh`. Items 5 and 6 stay manual — they're operator-driven setup, not per-run validation.

---

## 8. Current status — PawprintRecipes (`c:\alcorn\AI\PawprintRecipes-wrapper\PawprintRecipes`)

Snapshot refreshed 2026-05-06 (after ci.sh bootstrap + first kickoff diagnostic loop). Verify before kickoff — items shift fast in setup phase.

### Done

| Area | Status | Evidence |
|---|---|---|
| Planning artifacts | ✅ comprehensive | `_bmad-output/planning-artifacts/` has prd, architecture, database-schema, ux-design-specification, epics.md (~14k lines, 17 epics), approved-software-versions, story-and-epic-writing-guide, test-structure-guide, email-testing-guide, NewIndex.html visual reference |
| Implementation-readiness gate | ✅ passed | `_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-05.md`; CLAUDE.md says "Phase D Implementation Readiness COMPLETE" |
| Project-level CLAUDE.md | ✅ present | `CLAUDE.md` 154 lines, source-of-truth hierarchy + critical rules + memory-system note |
| Coding standards (split per platform) | ✅ four files | `coding-standards-{android,backend,ios,web}.md` |
| Coding standards index (singular `coding-standards.md`) | ✅ redirect-to-platform-files | resolves [injection.py:69](../src/context/injection.py) Layer 1 lookup; thin index that routes agents by `[component]` tag to the right per-platform file (so they only load what they need) |
| Memory system | ✅ junction in place | per CLAUDE.md §Memory system, `.claude/memory/` with junction back from user-home |
| Targetsetup templates copied in | ✅ present | `targetsetup/ci-script-specification.md`, `local-dev-docker-guide.md`, `lessons-learned-protocol.md`, etc. — operator's reference copies of the shipyard targetsetup canon |
| `scripts/ci.sh` bootstrap version | ✅ written and committed | ~210 lines; Phase 0 doc-only short-circuit + skip-when-missing for every other phase + flag parsing per spec. Will be replaced by Story 1.9. See §4.1 for the pattern |
| `.git/` initialized + initial commit + push | ✅ | branch `main`; remote `origin = https://github.com/dmalcorn/PawprintRecipes.git`; commit `42c16f3` is the planning-artifacts seed; subsequent commit added the bootstrap ci.sh |
| GitHub repo | ✅ exists, private | `dmalcorn/PawprintRecipes` |
| `<target>/factory.yaml` | ✅ present | greenfield (`fix_pre_existing_errors: true`); LangSmith project `PawprintRecipes`; sonnet-4-6 across the board, opus-4-6 for `epic_architect` |
| `<target>/.env` | ✅ present | `LANGCHAIN_PROJECT=PawprintRecipes`; plain GitHub URL (relies on Git Credential Manager) |
| `.gitignore` | ✅ minimal bootstrap | covers `.env*`, `checkpoints/`, OS noise; Story 1.2 will extend with node_modules / .next / __pycache__ / etc. |
| Mobile implementation-artifacts archived | ✅ | `_bmad-output/implementation-artifacts/_archive/` holds 16-1-android-conventions.md and 17-1-ios-conventions.md (Phase 2/3 only — out of phase for Phase 1 web build) |
| Railway project provisioning | ✅ | `PawprintRecipes` project (id `0ca088fc-3db0-47fa-b1f3-fe083b009a10`); services: `Postgres` + `mailpit` + `PawprintRecipes` (empty until source linked); 8 env vars set on app service incl. `RAILWAY_DOCKERFILE_PATH=docker/Dockerfile.backend`; mailpit web UI at `https://mailpit-production-0987.up.railway.app` |
| chat2diagram migration cleanup | ✅ | `shipyard/factory.yaml` and `shipyard/.env` removed; both targets now use the per-target layout |

### Outstanding — must complete before kickoff

| # | Item | Why | Where to fix |
|---|---|---|---|
| 1 | **PawprintRecipes Railway service not linked to GitHub repo** | required for auto-deploy on push; without it, every push to `main` triggers Railway's auto-detect to fail (Railpack tries Go/Rust/etc., finds nothing) | Railway dashboard → PawprintRecipes service → Settings → Source → Connect Repo → choose `dmalcorn/PawprintRecipes`. Auto-deploy gets useful output once Story 1.2 commits the Dockerfile + docker stack. |
| 2 | **`DATABASE_URL` is a resolved string, not a reference variable** *(deferrable)* | Railway CLI v4.x resolves `${{ServiceName.VAR}}` references at set-time regardless of shell escaping (the railway-setup-guide.md is out of date on this). Practical impact: Postgres password rotation won't propagate. Not blocking kickoff. | Railway dashboard → PawprintRecipes service → Variables → delete `DATABASE_URL` → "+ Add → Add Reference" → choose Postgres → DATABASE_URL. The dashboard preserves the reference correctly. |
| 3 | **Postgres password surfaced in earlier conversation transcript** *(deferrable)* | when verifying env-var setup with `railway variables --kv`, the resolved `DATABASE_URL` containing the password was returned to the operator's chat. Rotatable; not exploited. | Railway dashboard → Postgres service → Settings → "Reset Password". Combine with item #2 to fix the propagation gap at the same time. |

### Intentionally deferred to Story 1.2 (do NOT pre-create)

| Item | Why deferred |
|---|---|
| `docker/docker-compose.dev.yml` + `docker-compose.test.yml` + `docker-compose.prod.yml` + `docker-compose.prod-vps.yml` | Story 1.2's ACs cover all four files plus the three Dockerfiles, the Makefile, and the initial `.env.example`. Pre-creating conflicts with the story's "fresh clone" precondition and the dev agent's verification step. |
| `docker/Dockerfile.backend` + `Dockerfile.staff` + `Dockerfile.web` | same — Story 1.2 |
| `.env.docker.example` | same — Story 1.2 |

### Factory patches applied during this setup (UNCOMMITTED in shipyard)

These were diagnosed during the first kickoff cascade (2026-05-06) and patched in [src/multi_agent/bmad_invoke.py](../src/multi_agent/bmad_invoke.py). They are **not yet committed** to shipyard — pending verification of a successful end-to-end factory run. Both are Windows-only behaviors of the npm-installed claude CLI; they are no-ops on Linux/macOS.

| Symptom | Root cause | Fix |
|---|---|---|
| Every agent invocation died in 0.0s with `[WinError 2] The system cannot find the file specified` | Python's `subprocess.Popen` on Windows doesn't honor PATHEXT, so `["claude", ...]` couldn't find `claude.CMD` (the npm-global Windows shim) | resolve at module load: `CLAUDE_BIN = shutil.which("claude") or "claude"` and use `CLAUDE_BIN` in both call sites |
| Agents received only the first line of the prompt ("...You MUST:") and refused to act | Windows `cmd.exe` argv parsing in the `.CMD` shim drops everything after the first newline in a multi-line argument | drop `cli_args.extend(["--", prompt])`; switch `stdin=subprocess.DEVNULL` → `stdin=subprocess.PIPE`; write prompt with `proc.stdin.write(prompt); proc.stdin.close()` immediately after `Popen` |

Once Story 1.1 actually completes a real run end-to-end with these patches in place, commit them to shipyard so future targets inherit the fix. Until then, future targets on Windows will hit both bugs unless they pull from working-tree.

### Optional but recommended

| Item | Why |
|---|---|
| Set Anthropic / LangSmith / GitHub PAT secrets in **Railway app service** | App service deploy will fail without them once Story 1.2 lands a real Dockerfile; the factory build doesn't need them on Railway, but the operator's UAT will |

---

## 9. Kickoff command — always via `preflight.sh`

After the items in §8 "Outstanding" are all green:

```bash
cd c:/alcorn/Gauntlet/8-Capstone/factory/shipyard
source .venv/Scripts/activate
bash scripts/preflight.sh "C:\alcorn\AI\PawprintRecipes-wrapper\PawprintRecipes"
```

Resume after pause:

```bash
bash scripts/preflight.sh "C:\alcorn\AI\PawprintRecipes-wrapper\PawprintRecipes" --resume
```

What the script does:

1. If `shipyard/factory.yaml` or `shipyard/.env` already exists (left over from a previous preflight or a different target), renames them to `.old` — they're recovery breadcrumbs, not source of truth
2. Validates that `<target>/factory.yaml`, `<target>/.env`, `shipyard/.env.shared`, and `<target>/_bmad-output/planning-artifacts/epics.md` all exist
3. Stages: copies `<target>/factory.yaml` → `shipyard/factory.yaml`; concatenates `.env.shared` + `<target>/.env` → `shipyard/.env`
4. Smoke-tests Claude CLI auth, factory imports, relay health, target git remote
5. Prompts `Proceed with the build now? [y/N]` — default **No**
   - If yes: runs `python -m src.main --rebuild <target>` (forwards `--resume` and other flags)
   - If no: prints the exact command to run later, leaves staged files in place, exits 0
6. On exit (success, failure, or Ctrl+C, but **not** when declining): copies `shipyard/factory.yaml` back to `<target>/factory.yaml` if it was mutated mid-run (preserves the brownfield/greenfield toggle answer)

Staged `shipyard/factory.yaml` and `shipyard/.env` are **not deleted** at end of run. They stay in place until the next preflight rotates them to `.old`. This means if you decline the prompt and want to kick off later, you can — the files are ready.

The factory will prompt once for the brownfield/greenfield CI scope toggle (greenfield → `fix_pre_existing_errors=true`), then begin iterating epics.

Pause / resume semantics in [factory-replication-guide.md §Pause / resume](../gauntlet_docs/factory-replication-guide.md).

Watch live at: <https://shipyard-production-29ae.up.railway.app/>

---

## 10. Multi-target multiplexing — what's safe to interleave

The point of the per-target layout is that you can **start chat2diagram, pause, switch to PawprintRecipes, pause that, come back to chat2diagram, resume — without anything stepping on anything**. The key invariants:

| Where state lives | Per target | Notes |
|---|---|---|
| Resume state (`session.json`, `phase.json`, `epic-phase.json`, `rebuild.db`, CI logs) | **`<target>/checkpoints/`** | Already namespaced by target — verified across [rebuild.py:248](../src/intake/rebuild.py#L248), [checkpoint.py:51](../src/intake/checkpoint.py#L51), [orchestrator.py:288](../src/multi_agent/orchestrator.py#L288). Switching targets never touches another target's resume point. |
| Per-target factory config | **`<target>/factory.yaml`** | Committed to target repo, copied into shipyard root by preflight, copied back on exit if mutated |
| Per-target env vars | **`<target>/.env`** | Gitignored in target repo, concatenated with `.env.shared` by preflight |
| Operator-level secrets | `shipyard/.env.shared` | Persistent in shipyard root; gitignored |
| Relay session logs (Railway) | one row per session-id in shared Postgres | Sessions coexist; the dashboard auto-detects the most recent live one |
| LangSmith traces | one bucket per `LANGCHAIN_PROJECT` | Each target's traces stay in their own bucket |
| Railway CLI link | one project at a time on the host | `railway link --project <name>` on each context switch — only matters for setup/maintenance, not factory runs |

**Multiplexing footgun to know about:** if you run preflight for chat2diagram and decline the prompt, then run preflight for PawprintRecipes and decline that too, the staged files in shipyard root now belong to PawprintRecipes (chat2diagram's are saved as `.old`). If you then run the chat2diagram kickoff command from your terminal history, the build will run *against chat2diagram's source* but use *PawprintRecipes' factory.yaml*. To avoid this: re-run preflight for the target you actually want before kicking off, any time you're not sure what's currently staged.

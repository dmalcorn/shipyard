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
> - [target-templates/local-dev-docker-guide.md](../gauntlet_docs/target-templates/local-dev-docker-guide.md) — three-container local dev (app + db + mailpit)
> - [target-templates/ci-script-specification.md](../gauntlet_docs/target-templates/ci-script-specification.md) — what `scripts/ci.sh` must accept and emit

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
| `scripts/ci.sh` | required (auto-generated if missing AND `approved-tech-stack.md` exists) | invoked at every CI gate; must accept `--story X_Y`, `--epic N`, etc. per [ci-script-specification.md](../gauntlet_docs/target-templates/ci-script-specification.md) |
| `CLAUDE.md` | recommended | per-target rules + lessons-learned Tier 2; loaded by every Claude CLI invocation |
| `Dockerfile` (production) + `docker-compose.yml` (local dev) | recommended | three-container topology per [local-dev-docker-guide.md](../gauntlet_docs/target-templates/local-dev-docker-guide.md). Required if the target's CI script invokes `docker compose exec`. |
| `.gitignore` covering `.env`, `.env.docker`, `node_modules/`, `__pycache__/`, etc. | recommended | prevents committing secrets and build junk |

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

Snapshot taken 2026-05-06. Verify before kickoff — items shift fast in setup phase.

### Done

| Area | Status | Evidence |
|---|---|---|
| Planning artifacts | ✅ comprehensive | `_bmad-output/planning-artifacts/` has prd, architecture, database-schema, ux-design-specification, epics.md (~14k lines, 17 epics), approved-software-versions, story-and-epic-writing-guide, test-structure-guide, email-testing-guide, NewIndex.html visual reference |
| Implementation-readiness gate | ✅ passed | `_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-05.md`; CLAUDE.md says "Phase D Implementation Readiness COMPLETE" |
| Project-level CLAUDE.md | ✅ present | `CLAUDE.md` 154 lines, source-of-truth hierarchy + critical rules + memory-system note |
| Coding standards (split per platform) | ✅ four files | `coding-standards-{android,backend,ios,web}.md` |
| Memory system | ✅ junction in place | per CLAUDE.md §Memory system, `.claude/memory/` with junction back from user-home |
| Targetsetup templates copied in | ✅ present | `targetsetup/ci-script-specification.md`, `local-dev-docker-guide.md`, `lessons-learned-protocol.md`, etc. — operator's reference copies of the shipyard target-templates |
| `scripts/ci.sh` exists | ✅ stub present | 62 lines, backend-only; factory will skip auto-generation since the file exists |

### Outstanding — must complete before kickoff

| # | Item | Why | Where to fix |
|---|---|---|---|
| 1 | **No `.git/` directory** | factory will `git init` and create `master` branch automatically — fine, but means there's no GitHub remote yet | run `git init` + `gh repo create dmalcorn/PawprintRecipes --private --source=. --remote=origin` from inside the target |
| 2 | **`scripts/ci.sh` is a stub, not the contract-compliant script** | Current ci.sh has no `--story X_Y`, no `--epic N`, no doc-only short-circuit, references `docker/docker-compose.dev.yml` which doesn't exist. Factory CI gates will fail at first invocation. | Either (a) rewrite per [ci-script-specification.md](../gauntlet_docs/target-templates/ci-script-specification.md), or (b) delete it and add `_bmad-output/approved-tech-stack.md` so the factory generates a proper one. **(a) recommended** — operator already drafted the structure |
| 3 | **No `_bmad-output/approved-tech-stack.md`** | factory expects this exact filename and path. Target has `_bmad-output/planning-artifacts/approved-software-versions.md` — different file, different path. Only matters if option (b) above is chosen for ci.sh; otherwise irrelevant | copy/symlink approved-software-versions.md content to `_bmad-output/approved-tech-stack.md` if going route (b) |
| 4 | **No `_bmad-output/planning-artifacts/coding-standards.md` (singular)** | factory's Layer 1 context injection ([injection.py:69](../src/context/injection.py)) reads this exact path. With four split coding-standards-*.md files instead, agents lose Layer 1 standards context. Silent quality hit, not a crash. | create `coding-standards.md` that either (a) consolidates the four, or (b) is a stub that points at the four with section anchors |
| 5 | **No `Dockerfile` / `docker-compose.yml` for local dev** | Three-container topology (app + db + mailpit) per [local-dev-docker-guide.md](../gauntlet_docs/target-templates/local-dev-docker-guide.md) is required for the operator to UAT each story. The current `scripts/ci.sh` already references `docker/docker-compose.dev.yml`. | architect-generate or hand-write following the template; place under `docker/` or repo root |
| 6 | **No `.env.docker` / `.env.docker.example`** | docker-compose template needs these to start | follow [local-dev-docker-guide.md §The .env.docker file](../gauntlet_docs/target-templates/local-dev-docker-guide.md) |
| 7 | **Railway project not provisioned** | CLI is currently linked to `chat2bpmn`, not PawprintRecipes. No Postgres, no Mailpit, no app service. | follow [railway-setup-guide.md](../gauntlet_docs/railway-setup-guide.md) end-to-end. Project name MUST be exactly `PawprintRecipes` (one word, exact casing) |
| 8 | **GitHub repo not created** | factory pushes to `origin`; pre-create as empty (no README, no LICENSE) so first push lands cleanly | `gh repo create dmalcorn/PawprintRecipes --private`. After first push, switch default branch to `master` per [git-remote-setup-guide.md §2](../gauntlet_docs/git-remote-setup-guide.md) |
| 9 | **No `<target>/.env` for PawprintRecipes** | Per §6 each target carries its own .env. Without it, `preflight.sh` will refuse to start. | copy `shipyard/.env.target.example` to `c:\alcorn\AI\PawprintRecipes-wrapper\PawprintRecipes\.env` and fill in `LANGCHAIN_PROJECT=PawprintRecipes` + `GIT_REMOTE_ORIGIN` |
| 10 | **No `<target>/factory.yaml` for PawprintRecipes** | Same reason. | copy `shipyard/factory.yaml.example` to `c:\alcorn\AI\PawprintRecipes-wrapper\PawprintRecipes\factory.yaml`; fill in `target_repo`, `target_remote_url`, `target.dir` (`"C:\\alcorn\\AI\\PawprintRecipes-wrapper\\PawprintRecipes"`), `langsmith.project` |
| 11 | **chat2diagram still has its config in `shipyard/.env` and `shipyard/factory.yaml`** (legacy single-target layout) | The current shipyard root contains chat2diagram's last working config. Migrating it out *before* the first preflight run prevents accidental loss when preflight regenerates those files. | manually create `c:\alcorn\Gauntlet\8-Capstone\chat2diagram\.env` (target bits from `shipyard/.env`) and `c:\alcorn\Gauntlet\8-Capstone\chat2diagram\factory.yaml` (current `shipyard/factory.yaml` as-is); then delete `shipyard/factory.yaml` and `shipyard/.env` (not `.env.shared`). After this, both targets are set up symmetrically |

### Optional but recommended

| Item | Why |
|---|---|
| Delete or archive `_bmad-output/implementation-artifacts/16-1-android-conventions.md` and `17-1-ios-conventions.md` | These were authored Phase 1 but Phase 1 is **web-only**. Mobile conventions belong in Phase 2/3 prep. Keep them in `_archive/` to prevent the factory's BMAD agents from picking them up out of phase |
| Verify `.gitignore` | Should cover `.env*`, `node_modules/`, `__pycache__/`, `.next/`, `*.pyc`, `staticfiles/`, etc. before first commit |
| Set Anthropic / LangSmith / GitHub PAT secrets in **Railway app service** | App service won't deploy successfully without them; the build itself doesn't need them on Railway, but the operator's UAT will |

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

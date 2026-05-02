# Factory Replication Guide

How to stand up a Shipyard-style factory against a new target project from scratch. Written from the chat2diagram run (April 2026) — every step here was actually exercised end-to-end.

Sister documents:
- [git-remote-setup-guide.md](git-remote-setup-guide.md) — branch/PAT setup for the target repo's remotes
- [bmad-skill-setup-guide.md](bmad-skill-setup-guide.md) — adapting BMAD agents for autonomous use
- [How-to-extract-db-logs.md](How-to-extract-db-logs.md) — pulling pipeline logs off Railway for forensics
- [factory-lessons-from-chat2diagram.md](factory-lessons-from-chat2diagram.md) — what went wrong and how we learned

---

## What this factory is, in one paragraph

Shipyard is a Python LangGraph pipeline that drives Claude Code subprocesses against a *separate* target git repository. The factory and the target are two distinct repos on disk; the factory commits, pushes, and tags inside the target repo via `subprocess.run(..., cwd=target_dir)`. Nothing about the factory leaks into the target's package manifest, dependencies, or git history beyond the planning artifacts and the code agents produce. The relay/dashboard runs on Railway — a third repo — so observability is decoupled from the build itself.

That separation is the most important architectural fact. The factory can be developed, restarted, and even redeployed without touching the target's git history. Conversely, the target can be cloned, tested, and deployed independently of the factory.

---

## Architecture at a glance

```
┌──────────────────────────┐                 ┌────────────────────────────┐
│  shipyard/  (factory)    │                 │  chat2diagram/  (target)   │
│                          │                 │                            │
│  ├─ src/                 │  subprocess.run │  ├─ src/                   │
│  │  ├─ agent/            │ ───────────────▶│  ├─ scripts/ci.sh          │
│  │  ├─ multi_agent/      │  cwd=target_dir │  ├─ drizzle/               │
│  │  └─ intake/           │                 │  ├─ _bmad-output/          │
│  ├─ scripts/             │                 │  │  ├─ planning-artifacts/ │
│  ├─ factory.yaml         │                 │  │  └─ implementation-…    │
│  ├─ .env  (secrets)      │                 │  └─ checkpoints/           │
│  └─ checkpoints/         │                 │     ├─ session.json        │
│                          │                 │     └─ phase.json          │
└────────────┬─────────────┘                 └──────────┬─────────────────┘
             │                                          │
             │ HTTP POST events                         │ git push
             ▼                                          ▼
┌──────────────────────────────┐         ┌──────────────────────────────┐
│  shipyard-production         │         │  github.com/<user>/<target>  │
│  .up.railway.app  (relay)    │         │                              │
│                              │         │  + Railway deploys target    │
│  ├─ src/log_relay.py         │         │    via DOCKERFILE on push    │
│  ├─ Postgres                 │         └──────────────────────────────┘
│  │  ├─ sessions table        │
│  │  └─ log_events table      │
│  └─ Static dashboard         │
└──────────────────────────────┘
```

Three repos, three responsibilities:
- **shipyard** drives the build
- **chat2diagram** *is* the build
- **shipyard-production-relay** records the build for humans to watch

---

## Where things actually run — the host-vs-Docker question

This was a recurring source of confusion during the chat2diagram build, so it's worth nailing down explicitly. There are **four distinct execution contexts** in play, and they often get conflated:

1. **The factory build** (this conversation's 30 hours of work producing chat2diagram source code)
2. **The target's local dev** (a developer running `npm run dev` after the build, to iterate)
3. **The target's CI/test** (running `bash scripts/ci.sh` against the target source)
4. **The target's production runtime** (the deployed app serving HTTP traffic)

Each of those runs in a different place and uses different tools.

### Per-context execution

| Context | Where it runs | Container? | Notes |
|---|---|---|---|
| Factory orchestrator (Python LangGraph) | Operator's laptop | No (host mode) — see below for Docker mode | Host mode is what the chat2diagram build used. |
| Factory's BMAD agent subprocesses (Claude Code CLI) | Operator's laptop | No | Spawned as host subprocesses of the factory; share its CWD scoping. |
| Target build commands during the factory loop (`npm`, `npx`, `vitest`, `tsc`, `drizzle-kit`, `next build`) | Operator's laptop | No | All invoked via `bash -c "..."` from the factory's host subprocess. Same Windows shim resolution applies. |
| Target's local dev server (`npm run dev`) — *after* the factory finishes | Operator's laptop | No | Plain Next.js dev server. |
| Target's `scripts/ci.sh` invocations during build | Operator's laptop | No | Same as above — host bash. |
| Target's deployment build on Railway | Railway's cloud | **Yes — Linux container** | Railway runs `docker build` against the target's Dockerfile, on push to main. The image becomes the deployed app. |
| Target's production runtime | Railway's cloud | **Yes — Linux container** | The image from the previous step, serving HTTP. |
| Target's production Postgres | Railway's cloud | **Yes — Linux container** | Provisioned via Railway's Postgres add-on. |
| Relay service runtime | Railway's cloud | **Yes — Linux container** | Same shape as the target's runtime, but a separate Railway project. |
| Relay's Postgres | Railway's cloud | **Yes — Linux container** | Backs the dashboard's session/event store. |

The pattern: **everything operator-side is on the host. Everything cloud-side is in Linux containers on Railway.** There is no host-side container for either the factory or the target during the build.

### The factory's two modes

The factory does have a Docker mode for *itself*, but it's not the default and it's all-or-nothing:

| Mode | How it's invoked | Where the factory Python runs | Where target builds run |
|---|---|---|---|
| **Host mode** (default, used for chat2diagram) | `python -m src.main --rebuild <target>` | Operator's laptop | Operator's laptop (subprocess of the factory) |
| **Docker mode** (defined by `docker-compose.rebuild.yml`) | `docker compose -f docker-compose.rebuild.yml up` | Inside `rebuild` container | Inside the **same** `rebuild` container — target is mounted at `/app/workspace` |

There is no hybrid. In Docker mode the factory's bash subprocesses run *inside* the container, which means Linux paths and Linux-shim resolution. In host mode it's all Windows + Git Bash + `npx.cmd` shims. They produce the same output (committed code) but the runtime characteristics differ.

The chat2diagram build used **host mode**. Five pieces of evidence in the relay logs confirm this:
- `[WinError 2]` for npx subprocess invocations (Linux-only error wouldn't appear)
- All paths are `C:\alcorn\…` (Linux mounts would be `/app/workspace/…`)
- `taskkill /F /T /PID …` worked when killing the runaway pipeline (Windows process tree, host-only)
- The `bash -c "npx prettier --write ."` fix (`a43564b`) was specifically needed because Windows `subprocess.run` can't resolve `.cmd` shims (irrelevant in Linux containers)
- The husky pre-commit hook found `prettier` only after `node_modules\.bin\` was repopulated by a host `npm install`

If you're on a Linux host or a Mac, host mode might "just work" without the Windows-shim fixes. Docker mode is mostly useful when the operator's machine has tooling conflicts (e.g., wrong Node major version) or when reproducing a build from CI.

### What chat2diagram's Dockerfile is for

The Dockerfile in the **target** repo (`chat2diagram/Dockerfile`) is for **production deployment to Railway only**. It is not used during the factory's build of the source code. Railway pulls the source on push, runs `docker build` in their cloud, runs `preDeployCommand` (migrate-db.ts), then serves the resulting image. None of that touches the operator's laptop.

So when someone says "this project uses Docker," they probably mean *deployment* uses Docker, not that the local build does.

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.13+ | Factory runtime |
| Node.js | 22+ | Target build/test (Next.js) |
| Git | any recent | Source control |
| Git Bash (Windows) or bash | any | The factory's bash subprocesses use `bash -c "..."` for shell scripts |
| Claude Code CLI | latest | Subprocess spawned per agent invocation |
| Railway CLI | 4.x | Optional — for psql-into-prod-DB and deploy-log inspection |
| GitHub CLI (`gh`) | latest | Optional — for PR/repo management |

Operator-level configuration assumed:
- `claude` is on `PATH` and authenticated to a Claude Code subscription with sufficient quota for the build
- Git Credential Manager (or equivalent) is configured globally so `git push https://github.com/...` works without an embedded PAT
- A GitHub account that can create repos under a known username

---

## The four authentications

Different parts of the system need different credentials. Conflating them is the most common setup mistake.

### 1. Claude Code (per-host)

The `claude` CLI logs into your Anthropic account once at the host level. The factory inherits this — every subprocess the factory spawns runs as the same logged-in user. There is no per-call API key.

```bash
claude login        # opens browser
claude --print "test"   # confirm
```

If this account loses access mid-run (subscription change, 5-hour rate window), the factory's `bmad_invoke.py` detects it and force-quits cleanly. See [factory-lessons-from-chat2diagram.md](factory-lessons-from-chat2diagram.md#auth-cascade-pattern) for the full pattern.

### 2. GitHub (target repo push)

The factory pushes commits and tags to the target's GitHub remote. Two options:

**Option A — Git Credential Manager (recommended for local runs).** GCM stores a token in the OS credential vault and serves it to git transparently. Works with `https://github.com/<user>/<repo>.git` (no PAT in the URL).

```bash
git config --global credential.helper manager
# First push prompts for browser auth; thereafter, no prompts.
```

**Option B — Embedded PAT (Docker / CI / non-interactive).** When there's no TTY for OAuth, embed a PAT in the URL via `GIT_REMOTE_ORIGIN` in shipyard `.env`. See [git-remote-setup-guide.md](git-remote-setup-guide.md) for the exact format.

Important: the factory's `init_project_node` removes the existing `origin` remote and re-adds it from `GIT_REMOTE_ORIGIN` if that env var is set. Setting `GIT_REMOTE_ORIGIN` to a stale value will silently rewrite the target's remote on every run.

### 3. Railway (relay + target deployment)

Two distinct uses:
- **Relay service** — needs Railway login if you're administering deploys; runtime auth is via `SHIPYARD_RELAY_KEY` shared between the factory and the relay app
- **Target deployment** — Railway pulls from GitHub on push; needs the GitHub repo wired to a Railway project and a Postgres add-on

Local CLI:
```bash
railway login          # interactive — opens browser
railway link           # pick project + environment + service
```

For non-interactive use (or AI agents that can't drive a browser), generate a token at `https://railway.com/account/tokens` and `export RAILWAY_API_TOKEN=...`.

### 4. LangSmith (tracing)

Each agent invocation publishes a trace to LangSmith. The API key is set in shipyard `.env`:

```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=<your-project-name>
```

Optional but extremely useful — having `LANGCHAIN_PROJECT` per target keeps build histories separate.

---

## Repository structure

### Step 1 — clone shipyard

```bash
git clone <shipyard-url> /path/to/shipyard
cd /path/to/shipyard
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Step 2 — create or clone the target repo

The target must already have:
- `_bmad-output/planning-artifacts/` containing `epics.md`, `prd.md`, `architecture.md` (BMAD planning artifacts)
- `_bmad-output/approved-tech-stack.md` (the factory uses this to generate ci.sh on first run)
- A git repo (the factory will `git init` if missing, but creating it yourself with the right `.gitignore` is cleaner)

For a brownfield rebuild, clone the existing target repo. For a greenfield project, create an empty repo and seed `_bmad-output/`.

The target should live **outside** the factory's source tree. Anywhere works, but a sibling directory keeps things tidy:

```
/projects/
├── shipyard/        ← factory
├── target-app/      ← what's being built
└── relay/           ← optional: shipyard relay service if self-hosting
```

### Step 3 — configure shipyard/.env

Copy `.env.example` to `.env` and fill in:

```ini
# Anthropic / LangSmith
ANTHROPIC_API_KEY=sk-ant-…   # only if you don't use Claude Code subscription auth
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_…
LANGCHAIN_PROJECT=<your-target-name>

# Relay (point at your deployed relay service)
SHIPYARD_RELAY_URL=https://<your-relay>.up.railway.app
SHIPYARD_RELAY_KEY=<shared-secret-with-relay>

# Pipeline-author identity for git commits
GIT_AUTHOR_NAME=Your Name
GIT_AUTHOR_EMAIL=your@email.com

# Target's git remote — leave blank if you want the factory to use whatever
# git remote is already configured in the target repo (recommended for local
# runs with GCM; required for Docker runs without a credential helper).
GIT_REMOTE_ORIGIN=
GIT_REMOTE_MIRROR=
```

`.env` is gitignored. Never commit it.

### Step 4 — configure shipyard/factory.yaml

```yaml
operator:
  first_name: "Your"
  last_name: "Name"
  email: "your@email.com"

github:
  username: "your-gh-handle"
  target_repo: "target-app"
  target_remote_url: "https://github.com/your-gh-handle/target-app.git"

git:
  author_name: "Your Name"
  author_email: "your@email.com"

langsmith:
  project: "<your-target-name>"

target:
  dir: "/absolute/path/to/target-app"   # Windows: use "C:\\path\\with\\double-backslashes"

reviews:
  story_level: true   # set false to skip per-story code reviews

ci:
  story_level: true
  fix_pre_existing_errors: false   # true = greenfield (fix everything)
                                    # false = brownfield (scope to story changes)

models:
  dev_story: claude-sonnet-4-6
  code_review: claude-sonnet-4-6
  fix_ci: claude-sonnet-4-6
  epic_review: claude-sonnet-4-6
  epic_analysis: claude-sonnet-4-6
  epic_fix_cat_a: claude-sonnet-4-6
  epic_architect: claude-opus-4-6
  epic_fix_dev: claude-sonnet-4-6
```

The model selections matter — see [cost-analysis.md](cost-analysis.md) for the per-node tradeoffs. Architect-tier nodes (epic-level review, architecture decisions) use Opus; per-story dev work uses Sonnet.

---

## Relay service setup (Railway)

The relay is a small FastAPI service plus Postgres. It's optional — the factory works fine with `SHIPYARD_RELAY_URL` blank, you just lose the live dashboard. But the relay enables two things that proved invaluable during the chat2diagram run:

1. **Live dashboard** at `https://<your-relay>.up.railway.app/` — anyone with the URL can watch a build happen
2. **Forensic log replay** — every event is queryable for hours/days after the build, which made the post-incident analyses in this run possible

### Deploy

The relay's source is the same `shipyard/` repo (it shares code with the factory CLI for the schema). Deploy procedure:

1. Create a new Railway project, add a Postgres add-on
2. Connect the project to the shipyard repo (or fork it)
3. Set the start command to `uvicorn src.main:app --host 0.0.0.0 --port $PORT`
4. Set environment variables on the Railway service:
   - `DATABASE_URL` (Railway provides this automatically when Postgres is attached)
   - `SHIPYARD_RELAY_KEY=<generate-a-secret>` — must match what's in shipyard `.env`
5. Deploy — Railway will run `ensure_schema()` on startup, creating the `sessions` and `log_events` tables

The relay accepts authenticated POST events from the factory (`SHIPYARD_RELAY_KEY` in the Authorization header) and serves the dashboard publicly. There is no auth on read endpoints by design — the dashboard is meant to be shareable.

### Log extraction

For after-the-fact analysis, use [How-to-extract-db-logs.md](How-to-extract-db-logs.md) and `scripts/extract_log.py` (already in the shipyard repo). This pulls every event for a given session into a JSON file you can analyze locally. **This was the key to the continuous-improvement loop during the chat2diagram run** — see the lessons doc for the workflow.

---

## First run

### Pre-flight — confirm everything is wired

```bash
# Claude Code
claude --print "ready" --output-format text

# Target git remote
cd /path/to/target-app && git remote -v

# Relay reachable
curl https://<your-relay>.up.railway.app/health

# Factory imports cleanly
cd /path/to/shipyard && source .venv/Scripts/activate
python -c "from src.main import main; print('ok')"
```

### Kick off

```bash
cd /path/to/shipyard
python -m src.main --rebuild /path/to/target-app
```

The factory will:
1. Load `factory.yaml` and prompt for the brownfield/greenfield CI scope toggle
2. Read `_bmad-output/planning-artifacts/epics.md`
3. Generate `scripts/ci.sh` from `approved-tech-stack.md` if missing
4. Optionally configure the target's `origin` remote from `GIT_REMOTE_ORIGIN`
5. Iterate epics → stories → CS+DS → CI → fix_ci loop → git_commit
6. After each epic: dual review → triage → architect → fix-architect

### Pause / resume

- **Ctrl+C once** — graceful pause after current story completes
- **Ctrl+C twice** — force-quit, kill subprocesses, mark relay session paused
- **Resume** — same command + `--resume` flag

`checkpoints/session.json` tracks epic/story progress; `checkpoints/phase.json` tracks mid-story phase (so a Ctrl+C during fix_ci resumes at fix_ci, not at dev_story).

### Watch the build

Open `https://<your-relay>.up.railway.app/` — you should see the new session in LIVE mode within ~10 seconds of factory start.

---

## Common gotchas

### Windows: `npx`/`npm` shim resolution

The factory wraps Node tool calls in `bash -c "..."` because Python's `subprocess.run` on Windows can't resolve `.cmd` shims without a shell. If you see `[WinError 2] The system cannot find the file specified` in the factory output, that's the symptom — the fix landed in shipyard but if you're running an older version, upgrade.

### Line endings on factory.yaml

Editing `factory.yaml` on Windows can convert it to CRLF. Git diff will show every line as changed even if only three were edited. Run `python -c "open('factory.yaml','wb').write(open('factory.yaml','rb').read().replace(b'\r\n', b'\n'))"` before staging if you see this.

### Schema drift on the target's DB

If the target uses Drizzle (or any ORM with explicit migrations), the factory's `git_commit_node` now auto-runs `drizzle-kit generate` when `schema.ts` changed but no new `drizzle/*.sql` was added. This catches the case where the dev agent edits the schema but forgets to generate the matching migration. For other ORMs (Prisma, TypeORM), you'd want to add the equivalent at this point — currently only Drizzle is wired.

### Stale `node_modules/.bin/` after switching from Docker mode to host mode

If you previously ran the factory in Docker mode (or the target in `docker compose up` for local dev), the `node_modules/` on the host bind-mount can end up with executable shims pointing at Linux paths that don't resolve on Windows. The visible symptom is that husky's pre-commit hook fails with `'prettier' is not recognized` — the file is "there" but the symlink is dead, or `.bin/` is missing entirely because the volume that held it was the container's, not the host's.

Fix: from the target dir on the host, run `npm install` once. That regenerates `node_modules/.bin/` with native Windows shims (`.cmd` files instead of Linux symlinks). After that, host commits work normally.

This is purely a side effect of having tried Docker at some point — stopped containers don't cause it actively, but their leftover state on the host does.

### Two concurrent builds against the same target

Don't. The factory writes `checkpoints/session.json` and `checkpoints/phase.json` continuously, and a second instance would race. If you need a parallel build for testing, use `git worktree` to give it a separate working tree and a separate target dir.

### Rate limits / subscription expiry

The factory now detects three Anthropic auth/limit messages in agent output and force-quits cleanly:
- `does not have access to Claude` (subscription/org access lost)
- `You've hit your limit` (5-hour rate window)
- `Please login again or contact your administrator`

When this fires, you'll see `*** HALT: Anthropic auth/rate-limit signal detected` in the output, the relay session marks paused, and the process exits with code 2. Wait for the window to lift, run the pre-flight check, then `--resume`.

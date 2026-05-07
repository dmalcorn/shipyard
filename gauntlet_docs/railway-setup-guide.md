# Railway Setup Guide

How to provision a target project's Railway infrastructure (Postgres, Mailpit, app service) before kicking off the factory rebuild. This is the canonical playbook when the operator says *"set up Railway for the new target."*

**Audience:** Claude running from the shipyard repo with the operator authenticated to the Railway CLI. Operator handles initial `railway login` (browser OAuth) and any service-to-GitHub linking from the dashboard. Claude drives every other CLI step.

**Scope:** Per-target staging environment — one Railway *project* containing the target app, its Postgres, and a Mailpit service for UAT. This is **separate** from the shipyard relay (`shipyard-production-29ae` in the `clever-freedom` Railway project), which is shared infrastructure across every factory build and is **not touched here**.

## DB and dev-env topology — choose Option B

Before provisioning anything, decide explicitly how the target's local dev environment relates to Railway. This decision determines what gets built where.

**Option A — Railway-direct (anti-pattern, do NOT use):** the target's local dev runs on the host with `DATABASE_URL` and `EMAIL_HOST` pointing at Railway's services directly. No local Postgres or Mailpit. This is what the chat2bpmn and chat2diagram builds did *by accident* — a `.env` file with Railway's connection string was set somewhere in the factory's environment, and every dev/test run, every CI cycle, every UAT touched the same Railway database. Risks: tests can corrupt UAT data, UAT can corrupt tests, schema migrations get applied to a live DB during exploratory work, and there is no reproducibility on a fresh machine. Documented here so the pattern is recognizable when it shows up — never as a recommendation.

**Option B — Local Docker dev + Railway staging (the recommended path):** the target runs entirely in Docker Desktop on the operator's machine for development — three services (`app`, `db`, `mailpit`) defined in a `docker-compose.yml`. Code is bind-mounted from the host filesystem so the factory (running on host) can edit code and the app container hot-reloads. Railway hosts an *independent copy* of the same architecture for integration UAT and demo prep. Production (post-launch) replaces Railway Mailpit with a real SMTP server (typically self-hosted Postfix on a VPS) but keeps the same env-var contract. Three environments, identical app code, env-var differences only.

```
Local dev/test         Railway staging (UAT)      Production (VPS)
┌──────────────┐       ┌──────────────────┐       ┌──────────────────┐
│ docker-      │       │ Railway services │       │ App on VPS       │
│ compose.yml  │       │ (this guide)     │       │  ──SMTP──>       │
│  app + db +  │       │  app + db +      │       │   self-hosted    │
│  mailpit     │       │  mailpit         │       │   Postfix        │
└──────────────┘       └──────────────────┘       └──────────────────┘
   ↑ factory               ↑ git push to            ↑ post-launch
   writes here             GitHub triggers          deploy
                           Railway redeploy
```

**This guide documents the middle column.** For the left column (local Docker dev environment), see the target template [targetsetup/local-dev-docker-guide.md](../targetsetup/local-dev-docker-guide.md), which is copied into each target's `_bmad-output/planning-artifacts/`. For the right column, see the production VPS deployment notes (handled out of scope here).

The two environments are completely isolated. Local dev never reaches Railway's database; Railway staging never reaches the local one. This is the inverse of the chat2bpmn/chat2diagram pattern and is the explicit goal of the new setup.

## Link state drifts — re-link before every Railway operation

Independent from (and just as important as) the single-attempt-then-verify rule below: the Railway CLI's project link can revert silently between shell invocations. A `railway link --project X` succeeds, then the next `railway add` or `railway variable set` runs against a *different* project than you just linked to. Commands return success but mutate the wrong project. The most expensive failure mode is when this creates duplicate billable resources (e.g., a Postgres added to the wrong project that has to be manually deleted from the dashboard).

**Rule:** chain `railway link --project <name> && <actual-command>` in a single shell invocation. Do not assume a prior `railway link` is still in effect after any context switch — even within the same session.

**Verify the current link before any mutating command if you can't chain:**

```bash
railway status --json | python -c "import json,sys; print(json.load(sys.stdin).get('name'))"
```

If the output is not the project you expect, abort and re-link before proceeding.

**This is real and recurring** — it bit during the PawprintRecipes setup on 2026-05-06 (twice) and during the relay cleanup on 2026-05-02 (memorialized in [reference_railway_setup.md](../../../.claude/projects/c--alcorn-Gauntlet-8-Capstone-factory-shipyard/memory/reference_railway_setup.md)). Treat it as default behavior, not an edge case.

## The single-attempt-then-verify protocol

This is the most important rule in the document. It exists because the user has previously had to manually delete three duplicate Postgres services from the Railway dashboard after an agent retried `railway add` on silent output.

**Rule:** For any provisioning or mutating Railway CLI command — `railway add`, `railway link`, `railway redeploy`, `railway variables --set` — treat ambiguous, empty, or hung-looking output as **"unknown outcome,"** never as **"failure."** Run the command exactly once, then verify state before deciding whether to retry.

**Why "no output" is normal, not failure:**

| Command | Common silent-success behavior |
|---|---|
| `railway add --database postgres` | Emits "What do you need? Database" then exits with no further output. The service was created. |
| `railway add --image <img>` | No output. The service was created. |
| `railway redeploy --yes` | No output. The deploy was triggered. |
| `railway variables --set 'X=Y'` | No output. The variable was set. |
| `railway link --project <p> --service <s>` | No output. The CLI is now linked. |

**Verification — always available:**

```bash
railway status --json                       # full project state
railway variables --service <name> --kv     # all variables for a service (CONTAINS SECRETS)
```

**Before any retry:**

1. Run `railway status --json`.
2. Count services / inspect deployment status.
3. If the intended side-effect already happened, **stop**. The command succeeded.
4. Only retry if verification confirms no change from the pre-command state.

`railway add` is **not idempotent**. Each invocation creates a new service. Retrying without verification produces duplicates that have to be manually deleted from the dashboard.

## Prerequisites

### Authenticating the Railway CLI for Claude's use

The Railway CLI uses a per-machine auth token stored in `~/.railway/`. Once **any** shell on the host runs `railway login` and completes the browser OAuth flow, every subsequent shell — including the ones Claude spawns via the Bash tool — inherits the authenticated session. Claude does not need to authenticate separately.

**The pattern that works:**

1. Operator opens a VS Code terminal and runs `railway login`. The CLI opens a browser; operator approves; the token is written to `~/.railway/config.json`.
2. Operator confirms with `railway whoami`. Should show the logged-in email.
3. From that point on (until token expiry or explicit `railway logout`), Claude can drive every Railway CLI command — provisioning services, querying status, running maintenance like TRUNCATE — without re-authenticating.

**When you see `Unauthorized. Please run 'railway login' again.` in Claude's output:** that's always the operator's cue, never something Claude can fix. The auth flow is interactive browser OAuth — Claude can't drive it. Operator runs `railway login` in their VS Code terminal; Claude retries the original command.

### Other prerequisites

Confirm before running any provisioning command:

```bash
railway whoami        # should show the logged-in account
railway --version     # CLI v4.33.0 or later
```

The operator must have decided:

- Target project name (e.g., `PawprintRecipes`) — used as the Railway project name and as `LANGCHAIN_PROJECT` env var
- Whether the target app's GitHub repo is created yet (if so, it'll be linked from the dashboard after `railway init`; if not, that step happens later)

## Setup sequence

Run these in order. Each step has a *do-this* command and a *verify-this* command.

### 1. Create the Railway project

```bash
# Create
railway init --name <TargetName>

# Verify
railway status --json | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('name'))"
```

Expected: project name matches `<TargetName>`. If the operator already created the project from the dashboard, skip `init` and run `railway link --project <TargetName>` instead.

### 2. Add Postgres

```bash
# Create — ONCE only
railway add --database postgres

# Verify
railway status --json | python -c "
import json, sys
services = [s['name'] for s in json.load(sys.stdin).get('services', [])]
print('services:', services)
print('postgres count:', sum(1 for s in services if 'postgres' in s.lower()))
"
```

Expected: exactly one service whose name contains "Postgres". If output was silent and no Postgres exists yet, *something* about the auth or link state is wrong — investigate before retrying.

### 3. Add Mailpit

```bash
# Create — ONCE only
railway add --image axllent/mailpit:latest --service mailpit

# Verify
railway status --json | python -c "
import json, sys
services = [s['name'] for s in json.load(sys.stdin).get('services', [])]
print('services:', services)
"
```

Expected: services list now contains `Postgres`, `mailpit`, and (later) the app service. Same single-attempt-then-verify discipline as Postgres.

### 4. Expose Mailpit's web UI

The Mailpit web/API port (8025) needs a public domain so the operator can browse captured emails during UAT. The SMTP port (1025) stays internal — only the app talks to it.

```bash
# Generate a public domain for port 8025
railway domain --service mailpit --port 8025

# Verify
railway status --json | python -c "
import json, sys
for s in json.load(sys.stdin).get('services', []):
    if s['name'] == 'mailpit':
        print('domains:', s.get('domains', []))
"
```

Expected: at least one entry like `mailpit-production-XXXX.up.railway.app`. Save this — it goes into the app's `MAILPIT_WEB_URL` env var below.

### 5. Create the app service

If the operator wants to link to a GitHub repo for auto-deploy on push, that's done from the dashboard (Settings → Source). Otherwise:

```bash
# Create an empty service for the app
railway add --service <TargetName>

# Or if linking to GitHub repo from CLI:
# railway add --service <TargetName> --repo <github-owner/repo>
```

The app service will deploy on the first `railway up` or after the first GitHub push (if linked).

### 6. Set app-service environment variables

Use **reference variables** (`${{ServiceName.VAR}}`) for cross-service values. Reference variables resolve at deploy time and survive password rotation; never hardcode resolved URLs.

Use `--skip-deploys` when setting in sequence to avoid kicking off partial deploys mid-configuration. Trigger one clean redeploy at the end.

```bash
APP=<TargetName>
MAILPIT_DOMAIN=<the domain from step 4>

railway variables --service "$APP" --skip-deploys \
  --set "DATABASE_URL=\${{Postgres.DATABASE_URL}}" \
  --set "SMTP_HOST=mailpit.railway.internal" \
  --set "SMTP_PORT=1025" \
  --set "SMTP_USE_TLS=False" \
  --set "MAILPIT_WEB_URL=https://$MAILPIT_DOMAIN" \
  --set "LANGCHAIN_PROJECT=$APP" \
  --set "DEFAULT_FROM_EMAIL=test@yourdomain.example"
```

Then any target-specific secrets (auth keys, `NEXT_PUBLIC_*`, Anthropic API key if the target uses LLMs, etc.) — set those individually with `--skip-deploys` until the last one.

**Verify:**

```bash
railway variables --service "$APP" --kv | grep -E "^(DATABASE_URL|SMTP_HOST|MAILPIT_WEB_URL|LANGCHAIN_PROJECT)="
```

Expected: every variable listed. `DATABASE_URL` should show as a reference (e.g., `${{Postgres.DATABASE_URL}}`), not a resolved `postgres://` string. If it resolved at the CLI layer, the shell escaping was wrong — fix the quoting and re-set.

> ⚠️ `railway variables` output contains **secrets**. Don't paste it into chat, logs, or PR descriptions. Pipe through `grep` for specific names; never share full output.

### 7. Final redeploy

```bash
railway redeploy --service "$APP" --yes
```

Output is empty on success — that's normal.

**Verify the deploy started:**

```bash
railway status --json | python -c "
import json, sys
for s in json.load(sys.stdin).get('services', []):
    if s['name'].lower() != 'postgres' and s['name'] != 'mailpit':
        print(s['name'], '->', s.get('latestDeployment', {}).get('status'))
"
```

Expected: a deployment in `BUILDING`, `DEPLOYING`, or `SUCCESS`. Tail with `railway logs --service "$APP"` if you want live output.

## Final verification checklist

Before declaring the Railway setup done:

```bash
# 1. Exactly three services (or four if you added a worker), no duplicates
railway status --json | python -c "
import json, sys
services = sorted(s['name'] for s in json.load(sys.stdin).get('services', []))
print(services)
"
# Expected: ['Postgres', 'mailpit', '<TargetName>']

# 2. Mailpit web UI reachable
curl -sf "https://$MAILPIT_DOMAIN/api/v1/messages" | python -c "
import json, sys; d = json.load(sys.stdin); print('messages:', d.get('total', 0))
"
# Expected: messages: 0  (empty inbox on a fresh Mailpit)

# 3. App env vars wired
railway variables --service "$APP" --kv | grep -c "^SMTP_HOST="
# Expected: 1
```

If all three check out, the operator can kick off the factory:

```bash
python -m src.main --rebuild /path/to/<target>
```

## Common silent-success modes (don't be fooled)

| Symptom | Reality | Action |
|---|---|---|
| `railway add` exits with no "created" message | Service was created | Run `railway status --json` to confirm; do not retry |
| `railway redeploy` exits with no output | Deploy was triggered | Run `railway logs --service <s>` or check status |
| `railway variables --set` exits with no output | Variable was set | `railway variables --service <s> --kv \| grep <name>` to verify |
| `railway link` exits with no message | CLI is linked | `railway status` shows the linked project |
| `drizzle-kit push --force` in `preDeployCommand` exits 0 but creates no tables | **NOT a success — see chat2diagram lesson 005** | Use `migrate-db.ts` pattern (commit `90550fc` in chat2diagram) instead of `push` in preDeploy. Apply migrations from local machine against `DATABASE_PUBLIC_URL` if you hit it during the build. |

## What NOT to do

- **Don't retry on silent output.** That's how you get duplicate services. Verify first, always.
- **Don't hardcode resolved DATABASE_URL** between services. Use `${{Postgres.DATABASE_URL}}` so password rotation doesn't break the app and so secrets don't leak through CLI history.
- **Don't share `railway variables` output** anywhere. It contains secrets even when piped to a file.
- **Don't touch the shipyard relay project** (`clever-freedom` / `shipyard-production-29ae`). That's shared across every factory build; its repo connection is `dmalcorn/shipyard` and must stay that way (see [reference_railway_setup memory note](../../../.claude/projects/c--alcorn-Gauntlet-8-Capstone-factory-shipyard/memory/reference_railway_setup.md) for the time it got accidentally re-pointed).
- **Don't create one Railway project per environment.** Use Railway's *environments* feature within one project (`railway environment <name>`). Cross-project reference variables don't work; cross-environment ones do.
- **Don't use `drizzle-kit push --force` in a Railway `preDeployCommand`.** It can silently no-op even with exit 0 (chat2diagram lesson `005`). Use the `drizzle-orm/migrator` programmatic path in a `migrate-db.ts` script instead.

## What stays operator-driven

These are not Claude's job — the operator handles them out-of-band:

- `railway login` — opens a browser, requires human OAuth
- Linking the Railway service to a GitHub repo for auto-deploy — done from the Railway dashboard (Settings → Source). The CLI's `--repo` flag works for new services but the GitHub OAuth grant has to exist first.
- API token rotation
- Custom domain configuration
- Billing / plan changes

If a CLI step fails because authentication is stale or a GitHub grant is missing, **stop and ask the operator** — don't try to work around it.

## Cross-references

- [targetsetup/email-testing-guide.md](../targetsetup/email-testing-guide.md) — the test-time pattern Mailpit serves; explains why we need it on Railway and locally
- [factory-replication-guide.md](factory-replication-guide.md) — the broader "Railway (relay + target deployment)" section covers the relay (which this doc explicitly does NOT touch)
- [git-remote-setup-guide.md](git-remote-setup-guide.md) — embedded-PAT pattern for non-interactive GitHub auth
- [How-to-extract-db-logs.md](How-to-extract-db-logs.md) — read-only log extraction via REST API, **plus** direct DB access via `railway connect Postgres` (TRUNCATE between projects, ad-hoc SELECT, schema inspection)
- [chat2diagram lessons-learned `004`](https://github.com/dmalcorn/chat2diagram/blob/main/lessons-learned/004-railway-postgres-add-ambiguous-output.md) — the canonical writeup of the duplicate-service incident this doc exists to prevent
- [chat2diagram lessons-learned `005`](https://github.com/dmalcorn/chat2diagram/blob/main/lessons-learned/005-drizzle-kit-push-silent-failure-on-railway.md) — the silent-no-op `drizzle-kit push` pattern
- [Railway CLI reference](https://docs.railway.com/reference/cli-api) — full command reference

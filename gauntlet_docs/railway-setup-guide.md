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

### 4. Confirm Mailpit stays private — do NOT add a public domain

**Policy: Mailpit is private-network only.** Both ports (SMTP `1025` and the web UI `8025`) are reachable only via Railway's internal hostname `mailpit.railway.internal`. The app talks to it over private networking; nothing else.

Why no public domain: Mailpit listens on **two** ports inside the container. When a public domain is added without an explicit `targetPort`, Railway's auto-detection can't pick one and `CONFIGURE_NETWORK` errors out after a 5-minute timeout, marking the deployment FAILED. (Recovered case from PawprintRecipes 2026-05-06: deployment `7454d145-e75e-41fc-9246-b5352713f28b`.) Even with `--port 8025` specified, the safest posture is no public exposure at all.

```bash
# Verify mailpit has NO public service domains and NO TCP proxies.
railway status --json | python -c "
import json, sys
for s in json.load(sys.stdin).get('services', []):
    if s['name'] == 'mailpit':
        print('domains:', s.get('domains', []))
"
```

Expected: empty list. If a public domain already exists, delete it via the dashboard (Settings → Networking → remove domain) or via the GraphQL `serviceDomainDelete` mutation, then redeploy.

When the operator needs to browse captured emails during UAT (rare — most verification is via the API), spin up a temporary public domain with an explicit port, then **delete it after**:

```bash
railway domain --service mailpit --port 8025      # temporary
# ...browse mailpit-production-XXXX.up.railway.app...
# Then delete the domain from the dashboard before walking away.
```

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

railway variables --service "$APP" --skip-deploys \
  --set "DATABASE_URL=\${{Postgres.DATABASE_URL}}" \
  --set "SMTP_HOST=mailpit.railway.internal" \
  --set "SMTP_PORT=1025" \
  --set "SMTP_USE_TLS=False" \
  --set "LANGCHAIN_PROJECT=$APP" \
  --set "DEFAULT_FROM_EMAIL=test@yourdomain.example"
```

`MAILPIT_WEB_URL` is intentionally **not** set — Mailpit's web UI is not publicly reachable, and any test/UAT process that needs to query the API does so over the Railway private network (`http://mailpit.railway.internal:8025`) from inside another Railway service.

Then any target-specific secrets (auth keys, `NEXT_PUBLIC_*`, Anthropic API key if the target uses LLMs, etc.) — set those individually with `--skip-deploys` until the last one.

**Verify:**

```bash
railway variables --service "$APP" --kv | grep -E "^(DATABASE_URL|SMTP_HOST|LANGCHAIN_PROJECT)="
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

# 2. Mailpit deployment is healthy (no public reachability check — mailpit
#    is private-only by design; `railway run` injects env vars locally but
#    does NOT join Railway's private network, so curling
#    mailpit.railway.internal from outside Railway will not resolve).
railway status --json | python -c "
import json, sys
for s in json.load(sys.stdin).get('services', []):
    if s['name'] == 'mailpit':
        d = s.get('latestDeployment', {})
        print('mailpit deploy status:', d.get('status'),
              'stopped=' + str(d.get('deploymentStopped')))
"
# Expected: mailpit deploy status: SUCCESS stopped=False
# End-to-end mailpit reachability is exercised by the app's E2E test suite
# (which runs inside Railway and so DOES have private-network access).

# 3. App env vars wired
railway variables --service "$APP" --kv | grep -c "^SMTP_HOST="
# Expected: 1
```

If all three check out, the operator can kick off the factory:

```bash
python -m src.main --rebuild /path/to/<target>
```

## Renaming a service does NOT change its internal hostname

Railway's per-service `<name>.railway.internal` hostname is set at service-creation time and **does not update** when you rename the service. The dashboard tile and `RAILWAY_SERVICE_NAME` env var pick up the new name, but `RAILWAY_PRIVATE_DOMAIN` and the resolvable internal DNS entry stay locked to the original creation-time name forever.

Observed during PawprintRecipes 2026-05-09: renamed `Postgres → pawprint-postgres`, `Redis → pawprint-redis`, `mailpit → pawprint-mailpit`, `Staff → pawprint-staff`, `PawprintRecipes → pawprint-backend` to match the dev `docker-compose.yml` naming. Service names in the dashboard now match dev exactly. **Hostnames did not.** `pawprint-postgres` is still reachable internally at `postgres.railway.internal`, never `pawprint-postgres.railway.internal`.

**Implications when planning a rename:**

- **Reference variables (`${{ServiceName.VAR}}`) follow the rename** — Railway tracks references by service name, so a `${{Postgres.DATABASE_URL}}` reference becomes invalid after rename and needs to be re-set as `${{pawprint-postgres.DATABASE_URL}}`. The new reference resolves to the same URL as before (because the underlying hostname didn't change).
- **Hardcoded internal hostnames stay valid** — env vars like `SMTP_HOST=mailpit.railway.internal` keep working post-rename. Don't "helpfully" update them to the new service name; the new hostname doesn't exist and you'll break the consumer.
- **The only way to actually align hostnames** is to delete the service and recreate it with the desired name. Destructive (loses data on Postgres, Redis volumes, etc.). Not worth it for cosmetic alignment with a dev compose.
- **Recommended posture:** rename for dashboard ergonomics only when it's genuinely valuable; accept that internal hostname URLs will keep referencing the original names.

The `serviceUpdate` mutation for the rename itself is straightforward:

```bash
RAILWAY_TOKEN=$(python -c "import json; print(json.load(open(r'C:\\Users\\<user>\\.railway\\config.json'))['user']['token'])")
curl -s -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"mutation { serviceUpdate(id: \"<svc-id>\", input: { name: \"<new-name>\" }) { id name } }"}'
```

Returns `{"data":{"serviceUpdate":{"id":"...","name":"new-name"}}}` on success.

## A failed first build can lock a service into Railpack permanently

If a new service's first deploy attempts to build via Railpack (Railway's auto-detection layer) and fails, **subsequent deploys of that service ignore Dockerfile config** — even after explicitly setting `RAILWAY_DOCKERFILE_PATH`, setting `dockerfilePath` on the service instance via GraphQL, and switching `builder` between RAILPACK / NIXPACKS / etc. The Railpack-default decision sticks for the lifetime of the service.

Symptom: build logs say `using build driver railpack-v0.23.0` followed by `Railpack could not determine how to build the app.` even though the env vars and serviceInstance config look correct (and identical to a peer service that builds the Dockerfile fine). Compare via:

```bash
curl -s -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"query { service(id: \"<svc-id>\") { serviceInstances { edges { node { builder dockerfilePath } } } } }"}'
```

If the configs match a working sibling and Railpack still runs, the service is stuck.

**Fix: delete and recreate the service with env vars baked in at creation time.** Use the `serviceCreate` mutation directly so the Dockerfile env var is present *before* the first build runs:

```bash
curl -s -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "query": "mutation Create($input: ServiceCreateInput!) { serviceCreate(input: $input) { id name } }",
    "variables": {
      "input": {
        "projectId": "<project-id>",
        "environmentId": "<env-id>",
        "name": "<service-name>",
        "source": { "repo": "<owner/repo>" },
        "branch": "main",
        "variables": {
          "RAILWAY_DOCKERFILE_PATH": "docker/Dockerfile.<svc>",
          "OTHER_VAR": "..."
        }
      }
    }
  }'
```

Observed during PawprintRecipes 2026-05-09: pawprint-web created via dashboard, first build hit Railpack, ~45 min of trying to override the decision via `serviceInstanceUpdate` mutations and env var changes failed. Deleting and recreating with `variables` set in `serviceCreate` worked on the first try.

**Lesson:** when creating a new service that needs a Dockerfile, prefer `serviceCreate` with `variables` over the dashboard's "+ Create → GitHub Repo" flow. The dashboard flow does not let you set env vars before the first auto-deploy kicks off, and that auto-deploy can poison the service.

## Container PORT mismatch: Railway sets `PORT=8080`, your domain may target `3000`

Railway injects a `PORT` env var into the container — defaulting to `8080` when not set. Frameworks that respect `PORT` (Next.js `next start`, gunicorn with `--bind 0.0.0.0:$PORT`, etc.) will then listen on 8080. But the public domain's `targetPort` (set by `railway domain --port <n>`) is whatever you specified, often the dev port.

Symptom: container logs cleanly show `Ready` / `Listening at`, but the public URL returns 404 on every route. The container is listening on port A; Railway's edge is routing to port B; nothing on port B.

Fix: set `PORT` to match the `targetPort` you generated:

```bash
railway variables --service <svc> --set "PORT=3000"   # match your domain's targetPort
```

Or alternatively: harden the framework's CMD to ignore `PORT` and always bind to a fixed port (e.g. `gunicorn ... --bind 0.0.0.0:8000`), then set the domain's `targetPort` to match. Either approach works; pick one and stay consistent.

Observed during PawprintRecipes 2026-05-09: pawprint-web's `next start` bound to 8080 (Railway's default `PORT`), domain targeted 3000, every route returned 404 from the framework even though the container was healthy.

## Railway's private network is IPv6-only — Node.js fetch won't reach it by default

Inter-service communication on `*.railway.internal` traverses Railway's private network, which **does not route IPv4** between services. Containers must communicate over IPv6. This works automatically for most language runtimes (Python's `requests`, Go's `net/http`, etc.) because they honor the OS resolver.

**Node.js is the exception.** Node 18+ defaults to `verbatim` DNS ordering, but Next.js's SSR fetch (and any code using `undici`) frequently picks the IPv4 result and times out. Setting `NODE_OPTIONS=--dns-result-order=ipv6first` does **not** fix it — undici manages its own connection layer and ignores that flag.

Symptom (from Next.js SSR logs):

```
[TypeError: fetch failed] {
  [cause]: [Error [ConnectTimeoutError]: Connect Timeout Error
    (attempted addresses: 10.165.73.201:8000, timeout: 10000ms)]
}
```

Note `attempted addresses` shows only an IPv4 address. The backend is reachable on its IPv6 address but undici never tries it.

**Pragmatic workaround: route SSR fetches through the consumer's public URL.** Slower (the request goes Railway-edge → service instead of service-to-service direct), but reliable across redeploys and DNS changes:

```bash
# On the Next.js service:
railway variables --service pawprint-web --set \
  "INTERNAL_API_URL=https://<backend-public-domain>"
```

Then in code: SSR uses `INTERNAL_API_URL`, browser uses `NEXT_PUBLIC_API_URL` — both point at the public backend URL. Defeats the privacy benefit of internal networking but unblocks the deploy.

**Cleaner alternative (not yet validated):** force gunicorn / your backend to bind `[::]:8000` (IPv6 dual-stack) and use a custom undici dispatcher with `family: 6`. More code, more fragile under framework upgrades.

Observed during PawprintRecipes 2026-05-09: backend gunicorn on `0.0.0.0:8000` (IPv4 only inside the container), Next.js `fetch('http://pawprintrecipes.railway.internal:8000/...')` consistently timed out on IPv4. Pointing `INTERNAL_API_URL` at the public domain fixed every SSR route.

## `railway domain --port` may silently no-op

`railway domain --service <s> --port <n>` returns the generated URL on success, but the `--port` value is **not always persisted** to the underlying `serviceDomain.targetPort`. Symptom: the public URL returns `502 Bad Gateway` from `railway-edge` (header `X-Railway-Fallback: true`) even though the container's server logs `Listening at: http://0.0.0.0:<port>` cleanly — Railway's edge can't tell which port to route to and falls back.

Observed during PawprintRecipes Staff service setup 2026-05-09: passed `--port 8001`, got the domain back, edge returned 502 until `targetPort` was set via GraphQL.

**Verify after every `railway domain --port`** (the CLI does not surface `targetPort` — only the dashboard or GraphQL does):

```bash
RAILWAY_TOKEN=$(python -c "import json; print(json.load(open(r'C:\\Users\\<user>\\.railway\\config.json'))['user']['token'])")
curl -s -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"query { service(id: \"<service-id>\") { serviceInstances { edges { node { domains { serviceDomains { id domain targetPort } } } } } } }"}' \
  | python -m json.tool
```

If `targetPort` is `null`, fix it via the `serviceDomainUpdate` mutation. All four fields are required even though only `targetPort` is changing:

```bash
curl -s -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"mutation { serviceDomainUpdate(input: { serviceDomainId: \"<dom-id>\", domain: \"<domain>\", environmentId: \"<env-id>\", serviceId: \"<svc-id>\", targetPort: <port> }) }"}'
```

Returns `{"data":{"serviceDomainUpdate":true}}` on success; the edge picks up the new port within ~5 seconds.

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

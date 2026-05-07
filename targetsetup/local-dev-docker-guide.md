# Local Dev Docker Guide (Target Template)

How to structure the target project's local development environment so that everything runs in Docker Desktop on the operator's machine — app, database, and Mailpit — fully isolated from Railway staging and production. The factory (running on the host) edits code that's bind-mounted into the container; the app hot-reloads; tests run against local services; UAT happens at `localhost`.

This is a copy-into-target template. Place it at `_bmad-output/planning-artifacts/local-dev-docker-guide.md`. Both the bmad-architect (generating `Dockerfile` and `docker-compose.yml`) and the bmad-dev (writing scripts and tests that respect the topology) should read it.

## Why this exists

Three previous factory builds drifted into a hidden anti-pattern: the target's `.env` held a Railway `DATABASE_URL`, and every dev run, every test, every UAT touched the same Railway-hosted database. Tests could corrupt UAT data; UAT could corrupt tests; schema migrations got applied during exploratory work; the build could not be reproduced on a fresh machine because nothing was self-contained. The fix is **complete environment separation** — a local stack that is identical in shape to the Railway one but has zero connection to it.

The result: the operator can `docker compose up`, get a fully working stack at `localhost`, and **leave it running** as the routine state for development. The stack is meant to stay up — the containers idle cheaply between sessions, and `restart: unless-stopped` brings them back after host reboots. `docker compose down` and `down -v` exist for non-routine situations (port conflicts with another project, host resource pressure, DB state reset) but are not part of the daily loop. Railway is touched only when code lands on `main` and triggers a redeploy.

## The three-container topology

```
┌─ Host filesystem ────────────────────────────────────────┐
│  c:\alcorn\...\<TargetName>\                            │
│    ├── src/             (code — bind-mounted into app)  │
│    ├── docker-compose.yml                                │
│    ├── docker-compose.test.yml  (optional override)      │
│    ├── Dockerfile                                        │
│    ├── Dockerfile.dev   (optional, for the dev variant)  │
│    └── .env.docker      (env vars for the compose stack) │
│                                                          │
│  Factory (python -m src.main --rebuild ...) ─writes─┐    │
└──────────────────────────────────────────────────────│───┘
                                                       │
                                                       ▼
┌─ Docker Desktop ─────────────────────────────────────────┐
│                                                          │
│  ┌────────────┐   ┌──────────┐   ┌────────────────┐      │
│  │   app      │   │   db     │   │   mailpit      │      │
│  │            │──▶│          │   │                │      │
│  │  (Next.js  │   │ postgres │   │ axllent/       │      │
│  │  or Django │   │ :17      │   │ mailpit:latest │      │
│  │  + npm     │   │          │   │                │      │
│  │  run dev)  │   │          │   │ port 8025 →    │      │
│  │            │──SMTP───────────▶│ localhost:8025 │      │
│  │            │   │          │   │ (web UI)       │      │
│  │ port 3000 →│   │          │   │                │      │
│  │ localhost: │   │ port 5432│   │ port 1025      │      │
│  │ 3000       │   │ → 5432   │   │ (SMTP, internal│      │
│  └────────────┘   └──────────┘   │  network only) │      │
│                                  └────────────────┘      │
│                                                          │
│  Network: <project>_default (auto-created by compose)    │
└──────────────────────────────────────────────────────────┘
```

The app, db, and mailpit containers communicate by service name on the compose network (`db:5432`, `mailpit:1025`). The host reaches the app at `localhost:3000` and the Mailpit web UI at `localhost:8025`. The Postgres port is published to `localhost:5432` so the operator's IDE / SQL clients can connect.

## The `docker-compose.yml` template

```yaml
# docker-compose.yml — local development stack
# Routine:    docker compose up --watch      (leave it running between sessions)
# Stop:       docker compose down            (non-routine — keeps DB volume)
# Reset:      docker compose down -v         (non-routine — deletes DB volume; clean slate)
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile.dev
    container_name: <target>-app
    restart: unless-stopped
    ports:
      - "3000:3000"
    env_file:
      - .env.docker
    environment:
      DATABASE_URL: postgresql://<target>:<target>_dev@db:5432/<target>
      EMAIL_HOST: mailpit
      EMAIL_PORT: 1025
      EMAIL_USE_TLS: "False"
      DEFAULT_FROM_EMAIL: test@yourdomain.example
      MAILPIT_API_URL: http://mailpit:8025 # for E2E tests inside the network
    volumes:
      - .:/app # bind-mount source for hot reload
      - /app/node_modules # exclude — keep container's node_modules
      - /app/.next # exclude — keep container's build cache
    depends_on:
      db:
        condition: service_healthy
      mailpit:
        condition: service_healthy
    develop:
      watch: # docker compose --watch
        - action: sync
          path: ./src
          target: /app/src
        - action: rebuild
          path: ./package.json

  db:
    image: postgres:18
    container_name: <target>-db
    restart: unless-stopped
    ports:
      - "5432:5432" # exposed for local IDE/psql
    environment:
      POSTGRES_USER: <target>
      POSTGRES_PASSWORD: <target>_dev
      POSTGRES_DB: <target>
    volumes:
      # Postgres 18+: mount at /var/lib/postgresql (data lands in a version-major
      # subdir per pg_ctlcluster). For postgres ≤17, use /var/lib/postgresql/data.
      - pgdata:/var/lib/postgresql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U <target>"]
      interval: 5s
      timeout: 3s
      retries: 5

  mailpit:
    image: axllent/mailpit:latest
    container_name: <target>-mailpit
    restart: unless-stopped
    ports:
      - "8025:8025" # web UI + REST API
      # 1025 (SMTP) intentionally NOT exposed — only app reaches it via internal network
    healthcheck:
      test:
        [
          "CMD",
          "wget",
          "--spider",
          "-q",
          "http://localhost:8025/api/v1/messages",
        ]
      interval: 2s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

Replace every `<target>` placeholder with the actual project name (lowercase, alphanumeric — e.g., `pawprintrecipes`).

## The `Dockerfile.dev` (separate from production Dockerfile)

```dockerfile
# Dockerfile.dev — local development image for the app container
# DO NOT use for production. Production deploys via the regular Dockerfile.
FROM node:24-alpine

WORKDIR /app

# Install dependencies first for better layer caching
COPY package.json package-lock.json ./
RUN npm ci

# Code is bind-mounted at runtime — no COPY here for source files
EXPOSE 3000

CMD ["npm", "run", "dev"]
```

Why a separate dev Dockerfile:

- Production Dockerfile does multi-stage builds, prunes dev dependencies, sets `NODE_ENV=production`. None of that helps in dev.
- Dev image keeps dev dependencies (drizzle-kit, eslint, vitest) so the container can run them.
- Bind-mount means no `COPY` of source — saves rebuild time on every code change.

## Django backends — the migrate-on-start entrypoint

Django targets need an extra wrinkle: schema migrations have to run before the app server can serve a request, and they need to re-run after every model change, every `down -v` reset, and every container recreation. Without help, the operator has to remember to `make migrate` every time, and forgetting it means the container starts but every request crashes against a stale schema.

The fix is a tiny shared shell entrypoint that runs `manage.py migrate --noinput` before exec'ing the actual command — gated by an env var so it only fires in dev, never in prod.

```sh
# docker/django-entrypoint.sh — committed, used by EVERY Django service
#!/bin/sh
set -e
if [ "$RUN_MIGRATIONS_ON_START" = "true" ]; then
    echo "[entrypoint] Applying database migrations..."
    python manage.py migrate --noinput
fi
exec "$@"
```

Each Django Dockerfile wires it in identically:

```dockerfile
# Dockerfile.backend (or Dockerfile.staff, etc.) — Django dev image
# ... usual COPY requirements.txt, pip install, COPY source ...

COPY docker/django-entrypoint.sh /usr/local/bin/django-entrypoint.sh
RUN chmod +x /usr/local/bin/django-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/django-entrypoint.sh"]

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

Then in `docker-compose.dev.yml` (and ONLY in the dev compose — never `docker-compose.prod.yml` etc.), set the toggle on every Django service:

```yaml
services:
  backend:
    # ...
    environment:
      - RUN_MIGRATIONS_ON_START=true   # auto-migrate on every container start

  staff:
    # NOTE: a UI-only Django that proxies to the backend API has no DATABASES
    # setting — leave RUN_MIGRATIONS_ON_START unset there. The shared
    # entrypoint is still installed in Dockerfile.staff (no-op without the
    # env var), so the toggle is available if staff ever gains its own DB.
```

For monorepos with multiple Django apps (e.g., a customer-facing `backend/` plus an internal `staff/` template UI, both with their own `manage.py`), every Django Dockerfile installs the same shared entrypoint — but `RUN_MIGRATIONS_ON_START=true` only goes on services that **have their own `DATABASES` setting**. A UI-only Django that proxies to a backend API has no DATABASES configured, so `manage.py migrate` would crash on container start. Leave the env var unset for those services; the entrypoint becomes a no-op (`exec "$@"`), and the toggle stays available if the service ever gains its own DB schema.

The factory's orchestrator detects every `manage.py` (in `backend/`, `staff/`, etc.) and runs `makemigrations --check` against each project's container in turn. When it hits a UI-only Django (recognized by an `ImproperlyConfigured: DATABASES` error), it skips that project cleanly with one log line — no spurious auto-generate attempt.

Why dev-only via env var: production deploys want explicit, staged migrations (the deploy script runs `migrate` once before swapping containers), not every replica racing to apply migrations on startup. Setting `RUN_MIGRATIONS_ON_START` only in the dev compose keeps the same image safe for both environments.

### Recovery: when migrate-on-start hits `InconsistentMigrationHistory`

The entrypoint runs `manage.py migrate --noinput`, which calls Django's `check_consistent_history()` first. If the dev DB carries stale applied-migration state — a migration was renamed, squashed, reordered during authoring, or applied out of dependency order during a rough bootstrap — that check raises `InconsistentMigrationHistory` and the entrypoint fails. The container exits, and any `docker compose exec` against it fails with `Error response from daemon: container ... is not running`.

This is the same root cause [`ci-script-specification.md`](ci-script-specification.md) Phase 1b made hermetic via the SQLite-backed `migration_check.py` settings overlay (see [PawprintRecipes lessons-learned/003](https://github.com/dmalcorn/PawprintRecipes/blob/main/lessons-learned/003-migration-gate-ephemeral-db.md)). The CI gate validates files-on-disk against an ephemeral DB; the dev container's entrypoint, by design, validates against the **real** dev DB so it can self-heal on schema changes.

That tradeoff means the dev DB will occasionally land in inconsistent state — most often after a story squashes or reorders migrations, or after the operator manually pokes the DB. **The recovery is to wipe the volume and let migrations rebuild fresh:**

```bash
docker compose -f docker/docker-compose.dev.yml down -v
docker compose -f docker/docker-compose.dev.yml up -d
```

The `-v` removes the named Postgres volume; `up -d` starts the stack from a clean DB and the entrypoint applies all migrations in correct dependency order. This is the documented "reset" pattern from the Anti-patterns table below — the dev DB is scratch space; tests use SQLite (per `config.settings.test`) so nothing real is lost. After the reset, the entrypoint succeeds and `docker compose exec` works again.

If the operator has dev-DB state they want to keep (rare during active story work), the alternative is to run migrations manually in the right order via `docker compose exec pawprint-backend python manage.py migrate <app_label>` for each app in dependency order, but `down -v` is faster and idempotent.

When in doubt: `down -v && up -d`. Recovered from an `InconsistentMigrationHistory` entrypoint crash in PawprintRecipes Story 3-4 (2026-05-08) using exactly this recipe.

## Python dev tools in the container

The CI script ([ci-script-specification.md](ci-script-specification.md#prerequisite-dev-tools-must-be-installed-in-the-container)) dispatches backend lint, typecheck, and tests **inside** the dev backend container. That only works if the container's Python env has the tools the CI script invokes — ruff, mypy, pytest (+ pytest-django, pytest-cov), and any other `python -m <tool>` you run.

The clean separation: `requirements.txt` for runtime, `requirements-dev.txt` for CI/dev tools. The dev Dockerfile installs both; the production Dockerfile installs only `requirements.txt`.

```
backend/
├── requirements.txt          # Django, celery, drf, structlog, ...
└── requirements-dev.txt      # ruff, mypy, pytest*, django-stubs, ...
```

Dev Dockerfile (`docker/Dockerfile.<service>`):

```dockerfile
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
```

Production Dockerfile:

```dockerfile
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
```

A reasonable starter `requirements-dev.txt` for a Django target:

```
# Linting and formatting
ruff>=0.7.0,<1.0.0

# Type checking
mypy>=1.13.0,<2.0.0
django-stubs[compatible-mypy]>=5.1.0

# Optional legacy formatter — only if a story needs both ruff format AND
# black for some specific reason. Modern projects can skip.
# black>=24.0.0
```

Dev tools that are language-agnostic CLIs (bandit for Python security scan, npm audit for JS deps) stay on the operator's host — they don't import project code, so container dispatch buys nothing.

Why this matters: in PawprintRecipes Story 3-4 (2026-05-08), the CI script's Phase 1a/1b dispatch into the container hit `No module named ruff` because requirements.txt had only runtime deps + pytest. The agent had to scramble to add ruff/mypy mid-build. Getting this right at planning time avoids the scramble.

## The `.env.docker` file

```bash
# .env.docker — environment variables for `docker compose up`.
# This file is gitignored. Real values live here; .env.docker.example documents the shape.

# App secrets
NEXTAUTH_SECRET=<generate-with-openssl-rand-base64-32>
ANTHROPIC_API_KEY=sk-ant-...

# DATABASE_URL is overridden in docker-compose.yml (set there, not here)
# EMAIL_HOST and friends are also overridden in docker-compose.yml

# Anything ELSE the app needs — public-facing URLs, feature flags, etc.
NEXT_PUBLIC_BASE_URL=http://localhost:3000
```

Commit a `.env.docker.example` with the _shape_ (variable names + placeholder values) so a fresh clone knows what to fill in. The real `.env.docker` is gitignored.

## The `node_modules` wrinkle (and how it's solved)

The factory runs on the host. When `git_commit_node` stages a commit, it runs `prettier --write`, `eslint --fix`, and similar tools — these are looked up in `./node_modules/.bin/`. The container has its own `node_modules/` (as a Docker-managed anonymous volume, per the compose file above) so the host's `node_modules/` doesn't conflict with the Linux binaries inside the container.

This means **the operator must run `npm install` on the host once** before kicking off the factory, in addition to the install that happens inside the container at build time. Two `node_modules/` directories result — one Linux (in the container's volume) and one native to the host. JavaScript tooling is cross-platform, so versions stay aligned.

If you skip the host-side `npm install`, the factory's autoformat step fails with `'prettier' is not recognized` (the Windows variant of the same error chat2diagram hit; see [factory-replication-guide.md](../factory-replication-guide.md) "Stale `node_modules/.bin/` after switching from Docker mode to host mode" for the receipts).

For Django targets, the equivalent is: install Python dev dependencies on the host (`pip install -r requirements-dev.txt`) so the factory can run `ruff`, `black`, `mypy` from the host.

## How the factory and Docker dev coexist

```
1. Operator: docker compose up --watch          # start the stack
2. Operator: python -m src.main --rebuild .     # kick off factory (runs on host)
3. Factory: edits source files on host
4. Bind mount: changes appear instantly in app container
5. App: hot-reloads (Next.js / Django dev server picks up change)
6. Factory's git_commit_node: runs prettier on host, stages, commits
7. Factory: runs `npm test` or `pytest` on host (or via `docker compose exec`)
8. Operator: opens localhost:3000 to UAT each story as it lands
```

The factory **never enters the containers** for code edits. It always writes to the host filesystem. The containers see those writes through the bind mount.

For test runs, the factory has two options:

**Option 1 — Host-side test runs (simpler):** the factory runs `npm test` / `pytest` on the host, pointed at the Docker `db` (`localhost:5432`) and `mailpit` (`localhost:1025` if exposed in compose, OR via the test config) services. Requires Postgres port to be published in compose (it is, in the template above). The factory's CI script exports `DATABASE_URL=postgresql://...@localhost:5432/...` and runs tests on the host.

**Option 2 — Containerized test runs:** the factory runs `docker compose exec app npm test` so tests run inside the container with `db:5432` resolving via the internal network. More isolated, but the factory's bash subprocess has to know to wrap commands in `docker compose exec`. The factory's `run_tests` and `run_ci` nodes don't currently do this — they assume host-side execution.

**Recommendation: Option 1** for now. It matches the existing factory behavior (host-side test runs), and the published Postgres port on `localhost:5432` makes it work without changes. Mailpit's SMTP port stays internal (only the app container reaches it), but that's fine because tests query Mailpit's HTTP API at `localhost:8025`, not its SMTP port.

## Operator commands

**Routine policy:** start the stack once and leave it running. Don't tear it down at the end of a session — `restart: unless-stopped` keeps it healthy across reboots, and idle containers cost very little. `down` and `down -v` are non-routine operations; reach for them only in the situations called out below.

```bash
# Routine — start the stack once (with --watch for live reload)
docker compose up --watch

# Routine — start in detached mode (no terminal locked); leave it running
docker compose up -d

# Routine — view live logs without stopping anything
docker compose logs -f app
docker compose logs -f db

# Routine — run one-off commands while the stack stays up
docker compose exec app npm run drizzle:push          # apply schema
docker compose exec app npx tsx scripts/seed.ts        # seed dev data

# NON-ROUTINE — stop containers (keeps DB volume).
# Use only when: another project needs these ports, or you're freeing host RAM/CPU.
docker compose down

# NON-ROUTINE — stop and DELETE the DB volume (clean slate, destroys DB data).
# Use only when: local DB state is wedged, migrations are confused, or you want to re-seed.
docker compose down -v

# NON-ROUTINE — rebuild after Dockerfile.dev changes
docker compose build --no-cache app
docker compose up
```

## Required behaviors

|            |                                                                                                                                                                                                      |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **MUST**   | App container's `DATABASE_URL` resolves to the `db` service (not `localhost`, not Railway). The compose file sets this; the app code reads from env without modification                             |
| **MUST**   | `EMAIL_HOST` resolves to `mailpit` (the service name) inside the container; tests reaching Mailpit's HTTP API use `localhost:8025` from the host or `mailpit:8025` from inside the container         |
| **MUST**   | Source code is bind-mounted, NOT copied — `COPY` of source code in `Dockerfile.dev` defeats hot reload. Only dependency manifests (`package.json` / `requirements.txt`) get copied for layer caching |
| **MUST**   | `node_modules/` is a Docker-managed volume, NOT shared with the host — Linux binaries inside the container would conflict with Windows binaries the factory uses on the host                         |
| **SHOULD** | The host has its own `node_modules/` (after `npm install` on host) so factory autoformat tools can find prettier/eslint                                                                              |
| **SHOULD** | `.env.docker` is gitignored; commit `.env.docker.example` with shape only (no secrets)                                                                                                               |
| **MUST**   | The dev stack is left running between sessions — `up` once, leave it up. `down` and `down -v` are non-routine (only for port conflicts, host resource pressure, or DB state reset)                   |
| **SHOULD** | `docker compose down -v` is the documented "reset" command for when local state diverges from expected — but it is the exception, not part of the daily loop                                         |
| **SHOULD** | Production `Dockerfile` and dev `Dockerfile.dev` are separate files — production needs multi-stage build + dev-dep prune, dev needs the opposite                                                     |
| **MUST**   | Every Django service installs the shared `docker/django-entrypoint.sh` in its Dockerfile. `RUN_MIGRATIONS_ON_START=true` is set ONLY for services with their own `DATABASES` configured — and ONLY in `docker-compose.dev.yml`, never in prod compose. UI-only Django services that proxy to a backend API leave the env var unset (the entrypoint is a no-op without it)         |

## Anti-patterns

| Anti-pattern                                               | Why it hurts                                                                                                                                          | Fix                                                                                                                 |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL` in `.env` points at Railway's Postgres      | The chat2bpmn/chat2diagram failure mode — every dev run, test, and UAT touch the live staging DB; corruption between environments; no reproducibility | Use the compose file's per-service `environment:` block; `.env.docker` for app-level secrets only                   |
| Single `Dockerfile` used for both dev and prod             | Production builds keep dev-deps OR dev builds skip them — one or the other always breaks                                                              | Two files: `Dockerfile.dev` (dev) and `Dockerfile` (prod). Compose uses `Dockerfile.dev`; Railway uses `Dockerfile` |
| Sharing `node_modules/` between host and container         | Linux native deps (sharp, bcrypt) break on host; Windows native deps break in container                                                               | Use a Docker-managed volume for the container's `node_modules/`; run `npm install` on host separately for tooling   |
| `EMAIL_HOST=localhost` set on the container                | App tries to reach SMTP on the _container's_ localhost (i.e., itself), not Mailpit                                                                    | Use the service name: `EMAIL_HOST=mailpit`                                                                          |
| Skipping `--watch` mode and rebuilding on every change     | 30-60s rebuild kills dev productivity                                                                                                                 | `docker compose up --watch` syncs code changes live; only rebuilds on `package.json` changes                        |
| Forgetting `docker compose down -v` exists                 | Operator manually cleans Postgres tables, gets confused state                                                                                         | When in doubt, blow away the volume — the seed script puts data back                                                |
| Django container starts `runserver` without applying pending migrations | Container is "up" but every request crashes against a stale schema; operator forgets `make migrate` and assumes it's a code bug                       | Add the `django-entrypoint.sh` pattern; set `RUN_MIGRATIONS_ON_START=true` in dev compose so it self-heals on every start |
| Putting `RUN_MIGRATIONS_ON_START=true` in a prod compose file | Replicas race to apply migrations on rolling deploy; partial-state failure mid-rollout                                                                 | Set the env var ONLY in `docker-compose.dev.yml`. Production migrates via the deploy script, once, before swapping containers |
| Production using Mailpit's `mailpit.railway.internal` host | Real users see no email                                                                                                                               | Production env vars point at the actual SMTP server (e.g., self-hosted Postfix on a VPS); confirm at deploy time    |

## Multi-component considerations

For monorepo targets (e.g., Django backend + Next.js frontend):

- One `docker-compose.yml` with **multiple app services** — `backend`, `frontend`, `db`, `mailpit`. Each component gets its own service with its own `Dockerfile.dev`.
- The factory still writes to the host filesystem; each component's bind mount picks up changes independently.
- Backend talks to db at `db:5432`; frontend talks to backend at `backend:8000` (or whatever port).
- E2E tests live at the monorepo root, drive the frontend via Playwright, hit Mailpit's API for email assertions. Same pattern as [email-testing-guide.md](email-testing-guide.md) describes.

For mobile components (future): Kotlin / Swift apps don't run in Docker; they run on the operator's emulator or device. They talk to the backend service at `localhost:8000` (or the Docker host's IP). The local Docker stack still works as the backend; the mobile dev environment lives outside Docker.

## How the bmad-architect agent should use this guide

When generating Dockerfile + docker-compose.yml for a new target, the architect MUST:

1. Generate `Dockerfile` (production, multi-stage) AND `Dockerfile.dev` (local dev) as separate files
2. Generate `docker-compose.yml` matching the template above with the `<target>` placeholders filled in
3. Generate `.env.docker.example` with shape only — no secret values
4. Add `.env.docker` to `.gitignore`
5. Reference this guide in the target's `README.md` so future operators know the topology
6. **For Django targets:** generate `docker/django-entrypoint.sh` (the shared migrate-on-start script), wire it into every Django Dockerfile via `COPY` + `chmod +x` + `ENTRYPOINT`, and set `RUN_MIGRATIONS_ON_START=true` in `docker-compose.dev.yml` ONLY on Django services that have their own `DATABASES` setting. UI-only Django services that proxy to a backend API (e.g., a staff panel) install the entrypoint but leave the env var unset — the entrypoint is a no-op without it, and the toggle remains available if the service ever gains its own DB. Do NOT set the env var in any prod compose file

The architect SHOULD also coordinate with the [ci-script-specification.md](ci-script-specification.md): the CI script's Phase 1b (DB schema sync) needs to use `localhost:5432` (when run on host) or `db:5432` (when run inside compose). The compose file makes both work because the host port is published.

## How the bmad-dev agent should use this guide

When implementing any story whose acceptance criteria touch the database, email, or external services, the dev agent MUST:

1. Assume the local Docker stack is running (operator's responsibility before kickoff)
2. Use service names (`db`, `mailpit`) in app code env vars, NOT `localhost` and NOT Railway hostnames
3. Write tests that work against the local stack — `localhost:5432` for DB, `localhost:8025` for Mailpit's HTTP API
4. Never edit `docker-compose.yml` to add ad-hoc test services — use `docker-compose.test.yml` overrides if test-only services are needed (see [email-testing-guide.md](email-testing-guide.md))

## How the operator validates the dev setup

Before kickoff:

```bash
docker compose up -d --wait
docker compose ps                              # all three services should show "running (healthy)"
curl -sf http://localhost:3000/                # app reachable
curl -sf http://localhost:8025/api/v1/messages # Mailpit API reachable
docker compose exec db psql -U <target> -c '\l' # DB reachable, lists databases
```

If all four commands succeed, the stack is ready for the factory.

## Updating this guide

Update when a real factory build surfaces a topology problem this guide didn't anticipate. Add the failure mode to the anti-patterns table with a one-line _receipt_ (which build, what broke). Don't add hypothetical anti-patterns — only ones with traceable history.

## See also

- [email-testing-guide.md](email-testing-guide.md) — the Mailpit pattern this guide builds on; the email guide is the test-side, this guide is the dev-environment side
- [test-structure-guide.md](test-structure-guide.md) — test pyramid; tests run on the host pointed at the local Docker services
- [ci-script-specification.md](ci-script-specification.md) — Phase 1b (DB schema sync) and the CLI flags the factory expects from `scripts/ci.sh`
- [../railway-setup-guide.md](../railway-setup-guide.md) — the Railway side; this guide is the local side; together they form the Option B topology
- [../factory-replication-guide.md](../factory-replication-guide.md) — host-vs-Docker for the factory itself (different question; the factory continues to run on host, only the target runs in Docker)
- [Mailpit documentation](https://mailpit.axllent.org/) — full REST API reference
- [Docker Compose reference](https://docs.docker.com/compose/compose-file/) — full compose file spec

# Local Dev Docker Guide (Target Template)

How to structure the target project's local development environment so that everything runs in Docker Desktop on the operator's machine — app, database, and Mailpit — fully isolated from Railway staging and production. The factory (running on the host) edits code that's bind-mounted into the container; the app hot-reloads; tests run against local services; UAT happens at `localhost`.

This is a copy-into-target template. Place it at `_bmad-output/planning-artifacts/local-dev-docker-guide.md`. Both the bmad-architect (generating `Dockerfile` and `docker-compose.yml`) and the bmad-dev (writing scripts and tests that respect the topology) should read it.

## Why this exists

Three previous factory builds drifted into a hidden anti-pattern: the target's `.env` held a Railway `DATABASE_URL`, and every dev run, every test, every UAT touched the same Railway-hosted database. Tests could corrupt UAT data; UAT could corrupt tests; schema migrations got applied during exploratory work; the build could not be reproduced on a fresh machine because nothing was self-contained. The fix is **complete environment separation** — a local stack that is identical in shape to the Railway one but has zero connection to it.

The result: the operator can `docker compose up`, get a fully working stack at `localhost`, hammer on it for hours, and `docker compose down -v` to reset to clean state with one command. Railway is touched only when code lands on `main` and triggers a redeploy.

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
# Spin up:    docker compose up --watch
# Tear down:  docker compose down            (keeps DB volume)
# Reset:      docker compose down -v         (deletes DB volume — clean slate)
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
    image: postgres:17
    container_name: <target>-db
    restart: unless-stopped
    ports:
      - "5432:5432" # exposed for local IDE/psql
    environment:
      POSTGRES_USER: <target>
      POSTGRES_PASSWORD: <target>_dev
      POSTGRES_DB: <target>
    volumes:
      - pgdata:/var/lib/postgresql/data
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

```bash
# Start the stack (with --watch for live reload)
docker compose up --watch

# Start in detached mode (no terminal locked)
docker compose up -d

# View live logs
docker compose logs -f app
docker compose logs -f db

# Run a one-off command inside the app container
docker compose exec app npm run drizzle:push          # apply schema
docker compose exec app npx tsx scripts/seed.ts        # seed dev data

# Stop containers (keeps volumes)
docker compose down

# Stop and DELETE all volumes (clean slate — destroys DB data)
docker compose down -v

# Rebuild after Dockerfile.dev changes
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
| **SHOULD** | `docker compose down -v` is the documented "reset" command — operators should reach for it whenever local state diverges from expected                                                               |
| **SHOULD** | Production `Dockerfile` and dev `Dockerfile.dev` are separate files — production needs multi-stage build + dev-dep prune, dev needs the opposite                                                     |

## Anti-patterns

| Anti-pattern                                               | Why it hurts                                                                                                                                          | Fix                                                                                                                 |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL` in `.env` points at Railway's Postgres      | The chat2bpmn/chat2diagram failure mode — every dev run, test, and UAT touch the live staging DB; corruption between environments; no reproducibility | Use the compose file's per-service `environment:` block; `.env.docker` for app-level secrets only                   |
| Single `Dockerfile` used for both dev and prod             | Production builds keep dev-deps OR dev builds skip them — one or the other always breaks                                                              | Two files: `Dockerfile.dev` (dev) and `Dockerfile` (prod). Compose uses `Dockerfile.dev`; Railway uses `Dockerfile` |
| Sharing `node_modules/` between host and container         | Linux native deps (sharp, bcrypt) break on host; Windows native deps break in container                                                               | Use a Docker-managed volume for the container's `node_modules/`; run `npm install` on host separately for tooling   |
| `EMAIL_HOST=localhost` set on the container                | App tries to reach SMTP on the _container's_ localhost (i.e., itself), not Mailpit                                                                    | Use the service name: `EMAIL_HOST=mailpit`                                                                          |
| Skipping `--watch` mode and rebuilding on every change     | 30-60s rebuild kills dev productivity                                                                                                                 | `docker compose up --watch` syncs code changes live; only rebuilds on `package.json` changes                        |
| Forgetting `docker compose down -v` exists                 | Operator manually cleans Postgres tables, gets confused state                                                                                         | When in doubt, blow away the volume — the seed script puts data back                                                |
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

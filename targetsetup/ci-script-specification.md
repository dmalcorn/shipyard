# CI Script Specification (Target Template)

This document describes what `scripts/ci.sh` must do in any project the Shipyard factory builds. The factory invokes this script per story, per epic, and for full builds — its behavior under each invocation directly determines whether the factory's `fix_ci` retry loop converges, wastes cycles, or cascades into false failures.

This is a copy-into-target template. Place a copy at `_bmad-output/planning-artifacts/ci-script-specification.md` in the target repo before running the bmad-architect agent that generates `scripts/ci.sh`. The architect must produce a script that satisfies every "MUST" in this document.

## Why this matters

Three lessons from the chat2diagram build (April 2026):

1. A subtle bug where ci.sh ran `vitest` three times for stories with no matching test pattern — a 350-second pipeline against a 300-second timeout, causing a cascade of fix_ci cycles that burned ~$25 and 32 minutes on stories that were code-correct from cycle 1. (Fixed in chat2diagram commit `2c31777` after diagnosis.)
2. A captured-stdout bug where `subprocess.run` with `capture_output=True` returned `result.stdout = None` for some Windows-side runs, making the factory hand a Python error string to the fix_ci agent instead of the real CI output. (Fixed in shipyard commit `c96db6d` by tee-ing CI output to a per-cycle log file.)
3. A doc-only story (an Architecture-only spike) that took 5+ minutes to run CI because ci.sh ran the full test suite anyway, then timed out. (Fixed in chat2diagram by adding a Phase 0 short-circuit that exits 0 fast when only documentation paths changed.)

Each of those was a CI-script bug — not a factory bug, not a story bug. The factory had to be hardened around the CI-script's misbehavior. **Future targets should not have those bugs in the first place.** That is what this document exists to enforce.

## Required CLI interface

The script MUST accept these invocations:

```
bash scripts/ci.sh                    # full project CI (used for epic-level review)
bash scripts/ci.sh --story X-Y        # story-scoped CI (used per story)
bash scripts/ci.sh --quick            # fast subset (lint+typecheck only, no tests)
bash scripts/ci.sh --test-only        # tests only, skip lint/typecheck/build
```

Story IDs are dash-separated: `12-1`, `5-3`, `17-8`. The factory's `run_ci_node` always passes `--story` for per-story runs.

Unknown flags MUST exit non-zero with a message — never silently ignore.

## Required preamble

The script MUST start with:

```bash
#!/usr/bin/env bash
# CI script for <project> — <stack>
set -euo pipefail
```

`pipefail` matters: `cmd1 | cmd2` exit status reflects the failing command in the pipe, not just `cmd2`. Without it, a `vitest run | tee log.txt` pattern silently swallows test failures because `tee` always exits 0.

The script SHOULD also guard the bash version when it uses associative arrays (e.g., for the phase-timing summary in "Output and logging hygiene" below). macOS still ships bash 3 by default, and silent breakage on associative-array syntax produces extremely confusing failures. Reference:

```bash
if [ "${BASH_VERSINFO[0]}" -lt 4 ]; then
    echo "ERROR: bash 4+ required (found ${BASH_VERSION})." >&2
    echo "       On macOS: brew install bash && use /usr/local/bin/bash" >&2
    exit 1
fi
```

## Coordination with the dev Docker stack

Targets that follow [local-dev-docker-guide.md](local-dev-docker-guide.md) run their app + DB + supporting services in a long-lived dev compose stack (`docker/docker-compose.dev.yml`). The leave-it-up policy means that stack is normally already running when CI fires.

**Backend lint, typecheck, and test phases MUST run inside the dev backend container, not on the host.** This is enforced based on a real failure mode in the 2026-05 PawprintRecipes run: across 22 stories, Phase 3a (backend pytest) recorded **0 passes, 0 failures, and 9 silent skips** because `command -v pytest` returned false in the orchestrator's `subprocess.run` PATH context — masking every backend test outcome for the entire epic 1+2 build. The deeper problem isn't just pytest's PATH: even when the bare CLI shim resolves, the host's Python env doesn't have the project's pinned deps (celery, structlog, drf-spectacular, etc.) — the dev container does, courtesy of `docker/Dockerfile.<service>` running `pip install -r requirements.txt`. Two failure modes (PATH divergence + dep parity) collapse to one fix: dispatch into the container.

The phases this rule applies to:

| Phase | Why it must dispatch |
|---|---|
| 1a — Backend lint (ruff/black) | Tools live in `pip` env, deps presence affects analysis |
| 1b — Backend typecheck (mypy) | Same; mypy needs to import project deps |
| 1b — Migration gate (already containerized) | DB connection + Django runtime |
| 3a — Backend tests (pytest) | Imports the entire project; needs all deps |
| 3c — Contract-invariant tests (pytest) | Same; imports the contract generator |

Phases that legitimately stay on the host:

| Phase | Why it stays on host |
|---|---|
| 0 — Doc-only short-circuit | Pure git operations |
| fmt — Auto-format write pass | Best-effort; worse-case writes nothing |
| 1c — Frontend lint (eslint) | Resolves from `node_modules/.bin` host-side |
| 1d — Frontend typecheck (tsc) | Same |
| 3b — Frontend tests (vitest) | Same |
| 4 — E2E (Playwright) | Drives a browser process |
| 5a — Bandit | Scans source files; static |
| 5b — npm audit | Operates on `node_modules/` |

Each containerized phase MUST:

1. Detect whether the required service is in `running` state via `docker compose ps <service> --format json`.
2. If not running, bring it up with `docker compose up -d <service>` and recheck — don't fail just because the operator hasn't kicked off the stack yet.
3. If Docker isn't available at all (daemon down, CLI missing), warn and fall back to host execution as a degraded mode (with a clear "Docker unavailable — falling back to host" message). The operator's environment is broken in a way the script can't fix; we run what we can rather than skip silently.
4. If Docker IS available but the service can't be brought up, fail loud — silent skip masks real topology problems.

Reference helper scaffold (single file, reusable across phases):

```bash
DEV_COMPOSE_FILE="docker/docker-compose.dev.yml"
BACKEND_SERVICE="<your-backend-service>"   # e.g. pawprint-backend, app-backend

_docker_ready() {
    [ -f "$DEV_COMPOSE_FILE" ] || return 1
    command -v docker >/dev/null 2>&1 || return 1
    docker info >/dev/null 2>&1 || return 1
    return 0
}

_ensure_container_up() {
    local service="$1"
    local running
    running=$(docker compose -f "$DEV_COMPOSE_FILE" ps "$service" --format json 2>/dev/null \
                | grep -c '"State":"running"' || true)
    if [ "$running" -eq 0 ]; then
        echo "  $service not running — bringing up via 'docker compose up -d'"
        docker compose -f "$DEV_COMPOSE_FILE" up -d "$service"
    fi
}

_container_exec() {
    local service="$1"
    shift
    docker compose -f "$DEV_COMPOSE_FILE" exec -T "$service" "$@"
}
```

The factory's orchestrator (`src/multi_agent/orchestrator.py`'s `_ensure_migrations`) and stack adapters (`src/adapters/django.py`'s `autoformat`/`lint_fix`) use the same dispatch pattern via `src/dev_container.py`. CI script phases that touch the project's pinned Python tooling should match.

### Prerequisite: dev tools MUST be installed in the container

Container dispatch only works if the container has the tools the CI script invokes. Hit this in PawprintRecipes Story 3-4 (2026-05-08): right after the Phase 1a/1b dispatch refactor landed, the next CI cycle failed with `No module named ruff` inside `pawprint-backend`. Root cause: `requirements.txt` only listed runtime deps + pytest; ruff and mypy were assumed to be operator-installed on the host (which is what the previous host-side ci.sh was doing). Container dispatch broke that assumption silently — no `command -v ruff` check anymore, just an immediate import failure inside the container.

**Rule:** for every Python tool the CI script invokes inside the container via `python -m <tool>`, the tool MUST be pinned in the deps the container's Dockerfile installs. The minimal set for a Django-based target with this CI script:

| Tool | Phases that need it | Goes in |
|---|---|---|
| `ruff` | 1a (lint), fmt | requirements-dev.txt |
| `mypy` | 1b (typecheck) | requirements-dev.txt |
| `pytest` (+ `pytest-django`, `pytest-cov`) | 3a, 3c | requirements.txt OR requirements-dev.txt |
| `bandit` | 5a (host-side, separate concern) | n/a — host-installed |
| `black` (optional, legacy) | adapter fallback only | requirements-dev.txt if needed |

The cleanest split: `backend/requirements.txt` for runtime deps (Django, celery, drf, etc.), `backend/requirements-dev.txt` for CI/dev tools. The dev `Dockerfile.<service>` installs both:

```dockerfile
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
```

The production Dockerfile installs only `requirements.txt`. See [local-dev-docker-guide.md](local-dev-docker-guide.md#python-dev-tools-in-the-container) for the full pattern.

If the architect generates a Dockerfile that doesn't install the dev tools, every backend lint/typecheck phase will fail on the first CI cycle and the agent has to scramble to add them mid-build. Better to get this right at planning time.

### Optional: separate test-stack lifecycle

Some projects use a dedicated `docker/docker-compose.test.yml` so tests run against a throwaway DB while the long-lived dev stack keeps its data. Reasonable for projects with seed-data heavy tests, integration tests that mutate broadly, or anywhere a wiped test DB on every run is cheaper than carefully isolating fixtures.

When this pattern is used, the CI script SHOULD bring the test stack up at the top of the test phases and tear it down via a `trap` on `EXIT` so cleanup happens regardless of which phase failed:

```bash
TEST_STACK_FILE="docker/docker-compose.test.yml"
TEST_STACK_UP=false

teardown_test_stack() {
    if $TEST_STACK_UP; then
        docker compose -f "$TEST_STACK_FILE" down --volumes >/dev/null 2>&1 || true
    fi
}
trap 'teardown_test_stack; print_summary' EXIT

bring_up_test_stack() {
    if [ -f "$TEST_STACK_FILE" ]; then
        docker compose -f "$TEST_STACK_FILE" up -d --wait
        TEST_STACK_UP=true
    fi
}
```

The `trap ... EXIT` is the load-bearing piece — without it, a Phase 3a failure leaves the test stack running, and the next ci.sh invocation either errors on port collision or silently uses the prior run's mutated state.

## Required phases (in order)

### Phase 0 — Documentation-only short-circuit (MUST)

When `--story X-Y` is passed AND every changed/new path in the working tree is under documentation directories, exit 0 fast. Do not install dependencies, run tests, or build.

Recognized documentation paths (extend per project):

- `_bmad-output/**`
- `docs/**`
- `lessons-learned/**`
- `epic-reviews/**`
- `targetsetup/**` — the copied-in target templates (this guide, the local-dev-docker guide, etc.) are documentation; edits to them must not trigger full CI
- `*.md` at the project root

Detection MUST use git, not heuristics. Reference implementation:

```bash
if [ -n "$STORY_FILTER" ] && [ -d .git ]; then
    CHANGED=$({
        git diff --name-only HEAD 2>/dev/null || true
        git ls-files --others --exclude-standard 2>/dev/null || true
    } | sort -u)

    if [ -n "$CHANGED" ]; then
        CODE_FILES=$(echo "$CHANGED" | grep -Ev '^(_bmad-output/|docs/|lessons-learned/|epic-reviews/|targetsetup/|[^/]*\.md$)' || true)
        if [ -z "$CODE_FILES" ]; then
            echo "=== Story $STORY_FILTER is documentation-only — skipping lint, typecheck, tests, and build ==="
            echo "$CHANGED" | sed 's/^/    /'
            echo "=== All checks passed (documentation-only) ==="
            exit 0
        fi
    fi
fi
```

This MUST run before Phase 1 (dependency install) — otherwise a doc-only story still pays for `npm ci` or `pip install`.

### Phase 1 — Install dependencies (MUST)

If a dependency lock file exists and `node_modules/` (or its language equivalent) is missing or stale, install. Skip if already up to date — `npm ci` against an unchanged lock takes ~5 seconds vs ~60+ for a cold install.

### Phase 1b — Migration gate (MUST when applicable)

For projects with database migrations, this phase **gates CI on missing migration files** — i.e., it catches "operator changed a model but forgot to commit the generated migration." Apply-the-migrations is a separate concern that lives elsewhere (see "Where migrations are actually applied" below); this CI phase only checks that the migration files are committed and consistent with the model code.

The check MUST run inside the dev application container, not on the host. Two reasons:

- The host doesn't always have Django/SQLAlchemy/etc. installed, and shouldn't have to. The dev container does.
- The container has the dev DB reachable via the compose network. The host generally doesn't, unless the operator has configured it.

If the dev container isn't running, the script SHOULD bring it up via `docker compose up -d <backend-service>` before exec'ing the check. (The dev stack is meant to stay up between sessions per the leave-it-up policy in [local-dev-docker-guide.md](local-dev-docker-guide.md), but a fresh checkout or post-`down` state should still work.)

Reference patterns by stack:

- **Django** (`makemigrations --check`):
  ```bash
  docker compose -f docker/docker-compose.dev.yml exec -T <backend-service> \
      python manage.py makemigrations --check --dry-run --no-input
  ```
- **Drizzle** (`drizzle-kit check`):
  ```bash
  docker compose -f docker/docker-compose.dev.yml exec -T <app-service> \
      npx drizzle-kit check
  ```
- **Alembic** (`alembic check`):
  ```bash
  docker compose -f docker/docker-compose.dev.yml exec -T <backend-service> \
      alembic check
  ```

On nonzero exit, fail CI with an actionable message that names the fix command:

```
FAIL: Pending model changes have no committed migration files.
      Run:    make makemigrations
      Then commit the new files in backend/<app>/migrations/.
```

If Docker isn't available (e.g., daemon down, CLI missing), the gate SHOULD warn-and-skip rather than fail — the operator's environment is broken in a way the script can't fix, and we don't want to block legitimate runs. But if Docker IS available, missing migrations MUST fail.

This phase is NOT skipped by `--test-only` — uncommitted migrations are a correctness issue, not a static-analysis nicety.

#### Where migrations are actually applied

Applying migrations to the dev DB is **not** the CI script's job. Instead:

- The dev application container's entrypoint does it on every container start, gated by `RUN_MIGRATIONS_ON_START=true` in the dev compose file. See the "Django backends — the migrate-on-start entrypoint" section of [local-dev-docker-guide.md](local-dev-docker-guide.md) for the pattern.
- The factory orchestrator runs `makemigrations` (auto-generate) inside the container before each CI cycle if any model change is detected without a corresponding migration file. See `_ensure_migrations` in `src/multi_agent/orchestrator.py`.
- Production deploys apply migrations explicitly via the deploy script (e.g., `scripts/deploy-vps.sh`), once, before swapping containers — never via container startup.

The CI-script gate above is the third layer: catches the case where the orchestrator's auto-generate didn't fire (operator ran the build manually, or the orchestrator's makemigrations was skipped because the container couldn't be brought up) AND the operator didn't manually run `make makemigrations`.

### Phase 1c — Auto-format, then check (MUST)

Run the formatter in `--write` (apply changes) mode FIRST, then run it in `--check` mode to verify everything is clean. This is the opposite of the naive ordering and matters because:

- The factory's `fix_ci` agent should not be invoked for trivial format-only failures
- Auto-format catches trailing whitespace, missing newlines, inconsistent quotes — none of which the dev agent should waste budget fixing manually

```bash
# DO:
npx prettier --write "src/**/*.{ts,tsx,js,jsx,json,css}" 2>/dev/null || true
npx eslint --fix . 2>/dev/null || true
# Then in Phase 2:
npx prettier --check "src/**/*.{ts,tsx,js,jsx,json,css}" || exit 1

# DON'T:
npx prettier --check "src/**/*.{ts,tsx,js,jsx,json,css}" || exit 1   # fails on whitespace, expensive fix_ci cycle
```

### Phase 2 — Lint (MUST, skip with `--test-only`)

Run linters in check mode. Failures here MUST exit non-zero. Examples:

- TypeScript projects: `prettier --check`, `eslint .` (host-side; resolves from `node_modules/.bin`)
- Python projects: `python -m ruff check` (MUST run inside the dev backend container — see "Coordination with the dev Docker stack" above)
- Mixed-stack: each stack's lint runs in its own subsection with a `=== Phase 2: <stack> Lint ===` header

For multi-Python-service projects (e.g. `backend/` + `staff/` Django UI + worker), each service's lint runs inside its own container. The container's WORKDIR maps to the bind-mounted source dir, so the command becomes `python -m ruff check .` (no `backend/` prefix needed once inside).

### Phase 3 — Type check (MUST, skip with `--test-only`)

Examples:

- TypeScript: `npx tsc --noEmit` (host-side; tsc resolves from `node_modules/.bin`)
- Python: `python -m mypy . --ignore-missing-imports` MUST run inside the dev backend container — mypy needs to import project deps to type-check them, and those deps live in the container's pip env, not the host's

A note on `tsc --noEmit`: it's GLOBAL. A schema change in story X.5 that adds a required column will surface as TS errors in mocks across stories elsewhere. The factory's scope-constraint prompt now tells the agent these downstream errors ARE in scope (commit `a43564b`), but the CI script should make sure these errors are reported with full file paths and line numbers so the agent can find them.

### Phase 4 — Tests (MUST)

Backend tests (pytest) MUST dispatch into the dev backend container. Frontend tests (vitest, jest) stay on the host because their tooling resolves from `node_modules/.bin` and the test runtime is JSDOM/Node, not the application container. See "Coordination with the dev Docker stack" above for the dispatch rationale and helper scaffold.

**Critical: pytest dispatch MUST override `DJANGO_SETTINGS_MODULE` via `-e`.** The dev container's `docker-compose.dev.yml` sets `DJANGO_SETTINGS_MODULE=config.settings.dev` so the runtime app server uses dev (Postgres) settings. That env var **overrides** pyproject.toml's `[tool.pytest.ini_options].DJANGO_SETTINGS_MODULE` setting when pytest runs via `docker compose exec`. Without an explicit `-e` override, pytest picks up dev settings and tries to create a `test_<dbname>` database in real Postgres — which fails on schema-qualified table creates because Django doesn't propagate the schema-init script (`docker/postgres-init.sql` only runs once for the original DB, not for the auto-created `test_*` DB). This fails with `psycopg.errors.InvalidSchemaName: schema "user_schema" does not exist` at test setup, errors every backend test, and looks like a code bug when it's actually a settings-routing bug.

Reference dispatch (matches Phase 1b's migration-gate pattern):

```bash
docker compose -f "$DEV_COMPOSE_FILE" exec -T \
    -e DJANGO_SETTINGS_MODULE=config.settings.test \
    "$BACKEND_SERVICE" python -m pytest "${PYTEST_ARGS[@]}" \
    -k "$STORY_GREP_PYTEST" -m "not e2e" tests/
```

Same `-e` override applies to Phase 3c (contract invariants) and any other pytest dispatch into the container. Surfaced in PawprintRecipes Story 3-4 (2026-05-08) — backend tests had been silently skipping for 22 stories prior, so the gotcha was latent until Phase 3a actually started running.

Two patterns matter here, in order:

**Story-scoped test run with single-pass detection.** Story-scoping uses test name patterns: most projects tag tests with `story_X_Y` or `Story_X_Y` in their `describe()` / test names so they're filterable.

```bash
# Required pattern — run once with both default + json reporters:
STORY_JSON_FILE=$(mktemp /tmp/test-story-XXXXXX.json)
npx vitest run --passWithNoTests \
  -t "story_${STORY_UNDERSCORE}|Story_${STORY_UNDERSCORE}|${STORY_FILTER}" \
  --reporter=default --reporter=json --outputFile.json="$STORY_JSON_FILE" \
  || STORY_EXIT=$?
```

Then check the JSON file for `numPassedTests + numFailedTests == 0` to detect "no tests matched filter."

```bash
# DO NOT run vitest a second time just to count tests — that's the
# triple-vitest bug from chat2diagram.
```

**Full-suite fallback when zero tests matched.** When the filter pattern matches no tests, run the full suite. This is intentional — it prevents a doc-only-pretending-to-be-a-code story from passing CI silently with zero coverage.

```bash
if [ "${PASSED:-0}" -eq 0 ] && [ "${FAILED:-0}" -eq 0 ]; then
    echo "  No tests matched story filter '${STORY_FILTER}', running full suite..."
    npx vitest run "${VITEST_ARGS[@]+"${VITEST_ARGS[@]}"}"
fi
```

**Also fall back when the filter command itself fails.** A pytest/vitest invocation can exit non-zero for reasons unrelated to test results — config error, transient docker network issue, reporter-cache corruption, missing test directory. The factory's `run_ci` then sees a failure and invokes `fix_ci` with no idea whether the underlying tests were even reached. Falling back to the full suite when the filter run exits non-zero (not just when zero tests matched) gives the fix_ci agent the actual test output to diagnose against. Pattern:

```bash
STORY_EXIT=0
npx vitest run --passWithNoTests -t "$STORY_GREP" \
    --reporter=json --outputFile="$STORY_JSON" || STORY_EXIT=$?

if [ "$STORY_EXIT" -ne 0 ]; then
    echo "  Story-scoped run failed (exit=$STORY_EXIT) — running full suite for diagnostic"
    npx vitest run --passWithNoTests
else
    # parse PASSED/FAILED from $STORY_JSON, fall through to zero-match check above
fi
```

**E2E tests (Playwright, Cypress, etc.)** when applicable: same pattern — story-scoped if possible, full-suite fallback if zero match.

For backend-only or test-runner-specific patterns (pytest, gradle test, swift test), the same shape applies: filter by story, single-pass with reporter capturing both result+count, full-suite fallback on zero match.

### Phase 4b — Contract invariant tests (SHOULD when applicable)

Projects that publish a contract — OpenAPI spec, GraphQL schema, JSON Schema, gRPC proto — should have a dedicated test that verifies the published contract matches the implementation. This phase MUST always run (not story-filtered) because contract drift between story X.5 and story X.7 typically won't show up in either story's per-story tests but will quietly break consumers.

Examples:

- `pytest backend/tests/integration/test_openapi.py` — verifies the OpenAPI schema generated by drf-spectacular matches the registered routes and serializer fields
- `npx graphql-schema-linter` — verifies the GraphQL schema is well-formed and doesn't contain breaking changes from the published baseline
- `protoc --lint` — verifies proto definitions

Like the migration gate (Phase 1b), this phase is **not** skipped by `--story X-Y` and **not** skipped by `--test-only`. It's a correctness gate, not a story-local concern.

When the contract is generated by Python code (drf-spectacular, Pydantic-based generators), the test MUST dispatch into the dev backend container per the rule in "Coordination with the dev Docker stack" — same import-path concerns as Phase 3a.

### Phase 5 — Build (MUST, skip with `--test-only`)

Final verification that the project builds. For Next.js: `npx next build`. For Django: `python manage.py check --deploy`. For combined-stack projects, build each stack.

This phase is what catches "the code typechecks but the bundler can't actually package it" — surprisingly common for things like Next.js dynamic-import path issues.

### Phase 6 — Multi-stack invariants (when applicable)

For projects with `backend/` + `frontend/` (or similar component split):

- Each stack's phases run in their own subsection with explicit headers
- Story filter passes to each stack's test runner with appropriate translation
- Doc-only short-circuit detects changes across all stacks

Example structure for Django + Next.js project:

```bash
# Phase 0: doc-only check across both backend/ and frontend/ subtrees
# ...
echo "=== Phase 1: backend (Django) ==="
( cd backend && python manage.py migrate --check && black --check . && ruff check . && pytest -k "$STORY_PATTERN" )
echo "=== Phase 2: frontend (Next.js) ==="
( cd frontend && npx prettier --check "src/**" && npx eslint . && npx tsc --noEmit && npx vitest run -t "$STORY_PATTERN" )
echo "=== Phase 3: integration ==="
# any cross-stack tests
```

Note the `( … )` subshells — `cd backend` should not leak into the frontend phase.

## Pre-commit hooks (target-managed, factory-affecting)

Pre-commit hooks live in the target repo, not in the factory. For Node/TypeScript projects this is `husky` + `lint-staged` configured in `package.json`. For Python/Django it's the `pre-commit` framework configured in `.pre-commit-config.yaml`. The factory does NOT generate or manage these — but every commit the factory makes runs through them, so getting them right is part of running the factory successfully.

### Why pre-commit hooks belong in this spec even though they live in the target

Three reasons:

1. **Factory commits trigger the hooks.** When `git_commit_node` runs `git commit`, husky / pre-commit fires just like a developer's local commit. Hook failure = commit failure = factory marks the story failed. We hit this on the chat2diagram run mid-session: husky's pre-commit hook tried to invoke `prettier` but `node_modules\.bin\` had been wiped at some point and the binary couldn't resolve, so the hook errored, and the commit failed.

2. **Pre-commit hooks duplicate the factory's autoformat step** if not coordinated. The factory's `git_commit_node` already runs `prettier --write` / `eslint --fix` (or `black .` / `ruff check --fix .` for Django) BEFORE staging via the stack adapters. If pre-commit hooks ALSO run those same tools on staged files, that's double work; if the hook runs `--check` mode while the factory runs `--write`, they can fight each other.

3. **Hook tooling must be on `PATH` at factory runtime.** The factory subprocess inherits the operator's PATH. If the hook calls `prettier` (a node-modules-local binary on Windows requiring `.cmd` shim resolution) instead of `npx prettier`, the binary must resolve from the operator's environment when the factory's commit fires.

### Coordination with the factory's autoformat step

Two valid coordination patterns:

**Option A: hooks delegate to the factory.** Configure pre-commit hooks to do nothing the factory's adapter already does. Hooks can still do _other_ things — e.g., reject commits whose message format is wrong, or scan for accidentally committed secrets — but format/lint is owned entirely by the factory's `git_commit_node`. This is the simpler arrangement.

**Option B: factory delegates to hooks.** Disable the factory's auto-format adapter calls (set `format_via_adapter: false` in `factory.yaml`, once that flag exists in v2 work) and let pre-commit do all format/lint via lint-staged on the staged file set. Faster (lint-staged only touches changed files) but ties the factory more tightly to the target's tooling. Less recommended.

The chat2diagram run used Option A implicitly: husky + lint-staged ran `prettier --write` on staged files; the factory's `git_commit_node` separately ran `prettier --write` on the whole tree. Pure overhead — the factory pass was redundant once the hook ran. Resolved by accepting the redundancy as low cost. For a new target, choose explicitly.

### Required behaviors

Whatever path you pick, hooks MUST satisfy:

1. **Exit non-zero on failure.** No swallowed exit codes. The factory's commit fails fast.
2. **No interactive prompts.** stdin is closed in the factory's subprocess; any prompt-and-wait will hang until timeout.
3. **Complete in <30 seconds per commit.** The factory commits dozens of times per build. Slow hooks compound.
4. **Tolerate "no staged files of type X" gracefully.** A doc-only commit shouldn't fail the prettier hook because there are no `*.ts` files staged.
5. **Tolerate `node_modules/.bin/` repopulation.** Don't depend on global installs of `prettier` / `eslint` / `black` etc. — call them via `npx` (Node) or python module form (Python) so they resolve from the project's locked dependencies.

### Tooling on PATH — the chat2diagram lesson

Hook scripts that invoke `prettier` directly (rather than `npx prettier`) silently break when `node_modules/.bin/` is missing or stale. This happened twice during our run — once after a Docker session evicted the host-side bin shims, once after a `git clean` removed them. Resolution was always `npm install` to repopulate `.bin/`, but that's a recoverable-only-by-operator failure mode that's better avoided.

**Recommendation:** in lint-staged config, always call tools via `npx`:

```json
{
  "lint-staged": {
    "*.{ts,tsx,js,jsx,json,css}": ["npx prettier --write", "npx eslint --fix"]
  }
}
```

For pre-commit-framework (Python projects), use the `repo: local` form and `entry: "python -m black"` rather than bare `entry: "black"`:

```yaml
repos:
  - repo: local
    hooks:
      - id: black
        name: black
        entry: python -m black
        language: system
        types: [python]
```

This keeps the tool resolution path consistent between local dev, factory runs, and CI.

## Output and logging hygiene

- **MUST**: write all output to stdout/stderr unbuffered. The factory captures via `subprocess.run`. Buffered output makes failures look hung.
- **MUST**: use `set -o pipefail`. Without it, `... | tee logfile` masks failure exit codes.
- **MUST NOT**: redirect stderr to `/dev/null` (`2>/dev/null`) on test or build commands. The factory needs to see real errors when ci fails.
- **MAY**: `2>/dev/null` on auto-format/auto-fix commands where errors are deliberately ignored — but follow with a `|| true` so pipefail doesn't kill the script.
- **SHOULD**: prefix major sections with `=== Phase N: <description> ===` so log files are scannable.
- **SHOULD**: emit a per-phase status + duration table at the end of the run when the script has more than ~5 phases. Bash 4 associative arrays make this cheap; the operator-facing benefit is high — at a glance you can see which phase regressed without scrolling through 500+ lines of output. Also makes per-cycle regression detection trivial when the same script is run repeatedly. Reference scaffold:

```bash
declare -A _PHASE_LABEL _PHASE_STATUS _PHASE_START_S _PHASE_ELAPSED

_phase_start() {
    local phase_id="$1" label="$2"
    _PHASE_LABEL["$phase_id"]="$label"
    _PHASE_START_S["$phase_id"]=$SECONDS
}

_phase_end() {
    local phase_id="$1" status="$2"
    _PHASE_STATUS["$phase_id"]="$status"
    _PHASE_ELAPSED["$phase_id"]=$(( SECONDS - ${_PHASE_START_S["$phase_id"]:-$SECONDS} ))
}

print_summary() {
    echo ""
    echo "=== CI Summary ==="
    local phase_order=("0" "fmt" "1a" "1b" "1c" "1d" "1e" "2" "3a" "3b" "3c" "4" "4b" "5" "5a" "5b" "6")
    for phase_id in "${phase_order[@]}"; do
        local label="${_PHASE_LABEL[$phase_id]:-}"
        [ -z "$label" ] && continue
        local status="${_PHASE_STATUS[$phase_id]:-running}"
        local elapsed="${_PHASE_ELAPSED[$phase_id]:-?}"
        printf "  Phase %-4s  %-25s  %-8s  %3ss\n" \
            "$phase_id" "$label" "$status" "$elapsed"
    done
}

# Wire into the test-stack teardown trap so it always fires on exit:
trap 'teardown_test_stack; print_summary' EXIT
```

Status strings used in practice: `PASS`, `FAIL`, `skipped`, `skip-quick`, `skip-doc`, `done`. Pick a small consistent vocabulary so the summary stays scannable.

## Anti-patterns from prior builds (do not repeat)

| Anti-pattern                                                                                                                 | Why it hurt                                                                                                                     | Fix                                                                                                                                                  |
| ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------- |
| Running `vitest run` then `vitest run --reporter=json` to "check" zero matches                                               | Doubled CI time, cascaded fix_ci cycles, ~$25 wasted                                                                            | Single pass with `--reporter=default --reporter=json --outputFile.json=...`                                                                          |
| Format-check before format-write                                                                                             | Fix_ci agent invoked for trivial whitespace                                                                                     | Auto-format first, then check                                                                                                                        |
| Swallowing stderr (`2>/dev/null`) on test commands                                                                           | Real errors hidden, agent given empty CI output, `NoneType has no len` masquerade                                               | Only swallow on auto-fix commands; never on tests/typecheck/build                                                                                    |
| Hard-coded `--story N-N` filter that matches `numTotalTests` instead of `numPassedTests + numFailedTests`                    | Skipped tests inflated the count, fallback never triggered, bogus passes                                                        | Use passed+failed sum                                                                                                                                |
| Running full project CI for a doc-only story                                                                                 | 5+ min for a markdown edit, occasional timeouts                                                                                 | Phase 0 short-circuit                                                                                                                                |
| `git diff` in subshells without `2>/dev/null                                                                                 |                                                                                                                                 | true`                                                                                                                                                | Unset variables / missing repo failed Phase 0 entirely, broke all CI | Defensive defaults on every git invocation in detection logic |
| Pre-commit hook calls bare `prettier` / `eslint` / `black`                                                                   | Failed silently when `node_modules/.bin/` was wiped (Docker churn, manual `git clean`); operator had to `npm install` and retry | Always invoke via `npx prettier`, `npx eslint`, or `python -m black` so tools resolve from project-local installs                                    |
| Pre-commit hook duplicates the factory's autoformat step in the same mode (both `--write`, or one `--write` + one `--check`) | Double work, or hooks fight the factory's edits                                                                                 | Pick coordination pattern explicitly: hooks delegate to factory (Option A) OR factory delegates to hooks (Option B) — not both running the same tool |
| Running `manage.py migrate` (or any migrator) on the host inside `scripts/ci.sh`                                             | Host needs the framework, the DB driver, and a reachable DB on `localhost`; fragile across machines and breaks the moment the DB moves into Docker | Run migration commands inside the dev application container via `docker compose exec`; the container has the language runtime + the DB on the compose network without the host needing anything |
| Skipping the migration gate (`makemigrations --check` / `drizzle-kit check` / `alembic check`)                               | Operator changes a model, runs tests against a synced dev DB, doesn't notice the missing migration file is uncommitted; landed on `main`, prod deploy hits "no such column"      | Add Phase 1b gate; fail CI loud with the exact `make` command to fix it                                                                              |
| Setting `RUN_MIGRATIONS_ON_START=true` (or any auto-migrate-on-start flag) in a prod compose file                            | All replicas race to apply migrations during a rolling deploy; partial-state failure mid-rollout                                | Set the env var ONLY in `docker-compose.dev.yml`. Production migrates explicitly via the deploy script, once, before swapping containers             |

## How the bmad-architect should use this document

When generating `scripts/ci.sh` from `approved-tech-stack.md`, the architect agent MUST:

1. Implement every phase marked `MUST`
2. Match the exact CLI interface above
3. Use the reference implementation patterns for Phase 0 and Phase 4 verbatim (with stack-appropriate test commands)
4. Include the `=== Phase N: ... ===` section markers for log readability
5. Verify the resulting script against the "Anti-patterns" table — no anti-pattern from that table should appear in the generated script
6. Add a one-paragraph header comment naming the source of authority: "Generated from `_bmad-output/planning-artifacts/ci-script-specification.md`. Do not edit ad hoc — update the spec and regenerate."

## How the operator validates a generated CI script

Before kicking off the factory:

1. Read `scripts/ci.sh` end-to-end. Should be ~100-200 lines for a single-stack project, ~150-300 for multi-stack.
2. Run it against an unchanged checkout with the dev stack up: `make up && bash scripts/ci.sh`. Should pass with all phases marked, no Phase 0 short-circuit (since nothing changed, but also nothing broke).
3. Make a trivial doc-only change in `_bmad-output/`, run `bash scripts/ci.sh --story X-Y` for some story. Phase 0 should short-circuit in <2 seconds.
4. Make a trivial code change, run `bash scripts/ci.sh --story X-Y`. All phases should run, including the full-suite fallback if no tests match.
5. **Validate the migration gate (Phase 1b):** add a no-op field to a model (e.g., `dummy = models.IntegerField(null=True)` on any Django model), do NOT run `make makemigrations`, then `bash scripts/ci.sh --story X-Y`. The script MUST fail Phase 1b with a clear "pending model changes" message, not pass silently. Revert the change after.
6. Look at the output for any anti-patterns from the table above. Fix them in the architect's prompt or the script directly.

## Updating this specification

When a future factory build surfaces a new CI pattern worth standardizing, update this document AND the bmad-architect agent's prompt that references it. Keep this file shorter than 400 lines — if it sprawls, split out stack-specific guidance to companion docs.

## See also

- [local-dev-docker-guide.md](local-dev-docker-guide.md) — the dev Docker stack the migration gate dispatches into; the leave-it-up policy CI scripts assume; the Django entrypoint pattern that handles `migrate --noinput` on container start
- [factory-replication-guide.md](../factory-replication-guide.md#common-gotchas) — host-side gotchas that affect CI script behavior
- [factory-lessons-from-chat2diagram.md](../factory-lessons-from-chat2diagram.md) — full retrospective on the lessons codified here
- [story-and-epic-writing-guide.md](story-and-epic-writing-guide.md) — partner template for the planning side
- [test-structure-guide.md](test-structure-guide.md) — how the test suite that ci.sh invokes should be organized

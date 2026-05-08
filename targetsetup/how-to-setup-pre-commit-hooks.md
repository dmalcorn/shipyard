# How to Set Up Pre-Commit Hooks

A reusable target template for a git pre-commit hook that runs the
fast Phase 1 checks (lint + typecheck) on staged files before
allowing the commit. Catches type/lint errors at the *commit* edge
instead of letting them ride to story-end CI — or worse, accumulate
silently across an entire epic.

PawprintRecipes-specific names (`pawprint-backend` service,
`docker/docker-compose.dev.yml`, `backend/` and `web/` paths) appear
throughout as concrete examples — substitute your project's
equivalents per the "Adapting to a new project" checklist near the
end.

## What it is

A bash script at `scripts/git-hooks/pre-commit` that:

- Detects whether any staged files are under `backend/` or `web/`
- Dispatches `ruff check` + `mypy` into the running backend dev
  container if backend files are staged
- Runs `eslint` + `tsc --noEmit` on the host via `npx` if web files
  are staged
- Fails the commit on any error
- Exits cleanly (no work) if only docs/configs are staged

No Python `pre-commit` framework dependency, no global install — just
one git config setting that points git at the in-repo hooks
directory.

## Why it exists

Silent CI gates are how typecheck/lint debt accumulates. If Phase 1b
(mypy) silently skips because of a probe bug or container-dispatch
mismatch, errors land unnoticed and pile up across multiple epics.
By the time the gate is fixed, the cleanup is a multi-day project
(see the lessons-learned protocol entry for the type of incident
this prevents).

The pre-commit hook is the prevention layer — even if a CI phase
ever silently skips again, errors get caught at commit time on
whichever machine is doing the work.

## One-time setup

From the repo root:

```bash
git config core.hooksPath scripts/git-hooks
```

That's it. Git now uses `scripts/git-hooks/pre-commit` instead of
the default `.git/hooks/pre-commit.sample`. Because the path is
relative to the repo, the setting works the same on every machine
that clones this repo (after each clone, run the same command once).

Verify it took effect:

```bash
git config --get core.hooksPath
# scripts/git-hooks
```

## How it behaves

When you `git commit` (or `git commit -am`, or anything that triggers
a commit):

1. The hook reads the staged file list.
2. If any staged file is under `backend/`, it dispatches
   `python -m ruff check .` and `python -m mypy .` into the running
   `pawprint-backend` container.
3. If any staged file is under `web/`, it runs `npx eslint .` and
   `npx tsc --noEmit` on the host.
4. If any check fails, the commit is aborted.
5. If only docs/configs are staged (no `backend/` or `web/`), the
   hook exits cleanly with no work.

Typical run takes ~15–30s when backend files are staged, ~5–10s for
frontend-only.

## Prerequisites

- **Backend checks** require the dev container running:

  ```bash
  docker compose -f docker/docker-compose.dev.yml up -d pawprint-backend
  ```

  If the container isn't running, the hook *skips* the backend
  checks (with a yellow warning) rather than failing — that way you
  can still commit when working on docs while the stack is down. CI
  will catch anything you missed.

- **Frontend checks** require `npx` on PATH and `web/node_modules`
  populated (`cd web && npm ci`). Same skip-with-warning behavior if
  either is missing.

## Bypassing

Three escape hatches, in increasing order of how-permanent-they-are:

### 1. Single commit (`--no-verify`)

```bash
git commit --no-verify -m "wip: midway through refactor, will fix in next commit"
```

Use this when:

- You're checkpointing mid-refactor and the next commit will fix
  things.
- You're committing a doc/config change and don't want to wait for
  the container check.
- The hook is itself broken (e.g. Docker hiccup) and you've eyeballed
  your changes.

Don't use this to ship known-broken code to a story-done state —
Phase 1b in CI will catch it and your story will fail acceptance.

### 2. Disable the hook globally (toggle off)

```bash
git config --unset core.hooksPath
```

The hook stays in `scripts/git-hooks/pre-commit` (it's committed to
the repo) but git stops invoking it. Re-enable any time with the
install command above. Useful if:

- You're doing a big rebase or interactive history surgery and don't
  want hooks firing on every reword/edit.
- You're on a branch that's *meant* to be in a typecheck-failing
  state (e.g. an in-progress upgrade).

### 3. Edit the hook

It's a regular bash script. Read
[`scripts/git-hooks/pre-commit`](../scripts/git-hooks/pre-commit),
change what's checked, commit the change. Whatever lands in main
applies to all clones once they re-run the install command.

## Factory integration

When the Shipyard factory commits to the target repo, it passes
`--no-verify` so its commits are not double-gated against the same
checks the factory's own CI loop just ran. The factory's enforcement
is `run_ci` with `fix_ci` retry routing — the pre-commit hook is
deliberately for human/IDE commits only.

If you're operating the factory and you see commits landing without
the hook firing, that's by design. Direct `git commit` (from your
shell, your IDE, or Claude Code outside the factory) WILL trigger
the hook.

## What this hook does NOT do

- It does **not** run Phase 2 (test-stack-up), Phase 3 (tests),
  Phase 4 (e2e), or Phase 5 (build). Those stay in
  `bash scripts/ci.sh` and are gated at the story-done boundary.
- It does **not** modify any files (no auto-format, no lint-fix).
  Running formatters as part of the hook makes commits
  non-deterministic — if ruff format reformats a file, the staged
  content no longer matches the working tree. Run formatters
  explicitly when you want them.
- It does **not** run on the staff backend (`staff/`). If/when
  staff backend code accumulates similar debt, extend the hook the
  same way `ci.sh` does.

## Troubleshooting

**The hook isn't firing.**

- Check: `git config --get core.hooksPath` — should print
  `scripts/git-hooks`. If empty, run the install command.
- Check: `ls -l scripts/git-hooks/pre-commit` — should show
  executable bits (`-rwxr-xr-x`). On Windows/WSL, run
  `chmod +x scripts/git-hooks/pre-commit`.

**The hook says "pawprint-backend not running" but Docker is up.**

- Check the service is actually running:
  `docker compose -f docker/docker-compose.dev.yml ps pawprint-backend`.
- The hook treats anything other than `running` (e.g. `restarting`,
  `exited`) as not-running and skips. That's deliberate — better to
  skip and let CI catch it than to hang on a sick container.

**Mypy fails on changes I didn't make.**

- mypy runs on the *whole* `backend/` tree, not just staged files
  (mypy needs full context — module graph, settings, etc., not
  per-file). If errors exist anywhere in `backend/`, the hook will
  surface them. Either fix them or run `git commit --no-verify` and
  surface to whoever owns those files.
- This is the same behavior as Phase 1b in CI.

**I want to add more checks.**

- Edit the script. Match the existing pattern: detect what's
  staged, dispatch into the appropriate container or run on host,
  fail clearly. Keep it under 30s total — slow hooks get bypassed.

## The hook script

The file at `scripts/git-hooks/pre-commit` is a bash script
(~120 lines) that mirrors the dispatch pattern in
`scripts/ci.sh`. The structure:

```bash
#!/usr/bin/env bash
set -euo pipefail

DEV_COMPOSE_FILE="docker/docker-compose.dev.yml"
BACKEND_SERVICE="pawprint-backend"

# 1. Read staged file list, classify by directory
STAGED=$(git diff --cached --name-only --diff-filter=ACMR)
backend_staged=false
web_staged=false
while IFS= read -r f; do
    case "$f" in
        backend/*) backend_staged=true ;;
        web/*)     web_staged=true ;;
    esac
done <<< "$STAGED"

# 2. Skip if nothing relevant
if ! $backend_staged && ! $web_staged; then exit 0; fi

# 3. Backend gate: dispatch into container, skip if container not up
if $backend_staged; then
    if container_running; then
        docker compose ... exec -T pawprint-backend python -m ruff check .
        docker compose ... exec -T pawprint-backend python -m mypy . --ignore-missing-imports
    else
        echo "warning: backend container not running, skipping"
    fi
fi

# 4. Frontend gate: run on host via npx, skip if node_modules missing
if $web_staged; then
    (cd web && npx eslint .)
    (cd web && npx tsc --noEmit)
fi
```

Real script has color output, more granular skip messages, and
clearer fail messaging with bypass instructions. See the actual
file in any project that has installed the hook for the full
implementation.

## Adapting to a new project

When copying this hook to a new project, the swap-list:

| PawprintRecipes value | Replace with |
|---|---|
| `pawprint-backend` (compose service name) | Your backend service name from `docker-compose.dev.yml` |
| `docker/docker-compose.dev.yml` | Your dev compose file path (some projects keep it at the repo root) |
| `backend/` (Python source root) | Your Python source root if different (e.g. `api/`, `server/`) |
| `web/` (Next.js source root) | Your frontend source root if different (e.g. `frontend/`, `client/`) |
| `python -m mypy . --ignore-missing-imports` | Your project's mypy invocation. Drop if no Python. |
| `python -m ruff check .` | Your linter invocation. Could be flake8, pylint, etc. |
| `npx eslint .` / `npx tsc --noEmit` | Your frontend linter / typechecker. Drop if no frontend. |

**If your project has no backend container** (pure-frontend or
pure-Go/etc.), drop the backend section entirely; the hook becomes
even simpler. **If your project has multiple Python services**,
duplicate the backend block for each service container, the same
way `ci.sh` does for the staff panel.

**Keep the script under 30s total runtime.** Slow hooks get
bypassed, and a bypassed hook protects nothing. If you find
yourself adding a check that takes more than 5–10s, ask whether
it really needs to run on every commit or whether it should stay
in `ci.sh` at the story boundary.

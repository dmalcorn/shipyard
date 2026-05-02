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

## Required phases (in order)

### Phase 0 — Documentation-only short-circuit (MUST)

When `--story X-Y` is passed AND every changed/new path in the working tree is under documentation directories, exit 0 fast. Do not install dependencies, run tests, or build.

Recognized documentation paths (extend per project):
- `_bmad-output/**`
- `docs/**`
- `lessons-learned/**`
- `epic-reviews/**`
- `*.md` at the project root

Detection MUST use git, not heuristics. Reference implementation:

```bash
if [ -n "$STORY_FILTER" ] && [ -d .git ]; then
    CHANGED=$({
        git diff --name-only HEAD 2>/dev/null || true
        git ls-files --others --exclude-standard 2>/dev/null || true
    } | sort -u)

    if [ -n "$CHANGED" ]; then
        CODE_FILES=$(echo "$CHANGED" | grep -Ev '^(_bmad-output/|docs/|lessons-learned/|epic-reviews/|[^/]*\.md$)' || true)
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

### Phase 1b — Database schema sync (MAY, if applicable)

For projects with database migrations, run the migrator here so subsequent test runs see the current schema. Examples:
- Drizzle: `npx tsx scripts/migrate-db.ts` (NOT `drizzle-kit push --force` — see [factory-lessons-from-chat2diagram.md](../factory-lessons-from-chat2diagram.md#migration-tracking-corruption) for why)
- Django: `python manage.py migrate --check` or `python manage.py migrate`
- Rails: `bundle exec rails db:migrate`

Required only when `DATABASE_URL` is set in the environment AND the project has a migration mechanism. CI scripts that run without a DB available should detect that and skip cleanly, not fail.

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
- TypeScript projects: `prettier --check`, `eslint .`
- Python projects: `black --check`, `ruff check`
- Mixed-stack: each stack's lint runs in its own subsection with a `=== Phase 2: <stack> Lint ===` header

### Phase 3 — Type check (MUST, skip with `--test-only`)

Examples:
- TypeScript: `npx tsc --noEmit`
- Python with type hints: `mypy <packages>`

A note on `tsc --noEmit`: it's GLOBAL. A schema change in story X.5 that adds a required column will surface as TS errors in mocks across stories elsewhere. The factory's scope-constraint prompt now tells the agent these downstream errors ARE in scope (commit `a43564b`), but the CI script should make sure these errors are reported with full file paths and line numbers so the agent can find them.

### Phase 4 — Tests (MUST)

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

**E2E tests (Playwright, Cypress, etc.)** when applicable: same pattern — story-scoped if possible, full-suite fallback if zero match.

For backend-only or test-runner-specific patterns (pytest, gradle test, swift test), the same shape applies: filter by story, single-pass with reporter capturing both result+count, full-suite fallback on zero match.

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

**Option A: hooks delegate to the factory.** Configure pre-commit hooks to do nothing the factory's adapter already does. Hooks can still do *other* things — e.g., reject commits whose message format is wrong, or scan for accidentally committed secrets — but format/lint is owned entirely by the factory's `git_commit_node`. This is the simpler arrangement.

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

## Anti-patterns from chat2diagram (do not repeat)

| Anti-pattern | Why it hurt | Fix |
|---|---|---|
| Running `vitest run` then `vitest run --reporter=json` to "check" zero matches | Doubled CI time, cascaded fix_ci cycles, ~$25 wasted | Single pass with `--reporter=default --reporter=json --outputFile.json=...` |
| Format-check before format-write | Fix_ci agent invoked for trivial whitespace | Auto-format first, then check |
| Swallowing stderr (`2>/dev/null`) on test commands | Real errors hidden, agent given empty CI output, `NoneType has no len` masquerade | Only swallow on auto-fix commands; never on tests/typecheck/build |
| Hard-coded `--story N-N` filter that matches `numTotalTests` instead of `numPassedTests + numFailedTests` | Skipped tests inflated the count, fallback never triggered, bogus passes | Use passed+failed sum |
| Running full project CI for a doc-only story | 5+ min for a markdown edit, occasional timeouts | Phase 0 short-circuit |
| `git diff` in subshells without `2>/dev/null || true` | Unset variables / missing repo failed Phase 0 entirely, broke all CI | Defensive defaults on every git invocation in detection logic |
| Pre-commit hook calls bare `prettier` / `eslint` / `black` | Failed silently when `node_modules/.bin/` was wiped (Docker churn, manual `git clean`); operator had to `npm install` and retry | Always invoke via `npx prettier`, `npx eslint`, or `python -m black` so tools resolve from project-local installs |
| Pre-commit hook duplicates the factory's autoformat step in the same mode (both `--write`, or one `--write` + one `--check`) | Double work, or hooks fight the factory's edits | Pick coordination pattern explicitly: hooks delegate to factory (Option A) OR factory delegates to hooks (Option B) — not both running the same tool |

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
2. Run it against an unchanged checkout: `bash scripts/ci.sh`. Should pass with all phases marked, no Phase 0 short-circuit (since nothing changed, but also nothing broke).
3. Make a trivial doc-only change in `_bmad-output/`, run `bash scripts/ci.sh --story X-Y` for some story. Phase 0 should short-circuit in <2 seconds.
4. Make a trivial code change, run `bash scripts/ci.sh --story X-Y`. All phases should run, including the full-suite fallback if no tests match.
5. Look at the output for any anti-patterns from the table above. Fix them in the architect's prompt or the script directly.

## Updating this specification

When a future factory build surfaces a new CI pattern worth standardizing, update this document AND the bmad-architect agent's prompt that references it. Keep this file shorter than 400 lines — if it sprawls, split out stack-specific guidance to companion docs.

## See also

- [factory-replication-guide.md](../factory-replication-guide.md#common-gotchas) — host-side gotchas that affect CI script behavior
- [factory-lessons-from-chat2diagram.md](../factory-lessons-from-chat2diagram.md) — full retrospective on the lessons codified here
- [story-and-epic-writing-guide.md](story-and-epic-writing-guide.md) — partner template for the planning side
- [test-structure-guide.md](test-structure-guide.md) — how the test suite that ci.sh invokes should be organized

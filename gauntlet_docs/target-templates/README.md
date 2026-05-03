# Target Templates

Six documents in this directory describe what the Shipyard factory expects from a target project. Copy each one into your target's `_bmad-output/planning-artifacts/` *before* running the factory, and reference them when generating the target's own CI script, epics, and test layout. The lessons-learned protocol additionally requires copying its `## Agent Coding Rules` section header into the target's `CLAUDE.md`.

## The six templates

| File | Audience | Copy into target as |
|---|---|---|
| [ci-script-specification.md](ci-script-specification.md) | The bmad-architect agent that generates `scripts/ci.sh` | `_bmad-output/planning-artifacts/ci-script-specification.md` |
| [story-and-epic-writing-guide.md](story-and-epic-writing-guide.md) | The human (or agent) authoring `epics.md` | `_bmad-output/planning-artifacts/story-and-epic-writing-guide.md` |
| [test-structure-guide.md](test-structure-guide.md) | The bmad-architect agent + the dev agent on every story | `_bmad-output/planning-artifacts/test-structure-guide.md` |
| [local-dev-docker-guide.md](local-dev-docker-guide.md) | The bmad-architect agent (generates `Dockerfile.dev` + `docker-compose.yml`) + dev agent (writes code that respects local stack topology) | `_bmad-output/planning-artifacts/local-dev-docker-guide.md` |
| [email-testing-guide.md](email-testing-guide.md) | Projects with email-based auth or notifications — architect (CI), dev agent (E2E tests), operator (Railway service setup) | `_bmad-output/planning-artifacts/email-testing-guide.md` (only for projects with email features) |
| [lessons-learned-protocol.md](lessons-learned-protocol.md) | Architect at epic-review time + dev agent on every story (via `CLAUDE.md`) | `_bmad-output/planning-artifacts/lessons-learned-protocol.md` AND copy the `## Agent Coding Rules` section header into target's `CLAUDE.md` |

## Why they live here, not in target repos

Each template captures conventions and lessons we want **stable across every future factory build**. If they lived in target repos, they'd silently drift — one project's "story writing guide" would diverge from the next, and the factory would lose the ability to assume consistent inputs.

By keeping the canonical version in shipyard and copying snapshots into each target, we get:
- One source of truth per convention (this directory)
- No ambient drift (target gets a frozen copy at project start)
- Each target's planning artifacts are still self-contained (the BMAD agents working in the target see their own copy under `_bmad-output/`)

## How the factory uses them

The factory itself doesn't read these files directly. They're inputs to the **agents** — the bmad-architect that writes `scripts/ci.sh`, the bmad-pm that writes `epics.md`, the bmad-dev that writes test files for each story. Those agents read the target's `_bmad-output/planning-artifacts/` as Layer 2 context, so any template you place there influences their output.

## Operator workflow before kickoff

For each new factory project:

1. Create the new target repo (greenfield) or clone the existing one (brownfield)
2. `mkdir -p _bmad-output/planning-artifacts`
3. Copy these templates from shipyard into that directory:
   ```bash
   cp /path/to/shipyard/gauntlet_docs/target-templates/*.md \
      /path/to/new-target/_bmad-output/planning-artifacts/
   ```
4. Write the project-specific planning artifacts: `prd.md`, `architecture.md`, `epics.md`, `approved-tech-stack.md` — each consistent with the templates
5. Run the factory; the architect agent picks up the templates as part of its planning-artifact context

## Updating the templates

When a factory build surfaces a new lesson worth carrying forward (a CI pattern we should standardize, a story-writing anti-pattern we want to warn against), update the canonical version in this directory **and** the target's snapshot, then commit both. Treat updates here as part of factory v2 work — the templates are factory output as much as the Python code is.

## See also

- [factory-replication-guide.md](../factory-replication-guide.md) — how to set up a factory build from zero
- [factory-lessons-from-chat2diagram.md](../factory-lessons-from-chat2diagram.md) — retrospective these templates draw lessons from

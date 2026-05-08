# Target Templates

Twelve documents in this directory describe what the Shipyard factory expects from a target project. Copy each one into your target's `_bmad-output/planning-artifacts/` _before_ running the factory, and reference them when generating the target's own CI script, epics, and test layout. The lessons-learned protocol additionally requires copying its `## Agent Coding Rules` section header into the target's `CLAUDE.md`.

## The twelve templates

| File                                                                                 | Audience                                                                                                                                                         | Copy into target as                                                                                                                         |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| [ci-script-specification.md](ci-script-specification.md)                             | The bmad-architect agent that generates `scripts/ci.sh`                                                                                                          | `_bmad-output/planning-artifacts/ci-script-specification.md`                                                                                |
| [story-and-epic-writing-guide.md](story-and-epic-writing-guide.md)                   | The human (or agent) authoring `epics.md`                                                                                                                        | `_bmad-output/planning-artifacts/story-and-epic-writing-guide.md`                                                                           |
| [how-to-write-epics.md](how-to-write-epics.md)                                       | The PM author (or bmad-pm agent) drafting `epics.md` — 13 patterns that sit on top of standard story anatomy                                                     | `_bmad-output/planning-artifacts/how-to-write-epics.md`                                                                                     |
| [how-to-write-epics-for-android-vs-ios.md](how-to-write-epics-for-android-vs-ios.md) | The PM author drafting Android / iOS epics — mobile-specific patterns (platform discovery differences, store-listing handoff, no-Docker-for-mobile, phase gates) | `_bmad-output/planning-artifacts/how-to-write-epics-for-android-vs-ios.md` (only for projects with mobile epics)                            |
| [how-to-number-ux-spec.md](how-to-number-ux-spec.md)                                 | UX designer (or bmad-ux agent) — procedure for adding stable `UX-DR<N>` IDs so stories can cite patterns without depending on heading text                       | `_bmad-output/planning-artifacts/how-to-number-ux-spec.md` (run before `[frontend]` stories cite UX-DRs)                                    |
| [test-structure-guide.md](test-structure-guide.md)                                   | The bmad-architect agent + the dev agent on every story                                                                                                          | `_bmad-output/planning-artifacts/test-structure-guide.md`                                                                                   |
| [local-dev-docker-guide.md](local-dev-docker-guide.md)                               | The bmad-architect agent (generates `Dockerfile.dev` + `docker-compose.yml`) + dev agent (writes code that respects local stack topology)                        | `_bmad-output/planning-artifacts/local-dev-docker-guide.md`                                                                                 |
| [how-to-setup-dev-container.md](how-to-setup-dev-container.md)                       | The architect agent or operator setting up `.devcontainer/`, `Dockerfile.dev`, and `devcontainer-post-create.sh` for a Claude-friendly dev environment           | `_bmad-output/planning-artifacts/how-to-setup-dev-container.md`                                                                             |
| [how-to-setup-pre-commit-hooks.md](how-to-setup-pre-commit-hooks.md)                 | Operator (or dev agent) installing the in-repo git pre-commit hook that runs Phase 1 lint + typecheck on staged files; prevents type/lint debt accumulation     | Read at project setup; install via `git config core.hooksPath scripts/git-hooks` once per clone. No copy into `_bmad-output/` needed.       |
| [email-testing-guide.md](email-testing-guide.md)                                     | Projects with email-based auth or notifications — architect (CI), dev agent (E2E tests), operator (Railway service setup)                                        | `_bmad-output/planning-artifacts/email-testing-guide.md` (only for projects with email features)                                            |
| [how-to-manage-memory.md](how-to-manage-memory.md)                                   | Operator on Windows wanting Claude Code memory to live in-repo (portable across machines via flash drive / clone) instead of at the default user-home location   | Read once at project setup; recreate junction on each new machine. No copy into `_bmad-output/` needed.                                     |
| [lessons-learned-protocol.md](lessons-learned-protocol.md)                           | Architect at epic-review time + dev agent on every story (via `CLAUDE.md`)                                                                                       | `_bmad-output/planning-artifacts/lessons-learned-protocol.md` AND copy the `## Agent Coding Rules` section header into target's `CLAUDE.md` |

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
   cp /path/to/shipyard/targetsetup/*.md \
      /path/to/new-target/_bmad-output/planning-artifacts/
   ```
4. Write the project-specific planning artifacts: `prd.md`, `architecture.md`, `epics.md`, `approved-tech-stack.md` — each consistent with the templates
5. Run the factory; the architect agent picks up the templates as part of its planning-artifact context

## Updating the templates

When a factory build surfaces a new lesson worth carrying forward (a CI pattern we should standardize, a story-writing anti-pattern we want to warn against), update the canonical version in this directory **and** the target's snapshot, then commit both. Treat updates here as part of factory v2 work — the templates are factory output as much as the Python code is.

## See also

- [factory-replication-guide.md](../factory-replication-guide.md) — how to set up a factory build from zero
- [factory-lessons-from-chat2diagram.md](../factory-lessons-from-chat2diagram.md) — retrospective these templates draw lessons from

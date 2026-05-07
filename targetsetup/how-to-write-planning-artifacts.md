# How to Write Planning Artifacts

**Audience:** the BMAD planning agents (analyst, PM, architect, UX-designer, tech-writer) when authoring `_bmad-output/planning-artifacts/*` docs, and the operator reviewing those drafts before greenlighting an implementation run.

**One-line goal:** keep planning artifacts dense in load-bearing facts and lean on cross-doc fanout, because every cross-reference multiplies into a per-story file load during `bmad-create-story` (CS) and `bmad-dev-story` (DS).

## Why this matters

When CS and DS run, their workflows instruct the agent to perform "EXHAUSTIVE ARTIFACT ANALYSIS" — read the relevant epic, the previous story, architecture, and any docs those reference. The agent follows cross-references faithfully. **The size and cross-reference density of your planning artifacts directly drives how many files get loaded per story.**

This is not a bug in the BMAD methodology — the agent should see the context it needs. The question is whether your docs hand it that context efficiently or send it on cascading link-chases through tangentially-related files.

## The mechanism, observed

PawprintRecipes Epic 2, Story 2-2 ("User model + UserManager + Argon2 hashing", 29 minutes, 71 file reads). CS phase loaded ~12 unique files in the first 110 seconds. The `bmad-create-story` SKILL.md prescribes 8 of those:

- Activation files (`customize.toml`, `config.yaml`, `project-context.md`)
- Epic discovery (`epics/index.md`, the epic file itself)
- Sprint status, the previous story file
- `architecture.md`

The 4 additional files came from cross-references in the prescribed ones — most notably `database-schema.md`, which the epic spec referenced under "Critical migration ordering rules."

If the same epic had also cross-referenced `email-testing-guide.md`, `approved-tech-stack.md`, `ux-design-specification.md`, and `coding-standards.md` as separate "References" entries — the agent would have loaded all four, *whether or not story 2-2 actually needed them*. Multiply by the number of stories in the epic, and a chatty References section costs you many file loads.

## The lever: inline vs. link

When authoring a planning artifact, classify each fact:

- **Load-bearing for this epic's stories** — inline it directly in the doc the agent is already reading. Migration order, exact API contracts, naming conventions, security rules that override defaults, error-envelope shape.
- **Reference material** — link to it. Full database schema, complete UX specification, broad coding standards. The agent will follow the link only if a story actually needs it.

The principle: **if a story's correctness depends on a fact, put it where the agent will see it without following a link**. Don't make the agent decide whether `database-schema.md` §"Critical migration ordering rules" is the section it needs — paste the rule into the epic.

## When splitting is still right

Don't read the above as "always inline." Some docs should remain separate:

- `database-schema.md` — referenced across many epics; inlining into one epic would either over-burden it or be incomplete for others.
- `coding-standards.md` — applies project-wide; loaded by the orchestrator as a layer-1 context injection.
- `architecture.md` — the architectural overview, which CS already loads in step 3.
- UX specification — usually too large for inlining; the agent loads it via Glob when a `[frontend]` story cites a `UX-DR<N>` pattern.

The rule isn't "no separate docs." It's: **don't multiply doc count beyond what's earning its keep**, and don't multiply cross-references beyond what materially affects each story.

## Per-artifact guidance

### Epic specs (`_bmad-output/planning-artifacts/epics/epic-*.md`)

- **Inline:** acceptance criteria, file lists per story, ordering constraints, exact API contracts, error codes, env vars the story introduces.
- **Don't inline:** the full database schema, the complete UX spec.
- **References for Epic N section:** list only docs whose specific section materially affects *this epic's* stories. A 12-entry references block multiplies into 12 per-story loads.
- **"Files Likely Touched" per story** is the canonical record of what each story will modify — keep it accurate, the agent uses it heavily and a wrong list sends it hunting.
- **Cross-cuts encoded as same-commit edits** — call these out explicitly in the epic header so the dev agent doesn't split them across stories.

### Architecture (`_bmad-output/planning-artifacts/architecture.md`)

- This doc is loaded in full during CS step 3 — every link inside it cascades into per-story loads. Audit those links carefully.
- Keep architecture.md focused on architectural *decisions*, not a catalog of every file in the project.
- If a section is truly story-relevant, inline the rule rather than linking to a sister doc. Each link is a future cascade.

### Database schema, tech stack, infrastructure docs

- These are reference docs; separate files are fine.
- Watch for over-listing in epic-spec "References" sections. A schema doc referenced from every epic header costs you a load per story even when most stories don't touch the database.

### UX specification

- Stays separate; per-story citation via `UX-DR<N>` pattern numbers is how `[frontend]` stories pull what they need.
- Don't reference the UX spec from non-frontend epics — the agent loads it anyway.

## Authoring checklist

Before considering a planning artifact done:

1. **Every cross-reference earns its keep.** Each link multiplies into per-story loads across this epic. If most stories won't benefit from the linked doc, omit the link and inline the relevant fact.
2. **Load-bearing facts are inline.** If a story would fail without knowing X, X lives in the doc the agent will see — not three clicks away.
3. **The doc itself is necessary.** A new planning doc that captures three facts could live inside another doc.
4. **The "References" section is lean.** Five entries is healthy. Twelve is bloat. If you have twelve, ask which ones the *stories themselves* will consult, and demote the rest to inline-where-needed or omit.
5. **Per-story `Files Likely Touched` is accurate.** The dev agent uses this as the authoritative file list — wrong entries send it hunting and right entries save Glob calls.

## What this document is not

This is not a recommendation to fight the BMAD methodology's "EXHAUSTIVE ARTIFACT ANALYSIS" instruction. The agent should load the context it needs. The question this doc addresses is whether *your authoring choices* in the planning artifacts give the agent that context efficiently, or send it on link-chains through docs the story didn't actually need.

This is also not a tool for reducing load count for its own sake. CS and DS need to load enough to do their job correctly. The goal is making sure each load earns its place.

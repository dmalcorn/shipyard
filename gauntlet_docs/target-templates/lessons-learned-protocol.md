# Lessons-Learned Protocol (Target Template)

A two-tier system for capturing what went wrong during a project build so subsequent stories don't repeat the same mistakes. Tier 1 is the raw forensic record (one file per incident); Tier 2 is the distilled actionable rule (one line per pattern). Different consumers, different cadences, different ownership.

This is a copy-into-target template. The protocol below should appear in **the target's `CLAUDE.md`** (the file that Claude Code automatically loads as project context for every agent invocation), since the rules in Tier 2 only work if `CLAUDE.md` is read on every story. Place this guide at `_bmad-output/planning-artifacts/lessons-learned-protocol.md` for reference, and copy the relevant sections (especially "Tier 1 — Forensic record" format and the `## Agent Coding Rules` section header) into the target's `CLAUDE.md`.

## Why two tiers

Lessons need to serve two different audiences:

- **The architect agent at epic-review time** wants forensic context. What broke, when, what the fix was, what process gap let it through. This is Tier 1.
- **The dev agent on the next story** wants prescriptive rules. "Don't do X." "Always do Y in pattern Z." Self-contained, scannable, no historical context required. This is Tier 2.

If you collapse the two — only keep rules, no forensic detail — you lose the ability to revisit "wait, why did we make this rule?" six weeks later. If you collapse the other way — only forensic logs, no distilled rules — every dev agent has to read 30 history files before each story, blowing the context budget.

The chat2diagram build settled into this two-tier pattern empirically. This document codifies it.

## Tier 1 — `lessons-learned/NNN-<slug>.md` files

Each incident gets its own file. Numbering is sequential, format is fixed:

```
target/lessons-learned/
├── 001-ux-spec-enforcement.md
├── 002-missing-logout-ui.md
├── 003-unique-vs-index-drizzle-schema.md
└── …
```

Format every file follows:

```markdown
# Lesson Learned: <one-line title>

**Date:** YYYY-MM-DD HH:MM UTC
**Epic/Story:** <id>
**Severity:** <High | Medium | Low>
**Discovery:** <how the issue was surfaced — usually CI failure>

---

## What Happened
<2-4 sentences: the specific failure pattern>

## Root Cause Analysis
<2-4 sentences: WHY it happened — the process or structural reason, not just the surface bug>

## What Was Fixed
<2-4 sentences: the correction applied; cite specific files>

## Prevention Rules
- <one short prescriptive sentence — actionable, self-contained>
- <another prescriptive sentence>
- <2-5 bullets total>
```

### Who writes Tier 1 entries

**Automatic (factory-driven).** When a story's CI takes more than one cycle to pass (i.e., `fix_ci` had to run at least once), the factory's distillation phase invokes a Claude CLI agent that reads the per-cycle CI logs and the git diff and writes a new `lessons-learned/NNN-*.md` file in the format above. The new file is staged into the same git commit as the story's code. No operator action required. No BMAD skill installed; the prompt is built inline by the factory.

**Manual (operator-driven).** Some lessons aren't fix_ci-shaped — deployment failures (e.g. Railway misconfiguration), UX realizations (e.g. spec gaps surfaced during dev), strategic process decisions. Operators write these by hand, following the same format. The auto-distillation handles the per-incident technical patterns; humans handle the rest.

The two paths coexist. Automatic is a backstop against operator forgetfulness; manual is for cases the factory can't see.

## Tier 2 — `## Agent Coding Rules` section in `CLAUDE.md`

A single section in the target's `CLAUDE.md`, populated cumulatively over the build. Each rule is one prescriptive sentence:

```markdown
# CLAUDE.md — <project>

…(other sections)…

## Agent Coding Rules

- Never classify errors by matching on `error.message` strings — use typed error classes from `src/lib/errors.ts` and `instanceof` checks (see lessons-learned/006-...md).
- When a story adds a required field to a shared type, search every test fixture and mock for that type and update each one in the same commit (see lessons-learned/002-...md).
- Use `npx prettier` not bare `prettier` in pre-commit hooks so tools resolve from project-local installs (see lessons-learned/007-...md).
- …
```

Properties:

- **One sentence per rule.** Self-contained. The dev agent reading 30 of these in a row should not need to fetch any context to act on each one.
- **Cite the source lesson.** End the rule with `(see lessons-learned/NNN-…md)` so the architect or operator can revisit the forensic record later.
- **Loaded automatically by Claude Code.** `CLAUDE.md` is project-scoped context that every Claude CLI invocation reads as part of its system prompt. The dev agent sees these rules without any explicit prompt injection from the factory.

### Who writes Tier 2 entries

**Architect-driven, at epic-review time.** The factory's `epic_architect_node` runs at the end of each epic. Its prompt instructs it to (a) read all Category B review findings, (b) read every `lessons-learned/*.md` file (including the ones auto-captured during this epic), (c) look for recurring patterns (seen in 2+ stories OR explicitly flagged in a lesson's Prevention Rules), and (d) append matching rules to `CLAUDE.md`'s `## Agent Coding Rules` section.

The architect is the **gate** for Tier 2. Single-incident lessons live in Tier 1 only. Promotion to Tier 2 requires recurrence or architect judgment.

**Operator-driven, ad-hoc.** Operators may add rules manually if a lesson is important enough to surface immediately rather than wait for the next epic-review. Same format and citation requirement as the architect's additions.

## How dev agents see lessons

Without any prompt injection from the factory:

- `CLAUDE.md` (Tier 2) is loaded automatically by Claude Code on every dev agent invocation. The `## Agent Coding Rules` section is in the dev agent's effective system prompt for free.
- Tier 1 files are *not* automatically loaded — they're available via the dev agent's `Read` tool on demand. If a rule cites a lesson and the agent wants the full context, it can fetch it itself.

This means **the cost of accumulating lessons is bounded** to the size of the rules section in `CLAUDE.md`. Tier 1 files can grow indefinitely without affecting per-invocation context budget.

## Trigger conditions, in summary

| Event | What gets written | By whom |
|---|---|---|
| Story passes CI on cycle 1 | Nothing | (no lesson) |
| Story passes CI after >1 cycle | `lessons-learned/NNN-*.md` (Tier 1) | Factory's `_maybe_distill_lesson` |
| Story marked failed (gave up after max retries) | `lessons-learned/NNN-*.md` (Tier 1) at next-story discovery time, OR operator-written | Operator (manual) |
| Epic completes (epic-review phase) | New rules in `CLAUDE.md ## Agent Coding Rules` (Tier 2) | Architect (automatic) |
| Operator finds a non-fix-ci issue (deploy, UX, process) | `lessons-learned/NNN-*.md` (Tier 1), optionally a Tier 2 rule | Operator (manual) |

## Anti-patterns

| Anti-pattern | Why it hurts | Fix |
|---|---|---|
| Pruning `lessons-learned/` files when they feel "no longer relevant" | Strips forensic context the architect needs to judge new patterns | Don't prune. Files are cheap. |
| Adding Tier 2 rules without citing the source lesson | Future readers can't answer "wait, why did we add this rule?" | Always end the rule with `(see lessons-learned/<file>.md)` |
| Letting Tier 2 rules accumulate without distillation | Eventually `CLAUDE.md` becomes a wall of one-sentence rules and the dev agent's effective context gets noisy | Periodic operator review (per epic): consolidate or remove rules that have been superseded |
| Hand-editing auto-captured Tier 1 files to "improve" them | Confuses provenance — a lesson the architect references may now describe something the agent didn't actually capture | Add a follow-up lesson if the original was wrong; don't rewrite the original |
| Skipping Tier 1 because "we'll just remember" | The whole point of this protocol — humans don't remember | Trust the auto-distillation. If a lesson is bad, delete it (one operation); if it's missing, add manually |
| Promoting every Tier 1 lesson to Tier 2 | Tier 2 becomes noise; the dev agent's signal-to-noise ratio drops | Only the architect promotes. The architect's job is to recognize recurrence. |

## What this protocol does NOT cover

- **Cross-project lessons.** This protocol is scoped to one project. Lessons learned in one factory build don't automatically inform the next project's build. That's the role of the factory's `gauntlet_docs/factory-lessons-from-chat2diagram.md` pattern: cross-project durable patterns get captured there, project-specific tactical lessons stay in `lessons-learned/`.
- **Code-style enforcement.** Pre-commit hooks, ESLint configs, ruff configs do that. This protocol is for things that hooks and linters can't catch — pattern-level mistakes, process gaps, architectural drift.
- **Architecture decisions.** ADRs (architecture decision records) belong in `_bmad-output/planning-artifacts/architecture.md` or a separate `decisions/` directory. Lessons-learned captures unexpected outcomes; ADRs capture intentional decisions.

## See also

- [story-and-epic-writing-guide.md](story-and-epic-writing-guide.md) — story ACs that include "Cross-cutting Considerations" reduce the need for Tier 1 captures by anticipating cascading changes
- [test-structure-guide.md](test-structure-guide.md) — central mock factories and story-tag conventions, both of which directly prevent classes of failures that would otherwise become Tier 1 lessons
- [factory-lessons-from-chat2diagram.md](../factory-lessons-from-chat2diagram.md) — the cross-project equivalent (lessons that promote to factory hardenings instead of target rules)

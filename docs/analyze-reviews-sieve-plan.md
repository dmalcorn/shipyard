# Analyze-Reviews → Sieve: Plan & Discoveries

**Status:** Paused — waiting for Epic 3's epic-level review cycle to run so we can observe real BMAD native output at the epic level before finalizing the sieve design.

**Created:** 2026-04-12
**Context:** Investigating `analyze_reviews_node` in `src/intake/epic_graph.py` after observing it took ~5 minutes on Epic 2's review cycle.

---

## The problem

`analyze_reviews_node` is supposed to be clerical: take two review files produced by the BMAD and Claude reviewers and split each finding into Category A (obvious fix) or Category B (architect review). Instead, it invokes a `sonnet` Claude agent with the `analyze-reviews` label, and the prompt at [epic_graph.py:685-714](../src/intake/epic_graph.py#L685-L714) asks it to:

- *"Create an agreement analysis"*
- *"Compute agreement rate"*
- *"Deduplicate equivalent findings across reviewers"*
- *"Classify every unique finding..."*

The prompt invites re-analysis, not clerical sorting. On the Epic 2 run (session `f6c5b9b9`, 23:52:14 → 23:57:31 UTC) it burned **5 minutes, 17 seconds** and ~$0.41 on work that should be instantaneous.

## The intent (per user)

> "I envisioned that would be more of a clerical type of an analysis... The BMAD agents come back with an answer that's really clear. They say which things need to be fixed, they rank them, and they've got categories that are very, very clear. I don't need to have those analyzed again. It's the issues that were found that are not clear that I want to hand off to the architect."

The vision: replace the agent call with a deterministic Python **sieve** that reads both review files, routes each finding by the structured labels the reviewers already provide, and writes the two category files. No LLM, no re-analysis, no source file reads, no agreement-rate calculation, no semantic dedup.

## Key discovery: BMAD skill native output format

Found by searching the Railway `log_events` database dump for `bmad-code-review` mentions. Session `656c3ffa-e9ec-42d4-b7bf-50dc5410b25b` from 2026-03-28 ran the `bmad-code-review` skill at story level with full dev tools (`Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(*),Skill`).

### The four triage categories

The `bmad-code-review` skill's Step 3 (triage) sorts every finding into exactly one of:

| Category | Meaning | Disposition |
|---|---|---|
| **`patch`** | Obvious fix, single correct answer | **Auto-applied inline by the skill during the review** (when tools allow) |
| **`defer`** | Real issue, not blocking, address later | Appended to `_bmad-output/implementation-artifacts/deferred-work.md` |
| **`dismiss`** | False positive / noise | Reported in summary only, not persisted |
| **`decision-needed`** | Controversial, needs judgment | Reported in summary + written to story file |

### The summary line format (captured verbatim)

From session 656c3ffa, story 1-1 completion (March 28, 05:49:46 UTC):

```
**Code review complete.**
> **0** `decision-needed`, **4** `patch` (all fixed), **10** `defer`, **8** dismissed as noise.
> Findings written to `_bmad-output/implementation-artifacts/1-1-go-backend-project-scaffold.md`.
> Deferred items written to `_bmad-output/implementation-artifacts/deferred-work.md`.
```

Other examples from the same session:
- Story 1-2: `0 decision-needed, 9 patch, 5 defer, 8 dismissed as noise`
- Story 1-3: `2 decision-needed (auto-resolved), 9 patch, 10 defer, 7 dismissed as noise`

### `deferred-work.md` format

Living document grouped by story, each section a bulleted list. Current file on disk at `chat2bpmn/_bmad-output/implementation-artifacts/deferred-work.md` has ~10 sections covering stories 1-1 through 2-2. Sample:

```markdown
# Deferred Work

## Deferred from: code review of 1-7-project-settings-provider-configuration (2026-04-11)

- **appendConfigHistory read-modify-write race**: The function reads current
  JSONB array, appends in JS, writes back. Concurrent saves can lose entries.
  Spec notes single-writer pattern...
- ~~**extractProjectId manual URL parsing**~~: **RESOLVED** — See 1-6 resolution above.
```

Strikethrough + `**RESOLVED**` marks items fixed later. Clean, parseable, consistent.

## Mapping BMAD categories to factory buckets

The really good news: **BMAD already does the triage** the factory currently pays a Claude agent to do. A sieve can read BMAD's output directly and route:

| BMAD category | Factory bucket |
|---|---|
| `patch` | Category A (obvious fix) |
| `decision-needed` | Category B (architect) |
| `defer` | *new bucket* — append to `deferred-work.md`, no agent runs |
| `dismiss` | drop |

The Claude reviewer has no such labels — it emits `critical`/`major`/`minor` severity per the template the factory provides. A sieve would map Claude's output by a simpler rule (e.g., `major`/`critical` → Cat B, `minor` → Cat A) or inspect the "Action" field for triviality cues.

## Three open questions blocking the sieve design

### 1. What does BMAD emit at the *epic* level with read-only tools?

At story level, BMAD had full dev tools and auto-applied its `patch` items inline. At the epic level, the code passes `TOOLS_REVIEW_READONLY` (no `Edit`/`Write`/`Bash(*)`). When the skill's triage step tries to auto-apply a patch with no `Edit` tool, one of three things happens:

- **(a)** It downgrades the finding to `defer`.
- **(b)** It reports the `patch` without applying and tells the caller to apply it.
- **(c)** It errors out and the whole review fails.

**We don't know which until Epic 3's review cycle runs.** The BMAD prompt rewording from earlier in this session (epic_graph.py `epic_review_node` now says "Run the bmad-code-review skill on ALL code changes across this entire epic") hasn't executed yet — Epic 2's review already ran before that change landed.

### 2. Should `defer` be its own pipeline bucket or merge into Category B?

BMAD introduces a category the factory doesn't currently have. Options:

- **Option A:** Merge `defer` into Category B. The architect decides per item whether to fix now or actually defer. Simple, keeps the existing two-bucket pipeline, but duplicates work BMAD already did.
- **Option B:** Add a third bucket. The sieve appends `defer` items to `deferred-work.md` and skips any agent invocation for them. Matches BMAD's native convention and the "clerical split" intent exactly. Small wiring change in the graph.

User's intent favors **Option B** (clerical, no re-judgment). Recommend confirming after seeing epic-level behavior.

### 3. How does the epic-level BMAD output relate to story files and `deferred-work.md`?

At story level, BMAD writes findings back to the **story's** .md file and appends defers to `deferred-work.md`. At epic level, there's no single "story file" to write into — the epic spans many stories. BMAD might:

- Write per-story findings back to each story file (multi-write).
- Write a single consolidated epic findings file.
- Only emit the triage summary in stdout and rely on the caller to persist it.

The epic-level review runs under `epic_review_node` which captures stdout via the wrapper node and writes `epic-reviews/epic-review-bmad.md`. So BMAD's final agent output becomes that file — and the sieve reads *that* file. But what the file's internal structure looks like at epic level is unknown.

## The plan (once Epic 3's data arrives)

1. **Observe Epic 3's real BMAD output** at `chat2bpmn/epic-reviews/epic-review-bmad.md`. Verify the triage summary format matches story-level (4 categories). Verify that `patch` items appear in the file (since read-only tools should prevent inline application). Check whether `defer` items appear in-line or whether something tried to write to `deferred-work.md` and failed.
2. **Verify Claude's review** at `epic-reviews/epic-review-claude.md` still emits the expected Summary/Findings/Severity template.
3. **Design the parser.** Two parse functions:
   - `parse_bmad_review(content)` — tolerant markdown/text parser that extracts findings with their BMAD triage category.
   - `parse_claude_review(content)` — tolerant parser for the Summary/Findings template, mapping `severity` to a coarse category.

   If either parser fails, fall back to: **dump every finding from that reviewer into Category B** (safer side — architect reviews it).
4. **Write `_sieve_reviews()`** helper near `_epic_fix_plan_path` in `epic_graph.py`. Takes both review file paths, returns `(cat_a_items, cat_b_items, defer_items)`. Writes the three output files (`category-a-fix-plan.md`, `category-b-architect-review.md`, and appends to `deferred-work.md` if Option B).
5. **Rewrite `analyze_reviews_node`** — body collapses from ~45 lines + LLM call to ~10 lines + function call. Node stays for graph wiring; downstream `fix_category_a` and `epic_architect` don't care how the category files got written.
6. **Unit tests** against fixture review files saved from Epic 2 and Epic 3 runs.
7. **Optional graph change** (if Option B chosen): add a new trivial node between the sieve and the existing routing that just logs the deferred count. Or fold into `analyze_reviews_node` itself.
8. **Keep the agent as a fallback.** If either review file fails to parse, fall back to invoking the current analyze-reviews agent. Belt-and-suspenders during transition.

## Adjacent work already completed in this session (2026-04-11 → 2026-04-12)

Recorded here so a future session can see the context these changes give:

1. **BMAD reviewer prompt reworded** — `epic_review_node` now tells `bmad-agent-dev` to run the `bmad-code-review` skill by name, with no hunter names, step references, or output format override hardcoded. Rationale: prior prompt flattened BMAD's native triage output into a generic Summary/Findings format. See `epic_graph.py:599-615`.

2. **Epic fix plan filename now includes epic number** — `EPIC_FIX_PLAN_FILENAME_TEMPLATE = "epic-{epic_num}-fix-plan.md"`, routed through `_epic_fix_plan_path()` helper. Prior bug: architect wrote to `epic-reviews/epic-fix-plan.md` (drifted from bare-filename prompt) while fix-dev read `chat2bpmn/epic-fix-plan.md` (stale Epic 1 leftover, 14 fixes), causing fix-dev to spend 7 minutes "re-applying" 13 already-done fixes. See `epic_graph.py:75, 527-575, 854, 941`. Epic 2's plan renamed on disk to `epic-2-fix-plan.md` to match new convention.

3. **Architect `fixes_needed` check hardened** — replaced naive `"fixes_needed: false" in content.lower()` substring search with `_parse_fix_plan()` helper that parses YAML front matter tolerantly (whitespace, case, `true`/`false`/`yes`/`no`/`1`/`0`) AND counts `### Fix …` headings inside the `## Approved Fixes` section. Routing decision is now `flag AND approved_count > 0`. Either signal saying "no work" routes to `no_fix`. See `epic_graph.py:537-575, 914-930`. Verified against 8 edge cases including `FALSE` uppercase, whitespace-before-colon, missing front matter, and stray `### Fix` headings in the Dismissed section.

## How to pick back up in a future session

1. Check whether Epic 3's review has completed: look at `chat2bpmn/epic-reviews/` for recent timestamps, and grep the Railway `log_events` database for session IDs newer than `f6c5b9b9-0909-406f-b483-639478ab4854`.
2. Read the fresh `epic-review-bmad.md` and `epic-review-claude.md` to see the actual parseable format.
3. Resume at step 3 of "The plan" section above (design the parser).
4. If any of the "adjacent work" items from this session turn out to have regressed, fix those before touching the sieve.

## Files referenced

- [src/intake/epic_graph.py](../src/intake/epic_graph.py) — main graph module, contains all the nodes discussed
- `chat2bpmn/epic-reviews/` — epic-level review outputs
- `chat2bpmn/_bmad-output/implementation-artifacts/deferred-work.md` — BMAD's shared deferred-work log
- `chat2bpmn/.claude/skills/bmad-code-review/` — the skill itself (workflow.md + steps/step-01 through step-04)
- `logs/railway-dump-20260411-193447/log_events.jsonl` — 47,525 captured events across all sessions; searchable for `bmad-code-review` and similar
- `logs/session-f6c5b9b9-current/console.log` — Epic 2 live-session plain-text console transcript
- `logs/story-1-1-bmad-review.txt` — extracted story-1-1 bmad-code-review run (session 656c3ffa, March 28) — reference sample of BMAD behavior with full dev tools

# Story-Level Code Review — Redesign Proposal

**Status:** Proposal — no code changes yet. Operator decisions incorporated 2026-05-08.
**Date:** 2026-05-08
**Author:** Claude (drafted at operator request)

## TL;DR

Today's story-level code review is a single-agent "find issues and auto-fix everything you find" call. This is too aggressive — the operator turns it off in practice because there's no chance to triage what the agent decides to change. The epic-level flow, at the other end of the spectrum, is too elaborate for per-story use (two parallel reviewers, deterministic sieve, conditional architect call, four file outputs).

This proposal recommends a **middle ground for story level**: separate "review" and "fix" into two sequential agent calls, with the existing epic-level sieve dropped in between to split findings into auto-fix (Category A) vs defer-to-epic-review (Category B). The architect step stays at the epic level only — that's the right cadence for design decisions.

The result: story-level reviews regain operator trust (Category B items are visible and deferred, not silently changed), reuse infrastructure that already works, and add only one extra agent invocation per story (the read-only reviewer).

## Today's flow (the problem)

[`code_review_node` in `src/multi_agent/orchestrator.py:598`](../src/multi_agent/orchestrator.py#L598) is one agent call:

```python
result = invoke_bmad_agent(
    bmad_agent="bmad-agent-dev",
    command=f"code review for story {task_id}",
    tools=TOOLS_CODE_REVIEW,            # includes Edit, Write — not read-only
    working_dir=working_dir,
    timeout=TIMEOUT_MEDIUM,
    model=_model_for("code_review"),
    extra_context=(
        "When the code review workflow asks what to do with issues, "
        "automatically choose to fix them. No waiting for user input."
    ),
)
```

Three structural problems:

1. **Same agent finds and fixes.** No independent second opinion on whether a flagged issue is real, whether the proposed fix is the right one, or whether it's even worth fixing now vs deferring. The agent's own assessment is the only assessment.
2. **Auto-fix everything is the only mode.** The `extra_context` short-circuits the BMAD code-review skill's natural "what would you like to do?" prompt and tells the agent to apply every fix it can think of. There is no triage step that distinguishes "obviously safe lint-style nit" from "subtle architectural change that warrants a second look."
3. **Zero operator visibility into what changed and why.** The node returns a `files_modified` list but no record of *why* each file was modified — the reasoning lives in the agent's transcript and is not captured as an artifact. Auditing what the review actually did requires reading the conversation log after the fact.

The combination of #2 and #3 is why the operator currently disables this step. The `set_story_reviews_enabled(False)` toggle is doing real work — but disabling the whole step means the codebase loses any per-story signal between dev_story and run_ci. Reviews now happen only at the epic boundary, which is too late for catching consistency drift between stories within an epic.

## What the epic flow does (the model to borrow from, selectively)

The epic-level review pipeline ([`epic_graph.py:736-1247`](../src/intake/epic_graph.py#L736)) is six nodes:

```
prepare_epic_reviews → epic_review × 2 (BMAD + Claude, parallel)
  → collect_epic_reviews (fan-in, validate)
  → analyze_reviews (deterministic sieve into Category A / B / defer)
  → fix_category_a (auto-apply clear fixes)
  → [if Cat B exists] epic_architect → epic_fix
  → epic_ci → epic_git_commit
```

**Worth borrowing:**
- **Read-only review.** The epic reviewers use `TOOLS_REVIEW_READONLY` and produce a findings file. They cannot mutate code. The output is an auditable artifact.
- **Sieve-based categorization.** [`analyze_reviews_node`](../src/intake/epic_graph.py#L1018) parses the reviewer's findings deterministically into Category A (unambiguous fix, single correct path — typos, missing imports, style violations) and Category B (multiple valid approaches, security implications, design decisions). This is exactly the triage the current story flow lacks.
- **Auto-fix only Category A.** Category B is held out for the architect. This means the agent never silently makes design decisions on its own.

**Too elaborate for story level:**
- **Two parallel reviewers.** BMAD + Claude in parallel doubles the LLM cost and produces two files that need fan-in/dedup. Justified at epic level (broader scope, cross-story coherence to catch). Overkill at story level (single story, single change set, narrow scope).
- **Architect call.** The epic architect ([`epic_architect_node`](../src/intake/epic_graph.py#L1347)) is an opus call that takes Category B items and designs the right fix before any code changes. At per-story cadence this is too expensive (one opus call per story) and too narrow (story-level Category B items often need cross-story context that only emerges at epic-level review).
- **Multi-file outputs** (analysis.md + cat_a.md + cat_b.md + deferred-work entries). Useful at epic level for the architect to read. Excessive at story level where the operator just wants to know "what changed and what was deferred."

## Proposed design

A three-node story-level review block, replacing the single `code_review_node`:

```
dev_story → story_review → story_triage → run_ci → ...
```

### Node 1: `story_review` (new — replaces `code_review_node`)

Read-only single-agent review. Same pattern as `epic_review_node` but scoped to one story.

- Invokes `bmad-agent-dev` with the bmad-code-review skill — **single reviewer, BMAD only** (operator decision: simplest possible per-story review; the BMAD + Claude pair stays at epic level where the breadth justifies the cost)
- Tools: `TOOLS_REVIEW_READONLY` (no Edit/Write capability — agent cannot mutate)
- Output: a findings file at `checkpoints/story-review-{task_id}.md` using the same review-format YAML/markdown shape as epic reviews
- No "auto-fix" instruction in the prompt — just produce the report
- Prompt is the minimal "do a code review on story `{task_id}`" that lets the bmad-code-review skill drive the workflow as authored

This step is purely diagnostic. The review file is preserved per story for operator audit and for downstream review-of-reviews if needed.

### Node 2: `story_triage` (new — uses existing sieve infrastructure)

Deterministic sieve, no LLM call. Reuses `sieve_reviews()` from the epic-level path with one input file instead of two.

- Reads the story-review findings file
- Splits into:
  - **Category A** (clear fix): bundle into a fix plan and pass to a fix-only agent invocation
  - **Category B** (needs design): write to `_bmad-output/deferred-work.md` with a story tag, **do not fix**, **do not invoke architect**
- Output paths: `checkpoints/story-fix-plan-{task_id}.md` (Category A) and an appended block in the **single shared `deferred-work.md`** (operator decision — the same file the epic-level path already appends to; story tags in each entry let operators filter by story-id later if the file grows)
- Returns a flag indicating whether Category A items exist

If Category A is empty, the next node is skipped entirely — no fix agent invocation when there's nothing to fix.

### Node 3: `story_fix` (new — only runs if Category A items exist)

Single-agent fix call against the Category A plan.

- Invokes `bmad-agent-dev` with the standard fix tools
- Prompt: "Read the fix plan at `checkpoints/story-fix-plan-{task_id}.md`. Apply each fix exactly as specified. Do not invent additional fixes."
- This is the same surgical-fix pattern as `epic_fix_node` — the fix agent is told the plan is authoritative and not to scope-creep

### Why no architect at story level

The architect's value is **synthesizing across multiple findings to produce a coherent design**. At story level, individual Category B items rarely have enough context to design well — a "this might need a different schema shape" finding from one story makes more sense reviewed alongside related findings from other stories in the same epic. Deferring Category B items to the existing epic-level architect is the right cadence: by epic-end, the architect sees the full set of design questions accumulated across the epic and can decide each in context.

This means story-level review **never silently makes design decisions**. Category A is mechanical (the operator can trust the auto-fix). Category B is visible (in `deferred-work.md`) and gets human-or-architect attention later.

### Operator-visible artifacts per story

After `story_fix` completes, the operator can inspect:
- `checkpoints/story-review-{task_id}.md` — what the reviewer found (every finding, before triage)
- `checkpoints/story-fix-plan-{task_id}.md` — what auto-fixed (Category A only, with rationale per fix)
- `_bmad-output/deferred-work.md` — newly-appended Category B items tagged with story id

These are auditable and stored in the target repo, not the agent's transcript.

## Alternatives considered

### Alternative A: "Just remove the auto-fix instruction"

Keep one agent call. Strip the `extra_context` line that says "automatically choose to fix them." The bmad-code-review skill would then prompt the agent for a decision, which (since there's no human in the loop in autonomous mode) defaults to a stop-and-report behavior.

- **Pros:** Single-line change. No new nodes.
- **Cons:** No auto-fix at all means every finding becomes operator work. Operator told me they want *some* level of automatic action, just not "fix everything." This alternative goes too far the other direction.

### Alternative B: "Two parallel reviewers, like epic"

Mirror the epic flow exactly: BMAD + Claude reviewers in parallel, sieve, fix, conditional architect.

- **Pros:** Symmetry with epic flow. Two reviewers catch different things.
- **Cons:** Doubles the LLM cost per story. The cross-reviewer dedup is more useful at epic level (broader scope) than story level (narrow scope, fewer findings, less duplication value). Operator described the epic flow as "too involved" — replicating it at story cadence would compound the cost.

### Alternative C: "Single agent finds + fixes, but writes a fix log"

Keep the single agent call but require it to write a per-fix rationale to a log file before each Edit/Write. Operator can read the log post-hoc to audit.

- **Pros:** Minimal structural change.
- **Cons:** Doesn't solve the core problem — agent still finds *and* fixes in one pass, with no separate triage. The log helps audit but doesn't prevent unwise fixes from landing. Also: agents are unreliable about writing-then-doing in a single conversation; the log can drift from actual edits.

The proposed three-node design avoids all three downsides while staying significantly simpler than epic-level orchestration.

## Trade-offs

**Costs added vs current state (auto-fix-on):**
- One extra agent invocation per story (the read-only reviewer is new; `story_fix` replaces today's `code_review_node` LLM call). Net: +1 medium-timeout LLM call per story.
- Story latency increases by ~5-15 minutes per story depending on review complexity.
- Two new artifact files per story (review + fix plan); one cumulative deferred-work file.

**Costs added vs current state (auto-fix-off):**
- One extra agent invocation per story for the reviewer; one more if Category A items exist.
- Latency: +5-15 min per story, with the option to disable via the existing `reviews.story_level: false` toggle for fast iteration cycles.

**Value gained:**
- Operator gets back the per-story review signal that's currently disabled.
- Auto-fix is now bounded to Category A — the operator's stated trust threshold.
- Category B items become visible (in `deferred-work.md`) instead of either "fixed without anyone seeing" or "never raised."
- Reuses existing sieve infrastructure — `sieve_reviews()`, `render_category_file()`, `append_deferred_work()` are already battle-tested at epic level.

## Implementation sketch (for later)

When you're ready to implement, the changes are localized:

1. **`src/multi_agent/orchestrator.py`** — replace `code_review_node` with three new nodes. Update `build_orchestrator()` graph wiring around line 2005 to chain `story_review → story_triage → story_fix?` between `dev_story` and `run_ci`. The `?` is a conditional edge: skip `story_fix` if `has_category_a_items` is False.
2. **State schema** (`OrchestratorState`) — add fields for `story_review_path`, `story_fix_plan_path`, `has_category_a_items`. Mirror the epic-state additions.
3. **`src/intake/checkpoint.py`** — add `story_review`, `story_triage`, `story_fix` to the resume entry-phases set so phase-resume works for the new nodes. **Granular checkpointing** (operator decision): if a run is interrupted partway through the review block, resume picks up at the specific node that didn't complete — not by re-running the whole review block. Three new entries in `_RESUME_ENTRY_PHASES`.
4. **`factory.yaml`** — no required changes; the existing `reviews.story_level` toggle continues to enable/disable the whole story-review block.
5. **Sieve module** — currently in `src/intake/review_sieve.py` and called only from `epic_graph.py`. Will need to be importable from `orchestrator.py` (cross-package import — already happens for other helpers, no new dependency direction). The sieve API takes two review files; calling it with one reviewer's content and an empty string for the other should already work — the sieve was written to be tolerant. Confirm before relying on it; fall back to a single-input adapter if needed.

Estimated effort: a focused half-day, with testing.

## Operator decisions (incorporated above)

1. **Single reviewer.** BMAD dev agent only. The BMAD + Claude pair stays at epic level.
2. **One shared `deferred-work.md`.** Story-level and epic-level Category B items both append here. Each entry tagged with story-id (or epic-id) so they're filterable.
3. **BMAD dev agent for the review.** Same agent that does the epic-level BMAD reviewer pass. Prompt is the minimal "do a code review on story `{task_id}`" and the bmad-code-review skill drives the workflow.
4. **Granular resume.** If a run is interrupted partway through the three-node review block, resume picks up at the specific node that didn't complete (`story_review`, `story_triage`, or `story_fix`) — not at the start of the block.

## Failure handling — mirror the epic-level patterns

Operator decision: the same failure classes that can occur at the epic level can occur at the story level (rate-limit blips, agent timeouts, output format drift, empty reviews, sieve crashes). They get the **same treatment** at story level that they already get at epic level — no novel patterns introduced for story scope.

### Failure modes and their existing epic-level handling, applied at story level

The four failure classes and where the codebase already handles them at epic level:

| # | Failure | Epic-level handling (already in code) | Story-level applies the same |
|---|---|---|---|
| 1 | **LLM API errors** (rate-limit, 5xx, network) | `invoke_bmad_agent` and `invoke_claude_cli` already wrap the subprocess call with backoff/retry via `get_rate_limit_sleep_seconds()` in [`bmad_invoke.py`](../src/multi_agent/bmad_invoke.py). The agent-invocation layer handles this transparently. | Inherited automatically — `story_review` calls `invoke_bmad_agent` and gets the same retry behavior at no extra wiring cost. |
| 2 | **Agent timeout** (`TIMEOUT_MEDIUM`, 25 min) | Subprocess killed; `result["success"] = False`. Epic-level [`epic_review_node`](../src/intake/epic_graph.py#L813) still writes whatever output was captured to the review file, and [`collect_epic_reviews_node`](../src/intake/epic_graph.py#L962) treats an empty/malformed file as a hard failure that raises and triggers retry-on-resume. | Same. `story_review` writes whatever was captured. If the captured content is too small to be a real review, `story_triage` raises (matching pattern #4). On resume, the review re-runs from scratch. |
| 3 | **Output format drift** (substantive content but sieve parses zero findings) | Caught at [`epic_graph.py:1114-1127`](../src/intake/epic_graph.py#L1114): if the file is >`REVIEW_MIN_CONTENT_CHARS` but `sieve_reviews()` returns zero findings, log a "format drift suspected" warning and trigger the LLM-fallback agent ([`_analyze_reviews_agent_fallback`](../src/intake/epic_graph.py#L1174)) to re-parse the review with an LLM. | Same fallback path. `story_triage` checks the same threshold and, on suspected drift, invokes a story-scoped variant of `_analyze_reviews_agent_fallback` against the single review file to recover the findings. |
| 4 | **Empty / near-empty review file** | [`collect_epic_reviews_node`](../src/intake/epic_graph.py#L962) raises `RuntimeError`. The exception propagates up through `run_epic_node` in `rebuild_graph`, which catches it, marks the epic failed, and **leaves the phase checkpoint untouched** so the next resume retries the review from scratch. | Same. `story_triage` raises `RuntimeError` on a too-small review file. The orchestrator catches it, marks the story failed, leaves the story-phase checkpoint untouched, so the next resume re-runs `story_review`. The operator can intervene if the failure is persistent (e.g. agent confused by the story spec). |

### Failure handling for triage and fix nodes

**`story_triage` (deterministic sieve, no LLM).** Same as the epic-level analyze step: a code-level exception bubbles up and fails the story. This is correct — sieve bugs should produce a clear stop signal, not silently skip review.

**`story_fix` (applying Category A plan).** Mirror the epic-level `epic_fix_node` and `invoke_ci_with_fix` retry pattern: bounded retries on the LLM-side fix (LLM API errors handled by `invoke_bmad_agent`'s retry; non-API failures bubble up). A partial-apply on a Category A plan fails the story — same posture as `epic_fix_node` failures today, leaves the story-phase checkpoint pointing at `story_fix` so resume re-applies cleanly.

### Net result

Every failure mode the operator might encounter at story level is handled by code patterns that already exist and are battle-tested at the epic level. No new failure-handling philosophy is introduced for story scope — the implementation work is "extract the existing patterns from `epic_graph.py` and apply them to the new three-node story block."

If the LLM-fallback path for format drift turns out to be too heavy for per-story cadence in practice, it can be downgraded later to "log warning, skip triage + fix, defer to epic-level review" — the safety net is real because epic review still runs over the same diff. But starting with the same handling as epic and only relaxing if observed cost is too high is the safer migration path than starting with reduced handling and having to add it back.

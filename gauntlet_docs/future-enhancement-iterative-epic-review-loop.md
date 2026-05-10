# Iterative Epic Review Loop — Future Enhancement

**Status:** Proposal. Not built.
**Captured:** 2026-05-09 (during Epic 6 incident analysis)

## Concept

The current epic-level review cycle is one-shot:

```
prepare_epic_reviews → reviewers (parallel) → analyze_reviews
  → fix_category_a → epic_architect → epic_fix → epic_ci
    → pass: epic_git_commit → END
    → fail: epic_error → END
```

A failed `epic_ci` ends the epic. Architect-approved fixes that introduced *new* problems get caught by CI but never re-reviewed. The proposal is to loop back from `epic_ci` (on failure) to `prepare_epic_reviews`, re-run the review/fix cycle on the now-modified codebase, and repeat until the codebase converges (CI passes, or the reviewer finds nothing to change).

```
                          ┌────────────────────────────┐
                          │                            │
prepare_epic_reviews → reviewers → analyze_reviews     │
  → fix_category_a → epic_architect → epic_fix         │
    → epic_ci                                          │
      → pass: epic_git_commit → END                    │
      → fail (within budget): ─────────────────────────┘
      → fail (budget exhausted): epic_halt → END
```

## Why eventually

Convergent review-fix loops are a well-known agentic pattern — each pass addresses issues the previous pass surfaced. For complex epics (~10+ stories with cross-cutting concerns), one pass through the review cycle frequently leaves issues that the architect's own fixes either revealed or introduced. A second pass catches these; subsequent passes typically catch less.

Current behavior (one-shot) means the operator sees the result, manually triages, and either resumes for another factory build or gives up. Automating the loop would reduce operator load on epics that *would* converge with one or two more cycles.

## Why not now

1. **No data yet on convergence.** We don't know empirically how often a second cycle would have helped. Without that data we'd be optimizing speculatively.
2. **Cost compounds fast.** Epic 6's first fix cycle was ~30 minutes of agent time (architect call, fix-cat-a, fix-architect, then up to 4 CI attempts). Five cycles = 2.5+ hours per epic, billed even when the second cycle wouldn't have helped.
3. **Context bloat risk.** Naive implementations carry previous-cycle CI output forward into the next fix prompt. By cycle 3 you're feeding the agent multi-thousand-line stale context that degrades response quality.
4. **No convergence signal designed yet.** "CI passed" is the obvious stop, but the *informative* stop is "this cycle's reviewer found nothing to change" — that means we've converged. Building that signal cleanly requires changes to `analyze_reviews_node` to expose a "findings count" and to the routing logic.
5. **Operator handoff is missing.** When the budget is exhausted, the run needs to halt with a clear summary, not silently fall through to `epic_error`. Same shape as the `run_ci`-exhaustion halt added 2026-05-09.

## Design sketch

### State plumbing already in place

- [`MAX_EPIC_FIX_CYCLES = 2`](../src/intake/epic_graph.py) — already a constant, currently unused
- [`epic_fix_cycle: int`](../src/intake/epic_graph.py) — already an `EpicState` field, currently always 0

### What needs to change

1. **Routing.** In `route_after_epic_ci`, on `epic_test_passed=False`:
   - If `epic_fix_cycle < MAX_EPIC_FIX_CYCLES`: increment `epic_fix_cycle`, route back to `prepare_epic_reviews`.
   - If `epic_fix_cycle >= MAX_EPIC_FIX_CYCLES`: route to a new `epic_halt` node (analogous to story-level halt), which logs a clear operator message and ends the epic with `epic_status="paused"`.
2. **Cycle-aware prompts.** `prepare_epic_reviews_node` (or `analyze_reviews_node`) tags review files with the cycle number to keep artifacts from earlier cycles inspectable. Suggested filenames: `epic-{N}-cycle-{C}-review-bmad.md`, `epic-{N}-cycle-{C}-analysis.md`, etc.
3. **Early-stop heuristic.** Bring back the conditional that was just removed from `epic_fix_node`, but as a top-level early-exit: if `analyze_reviews_node` produces zero Cat-A and zero Cat-B findings on cycle ≥ 2, route directly to `epic_ci` (skip the architect/fix steps) and on CI pass go straight to `epic_git_commit`. The convergence signal is "the reviewers stopped finding things," not "CI passed" — those mean different things.
4. **Deferred-work integration.** Items that survive all cycles in the `defer` bucket are already appended to `_bmad-output/implementation-artifacts/deferred-work.md` by the sieve. No change needed.
5. **Cost cap.** Configurable via `factory.yaml` (`epic_review.max_cycles: int` and a per-epic wall-clock cap, e.g. `epic_review.max_minutes`).

### Termination conditions (in priority order)

1. **CI passed** → commit + advance to next epic.
2. **Cycle limit reached** → halt with operator message; deferred-work file has the leftover findings.
3. **No new findings this cycle** (cycle ≥ 2) → "converged," commit + advance even if CI passed first try this cycle.
4. **Wall-clock budget exhausted** → halt with operator message including elapsed time.

## Escape hatches required

- Operator halt at budget exhaustion (cycle limit OR wall-clock cap). Must surface to the dashboard as a halt, not a silent epic_error.
- Resume support: an operator who fixes the underlying issue manually and resumes should re-enter at the cycle they were on, not start over.
- Pause-aware: `is_pause_requested()` should be checked between cycles so Ctrl+C halts cleanly without burning another cycle's budget.

## Open questions

- **Should fix prompts include prior-cycle CI output?** The instinctive answer is "yes, focus on what failed last time" but this is exactly the context-bloat trap. Better answer is probably "no — let the reviewer surface failures fresh, the agent fixes what it sees."
- **Should reviewers see prior-cycle artifacts?** Probably yes, but as `Read`-on-demand, not pre-loaded. Reviewer can choose to consult them if useful.
- **What's the right `MAX_EPIC_FIX_CYCLES` default?** `2` is the current constant. Empirically I'd guess `2` is right — first cycle is the main pass, second is the convergence check. `3+` is probably wasted budget.
- **Cost gating per epic vs. per project?** A single epic going to 3 cycles is fine; an entire 10-epic project going to 3 cycles each is 30+ hours. Probably want a project-level wall-clock cap too.

## Decision criteria — when to actually build this

Build when **either** of these is true:

1. We have run logs from ≥ 5 distinct epics (across ≥ 2 projects) where the operator's manual triage on a failed `epic_ci` would have been "just resume, the next pass would have fixed it." That's the data signal that convergence happens often enough to be worth automating.
2. A target project has an epic with ≥ 15 stories where one-shot review is observably insufficient (e.g. multi-cycle manual triage is the norm).

Without one of those, this is speculative engineering.

## Related

- [analyze-reviews-sieve-plan.md](analyze-reviews-sieve-plan.md) — current one-shot review pipeline
- [epic-review-redesign.md](epic-review-redesign.md) — the redesign that produced today's pipeline
- [story-review-redesign-proposal.md](story-review-redesign-proposal.md) — story-level review (separate concern)
- [src/intake/epic_graph.py](../src/intake/epic_graph.py) — `MAX_EPIC_FIX_CYCLES` and `epic_fix_cycle` are already declared but unused; this proposal would wire them up.

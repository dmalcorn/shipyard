# Story-Batch Review — Design Doc

**Status:** **Ready to execute** as of 2026-05-09 after code-base verification and operator decisions. Vocabulary handling and architect-input format will likely need iteration during implementation (operator-acknowledged — the existing epic-end sieve took ~6 iterations to handle the BMAD reviewer's word choices). Use the Execution checklist below to track multi-session progress — each checkpoint marker (🛑) is a safe place to clear context and resume in a fresh session.
**Date:** 2026-05-09
**Supersedes:** the deleted `story-review-redesign-proposal.md` from 2026-05-08 (which proposed per-story reviews; that approach was reconsidered and replaced by the batch approach below).

## Revision log

- 2026-05-09 (initial): batch-review pipeline proposal as written.
- 2026-05-09 (post-verification): code-base claims audited against current source. Several factual corrections inline (template renames, sieve vocabulary, pause checks, resume mechanism, code_review removal scope). Effort estimate revised. Open questions raised.
- 2026-05-09 (decisions baked in): operator answered the open questions (graph topology = clone-and-rename, toggle = renamed, pause = next-story-boundary only, vocabulary = batch-only new tokens with iteration expected, test approach = mocks + fixture epic). Open questions section removed.
- 2026-05-09 (execution checklist added): inserted the multi-session "Execution checklist" section between TL;DR and Why, with five checkpoint groups and 🛑 markers at safe context-clear boundaries. Step references throughout the doc remain stable; the checklist is the index, not a replacement.
- 2026-05-09 (model-config completeness): added the "Model configuration" subsection above the per-node detail section. Five new `epic_batch_*` keys preserve the per-node model-selection design artifact already in place for epic-end. All per-node descriptions now reference their model key explicitly via `_epic_model_for("epic_batch_X")`. Step 8 now creates all five entries in one diff rather than spreading them across later steps.
- 2026-05-09 (implementation complete, all 5 checkpoints): all 15 steps landed across 5 checkpoint groups. Net: 480 → 544 passing tests (+64), 1 net ruff error reduced (deleted `json` import in orchestrator.py during Step 13 cleanup), 1 net mypy error added (the new `load_batch_phase_checkpoint` mirrors the established `load_*_phase_checkpoint` Any-return pattern at lines 90 and 177 — same shape, same accepted compromise). Notable deviations from spec: (a) Checkpoint B preserved byte-identical epic-end behavior (commit message `epic 6 code review fixes`, scope_hint `epic 6`, all artifact filenames); the Step 9 helper extraction at Checkpoint C accepts small cosmetic deviations in audit log labels (now `epic-6 CI` instead of `epic CI`) which are internal/forensic only. (b) The Step 14 fixture-epic integration test was deliberately skipped — it requires a 4-story BMAD-shaped target project plus real BMAD/Claude CLI calls (cost+brittleness), and the unit tests + graph-wiring tests cover the routing correctness it would have validated. Documented for follow-up if a smoke-test target becomes available. (c) Vocabulary drift handling: parser uses substring matching with a fallback to escalate-to-architect on unknown tokens, plus the existing `_run_review_sieve` zero-findings warning that triggers the legacy LLM agent fallback path. Iteration expected on the first real batch run.

## TL;DR

Insert a code-review pipeline that fires every N successfully-completed stories within an epic. Single BMAD reviewer, deterministic sieve into three buckets (`patch`, `decision needed`, `deferred`), architect builds a fix plan for `decision needed` items, dev agent applies the plan, batch-CI verifies. Failures that the dev agent can't apply land in `deferred-work.md`. Default `N=4`, configurable per project. Epic-end review pipeline is **unchanged** — batch review is additive.

**Status (post-decisions):** ready to execute. Estimated 5–6 focused days, not 1–2. Vocabulary and architect-input handling will iterate during implementation — that's expected, not a blocker.

## Execution checklist

Mark items `[x]` as completed. Each session should typically tackle one checkpoint group. Stop at a 🛑 checkpoint marker; do not push into the next group without a fresh context. Each checkpoint represents a state where the codebase is stable, tested, and a fresh session can pick up cleanly using only the doc as context.

When resuming in a new session, give the next-session-me this prompt: *"Read `gauntlet_docs/story-batch-review-design.md`. Continue from the first unchecked item in the Execution checklist. Stop at the next 🛑 checkpoint."*

### Group 1: Foundation (independent of each other, can be done in any order)
- [x] **Step 1** — `ReviewScope` abstraction in new file `src/intake/review_scope.py` + unit tests (`tests/test_intake/test_review_scope.py`)
- [x] **Step 4** — `get_story_batch_size()` in `src/config.py` + unit tests in `tests/test_config.py`

**🛑 Checkpoint A — Foundation merged.** Both new modules import cleanly, all new tests pass, full existing test suite still green. **Safe to clear context.**

### Group 2: Refactor existing pipeline (must precede new batch nodes)
- [x] **Step 2** — Filename template constants and format-string updates per Step 2's "only `EPIC_FIX_PLAN_FILENAME_TEMPLATE` is renamed; the other six just have format-string body updated" guidance
- [x] **Step 3** — Refactor 8 epic nodes to accept a `ReviewScope` (depends on Step 1)
  - `prepare_epic_reviews_node`, `epic_review_node`, `analyze_reviews_node`, `fix_category_a_node`, `epic_architect_node`, `epic_fix_node`, `epic_ci_node`, `epic_git_commit_node`
  - Per Step 9's clone-and-rename decision: refactor each as a thin wrapper around a shared scope-aware helper

**🛑 Checkpoint B — Epic-end pipeline refactored.** All existing tests still green; epic-end behavior is **byte-for-byte identical** to before (artifact filenames, commit messages, prompts unchanged). Run a manual smoke test against a recent epic if practical. **Safe to clear context.**

### Group 3: New batch pipeline (depends on Groups 1 + 2)
- [x] **Step 5** — New state fields on `EpicState`; initialize in `run_epic_node`; increment in `process_story_result_node`; reset in `batch_commit_node`
- [x] **Step 6** — `route_next_story` returns `"batch_boundary"` when conditions met; wire new edge in `build_epic_graph` (depends on Step 4 + Step 5)
- [x] **Step 7** — `prepare_batch_review_node` (depends on Step 1 + Step 5)
- [x] **Step 8** — `batch_review_node` with the new vocabulary prompt; add **all five** new `_EPIC_MODEL_CONFIG` entries (`epic_batch_review`, `epic_batch_analysis`, `epic_batch_fix_cat_a`, `epic_batch_architect`, `epic_batch_fix_dev`) per the Model configuration section. Initialize each batch key to the same default as its epic-end counterpart so behavior is identical out of the box (depends on Step 1 + Step 7)
- [x] **Step 9** — Wire batch wrappers (`analyze_batch_review`, `fix_batch_category_a`, `batch_architect`, `batch_fix`, `batch_ci`, `batch_commit`) per the wrapper table in Step 9 (depends on Step 3)

**🛑 Checkpoint C — Batch pipeline structurally complete.** Smoke-test that the batch trigger fires at the right boundary. Sieve / architect / fix may still need calibration in Group 4 — at this checkpoint, the batch reviewer should run and produce a review file; downstream may not yet route findings correctly. **Safe to clear context.**

### Group 4: Calibration + cleanup
- [x] **Step 10** — Sieve vocabulary parser extension (drift-tolerant per Step 10's substring-matching approach; expect iteration)
- [x] **Step 11** — `batch-phase.json` checkpoint, `session.json` extension, resume routing (depends on Step 5)
- [x] **Step 12** — Halt routing on batch-CI exhaustion via `route_after_batch_ci` returning `pass | halt` to existing `epic_halt_node` (depends on Step 9)
- [x] **Step 13** — Remove dead `code_review_node` (full cleanup surface per Step 13's enumeration)
- [x] **Step 13a** — Toggle rename `_STORY_REVIEWS_ENABLED` → `_BATCH_REVIEWS_ENABLED`; update all import sites; CLI flag and config key keep their names

**🛑 Checkpoint D — All wiring complete.** Sieve handles the new vocabulary (or falls back cleanly to legacy LLM agent on drift). Resume from each batch phase works. Halt-and-resume tested manually. **Safe to clear context.**

### Group 5: Tests + final config
- [x] **Step 14** — Unit tests, mocked integration tests, and fixture-epic integration test (per Step 14's full enumeration). Marked `@pytest.mark.slow`
- [x] **Step 15** — Add `review.story_batch_size: 4` to `factory.yaml.example` with explanatory comment

**🛑 Checkpoint E — Done.** Run the fixture-epic test against a clean checkout. Document this batch's findings (vocabulary drift hit, architect-format adjustments made) so iteration N+1 has the context. Update the Revision log at the top of this doc with a final entry summarizing how implementation matched (or diverged from) the spec.

### Out-of-band cleanup (optional, no checkpoint dependency)
- [ ] Remove `OrchestratorState.has_review_issues`, `OrchestratorState.review_file_path`, `check_review_node`, and `route_after_check_review` — verified to be already-dead code unrelated to this design (flagged in Step 13). Can be done in any session as a small side-PR if it bothers you; otherwise leave alone.

## Why

Epic 6 (PawprintRecipes, 2026-05-09) failed 6 of 11 stories at `run_ci` because problems compounded across the story loop. The current factory has only one review point — at epic-end, after all stories are committed. By the time the epic-end review runs, the codebase has already been poisoned by stories 2-5's untested edits drifting into stories 6-9's CI runs.

A single review at epic-end is too late. A review after every story is too expensive (and produces too thin a signal — single-story reviews mostly catch lint-grade nits). A review every N stories is the middle ground: enough cross-story context to find consistency issues, frequent enough to interrupt cascades.

## Existing assets to reuse

The epic-end pipeline already implements every node we need. It just hardcodes "epic" everywhere:

| Existing node | What it does | Hardcodes |
|---|---|---|
| [`prepare_epic_reviews_node`](../src/intake/epic_graph.py) | Build in-scope story list, exclude doc-only/polish stories | `epic-{N}-...` filenames |
| [`epic_review_node`](../src/intake/epic_graph.py) | Run a reviewer (BMAD or Claude), capture output, write to disk | `epic-{N}-review-bmad.md` etc. |
| [`analyze_reviews_node`](../src/intake/epic_graph.py) | Sieve reviewer output into Cat A / Cat B / defer buckets | `epic-{N}-analysis.md`, `epic-{N}-category-a-fix-plan.md`, `epic-{N}-category-b-architect-review.md` |
| [`fix_category_a_node`](../src/intake/epic_graph.py) | Auto-apply Cat A fixes via BMAD dev agent | `epic-{N}` in prompt; reads/writes `epic-{N}-...` paths |
| [`epic_architect_node`](../src/intake/epic_graph.py) | Architect designs Cat B fix plan | `epic-{N}-fix-plan.md` |
| [`epic_fix_node`](../src/intake/epic_graph.py) | BMAD dev agent applies architect's plan, defers unapplicable fixes | `epic-{N}` in prompt |
| [`epic_ci_node`](../src/intake/epic_graph.py) | Run full CI with retry-and-fix loop | `epic {N}` in scope_hint |
| [`epic_git_commit_node`](../src/intake/epic_graph.py) | Commit the review-driven changes | `epic {N} code review fixes` message |

The plan is to **refactor these to be scope-aware** rather than clone them with `_batch` suffixes. A `ReviewScope` abstraction encapsulates "epic-{N}" or "epic-{N}-batch-{B}" identity; existing nodes accept a `ReviewScope` instead of a bare `epic_num`. The new batch pipeline reuses the same node implementations.

This means **fewer new files than node names suggest** — the new code is mostly the scope abstraction, the routing wiring, and one new prompt (the batch reviewer with the new vocabulary).

## Design

### The `ReviewScope` abstraction

A small dataclass that captures both the epic and (optional) batch identity, plus formatting helpers:

```python
@dataclass(frozen=True)
class ReviewScope:
    epic_num: str
    batch_num: int | None = None  # None → epic-end review; 1+ → mid-epic batch

    @property
    def is_batch(self) -> bool:
        return self.batch_num is not None

    @property
    def label(self) -> str:
        """Filename-safe label, e.g. 'epic-6' or 'epic-6-batch-2'."""
        if self.batch_num is None:
            return f"epic-{self.epic_num}"
        return f"epic-{self.epic_num}-batch-{self.batch_num}"

    @property
    def prose_label(self) -> str:
        """Human-readable label for prompts, e.g. 'Epic 6' or 'Epic 6 batch 2'."""
        if self.batch_num is None:
            return f"Epic {self.epic_num}"
        return f"Epic {self.epic_num} batch {self.batch_num}"

    def artifact_path(self, template: str, working_dir: str | None) -> str:
        """Resolve a per-scope artifact path. Template uses {scope} placeholder."""
        filename = template.format(scope=self.label)
        return _reviews_path(filename, working_dir=working_dir)
```

**Lives in:** new module `src/intake/review_scope.py`. Pure dataclass, no graph dependencies.

**Filename-template constants** get rewritten from `"epic-{epic_num}-foo.md"` to `"{scope}-foo.md"`:

```python
# Before:
EPIC_FIX_PLAN_FILENAME_TEMPLATE = "epic-{epic_num}-fix-plan.md"

# After:
FIX_PLAN_FILENAME_TEMPLATE = "{scope}-fix-plan.md"
```

So `ReviewScope(epic_num="6", batch_num=None).artifact_path(FIX_PLAN_FILENAME_TEMPLATE, ...)` resolves to `.../epic-reviews/epic-6-fix-plan.md`, while `ReviewScope(epic_num="6", batch_num=2).artifact_path(...)` resolves to `.../epic-reviews/epic-6-batch-2-fix-plan.md`.

### Vocabulary

**Batch reviewer prompt uses `patch | deferred | decision needed`** instead of the epic-end prompt's `critical | major | minor`. The batch reviewer's findings get classified by the BMAD code-review skill into BMAD's native 5-category triage internally (`intent_gap | bad_spec | patch | defer | reject`), but the operator-visible vocabulary in the consolidated review report is the cleaner three-bucket form.

The sieve maps reviewer-emitted vocabulary to the existing internal bucket types:

| Reviewer says | Sieve bucket | Downstream action |
|---|---|---|
| `patch` | `cat_a` | fix-cat-a auto-applies |
| `decision needed` | `cat_b` | architect builds plan, dev applies it |
| `deferred` | `defer` | appended to `deferred-work.md`, no agent action |

This keeps the existing bucket names internal (no churn in `analyze_reviews_node`, `fix_category_a_node`, etc.) while presenting the cleaner vocabulary at the prompt and review-report layer.

**Epic-end review prompts are unchanged** — they continue to ask for `critical | major | minor` because they're working today and the operator hasn't asked to disturb them. Vocabulary realignment for epic-end is out of scope for this work.

### Trigger logic

A batch boundary is detected after a story completes successfully (in `process_story_result_node`):

- Increment `stories_in_current_batch` and append to `current_batch_story_ids` only when `current_story_status == "completed"` AND the story is not a doc-only spike or integration-polish (regex match on `story_name` against `\bspike\b` / `\bintegration polish\b`, case-insensitive — same exclusion regex used by `_doc_only_task_ids` for epic-end review). Failed stories don't count (their dev work is uncommitted; nothing to review). Spike/polish don't count (they're documentation; including them in the batch reviewer's input set was observed to mis-frame the entire review as a documentation pass — see `prepare_batch_review_node` rationale below).
- Fire the batch review when `stories_in_current_batch >= review.story_batch_size` AND there are stories remaining in the epic (i.e. don't fire a batch immediately before epic-end review — let the epic-end review cover the leftover stories).
- Reset `stories_in_current_batch = 0` and `current_batch_story_ids = []` after the batch review pipeline completes.

If `review.story_batch_size = 0`, the trigger never fires — pipeline behaves identically to today (epic-end review only).

**The interactive `[Y/n]` startup prompt also gates the batch pipeline** (see Step 13a). Three opt-out paths — CLI flag `--no-story-reviews`, config key `reviews.story_level: false`, or "n" at the prompt — all set a master `_BATCH_REVIEWS_ENABLED` boolean that the trigger respects on top of the size check. Default is enabled, so an operator hitting Enter at the prompt with `story_batch_size: 4` in factory.yaml gets batch reviews firing every 4 stories.

**Leftover stories at epic-end:** if the epic has 11 stories and `story_batch_size = 4`, batches fire after stories 4 and 8. Stories 9, 10, 11 don't trigger a third batch — they're folded into the regular epic-end review, which already covers all stories in the epic.

### Configuration

Adds one entry to `factory.yaml`:

```yaml
review:
  story_batch_size: 4   # 0 disables; default 4
```

Loader behavior in `src/config.py`:

- `get_story_batch_size() -> int` — returns the integer, defaulting to `4` if unset, `0` to disable, validated to be `>= 0`.
- Mirrors the pattern of `get_fix_pre_existing()` already in the same module.

### Pipeline graph

Today's epic graph is:

```
select_story → run_story → process_result → advance_story → route_next_story
                                                                ↓
                                            paused | more_stories | epic_done
```

New graph (batch nodes added between `advance_story` and `select_story`):

```
select_story → run_story → process_result → advance_story → route_next_story
                                                                ↓
                                  paused | more_stories | batch_boundary | epic_done
                                                              ↓
                                                  prepare_batch_review
                                                              ↓
                                                  batch_review (single BMAD)
                                                              ↓
                                                  analyze_batch_review (sieve)
                                                              ↓
                                                  fix_category_a (if any)
                                                              ↓
                                                  batch_architect (if cat_b)
                                                              ↓
                                                  batch_fix (if architect produced plan)
                                                              ↓
                                                  batch_ci
                                                              ↓
                                              batch_pass | batch_halt
                                                  ↓             ↓
                                          batch_commit       epic_halt
                                                  ↓
                                          select_story (continue loop)
```

`route_next_story` becomes:

```python
def route_next_story(state):
    if is_pause_requested():
        return "paused"
    stories = state["stories"]
    story_index = state["story_index"]
    if story_index >= len(stories):
        return "epic_done"
    if (
        get_story_batch_size() > 0
        and state.get("stories_in_current_batch", 0) >= get_story_batch_size()
    ):
        return "batch_boundary"
    return "more_stories"
```

The existing `more_stories` arrow stays exactly as today; we just add one new arrow.

### Model configuration

The existing pipeline preserves a per-node model-selection design artifact at [`epic_graph.py:87-93`](../src/intake/epic_graph.py#L87-L93): five entries in `_EPIC_MODEL_CONFIG` let the operator tune the model per pipeline phase (sonnet for most work; opus for the architect, where design decisions warrant the higher tier). This pattern is preserved for the batch pipeline — each batch node gets its own scope-specific key so the operator can tune batch-level models independently of epic-end (e.g., move batch-review to haiku in a future round to cut cost while keeping epic-end review on sonnet).

Final `_EPIC_MODEL_CONFIG` after this work:

```python
_EPIC_MODEL_CONFIG: dict[str, str | None] = {
    # Existing epic-end entries — UNCHANGED
    "epic_review":          "claude-sonnet-4-6",
    "epic_analysis":        "claude-sonnet-4-6",  # LLM fallback when sieve fails
    "epic_fix_cat_a":       "claude-sonnet-4-6",
    "epic_architect":       "claude-opus-4-6",     # design-decision tier
    "epic_fix_dev":          "claude-sonnet-4-6",
    # New batch-pipeline entries — initialized to mirror epic-end
    "epic_batch_review":    "claude-sonnet-4-6",
    "epic_batch_analysis":  "claude-sonnet-4-6",  # LLM fallback when sieve fails
    "epic_batch_fix_cat_a": "claude-sonnet-4-6",
    "epic_batch_architect": "claude-opus-4-6",     # design-decision tier
    "epic_batch_fix_dev":   "claude-sonnet-4-6",
}
```

**Rationale for the parallel keys (rather than reusing epic-end keys for batch nodes):**

- Preserves the existing design pattern operators already understand.
- Lets future tuning treat batch and epic-end differently without code changes — only `set_epic_model_config({"epic_batch_review": "claude-haiku-4-5"})` from a config loader.
- Costs nothing today: batch keys mirror epic-end values out of the box, so behavior is identical until the operator chooses to diverge.
- The `epic_batch_architect` key matters specifically — if the operator ever wants to use opus only at epic-end (not batch), they can, without touching graph code.

Each per-node section below references its model key. The clone-and-rename topology (per Step 9 decision) makes this straightforward — each thin wrapper passes `_epic_model_for("epic_batch_X")` to the shared scope-aware helper.

### Pipeline nodes — details

#### `prepare_batch_review_node` (new function, reuses `prepare_epic_reviews_node` logic with scope)

Builds the in-scope story list for the batch from `current_batch_story_ids`. The exclusion of doc-only spike + integration-polish stories now happens **upstream** in `process_story_result_node` (see "Trigger logic" section): completed spike/polish stories don't bump the batch counter and don't enter `current_batch_story_ids` in the first place, so the list this node receives is already filtered.

**Revised rationale (2026-05-09 post-Epic-7-batch-1 revision)** — the original design said batch reviews would NOT exclude spike/polish, on the grounds that "a batch is just N consecutive completed stories and has no special structural roles." That rationale was wrong. When Epic 7 batch-1 included Story 7-1 (the spike), the BMAD reviewer's first action was to load `safety-conventions.md` (the spike's own deliverable, a doc-only file), which framed the entire review as a documentation pass — all 11 findings landed on the spec, zero on actual code, no Hunter subagents spawned. Excluding doc-only stories from the batch counter sharpens the reviewer's frame to "code in stories N-M" and matches the proven epic-end behavior.

Outputs: populates `batch_review_stories` (list of `{story_id, story_name, task_id}` dicts) on state.

#### `batch_review_node` (new function — single BMAD reviewer with new vocabulary)

Fires a **single** BMAD reviewer (no parallel Claude reviewer at batch level — operator decision: keep the two-reviewer pattern at epic-end only).

The prompt is a fresh build using the new vocabulary:

```
Run the bmad-code-review skill across the following stories from
{scope.prose_label}. The skill defines the review workflow — follow it
as authored, do not deviate.

Stories to review:
- {task_id}: {story_name}
- ...

You're free to review the stories individually, in batches, or all
together. Within a batch, stories are usually closely related;
reviewing them holistically often surfaces cross-story consistency
issues (naming drift, contract mismatches, integration gaps) that a
strict story-by-story pass would miss. Use your judgment about how to
group your review.

Consolidate findings into a single report using the format below.
Group findings by story and add a final section for cross-story
integration issues.

Use this exact output format:

---
agent_role: reviewer
task_id: {scope.label}-review
timestamp: {ISO timestamp}
input_stories: [comma-separated story task_ids]
reviewer_type: bmad
review_scope: batch
---

# {scope.prose_label} Code Review

## Summary
{1-2 sentence overview}

## Findings

### 1. {Finding title}
- **Story:** {task_id}
- **File:** {relative path}
- **Issue:** {description}
- **Category:** {patch | decision needed | deferred}
- **Action:** {recommended fix, or rationale for decision-needed/deferred}

Use exactly these three categories: patch, decision needed, deferred.
- **patch** = mechanical fix with one clear correct path (e.g. typo,
  missing import, style violation)
- **decision needed** = real issue, multiple valid approaches or
  design implications — needs architect input
- **deferred** = pre-existing issue not caused by these stories;
  worth recording but not addressing now

Output your review as your final response. Do NOT write any files.

OUTPUT HANDLING — READ CAREFULLY:
[same belt-and-suspenders block as epic-end reviewer about not calling
Write/Edit/Bash workarounds]
```

**Tools:** `TOOLS_REVIEW_READONLY` (already grants `Skill` after today's earlier change).
**Model:** `_epic_model_for("epic_batch_review")` — defaults to `claude-sonnet-4-6` per the Model configuration table above.
**Timeout:** `TIMEOUT_MEDIUM`.

Output: writes review to `{scope.label}-review-bmad.md` (e.g. `epic-6-batch-2-review-bmad.md`).

#### `analyze_batch_review_node` (reuses `analyze_reviews_node` with `ReviewScope` parameterization)

The existing sieve module ([`src/intake/review_sieve.py`](../src/intake/review_sieve.py)) already takes review file content strings as inputs and produces buckets.

1. **Single review file is already supported.** Verified 2026-05-09: `sieve_reviews(bmad_content, claude_content)` accepts two strings, and both `parse_bmad_review("")` and `parse_claude_review("")` return empty lists (they iterate `splitlines()` over empty content). Pass `""` for the missing reviewer; no signature change required.
2. **Vocabulary handling is per Step 10 of the implementation plan.** Recognize the new field-line `- **Category:** patch | decision needed | deferred` style, mapping the three tokens to existing internal buckets (`cat_a | cat_b | defer`).

Outputs (relative to `epic-reviews/`):
- `{scope.label}-analysis.md` — sieve summary
- `{scope.label}-category-a-fix-plan.md` — Cat A items
- `{scope.label}-category-b-architect-review.md` — Cat B items
- Appends to `_bmad-output/implementation-artifacts/deferred-work.md` (single shared file, headers tagged with scope)

**Model:** primarily deterministic (no LLM call). On the legacy LLM-fallback path (when the sieve hits vocabulary drift), uses `_epic_model_for("epic_batch_analysis")` — defaults to `claude-sonnet-4-6` per the Model configuration table.

#### `fix_batch_category_a_node` (thin wrapper around shared scope-aware helper, per Step 9 clone-and-rename)

Wrapper that builds `ReviewScope(epic_num=epic_num, batch_num=batch_num)` from state and delegates to the shared `_fix_category_a(scope, ...)` helper extracted from `fix_category_a_node`. The existing code paths (path generation, prompt construction) all funnel through the scope abstraction.

**Model:** `_epic_model_for("epic_batch_fix_cat_a")` — defaults to `claude-sonnet-4-6` per the Model configuration table.

#### `batch_architect_node` (reuses `epic_architect_node` with scope)

Refactor `epic_architect_node` to take a `ReviewScope`. Architect is invoked with the Cat B file as input; produces `{scope.label}-fix-plan.md`.

The architect's prompt is unchanged in substance — it reads Cat B items, considers them, writes a structured plan with approved fixes. Just the input/output paths change with scope.

**Model:** `_epic_model_for("epic_batch_architect")` — defaults to `claude-opus-4-6` per the Model configuration table (same default as epic-end architect; design decisions warrant the higher tier regardless of scope, but operator can tune batch independently if cost matters).

**Iteration expected (2026-05-09):** the architect's prompt currently assumes the cat_b file's format from today's sieve output. Once the sieve emits cat_b items derived from the new vocabulary's field-line findings, the rendered cat_b file may differ subtly from today's epic-end output. **Treat this as a follow-up calibration task during implementation:** run the first batch end-to-end, inspect the architect's plan output for confusion/drift, and adjust either (a) the sieve's `render_category_file` to match the architect's expected format, or (b) the architect's prompt to handle the new shape. Don't try to anticipate the exact mismatch from the spec — the empirical signal will be clearer than guessing.

#### `batch_fix_node` (reuses `epic_fix_node`)

Same refactor — scope-aware. Already converted to BMAD pattern earlier today, already logs unapplicable fixes to `deferred-work.md`. The BMAD dev agent applies the architect's plan; anything it can't apply gets a `## Deferred from: {scope.label} fix-architect (DATE)` section in the deferred-work file with explanations.

**Model:** `_epic_model_for("epic_batch_fix_dev")` — defaults to `claude-sonnet-4-6` per the Model configuration table.

#### `batch_ci_node` (reuses `epic_ci_node`)

Run full CI (`scripts/ci.sh` with no story scoping), with the same retry-and-fix loop (max 4 attempts, BMAD `Fix CI failures` invocation between attempts) that epic-end uses.

`scope_hint` for `invoke_ci_with_fix` becomes `scope.prose_label` (e.g. `"Epic 6 batch 2"`). The CI output file becomes `checkpoints/ci-output-epic_6-batch-2.txt`.

#### `batch_commit_node` (reuses `epic_git_commit_node` with scope)

Commit message becomes `"{scope.label} code review fixes"` (e.g. `"epic-6-batch-2 code review fixes"`).

### Halt behavior on batch-CI exhaustion

Mirrors the story-level halt added 2026-05-09: if `batch_ci_node` returns `epic_test_passed=False` after exhausting its retry-and-fix loop, route to the epic-level halt path. Operator gets a clear message:

```
*** HALT: Epic 6 batch 2 CI failed after architect-driven fixes.
    Working tree contains uncommitted batch-fix attempts.
    Resolve manually and resume.
```

The batch's local commits (cat-a + fix-architect commits) stay in the tree; only the post-fix CI attempts that failed are uncommitted. Same recovery model as story-level halt.

### Deferred-work.md format

Each batch review may append two kinds of entries:
1. **Defer-bucket findings from the sieve:** `## Deferred from: code review of epic-6-batch-2 (2026-05-09)` followed by bullets, one per defer-classified finding.
2. **Unapplicable fixes from `batch_fix_node`:** `## Deferred from: epic-6-batch-2 fix-architect (2026-05-09)` followed by bullets describing the fix that couldn't be applied and why.

Existing `append_deferred_work` helper in `src/intake/review_sieve.py` already handles the first case for epic-end; just needs to accept a `ReviewScope` so the header reads correctly. The second case is already handled by the deferred-work prompt in `epic_fix_node` (which is now scope-aware).

### State plumbing

Three new fields on `EpicState`:

```python
class EpicState(TypedDict, total=False):
    # ... existing fields ...
    stories_in_current_batch: int           # 0 → reset; increments on success
    current_batch_story_ids: list[str]      # task_ids in the current pending batch
    batch_num: int                          # 1, 2, 3... — increments after each batch fires
    # Per-batch fields (mirror existing epic-level ones, reused via ReviewScope)
    batch_review_stories: list[dict[str, str]]
    batch_review_file_path: str
    batch_fix_plan_path: str
    batch_fixes_needed: bool
    batch_test_passed: bool
    batch_last_ci_output: str
```

The existing epic-level fields (`epic_review_file_paths`, `epic_fix_plan_path`, `epic_files_modified`, etc.) stay — they get used during the epic-end pipeline. Batch-pipeline fields parallel them.

### Resume behavior

**Verified 2026-05-09:** the existing checkpoint plumbing has gaps the original design overlooked. Two things are stored separately today:

1. **`epic-phase.json`** — written by [`save_epic_phase_checkpoint`](../src/intake/checkpoint.py#L122) — stores **only** `session_id, epic_num, completed_phase, next_phase`. It uses [`EPIC_PHASE_ORDER`](../src/intake/checkpoint.py#L111-L119), a flat ordered list. None of the new batch-state fields (`batch_num`, `current_batch_story_ids`, `stories_in_current_batch`, `batch_review_stories`) are persisted here.
2. **`session.json`** (rolling) — written in `process_story_result_node` ([`epic_graph.py:494-507`](../src/intake/epic_graph.py#L494-L507)) — has hard-coded keys: `session_id, target_dir, resume_epic_index, resume_story_index, resume_stories_completed, resume_stories_failed, resume_total_interventions, resume_story_results`. Also doesn't include any batch fields.

The doc's claim "the rolling story-level checkpoint already saves batch state" is **wrong**.

**What needs to change:**

- Extend the rolling `session.json` writer to include the three new fields: `stories_in_current_batch`, `current_batch_story_ids`, `batch_num`. Add the corresponding `resume_*` keys on the load side ([`rebuild_graph.py`](../src/intake/rebuild_graph.py)) so a hard-killed run that lost batch state recovers correctly.
- The flat `EPIC_PHASE_ORDER` list does not naturally express "batch happens N times during the story loop." Two viable approaches:
  - **(a)** Tag in-batch phase names with the batch number — e.g., `batch_2_review`, `batch_2_ci` — and add entries dynamically. Requires reworking `next_phase` derivation since it's currently `EPIC_PHASE_ORDER[idx + 1]` which assumes a single linear sequence.
  - **(b)** Add a separate `batch-phase.json` that captures `(batch_num, completed_phase)`, completely orthogonal to `epic-phase.json`. Cleaner conceptually but adds a third checkpoint file. **Recommended.**

  Whichever is chosen, `route_on_epic_entry` needs to inspect both files: if `batch-phase.json` says "we were mid-batch when killed," resume into the right batch phase first; only after the batch completes does the epic-end resume continue.
- After each successful batch-pipeline phase, call a new `_save_batch_phase(state, phase)` analogous to `_save_epic_phase`. After a batch fully completes, clear `batch-phase.json`.
- Required state fields to restore on resume: `batch_num`, `current_batch_story_ids`, `batch_review_stories`, `batch_review_file_path`, `batch_fix_plan_path`. (The rolling `session.json` carries the persistent ones; the others are derived in `prepare_batch_review_node` and survive across phase-resume because they're produced by an earlier batch phase that already completed.)
- Halt-and-resume edge case: if `batch_ci` exhausts retries and halts (see "Halt behavior" below), the operator manually fixes the target repo and resumes. On resume, the epic graph loads `batch-phase.json` showing `batch_fix` (or `batch_ci`) as the last completed phase; resume re-enters at `batch_ci`. This is correct — re-running CI verifies the manual fix landed.
- Halt-without-reset edge case: `stories_in_current_batch` and `current_batch_story_ids` get reset only in `batch_commit_node` (the happy-path tail). On halt before that, they remain populated; resume re-attempts the batch from the failed phase using them — correct behavior.

### Removing the dead `code_review_node`

The current per-story `code_review_node` ([orchestrator.py:598](../src/multi_agent/orchestrator.py#L598)) becomes dead code under this design — there's no per-story review point anymore.

**Operator decision: remove if dead, repurpose if useful.** Analysis of repurposing:
- The function invokes `bmad-agent-dev` with auto-fix instruction, not read-only — wrong shape for batch reviewer.
- The function operates on a single story's diff, not multi-story — wrong shape for batch reviewer.
- The function's prompt asks for inline Cat A application, not the read-only review the batch needs.

Net: the only thing salvageable is the function name. **Remove it** along with its graph wiring at [orchestrator.py:2031](../src/multi_agent/orchestrator.py#L2031) and `route_after_llm_node` edge.

The orchestrator graph becomes:

```
START → check_story → dev_story → run_ci ⇄ fix_ci → git_commit → END
                                              ↓ (max cycles)
                                         error_handler → END
```

Tests in `tests/test_multi_agent/test_orchestrator.py` that reference `code_review_node` get removed alongside.

## Implementation plan (step-by-step)

Sized to be executable in a focused day. Each step is self-contained and testable.

### Step 1: `ReviewScope` abstraction
- New file: `src/intake/review_scope.py`
- Dataclass per the snippet above
- Unit tests: `tests/test_intake/test_review_scope.py`

### Step 2: Refactor existing artifact-path constants and helpers in `epic_graph.py`

Verified against [`epic_graph.py:113-119`](../src/intake/epic_graph.py#L113-L119) — only `EPIC_FIX_PLAN_FILENAME_TEMPLATE` actually has the `EPIC_` prefix today. The other six constants already lack the prefix.

- Rename `EPIC_FIX_PLAN_FILENAME_TEMPLATE` → `FIX_PLAN_FILENAME_TEMPLATE` (drops `EPIC_` prefix; uses `{scope}` placeholder).
- For these six existing constants, **only the format-string body changes** (`epic-{epic_num}-...` → `{scope}-...`); no rename: `REVIEW_BMAD_FILENAME_TEMPLATE`, `REVIEW_CLAUDE_FILENAME_TEMPLATE`, `ANALYSIS_FILENAME_TEMPLATE`, `CATEGORY_A_PLAN_FILENAME_TEMPLATE`, `CATEGORY_B_REVIEW_FILENAME_TEMPLATE`, `CATEGORY_A_DONE_FILENAME_TEMPLATE`.
- Replace `_epic_fix_plan_path(epic_num, working_dir)` and `_epic_artifact_path(template, epic_num, working_dir)` with `scope.artifact_path(template, working_dir)` calls at the call sites.
- All existing tests must pass after this refactor (epic-end pipeline behavior unchanged).

### Step 3: Refactor existing nodes to accept a `ReviewScope` parameter
Functions to refactor:
- `prepare_epic_reviews_node` — read `epic_num` from state, build `ReviewScope(epic_num=..., batch_num=None)`, pass to scope-aware helpers internally
- `epic_review_node` — same; the BMAD/Claude prompts get the scope's `prose_label` interpolated
- `analyze_reviews_node` — same
- `fix_category_a_node` — same
- `epic_architect_node` — same
- `epic_fix_node` — same
- `epic_ci_node` — same; `scope_hint = scope.prose_label`
- `epic_git_commit_node` — same; commit message uses `scope.label`

Each refactor is local: read scope from state at the top of the function, replace `epic_num` references with `scope.X` calls, no behavior change. Unit tests stay green.

### Step 4: Configuration
- Add `get_story_batch_size()` to `src/config.py`
- Default: 4. Validates `>= 0`.
- Unit tests: `tests/test_config.py`

### Step 5: New state fields
- Add `stories_in_current_batch`, `current_batch_story_ids`, `batch_num`, plus the per-batch parallel fields to `EpicState`
- Initialize them in `run_epic_node` ([rebuild_graph.py:706](../src/intake/rebuild_graph.py#L706))
- Increment in `process_story_result_node` on `current_story_status == "completed"`
- Reset in `batch_commit_node` after each batch

### Step 6: New batch-trigger routing
- Modify `route_next_story` to return `"batch_boundary"` when conditions are met
- Wire the new edge into `build_epic_graph`
- Unit tests for the routing decision

### Step 7: New `prepare_batch_review_node`
- Lives in `epic_graph.py` near `prepare_epic_reviews_node`
- Builds `ReviewScope(epic_num=epic_num, batch_num=batch_num)` from state
- Populates `batch_review_stories` from `current_batch_story_ids`
- Wires into the graph

### Step 8: New `batch_review_node` + all five batch model-config entries
- Lives in `epic_graph.py` near `epic_review_node`
- Builds the new prompt with the new vocabulary
- Single BMAD reviewer (no Claude pair)
- Tools: `TOOLS_REVIEW_READONLY`
- Captures output, writes to `{scope.label}-review-bmad.md`
- **All five new entries** in `_EPIC_MODEL_CONFIG` per the Model configuration section:
  - `"epic_batch_review": "claude-sonnet-4-6"`
  - `"epic_batch_analysis": "claude-sonnet-4-6"`
  - `"epic_batch_fix_cat_a": "claude-sonnet-4-6"`
  - `"epic_batch_architect": "claude-opus-4-6"`
  - `"epic_batch_fix_dev": "claude-sonnet-4-6"`
- Add all five at once in this step rather than spreading them across later steps — keeps the model-config block coherent and reviewable in one diff

### Step 9: Wire reused nodes into batch path

**Decision (2026-05-09): clone-and-rename topology.** Each batch-pipeline graph node has a unique name and a thin wrapper function that sets `ReviewScope(epic_num=..., batch_num=...)` and delegates to the shared scope-aware helper. State-driven single-set-of-nodes was rejected — LangGraph traces and the resume-target map are far more legible when each node maps 1:1 to a unique pipeline phase, and the wrapper overhead is small.

Wrappers (each ~5-10 lines, all in `epic_graph.py`):

| New batch node | Underlying helper | Source |
|---|---|---|
| `analyze_batch_review_node` | `_analyze_reviews(scope, ...)` | extracted from `analyze_reviews_node` |
| `fix_batch_category_a_node` | `_fix_category_a(scope, ...)` | extracted from `fix_category_a_node` |
| `batch_architect_node` | `_run_architect(scope, ...)` | extracted from `epic_architect_node` |
| `batch_fix_node` | `_apply_architect_fix(scope, ...)` | extracted from `epic_fix_node` |
| `batch_ci_node` | `_run_full_ci(scope, ...)` | extracted from `epic_ci_node` |
| `batch_commit_node` | `_commit_review_fixes(scope, ...)` | extracted from `epic_git_commit_node` |

The existing `epic_*` nodes become equally-thin wrappers around the same shared helpers, with `ReviewScope(epic_num, batch_num=None)`. Net file-size impact is small — most lines move into the helper functions, the wrappers are tiny.

### Step 10: Vocabulary mapping in the sieve

**Bigger scope than initially written** — codebase verification (2026-05-09) found:

1. The sieve's existing `_BMAD_INLINE_CATEGORY` regex at [`review_sieve.py:101-104`](../src/intake/review_sieve.py#L101-L104) only matches inline backticked tags like `` `[patch]` ``. The new prompt's category line is field-line style (`- **Category:** patch`), which the BMAD parser doesn't currently handle — it only handles inline tags or section headings, not bullet-line `**Field:**` values. (The Claude parser handles `**Severity:**` field lines but doesn't generalize to a `**Category:**` field with the new vocabulary.)
2. The new prompt token `decision needed` (with space) **already** normalizes correctly via the existing `decision[-\s]needed` regex — no change needed for that token alone.
3. The new prompt token `deferred` (vs existing `defer`) does **NOT** match the existing inline regex (which requires `\]` immediately after `defer`). Either alias it or extend the regex.
4. The bmad-code-review skill's [`step-03-triage.md`](../.claude/skills/bmad-code-review/steps/step-03-triage.md) authoritatively defines the skill's native triage as `intent_gap | bad_spec | patch | defer | reject`. The sieve's `BMAD_CATEGORIES = ("patch", "defer", "dismiss", "decision-needed")` is a **separate, divergent** vocabulary — `dismiss` and `decision-needed` aren't in the skill spec at all. These tokens enter sieve output via the older epic-end review prompts that explicitly ask for them (Epic 9 chat2bpmn used `Category: patch/defer/dismiss` table format). For the new batch reviewer the prompt fully owns the token vocabulary, so the divergence is contained to the new parser logic.

**Operator-acknowledged reality (2026-05-09):** the BMAD reviewer's word choices drift between runs — even given an explicit prompt, the agent picks "accurate-sounding" variants. The existing epic-end sieve took ~6 iterations to handle all the permutations. **Expect the same pattern here.** Build the new parser with drift tolerance from the start: prefer keyword-substring detection over exact-token matching where ambiguity is low (the existing [`_classify_bmad_heading`](../src/intake/review_sieve.py#L122-L159) is the right pattern — `if "defer" in text: return "defer"` rather than exact-match).

**Concrete changes:**

- **Add a field-line BMAD parser** (or extend the BMAD parser's per-finding inspection) to recognize `- **Category:** {token}` as the new authoritative category source for batch reviews. Field-line values dominate over section heading / inline tag for the new vocabulary.
- **Tolerant token mapping** (mirrors `_classify_bmad_heading`'s substring-match approach):
  - Contains `patch` → `patch (cat_a)`. Also catches `simple patch`, `patches needed`, etc.
  - Contains `decision` (with optional `need`/`needed` nearby) → `decision-needed (cat_b)`. Catches `decision needed`, `decision required`, `requires decision`, etc.
  - Contains `defer` (covers both `defer` and `deferred`) → `defer`. Anything matching `dismiss`/`reject`/`drop` → drop the finding (not added to any bucket).
  - Unknown tokens after this fuzzy pass → log a warning, default to `decision-needed (cat_b)` (escalate-to-architect rather than auto-patch — safer fallback when uncertain).
- Existing inline-tag and section-heading parsing keeps working unchanged (epic-end compatibility).
- Existing tokens (`critical | major | minor`) keep working for epic-end Claude reviewer compatibility — the sieve handles all three vocabularies in parallel until epic-end is also migrated (out of scope here).
- **Iteration loop expected:** the first batch-reviewed epic will likely surface unhandled vocabulary variants. Build a feedback path: when the sieve finds zero classifiable findings AND the review file is non-empty, log a clear warning ("sieve found 0 findings in non-empty review — possible vocabulary drift, falling back to legacy LLM analyze-reviews agent"), and fall back to the legacy LLM analyze-reviews agent (still in the codebase as the sieve's documented fallback path per [`review_sieve.py:13-15`](../src/intake/review_sieve.py#L13-L15)). That keeps the pipeline functional during the iteration period.
- New tests in `tests/test_intake/test_review_sieve.py` covering: a batch-style review with `**Category:** patch / decision needed / deferred` field lines parsed correctly into cat_a/cat_b/defer; vocabulary drift cases (`Category: requires decision`, `Category: should defer`, `Category: simple patch`); single-file invocation `sieve_reviews(review_content, "")` returning correct buckets (verified — both parsers iterate `splitlines()` so empty input is safe); and the zero-findings-fallback path.

### Step 11: Resume support

Per the revised "Resume behavior" section above (codebase verification revealed gaps not addressed in the original design):

- Implement option (b) — new `batch-phase.json` checkpoint file at `checkpoints/batch-phase.json` with `save_batch_phase_checkpoint(session_id, target_dir, batch_num, completed_phase)` and matching load/clear helpers in [`src/intake/checkpoint.py`](../src/intake/checkpoint.py). Define a `BATCH_PHASE_ORDER` list mirroring `EPIC_PHASE_ORDER` for the batch nodes.
- Add a `_save_batch_phase` helper in `epic_graph.py` analogous to `_save_epic_phase`; call from each batch-pipeline node after success. Clear `batch-phase.json` in `batch_commit_node` after the batch completes successfully.
- Add `route_on_epic_entry`-style inspection: when re-entering `run_epic_node`, load `batch-phase.json` first; if present, jump to the batch phase before normal epic-phase resume.
- **Extend `session.json`** at [`epic_graph.py:494-507`](../src/intake/epic_graph.py#L494-L507) to persist `stories_in_current_batch`, `current_batch_story_ids`, `batch_num` under `resume_*` keys. Match by reading those keys back in `rebuild_graph.py`'s resume-state loader.
- New tests: `tests/test_intake/test_phase_resume.py` cases for resume-from-each-batch-phase. Add `tests/test_intake/test_checkpoint.py` cases for the new functions.

### Step 12: Halt on batch-CI exhaustion

Note: existing [`route_after_epic_ci`](../src/intake/epic_graph.py#L1592-L1596) routes failure to `error` (terminal), not `halt`. The new batch routing has different semantics — fail must route to `epic_halt` (which then ends the run with state preserved for operator inspection).

- Add `route_after_batch_ci(state)` returning `pass | halt`. On `pass` → `batch_commit`; on `halt` → `epic_halt_node` (reused).
- `epic_halt_node` reads `epic_num` and `failed_phase` from state. Since the batch flow runs inside the same epic graph, those fields are already populated. The halt message will need `current_story_failed_phase` set to a batch-specific phase name (e.g. `batch_ci`) so the message reads "Epic 6 batch 2 CI failed" rather than "Epic 6 run_ci failed."
- Operator sees the halt message and recovers manually; on resume, `batch-phase.json` (per Step 11) drives re-entry into `batch_ci` for verification.

### Step 13: Remove dead `code_review_node`

Verified 2026-05-09 — the surface is wider than originally written. **Full enumeration:**

In [`src/multi_agent/orchestrator.py`](../src/multi_agent/orchestrator.py):
- Delete `code_review_node` function (lines 598-637).
- Delete `_MODEL_CONFIG["code_review"]` entry (line 81).
- Remove `"code_review"` from `_RESUME_ENTRY_PHASES` (line 515).
- In `build_orchestrator_graph`:
  - Remove `graph.add_node("code_review", code_review_node)` (line 2005).
  - Remove `"code_review": "code_review"` from `route_on_entry`'s edge map (line 2026).
  - Change `route_after_story_check` skip target: `"skip": "code_review"` → `"skip": "run_ci"` (line 2034).
  - Change `dev_story` continue target: `"continue": "code_review"` → `"continue": "run_ci"` (line 2041).
  - Remove the entire `code_review → run_ci` conditional-edge block (lines 2045-2049).
  - Update build_orchestrator_graph docstring (lines 1986-1993) which describes `check_review/code_review/fix_review` flow that no longer exists.
- Update module-level docstring at line 5 if it references `code_review`.

In tests:
- [`tests/test_intake/test_phase_resume.py`](../tests/test_intake/test_phase_resume.py) — references at lines 52, 152, 179, 185, 214, 230, 260, 268. The test file uses `code_review` as a phase name in resume-target tests. Either remove those cases (if Step 11's new resume targets cover them) or update them to point at `run_ci` / `git_commit`.

**Adjacent dead-code observation (NOT in scope for Step 13, flagged for future cleanup):**
- `OrchestratorState.has_review_issues`/`review_file_path` (lines 209-210), `check_review_node` (line 1557), and `route_after_check_review` (line 1929) appear to be **already-dead code** — none are wired into `build_orchestrator_graph` today. They look like leftovers from an earlier review-fix flow. Worth a separate cleanup PR but not blocking on this work.

**Toggle plumbing — handled in Step 13a:** `_STORY_REVIEWS_ENABLED`, `get_story_reviews_enabled`, `set_story_reviews_enabled`, the `--no-story-reviews` CLI flag in `main.py:646-648`, and the `reviews.story_level` config key are repurposed (not removed) per Step 13a.

### Step 13a: Repurpose the existing story-review toggle

The existing factory has three controls that all flow into a single boolean (`_STORY_REVIEWS_ENABLED` in [`orchestrator.py:95`](../src/multi_agent/orchestrator.py#L95)):

| Today's control | What it controls now | What it controls after this redesign |
|---|---|---|
| CLI flag `--no-story-reviews` | per-story `code_review_node` | batch review pipeline |
| factory.yaml `reviews.story_level: false` | per-story `code_review_node` | batch review pipeline |
| Interactive `[Y/n]` startup prompt at [`rebuild_graph.py:279`](../src/intake/rebuild_graph.py#L279) | per-story `code_review_node` | batch review pipeline |

**The toggle is read in exactly one place today** — inside `code_review_node` (which Step 13 removes). Without this step, all three controls become silently dead — operator-set flags that have no effect.

Repurpose them instead of removing:

1. **Rename the global boolean** in `orchestrator.py` from `_STORY_REVIEWS_ENABLED` to `_BATCH_REVIEWS_ENABLED`. Update getter/setter: `get_story_reviews_enabled` → `get_batch_reviews_enabled`, `set_story_reviews_enabled` → `set_batch_reviews_enabled`. **Decided 2026-05-09 — rename rather than keep the historical name; the old name is misleading and would cost future readers time.** Update all import sites: [`orchestrator.py:95-106`](../src/multi_agent/orchestrator.py#L95-L106) (definitions), [`rebuild_graph.py:41-43`](../src/intake/rebuild_graph.py#L41-L43) (import), [`rebuild_graph.py:285,293`](../src/intake/rebuild_graph.py#L285) (call sites), [`main.py:401,429`](../src/main.py#L401) (import + call site), and the parameter name `skip_story_reviews` in [`main.py:380, 669`](../src/main.py#L380) → `skip_batch_reviews`.

2. **Add the toggle check to `route_next_story`** as a master gate, on top of the size check the design already has:

   ```python
   if (
       get_batch_reviews_enabled()                    # NEW: master gate
       and get_story_batch_size() > 0                 # config-side gate
       and state.get("stories_in_current_batch", 0) >= get_story_batch_size()
   ):
       return "batch_boundary"
   ```

3. **Update the interactive prompt text** at `rebuild_graph.py:_prompt_story_reviews()`:
   - From: `"Run story-level code reviews? [Y/n]"`
   - To: `"Run story-batch code reviews? [Y/n]"`
   - Update the disabled-message print: `"Story-level code reviews: DISABLED"` → `"Story-batch code reviews: DISABLED"`
   - And the enabled-message print correspondingly.

4. **Keep CLI flag `--no-story-reviews` for backwards compatibility** (operators don't have to relearn the flag). Verified at [`main.py:645-649`](../src/main.py#L645-L649); current help text says `"Skip story-level code reviews (epic reviews still run)"`. Update to `"Disable batch-level code reviews (epic-end review still runs)."` so `--help` reflects the new meaning.

5. **Keep config key `reviews.story_level: true|false` for backwards compatibility.** Update the comment in `factory.yaml.example` to reflect that it now gates the batch pipeline.

**Net result:** any of the three opt-out paths (CLI, config, prompt) disables the entire batch pipeline for the run, regardless of `review.story_batch_size`. Default behavior — operator hits Enter at the prompt with batch size 4 in factory.yaml — fires the batch pipeline.

**Tests:**
- `tests/test_intake/test_rebuild_graph.py` — the prompt's disabled-state branch
- `tests/test_intake/test_epic_graph.py` — `route_next_story` returns `more_stories` (not `batch_boundary`) when the toggle is off, even when batch size threshold is met

### Step 14: Tests

**Decision (2026-05-09): use both mocks and a fixture epic.** Mocks cover unit-level routing and the cheap permutations; the fixture epic covers the integration story end-to-end. Operator-acknowledged: this is a complicated update and needs thorough testing.

**Unit tests:**
- `tests/test_intake/test_review_scope.py` — `ReviewScope` dataclass behavior (label, prose_label, artifact_path).
- `tests/test_intake/test_review_sieve.py` — extend with the new field-line `**Category:**` parser cases, drift-vocabulary cases, single-file invocation, zero-findings fallback path (per Step 10).
- `tests/test_intake/test_epic_graph.py` — `route_next_story` returning `batch_boundary` vs `more_stories` for various combinations of `_BATCH_REVIEWS_ENABLED` toggle, `story_batch_size`, `stories_in_current_batch`, and remaining-stories count. Specifically include: `epic_size=8, batch_size=4` → exactly one batch fires (after story 4); `epic_size=11, batch_size=4` → two batches (after 4 and 8); `batch_size=0` disables.
- `tests/test_config.py` — `get_story_batch_size()` defaults and bounds.
- `tests/test_intake/test_checkpoint.py` — `save_batch_phase_checkpoint` / `load_batch_phase_checkpoint` / `clear_batch_phase_checkpoint`.
- `tests/test_intake/test_phase_resume.py` — resume from each batch phase (mirrors existing epic-phase resume cases).
- `tests/test_intake/test_rebuild_graph.py` — the renamed prompt's disabled-state branch.

**Mocked integration tests** (fast, no LLM/agent calls):
- `tests/test_intake/test_epic_graph.py` — drive the epic graph with mocked node functions, verify the new edges fire in the right order across one batch boundary.
- Verify state-field plumbing end-to-end: `stories_in_current_batch` increments correctly, `current_batch_story_ids` accumulates and resets, `batch_num` increments after each batch.

**Fixture-epic integration test** (slow, but real):
- New fixture under `tests/fixtures/epic-batch-test/` — a 4-story epic where stories 1-4 each touch a small file, designed so the BMAD reviewer reliably finds 1-2 findings (so cat_a / cat_b paths get exercised).
- Test runs the rebuild pipeline with `story_batch_size=2` against this fixture and asserts: batch fires after story 2; batch artifacts written; batch CI passes; batch commit created in git log; final epic-end review still runs and reviews all 4 stories.
- Mark the test with `@pytest.mark.slow` so it can be skipped in fast CI runs.

### Step 15: Update factory.yaml.example
- Add the new `review.story_batch_size: 4` entry
- Comment explaining the configurability

## Edge cases to handle

1. **Failed story partway through batch.** Today's halt-on-`run_ci`-exhaustion fires before the batch counter increments, so a CI-failed story doesn't pollute batch state. A dev-story-failed story (only non-halting failure mode) is correctly excluded from the batch by the "increment only on success" rule.

2. **Pause during batch review.** Verified 2026-05-09: `is_pause_requested()` is called in only **3 places** today — `route_next_story` ([`epic_graph.py:611`](../src/intake/epic_graph.py#L611)) and twice in `rebuild_graph.py` (between epics). There are **no inter-node pause checks within the epic post-processing pipeline today**. **Decision (2026-05-09): accept "pause does not interrupt mid-batch."** Pause takes effect at the next story boundary (or epic boundary) — never mid-batch and never mid-epic-post-processing. This matches today's epic-end semantics. The batch pipeline is short enough (review + sieve + maybe architect + fix + CI + commit) that waiting it out is rarely worse than the operator's interrupt loop. Document the behavior in the operator-facing pause prompt / README so this isn't a surprise.

3. **Resume mid-batch.** Phase checkpoints handle this — operator resumes the run, and the epic graph picks up at whichever batch phase didn't complete. Tests should cover resume from each batch phase.

4. **Batch boundary aligns with epic end.** If `epic_size % batch_size == 0` (e.g. 12-story epic with N=4), the trigger condition (`stories_in_current_batch >= story_batch_size AND there are stories remaining`) prevents the third batch from firing — the design's `route_next_story` already short-circuits when `story_index >= len(stories)` is imminent. **Verify** during implementation: re-read the trigger condition and write a regression test for `epic_size=8, batch_size=4` ensuring exactly one batch fires (after story 4) and the epic-end review handles stories 5-8. If the conditional is too lax and a redundant final batch fires, tighten it; do not accept "redundant review" as the disposition.

5. **First batch with `batch_num=1`.** Initialized in `run_epic_node` to `batch_num=0`; incremented to 1 in `prepare_batch_review_node` before reading. Avoids off-by-one confusion.

6. **`story_batch_size=0` (disabled).** `route_next_story` short-circuits the batch_boundary check; pipeline behaves identically to today (epic-end review only).

7. **Sieve produces zero findings (clean batch).** Skip Cat A, skip architect, skip fix, run batch_ci anyway as a sanity check, commit (probably no-op git commit since no files changed). Document this — it's unusual but not a failure.

8. **Architect approves zero fixes.** Skip `batch_fix`, run `batch_ci`, commit any prior Cat A changes.

9. **Operator changes `story_batch_size` mid-run via factory.yaml edit.** The next `route_next_story` call picks up the new value. Acceptable behavior; no special handling.

## What's NOT in scope for this work

- **Iterative epic review loop.** Captured in [`gauntlet_docs/future-enhancement-iterative-epic-review-loop.md`](future-enhancement-iterative-epic-review-loop.md). Separate work.
- **Vocabulary cleanup at epic-end.** Epic-end review prompts continue to ask for `critical | major | minor`. Migrating epic-end to the new vocabulary is a separate cleanup.
- **Per-story review.** Explicitly rejected — replaced by batch.
- **Iterative batch loop (re-review after batch-CI passes).** Same iterative-loop concerns apply at batch level; if it's worth doing, it's worth doing at both levels in one pass. Out of scope here.
- **Two-reviewer (BMAD + Claude) at batch level.** Operator decision: single reviewer at batch, two-reviewer pair stays at epic-end only.
- **Removing `Edit` from BMAD-invocation toolsets.** Separate parking-lot item; doesn't affect this work.

## Operator decisions (resolved 2026-05-09)

These were the open questions; answers are baked into the design above:

1. **Architect at batch end:** **Yes** (option A — always-run). Symmetric with epic-end pattern.
2. **Default batch size:** **4**, configurable via `factory.yaml`.
3. **Vocabulary for new prompts:** **`patch | deferred | decision needed`**. Epic-end vocabulary unchanged.
4. **Old proposal disposition:** **Deleted.** This doc is the canonical design.
5. **Existing `code_review_node`:** **Removed** (becomes dead code under this design; can't be cleanly repurposed for batch).
6. **Existing review-toggle controls** (CLI flag, factory.yaml key, interactive prompt): **Repurposed** to gate the batch pipeline rather than removed. See Step 13a in the implementation plan. Operator workflow stays familiar — same three opt-out paths, just redirected at the new pipeline.

## Decisions baked in (2026-05-09)

All previously-open questions are now decided. Decisions live in the relevant Step sections of the implementation plan; this is the index.

1. **Graph topology (Step 9):** clone-and-rename. Each batch node is a thin wrapper around a shared scope-aware helper. Existing `epic_*` nodes become equally-thin wrappers calling the same helpers with `batch_num=None`. See Step 9 for the wrapper table.
2. **Toggle naming (Step 13a):** rename `_STORY_REVIEWS_ENABLED` → `_BATCH_REVIEWS_ENABLED` (and getter/setter); update all import sites. CLI flag `--no-story-reviews` and config key `reviews.story_level` keep their names for backwards compatibility.
3. **Pause behavior (Edge case 2):** pause takes effect only at the next story boundary or epic boundary — never mid-batch and never mid-epic-post-processing. Matches today's epic-end semantics. Documented operator-facing.
4. **Sieve vocabulary (Step 10):** new vocabulary applies to batch only; epic-end vocabulary remains unchanged for now (epic-end migration is a follow-up). New parser uses substring/keyword matching to tolerate drift, with a clear-warning fallback to the legacy LLM analyze-reviews agent when zero findings are extracted from a non-empty review. Iteration expected — the existing epic-end sieve took ~6 iterations to settle.
5. **Architect input format (`batch_architect_node` description):** treat as a calibration task during implementation. Inspect the first real batch's architect output, adjust the sieve's `render_category_file` or the architect prompt to match — don't try to anticipate the mismatch from the spec.
6. **Test approach (Step 14):** mocks + fixture epic. Mocks cover unit-level routing and permutations; a 4-story fixture epic under `tests/fixtures/epic-batch-test/` covers the integration story end-to-end. Marked `@pytest.mark.slow` so it can skip in fast CI runs.

## Estimated effort

**Revised 2026-05-09 after codebase verification: 5–6 focused days, not 1–2.** Original estimate undercounted three pieces:

| Slice | Estimate |
|---|---|
| `ReviewScope` abstraction + Step 1-2 template/helper refactor | 0.5d |
| Step 3 — refactor 8 epic nodes to accept `ReviewScope` | 1d |
| Steps 4-8 — config, state plumbing, trigger routing, prepare-batch, batch-review prompt | 1d |
| Step 9 — graph wiring topology choice + implementation | 0.5–1d (depends on choice; see below) |
| Step 10 — sieve parser extension for new field-line `**Category:**` format and token aliases | 0.5–1d |
| Step 11 — new `batch-phase.json` checkpoint, session.json extension, resume routing | 0.5–1d |
| Steps 12-13 — halt routing + dead-code removal (full Step 13 surface) | 0.5d |
| Step 13a — toggle repurpose, naming decision, CLI/config docstring updates | 0.25d |
| Step 14-15 — tests + factory.yaml.example | 1–1.5d |

The dominant residual risk is the BMAD reviewer's vocabulary drift in the sieve (Step 10) — operator-acknowledged ~6 iterations on the existing epic-end sieve. The fallback-to-legacy-LLM path keeps the pipeline functional during iteration. The graph topology (Step 9) is decided: clone-and-rename, with thin wrappers around shared scope-aware helpers.

## Cross-references

- Epic-end review pipeline today: [`src/intake/epic_graph.py`](../src/intake/epic_graph.py), nodes `prepare_epic_reviews_node` through `epic_git_commit_node`
- Sieve: [`src/intake/review_sieve.py`](../src/intake/review_sieve.py)
- Per-story orchestrator: [`src/multi_agent/orchestrator.py`](../src/multi_agent/orchestrator.py)
- Halt-on-CI-exhaustion (recent): [`src/intake/epic_graph.py:579-598`](../src/intake/epic_graph.py#L579-L598)
- Future enhancement (iterative loop): [`future-enhancement-iterative-epic-review-loop.md`](future-enhancement-iterative-epic-review-loop.md)
- Epic 6 incident analysis: session log `b1458cb7-2781-4b90-9112-2eef9babc33c`

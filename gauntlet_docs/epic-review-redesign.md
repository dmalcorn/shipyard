# Epic Code Review Redesign: Looper-Aligned LangGraph Implementation

## Status: IMPLEMENTED — Decisions finalized and code updated 2026-03-26

---

## Current State Analysis

### What the Looper Scripts Do (7 Phases)

The original bash scripts (`looper/code-review-loop-bmad.sh`, `looper/code-review-loop-claude.sh`, `looper/code-review-analysis-fix.sh`) implement a sophisticated 7-phase epic code review:

| Phase | Name | What Happens | Agent |
|-------|------|-------------|-------|
| 0 | REVIEW | Two parallel reviews with **different methodologies**: BMAD 3-layer adversarial review + plain Claude direct review. Both are **read-only** — output captured by script, not written by agents. | Two Claude CLI sessions |
| 1 | ANALYZE | Compare both reviews. Create agreement table (what each caught, agreement rate, unique findings). Classify every issue as **Category A** (obvious fix) or **Category B** (architect decision). Produce: analysis.md, fix-plan.md (Cat A only), architect-review-needed.md (Cat B only). | Claude (analysis) |
| 2 | FIX | Apply Category A fixes immediately. Log results. Any skipped items get appended to Category B for architect. Run pytest + ruff check. | Dev agent |
| 3 | ARCHITECT | Review Category B items only. Make decisions with rationale. Produce: architect-recommendations.md, architect-fix-plan.md. Also does recurring pattern detection (updating CLAUDE.md). | Architect agent (reads CLAUDE.md + coding-standards.md first) |
| 4 | ARCH-FIX | Apply architect's approved fixes. | Dev agent |
| 5 | CI | Run full CI with auto-fix retry loop (up to 4 attempts, 35min timeout each). | Bash + Claude |
| 6 | GIT | Stage epic-specific files, commit with pre-commit hooks and retry. | Bash (git) |

### What LangGraph Currently Does (3 Steps)

| Step | What Happens | Agent |
|------|-------------|-------|
| 1 | Two parallel reviewers with different focus areas (integration vs architecture), both write review files to `epic-reviews/`. | LangGraph sub-agents (Sonnet) |
| 2 | Architect reads both review files, decides fix/dismiss, writes `epic-fix-plan.md`, updates CLAUDE.md with recurring patterns. | LangGraph sub-agent (Opus) |
| 3 | Fix dev applies plan, CI runs with retry loop. | LangGraph sub-agents |

### Key Gaps (Looper Has, LangGraph Doesn't)

1. **No Category A/B Split** — LangGraph sends everything to architect with no pre-triage. Looper fixes obvious stuff immediately.
2. **No Comparison/Agreement Analysis** — Looper creates explicit agreement tables and deduplicates. LangGraph hands raw files to architect.
3. **Different Review Methodologies** — Looper uses two fundamentally different approaches (BMAD 3-layer vs plain Claude). LangGraph uses same methodology with different focus areas.
4. **Reviewer Write Restrictions** — Looper reviewers are strictly read-only (output captured by script). LangGraph reviewers have write_file and sometimes write to wrong paths.
5. **No Skipped Items Flow** — Looper appends skipped Phase 2 items to architect list. LangGraph has no equivalent.

### Things LangGraph Does Better (to preserve)

1. **Multi-perspective review agents** — The idea of having agents look from different perspectives (integration focus vs architecture focus) is valuable and should be preserved alongside the BMAD/Claude methodology split.
2. **LangGraph checkpointing** — Built-in resume capability, no need for the JSON state file.

### Things NOT to preserve from Looper

1. **Interactive architect gate** — The "Continue without architect review? [y/N]" prompt. User reports it never worked properly (timed out or continued without answer). Pipeline should be fully automated.
2. **Phase-level JSON resume** — LangGraph's own checkpointing handles this.

---

## Proposed Redesign

### Overview: Epic Review Pipeline (Implemented)

```
...all stories done
  → prepare_epic_reviews (clean review dir)
  → 2 parallel review agents (fan-out via Send)
     - Agent 1: BMAD 3-layer adversarial (via Claude CLI + bmad-code-review skill, read-only)
     - Agent 2: Claude integration/architecture review (via Claude CLI, read-only)
  → collect_reviews (fan-in, validate files)
  → analyze_reviews (compare, deduplicate, classify A vs B — dev agent via Claude CLI)
  → fix_category_a (apply obvious fixes, run quick checks — dev agent via Claude CLI)
  → route: has Category B items?
     → yes: epic_architect (review Category B, make decisions, update CLAUDE.md — Claude CLI --model opus)
            → route: fixes needed?
               → yes: epic_fix (apply fixes — dev agent via Claude CLI)
     → no: skip architect
  → epic_ci (run CI with auto-fix retry loop, up to 4 attempts)
  → epic_git_commit
  → epic_complete → END
```

### Detailed Node Design

#### Node 1: `prepare_epic_reviews`
- Clean `epic-reviews/` directory
- No change from current behavior
- Returns empty `epic_review_file_paths`

#### Node 2: Three Parallel Review Agents (Fan-Out)

**Agent 1: BMAD 3-Layer Review** (via Claude CLI)
- Uses `invoke_bmad_agent()` with `bmad-code-review` skill or bakes the 3-layer prompt directly (like looper does, to avoid HALT statements)
- Tool permissions: `TOOLS_REVIEW_READONLY` (Read, Glob, Grep, Task, TodoWrite, Skill)
- Strictly read-only — output captured, written to file by the node (not by the agent)
- Reviews ALL files modified in the epic, story by story
- Output: `epic-reviews/epic-review-bmad.md`

**Agent 2: Claude Integration Review** (via Claude CLI)
- Direct Claude invocation (no BMAD skill) — same approach as `code-review-loop-claude.sh`
- Focus: cross-story integration issues, inconsistencies, correctness, spec violations
- Tool permissions: `TOOLS_REVIEW_READONLY`
- Strictly read-only — output captured, written to file by the node
- Output: `epic-reviews/epic-review-integration.md`

**Agent 3: Claude Architecture Review** (via Claude CLI)
- Direct Claude invocation (no BMAD skill)
- Focus: architectural coherence, code duplication between stories, naming consistency, maintainability
- Tool permissions: `TOOLS_REVIEW_READONLY`
- Strictly read-only — output captured, written to file by the node
- Output: `epic-reviews/epic-review-architecture.md`

**Key design decision**: All three agents use Claude CLI (`invoke_bmad_agent` or similar), NOT LangGraph sub-agents. This solves the "writes to wrong path" problem because the node captures stdout and writes the file itself. Agents never have write access.

#### Node 3: `collect_reviews`
- Fan-in: validate all 3 review files exist
- If a file is missing, log warning but continue with what we have
- Returns list of valid review file paths

#### Node 4: `analyze_reviews` (NEW — corresponds to Looper Phase 1)

This is the key new node. It invokes a Claude agent (via CLI or LangGraph sub-agent) to:

1. Read all 3 review files
2. Create an **agreement analysis**:
   - What issues each agent caught
   - Which issues multiple agents agree on (higher confidence)
   - Unique findings per agent
   - Agreement rate
3. **Deduplicate** — merge equivalent findings across agents
4. **Classify** every unique finding as:
   - **Category A** (Clear Fix): Unambiguous, no architectural decisions, single correct fix
   - **Category B** (Architect Review): Multiple valid approaches, security implications, API changes, cross-epic impact
5. Write three output files:
   - `epic-reviews/analysis.md` — Full comparison table and findings
   - `epic-reviews/category-a-fix-plan.md` — Category A issues with specific fix instructions
   - `epic-reviews/category-b-architect-review.md` — Category B issues for architect

Tool permissions: `Read,Glob,Grep,Write,Task,TodoWrite` (can write analysis files, cannot edit source)

#### Node 5: `fix_category_a` (NEW — corresponds to Looper Phase 2)

Invokes a dev agent (via Claude CLI with `TOOLS_DEV` permissions) to:

1. Read `epic-reviews/category-a-fix-plan.md`
2. Read CLAUDE.md and coding-standards.md first
3. Apply each fix, logging results
4. Any fix that can't be applied cleanly gets appended to `category-b-architect-review.md`
5. Run quick verification (pytest relevant tests, ruff check)

Output: `epic-reviews/category-a-fix-done.md` (execution log)

Routing after this node:
- If Category B items exist → proceed to architect
- If no Category B items → skip to CI

#### Node 6: `epic_architect` (Enhanced — corresponds to Looper Phase 3)

Invokes architect agent (Opus tier, via LangGraph sub-agent or Claude CLI) to:

1. **CRITICAL FIRST STEP**: Read CLAUDE.md and `_bmad-output/planning-artifacts/coding-standards.md`
2. Read `epic-reviews/category-b-architect-review.md`
3. Read source files mentioned in findings
4. For each finding: decide **fix** (with specific instructions) or **dismiss** (with rationale)
5. Write `epic-fix-plan.md` with YAML frontmatter including `fixes_needed: true/false`
6. **Recurring Pattern Detection** (preserved from current implementation):
   - Look across ALL findings for patterns repeated in 2+ stories
   - Append new rules to CLAUDE.md under `## Agent Coding Rules`
   - Don't duplicate existing rules

Output: `epic-fix-plan.md`

#### Node 7: `fix_architect_plan` (corresponds to Looper Phase 4)

Same as current `epic_fix_node` — invokes dev agent to apply architect's approved fixes.

#### Node 8: `epic_ci` (corresponds to Looper Phase 5)

Run full CI with auto-fix retry loop:
1. Run `npm test` or `pytest` (auto-detected)
2. If fails: invoke fix agent with CI output, retry (up to 4 cycles)
3. Auto `npm install` if node_modules missing (already implemented)

#### Node 9: `epic_git_commit`

Git add + commit for the epic. Handles stale index.lock (already implemented).

### State Schema Additions

```python
class EpicState(TypedDict, total=False):
    # ... existing fields ...

    # NEW: Analysis phase outputs
    category_a_fix_plan_path: str      # Path to Category A fix plan
    category_b_review_path: str        # Path to Category B items for architect
    analysis_path: str                 # Path to comparison analysis
    category_a_fixes_applied: bool     # Whether Cat A fixes were done
    has_category_b_items: bool         # Whether architect review is needed
```

### Routing Logic

```
prepare_epic_reviews
  → [fan-out] 3 review agents (parallel)
  → collect_reviews
  → analyze_reviews
  → fix_category_a
  → route_after_category_a:
      if has_category_b_items → epic_architect
      else → epic_ci
  → epic_architect
  → route_after_architect:
      if fixes_needed → fix_architect_plan → epic_ci
      else → epic_ci
  → epic_ci
  → route_after_ci:
      if pass → epic_git_commit → END
      if fail + retries left → fix_ci → epic_ci
      if fail + no retries → epic_error → END
```

### Key Implementation Notes

1. **All 3 reviewers use Claude CLI** (`invoke_bmad_agent` or a new `invoke_claude_review` helper), not LangGraph sub-agents. This gives us:
   - Scoped tool permissions (read-only enforced by Claude CLI)
   - Output captured by the node, not written by the agent (no wrong-path problem)
   - Access to BMAD skills for Agent 1
   - Consistent with the rest of the pipeline (create_story, write_tests, implement all use Claude CLI)

2. **The analyze node could be either Claude CLI or LangGraph sub-agent**. It's an analysis task that writes files — doesn't need BMAD skills. LangGraph sub-agent with `write_file` tool restricted to `epic-reviews/` would work. Claude CLI also fine.

3. **The fix_category_a node needs full dev tools** (Edit, Bash for tests). Best done via Claude CLI with TOOLS_DEV permissions, same as the story-level dev agent.

4. **The architect node stays as LangGraph sub-agent** (uses Opus tier, already working). Or could switch to Claude CLI for consistency — depends on whether we want Opus specifically for architect decisions.

5. **File locations**:
   - All review artifacts: `epic-reviews/` (cleaned before each epic)
   - Fix plan: `epic-fix-plan.md` (project root, same as current)
   - Analysis: `epic-reviews/analysis.md`
   - Category A plan: `epic-reviews/category-a-fix-plan.md`
   - Category B items: `epic-reviews/category-b-architect-review.md`

### Migration Path

The changes are isolated to `src/intake/epic_graph.py`:
- Replace `epic_review_node` with 3 new review agent invocations
- Add `analyze_reviews_node` (new)
- Add `fix_category_a_node` (new)
- Modify `epic_architect_node` to read Category B file instead of raw reviews
- Update graph wiring with new conditional routing
- Add new state fields

No changes needed to: orchestrator.py, rebuild_graph.py, bmad_invoke.py, spawn.py.

### Decisions (Finalized)

1. **2 reviewers** (not 3): BMAD 3-layer adversarial + Claude integration/architecture review. Reduced from 3 to avoid cost/time overhead.

2. **BMAD reviewer uses skill** (not baked prompt): HALT statements were already removed from customized skills. Skill invocation keeps the review logic evolving with the skill definition.

3. **Analyze node**: Claude CLI with dev-agent role. Classification/comparison doesn't need Opus.

4. **Architect node**: Claude CLI with `--model opus` flag. `invoke_bmad_agent` and `invoke_claude_cli` now accept a `model` parameter that maps to `claude --model`. This gives explicit model control while keeping all agents on the same CLI invocation path.

5. **Per-story review**: Preserved as-is. Not stripped for rebuild mode.

---

## Summary of Changes from Current Implementation

| Aspect | Current | Proposed |
|--------|---------|----------|
| Review agents | 2 LangGraph sub-agents (same method, different focus) | 2 Claude CLI agents (BMAD 3-layer + Claude integration/architecture) |
| Review output | Agents write their own files (wrong-path bug) | Nodes capture output and write files (no wrong-path bug) |
| Pre-triage | None — everything goes to architect | Category A/B classification with agreement analysis |
| Obvious fixes | Architect decides everything | Category A fixes applied immediately by dev agent |
| Architect scope | Reviews all findings | Reviews only Category B (complex decisions) |
| CLAUDE.md updates | Architect does it | Preserved — architect still does recurring pattern detection |
| CI retry | Exists but basic | Enhanced with auto-fix loop (up to 4 attempts) |
| Git commit | Exists | Preserved with stale lock cleanup |

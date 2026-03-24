# Epic 3 — Code Review Analysis

**Date:** 2026-03-24
**Stories reviewed:** 3-1, 3-2, 3-3, 3-4, 3-5, 3-6
**Review agents:** BMAD Code Review Workflow, Direct Claude

---

## Executive Summary

Two independent review agents analyzed all 6 stories in Epic 3 (Multi-Agent Orchestration). Story 3-5 produced no findings from either agent — all issues come from stories 3-1 through 3-4 and 3-6.

After deduplication and consolidation across stories and agents, **39 unique issues** remain:
- **28 Category A** (clear, non-controversial fixes) → fix plan
- **11 Category B** (architectural/design decisions) → architect review

The most critical themes are:
1. **Path traversal bypass** in `_is_path_allowed` (security — P0)
2. **Broken fix-dev retry loop** — `edit_retry_count` never incremented + shared counters
3. **State schema gaps** — missing reducer on `review_file_paths`, dead `error_log` field
4. **Prompt/path inconsistencies** — `fix-plan.md` path differs between prompts and orchestrator
5. **SQLite connection leak** — connections opened but never closed in subgraph creation

---

## Agent Coverage Comparison

| Dimension | BMAD Workflow | Direct Claude |
|---|---|---|
| Stories reviewed | 6 (5 with findings) | 6 (5 with findings) |
| Total raw findings | ~59 | ~46 |
| Review layers | 3 (Blind Hunter, Edge Case, Acceptance) | 1 (combined) |
| Duration | 23m 0s | 25m 27s |
| Unique findings (not in other agent) | ~18 | ~12 |
| Files loaded per story | 3–6 source files | 8–15 files (broader scope) |

### Coverage by Story

| Story | BMAD Issues | Claude Issues | Overlap | Total Unique |
|---|---|---|---|---|
| 3-1 Agent Role Defs | 14 | 11 | 6 | 19 |
| 3-2 Sub-Agent Spawning | 14 | 12 | 6 | 20 |
| 3-3 Parallel Review | 14 | 10 | 4 | 20 |
| 3-4 Architect Fix Pipeline | 17 | 7 | 5 | 19 |
| 3-5 Full TDD Pipeline | 0 | 0 | 0 | 0 |
| 3-6 CODEAGENT.md | 17 | 6 | 3 | 20 |

**Note:** Many issues are repeated across stories (same root cause found in different contexts). After cross-story deduplication, the ~98 raw rows consolidate to 39 unique issues.

---

## Agent Strengths

### BMAD Workflow Strengths
- **Edge case depth** — Found attack payloads for path traversal (e.g., `reviews/../src/main.py`)
- **Spec compliance** — Caught AC#5 exact text deviation, missing `fix_cycle_count` per spec
- **Repeat detection** — Found the shared counter issue independently in 3 stories
- **Boundary conditions** — `retry_count` None edge case, file-named-as-directory confusion

### Direct Claude Strengths
- **Coding standards enforcement** — Caught missing exception handling in restricted tools per tool interface contract
- **Architecture layer violations** — Double context injection (Layer 1 + Layer 2)
- **Dead code detection** — Unused logging import, unnecessary f-string, unnecessary @patch
- **Test quality** — Tool count tests verify wrong module, test doesn't verify successful write

---

## Consolidated Issue List with Classification

Each issue is assigned to exactly one category:
- **A** = Clear fix (goes to fix plan only)
- **B** = Architect review needed (goes to architect review only)

### Story 3-1: Agent Role Definitions & Tool Subsets

| ID | Issue | Severity | Cat | Agents |
|---|---|---|---|---|
| A-01 | Path traversal bypass — `lstrip("./")` doesn't normalize `..` | CRITICAL | A | Both |
| A-09 | `PERMISSION_DENIED_MSG` text doesn't match AC#5 | HIGH | A | Both |
| A-11 | Restricted tools lack try/except per tool interface contract | MEDIUM | A | Claude |
| A-12 | `get_prompt()` docstring omits `fix_dev` from valid roles | LOW | A | Both |
| A-13 | Restricted tool docstrings say "Used by: Dev, Architect" (wrong) | LOW | A | Both |
| A-14 | Unused `logging` import and `logger` in restricted.py | LOW | A | Claude |
| A-15 | Unnecessary f-string in `_format_allowed` | LOW | A | Claude |
| A-23 | Test `_exact` only checks substrings, not exact equality | MEDIUM | A | Both |
| A-28 | `get_tools_for_role` raises raw `KeyError` on missing tool | LOW | A | BMAD |
| B-03 | Reviewer `edit_file` — tool exclusion vs restricted-returns-error (AC#5) | MEDIUM | B | Both |

### Story 3-2: Sub-Agent Spawning with Subgraphs

| ID | Issue | Severity | Cat | Agents |
|---|---|---|---|---|
| A-04 | SQLite connection leak — opened but never closed | HIGH | A | Both |
| A-17 | `create_agent_subgraph` return type uses `Any` | LOW | A | Both |
| A-19 | `MAX_RETRIES` naming misleading — actually max turns | LOW | A | Claude |
| A-20 | `run_sub_agent` bypasses `build_trace_config()` validation | MEDIUM | A | Both |
| A-26 | `tmp_path` typed as `object` instead of `Path` in test fixtures | LOW | A | Both |
| A-27 | Test imports inside methods instead of at module top | LOW | A | Both |
| B-04 | Double context injection — files in both Layer 1 and Layer 2 | MEDIUM | B | Claude |
| B-05 | System prompt re-prepended every LLM turn (not persisted) | MEDIUM | B | BMAD |
| B-06 | `run_sub_agent` doesn't propagate/distinguish success vs failure | MEDIUM | B | BMAD |
| B-07 | Thread ID collision — `int(time.time())` 1-second granularity | HIGH | B | BMAD |
| B-11 | `check_same_thread=False` SQLite threading model | MEDIUM | B | Claude |

### Story 3-3: Parallel Review Pipeline (Send API)

| ID | Issue | Severity | Cat | Agents |
|---|---|---|---|---|
| A-02 | `review_file_paths` missing `operator.add` reducer | MEDIUM | A | Both |
| A-18 | `.gitkeep` missing `encoding="utf-8"` | LOW | A | Both |
| A-24 | Tests use real `reviews/` dir instead of `tmp_path` | MEDIUM | A | Both |
| A-25 | Unnecessary `@patch` on `test_architect_uses_opus_model_tier` | LOW | A | Both |
| A-16 | `build_orchestrator` return type is `Any` | MEDIUM | A | Claude |
| B-02 | No conditional routing after `collect_reviews` — architect runs with bad data | HIGH | B | Both |
| B-08 | `_validate_review_file` — how robust should frontmatter validation be? | LOW | B | Both |
| B-10 | `_run_bash` missing `cwd` parameter — execution context | MEDIUM | B | BMAD |

### Story 3-4: Architect Decision & Fix Pipeline

| ID | Issue | Severity | Cat | Agents |
|---|---|---|---|---|
| A-03 | `edit_retry_count` never incremented — retry context dead code | HIGH | A | Both |
| A-06 | `error_log` accumulator field never populated | MEDIUM | A | BMAD |
| A-10 | Add "architect" to `VALID_PHASES`, fix `architect_node` phase | LOW | A | Both |
| A-21 | Redundant pytest instruction in `fix_dev_node` task description | LOW | A | BMAD |
| A-22 | Ambiguous `current_phase` reuse in post-fix nodes | LOW | A | BMAD |
| B-01 | Shared `test_cycle_count`/`ci_cycle_count` — missing `fix_cycle_count` | HIGH | B | Both |
| B-09 | No validation `fix-plan.md` exists before spawning Fix Dev | MEDIUM | B | BMAD |

### Story 3-5: Full TDD Orchestrator Pipeline

No findings from either agent.

### Story 3-6: CODEAGENT.md Multi-Agent Design Section

| ID | Issue | Severity | Cat | Agents |
|---|---|---|---|---|
| A-05 | Python list repr injected as YAML in review task description | MEDIUM | A | BMAD |
| A-07 | Fix Dev prompt references `reviews/fix-plan.md` (wrong path) | MEDIUM | A | Both |
| A-08 | Architect prompt says "write to reviews/" but should be project root | MEDIUM | A | Both |

---

## Severity Distribution (Consolidated)

| Severity | Category A | Category B | Total |
|---|---|---|---|
| CRITICAL | 1 | 0 | 1 |
| HIGH | 3 | 3 | 6 |
| MEDIUM | 10 | 6 | 16 |
| LOW | 14 | 2 | 16 |
| **Total** | **28** | **11** | **39** |

---

## Output Files

| File | Contents | Issue Count |
|---|---|---|
| `epic3-code-review-fix-plan.md` | Category A only — clear fixes, prioritized P0–P3 | 28 |
| `epic3-architect-review-needed.md` | Category B only — needs architect decision | 11 |

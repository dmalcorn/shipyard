# Epic 3 — Architect Review Needed

**Date:** 2026-03-24
**Scope:** Category B issues only — require architectural decision before fixing
**Total items:** 15

Items are classified **not in** `epic3-code-review-fix-plan.md`. No overlap.

---

## B-01: Reviewer `edit_file` strategy — tool exclusion vs restricted tool

- **Files:** `src/multi_agent/roles.py:65`, `src/tools/restricted.py`
- **Found by:** Both agents (BMAD 3-1#11,13 + Claude 3-1#2)
- **Severity:** MEDIUM

### Current State
AC#5 says: "When [Reviewer] attempts to call `edit_file` on a source file, Then the tool returns `ERROR: Permission denied...`" The implementation removes `edit_file` from the Reviewer's tool list entirely — the LLM can never call it. The test checks tool absence, not error return.

### Why Architect Review
Two valid enforcement philosophies:

| Option | Pros | Cons |
|---|---|---|
| A. Tool exclusion (current) | Stronger — LLM can't even attempt the call | Deviates from AC#5 text; no corrective feedback |
| B. Restricted tool returning error | Matches AC#5 exactly; teaches LLM boundaries | Tool exists in schema — LLM may waste turns trying |
| C. Tool exclusion + update AC#5 | Clean enforcement + accurate spec | Requires spec change approval |

### Recommendation
Option C. Tool exclusion is defensively stronger. Update the story spec to reflect the actual (better) implementation.

### Decision Question
**Should the Reviewer have a restricted `edit_file` that returns an error message (matching AC#5 literally), or keep tool exclusion and update the spec?**

---

## B-02: AC#5 error message exact text (depends on B-01)

- **Files:** `src/tools/restricted.py:19-21`
- **Found by:** Both agents
- **Severity:** MEDIUM

### Current State
Message: `"ERROR: Permission denied: reviewer agents cannot edit source files. Write to reviews/ only."`
AC#5 specifies: `"ERROR: Permission denied: Review agents cannot edit source files. Write to reviews/ directory only."`

### Why Architect Review
If B-01 chooses tool exclusion (Option C), this is moot — the message is never produced for `edit_file`. If B-01 chooses Option B, the exact text needs sign-off. The `write_file` restricted tool still uses this message format, so the text matters regardless.

### Decision Question
**If restricted `edit_file` is added (B-01=B), should the error message match AC#5 verbatim? For `write_file`, should the message use title-case role names and include "directory"?**

---

## B-03: fix-plan.md canonical path

- **Files:** `src/agent/prompts.py:82,109`, `src/multi_agent/orchestrator.py:30`, `src/multi_agent/roles.py:75`
- **Found by:** Both agents (across stories 3-1, 3-4, 3-6)
- **Severity:** HIGH

### Current State
Three conflicting references:
- `orchestrator.py:30`: `FIX_PLAN_PATH = "fix-plan.md"` (project root)
- `prompts.py:109` (Fix Dev prompt): `"Read the fix plan from reviews/fix-plan.md"`
- `prompts.py:82` (Architect prompt): `"You CAN write fix plans to the reviews/ directory"`
- `roles.py:75`: `write_restrictions=("reviews/", "fix-plan.md")` — allows both locations

### Why Architect Review
The orchestrator uses project root, the prompts reference `reviews/`. If Fix Dev follows its system prompt literally, it reads from the wrong path. This is a cross-cutting inconsistency that affects the agent communication contract.

| Option | Pros | Cons |
|---|---|---|
| A. Project root `fix-plan.md` | Clean separation (reviews = reviewer output, root = architect decisions) | Need to update both prompts |
| B. `reviews/fix-plan.md` | All inter-agent files in one directory, matches prompt text | Need to update `FIX_PLAN_PATH` constant and orchestrator |

### Recommendation
Option A. Keep the clear directory semantics. Update the two prompt strings. (Fix plan items A-42/A-44 implement this if approved.)

### Decision Question
**Should `fix-plan.md` live at project root (current orchestrator behavior) or inside `reviews/` (current prompt text)?**

---

## B-04: Shared retry counters across pipeline phases — missing `fix_cycle_count`

- **Files:** `src/multi_agent/orchestrator.py:76-77,466,517,535,553`
- **Found by:** Both agents (BMAD 3-3, 3-4, 3-6 + Claude 3-4)
- **Severity:** HIGH

### Current State
`test_cycle_count` is incremented by `unit_test_node` (line 466), `post_fix_test_node` (line 517), and `system_test_node` (line 553). `ci_cycle_count` is shared between `ci_node` (line 484) and `post_fix_ci_node` (line 535). If the initial TDD loop consumes 3 of 5 allowed test cycles, the post-fix loop gets only 2 attempts. Story spec Task 4 says "Track `fix_cycle_count`" and "up to 5 cycles" for the fix test gate.

### Why Architect Review
Multiple valid approaches with different state schema implications:

| Option | Pros | Cons |
|---|---|---|
| A. Add `fix_test_cycle_count` + `fix_ci_cycle_count` | Clean separation, each phase gets full budget | More state fields, more routing logic |
| B. Reset counters between phases | Simpler state, reuses existing fields | Implicit — easy to forget, loses history |
| C. Keep shared counters, increase limits | Minimal code change | Wasteful, doesn't match spec intent |
| D. Per-phase counter dict | Extensible, single field | Complex access pattern |

### Recommendation
Option A. Matches the story spec's intent for independent budgets. Add `fix_test_cycle_count: int` and `fix_ci_cycle_count: int` to `OrchestratorState`.

### Decision Question
**Should each pipeline phase (TDD loop, fix loop, system tests) have its own independent cycle counter, or share a budget?**

---

## B-05: Double context injection — files in both system prompt and task context

- **File:** `src/multi_agent/spawn.py:82,118`
- **Found by:** Claude 3-2#2
- **Severity:** MEDIUM

### Current State
`create_agent_subgraph()` passes `context_files` to BOTH `build_system_prompt()` (Layer 1 — SystemMessage) and `inject_task_context()` (Layer 2 — HumanMessage). Per the architecture doc, context files are Layer 2 content. This duplicates every context file in the sub-agent's input.

### Why Architect Review
Touches the core context injection architecture:

| Option | Pros | Cons |
|---|---|---|
| A. Remove from Layer 1 (system prompt) | Matches architecture; saves tokens | System prompt may lose role-relevant file context |
| B. Remove from Layer 2 (task context) | System prompt has full picture | Task context needs file context for instructions |
| C. Keep both (current) | Redundancy ensures LLM sees context | Wastes tokens, duplicate content |
| D. Split: coding-standards in L1, task files in L2 | Clean separation by purpose | Requires refactoring `build_system_prompt` |

### Recommendation
Option A. System prompt should contain only role description + coding standards (Layer 1). Task-specific files belong in Layer 2.

### Decision Question
**Should context files be injected in Layer 1 (system prompt), Layer 2 (task context), or both?**

---

## B-06: System prompt re-prepended every LLM turn

- **File:** `src/multi_agent/spawn.py:87-89`
- **Found by:** BMAD 3-2#1.3
- **Severity:** MEDIUM

### Current State
The `agent_node` function prepends `SystemMessage` to a local copy of messages but never stores it in state. On the next turn, the check fails again, causing re-prepending. This bloats context with repeated system prompts.

### Why Architect Review
Fix approach depends on LangGraph's message handling semantics:

| Option | Pros | Cons |
|---|---|---|
| A. Store SystemMessage in state on first call | Persisted once, never duplicated | Requires reducer to handle SystemMessage |
| B. Set SystemMessage in initial_state before invocation | Clean, one-time injection | May not survive checkpoint serialization |
| C. Use LangGraph's `system_message` config option | Framework-native | Version-dependent availability |

### Recommendation
Option A — include the SystemMessage in the initial state's messages list.

### Decision Question
**How should the system prompt be persisted across LLM turns — stored in state, passed via config, or handled differently?**

---

## B-07: `run_sub_agent` doesn't propagate success vs failure

- **File:** `src/multi_agent/spawn.py:191-207`
- **Found by:** BMAD 3-2#1.4
- **Severity:** MEDIUM

### Current State
If a sub-agent exceeds MAX_RETRIES, `run_sub_agent` returns `final_message` containing "ERROR:" but has no explicit success/failure signal. The orchestrator blindly proceeds.

### Why Architect Review
Error contract affects all orchestrator nodes:

| Option | Pros | Cons |
|---|---|---|
| A. Add `"success": bool` to return dict | Explicit, easy to route on | All callers must check |
| B. Raise exception on failure | Standard Python | Graph nodes shouldn't raise per coding standards |
| C. Parse `final_message` for "ERROR:" | No code change | Fragile string matching |

### Recommendation
Option A — add `"success": bool` to the return dict.

### Decision Question
**How should `run_sub_agent` signal failure to the orchestrator — explicit status field, exception, or message parsing?**

---

## B-08: No conditional routing after `collect_reviews`

- **Files:** `src/multi_agent/orchestrator.py:352-358,803`
- **Found by:** Both agents (BMAD 3-3, 3-4 + Claude 3-4)
- **Severity:** HIGH

### Current State
`collect_reviews` detects missing reviews and sets `"error"` in state, but line 803 is an unconditional edge: `graph.add_edge("collect_reviews", "architect_node")`. The Architect runs even with 0 valid reviews — wasting an expensive Opus call.

### Why Architect Review
Failure strategy has pipeline-wide implications:

| Option | Pros | Cons |
|---|---|---|
| A. Conditional edge → `error_handler` when < 2 reviews | Fail-fast, clear | Pipeline halts entirely |
| B. Retry `route_to_reviewers` | Self-healing | Could loop, needs retry limit |
| C. Let architect proceed with partial data | Graceful degradation | Garbage-in risk |

### Recommendation
Option A for MVP — fail-fast. AC#3 says "both reviews are complete" is a precondition.

### Decision Question
**When reviews are incomplete (0 or 1 out of 2), should the pipeline halt, retry, or let the architect proceed?**

---

## B-09: `check_same_thread=False` SQLite threading model

- **File:** `src/multi_agent/spawn.py:113`
- **Found by:** Claude 3-2#6
- **Severity:** MEDIUM

### Current State
`sqlite3.connect(checkpoints_db, check_same_thread=False)` disables Python's thread safety check. If LangGraph uses multiple threads, concurrent writes can cause data corruption.

### Why Architect Review
Threading model affects data integrity:

| Option | Pros | Cons |
|---|---|---|
| A. Keep flag, enable WAL mode | Better concurrent reads | WAL doesn't protect concurrent writes on same connection |
| B. Remove flag, connection-per-thread | Thread-safe by default | Need to restructure SqliteSaver usage |
| C. Use `SqliteSaver.from_conn_string()` | Framework manages threading | May not exist in current langgraph version |

### Recommendation
Investigate Option C first — also resolves A-03 (connection leak).

### Decision Question
**Should SQLite checkpointing use `check_same_thread=False`, switch to framework-managed connections, or adopt a different checkpointer?**

---

## B-10: Thread ID collision for parallel reviewers

- **File:** `src/multi_agent/spawn.py:173`
- **Found by:** BMAD (3-2#1.5/2.6, 3-4#7)
- **Severity:** HIGH

### Current State
```python
sub_thread_id = f"{parent_session_id}-{role}-{int(time.time())}"
```
`int(time.time())` has 1-second granularity. Two parallel reviewer sub-agents spawned via Send API within the same second get identical `thread_id`, causing checkpoint collisions.

### Why Architect Review
Thread ID strategy affects checkpoint data integrity:

| Option | Pros | Cons |
|---|---|---|
| A. Use `uuid.uuid4()` suffix | Guaranteed unique | Loses human-readable structure |
| B. Accept `reviewer_id` parameter, include in thread_id | Semantic, readable | Requires caller to pass additional context |
| C. Use monotonic counter (thread-safe) | Sequential, readable | Needs shared state |
| D. Use `time.time_ns()` (nanosecond precision) | Minimal change | Still theoretically collidable |

### Recommendation
Option B — the orchestrator already has `reviewer_id` (1 or 2). Pass it through and use `f"{parent}-{role}-{reviewer_id}-{int(time.time())}"`.

### Decision Question
**What thread ID strategy should parallel sub-agents use to prevent checkpoint collisions?**

---

## B-11: Context files silent degradation vs fail-loud

- **File:** `src/context/injection.py:90-95`
- **Found by:** BMAD 3-2#2.3
- **Severity:** LOW

### Current State
When a context file doesn't exist, `inject_task_context` substitutes "(file not available)" and proceeds. For critical context (story spec), this could produce completely wrong output. Coding standards say "Fail-loud semantics."

### Why Architect Review
For optional context files, degradation makes sense. For required context (story spec, fix plan), failure should halt. This requires classifying context files.

### Decision Question
**Should missing context files cause failure or graceful degradation? Should there be a required/optional distinction?**

---

## B-12: `run_sub_agent` signature deviates from spec

- **File:** `src/multi_agent/spawn.py:127-135`
- **Found by:** BMAD 3-2#3.2
- **Severity:** LOW

### Current State
Spec says: `run_sub_agent(state: OrchestratorState, role, task, context_files) -> dict`
Implementation takes individual fields: `parent_session_id, task_id, role, task_description, ...`

### Why Architect Review
The implementation is arguably better (avoids coupling to OrchestratorState), but deviates from spec. Should be formally accepted.

### Decision Question
**Should the spec be updated to match the implementation (individual params), or should the code take `OrchestratorState`?**

---

## B-13: `_run_bash` missing `cwd` parameter

- **File:** `src/multi_agent/orchestrator.py:148-153`
- **Found by:** BMAD 3-3#2.2
- **Severity:** MEDIUM

### Current State
No `cwd` parameter in `subprocess.run`. Commands resolve relative paths against the process's CWD, which may not be the project root.

### Why Architect Review
Working directory strategy is cross-cutting:

| Option | Pros | Cons |
|---|---|---|
| A. Pass `cwd=PROJECT_ROOT` from config | Explicit, portable | Needs constant or config |
| B. Resolve from `__file__` | Auto-detect | Fragile if installed elsewhere |
| C. Document CWD requirement | No code change | Error-prone |

### Decision Question
**Where should bash command execution get its working directory?**

---

## B-14: No validation fix-plan.md exists before spawning Fix Dev

- **File:** `src/multi_agent/orchestrator.py:806`
- **Found by:** BMAD 3-4#9
- **Severity:** MEDIUM

### Current State
`graph.add_edge("architect_node", "fix_dev_node")` is unconditional. If Architect fails to write `fix-plan.md`, Fix Dev spawns anyway.

### Why Architect Review
Part of broader pipeline validation question (see B-08):

| Option | Pros | Cons |
|---|---|---|
| A. Conditional edge with file existence check | Fail-fast | More complex graph |
| B. Validate inside `fix_dev_node` | Simpler graph | Late failure |
| C. Dedicated validation node | Clean separation | Extra node |

### Recommendation
Option A — add `route_after_architect` that checks `os.path.exists(FIX_PLAN_PATH)`.

### Decision Question
**Should fix-plan.md existence be validated via graph routing, inside fix_dev_node, or via a dedicated validation node?**

---

## B-15: `_validate_review_file` — validation depth

- **File:** `src/multi_agent/orchestrator.py:128-138`
- **Found by:** Both agents (across 3-3, 3-4, 3-6)
- **Severity:** LOW

### Current State
```python
return content.startswith("---")
```
Any file starting with `---` passes, even without closing `---`, valid YAML, or required fields.

### Why Architect Review
Validation robustness is a design trade-off:

| Option | Pros | Cons |
|---|---|---|
| A. Check opening AND closing `---` | Minimal change | Doesn't verify content |
| B. Parse YAML, check required fields | Full validation | Adds pyyaml dependency |
| C. Keep current | Simple, fast | Accepts garbage |

### Recommendation
Option A as minimum. Option B if pyyaml is already a dependency.

### Decision Question
**How thoroughly should review file frontmatter be validated?**

---

## Summary

| ID | Issue | Severity | Key Decision |
|---|---|---|---|
| B-03 | fix-plan.md canonical path | HIGH | Project root or reviews/? |
| B-04 | Shared retry counters | HIGH | Separate counters per phase? |
| B-08 | No routing after failed reviews | HIGH | Halt, retry, or degrade? |
| B-10 | Thread ID collision | HIGH | UUID, reviewer_id, counter? |
| B-01 | Reviewer edit_file strategy | MEDIUM | Tool exclusion or restricted? |
| B-02 | Error message exact text | MEDIUM | Verbatim AC#5 or current? |
| B-05 | Double context injection | MEDIUM | Layer 1, Layer 2, or both? |
| B-06 | System prompt re-prepended | MEDIUM | Store in state or config? |
| B-07 | No success/failure signal | MEDIUM | Status field or exception? |
| B-09 | SQLite threading model | MEDIUM | Current, framework-managed, async? |
| B-13 | Missing `cwd` in bash exec | MEDIUM | Config, auto-detect, or CWD? |
| B-14 | No fix-plan.md validation | MEDIUM | Graph routing or self-check? |
| B-11 | Context files degradation | LOW | Fail-loud or graceful? |
| B-12 | run_sub_agent signature | LOW | Update spec or code? |
| B-15 | Review file validation depth | LOW | Structural or full YAML? |

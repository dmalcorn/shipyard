# Epic 3 — Architect Review Needed

**Date:** 2026-03-24
**Scope:** Category B issues only — require architectural decision before fixing
**Total items:** 11

Items are classified **not in** `epic3-code-review-fix-plan.md`. No overlap.

---

## B-01: Shared retry counters across pipeline phases — missing `fix_cycle_count`

- **Files:** `src/multi_agent/orchestrator.py:76-77,466,517,535,553`
- **Found by:** Both agents (BMAD 3-3#1.3, 3-4#2,12,13, 3-6#1,2 + Claude 3-4#2)
- **Severity:** HIGH

### Current State
`test_cycle_count` is incremented by `unit_test_node` (line 466), `post_fix_test_node` (line 517), and `system_test_node` (line 553). `ci_cycle_count` is shared between `ci_node` (line 484) and `post_fix_ci_node` (line 535). If the initial TDD loop consumes 3 of 5 allowed test cycles, the post-fix loop gets only 2 attempts. The story spec (Task 4) says "Track `fix_cycle_count`" and "up to 5 cycles" for the fix test gate.

### Why Architect Review
Multiple valid approaches exist, each with different state schema implications:

| Option | Pros | Cons |
|---|---|---|
| A. Add `fix_test_cycle_count` + `fix_ci_cycle_count` | Clean separation, each phase gets full budget | More state fields, more routing logic |
| B. Reset counters between phases | Simpler state, reuses existing fields | Implicit — easy to forget reset step, loses history |
| C. Keep shared counters, increase limits | Minimal code change | Wasteful budget, doesn't match spec intent |
| D. Per-phase counter dict `cycle_counts: dict[str, int]` | Extensible, single field | More complex access pattern, harder to type |

### Recommendation
Option A. It matches the story spec's intent for independent budgets and is explicit. The new fields would be `fix_test_cycle_count: int` and `fix_ci_cycle_count: int`.

### Decision Question
**Should each pipeline phase (TDD loop, fix loop, system tests) have its own independent cycle counter, or share a budget?**

---

## B-02: No conditional routing after `collect_reviews`

- **Files:** `src/multi_agent/orchestrator.py:352-358,803`
- **Found by:** Both agents (BMAD 3-3#1.2/3.1, 3-4#3/15 + Claude 3-4#3)
- **Severity:** HIGH

### Current State
`collect_reviews` (line 352) detects when fewer than 2 valid review files exist and sets `"error"` in state. But line 803 is an unconditional edge: `graph.add_edge("collect_reviews", "architect_node")`. The Architect Agent runs regardless — even with 0 valid reviews — wasting an expensive Opus model call on incomplete data.

### Why Architect Review
The failure strategy has pipeline-wide implications:

| Option | Pros | Cons |
|---|---|---|
| A. Conditional edge → `error_handler` when < 2 reviews | Fail-fast, clear | Pipeline halts entirely — no partial value |
| B. Conditional edge → retry `route_to_reviewers` | Self-healing | Could loop forever, complexity, budget question |
| C. Let architect proceed with whatever reviews exist | Graceful degradation, simpler graph | Architect may produce poor fix plan from incomplete data |
| D. Conditional edge → architect only if ≥ 1, error if 0 | Balanced | Architect with 1 review may miss issues |

### Recommendation
Option A for now (MVP — fail-fast). Add a `route_after_collect_reviews` function that checks `len(state.get("review_file_paths", []))` and routes to `error_handler` if < 2.

### Decision Question
**When reviews are incomplete (0 or 1 out of 2), should the pipeline halt, retry, or let the architect proceed with partial data?**

---

## B-03: Reviewer `edit_file` strategy — tool exclusion vs restricted tool

- **Files:** `src/multi_agent/roles.py:65`, `src/tools/restricted.py`
- **Found by:** Both agents (BMAD 3-1#11,13 + Claude 3-1#2)
- **Severity:** MEDIUM

### Current State
AC#5 says: "When [Reviewer] attempts to call `edit_file` on a source file, Then the tool returns `ERROR: Permission denied...`" The implementation removes `edit_file` from the Reviewer's tool list entirely — the LLM can never call it. The test checks tool absence, not error return.

### Why Architect Review
Two valid enforcement philosophies:

| Option | Pros | Cons |
|---|---|---|
| A. Tool exclusion (current) | Stronger — LLM can't even attempt the call | Deviates from AC#5 text; no error message to learn from |
| B. Restricted tool returning error | Matches AC#5 exactly; teaches LLM boundaries | Tool exists in schema — LLM may waste turns trying |
| C. Tool exclusion + update AC#5 | Clean enforcement + accurate spec | Requires spec change approval |

### Recommendation
Option C. Tool exclusion is defensively stronger. Update the story spec to reflect the actual (better) implementation.

### Decision Question
**Should the Reviewer have a restricted `edit_file` that returns an error message (matching AC#5 literally), or keep tool exclusion and update the spec?**

---

## B-04: Double context injection — files in both system prompt and task context

- **File:** `src/multi_agent/spawn.py:82,118`
- **Found by:** Claude 3-2#2
- **Severity:** MEDIUM

### Current State
`create_agent_subgraph()` passes `context_files` to BOTH:
1. `build_system_prompt(role_config.system_prompt_key, context_files)` (line 82) — Layer 1
2. `inject_task_context(task_description, context_files)` (line 118) — Layer 2

This duplicates the full content of every context file in the sub-agent's input — once in the SystemMessage and once in the HumanMessage. Per the architecture doc, context files are Layer 2 content.

### Why Architect Review
This touches the core context injection architecture:

| Option | Pros | Cons |
|---|---|---|
| A. Remove from Layer 1 (system prompt) | Matches architecture spec; saves tokens | System prompt may need file context for role constraints |
| B. Remove from Layer 2 (task context) | System prompt has full picture | Task context is where "what to do" lives — needs file context |
| C. Keep both (current) | Redundancy ensures LLM sees context | Wastes tokens, may confuse with duplicate content |
| D. Split: coding-standards in L1, task files in L2 | Clean separation by purpose | Requires `build_system_prompt` to accept different file types |

### Recommendation
Option A — remove `context_files` from `build_system_prompt()`. System prompt should contain only the role description + coding standards (Layer 1). Task-specific files belong in Layer 2 via `inject_task_context()`.

### Decision Question
**Should context files be injected in Layer 1 (system prompt), Layer 2 (task context), or both? What files, if any, belong in Layer 1?**

---

## B-05: System prompt re-prepended every LLM turn

- **File:** `src/multi_agent/spawn.py:87-89`
- **Found by:** BMAD 3-2#1.3
- **Severity:** MEDIUM

### Current State
```python
def agent_node(state: AgentState) -> dict[str, Any]:
    messages = state["messages"]
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt), *messages]
```
The `SystemMessage` is prepended to a local copy of messages but never stored in state. On the next turn, `messages[0]` is the original `HumanMessage` again (from task context), so the system prompt gets re-prepended every turn. This bloats context with repeated preamble.

### Why Architect Review
The fix approach depends on LangGraph's message handling semantics:

| Option | Pros | Cons |
|---|---|---|
| A. Store SystemMessage in state on first call | Persisted once, never duplicated | Requires `add_messages` reducer to handle SystemMessage idempotently |
| B. Set SystemMessage in initial_state before invocation | Clean, one-time injection | LangGraph may not preserve SystemMessage ordering through checkpoints |
| C. Use LangGraph's `system_message` config option | Framework-native approach | May not be available in all LangGraph versions |
| D. Use a state flag `system_prompt_set: bool` | Explicit control | Extra state field for bookkeeping |

### Recommendation
Option A — include the `SystemMessage` in the initial state's `messages` list so it's stored once via the reducer.

### Decision Question
**How should the system prompt be persisted across LLM turns — stored in state, passed via config, or handled differently?**

---

## B-06: `run_sub_agent` doesn't propagate success vs failure

- **File:** `src/multi_agent/spawn.py:191-207`
- **Found by:** BMAD 3-2#1.4
- **Severity:** MEDIUM

### Current State
If a sub-agent hits the error handler (exceeds `MAX_RETRIES`), `run_sub_agent` returns `{"files_modified": [...], "final_message": "ERROR: Sub-agent exceeded 50 turns."}`. The caller gets a `final_message` containing "ERROR:" but there's no explicit success/failure signal. The orchestrator cannot programmatically distinguish success from failure without parsing the message string.

### Why Architect Review
The error contract affects the orchestrator's routing logic:

| Option | Pros | Cons |
|---|---|---|
| A. Add `"success": bool` field to return dict | Explicit, easy to route on | Requires all callers to check |
| B. Raise exception on failure | Standard Python error handling | Orchestrator graph nodes shouldn't raise per coding standards |
| C. Add `"status": "success"|"error"|"timeout"` field | Richer than bool | More complex routing |
| D. Keep current — parse `final_message` for "ERROR:" | No code change | Fragile, depends on message format |

### Recommendation
Option A — add `"success": bool` to the return dict. Set `False` when the final message starts with "ERROR:".

### Decision Question
**How should `run_sub_agent` signal failure to the orchestrator — explicit status field, exception, or message parsing?**

---

## B-07: Thread ID collision for parallel reviewers

- **File:** `src/multi_agent/spawn.py:173`
- **Found by:** BMAD 3-2#1.5/2.6, 3-4#7
- **Severity:** HIGH

### Current State
```python
sub_thread_id = f"{parent_session_id}-{role}-{int(time.time())}"
```
`int(time.time())` has 1-second granularity. Two parallel reviewer sub-agents spawned via Send API within the same second get identical `thread_id` values (e.g., `sess-1-reviewer-1711234567`). Since both share `checkpoints_db`, their checkpoint writes collide — one agent's state may overwrite the other's.

### Why Architect Review
The thread ID strategy affects checkpoint data integrity:

| Option | Pros | Cons |
|---|---|---|
| A. Use `uuid.uuid4()` suffix | Guaranteed unique | Loses human-readable structure |
| B. Accept `reviewer_id` parameter, include in thread_id | Semantic, readable | Requires caller to pass additional context |
| C. Use monotonic counter (thread-safe) | Sequential, readable | Needs shared state (module-level counter) |
| D. Use `time.time_ns()` (nanosecond precision) | Minimal code change | Still theoretically collidable on fast systems |

### Recommendation
Option B — the orchestrator already has `reviewer_id` (1 or 2). Pass it through to `run_sub_agent` and include in the thread_id: `f"{parent_session_id}-{role}-{reviewer_id}-{int(time.time())}"`.

### Decision Question
**What thread ID strategy should parallel sub-agents use to prevent checkpoint collisions — uuid, reviewer_id, counter, or nanosecond timestamp?**

---

## B-08: `_validate_review_file` — how robust should frontmatter validation be?

- **File:** `src/multi_agent/orchestrator.py:128-138`
- **Found by:** Both agents (BMAD 3-3#1.5, 3-4#8, 3-6#7 + Claude 3-3#3)
- **Severity:** LOW

### Current State
```python
return content.startswith("---")
```
Any file starting with `---` passes validation, even without a closing `---` delimiter, valid YAML, or required fields (`agent_role`, `task_id`, `timestamp`, `input_files`, `reviewer_id`).

### Why Architect Review
Validation robustness is a design trade-off:

| Option | Pros | Cons |
|---|---|---|
| A. Check opening AND closing `---` | Minimal, catches most malformed files | Still doesn't validate YAML content |
| B. Parse YAML and check required fields | Full validation per coding-standards.md | Adds `pyyaml` dependency, more code |
| C. Regex check for key fields in frontmatter | No new dependency, moderate validation | Fragile regex, not true YAML parsing |
| D. Keep current (current) | Simple, fast | Accepts garbage files |

### Recommendation
Option A as minimum viable improvement. Option B if `pyyaml` is already a dependency.

### Decision Question
**How thoroughly should review file frontmatter be validated — structural check only, or full YAML field validation?**

---

## B-09: No validation `fix-plan.md` exists before spawning Fix Dev

- **File:** `src/multi_agent/orchestrator.py:806`
- **Found by:** BMAD 3-4#9
- **Severity:** MEDIUM

### Current State
```python
graph.add_edge("architect_node", "fix_dev_node")  # unconditional
```
If the Architect Agent fails to write `fix-plan.md` (errors out, exceeds turn limit, writes wrong path), the Fix Dev Agent is spawned anyway. It reads a nonexistent or stale file.

### Why Architect Review
Pre-condition checking strategy affects graph structure:

| Option | Pros | Cons |
|---|---|---|
| A. Add conditional edge with file existence check | Fail-fast if plan missing | Another routing function, slightly more complex graph |
| B. Validate inside `fix_dev_node` at start | Simpler graph, node handles own pre-conditions | Late failure — sub-agent already spawned |
| C. Make `architect_node` return validation status | Source of truth validates its own output | Requires trusting LLM-generated status |
| D. Add intermediate validation node | Clean separation of concerns | Extra node in graph |

### Recommendation
Option A — add a `route_after_architect` function that checks `os.path.exists(FIX_PLAN_PATH)` and routes to `error_handler` if missing.

### Decision Question
**Should fix-plan.md existence be validated via graph routing (pre-condition), inside the fix_dev_node (self-check), or via a dedicated validation node?**

---

## B-10: `_run_bash` missing `cwd` parameter

- **File:** `src/multi_agent/orchestrator.py:148-153`
- **Found by:** BMAD 3-3#2.2
- **Severity:** MEDIUM

### Current State
```python
result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
```
No `cwd` parameter. Commands like `pytest tests/ -v`, `bash scripts/local_ci.sh` resolve relative paths against the process's current working directory. If the orchestrator is invoked from a parent directory, all paths break.

### Why Architect Review
The working directory strategy is cross-cutting:

| Option | Pros | Cons |
|---|---|---|
| A. Pass `cwd=project_root` from config/env | Explicit, portable | Needs a `PROJECT_ROOT` constant or config |
| B. Pass `cwd` from `OrchestratorState` | Per-invocation flexibility | State bloat for rarely-changing value |
| C. Resolve `cwd` from `__file__` location | Auto-detect, no config needed | Fragile if package is installed elsewhere |
| D. Document that CWD must be project root | No code change | Error-prone, easy to forget |

### Recommendation
Option A — add `PROJECT_ROOT` constant (derived from `__file__` or config) and pass `cwd=PROJECT_ROOT` to all `subprocess.run` calls.

### Decision Question
**Where should bash command execution get its working directory — config constant, state field, auto-detect from `__file__`, or rely on process CWD?**

---

## B-11: `check_same_thread=False` SQLite threading model

- **File:** `src/multi_agent/spawn.py:113`
- **Found by:** Claude 3-2#6
- **Severity:** MEDIUM

### Current State
```python
conn = sqlite3.connect(checkpoints_db, check_same_thread=False)
```
This disables Python's thread-safety check for SQLite connections. If LangGraph uses async execution or multiple threads internally, concurrent writes to the same connection can cause silent data corruption. The flag was likely added to avoid `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`.

### Why Architect Review
Threading model affects data integrity:

| Option | Pros | Cons |
|---|---|---|
| A. Keep flag, enable WAL mode for concurrent reads | Better concurrent performance | WAL mode doesn't protect concurrent writes on same connection |
| B. Remove flag, use connection-per-thread | Thread-safe by default | Need to restructure how SqliteSaver receives connections |
| C. Use `SqliteSaver.from_conn_string()` (manages own connections) | Framework handles threading | May not exist in current langgraph version |
| D. Use async checkpointer (`AsyncSqliteSaver`) | Native async support | Requires async graph execution |

### Recommendation
Investigate Option C first — if `SqliteSaver` supports connection string initialization, let the framework manage connection lifecycle and threading. This also resolves B-04 (connection leak).

### Decision Question
**Should SQLite checkpointing use `check_same_thread=False` with the current pattern, switch to framework-managed connections, or adopt a different checkpointer?**

---

## Summary

| ID | Issue | Severity | Key Decision |
|---|---|---|---|
| B-01 | Shared retry counters | HIGH | Separate counters per phase, or shared budget? |
| B-02 | No routing after failed reviews | HIGH | Halt, retry, or degrade? |
| B-07 | Thread ID collision | HIGH | UUID, reviewer_id, counter, or nanoseconds? |
| B-03 | Reviewer edit_file strategy | MEDIUM | Tool exclusion or restricted-returns-error? |
| B-04 | Double context injection | MEDIUM | Layer 1, Layer 2, or both? |
| B-05 | System prompt re-prepended | MEDIUM | Store in state, config, or initial messages? |
| B-06 | No success/failure signal | MEDIUM | Status field, exception, or message parsing? |
| B-09 | No fix-plan.md validation | MEDIUM | Graph routing, self-check, or validation node? |
| B-10 | Missing `cwd` in bash exec | MEDIUM | Config constant, state, or auto-detect? |
| B-11 | SQLite threading model | MEDIUM | Current pattern, framework-managed, or async? |
| B-08 | Review file validation depth | LOW | Structural only or full YAML parsing? |

# Epic 2 — Architect Review Needed

**Scope:** Category B issues ONLY — items requiring architectural decisions, where multiple valid approaches exist.
**Category A items** (clear fixes) are in `epic2-code-review-fix-plan.md`.
**Zero overlap** between the two files.

---

## Theme 1: Security Architecture

### B-01: search_files and list_files have no path sandbox validation

- **Files:** `src/tools/search.py:19-35` (list_files), `src/tools/search.py:39-73` (search_files)
- **Current state:** Both tools accept a `path` parameter and pass it directly to `Path.glob()` / `os.walk()` without any sandbox validation. A malicious path like `"/etc"` would access files outside the project root. Compare with `read_file` (`src/tools/file_ops.py:50`) which validates via `_validate_path()`.
- **Why architect review:** Multiple valid approaches exist, and this decision affects the security model for all tool execution. This is a pre-existing issue (not introduced by Epic 2) but was surfaced by the review.
- **Found by:** BMAD 2-4 #1.5, #1.6

| Option | Pros | Cons |
|--------|------|------|
| A. Add `_validate_path()` calls in each tool | Consistent with read_file/edit_file pattern | Must maintain validation in every new tool |
| B. Centralized path middleware before tool dispatch | Single enforcement point | Requires modifying ToolNode dispatch |
| C. OS-level sandbox (chroot/container) | Strongest guarantee | Heavier infra, may not work on Windows dev |

- **Recommendation:** Option A (consistent with existing pattern in file_ops.py)
- **Decision question:** Should all tools that accept path parameters use the same `_validate_path()` function from `file_ops.py`, and should it be extracted to a shared `src/tools/security.py` module?

---

### B-02: run_command uses shell=True with no command allowlisting

- **File:** `src/tools/bash.py:32`
- **Current state:** `subprocess.run(command, shell=True, cwd=project_root, ...)` — working directory is sandboxed but commands can escape via `cd /etc && cat passwd` or pipe to external processes. `project-context.md:125` says "sandbox all run_command tool execution" but only CWD is sandboxed.
- **Why architect review:** This is a fundamental security/capability tradeoff. Restricting commands too much limits the agent's ability to run tests, linters, and build tools. This also interacts with Epic 3+ orchestrator design.

| Option | Pros | Cons |
|--------|------|------|
| A. Command allowlist (pytest, ruff, mypy, git, etc.) | Strong security | Must maintain allowlist, blocks legitimate commands |
| B. Command denylist (no curl, wget, rm -rf, etc.) | Less restrictive | Incomplete, cat-and-mouse |
| C. Keep as-is with audit logging | Maximum flexibility | Relies on audit trail, no prevention |
| D. Drop `shell=True`, use argument list | Prevents shell injection/chaining | Agent can't use pipes, redirects, `&&` |

- **Recommendation:** Option A for production, Option C acceptable for MVP
- **Decision question:** What is the acceptable security boundary for agent shell access in MVP vs. production? Should Epic 3's orchestrator enforce stricter limits per role?

---

## Theme 2: Audit Logger Integration Design

### B-03: log_agent_done() is defined but never called in production

- **Files:** `src/logging/audit.py:86-88` (definition), `src/agent/nodes.py` (no call site)
- **Current state:** The method exists and is unit-tested, but no production code calls it. The `│  └─ Done` marker never appears in real audit logs, violating the Decision 6 tree format (AC #4).
- **Why architect review:** The "where" question has multiple valid answers with different implications for graph architecture:
- **Found by:** BMAD 2-2 #11, Claude 2-2 #1

| Option | Pros | Cons |
|--------|------|------|
| A. Call in `should_continue` when routing to END | Triggers on natural completion | `should_continue` is a routing function, not a node — side effects are unusual |
| B. Add a dedicated terminal node before END | Clean separation of concerns | Adds a node to the graph; changes graph topology |
| C. Call in `main.py` after `graph.invoke()` returns | Simple, no graph changes | Doesn't capture agent completion if graph errors; misses internal routing context |
| D. Call in `agent_node` when detecting no tool_calls | Agent knows it's "done" | Agent doesn't know routing outcome; could be wrong if error_handler fires |

- **Recommendation:** Option A (routing functions can have lightweight side effects like logging)
- **Decision question:** Where in the graph lifecycle should `log_agent_done()` be called, and should it be paired with the try/finally fix from A-02?

---

### B-04: log_bash() is defined but never called in production

- **Files:** `src/logging/audit.py:90-100` (definition), `src/agent/nodes.py:72-96` (tool_node — no bash detection)
- **Current state:** `log_bash()` exists and is unit-tested but never invoked. `tool_node` calls `log_tool_call()` uniformly for all tools including `run_command`. The `_script_count` is always 0, and bash calls use generic tool format instead of the Decision 6 bash format.
- **Why architect review:** Requires a detection strategy — how does the tool_node know a tool call is "bash" vs. a regular tool?
- **Found by:** BMAD 2-2 #12, Claude 2-2 #3

| Option | Pros | Cons |
|--------|------|------|
| A. Check tool_name == "run_command" in tool_node | Simple, direct | Fragile if bash tool name changes; hardcodes tool name |
| B. Tool metadata/tag system (tool.metadata["type"] = "bash") | Extensible, clean | Requires modifying tool definitions |
| C. Defer to multi-agent epic (log_bash for orchestrator scripts) | log_bash may be for orchestrator-level scripts, not tool calls | Leaves method unused for now |
| D. Remove log_bash() until needed | No dead code | May need to re-add later |

- **Recommendation:** Option A for now (simple detection), with a TODO to revisit for orchestrator-level bash
- **Decision question:** Is `log_bash()` intended for agent tool calls (`run_command`) or for orchestrator-level bash nodes (CI, git, tests)? This determines whether the fix belongs in `tool_node` or in the orchestrator.

---

### B-05: Summary line omits ${cost} from Decision 6 format

- **File:** `src/logging/audit.py:106-108`
- **Current state:** Summary line is `Total: {agents} agents, {scripts} scripts, {files} files touched`. Architecture Decision 6 specifies `Total: {agents} agents, {scripts} scripts, ${cost}, {files} files touched`. The story spec also omits cost, suggesting deliberate scoping.
- **Why architect review:** This is a spec-vs-spec conflict. Story 2-2 intentionally omitted cost, but AC #4 says "match Decision 6."
- **Found by:** BMAD 2-2 #13, Claude 2-2 #4

| Option | Pros | Cons |
|--------|------|------|
| A. Add `$0.00` placeholder | Satisfies Decision 6 format | Misleading if cost tracking isn't implemented |
| B. Add cost tracking (token counting) | Full Decision 6 compliance | Significant scope — requires API response parsing |
| C. Keep as-is, update Decision 6 to remove cost | Honest, no dead placeholders | Deviates from original architecture |
| D. Add `${cost}` field, populate in later epic | Satisfies format, defers implementation | Placeholder value until cost tracking exists |

- **Recommendation:** Option D (add field with `$-.--` placeholder, implement in Epic 5/6)
- **Decision question:** Should the audit logger include a cost placeholder now, or should Decision 6 be updated to reflect cost as a future addition?

---

### B-06: Tool call log format deviates from Decision 6

- **File:** `src/logging/audit.py:82-84`
- **Current state:** All tools logged as `│  ├─ {tool_name}: {file_path} ({result_prefix})` with `SUCCESS`/`ERROR`. Decision 6 shows different formats: `Read: {file}` (no parenthetical), `Edit: {file} ({description})` (description not SUCCESS/ERROR).
- **Why architect review:** Story spec redefined format as `({result_prefix})` for all tools. This is a story-spec-vs-architecture-spec conflict.
- **Found by:** BMAD 2-2 #14

| Option | Pros | Cons |
|--------|------|------|
| A. Keep story spec format (current) | Uniform, simpler code | Doesn't match Decision 6 exactly |
| B. Implement per-tool formats from Decision 6 | Matches architecture | More complex logging, harder to maintain |
| C. Update Decision 6 to match implementation | Single source of truth | Architecture doc reflects implementation rather than guiding it |

- **Recommendation:** Option A (current format is more useful — SUCCESS/ERROR is actionable)
- **Decision question:** Should the architecture Decision 6 format spec be updated to match the implemented format, or should the logger be modified to match Decision 6?

---

### B-07: agent_node uses retry_count == 1 as proxy for "first agent"

- **File:** `src/agent/nodes.py:66`
- **Current state:** `log_agent_start` fires only when `retry_count == 1`. In single-agent mode this works. In multi-agent mode, subsequent agents start with `retry_count > 1` and never log their start.
- **Why architect review:** This interacts with Epic 3 multi-agent design. The detection strategy for "new agent started" needs to work across agent transitions.
- **Found by:** Claude 2-2 #7

| Option | Pros | Cons |
|--------|------|------|
| A. Add `_agent_logged` flag to state | Explicit per-agent tracking | Adds state field |
| B. Track in audit logger (log_agent_start sets flag, log_agent_done clears) | No state changes | Requires B-03 (log_agent_done) to be resolved first |
| C. Defer to Epic 3 | Don't over-engineer for single-agent MVP | Leaves known limitation |

- **Recommendation:** Option C (defer — single-agent MVP doesn't hit this)
- **Decision question:** Should this be deferred to Epic 3, or fixed now to prevent technical debt accumulation?

---

### B-08: No integration test for audit logging in graph execution

- **File:** `tests/test_logging/test_audit.py` (missing tests)
- **Current state:** Unit tests verify AuditLogger in isolation. No test verifies that `agent_node` calls `log_agent_start()` or `tool_node` calls `log_tool_call()` during actual graph execution.
- **Why architect review:** The test content depends on decisions from B-03, B-04, and B-07. Writing the integration test before those decisions creates throwaway test code.
- **Found by:** BMAD 2-2 #16

| Option | Pros | Cons |
|--------|------|------|
| A. Write integration test now with current behavior | Documents current behavior | Test will need rewriting after B-03/B-04 |
| B. Defer until B-03/B-04 resolved | Test reflects final design | Leaves gap longer |
| C. Write test for what works (log_agent_start, log_tool_call) and TODO for rest | Partial coverage now | Mix of tested and untested paths |

- **Recommendation:** Option B (defer until audit integration design is finalized)
- **Decision question:** Should integration tests be written now for what works, or deferred until the audit logger integration decisions (B-03, B-04) are made?

---

## Theme 3: Application Architecture

### B-09: Module-level graph creation causes import-time side effects

- **File:** `src/main.py:35`
- **Current state:** `graph = create_agent()` at module level opens a real SQLite connection and creates the `checkpoints/` directory at import time. Any code that imports `src.main` (test discovery, IDE tooling, FastAPI auto-reload) triggers this.
- **Why architect review:** Fixing this changes the application initialization pattern.
- **Found by:** BMAD 2-1 #3

| Option | Pros | Cons |
|--------|------|------|
| A. Lazy initialization (create on first request) | No import side effects | Need thread-safe singleton pattern; slightly more complex |
| B. FastAPI lifespan event | Framework-native; clean startup/shutdown | CLI mode doesn't use FastAPI lifespan |
| C. Dependency injection (pass graph to routes) | Testable, explicit | More boilerplate; changes route signatures |
| D. Keep as-is | Simple | Tests and imports trigger DB creation |

- **Recommendation:** Option A (lazy singleton with `functools.lru_cache` or similar)
- **Decision question:** Should graph initialization be lazy (on first use) or explicit (at app startup via lifespan), and how should the CLI mode participate?

---

### B-10: SQLite connection opened but never closed

- **File:** `src/agent/graph.py:55-57`
- **Current state:** `sqlite3.connect()` returns a connection passed to `SqliteSaver`, but `create_agent()` returns only the compiled graph. No code path closes the connection. On repeated calls (e.g., tests), connections accumulate.
- **Why architect review:** The solution is coupled with B-09 (initialization pattern).
- **Found by:** BMAD 2-1 #2, Claude 2-1 #5

| Option | Pros | Cons |
|--------|------|------|
| A. Return (graph, conn) tuple, close on shutdown | Explicit cleanup | Changes return type of create_agent() |
| B. Context manager pattern (with create_agent() as graph) | Pythonic lifecycle | More complex usage |
| C. Store conn as graph attribute/metadata | Single return value | Relies on undocumented attribute |
| D. Accept leak for server process (single long-lived conn) | Simplest | Resource leak in tests; bad practice |

- **Recommendation:** Option A, paired with B-09's lazy initialization
- **Decision question:** Should `create_agent()` manage connection lifecycle, or should a higher-level application context own it?

---

### B-11: Relative paths for checkpoints depend on working directory

- **Files:** `src/main.py:32`, `src/agent/graph.py:19`
- **Current state:** `os.makedirs("checkpoints")` and `CHECKPOINTS_DB = "checkpoints/shipyard.db"` are relative. Running from a different CWD (Docker, systemd, IDE) creates files in the wrong location.
- **Why architect review:** Path resolution strategy affects deployment and CI environments.
- **Found by:** BMAD 2-1 #8

| Option | Pros | Cons |
|--------|------|------|
| A. Resolve relative to `__file__` (project root) | Works regardless of CWD | Assumes project structure |
| B. Environment variable `SHIPYARD_DATA_DIR` | Configurable per environment | Extra config to manage |
| C. XDG-compliant paths (`~/.local/share/shipyard/`) | Platform-standard | Moves data away from project |
| D. Keep relative, document CWD requirement | Simplest | Breaks in non-standard execution |

- **Recommendation:** Option B (env var with sensible default fallback to project root)
- **Decision question:** Should Shipyard use an environment variable for data paths, or resolve paths relative to the project root?

---

### B-12: CLI loop message accumulation semantics with LangGraph checkpointing

- **File:** `src/main.py:150-156`
- **Current state:** Each CLI iteration calls `graph.invoke({"messages": [HumanMessage(content=stripped)]}, config=config)` with only the new message. LangGraph's `MessagesState` uses `operator.add` reducer. Whether the new message appends to or replaces the checkpoint depends on LangGraph internals.
- **Why architect review:** If LangGraph replaces rather than appends, multi-turn CLI sessions lose history. This needs testing/verification.
- **Found by:** BMAD 2-4 #2.6

| Option | Pros | Cons |
|--------|------|------|
| A. Verify current behavior is correct (test multi-turn) | Confirms or denies the issue | May find it's already correct |
| B. Explicitly accumulate messages client-side | Guaranteed correct | Duplicates LangGraph's checkpointer role |
| C. Document as known limitation if broken | Honest | Poor user experience |

- **Recommendation:** Option A first (test it), then fix if needed
- **Decision question:** Has multi-turn CLI conversation been tested? Does LangGraph's SqliteSaver correctly accumulate messages when invoked with a single new message?

---

## Theme 4: Data Model / API Design

### B-13: model_tier metadata disconnected from actual model used

- **Files:** `src/multi_agent/roles.py:186` (writes metadata), `src/agent/nodes.py:43` (hardcodes model)
- **Current state:** `build_trace_config(model_tier="opus")` writes "opus" to trace metadata, but `agent_node` always uses `DEFAULT_MODEL = "claude-sonnet-4-6"` regardless. Traces can claim Opus was used when Sonnet was.
- **Why architect review:** Connecting model_tier to actual model selection is Epic 3 scope (role-based model tiers). Fixing it now could over-engineer the MVP.
- **Found by:** BMAD 2-1 #1

| Option | Pros | Cons |
|--------|------|------|
| A. Use MODEL_IDS[model_tier] in agent_node | Metadata matches reality | Requires passing model_tier through state; changes agent behavior |
| B. Hardcode model_tier="sonnet" in MVP callers | Metadata is accurate for MVP | Still disconnected in build_trace_config API |
| C. Defer to Epic 3 (multi-agent brings role-based models) | Avoids premature optimization | Trace metadata is misleading until then |

- **Recommendation:** Option C (defer — Epic 3 introduces role-based model selection naturally)
- **Decision question:** Is misleading model_tier metadata acceptable for MVP traces, or should callers be constrained to `model_tier="sonnet"` until Epic 3?

---

### B-14: task_id always equals session_id — not a meaningful identifier

- **Files:** `src/main.py:81`, `src/main.py:128`
- **Current state:** Both HTTP and CLI set `task_id=session_id` (a UUID). Architecture Pattern 6 shows `task_id: "story-42"` as the expected meaningful value. Filtering by task_id in LangSmith is useless when it's a UUID.
- **Why architect review:** Making task_id meaningful requires either user input or orchestrator assignment. This is an API/UX decision.
- **Found by:** BMAD 2-1 #10, Claude 2-1 #4

| Option | Pros | Cons |
|--------|------|------|
| A. Accept task_id in InstructRequest | Meaningful when provided | Optional field, still UUIDs when omitted |
| B. Derive from message content (first N chars) | Automatic | Fragile, not a stable identifier |
| C. Keep UUID for MVP, fix in orchestrator (Epic 3) | Orchestrator assigns story-42 naturally | MVP traces have low-value task_id |
| D. Default to "mvp-session" string literal | Better than UUID for filtering | Not unique per task |

- **Recommendation:** Option A (add optional `task_id` field to `InstructRequest`)
- **Decision question:** Should the `/instruct` API accept an optional `task_id` parameter, or should task_id remain internal until the orchestrator assigns it in Epic 3?

---

### B-15: No validation on empty session_id/task_id strings

- **Files:** `src/multi_agent/roles.py:149-156`, `src/agent/graph.py:60-67`
- **Current state:** `session_id` and `task_id` accept any string including `""`. An empty `thread_id` could cause unpredictable checkpointing behavior (collisions between sessions).
- **Why architect review:** Validation strategy depends on B-14 (what is task_id) and whether empty strings should generate defaults or raise errors.
- **Found by:** BMAD 2-1 #5, #6

| Option | Pros | Cons |
|--------|------|------|
| A. Raise ValueError on empty strings | Fail-loud, consistent with other validations | Callers must always provide non-empty values |
| B. Generate UUID default for empty session_id | Graceful fallback | Hides caller bugs |
| C. Validate in build_trace_config only | Single validation point | Callers of create_trace_config bypass |

- **Recommendation:** Option A (fail-loud, consistent with existing agent_role/model_tier validation)
- **Decision question:** Should empty `session_id` and `task_id` raise `ValueError` (consistent with other validations) or silently generate defaults?

---

### B-16: _extract_response silently drops non-dict content blocks

- **File:** `src/main.py:112-115`
- **Current state:** When `AIMessage.content` is a list, only `dict` blocks with a `"text"` key are processed. `thinking` blocks and other content types are silently discarded, potentially returning empty string when the model did produce useful output.
- **Why architect review:** Depends on whether extended thinking / other block types will be used.
- **Found by:** BMAD 2-1 #7

| Option | Pros | Cons |
|--------|------|------|
| A. Handle `thinking` blocks explicitly | Future-proof for extended thinking | Adds complexity for a feature not yet used |
| B. Log a warning for unrecognized block types | Visibility without crash | Still drops content |
| C. Keep as-is (MVP doesn't use thinking) | Simplest | Silent data loss if thinking is enabled |

- **Recommendation:** Option B (add warning log for dropped blocks)
- **Decision question:** Will Shipyard agents use extended thinking? If so, how should thinking blocks appear in the response?

---

## Theme 5: Orchestrator Design

### B-17: _ensure_reviews_dir() deletes all previous review files

- **File:** `src/multi_agent/orchestrator.py:64-82`
- **Current state:** Before each pipeline run, all files in `reviews/` (except `.gitkeep`) are deleted. If a user wants to compare reviews across runs, or if a concurrent pipeline runs, all prior review artifacts are lost.
- **Why architect review:** The cleanup strategy affects the orchestrator's audit trail and debugging capability.
- **Found by:** BMAD 2-4 #1.8

| Option | Pros | Cons |
|--------|------|------|
| A. Timestamped subdirectories (`reviews/{timestamp}/`) | Preserves history | Disk accumulation; more complex paths |
| B. Session-scoped directories (`reviews/{session_id}/`) | Natural grouping | Same accumulation concern |
| C. Keep current behavior + warn in logs | Simple; reviews/ is git-ignored | No history preserved |
| D. Archive old reviews before cleaning | Best of both | More complex file management |

- **Recommendation:** Option B (aligns with session-based architecture)
- **Decision question:** Should review artifacts be scoped to sessions (preserved), or should each pipeline run start clean?

---

### B-18: Retry count off-by-one: agent gets 49 turns, not 50

- **Files:** `src/agent/nodes.py:60` (increment), `src/agent/nodes.py:111` (check), `CODEAGENT.md:31,61`
- **Current state:** `agent_node` increments `retry_count` before `should_continue` checks `>= 50`. Sequence: turn 1 (count->1), ..., turn 49 (count->49) -> tool call -> turn 50 (count->50) -> should_continue fires "error". The agent gets 49 productive LLM calls, not 50 as documented.
- **Why architect review:** The fix depends on whether "50" means "50 LLM calls" or "50 loop iterations."
- **Found by:** BMAD 2-4 #2.1

| Option | Pros | Cons |
|--------|------|------|
| A. Change check to `> MAX_RETRIES` (50 LLM calls) | Matches documentation | Edge case: 51st retry_count value |
| B. Update docs to say 49 | Matches code | Arbitrary-looking number |
| C. Increment after should_continue | 50 LLM calls exactly | Requires refactoring increment location |
| D. Keep as-is, document as "up to 50 iterations including error" | Minimal change | Confusing semantics |

- **Recommendation:** Option A (change to `> MAX_RETRIES` for exactly 50 LLM calls)
- **Decision question:** Should the agent get exactly 50 LLM calls (change code), or should the documentation be updated to reflect the actual 49?

---

## Theme 6: Concurrency

### B-19: _active_loggers dict is not thread-safe for concurrent requests

- **File:** `src/logging/audit.py:13`
- **Current state:** `_active_loggers` is a plain `dict`. FastAPI's sync `/instruct` endpoint runs in a thread pool. Concurrent requests perform unsynchronized reads/writes. CPython's GIL makes individual dict operations atomic, but check-then-act patterns across `start_session`/`end_session`/`get_logger` are not atomic.
- **Why architect review:** For single-user MVP this is fine. The question is whether to add protection now or defer.
- **Found by:** BMAD 2-2 #3, Claude 2-2 #9

| Option | Pros | Cons |
|--------|------|------|
| A. Use `threading.Lock` | Thread-safe, explicit | Overhead for MVP single-user use |
| B. Use `contextvars.ContextVar` (per-request) | No global state, no locking | Requires passing context through LangGraph |
| C. Keep as-is for MVP | Simplest | Known race condition |

- **Recommendation:** Option C for MVP, revisit if/when concurrent use is supported
- **Decision question:** Is single-user MVP the confirmed scope, making thread safety deferrable? Or should we protect now?

---

## Summary of Required Decisions

| # | Theme | Key Question | Urgency |
|---|-------|-------------|---------|
| B-01 | Security | Path sandbox strategy for search tools | HIGH — security gap |
| B-02 | Security | Shell command restrictions for run_command | HIGH — security gap |
| B-03 | Audit | Where to call log_agent_done() | MEDIUM — spec violation |
| B-04 | Audit | How to detect/log bash tool calls | MEDIUM — spec violation |
| B-05 | Audit | Cost field: placeholder, defer, or remove from spec | LOW |
| B-06 | Audit | Tool log format: keep current or match Decision 6 | LOW |
| B-07 | Audit | Defer retry_count proxy fix to Epic 3? | LOW |
| B-08 | Audit | Defer integration tests until B-03/B-04 resolved? | LOW |
| B-09 | Architecture | Graph initialization: lazy vs. lifespan | MEDIUM |
| B-10 | Architecture | SQLite connection lifecycle ownership | MEDIUM |
| B-11 | Architecture | Data path resolution strategy | LOW |
| B-12 | Architecture | Verify CLI multi-turn message accumulation | MEDIUM |
| B-13 | Data Model | Defer model_tier accuracy to Epic 3? | LOW |
| B-14 | Data Model | Add task_id to InstructRequest API? | LOW |
| B-15 | Data Model | Validation strategy for empty strings | LOW |
| B-16 | Data Model | Handle non-dict content blocks? | LOW |
| B-17 | Orchestrator | Review artifact retention strategy | MEDIUM |
| B-18 | Orchestrator | Retry count: 49 or 50 LLM calls? | LOW |
| B-19 | Concurrency | Thread safety: now or defer? | LOW |

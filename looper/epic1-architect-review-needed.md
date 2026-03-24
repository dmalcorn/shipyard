# Epic 1 — Architect Review Needed

Category B issues only. Each item requires an architectural decision before implementation.

---

## B-01: Search/List Tools — Sandbox Enforcement Scope

### Files
- `src/tools/search.py:16` (`list_files`)
- `src/tools/search.py:35` (`search_files`)

### Current State
`list_files` and `search_files` accept arbitrary `path` parameters with no validation. An agent can glob `/etc/` or search any directory on the filesystem. `file_ops.py` has `_validate_path()` for sandboxing, but search tools don't use it.

### Why Architect Review
- `project-context.md` says "Sandbox all `run_command` tool execution" but doesn't explicitly mention read-only search tools
- Read-only access to the full filesystem may be intentional for agents that need to discover files
- Sandboxing search tools could limit legitimate use cases (e.g., searching installed packages, reading config files)

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Add `_validate_path` to search tools | Consistent sandbox, prevents data exfiltration | May break legitimate search use cases |
| B. Add optional `restrict_to_project` param | Flexible, default safe | Complexity, agents can bypass |
| C. Leave unsandboxed (document as intentional) | Simpler, agents have full read access | Security surface area for prompt injection |
| D. Sandbox by default, add allowlist dirs | Safe default with escape hatch | Config complexity |

### Recommendation
Option A for MVP consistency, with documented escape plan for Epic 2+.

### Decision Question
**Should read-only tools (list_files, search_files) be restricted to the project directory, or is full filesystem read access acceptable for agents?**

---

## B-02: SQLite Connection Lifecycle

### Files
- `src/agent/graph.py:53-55`

### Current State
`sqlite3.connect()` creates a connection that is never closed. No context manager, no shutdown hook. The connection lives for the process lifetime. On Windows, this can prevent file deletion and cause lock issues.

### Why Architect Review
Multiple valid approaches exist. The choice affects testability, resource management, and future multi-tenant support.

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Return connection alongside graph, caller manages lifecycle | Explicit, testable | API change, caller burden |
| B. FastAPI lifespan handler closes on shutdown | Clean for server mode | Doesn't help CLI mode |
| C. Use `SqliteSaver.from_conn_string()` (if available) | LangGraph manages lifecycle | May not be available in current version |
| D. Accept leak for MVP, add TODO | Zero work | Technical debt, Windows issues |

### Recommendation
Option B (FastAPI lifespan) for server mode + explicit close in CLI `finally` block.

### Decision Question
**How should the SQLite checkpoint connection lifecycle be managed across server and CLI modes?**

---

## B-03: ChatAnthropic Instance Creation Strategy

### Files
- `src/agent/nodes.py:42`

### Current State
Every call to `agent_node` creates a new `ChatAnthropic(model=DEFAULT_MODEL).bind_tools(tools)`. In a 50-turn session, this creates 50 client instances with 50 HTTP connection setups.

### Why Architect Review
Where to create and cache the model instance has architectural implications for:
- Tool binding (tools may change per role in multi-agent)
- API key rotation
- Model switching per role (Epic 2+)

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Module-level singleton | Simple, fast | Can't change model/tools per role |
| B. Per-session cache (store in state or closure) | Flexible for multi-agent | State schema change or closure complexity |
| C. Factory in `graph.py`, bind at compile time | Clean separation | Less flexible for runtime changes |
| D. Create per-turn (current) | Simplest code, no caching bugs | Performance cost, wasteful |

### Recommendation
Option C for Epic 1 (single-agent, fixed tools). Revisit for Epic 2 multi-agent.

### Decision Question
**Should the ChatAnthropic instance be created once at graph build time, or does multi-agent (Epic 2) require per-role model instances?**

---

## B-04: `context_files` Field + Layer 2 Integration

### Files
- `src/agent/state.py:15-26` (missing field)
- `src/agent/nodes.py:46` (dead access)
- `src/context/injection.py:78-96` (`inject_task_context` -- implemented but not wired)
- `src/agent/graph.py` (no Layer 2 call)

### Current State
`context_files` is not declared in `AgentState`. The `state.get("context_files")` call always returns `None`. `inject_task_context` (Layer 2) is implemented and tested in isolation but never called from the agent loop. AC #2 of Story 1-5 is functionally unmet.

### Why Architect Review
- Adding `context_files` to `AgentState` changes the state schema contract
- Where Layer 2 injection happens (in `agent_node`? as a pre-processing step? as a separate graph node?) is a design decision
- How context files get populated in state (caller provides them? read from task spec?) is undefined
- This connects to Epic 2's multi-agent orchestration (context may differ per agent)

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Add `context_files: list[str]` to AgentState, inject in `agent_node` | Simple, completes AC #2 | Mixes concerns in `agent_node` |
| B. Add as optional field, create separate preprocessing node | Clean separation | More graph complexity |
| C. Remove `context_files` access, make Layer 2 a caller responsibility | Clean node code | Caller must know about injection |
| D. Defer to Epic 2 multi-agent orchestration | Avoids premature design | AC #2 stays unmet |

### Recommendation
Option A for MVP -- add the field and wire `inject_task_context` into `agent_node`.

### Decision Question
**Should `context_files` be added to `AgentState` and Layer 2 injection wired into `agent_node` now, or deferred to the multi-agent orchestration in Epic 2?**

---

## B-05: Module-Level Side Effects

### Files
- `src/main.py:28` (`load_dotenv()`)
- `src/main.py:31` (`os.makedirs`)
- `src/main.py:34` (`graph = create_agent()`)

### Current State
Importing `src.main` triggers `.env` loading, directory creation, and SQLite connection setup. Tests must mock `graph` before any test function runs, and `load_dotenv` may load real API keys into the test environment.

### Why Architect Review
Restructuring initialization is an architectural change that affects the import chain, test setup, and deployment patterns.

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Lazy initialization with `functools.lru_cache` | Import-safe, cached after first use | Complexity, thread safety |
| B. Move all init into `main()` function | Clean imports, testable | Must restructure CLI/server entry |
| C. Use FastAPI lifespan for server, explicit init for CLI | Framework-correct pattern | Two init paths to maintain |
| D. Accept for MVP (current) | No work | Test fragility, env pollution |

### Recommendation
Option C -- it's the FastAPI-recommended pattern and naturally separates server vs CLI initialization.

### Decision Question
**Should module-level initialization be restructured to a FastAPI lifespan handler + explicit CLI init, or accepted as-is for MVP?**

---

## B-06: System Prompt Injection Lifecycle

### Files
- `src/agent/nodes.py:54-55`

### Current State
System prompt is only injected if `messages[0]` is not already a `SystemMessage`. On resumed sessions, the persisted `SystemMessage` from the previous invocation is kept even if `agent_role` has changed. The freshly built prompt is silently discarded.

### Why Architect Review
- System prompt management strategy affects multi-agent behavior (Epic 2)
- LangGraph may have built-in patterns for system prompts that should be adopted
- "Always overwrite" vs "check and update" vs "prepend on every turn" have different trade-offs for token cost and correctness

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Always replace `messages[0]` with fresh system prompt | Correct for role changes | Extra token cost if unchanged |
| B. Compare content, replace only if different | Efficient, correct | Comparison logic complexity |
| C. Use LangGraph's system message config (if available) | Framework-aligned | May not exist in current version |
| D. Accept current behavior (no role changes in Epic 1) | No work | Breaks in Epic 2 multi-agent |

### Recommendation
Option A -- correctness over optimization. Token cost of one system message per turn is negligible.

### Decision Question
**Should the system prompt be unconditionally replaced on every turn, or should the current "inject only if missing" behavior be kept?**

---

## B-07: Error Handling for `graph.invoke()` in Endpoints

### Files
- `src/main.py:82-85` (HTTP endpoint)
- `src/main.py:133-136` (CLI mode)

### Current State
No `try/except` around `graph.invoke()`. LLM API errors (429, 500, timeout), SQLite errors, and LangGraph internal errors propagate as unhandled HTTP 500 with raw stack traces, or as CLI crashes.

### Why Architect Review
- Error classification (retriable vs fatal) is a design decision
- Whether to use FastAPI exception handlers, middleware, or inline try/except
- What structured error response format to use
- Whether to add retry logic at the endpoint level

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Inline try/except with structured error response | Simple, localized | Duplicated in CLI and HTTP |
| B. FastAPI exception handler middleware | Centralized, clean | Only helps HTTP, not CLI |
| C. Wrapper function used by both HTTP and CLI | DRY, consistent | Abstraction for two callers |
| D. Accept raw errors (fail-loud) | "Fail-loud" compliant | Poor UX, leaks internals |

### Recommendation
Option C -- a shared wrapper that catches, logs, and returns structured errors.

### Decision Question
**What structured error response format should `graph.invoke()` failures use, and should retry logic be added for transient errors (rate limits)?**

---

## B-08: `AgentState` Required Fields Not Initialized

### Files
- `src/agent/state.py:22-26`
- `src/main.py:82-85`

### Current State
`AgentState` defines `task_id: str`, `retry_count: int`, `current_phase: str`, `agent_role: str`, `files_modified: list[str]` as required fields. But `graph.invoke()` only provides `{"messages": [...]}`. LangGraph may silently default these, or it may fail in edge cases.

### Why Architect Review
- Whether fields should have defaults in the TypedDict or be required
- How `task_id` and `agent_role` get populated (caller vs default vs orchestrator)
- This directly affects Epic 2 multi-agent orchestration

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Add defaults to all fields in `AgentState` | Works with minimal invoke input | Hides misconfiguration |
| B. Require callers to provide all fields | Explicit, catches errors | Verbose invoke calls |
| C. Use `NotRequired` (PEP 655) for optional fields | Type-safe optional fields | Requires Python 3.11+ (available since project targets 3.13) |
| D. Provide defaults in `main.py` invoke call | Explicit at call site | Duplicated if multiple callers |

### Recommendation
Option A with logging when defaults are used -- simplest path for MVP.

### Decision Question
**Should `AgentState` fields have defaults (accepting silent misconfiguration) or be required (forcing explicit initialization)?**

---

## B-09: Context File Path Traversal Risk

### Files
- `src/context/injection.py:22-29` (`_read_file_safe`)
- `src/context/injection.py:61-65` (`build_system_prompt`)
- `src/context/injection.py:88-94` (`inject_task_context`)

### Current State
Both `build_system_prompt` and `inject_task_context` accept arbitrary file paths in `context_files` and read them without validation. Paths like `../../.env` or `/etc/passwd` would be read and injected into the LLM prompt.

### Why Architect Review
- Context files may legitimately need to come from outside the project (e.g., shared coding standards, org-level configs)
- Validation strategy depends on trust model: who populates `context_files`?
- If the orchestrator (trusted code) populates it, validation may be unnecessary
- If the agent itself can set `context_files`, validation is critical

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Validate all paths against project root | Secure | May block legitimate cross-project files |
| B. Allowlist of permitted directories | Flexible security | Configuration complexity |
| C. No validation (trust orchestrator) | Simple | Vulnerable if agent can influence paths |
| D. Validate only in agent-facing code paths | Targeted security | Complex to maintain |

### Recommendation
Option A for MVP -- context files should come from the project directory.

### Decision Question
**Should context file paths be validated against the project root, and who is the trusted source that populates the `context_files` list?**

---

## B-10: Context File Size Limits

### Files
- `src/context/injection.py:24-26`

### Current State
`_read_file_safe` reads entire files with `f.read()` and no size cap. A multi-megabyte file injected into the system prompt could blow the context window or cause massive token costs.

### Why Architect Review
- What size limit is appropriate depends on the target model's context window
- Whether to truncate (and how) or reject large files is a UX decision
- The coding standards specify 5000-char truncation for tool output, but context injection has no equivalent

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Truncate at 5000 chars (match tool convention) | Consistent | May lose critical context |
| B. Truncate at a higher limit (e.g., 20000 chars) | More context for agents | Higher token cost |
| C. Warn but don't truncate | Full context available | Risk of context overflow |
| D. Per-layer limits (Layer 1: 5k, Layer 2: 10k) | Tuned to purpose | More configuration |

### Recommendation
Option B with a `(truncated)` note -- 20k gives meaningful context while preventing runaway costs.

### Decision Question
**What size limit should context file injection use, and should it match the 5000-char tool output limit or be different?**

---

## B-11: Runtime Path Resolution Strategy

### Files
- `src/main.py:31` (`os.makedirs("checkpoints", ...)`)
- `src/agent/graph.py:19` (`CHECKPOINTS_DB = "checkpoints/checkpoints.db"`)
- `src/context/injection.py:19` (`CODING_STANDARDS_PATH = "coding-standards.md"`)
- `src/tools/file_ops.py:17` (`_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent`)

### Current State
The codebase uses three different path resolution strategies: relative to CWD, relative to `__file__`, and hardcoded strings. If the process is started from a directory other than the project root, relative paths break.

### Why Architect Review
- Cross-cutting concern affecting multiple modules
- Docker WORKDIR, test runners, and IDE run configs all affect CWD
- Need a single, canonical "project root" determination strategy

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Use `Path(__file__).resolve()` everywhere (relative to module location) | Works regardless of CWD | Breaks if installed as package |
| B. Environment variable `SHIPYARD_PROJECT_ROOT` | Explicit, Docker-friendly | Must be set everywhere |
| C. Central `config.py` that exports `PROJECT_ROOT` | Single source of truth | Import dependency |
| D. Require CWD = project root (current implicit assumption) | Simple | Fragile, undocumented |

### Recommendation
Option C -- a `src/config.py` that exports `PROJECT_ROOT = Path(__file__).resolve().parent.parent` with optional env var override.

### Decision Question
**Should the project adopt a central `PROJECT_ROOT` constant, and should it support env var override for Docker/CI?**

---

## B-12: `should_continue` Retry Check vs Natural End

### Files
- `src/agent/nodes.py:65-76`

### Current State
`should_continue` checks `retry_count >= MAX_RETRIES` BEFORE checking tool calls. At exactly turn 50, even if the LLM returned a final answer with no tool calls, the function returns `"error"` instead of `"end"`. The agent's valid final response is discarded.

### Why Architect Review
- "Exceeds 50 turns" is ambiguous -- does it mean the cap triggers at 50 or 51?
- The retry check should arguably only block continuation to tools, not block a natural end
- Reordering the checks changes the semantic contract

### Options

| Option | Pros | Cons |
|--------|------|------|
| A. Check tool calls first, then retry limit | Preserves final answer | Allows one extra turn |
| B. Keep current order but change to `> MAX_RETRIES` | 50 full turns, error at 51 | Off-by-one confusion |
| C. Only apply retry check to "tools" routing | Most correct semantics | Slightly more complex logic |
| D. Keep current behavior | Simple, conservative | Discards valid final answers at limit |

### Recommendation
Option C -- the retry limit should only prevent further tool calls, not block a natural end.

### Decision Question
**Should the retry limit only prevent further tool calls (allowing a natural end at the limit), or should it unconditionally terminate?**

---

## B-13: Default Agent Role Security

### Files
- `src/agent/nodes.py:45`

### Current State
`state.get("agent_role", "dev")` defaults to "dev" if no role is set. The "dev" role has full write permissions -- the most privileged role.

### Why Architect Review
In a multi-agent system, defaulting to the most privileged role is a security concern. Whether to fail loudly on missing role or default gracefully is a trust model decision.

### Decision Question
**Should a missing `agent_role` default to "dev" (most privileged), raise an error, or default to a least-privileged role?**

---

## B-14: Cross-Module Dependency Direction

### Files
- `src/agent/graph.py:17` (imports from `src.multi_agent.roles`)

### Current State
The core agent module (`src/agent/`) depends on the multi-agent module (`src/multi_agent/`). Multi-agent is Epic 3 scope.

### Why Architect Review
Module dependency direction affects future maintainability. Core modules should not depend on extension modules.

### Decision Question
**Should `create_trace_config` be moved from `src/multi_agent/roles.py` to `src/agent/graph.py`, or is the current dependency direction acceptable?**

---

## B-15: `git_snapshot.sh` Staging Strategy

### Files
- `scripts/git_snapshot.sh:11`

### Current State
`git add -A` stages everything. In an agent pipeline with no human review gate, this could commit sensitive files if `.gitignore` is incomplete.

### Why Architect Review
The script is designed for automated agent use. The risk profile differs from manual commits.

### Decision Question
**Should `git_snapshot.sh` use `git add -A` (current) or use selective staging (e.g., `git add src/ tests/ scripts/` with an explicit allowlist)?**

---

## B-16: Missing Session Resumption Test

### Files
- `tests/test_agent/test_graph.py`

### Current State
AC #4 says "the session can be resumed with the same `thread_id`." No test verifies that state persists and can be resumed.

### Why Architect Review
Testing session resumption requires understanding LangGraph's persistence model and may need a real SQLite DB in tests (vs. mocks).

### Decision Question
**Should session resumption tests use a real SQLite checkpointer (integration test) or mock the persistence layer (unit test)?**

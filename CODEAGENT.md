# CODEAGENT.md — Shipyard

## Agent Architecture (MVP)

### Overview

Shipyard is an autonomous coding agent built on **LangGraph** (Python) with **Claude** via the Anthropic SDK (`langchain-anthropic`). It runs as a persistent process — either a FastAPI server (`POST /instruct`) or an interactive CLI loop — accepting instructions continuously without restarting. State is checkpointed to SQLite after every graph node, enabling session resumption across restarts.

### Core Loop Design

The agent uses a custom **`StateGraph`** with two primary nodes in a ReAct (Reason + Act) pattern:

```
START → agent_node → should_continue → tool_node → agent_node → ... → END
```

- **`agent_node`**: Calls Claude with the system prompt + accumulated messages. Returns an AI message that may contain tool calls.
- **`tool_node`**: Executes all tool calls from the last AI message. Returns `ToolMessage` results.
- **`should_continue`** (conditional edge): If the AI message contains `tool_calls`, route to `tool_node`. Otherwise, route to `END`.

The loop continues until Claude responds without requesting any tool calls — meaning it has completed the task or is reporting a final answer.

### State Schema

```python
class AgentState(MessagesState):
    task_id: str                                    # Unique task identifier
    retry_count: int                                # Current retry count for circuit breaking
    current_phase: str                              # "test" | "dev" | "review" | "architect" | "fix" | "ci"
    agent_role: str                                 # "dev" | "test" | "reviewer" | "architect" | "fix_dev"
    files_modified: Annotated[list[str], operator.add]  # Accumulated list of modified file paths
```

State fields beyond `messages` enable conditional routing (e.g., `retry_count > 3` → error handler), trace metadata, and audit logging without parsing message history.

### Entry and Exit Conditions

**Entry (normal run):**
- User sends instruction via `POST /instruct` or CLI input
- `AgentState` is initialized with the instruction as a `HumanMessage`
- Config includes `thread_id` for session persistence and metadata for tracing

**Exit (normal):**
- Claude responds without tool calls → graph reaches `END`
- Response returned to user

**Exit (error):**
- Global turn cap (50 LLM turns) exceeded → error handler logs report, halts task
- Per-operation retry limits exceeded (3 edit retries, 5 test cycles, 3 CI failures) → error handler escalates to user
- Error handler produces a failure report and surfaces it for human intervention

### Persistence

- **Checkpointer:** `SqliteSaver` from `langgraph-checkpoint-sqlite`
- **Granularity:** State persisted after every node execution
- **Session resumption:** Same `thread_id` in config restores full conversation history and state
- **New session:** Different `thread_id` starts fresh

### Tool Definitions

All tools follow a consistent contract: string parameters in, string result out. Success returns start with `SUCCESS:`, errors start with `ERROR:` with a recovery hint.

| Tool | Description | Parameters |
|---|---|---|
| `read_file` | Read file contents | `file_path: str` |
| `edit_file` | Exact string replacement (surgical edit) | `file_path: str, old_string: str, new_string: str` |
| `write_file` | Create or overwrite a file | `file_path: str, content: str` |
| `list_files` | Glob pattern matching in a directory | `directory: str, pattern: str` |
| `search_files` | Regex search across file contents | `directory: str, regex_pattern: str` |
| `run_command` | Execute a shell command with timeout | `command: str` |

### Context Injection

Three-layer system to manage token cost while ensuring agents have the context they need:

- **Layer 1 (Always Present):** Agent role description, project conventions, orchestration guidance — injected as the system prompt at agent start. Small footprint (<3K tokens).
- **Layer 2 (Task-Specific):** Task description, relevant file paths, prior agent output files (e.g., review files, fix plans) — injected with the task assignment as part of the user message.
- **Layer 3 (On-Demand):** Agent uses `read_file`, `list_files`, and `search_files` tools to explore the codebase during execution. Unbounded but governed by the agent's judgment and context window limits.

### Observability

- **LangSmith auto-tracing:** Activated via environment variables (`LANGCHAIN_TRACING_V2=true`). Every node execution, LLM call, tool call, and conditional edge decision is traced automatically with zero custom code.
- **Custom metadata:** Every agent invocation includes `agent_role`, `task_id`, `model_tier`, `phase`, and `parent_session` in the config metadata for filtering and linking traces.
- **Markdown audit log:** Local `logs/session-{id}.md` files provide a human-readable record of each session — agent actions, tool calls, results, and costs in a tree-style format.

---

## File Editing Strategy (MVP)

### Mechanism: Anchor-Based Exact String Replacement

The `edit_file` tool performs surgical edits using exact string matching:

```
edit_file(file_path, old_string, new_string)
```

1. Read the file contents
2. Count occurrences of `old_string` in the file
3. If count == 0 → return `ERROR: old_string not found. Re-read the file to get current contents.`
4. If count > 1 → return `ERROR: old_string found {count} times. Provide more surrounding context to make the match unique.`
5. If count == 1 → replace `old_string` with `new_string`, write the file, return `SUCCESS`

### Why This Strategy

- **Fail-loud:** No fuzzy matching. Edits either succeed exactly or fail with a diagnostic error. Silent corruption is impossible.
- **Robust to line drift:** Unlike line-range replacement, adding/removing lines above the target doesn't break subsequent edits.
- **Language-agnostic:** No parser needed per language (unlike AST-based editing).
- **LLM-native:** Claude produces exact string matches more reliably than unified diffs, which require precise hunk headers.

### What Happens When It Gets the Location Wrong

Claude's trained self-correction behavior handles this:

1. **No match found (stale context):** Edit tool returns error → Claude re-reads the file to refresh its view of current contents → retries with accurate `old_string`
2. **Non-unique match:** Edit tool returns error with match count → Claude provides more surrounding context to disambiguate → retries with a longer, unique `old_string`
3. **No match found (hallucinated content):** Edit tool returns error → Claude re-reads the file → discovers actual content differs from what it assumed → retries with real content

### Retry Limits

- 3 consecutive edit failures on the same target → force a complete file re-read and fresh approach
- These per-edit retries count toward the global 50-turn cap

### Recovery Layers

1. **Layer 1 — Claude self-correction:** Edit tool fails loudly → Claude re-reads and retries (zero implementation cost, always active)
2. **Layer 2 — Post-edit validation:** After successful edits, lint (ruff) and type check (mypy) run via bash. New errors are fed back to the agent for correction.
3. **Layer 3 — Git snapshot rollback:** Before significant edit sequences, a git commit snapshot is created. If downstream review flags unfixable problems, the Architect can direct a rollback.

---

## Multi-Agent Design (MVP)

### Orchestration Model

**Hybrid: Subgraphs (sequential pipeline) + `Send` API (parallel review)**

Each agent role is a compiled `StateGraph` subgraph. A parent orchestrator graph invokes them as nodes, transforming state at boundaries.

### How Agents Communicate

**Filesystem is the coordination primitive.** Agents do not share message history or memory. Instead:

- Each agent writes its output to designated files (test files, source code, review files, fix plans)
- Downstream agents read those files as input via Layer 2 context injection
- No automatic merging — the Architect agent reads all upstream outputs and makes deliberate decisions about what to incorporate

### Agent Roles and Tool Access

| Role | Model Tier | Can Read | Can Write | Tools |
|---|---|---|---|---|
| Dev Agent | Sonnet | All files | Source files | read, edit, write, list, search, bash |
| Test Agent | Sonnet | All files | Test files only | read, edit, write, list, search, bash |
| Review Agent | Sonnet | All files | `reviews/review-agent-{n}.md` only | read, list, search, write (path-restricted) |
| Architect Agent | Opus | Review files, source | `fix-plan.md` only | read, list, search, write (path-restricted) |
| Fix Dev Agent | Sonnet | All files + fix plan | Source files | read, edit, write, list, search, bash |

### MVP Coordination (2 agents minimum)

Two agents as subgraph nodes in a parent `StateGraph`:

```
START → dev_agent → review_agent → END
```

Dev Agent writes code, Review Agent analyzes it and writes a review file. This satisfies the PRD's MVP requirement of "spawn and coordinate at least two agents."

### Full Pipeline (Early Submission)

```
START → test_agent → dev_agent → bash(CI) → bash(git snapshot)
      → Send(reviewer_1, reviewer_2) → architect_agent
      → fix_dev_agent → bash(CI) → bash(system tests)
      → bash(final CI) → bash(git push) → END
```

- `Send` API spawns 2 review agents concurrently — results merge via `Annotated[list, operator.add]` reducer
- Bash nodes handle deterministic tasks (CI, git, test execution) to save LLM tokens
- The same `StateGraph` from MVP grows to this pipeline by adding nodes and edges — no refactoring required

### How Outputs Are Merged

There is no automatic merge. The Architect Agent:
1. Reads both review files (`reviews/review-agent-1.md`, `reviews/review-agent-2.md`)
2. Evaluates each finding — decides which are genuine issues vs. acceptable
3. Produces a fix plan file (`fix-plan.md`) with specific, actionable instructions
4. A fresh Fix Dev Agent executes the approved fixes

This ensures a qualified agent reviews before any changes are applied, preventing blind auto-merging.

---

## Trace Links (MVP)

_Populated after running the agent:_

- Trace 1 (normal run):
- Trace 2 (different execution path — error, branching condition, or different task type):

---

## Architecture Decisions (Final Submission)

_To be completed for Final Submission. Source: [architecture.md](_bmad-output/planning-artifacts/architecture.md)_

Key decisions documented there:
1. Custom `StateGraph` from day one (no `create_react_agent` refactoring)
2. Hybrid multi-agent: Subgraphs + `Send` API
3. Extended `AgentState` schema with `task_id`, `retry_count`, `current_phase`
4. Dual retry limits: global 50-turn cap + per-operation counters
5. Shared working directory with role-based write restrictions
6. Markdown audit logs (human-readable, deliverable-ready)

---

## Ship Rebuild Log (Final Submission)

_To be completed during Ship app rebuild._

---

## Comparative Analysis (Final Submission)

_To be completed after Ship app rebuild. All seven sections required:_

1. Executive Summary
2. Architectural Comparison
3. Performance Benchmarks
4. Shortcomings
5. Advances
6. Trade-off Analysis
7. If You Built It Again

---

## Cost Analysis (Final Submission)

_To be completed. Track actual spend during development._

### Development and Testing Costs
- Claude API costs (input/output token breakdown):
- Number of agent invocations:
- Total development spend:

### Production Cost Projections

| Scale | Monthly Cost |
|---|---|
| 100 Users | $ /month |
| 1,000 Users | $ /month |
| 10,000 Users | $ /month |

_Assumptions: TBD based on actual usage data._

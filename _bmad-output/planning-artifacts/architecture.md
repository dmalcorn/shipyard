---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
status: complete
completedAt: '2026-03-23'
inputDocuments:
  - _bmad-output/planning-artifacts/product-brief-shipyard-2026-03-23.md
  - _bmad-output/planning-artifacts/research/technical-langgraph-agent-patterns-research-2026-03-23.md
  - gauntlet_docs/PRESEARCH.md
  - gauntlet_docs/shipyard_prd.pdf
workflowType: 'architecture'
project_name: 'shipyard'
user_name: 'Diane'
date: '2026-03-23'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**
- FR1: Persistent agent loop — FastAPI server or CLI loop accepting instructions continuously without restart, with LangGraph state checkpointing (SQLite) for session persistence across restarts
- FR2: Surgical file editing — `edit_file(path, old_string, new_string)` with exact string matching. Fails loudly on no-match or non-unique match. No fuzzy fallback. Read-before-edit enforced.
- FR3: Context injection — 3-layer system: Layer 1 (always-present role/conventions in system prompt), Layer 2 (task-specific files passed per instruction), Layer 3 (on-demand via Read/Grep/Glob tools)
- FR4: Multi-agent coordination — file-based communication, no shared memory. Minimum 2 agents for MVP; full pipeline (Test → Dev → 2 Review → Architect → Fix Dev) for Early Submission
- FR5: LangSmith tracing — zero-config auto-tracing via environment variables. Every node, LLM call, tool call traced. Custom metadata tags for agent role, task ID, model used
- FR6: Tool suite — Read, Edit, Write, Glob, Grep, Bash (plus sub-agent spawn for multi-agent). Review agents get read-only subset.
- FR7: Ship app rebuild — agent rebuilds Ship from scratch as integration test (Early Submission)
- FR8: CODEAGENT.md — Agent Architecture + File Editing Strategy sections for MVP; full document for Final

**Non-Functional Requirements:**
- NFR1: Edit reliability — >90% first-attempt surgical edit success rate (measured via LangSmith trace: edit calls vs retries)
- NFR2: Loop stability — 30+ minutes continuous operation without crash
- NFR3: Trace completeness — every agent action visible and linkable in LangSmith
- NFR4: Fail-loud semantics — edits must fail explicitly, never silently corrupt
- NFR5: Token cost awareness — model routing (Haiku for reads/search, Sonnet for coding/review, Opus for Architect decisions), no hard budget cap but cost tracked for analysis deliverable
- NFR6: Reproducibility — another engineer can clone, set env vars, and run locally in <10 minutes

**Scale & Complexity:**
- Primary domain: Agent infrastructure / developer tooling (Python)
- Complexity level: High
- Estimated architectural components: 8 (FastAPI server, LangGraph core loop, tool executor, context injector, agent spawner, checkpoint store, audit logger, CI scripts)

### Technical Constraints & Dependencies

- **LangGraph mandatory** — only practical choice given LangSmith tracing requirement and one-week timeline
- **Claude via Anthropic SDK** — required by PRD; model routing across Haiku 4.5 / Sonnet 4.6 / Opus 4.6
- **Python 3.13+** — LangGraph Python ecosystem is most mature
- **Docker** — container is the deployment unit (local for MVP, Railway for Final)
- **SQLite checkpointing** — lightweight persistence for MVP, upgradeable to Postgres later
- **No GitHub Actions** — all CI runs locally via bash scripts to conserve quota

### Cross-Cutting Concerns Identified

1. **Token cost management** — touches every agent invocation. Model routing decisions (which tier for which task) affect both quality and cost. Opus context must be kept minimal.
2. **Context window pressure** — long sessions accumulate message history linearly. Compaction strategy needed but triggers extra LLM calls. Layered injection is the mitigation.
3. **Error recovery** — spans all components. Three layers: (1) Claude self-correction on edit failure, (2) lint/test validation nodes after edits, (3) git snapshot rollback for catastrophic review findings.
4. **Filesystem as coordination primitive** — all inter-agent communication via files. Defines how agents share work, how reviews are collected, how fix plans are transmitted. Must be consistent across all agent types.
5. **Observability** — LangSmith auto-tracing plus custom metadata tags plus local file-based audit log. Three layers to ensure traces survive regardless of LangSmith availability.
6. **MVP vs Full Pipeline phasing** — architecture must support minimal 2-agent coordination for Tuesday while being extensible to the full TDD pipeline by Thursday without refactoring the core graph.

## Starter Template Evaluation

### Primary Technology Domain

Agent infrastructure / developer tooling (Python) — this is not a web application, mobile app, or API service. It is a standalone autonomous coding agent that runs as a persistent process.

### Technical Preferences (Pre-Established)

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.13+ | LangGraph Python ecosystem is most mature; more examples and better LangSmith integration than JS |
| Agent Framework | LangGraph | Mandatory — only practical choice given LangSmith tracing requirement |
| LLM Integration | `langchain-anthropic` (ChatAnthropic) | Required by PRD; provides Claude tool-use via LangGraph |
| Server | FastAPI | Lightweight, async, well-suited for agent instruction endpoint |
| Persistence | SQLite via `langgraph-checkpoint-sqlite` | Zero-config, file-based, upgradeable to Postgres later |
| Containerization | Docker + docker-compose | Portable between local dev and Railway deployment |
| Tracing | LangSmith (auto via env vars) | Zero custom code; traces every node, LLM call, tool call |
| Package Management | pip + `requirements.txt` (or `pyproject.toml`) | Standard Python; no need for Poetry/PDM complexity |

### Starter Options Considered

1. **Manual scaffold** — Hand-build project structure with precise control over layout, dependencies, and configuration. No unnecessary abstractions.
2. **`create_react_agent` as MVP core** — LangGraph prebuilt function that replaces full graph setup with one call. Good for getting the core loop running fast, then refactor to custom `StateGraph` for multi-agent.
3. **`langgraph new` CLI** — Official LangGraph project generator. Opinionated structure may conflict with multi-agent topology needs.

### Selected Approach: Manual Scaffold + `create_react_agent` MVP Core

**Rationale:** The project structure is simple enough (8 components) that a template adds no value. Manual scaffolding gives precise control over the directory layout and avoids inheriting opinions that need to be undone. The `create_react_agent` prebuilt is used as the initial agent core — it handles the ReAct loop, tool binding, and checkpointing in one call — then gets refactored to a custom `StateGraph` when multi-agent coordination is added.

**Initialization Commands:**

```bash
mkdir shipyard && cd shipyard
python -m venv .venv && source .venv/bin/activate
pip install langgraph langchain-anthropic langgraph-checkpoint-sqlite python-dotenv fastapi uvicorn
```

**Project Structure (Target):**

```
shipyard/
├── src/
│   ├── __init__.py
│   ├── main.py              # FastAPI server + CLI entry point
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py          # LangGraph graph definition (core loop)
│   │   ├── prompts.py        # System prompts and context templates
│   │   └── state.py          # Custom state schema
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── file_ops.py       # read_file, edit_file, write_file
│   │   ├── search.py         # glob, grep
│   │   └── bash.py           # run_command
│   ├── multi_agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py   # Parent graph for multi-agent coordination
│   │   ├── agents.py         # Agent role definitions (Dev, Test, Review, Architect)
│   │   └── spawn.py          # Sub-agent spawning logic
│   └── context/
│       ├── __init__.py
│       └── injection.py      # Context layer management
├── scripts/
│   └── local_ci.sh           # Local CI bash script (lint, type check, test)
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pyproject.toml
└── CODEAGENT.md
```

**Architectural Decisions Provided by This Approach:**

- **Language & Runtime:** Python 3.13+, no TypeScript
- **Build Tooling:** pip for dependencies, no complex build step (Python is interpreted)
- **Testing Framework:** pytest (standard Python, added when Test Agent work begins)
- **Code Organization:** `src/` layout with domain-based modules (agent, tools, multi_agent, context)
- **Development Experience:** `uvicorn --reload` for FastAPI hot reloading, `.env` for secrets, SQLite file for persistence (no database server needed)

**Note:** Project initialization using these commands should be the first implementation story.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
1. Graph topology: Custom `StateGraph` from day one (no `create_react_agent` → refactor path)
2. Multi-agent pattern: Hybrid — Subgraphs for sequential pipeline + `Send` API for parallel review
3. Max retries: Global turn cap (50) + per-operation retry limits (3 edit retries, 5 test cycles)

**Important Decisions (Shape Architecture):**
4. Agent state schema: Extended — `task_id`, `retry_count`, `current_phase` beyond `MessagesState`
5. Working directory: Shared with role-based write restrictions
6. Audit log: Markdown format, human-readable, feeds deliverables directly

**Deferred Decisions (Post-MVP):**
- Context compaction strategy (needed when sessions exceed context window — not an MVP concern)
- Postgres migration from SQLite (only if concurrent sessions needed in production)
- Agent nesting depth (sub-agents spawning sub-agents — defer until full pipeline proves it's needed)

### Decision 1: Graph Topology

| Aspect | Decision |
|---|---|
| Choice | Custom `StateGraph` from day one |
| Rationale | 2-node `StateGraph` (agent + tools) is nearly identical code to `create_react_agent` but avoids mid-week refactoring. The same graph grows organically from single-agent MVP to multi-agent pipeline by adding nodes and edges. |
| Affects | Core loop, all agent definitions, multi-agent coordination |

### Decision 2: Multi-Agent Coordination Pattern

| Aspect | Decision |
|---|---|
| Choice | Hybrid: Subgraphs (sequential) + `Send` API (parallel review) |
| Rationale | The pipeline is inherently sequential (Test → Dev → CI → Review → Architect → Fix Dev → CI → Push) except for the parallel review step where 2 independent reviewers analyze the same code. Subgraphs model the sequential flow naturally; `Send` API models the fan-out/fan-in review step. |
| MVP scope | 2 agents as subgraph nodes in a parent `StateGraph` (e.g., Dev + Review) |
| Full pipeline | Test → Dev → `Send`(Reviewer1, Reviewer2) → Architect → Fix Dev |
| Affects | `multi_agent/orchestrator.py`, agent spawning, state transformation between subgraphs |

### Decision 3: Agent State Schema

| Aspect | Decision |
|---|---|
| Choice | Extended state beyond `MessagesState` |
| Fields | `messages` (inherited), `task_id` (str), `retry_count` (int), `current_phase` (str enum), `agent_role` (str), `files_modified` (list[str]) |
| Rationale | Enables conditional routing in the graph (e.g., retry_count > max → error handler), makes traces self-documenting, and provides metadata for LangSmith custom tags without parsing message history |
| Affects | `agent/state.py`, all graph node functions, conditional edge logic |

```python
# src/agent/state.py
from typing import Literal
from typing_extensions import TypedDict, Annotated
from langgraph.graph import MessagesState
import operator

class AgentState(MessagesState):
    task_id: str
    retry_count: int
    current_phase: str  # "test", "dev", "review", "architect", "fix", "ci"
    agent_role: str     # "dev", "test", "reviewer", "architect"
    files_modified: Annotated[list[str], operator.add]
```

### Decision 4: Retry Limits and Circuit Breaking

| Aspect | Decision |
|---|---|
| Choice | Dual limits — global turn cap + per-operation counters |
| Global cap | 50 LLM turns per task invocation |
| Edit retries | 3 consecutive failures on the same edit → force re-read and fresh approach |
| Test cycles | 5 test-fail → fix cycles → escalate to error handler |
| CI failures | 3 CI fix cycles → escalate to error handler |
| Error handler | Logs failure report, halts task, surfaces to user for intervention |
| Rationale | Global cap prevents runaway cost. Per-operation limits catch specific doom loops early. Both are needed because a global cap alone won't catch a 40-turn edit loop that stays under 50 total. |
| Affects | Conditional edges in graph, `retry_count` state field, error handler node |

### Decision 5: Working Directory and Role Isolation

| Aspect | Decision |
|---|---|
| Choice | Shared directory with role-based write restrictions |
| Dev Agent | Full access: read, edit, write source files; run commands |
| Test Agent | Write tests only; read source for reference; run test commands |
| Review Agents | Read-only on source + tests; write ONLY to designated review files (`reviews/review-agent-{n}.md`) |
| Architect Agent | Read review files; write fix plan (`fix-plan.md`); no source edits |
| Fix Dev Agent | Read fix plan; edit source files; run tests and CI |
| Enforcement | Tool subset per agent role — review agents receive `[read_file, list_files, search_files, write_file]` where `write_file` is path-restricted to `reviews/` directory |
| Rationale | Avoids the complexity of directory copies while preventing reviewers from editing source (the "fix it while reviewing" anti-pattern). File-based communication is already the coordination primitive. |
| Affects | Tool binding per agent role in `multi_agent/agents.py`, tool definitions with path validation |

### Decision 6: Audit Log Format

| Aspect | Decision |
|---|---|
| Choice | Markdown format — human-readable, deliverable-ready |
| File | `logs/session-{session_id}.md` |
| Rationale | Directly feeds the AI Development Log and Trace Links deliverables. LangSmith already provides machine-parseable data; duplicating that in JSON locally adds no value. |
| Affects | Audit logger component, session lifecycle |

**Format:**
```
[Session {id}] {timestamp} — Task: "{description}"
│
├─ [{Agent Role} - {Model}] Started
│  ├─ Read: {file}
│  ├─ Edit: {file} ({description})
│  └─ Done
│
├─ [Bash] {script_name}
│  └─ {result}
│
└─ [Session Complete] Total: {agents} agents, {scripts} scripts, ${cost}, {files} files touched
```

### Decision Impact Analysis

**Implementation Sequence:**
1. Define `AgentState` schema (Decision 3) — foundation for everything
2. Build custom `StateGraph` with 2 nodes (Decision 1) — core loop
3. Add retry logic via conditional edges (Decision 4) — safety rails
4. Wire tool subsets per role (Decision 5) — preparation for multi-agent
5. Add audit logger (Decision 6) — observability from the start
6. Expand to multi-agent with subgraphs + `Send` (Decision 2) — Early Submission

**Cross-Component Dependencies:**
- Decision 1 (StateGraph) enables Decision 2 (multi-agent patterns) — same graph, more nodes
- Decision 3 (state schema) enables Decision 4 (retry logic) — `retry_count` field drives conditional edges
- Decision 5 (role isolation) shapes Decision 2 — each subgraph agent gets its tool subset at spawn time
- Decision 6 (audit log) is independent — can be added at any point

## Implementation Patterns & Consistency Rules

### Critical Conflict Points Identified

6 areas where inconsistency could cause agent implementation failures or debugging headaches.

### Pattern 1: Tool Interface Contract

All tools follow the same contract — string in, string out, with a consistent error prefix:

```python
@tool
def tool_name(param1: str, param2: str) -> str:
    """One-line description. Used by: [which agent roles]."""
    # ... implementation ...
    # SUCCESS case:
    return f"SUCCESS: {description_of_result}"
    # ERROR case:
    return f"ERROR: {description_of_failure}. {recovery_hint}"
```

**Rules:**
- All tool return values are strings (LLM-consumable)
- Success responses start with `SUCCESS:`
- Error responses start with `ERROR:` followed by a recovery hint
- Tool docstrings state which agent roles use them
- No exceptions escape tools — all errors are caught and returned as `ERROR:` strings
- Large outputs (>5000 chars) are truncated with a note: `(truncated, {n} chars total)`

### Pattern 2: Agent Prompt Structure

All agent system prompts follow this template:

```
## Role
You are a {role} Agent. {one-sentence identity}.

## Constraints
- {what you CAN do}
- {what you CANNOT do}
- {write restrictions if any}

## Process
1. {step 1}
2. {step 2}
...

## Output
{what you produce and where it goes}
```

**Rules:**
- Every agent prompt states its role, constraints, process, and expected output
- Constraints explicitly list forbidden actions (e.g., "Do NOT edit source code" for Review Agents)
- Process section gives a numbered sequence — agents follow steps in order
- Output section names the exact file path(s) the agent writes to

### Pattern 3: File-Based Communication Format

All inter-agent files (reviews, fix plans, test specs) follow this structure:

```markdown
---
agent_role: {role}
task_id: {task_id}
timestamp: {ISO 8601}
input_files: [{list of files read}]
---

# {Title}

## Summary
{1-2 sentence overview}

## Findings / Plan / Spec
{numbered list of items}

### {Item N}
- **File:** {path}
- **Issue/Change:** {description}
- **Severity/Priority:** {critical|major|minor}
- **Action:** {what to do}
```

**Rules:**
- YAML frontmatter with `agent_role`, `task_id`, `timestamp`, `input_files`
- Summary section always present
- Individual items are numbered and reference specific file paths
- Severity/Priority uses a fixed 3-level scale: critical, major, minor
- File paths are always relative to project root

### Pattern 4: Python Code Conventions

```
# Naming
- snake_case: functions, variables, modules, file names
- PascalCase: classes only (AgentState, not agent_state)
- UPPER_SNAKE: constants (MAX_RETRIES, DEFAULT_MODEL)

# Type hints
- Required on all function signatures (params + return)
- Not required on local variables (type inference is fine)
- Use `from __future__ import annotations` for forward references

# Imports
- Standard library → third-party → local, separated by blank lines
- Absolute imports only (from src.tools.file_ops import ..., not relative)
- No wildcard imports (from x import *)

# Docstrings
- Required on public functions and classes
- Not required on private helpers (_prefixed)
- Single-line for simple functions, Google-style for complex ones

# Error handling
- Tools: catch all exceptions, return ERROR: strings
- Graph nodes: let LangGraph handle retries via state
- Never bare `except:` — always `except Exception as e:` minimum
```

### Pattern 5: Error Message Format

Tool errors must be self-correcting — the error message tells the LLM exactly what went wrong and what to do next:

```
ERROR: old_string not found in {file_path}. Re-read the file to get current contents.
ERROR: old_string found {count} times in {file_path}. Provide more surrounding context to make the match unique.
ERROR: Command failed with exit code {code}: {stderr_first_500_chars}
ERROR: File not found: {file_path}. Use list_files to discover available files.
ERROR: Permission denied: Review agents cannot edit source files. Write to reviews/ directory only.
```

**Rules:**
- Always include the file path or command that failed
- Always include a recovery action ("Re-read", "Provide more context", "Use list_files")
- For command failures, include stderr (truncated to 500 chars)
- Role-violation errors explain what the agent CAN do instead

### Pattern 6: Trace Metadata Schema

All agent invocations include consistent LangSmith metadata:

```python
config = {
    "configurable": {"thread_id": session_id},
    "metadata": {
        "agent_role": "dev",          # dev|test|reviewer|architect|fix_dev
        "task_id": "story-42",        # matches task_id in state
        "model_tier": "sonnet",       # haiku|sonnet|opus
        "phase": "implementation",    # test|implementation|review|fix|ci
        "parent_session": session_id, # for sub-agents, the parent's session
    }
}
```

**Rules:**
- `agent_role` uses the fixed set: `dev`, `test`, `reviewer`, `architect`, `fix_dev`
- `model_tier` uses: `haiku`, `sonnet`, `opus`
- `phase` uses: `test`, `implementation`, `review`, `fix`, `ci`
- Sub-agents always include `parent_session` to link traces
- All metadata fields are lowercase, underscore-separated

### Enforcement Guidelines

**All Implementation MUST:**
- Follow tool contract (string in, string out, SUCCESS/ERROR prefix)
- Include type hints on all function signatures
- Use consistent error messages with recovery hints
- Include trace metadata on every agent invocation
- Write inter-agent files with YAML frontmatter

**Enforcement Mechanisms:**
- `ruff` linter for Python code style (PEP 8 + import ordering)
- `mypy` for type checking (enforces type hint requirement)
- Local CI script runs both before any git commit
- Code review agents check for pattern violations as part of their review

### Anti-Patterns to Avoid

| Anti-Pattern | Correct Pattern |
|---|---|
| Tool raises exception to caller | Tool catches exception, returns `ERROR:` string |
| Agent prompt says "do whatever you think is best" | Agent prompt gives numbered process steps |
| Review file is unstructured prose | Review file uses frontmatter + numbered findings |
| Error message says "something went wrong" | Error message says exactly what failed and what to do |
| Bare `except:` clause | `except Exception as e:` with logged message |
| `from .tools import *` | `from src.tools.file_ops import read_file, edit_file` |

## Project Structure & Boundaries

### Complete Project Directory Structure

```
shipyard/
├── README.md
├── CODEAGENT.md                    # Required deliverable — agent architecture docs
├── requirements.txt                # pip dependencies
├── pyproject.toml                  # Project metadata, ruff/mypy config
├── .env.example                    # Template: ANTHROPIC_API_KEY, LANGCHAIN_* vars
├── .gitignore
├── Dockerfile
├── docker-compose.yml
│
├── src/
│   ├── __init__.py
│   ├── main.py                     # Entry point: FastAPI server + CLI mode switch
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py                # Core StateGraph definition (agent + tools nodes)
│   │   ├── state.py                # AgentState schema (messages, task_id, retry_count, etc.)
│   │   ├── prompts.py              # System prompt templates per agent role
│   │   └── nodes.py                # Node functions: agent_node, tool_node, should_continue
│   │
│   ├── tools/
│   │   ├── __init__.py             # Tool registry: tools list, tools_by_name dict
│   │   ├── file_ops.py             # read_file, edit_file, write_file
│   │   ├── search.py               # list_files (glob), search_files (grep)
│   │   └── bash.py                 # run_command (shell execution with timeout)
│   │
│   ├── multi_agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # Parent StateGraph: pipeline nodes + conditional edges
│   │   ├── roles.py                # Role definitions: tool subsets, model tier, prompts per role
│   │   └── spawn.py                # create_agent_subgraph(): builds a role-specific compiled graph
│   │
│   ├── context/
│   │   ├── __init__.py
│   │   └── injection.py            # build_system_prompt(), inject_task_context()
│   │
│   └── logging/
│       ├── __init__.py
│       └── audit.py                # Markdown audit logger: session lifecycle, agent events
│
├── scripts/
│   ├── local_ci.sh                 # Lint (ruff) + type check (mypy) + test (pytest)
│   ├── run_tests.sh                # pytest runner with coverage
│   └── git_snapshot.sh             # git add + commit with message
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                 # Shared fixtures: temp files, mock tools, test state
│   ├── test_tools/
│   │   ├── __init__.py
│   │   ├── test_file_ops.py        # Tests for read_file, edit_file, write_file
│   │   ├── test_search.py          # Tests for list_files, search_files
│   │   └── test_bash.py            # Tests for run_command
│   ├── test_agent/
│   │   ├── __init__.py
│   │   ├── test_graph.py           # Tests for core agent loop behavior
│   │   ├── test_state.py           # Tests for state schema and transitions
│   │   └── test_nodes.py           # Tests for node functions
│   ├── test_multi_agent/
│   │   ├── __init__.py
│   │   ├── test_orchestrator.py    # Tests for pipeline graph
│   │   └── test_spawn.py           # Tests for agent spawning
│   └── test_context/
│       ├── __init__.py
│       └── test_injection.py       # Tests for context layer management
│
├── logs/                           # Git-ignored; runtime audit logs
│   └── .gitkeep
│
├── reviews/                        # Git-ignored; inter-agent review files
│   └── .gitkeep
│
├── checkpoints/                    # Git-ignored; SQLite checkpoint DB
│   └── .gitkeep
│
└── gauntlet_docs/                  # Assignment docs, PRESEARCH, PRD
    ├── PRESEARCH.md
    └── shipyard_prd.pdf
```

### Architectural Boundaries

**API Boundary (FastAPI):**
- Single endpoint: `POST /instruct` — accepts `{message: str, session_id?: str}`
- Returns: `{session_id: str, response: str, messages_count: int}`
- CLI mode: `python main.py --cli` — interactive loop, same agent invocation path
- Both modes call the same `agent.invoke()` under the hood — the API is a thin wrapper

**Agent Graph Boundary:**
- Input: `AgentState` with messages + metadata
- Output: Updated `AgentState` with accumulated messages and tool results
- The graph boundary is where checkpointing happens — state is persisted after every node
- Sub-agents get their own compiled graphs but share the same tool implementations

**Tool Boundary:**
- Tools are pure functions: `(args) → str`
- No tool accesses agent state directly — tools receive parameters and return strings
- Tools operate on the filesystem; the filesystem is the shared state between agents
- Path validation happens inside tools (e.g., review agents can only write to `reviews/`)

**Multi-Agent Boundary:**
- Parent orchestrator graph invokes sub-agent graphs as nodes
- State transformation happens at boundaries: parent state → sub-agent input, sub-agent output → parent state
- Sub-agents do NOT share message history — each starts with a fresh context containing only its task and injected context files
- The only shared state is the filesystem

### Requirements to Structure Mapping

| Requirement | Primary Files | Supporting Files |
|---|---|---|
| FR1: Persistent loop | `src/main.py` | `src/agent/graph.py`, `src/agent/state.py` |
| FR2: Surgical editing | `src/tools/file_ops.py` (edit_file) | `src/agent/nodes.py` (tool_node) |
| FR3: Context injection | `src/context/injection.py` | `src/agent/prompts.py` |
| FR4: Multi-agent | `src/multi_agent/orchestrator.py` | `src/multi_agent/roles.py`, `spawn.py` |
| FR5: LangSmith tracing | `.env.example` (env vars) | `src/multi_agent/roles.py` (metadata) |
| FR6: Tool suite | `src/tools/*.py` | `src/tools/__init__.py` (registry) |
| FR7: Ship rebuild | (external — target project) | `src/multi_agent/orchestrator.py` (pipeline) |
| FR8: CODEAGENT.md | `CODEAGENT.md` | All architecture docs |

### Cross-Cutting Concern Mapping

| Concern | Where It Lives |
|---|---|
| Token cost / model routing | `src/multi_agent/roles.py` — model tier per role |
| Error recovery (retry logic) | `src/agent/nodes.py` — conditional edges, `src/agent/state.py` — retry_count |
| Observability | `src/logging/audit.py` + LangSmith env vars + metadata in `roles.py` |
| File-based communication | `reviews/` directory + Pattern 3 format from Implementation Patterns |
| Role isolation | `src/multi_agent/roles.py` — tool subset definitions per role |

### Data Flow

```
User Instruction
    │
    ▼
FastAPI /instruct (or CLI input)
    │
    ▼
agent.invoke(AgentState, config)
    │
    ├─► agent_node: LLM call with system prompt + messages
    │       │
    │       ▼
    │   should_continue: tool_calls? → yes → tool_node → agent_node (loop)
    │                                → no  → END (response)
    │
    ├─► [Multi-agent mode] orchestrator.invoke()
    │       │
    │       ├─► test_agent subgraph → writes test files
    │       ├─► dev_agent subgraph → writes source files
    │       ├─► bash node → runs CI/tests
    │       ├─► Send(reviewer_1, reviewer_2) → write review files
    │       ├─► architect_agent subgraph → reads reviews, writes fix plan
    │       ├─► fix_dev_agent subgraph → reads fix plan, edits source
    │       └─► bash node → final CI + git push
    │
    ▼
Response returned to user
```

### Development Workflow

**Local development:**
```bash
# Start in CLI mode (MVP)
python src/main.py --cli

# Start as FastAPI server
uvicorn src.main:app --reload --port 8000

# Run tests
pytest tests/ -v

# Run local CI
bash scripts/local_ci.sh
```

**Docker:**
```bash
docker compose up               # Starts FastAPI server
docker compose run agent --cli  # Interactive CLI mode
```

## Architecture Validation Results

### Coherence Validation

**Decision Compatibility:** PASS
- LangGraph + ChatAnthropic + SQLite checkpointing are a proven combination (documented in research)
- Custom `StateGraph` with extended `AgentState` supports all 6 architectural decisions without conflicts
- Hybrid multi-agent pattern (subgraphs + `Send`) is natively supported by LangGraph
- FastAPI + CLI dual-mode uses the same `agent.invoke()` path — no divergence risk

**Pattern Consistency:** PASS
- All 6 implementation patterns are internally consistent and reference the same conventions
- Tool contract (Pattern 1) aligns with error message format (Pattern 5) — both use `SUCCESS:/ERROR:` prefix
- Agent prompt structure (Pattern 2) aligns with role isolation (Decision 5) — constraints section enforces write restrictions
- File-based communication format (Pattern 3) aligns with trace metadata (Pattern 6) — both use `task_id` as the linking field
- Python conventions (Pattern 4) are enforceable via ruff + mypy in the local CI script

**Structure Alignment:** PASS
- Project structure maps to all 8 FRs (verified in Requirements to Structure Mapping table)
- Every cross-cutting concern has an identified home (verified in Cross-Cutting Concern Mapping table)
- Boundaries are clean: API → Graph → Tools → Filesystem, with no circular dependencies

**Inconsistency Resolved:**
- Starter Evaluation title references `create_react_agent` but Decision 1 chose custom `StateGraph`. Decision 1 is authoritative. The project structure from Step 3 remains valid; only the agent core approach changed.
- `multi_agent/agents.py` (Step 3) was renamed to `multi_agent/roles.py` (Step 6). The Step 6 structure is authoritative.

### Requirements Coverage Validation

**Functional Requirements:**

| FR | Architectural Support | Status |
|---|---|---|
| FR1: Persistent loop | FastAPI server + CLI loop, SQLite checkpointing, `thread_id` session management | Covered |
| FR2: Surgical editing | `edit_file` tool with exact string match, fail-loud on no-match/non-unique, Pattern 5 error recovery | Covered |
| FR3: Context injection | 3-layer system in `context/injection.py`, system prompt (L1), task files (L2), on-demand tools (L3) | Covered |
| FR4: Multi-agent | Hybrid subgraph + `Send` pattern, role isolation, file-based communication | Covered |
| FR5: LangSmith tracing | Zero-config env vars, custom metadata schema (Pattern 6), audit log (Decision 6) | Covered |
| FR6: Tool suite | 6 tools in `tools/` module, tool registry in `__init__.py`, role-based subsets in `roles.py` | Covered |
| FR7: Ship rebuild | Orchestrator pipeline runs the full TDD cycle against any target project | Covered |
| FR8: CODEAGENT.md | Architecture document + this validation feed directly into CODEAGENT.md sections | Covered |

**Non-Functional Requirements:**

| NFR | Architectural Support | Status |
|---|---|---|
| NFR1: >90% edit reliability | Fail-loud edit tool + self-correcting error messages + 3 retry limit | Covered |
| NFR2: 30+ min stability | SQLite checkpointing survives restarts, global 50-turn cap prevents runaway | Covered |
| NFR3: Trace completeness | LangSmith auto-traces all nodes/tools + custom metadata + Markdown audit log | Covered |
| NFR4: Fail-loud semantics | Edit tool returns ERROR on no-match/non-unique, never fuzzy-matches | Covered |
| NFR5: Token cost awareness | Model routing per role (Haiku/Sonnet/Opus) in `roles.py`, cost tracked in traces | Covered |
| NFR6: Reproducibility | `.env.example`, `requirements.txt`, Docker, README — clone-and-run in <10 min | Covered |

### Implementation Readiness Validation

**Decision Completeness:** PASS
- All 6 critical/important decisions documented with rationale and affected components
- 3 deferred decisions explicitly listed with deferral justification
- Implementation sequence defined with dependency ordering

**Structure Completeness:** PASS
- Complete directory tree with every file annotated
- 4 architectural boundaries defined (API, Graph, Tool, Multi-Agent)
- Requirements-to-structure mapping covers all 8 FRs
- Cross-cutting concern mapping covers all 5 concerns

**Pattern Completeness:** PASS
- 6 patterns covering all conflict points
- Concrete code examples for every pattern
- Anti-pattern table with 6 entries
- Enforcement mechanisms defined (ruff, mypy, local CI)

### Gap Analysis Results

**Critical Gaps:** None found.

**Important Gaps (addressable during implementation):**
1. **`read_file` tool behavior for large files** — the tool contract doesn't specify what happens when a file exceeds context window limits. Recommendation: truncate at 10,000 chars with a note, and provide an offset/limit parameter for reading specific sections.
2. **Target project working directory** — when Shipyard rebuilds Ship, where does the target project live relative to Shipyard's own directory? Recommendation: configurable `--target-dir` parameter, defaulting to `./target/`.

**Nice-to-Have Gaps (post-MVP):**
1. Context compaction strategy (already listed as deferred)
2. Agent prompt versioning (track which prompt version produced which result)
3. Cost estimation before execution (predict token usage based on task complexity)

### Architecture Completeness Checklist

**Requirements Analysis**
- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified
- [x] Cross-cutting concerns mapped

**Architectural Decisions**
- [x] Critical decisions documented with rationale
- [x] Technology stack fully specified with versions
- [x] Integration patterns defined (subgraphs + Send)
- [x] Error recovery strategy defined (3-layer)

**Implementation Patterns**
- [x] Naming conventions established (PEP 8 + project-specific)
- [x] Structure patterns defined (tool contract, prompt template, communication format)
- [x] Communication patterns specified (file-based, YAML frontmatter)
- [x] Process patterns documented (error messages, trace metadata)

**Project Structure**
- [x] Complete directory structure defined
- [x] Component boundaries established (API, Graph, Tool, Multi-Agent)
- [x] Integration points mapped (data flow diagram)
- [x] Requirements to structure mapping complete

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High

**Key Strengths:**
- Architecture directly maps to PRD requirements with no gaps
- Custom `StateGraph` design avoids mid-week refactoring — grows from MVP to full pipeline without structural changes
- Tool contract and error message patterns are designed for LLM self-correction — reduces human intervention
- File-based coordination is simple, debuggable, and produces persistent artifacts for traceability
- All enforcement is automated (ruff, mypy, local CI) — no manual pattern policing needed

**Areas for Future Enhancement:**
- Context compaction for long sessions (post-MVP)
- Agent prompt versioning for reproducibility
- Cost prediction before execution
- Postgres migration for concurrent production sessions

### Implementation Handoff

**AI Agent Guidelines:**
- Follow all architectural decisions exactly as documented
- Use implementation patterns consistently across all components
- Respect project structure and boundaries
- Refer to this document for all architectural questions
- When in doubt, check the anti-patterns table

**First Implementation Priority:**
1. Create project scaffold (directory structure, `requirements.txt`, `.env.example`, `pyproject.toml`)
2. Implement `AgentState` in `src/agent/state.py`
3. Implement tools in `src/tools/` following Pattern 1 (tool contract)
4. Build 2-node `StateGraph` in `src/agent/graph.py`
5. Wire FastAPI + CLI in `src/main.py`
6. Set LangSmith env vars and verify tracing
7. Test: send instruction → agent reads file → agent makes surgical edit → verify in trace

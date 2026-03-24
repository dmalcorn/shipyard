# Story 1.4: Core Agent Loop (StateGraph)

Status: ready-for-dev

## Story

As a developer,
I want a working LangGraph agent that accepts an instruction, reasons about it, calls tools, and returns a result,
so that I have the foundational agent loop that all multi-agent features will build on.

## Acceptance Criteria

1. **Given** the agent is initialized with a custom `StateGraph` (not `create_react_agent`) **When** the agent receives a message **Then** it enters the ReAct loop: agent_node → should_continue → tool_node → agent_node (repeat) **And** the loop terminates when the LLM returns no tool calls
2. **Given** the `AgentState` schema **When** a session runs **Then** state includes `messages`, `task_id`, `retry_count`, `current_phase`, `agent_role`, `files_modified`
3. **Given** a global turn cap of 50 **When** the agent exceeds 50 LLM turns in a single task **Then** the loop terminates with an error message rather than running indefinitely
4. **Given** SQLite checkpointing is configured **When** the agent processes a message **Then** state is persisted after every node execution **And** the session can be resumed with the same `thread_id`

## Tasks / Subtasks

- [ ] Task 1: Implement `AgentState` in `src/agent/state.py` (AC: #2)
  - [ ] Extend `MessagesState` from `langgraph.graph`
  - [ ] Add fields: `task_id: str`, `retry_count: int`, `current_phase: str`, `agent_role: str`, `files_modified: Annotated[list[str], operator.add]`
  - [ ] Import `operator` for the `files_modified` reducer (append semantics)
- [ ] Task 2: Create tool registry in `src/tools/__init__.py` (AC: #1)
  - [ ] Import all tools from `file_ops.py`, `search.py`, `bash.py`
  - [ ] Export `tools` list and `tools_by_name` dict for graph binding
- [ ] Task 3: Implement node functions in `src/agent/nodes.py` (AC: #1, #3)
  - [ ] `agent_node(state: AgentState)` — calls `ChatAnthropic` with system prompt + state messages, returns updated messages
  - [ ] `tool_node(state: AgentState)` — uses `ToolNode` from `langgraph.prebuilt` or manual tool dispatch; executes tool calls from last AI message, returns tool results as messages
  - [ ] `should_continue(state: AgentState)` — checks if last AI message has tool calls → route to "tools" or "end"; also checks `retry_count >= 50` → route to error handler
- [ ] Task 4: Build `StateGraph` in `src/agent/graph.py` (AC: #1, #3, #4)
  - [ ] Create `StateGraph(AgentState)`
  - [ ] Add nodes: `"agent"` → `agent_node`, `"tools"` → `tool_node`
  - [ ] Add edges: `START → "agent"`, `"agent" → should_continue (conditional)`, `"tools" → "agent"`
  - [ ] Conditional edge from `should_continue`: `"continue" → "tools"`, `"end" → END`, `"error" → END` (with error message)
  - [ ] Configure `SqliteSaver` checkpointer from `langgraph-checkpoint-sqlite`
  - [ ] Compile graph with checkpointer: `graph.compile(checkpointer=memory)`
  - [ ] Export a `create_agent()` function that returns the compiled graph
- [ ] Task 5: Configure LLM in `agent_node` (AC: #1)
  - [ ] Use `ChatAnthropic(model="claude-sonnet-4-6")` as default for single-agent mode
  - [ ] Bind tools to the model: `model.bind_tools(tools)`
  - [ ] Load API key from environment variable
- [ ] Task 6: Write tests in `tests/test_agent/` (AC: #1-4)
  - [ ] `test_state.py` — verify `AgentState` has all required fields, `files_modified` uses append reducer
  - [ ] `test_graph.py` — verify graph compiles, has correct nodes/edges
  - [ ] `test_nodes.py` — test `should_continue` routing logic (tool calls → continue, no tool calls → end, retry exceeded → error)

## Dev Notes

- **CRITICAL: Do NOT use `create_react_agent`** — Decision 1 in architecture mandates custom `StateGraph` from day one. The 2-node graph (agent + tools) is nearly identical code but avoids mid-week refactoring.
- `ChatAnthropic` comes from `langchain-anthropic` package — import as `from langchain_anthropic import ChatAnthropic`
- `SqliteSaver` comes from `langgraph-checkpoint-sqlite` — import as `from langgraph.checkpoint.sqlite import SqliteSaver`
- The `should_continue` function is a conditional edge — it returns a string key that maps to the next node
- `retry_count` must be incremented in `agent_node` each time it's called — this drives the global 50-turn cap
- `files_modified` uses `Annotated[list[str], operator.add]` so each tool call appends rather than overwrites
- The graph must work with `thread_id` in config for session resumption: `graph.invoke(state, config={"configurable": {"thread_id": "session-1"}})`
- `ToolNode` from `langgraph.prebuilt` can be used for the tool execution node — it handles tool call dispatch automatically

### AgentState Schema (from architecture Decision 3)

```python
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

### Project Structure Notes

- `src/agent/state.py` — AgentState schema
- `src/agent/graph.py` — StateGraph definition and compilation
- `src/agent/nodes.py` — node functions (agent_node, tool_node, should_continue)
- `src/tools/__init__.py` — tool registry
- Stories 1.1, 1.2, and 1.3 must be complete before this story (tools must exist to bind)

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 1: Graph Topology]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 3: Agent State Schema]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 4: Retry Limits and Circuit Breaking]
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Flow]
- [Source: _bmad-output/planning-artifacts/architecture.md#Agent Graph Boundary]
- [Source: coding-standards.md#Python Conventions]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

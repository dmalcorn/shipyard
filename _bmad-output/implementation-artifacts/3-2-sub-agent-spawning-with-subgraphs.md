# Story 3.2: Sub-Agent Spawning with Subgraphs

Status: complete

## Story

As a developer,
I want the orchestrator to spawn specialized agents as LangGraph subgraphs that run independently with their own context,
so that each agent gets a fresh context window with only its task and injected files.

## Acceptance Criteria

1. **Given** the orchestrator parent graph **When** it spawns a sub-agent (e.g., Dev Agent) **Then** a new compiled subgraph is created with the role's tool subset, system prompt, and model tier
2. **Given** a sub-agent subgraph **When** it runs **Then** it does NOT share message history with the parent — it starts fresh with only its task description and injected context files
3. **Given** a sub-agent **When** it produces output **Then** the output is written to the filesystem (the coordination primitive) and the parent graph reads it
4. **Given** sub-agent state **When** traced in LangSmith **Then** the sub-agent trace is linked to the parent via `parent_session` metadata

## Tasks / Subtasks

- [x] Task 1: Create `src/multi_agent/spawn.py` with `create_agent_subgraph()` factory (AC: #1)
  - [x] Function signature: `create_agent_subgraph(role: str, task_description: str, context_files: list[str] | None = None) -> CompiledGraph`
  - [x] Look up role config from `roles.py` to get model tier, tool subset, system prompt
  - [x] Build a 2-node `StateGraph` (agent_node + tool_node) with `should_continue` conditional edge — same pattern as the core loop from Story 1.4
  - [x] Bind the role's tool subset to the LLM via `ChatAnthropic.bind_tools()`
  - [x] Inject Layer 1 context (system prompt with role) + Layer 2 context (task-specific files read from disk)
  - [x] Compile with `SqliteSaver` checkpointing
  - [x] Return the compiled graph ready to invoke
- [x] Task 2: Implement fresh context isolation (AC: #2)
  - [x] Sub-agent receives a NEW `AgentState` with fresh `messages` list — NOT the parent's messages
  - [x] Initial messages contain ONLY: system prompt (role + constraints), task description (HumanMessage), and any injected file contents
  - [x] Parent state fields (`task_id`, `current_phase`, etc.) are passed via the new state, not via message history
  - [x] Sub-agent gets its own `thread_id` (e.g., `{parent_session_id}-{role}-{timestamp}`)
- [x] Task 3: Implement file-based output coordination (AC: #3)
  - [x] Sub-agents write results to the filesystem per their role's output pattern:
    - Dev Agent → modified source files (tracked in `files_modified` state field)
    - Test Agent → test files in `tests/`
    - Review Agent → `reviews/review-agent-{n}.md`
    - Architect Agent → `fix-plan.md` in project root or `reviews/`
  - [x] Parent orchestrator reads output files after sub-agent completes
  - [x] All inter-agent files use YAML frontmatter format (Pattern 3 from architecture)
- [x] Task 4: Wire LangSmith trace linking (AC: #4)
  - [x] Pass `parent_session` in the config metadata when invoking sub-agent
  - [x] Verify traces appear linked in LangSmith UI
- [x] Task 5: Create orchestrator node wrapper (AC: #1-#3)
  - [x] `run_sub_agent(state: OrchestratorState, role: str, task: str, context_files: list[str]) -> dict`
  - [x] Creates subgraph via `create_agent_subgraph()`
  - [x] Invokes with fresh state and config
  - [x] Reads output files from filesystem after completion
  - [x] Returns state updates for the parent graph (files_modified, phase progression)
- [x] Task 6: Write tests in `tests/test_multi_agent/test_spawn.py` (AC: #1-#4)
  - [x] Test `create_agent_subgraph` returns a compiled graph with correct tool count per role
  - [x] Test sub-agent receives fresh messages (not parent history)
  - [x] Test sub-agent config includes `parent_session` metadata
  - [x] Test sub-agent thread_id is distinct from parent thread_id
  - [x] Integration test: spawn a Dev Agent subgraph, invoke with a simple task, verify it can call tools

## Dev Notes

- **Primary files:** `src/multi_agent/spawn.py` (new), update `src/multi_agent/orchestrator.py`
- **Key LangGraph pattern:** Sub-agents are compiled `StateGraph` instances invoked as function calls within parent graph nodes — they are NOT nested `StateGraph` nodes (that's the subgraph pattern used in Story 3.5). Here, `create_agent_subgraph()` builds a standalone graph that a parent node invokes via `.invoke()`.
- **Context isolation is critical:** The whole point of sub-agents is fresh context. If you pass the parent's messages, you defeat the purpose. Each sub-agent should feel like starting a new conversation with a specialist who only knows their task.
- **ChatAnthropic model instantiation:**
  ```python
  from langchain_anthropic import ChatAnthropic
  llm = ChatAnthropic(model=model_id, temperature=0)
  llm_with_tools = llm.bind_tools(tools)
  ```
- **Model IDs:** Sonnet = `claude-sonnet-4-6`, Opus = `claude-opus-4-6`, Haiku = `claude-haiku-4-5-20251001`
- **Checkpointing:** Each sub-agent gets its own checkpointer instance or uses a shared `SqliteSaver` with a unique `thread_id`
- **Do NOT use `create_react_agent`** — build the 2-node StateGraph manually per architecture Decision 1
- **Global turn cap (50) applies per sub-agent** — each sub-agent has its own retry_count in its own state

### Dependencies

- **Requires:** Story 1.4 (Core Agent Loop) — the 2-node StateGraph pattern to replicate
- **Requires:** Story 1.5 (Context Injection) — `build_system_prompt()` for role-specific prompts
- **Requires:** Story 2.1 (LangSmith Tracing) — metadata config structure
- **Requires:** Story 3.1 (Agent Role Definitions) — role configs, tool subsets, system prompts
- **Feeds into:** Story 3.3 (Parallel Review Pipeline) — spawning mechanism used by Send API
- **Feeds into:** Story 3.5 (Full TDD Orchestrator) — all pipeline stages use this spawning

### Project Structure Notes

- `src/multi_agent/spawn.py` — new file, architecture doc specifies this exact path
- `src/multi_agent/orchestrator.py` — will be extended (main wiring happens in Story 3.5)
- `tests/test_multi_agent/test_spawn.py` — new test file

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 2: Multi-Agent Coordination Pattern]
- [Source: _bmad-output/planning-artifacts/architecture.md#Multi-Agent Boundary]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 6: Trace Metadata Schema]
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Flow diagram — sub-agent invocation]
- [Source: _bmad-output/project-context.md#Framework-Specific Rules — LangGraph]
- [Source: coding-standards.md#File-Based Communication Format]

## Dev Agent Record

### Agent Model Used
claude-opus-4-6

### Debug Log References
N/A

### Completion Notes List
- create_agent_subgraph() returns (compiled_graph, initial_state) tuple for flexible invocation
- Fresh context via inject_task_context() — sub-agent gets only task instruction + context files, no parent history
- Sub-agent thread_id format: `{parent_session_id}-{role}-{timestamp}` for uniqueness
- run_sub_agent() orchestrator wrapper handles full lifecycle: create → configure → invoke → extract results
- Config metadata includes parent_session for LangSmith trace linking
- 19 new tests covering subgraph creation, context isolation, routing, and orchestrator wrapper
- ruff + mypy clean

### File List
- src/multi_agent/spawn.py (new — create_agent_subgraph, run_sub_agent, _should_continue)
- tests/test_multi_agent/test_spawn.py (new — 19 tests)

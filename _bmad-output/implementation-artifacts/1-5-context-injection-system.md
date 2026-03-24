# Story 1.5: Context Injection System

Status: complete

## Story

As a developer,
I want to inject context (role descriptions, task specs, coding standards) into the agent so it follows project conventions,
so that the agent's behavior changes based on the context provided.

## Acceptance Criteria

1. **Given** Layer 1 context files exist (agent role description, coding standards, orchestration guidance) **When** the agent starts a session **Then** Layer 1 context is included in the system prompt for every invocation
2. **Given** a task instruction includes Layer 2 context (specific file paths, task specs) **When** the agent receives the instruction **Then** the task-specific files are read and included in the message context
3. **Given** the agent is running **When** it needs additional information during execution **Then** it can use Read, Grep, and Glob tools (Layer 3) to pull on-demand context
4. **Given** the same instruction sent with different Layer 1 context (e.g., "You are a Dev Agent" vs "You are a Review Agent") **When** both agents process the instruction **Then** their outputs demonstrably differ based on the injected role context

## Tasks / Subtasks

- [x] Task 1: Implement `build_system_prompt` in `src/context/injection.py` (AC: #1, #4)
  - [x] Parameters: `role: str`, `context_files: list[str] | None = None` → returns `str`
  - [x] Load role-specific prompt template from `src/agent/prompts.py`
  - [x] Always inject Layer 1 content: role description + coding standards (from `coding-standards.md`)
  - [x] Concatenate into a single system prompt string
  - [x] Return the assembled prompt
- [x] Task 2: Implement `inject_task_context` in `src/context/injection.py` (AC: #2)
  - [x] Parameters: `instruction: str`, `context_files: list[str] | None = None` → returns `list[BaseMessage]`
  - [x] If `context_files` provided, read each file and prepend content to the instruction
  - [x] Format: `"## Context: {filename}\n{content}\n\n"` followed by `"## Instruction\n{instruction}"`
  - [x] Return as a `HumanMessage` list suitable for adding to state messages
- [x] Task 3: Create agent prompt templates in `src/agent/prompts.py` (AC: #1, #4)
  - [x] Define prompt templates following Pattern 2 (Role, Constraints, Process, Output sections)
  - [x] Create `DEV_AGENT_PROMPT` — full tool access, writes source code
  - [x] Create `REVIEW_AGENT_PROMPT` — read-only, writes to `reviews/` only
  - [x] Create base `get_prompt(role: str)` function that returns the right template
  - [x] Prompts explicitly list what each role CAN and CANNOT do
- [x] Task 4: Integrate with agent_node in `src/agent/graph.py` (AC: #1, #2)
  - [x] `agent_node` calls `build_system_prompt(state["agent_role"])` to get the system prompt
  - [x] System prompt is passed as the first message to `ChatAnthropic`
  - [x] Task context files (Layer 2) are injected into the human message
- [x] Task 5: Write tests in `tests/test_context/test_injection.py` (AC: #1-4)
  - [x] Test `build_system_prompt` — includes role description, includes coding standards
  - [x] Test `inject_task_context` — reads context files, formats correctly
  - [x] Test different roles produce different prompts (dev vs reviewer)
  - [x] Test Layer 3 is available via tools (read_file, search_files, list_files already exist)

## Dev Notes

- **3-layer context system** (architecture FR3):
  - **Layer 1 (always-present):** Role description + coding standards in system prompt — injected on every LLM call
  - **Layer 2 (task-specific):** File contents passed per instruction — read once at task start
  - **Layer 3 (on-demand):** Agent uses Read/Grep/Glob tools during execution — no special code needed, tools already exist from Stories 1.2/1.3
- Layer 3 requires no implementation — it's the tools themselves. The agent naturally uses them during the ReAct loop.
- Prompt templates follow Pattern 2 from architecture: Role, Constraints, Process, Output sections
- `coding-standards.md` at project root is the Layer 1 conventions file — read it at startup and include in every system prompt
- Keep system prompts concise to manage token costs — Opus context especially should be minimal (NFR5)
- The `build_system_prompt` function is the single point where all Layer 1 context is assembled

### Project Structure Notes

- `src/context/injection.py` — context layer management functions
- `src/agent/prompts.py` — prompt templates per agent role
- `tests/test_context/test_injection.py`
- Depends on Stories 1.1-1.4 (tools exist, graph exists, agent_node exists)

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 2: Agent Prompt Structure]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 5: Working Directory and Role Isolation]
- [Source: _bmad-output/planning-artifacts/architecture.md#Cross-Cutting Concerns — Context window pressure]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.5: Context Injection System]
- [Source: coding-standards.md] (this file IS the Layer 1 conventions content)

## Dev Agent Record

### Agent Model Used
Claude Opus 4.6

### Debug Log References
N/A

### Completion Notes List
- Implemented 4 prompt templates (dev, test, reviewer, architect) following Pattern 2 from architecture
- `build_system_prompt` assembles Layer 1: role prompt + coding-standards.md + optional context files
- `inject_task_context` assembles Layer 2: reads context files, prepends to instruction as HumanMessage
- Layer 3 requires no implementation — existing tools (read_file, search_files, list_files) serve as on-demand context
- Integrated into `agent_node` in nodes.py — replaces hardcoded SYSTEM_PROMPT with role-aware prompt via `build_system_prompt(state["agent_role"])`
- Added TEST_AGENT_PROMPT and ARCHITECT_AGENT_PROMPT beyond the minimum spec (dev + reviewer) for completeness
- Fallback to original prompt if unknown role is provided
- 23 tests covering all ACs, 157/157 full suite passing

### File List
- src/agent/prompts.py (new) — prompt templates + get_prompt()
- src/context/injection.py (new) — build_system_prompt(), inject_task_context()
- src/agent/nodes.py (modified) — integrated build_system_prompt, replaced hardcoded SYSTEM_PROMPT
- tests/test_context/test_injection.py (new) — 23 tests for AC #1-4

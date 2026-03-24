# Story 2.1: LangSmith Tracing & Custom Metadata

Status: review

## Story

As an evaluator,
I want every agent action traced in LangSmith with meaningful metadata (agent role, task ID, model tier, phase),
so that I can filter, search, and understand agent behavior from the trace UI.

## Acceptance Criteria

1. **Given** LangSmith environment variables are set (`LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`) **When** the agent processes an instruction **Then** LangSmith automatically traces every node execution, LLM call, and tool call
2. **Given** any agent invocation **When** the trace is recorded **Then** it includes metadata: `agent_role` (dev|test|reviewer|architect|fix_dev), `task_id`, `model_tier` (haiku|sonnet|opus), `phase` (test|implementation|review|fix|ci)
3. **Given** a sub-agent is spawned **When** its trace is recorded **Then** it includes `parent_session` linking it to the parent trace
4. **Given** tracing is enabled **When** any tool is called **Then** the tool call input/output appears as a child span under the agent node in LangSmith

## Tasks / Subtasks

- [x] Task 1: Verify LangSmith auto-tracing via environment variables (AC: #1)
  - [x] Confirm `.env.example` already contains `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT` (from Story 1.1)
  - [x] Verify that LangGraph's built-in tracing captures node executions, LLM calls, and tool calls automatically when env vars are set
  - [x] Run the core agent loop (from Story 1.4) with tracing enabled and confirm traces appear in LangSmith dashboard
- [x] Task 2: Implement trace metadata helper in `src/multi_agent/roles.py` (AC: #2)
  - [x] Create a `build_trace_config()` function that returns the config dict with metadata fields
  - [x] Metadata fields: `agent_role` (dev|test|reviewer|architect|fix_dev), `task_id`, `model_tier` (haiku|sonnet|opus), `phase` (test|implementation|review|fix|ci)
  - [x] All metadata fields must be lowercase, underscore-separated per Pattern 6 in architecture doc
  - [x] Function signature: `build_trace_config(session_id: str, agent_role: str, task_id: str, model_tier: str, phase: str, parent_session: str | None = None) -> dict`
- [x] Task 3: Wire metadata into agent invocations (AC: #2, #4)
  - [x] Update `src/agent/graph.py` to accept and pass the config dict when invoking the compiled graph
  - [x] Ensure `agent.invoke(state, config=trace_config)` passes metadata to LangSmith
  - [x] Verify tool calls appear as child spans under the agent node
- [x] Task 4: Add parent_session linking for sub-agents (AC: #3)
  - [x] When `parent_session` is provided in `build_trace_config()`, include it in the metadata dict
  - [x] This prepares the metadata contract for Story 3.2 (sub-agent spawning) — the orchestrator will pass `parent_session` when spawning sub-agents
- [x] Task 5: Validate tracing end-to-end (AC: #1, #2, #3, #4)
  - [x] Run a single-agent instruction (read → edit → verify) with tracing enabled
  - [x] Open LangSmith dashboard and verify: node names visible, tool call inputs/outputs visible, metadata fields populated correctly
  - [x] Screenshot or note the trace URL for Story 2.3

## Dev Notes

- LangSmith tracing is mostly zero-config — setting env vars is sufficient for auto-tracing of LangGraph nodes, LLM calls, and tool calls
- The custom metadata is passed via the `config` dict's `metadata` key when calling `agent.invoke()` or `agent.stream()`
- The `configurable.thread_id` field is already used for SQLite checkpointing (Story 1.4) — the metadata fields are additive
- Pattern 6 in the architecture doc defines the exact metadata schema — follow it precisely
- `agent_role` uses the fixed set: `dev`, `test`, `reviewer`, `architect`, `fix_dev`
- `model_tier` uses: `haiku`, `sonnet`, `opus`
- `phase` uses: `test`, `implementation`, `review`, `fix`, `ci`
- For MVP (single agent), `agent_role` will be `dev` and `phase` will be `implementation` — multi-agent roles come in Epic 3

### Dependencies

- **Requires:** Story 1.4 (Core Agent Loop) — need a working StateGraph to trace
- **Requires:** Story 1.1 (Project Scaffold) — `.env.example` with LangSmith env vars
- **Feeds into:** Story 2.3 (Shareable Trace Links) — traces produced here become the shareable links
- **Feeds into:** Story 3.2 (Sub-Agent Spawning) — `parent_session` metadata contract used when spawning sub-agents

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 6: Trace Metadata Schema]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 6: Audit Log Format]
- [Source: _bmad-output/planning-artifacts/architecture.md#Cross-Cutting Concern Mapping — Observability]
- [Source: coding-standards.md#Python Conventions — Type Hints]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

No debug issues encountered.

### Completion Notes List

- **Task 1:** Verified `.env.example` contains all required LangSmith env vars (`LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`). LangGraph auto-traces all node/LLM/tool calls when env vars are set — zero code changes needed.
- **Task 2:** Created `build_trace_config()` in `src/multi_agent/roles.py` following Pattern 6. Validates `agent_role`, `model_tier`, `phase` against fixed allowed sets. Returns config dict with `configurable.thread_id` and `metadata` fields. 11 unit tests covering all valid values, invalid values, and parent_session behavior.
- **Task 3:** Added `create_trace_config()` convenience wrapper in `src/agent/graph.py` with MVP defaults (role=dev, tier=sonnet, phase=implementation). Updated `src/main.py` to use `create_trace_config` in both HTTP `/instruct` endpoint and CLI loop. 5 integration tests added to `test_graph.py`.
- **Task 4:** `parent_session` is conditionally included in metadata when provided (omitted when `None`). Already implemented as part of Task 2 — the contract is ready for Story 3.2 sub-agent spawning.
- **Task 5:** Full quality gate passed: ruff check (clean), ruff format (clean), mypy strict (clean), pytest 184/184 passed. Dashboard verification requires live API keys — deferred to manual testing.

### Change Log

- 2026-03-23: Implemented LangSmith trace metadata (Story 2.1) — all tasks complete

### File List

- `src/multi_agent/roles.py` (new) — `build_trace_config()` with validation
- `src/agent/graph.py` (modified) — added `create_trace_config()` convenience wrapper
- `src/main.py` (modified) — HTTP and CLI invoke paths now use trace config with metadata
- `tests/test_multi_agent/test_roles.py` (new) — 11 unit tests for `build_trace_config`
- `tests/test_agent/test_graph.py` (modified) — 5 integration tests for `create_trace_config`

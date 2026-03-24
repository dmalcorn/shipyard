# Story 3.4: Architect Decision & Fix Pipeline

Status: complete

## Story

As a developer,
I want an Architect Agent to evaluate review findings and produce a fix plan that a fresh Dev Agent executes,
so that only validated issues are fixed and the fix agent isn't polluted by the original implementation context.

## Acceptance Criteria

1. **Given** the Architect Agent receives both review files **When** it evaluates findings **Then** it produces a `fix-plan.md` with: which findings to fix (with justification), which to dismiss (with justification), and specific fix instructions per item
2. **Given** a fix plan exists **When** the orchestrator spawns a Fix Dev Agent **Then** it is a fresh Dev Agent (no shared history with original Dev) that reads the fix plan and executes the approved fixes
3. **Given** the Fix Dev Agent completes fixes **When** unit tests are run **Then** all tests pass before proceeding to CI

## Tasks / Subtasks

- [x] Task 1: Implement `architect_node` in orchestrator (AC: #1)
  - [x] Spawn an Architect Agent via `run_sub_agent(role="architect", ...)`
  - [x] Pass both review files as context: `reviews/review-agent-1.md`, `reviews/review-agent-2.md`
  - [x] Also pass the list of modified source files so the Architect can read the actual code
  - [x] Architect uses Opus model tier (via role config from Story 3.1)
  - [x] Task description instructs it to triage findings and write fix-plan.md
- [x] Task 2: Define `fix-plan.md` output format (AC: #1)
  - [x] Format included in architect_node task description with YAML frontmatter template
  - [x] Added `fix-plan.md` to `.gitignore`
- [x] Task 3: Implement `fix_dev_node` in orchestrator (AC: #2)
  - [x] Spawn a Fix Dev Agent via `run_sub_agent(role="fix_dev", ...)`
  - [x] Fix Dev Agent is FRESH — run_sub_agent creates unique thread_id, no shared history
  - [x] Pass `fix-plan.md` as the primary context file plus source files
  - [x] Task description includes scope discipline instructions
- [x] Task 4: Implement post-fix test gate (AC: #3)
  - [x] `run_test_gate` runs `pytest tests/ -v` via subprocess
  - [x] If tests pass: route to END
  - [x] If tests fail: route back to `fix_dev_node` for correction (up to 5 cycles)
  - [x] Track `fix_cycle_count` in orchestrator state
  - [x] `halt_node` reports failure when retry limit exceeded
- [x] Task 5: Wire architect → fix_dev → test_gate edges in orchestrator (AC: #1-#3)
  - [x] `collect_reviews` → `architect_node` → `fix_dev_node` → `test_gate`
  - [x] `test_gate` conditional edge: pass → END, retry → `fix_dev_node`, halt → `halt` → END
  - [x] `OrchestratorState` includes `fix_cycle_count`, `test_passed`, `error` fields
- [x] Task 6: Write tests (AC: #1-#3)
  - [x] Test `architect_node` spawns Architect with Opus model tier
  - [x] Test `architect_node` passes both review files as context
  - [x] Test `fix_dev_node` spawns a fresh agent with role='fix_dev'
  - [x] Test `fix_dev_node` passes fix-plan.md as context
  - [x] Test `run_test_gate` routes to next stage on test pass
  - [x] Test `run_test_gate` routes back to fix_dev on test failure
  - [x] Test `run_test_gate` halts on retry limit exceeded

## Dev Notes

- **Primary files:** `src/multi_agent/orchestrator.py` (extend with architect + fix nodes)
- **Architect uses Opus:** This is the most expensive agent call. Keep context minimal — only pass review files and relevant source files, not the entire codebase.
- **Fresh Fix Dev is critical:** The Fix Dev Agent must NOT have access to the original Dev Agent's conversation history. This prevents the "sunk cost" bias where the agent defends its original implementation instead of objectively applying fixes. Fresh context = objective execution.
- **Fix plan is the single source of truth:** The Fix Dev Agent should ONLY fix what the Architect approved. No freelancing. The system prompt must be explicit about scope discipline.
- **Test gate retry limits:** Per architecture Decision 4: 5 test cycles. The fix_dev_node gets re-invoked with the failing test output as additional context so it knows what broke.
- **Bash scripts for tests:** `pytest` runs as a bash command (not an LLM call) to conserve tokens. The test output is captured and passed to the Fix Dev Agent if tests fail.
- **Do NOT let the Architect edit source** — Architect can only write to `fix-plan.md` and `reviews/`. Source edits are the Fix Dev Agent's job.

### Dependencies

- **Requires:** Story 3.1 (Agent Role Definitions) — Architect and Fix Dev role configs
- **Requires:** Story 3.2 (Sub-Agent Spawning) — `create_agent_subgraph()` for both agents
- **Requires:** Story 3.3 (Parallel Review Pipeline) — review files as input
- **Feeds into:** Story 3.5 (Full TDD Orchestrator) — architect+fix is a stage in the pipeline

### Project Structure Notes

- `fix-plan.md` — written to project root (or `reviews/fix-plan.md`), runtime artifact
- Add `fix-plan.md` to `.gitignore` if writing to project root

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 2: Multi-Agent Coordination Pattern — sequential subgraphs]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 4: Retry Limits — 5 test cycles]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 5: Working Directory — Architect read reviews + write fix plan only]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 3: File-Based Communication Format]
- [Source: _bmad-output/project-context.md#Model Routing — Opus for Architect]
- [Source: coding-standards.md#File-Based Communication Format]

## Dev Agent Record

### Agent Model Used
claude-opus-4-6

### Debug Log References
N/A

### Completion Notes List
- Architect node and fix_dev_node both implemented in `orchestrator.py` alongside Story 3.3 nodes
- `run_test_gate` named to avoid pytest collecting `test_gate_node` as a test function
- Fix Dev gets additional context about fix cycle number on retries
- `halt_node` sets error message in state for pipeline reporting
- `build_orchestrator_graph()` returns uncompiled StateGraph for caller to compile with checkpointer

### File List
- `src/multi_agent/orchestrator.py` — architect_node, fix_dev_node, run_test_gate, halt_node, route_after_test_gate, build_orchestrator_graph
- `tests/test_multi_agent/test_orchestrator.py` — TestArchitectNode, TestFixDevNode, TestTestGate, TestRouteAfterTestGate, TestBuildOrchestratorGraph
- `.gitignore` — added `fix-plan.md`

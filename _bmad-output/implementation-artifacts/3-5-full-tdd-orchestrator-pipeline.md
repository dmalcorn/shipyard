# Story 3.5: Full TDD Orchestrator Pipeline

Status: complete

## Story

As a developer,
I want the complete pipeline (Test → Dev → CI → Review → Architect → Fix → CI → System Tests → Push) wired as a parent StateGraph,
so that I can give Shipyard a feature spec and it delivers tested, reviewed, committed code.

## Acceptance Criteria

1. **Given** the orchestrator receives a task (epic/story spec) **When** the pipeline runs **Then** it executes in this order: Test Agent → Dev Agent → unit tests → local CI → git snapshot → 2 Review Agents (parallel) → Architect → Fix Dev → unit tests → local CI → system tests → local CI (final gate) → git commit and push
2. **Given** any test or CI failure in the pipeline **When** the failure occurs **Then** it routes back to the appropriate agent for correction (per retry limits: 3 edit, 5 test, 3 CI)
3. **Given** retry limits are exceeded **When** the error handler fires **Then** it halts the pipeline and produces a failure report with what went wrong
4. **Given** bash scripts for CI, testing, and git **When** they run **Then** they execute as bash commands (not LLM calls) to conserve token cost

## Tasks / Subtasks

- [x] Task 1: Define `OrchestratorState` schema (AC: #1-#3)
  - [x] Extend `AgentState` or create a new TypedDict for the orchestrator:
    ```python
    class OrchestratorState(TypedDict):
        task_id: str
        task_description: str
        context_files: list[str]
        current_phase: str  # test|dev|unit_test|ci|git_snapshot|review|architect|fix|system_test|push
        files_modified: Annotated[list[str], operator.add]
        test_cycle_count: int
        ci_cycle_count: int
        edit_retry_count: int
        error_log: list[str]
        review_files: list[str]
        fix_plan_path: str
        pipeline_status: str  # running|completed|failed
    ```
  - [x] Include all retry counters for circuit breaking
- [x] Task 2: Build the parent `StateGraph` with all pipeline nodes (AC: #1)
  - [x] Create nodes (in execution order):
    1. `test_agent_node` — spawns Test Agent to write failing tests from spec
    2. `dev_agent_node` — spawns Dev Agent to implement code that passes tests
    3. `unit_test_node` — runs `pytest tests/ -v` via bash (NOT an LLM call)
    4. `ci_node` — runs `bash scripts/local_ci.sh` (ruff + mypy + pytest)
    5. `git_snapshot_node` — runs `bash scripts/git_snapshot.sh` (git add + commit)
    6. `review_node` — Review Agent subgraph (reused for both reviewers via Send)
    7. `collect_reviews_node` — reads review files after parallel reviews complete
    8. `architect_node` — spawns Architect Agent (from Story 3.4)
    9. `fix_dev_node` — spawns Fix Dev Agent (from Story 3.4)
    10. `post_fix_test_node` — runs pytest again after fixes
    11. `post_fix_ci_node` — runs local CI after fixes pass
    12. `system_test_node` — runs system/integration tests
    13. `final_ci_node` — final CI gate
    14. `git_push_node` — git commit and push
    15. `error_handler_node` — produces failure report on limit exceeded
  - [x] Wire edges in sequence with conditional routing for failures
- [x] Task 3: Implement bash-based nodes (AC: #4)
  - [x] `unit_test_node`: `run_command("pytest tests/ -v")` — capture output, parse pass/fail
  - [x] `ci_node`: `run_command("bash scripts/local_ci.sh")` — capture exit code
  - [x] `git_snapshot_node`: `run_command("bash scripts/git_snapshot.sh '{message}'")` — creates snapshot commit
  - [x] `system_test_node`: `run_command("pytest tests/ -v --system")` or equivalent system test marker
  - [x] `git_push_node`: `run_command("git push")` — final push after all gates pass
  - [x] These nodes call bash directly — NO LLM invocation, just command execution and result parsing
- [x] Task 4: Implement conditional routing for failures (AC: #2)
  - [x] After `unit_test_node`: pass → `ci_node`, fail → `dev_agent_node` (test_cycle_count < 5)
  - [x] After `ci_node`: pass → `git_snapshot_node`, fail → `dev_agent_node` (ci_cycle_count < 3)
  - [x] After `post_fix_test_node`: pass → `post_fix_ci_node`, fail → `fix_dev_node` (test_cycle_count < 5)
  - [x] After `post_fix_ci_node`: pass → `system_test_node`, fail → `fix_dev_node` (ci_cycle_count < 3)
  - [x] After `system_test_node`: pass → `final_ci_node`, fail → route to dev or fix agent
  - [x] After `final_ci_node`: pass → `git_push_node`, fail → error handler
  - [x] All failure routes increment the appropriate retry counter in state
  - [x] Pass failing output as context to the retry agent so it knows what broke
- [x] Task 5: Implement error handler node (AC: #3)
  - [x] `error_handler_node` produces a structured failure report:
    ```markdown
    # Pipeline Failure Report
    ## Task: {task_id}
    ## Failed Phase: {current_phase}
    ## Retry Counts: edit={n}/3, test={n}/5, CI={n}/3
    ## Error Log:
    {accumulated errors from error_log state field}
    ## Files Modified:
    {list of files touched during the run}
    ```
  - [x] Set `pipeline_status = "failed"`
  - [x] Log to audit logger (Story 2.2)
- [x] Task 6: Implement `Send` API integration for review phase (AC: #1)
  - [x] Reuse `route_to_reviewers` from Story 3.3
  - [x] Wire: `git_snapshot_node` → conditional edge → `route_to_reviewers` → `review_node` (×2 parallel) → `collect_reviews_node`
- [x] Task 7: Create the compiled orchestrator graph (AC: #1)
  - [x] `build_orchestrator() -> CompiledGraph` — assembles the full pipeline
  - [x] Compile with checkpointing so pipeline can resume on crash
  - [x] Entry point: invoke with `task_description` and `context_files`
- [x] Task 8: Write tests (AC: #1-#4)
  - [x] Test `OrchestratorState` has all required fields
  - [x] Test pipeline node count and edge connections
  - [x] Test conditional routing: unit test fail → dev agent retry
  - [x] Test conditional routing: CI fail → dev agent retry
  - [x] Test retry limit exceeded → error handler
  - [x] Test bash nodes do NOT invoke LLM (verify no ChatAnthropic calls)
  - [x] Test error handler produces failure report with correct format
  - [x] Integration test: run pipeline with a simple task end-to-end (mock LLM calls)

## Dev Notes

- **Primary file:** `src/multi_agent/orchestrator.py` — this is the main file for the full pipeline
- **This is the most complex story in Epic 3.** It wires together everything from Stories 3.1-3.4.
- **Bash nodes are NOT LLM calls.** This is a critical cost optimization. Tests, CI, and git operations run as shell commands. The output is captured and used for routing decisions (pass/fail) and as context for retry agents.
- **Pipeline execution order (happy path):**
  1. Test Agent writes failing tests from the feature spec
  2. Dev Agent implements code to pass the tests (TDD)
  3. `pytest` runs — must pass
  4. `local_ci.sh` runs (ruff + mypy + pytest) — must pass
  5. `git_snapshot.sh` creates a checkpoint commit
  6. 2 Review Agents analyze code in parallel (Send API)
  7. Architect evaluates reviews, writes fix plan
  8. Fix Dev Agent applies approved fixes
  9. `pytest` runs again — must pass
  10. `local_ci.sh` runs again — must pass
  11. System tests run — must pass
  12. Final CI gate — must pass
  13. Git commit and push
- **Retry routing logic:** When a failure occurs, the failing output (stderr, test output, etc.) is added to the retry agent's context so it knows exactly what to fix. Don't just re-run blindly.
- **State management:** Each phase transition updates `current_phase` in state. This enables LangSmith trace filtering by phase and drives conditional routing.
- **Global 50-turn cap:** Still applies per sub-agent. The orchestrator itself doesn't count LLM turns (it's mostly bash nodes and sub-agent invocations).

### Dependencies

- **Requires:** Story 3.1 (Agent Role Definitions) — all role configs
- **Requires:** Story 3.2 (Sub-Agent Spawning) — `create_agent_subgraph()`
- **Requires:** Story 3.3 (Parallel Review Pipeline) — Send API review nodes
- **Requires:** Story 3.4 (Architect Decision & Fix) — architect + fix dev nodes
- **Requires:** Story 1.4 (Core Agent Loop) — StateGraph patterns
- **Requires:** Story 2.2 (Markdown Audit Logger) — logging pipeline events
- **Feeds into:** Story 3.6 (CODEAGENT.md Multi-Agent Design) — documents this pipeline
- **Feeds into:** Story 4.2 (Ship App Rebuild) — uses this pipeline to rebuild Ship

### Project Structure Notes

- `src/multi_agent/orchestrator.py` — main orchestrator graph, the hub of Epic 3
- `scripts/local_ci.sh` — already exists from Story 1.1
- `scripts/git_snapshot.sh` — may need creation if not already present
- `scripts/run_tests.sh` — already in architecture doc structure

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 1: Graph Topology — Custom StateGraph]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 2: Multi-Agent Coordination Pattern — full pipeline]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 4: Retry Limits — 3 edit, 5 test, 3 CI]
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Flow diagram — complete pipeline]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.5 — execution order specification]
- [Source: _bmad-output/project-context.md#Retry Limits — Circuit Breakers]
- [Source: coding-standards.md#Quality Enforcement — local CI pipeline]

## Dev Agent Record

### Agent Model Used
Claude Opus 4.6

### Debug Log References
N/A — all tests pass locally (291/291)

### Completion Notes List
- Extended `OrchestratorState` with full pipeline fields: `task_description`, `context_files`, `files_modified` (Annotated reducer), `current_phase`, `pipeline_status`, `test_cycle_count`, `ci_cycle_count`, `edit_retry_count`, `error_log` (Annotated reducer), `last_test_output`, `last_ci_output`
- Implemented 16 graph nodes: 5 LLM agent nodes (test_agent, dev_agent, review×2, architect, fix_dev) + 8 bash nodes (unit_test, ci, git_snapshot, post_fix_test, post_fix_ci, system_test, final_ci, git_push) + error_handler
- Bash nodes use shared `_run_bash()` helper — no LLM invocation, verified by test
- Conditional routing at 6 failure points with retry limits: 5 test cycles, 3 CI cycles, 3 edit retries
- Error handler produces structured markdown failure report
- Preserved all Story 3.3-3.4 functionality (parallel review, architect, fix dev)
- Added `build_orchestrator()` for compiled graph with optional checkpointer
- Added `testpaths = ["tests"]` to pyproject.toml to prevent pytest from collecting source functions named `test_*`
- 65 orchestrator tests + 291 total suite tests, all passing

### File List
- `src/multi_agent/orchestrator.py` — Full TDD pipeline StateGraph (rewritten)
- `tests/test_multi_agent/test_orchestrator.py` — 65 tests covering all 8 story tasks (rewritten)
- `pyproject.toml` — Added `[tool.pytest.ini_options]` testpaths

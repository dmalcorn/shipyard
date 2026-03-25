# Story 4.4: Defect — working_dir Not Threaded Through Orchestrator to Sub-Agents

Status: review

Type: defect

## Story

As a developer running a rebuild against an external target directory,
I expect all sub-agents and bash nodes to operate within my specified `target_dir`,
but currently the orchestrator ignores `target_dir` and all agents default to Shipyard's CWD.

## Problem Description

The scoped-tools infrastructure is fully built (`src/tools/scoped.py`, `get_tools_for_role(working_dir=...)`, `run_sub_agent(working_dir=...)`), but the orchestrator pipeline never wires `target_dir` through to the agents that need it.

### Root Cause

1. **`OrchestratorState` has no `working_dir` field** — there is no way to carry the target directory through the state graph ([orchestrator.py:50-89](src/multi_agent/orchestrator.py#L50-L89))
2. **`_run_story_pipeline()` drops `target_dir` on the floor** — it receives `target_dir` as a parameter but never puts it into the initial state ([rebuild.py:258-306](src/intake/rebuild.py#L258-L306))
3. **All 5 LLM agent nodes call `run_sub_agent()` without `working_dir`** — `test_agent_node`, `dev_agent_node`, `review_node`, `architect_node`, `fix_dev_node` all omit the parameter ([orchestrator.py:179-458](src/multi_agent/orchestrator.py#L179-L458))
4. **All bash nodes run without `cwd`** — `unit_test_node`, `ci_node`, `system_test_node`, `git_snapshot_node`, `git_push_node` all call `_run_bash()` which uses `subprocess.run()` without setting `cwd` ([orchestrator.py:142-164](src/multi_agent/orchestrator.py#L142-L164))

### Impact

When `--rebuild /some/external/path` is used, agents operate on Shipyard's own source tree instead of the target project. The sandbox enforcement in `scoped.py` is never activated.

## Acceptance Criteria

1. **Given** a rebuild is started with `target_dir=/any/path` **When** any sub-agent is spawned **Then** `run_sub_agent()` receives `working_dir=target_dir` and the agent's tools are scoped to that directory
2. **Given** a rebuild is running **When** bash nodes execute tests, CI, or git commands **Then** they run with `cwd=target_dir` so they operate on the target project, not Shipyard
3. **Given** `target_dir` is an absolute path outside Shipyard's tree **When** the pipeline runs **Then** all file operations stay within `target_dir` (scoped tools enforce the sandbox)
4. **Given** `target_dir` is a relative path like `./target/` **When** the pipeline runs **Then** it is resolved to an absolute path before being threaded through the orchestrator
5. **Given** the existing test suite **When** these changes are applied **Then** all existing orchestrator tests continue to pass (backward compatible — `working_dir` defaults to `None` when not in rebuild mode)

## Tasks / Subtasks

- [x] Task 1: Add `working_dir` field to `OrchestratorState` (AC: #1, #5)
  - Add `working_dir: str` as an optional field (default empty string) to the `OrchestratorState` TypedDict in `src/multi_agent/orchestrator.py`
  - Add `working_dir` to `ReviewNodeInput` so it flows through the Send API fan-out

- [x] Task 2: Thread `working_dir` through all LLM agent nodes (AC: #1, #3)
  - `test_agent_node`: read `working_dir` from state, pass to `run_sub_agent(working_dir=...)`
  - `dev_agent_node`: same
  - `review_node`: same (read from `ReviewNodeInput`)
  - `architect_node`: same
  - `fix_dev_node`: same
  - When `working_dir` is empty/None, behavior is unchanged (backward compat)

- [x] Task 3: Thread `working_dir` through all bash nodes (AC: #2, #3)
  - Update `_run_bash()` to accept an optional `cwd` parameter and pass it to `subprocess.run()`
  - `unit_test_node`, `ci_node`, `post_fix_test_node`, `post_fix_ci_node`, `system_test_node`, `final_ci_node`: read `working_dir` from state, pass as `cwd` to `_run_bash()`
  - `git_snapshot_node`, `git_push_node`: same — git commands must run in the target repo
  - `_ensure_reviews_dir()` and `_review_file_path()`: make paths relative to `working_dir` when set

- [x] Task 4: Wire `target_dir` from `_run_story_pipeline()` into `OrchestratorState` (AC: #1, #4)
  - In `rebuild.py::_run_story_pipeline()`, resolve `target_dir` to an absolute path via `os.path.abspath()`
  - Set `working_dir` in the `initial_state` dict passed to `compiled.invoke()`

- [x] Task 5: Write/update tests (AC: #1-#5)
  - Test that `OrchestratorState` accepts `working_dir` and it propagates through the graph
  - Test that `_run_bash()` passes `cwd` to `subprocess.run()` when provided
  - Test that `_run_story_pipeline()` resolves relative paths to absolute
  - Verify existing orchestrator tests still pass without `working_dir` set

## Dev Notes

- **This is a wiring defect, not a design issue.** The scoped tools in `src/tools/scoped.py` already work correctly — they just never get activated because the orchestrator doesn't pass `working_dir` down.
- **Story 4.2 spec called for this** — Task 2 in Story 4.2 explicitly says "Add a `working_dir` parameter to `run_sub_agent()` that sets the current working directory for all tool operations within the sub-agent." The parameter exists on `run_sub_agent()` but is never used by the orchestrator nodes.
- **`run_sub_agent()` and `create_agent_subgraph()` already accept `working_dir`** — see `src/multi_agent/spawn.py:49-54` and `src/multi_agent/spawn.py:132-141`. No changes needed there.
- **Backward compatibility:** When `working_dir` is not set (standalone orchestrator usage, not rebuild mode), all behavior must remain identical. The field should default to empty string in state and all threading should be conditional on it being non-empty.
- **The `_run_bash` helper also needs `cwd`** — without it, `pytest`, `ruff`, `mypy`, and git commands all run against Shipyard's repo, not the target project.

## Dev Agent Record

### Implementation Plan
Wiring defect fix — thread `working_dir` through the entire orchestrator pipeline:
1. Added `working_dir: str` to `OrchestratorState` and `ReviewNodeInput`
2. All 5 LLM agent nodes now read `working_dir` from state and pass to `run_sub_agent(working_dir=...)`
3. `_run_bash()` accepts optional `cwd` param, all 8 bash nodes pass `working_dir` as `cwd`
4. `_ensure_reviews_dir()` and `_review_file_path()` accept optional `working_dir` to scope review file paths
5. `_run_story_pipeline()` resolves `target_dir` to absolute path and sets `working_dir` in initial state

### Debug Log
- Existing tests used `assert_called_once_with` without `cwd` kwarg — updated 3 assertions to include `cwd=None`
- Pre-existing failures: `test_architect_uses_opus_model_tier` (roles.py has `# TESTING` overrides), scaffold tests for missing `src/logging/__init__.py`

### Completion Notes
- All 5 acceptance criteria satisfied
- 25 new tests added covering state schema, bash cwd threading, LLM agent working_dir threading, and rebuild path resolution
- All 413 tests pass; 9 pre-existing failures unrelated to this story
- Backward compatible: empty/missing `working_dir` produces `cwd=None` / `working_dir=None` (no behavior change)

## File List
- `src/multi_agent/orchestrator.py` — added `working_dir` to state schemas, threaded through all nodes
- `src/intake/rebuild.py` — resolves `target_dir` to absolute, sets `working_dir` in initial state
- `tests/test_multi_agent/test_orchestrator.py` — 25 new tests, 3 updated assertions
- `tests/test_intake/test_rebuild.py` — 2 new tests for `_run_story_pipeline` working_dir wiring

## Change Log
- 2026-03-24: Fixed working_dir threading defect — all orchestrator nodes now propagate working_dir to sub-agents and bash commands

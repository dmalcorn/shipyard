# Story 4.5: Defect — Scoped Tools Gaps: Context Injection, Write Restrictions, and Cleanup

Status: review

Type: defect

## Story

As a developer running a rebuild against an external target directory,
I expect context files to be read from the target project, write restrictions to be enforced per role even in scoped mode, and the working_dir plumbing to be consistent and type-safe.

## Problem Description

Code review of Story 4.4 surfaced five issues — two functional gaps pre-existing in the scoped tools infrastructure (Stories 4.2 / 3.1) and three code quality issues introduced by 4.4's repetitive wiring pattern.

### Intent Gap #6: context_files paths not resolved relative to working_dir

`build_system_prompt()` and `inject_task_context()` in `src/context/injection.py` read context files via `_read_file_safe(file_path)`, which opens paths relative to Shipyard's process CWD. In rebuild mode, context_files are relative paths that exist in the target dir (e.g., `src/main.py`), not in Shipyard's tree. Result: context injection silently fails or reads wrong files.

**Affected call chain:** orchestrator agent nodes → `run_sub_agent(context_files=...)` → `create_agent_subgraph()` → `build_system_prompt()` / `inject_task_context()` — neither receives `working_dir`.

### Intent Gap #7: write_restrictions bypassed when working_dir is set

`get_tools_for_role()` in `src/multi_agent/roles.py` (line 146-156) short-circuits to scoped tools when `working_dir` is set, skipping the `write_restrictions` branch entirely. Roles like `reviewer` (restricted to `reviews/`) and `test` (restricted to `tests/`) get unrestricted write access anywhere inside the target dir. The scoped tools in `src/tools/scoped.py` have no awareness of role-based write restrictions.

### Defer #8: Empty-string sentinel for "no working_dir" repeated in ~15 places

Every orchestrator node does `state.get("working_dir", "") then `working_dir or None`. This pattern is repeated ~15 times, increasing the risk of a missed guard.

### Defer #9: ReviewNodeInput.working_dir is required but should be NotRequired

`ReviewNodeInput` is `total=True` by default, making `working_dir` a required field. Inconsistent with `OrchestratorState`'s `total=False`. TypedDict not enforced at runtime, but a type-level correctness issue.

### Defer #10: route_to_reviewers passes working_dir raw without or None guard

`route_to_reviewers` passes the raw string to `ReviewNodeInput` without the `or None` guard used at every other call site. Safe because downstream applies the guard, but inconsistent with the pattern.

## Acceptance Criteria

1. **Given** context_files with relative paths in rebuild mode **When** `build_system_prompt()` or `inject_task_context()` is called **Then** paths are resolved relative to `working_dir`, not Shipyard's CWD
2. **Given** a role with `write_restrictions` (reviewer, test, architect) in rebuild mode **When** scoped tools are created **Then** write restrictions are enforced within the target dir (e.g., reviewer can only write to `{target_dir}/reviews/`)
3. **Given** the orchestrator pipeline **When** `working_dir` is read from state **Then** a single helper normalizes the empty-string-to-None conversion, eliminating the repeated `or None` pattern
4. **Given** `ReviewNodeInput` **When** type-checked **Then** `working_dir` is `NotRequired[str]`, consistent with the optional semantics
5. **Given** all call sites passing `working_dir` **When** reviewed **Then** the `or None` guard is applied consistently (or unnecessary due to the helper from AC#3)
6. **Given** the existing test suite **When** these changes are applied **Then** all existing tests continue to pass

## Tasks / Subtasks

- [x] Task 1: Add `working_dir` parameter to context injection functions (AC: #1)
  - Update `build_system_prompt(role, context_files, working_dir=None)` in `src/context/injection.py`
  - Update `inject_task_context(instruction, context_files, working_dir=None)` in `src/context/injection.py`
  - In `_read_file_safe()`, when `working_dir` is set, resolve relative paths against it
  - Thread `working_dir` from `create_agent_subgraph()` in `src/multi_agent/spawn.py` through to both functions

- [x] Task 2: Integrate write_restrictions into scoped tools (AC: #2)
  - Update `get_scoped_tools(working_dir, write_restrictions=None)` in `src/tools/scoped.py` to accept optional write restrictions
  - When `write_restrictions` is provided, the scoped `write_file` and `edit_file` tools must validate paths against both the sandbox boundary AND the role's allowed prefixes
  - Update `get_tools_for_role()` in `src/multi_agent/roles.py` to pass `role_config.write_restrictions` to `get_scoped_tools()` when `working_dir` is set

- [x] Task 3: Extract working_dir helper to eliminate repeated sentinel pattern (AC: #3, #5)
  - Add a helper function (e.g., `_get_working_dir(state)`) in `src/multi_agent/orchestrator.py` that returns `state.get("working_dir") or None`
  - Replace all ~15 instances of the `state.get("working_dir", "")` / `working_dir or None` pattern with the helper

- [x] Task 4: Fix ReviewNodeInput type and route_to_reviewers guard (AC: #4, #5)
  - Change `ReviewNodeInput` to use `total=False` or mark `working_dir` as `NotRequired[str]`
  - Apply consistent `or None` guard in `route_to_reviewers` (or delegate to the helper from Task 3)

- [x] Task 5: Write/update tests (AC: #1-#6)
  - Test `build_system_prompt()` and `inject_task_context()` resolve paths relative to `working_dir`
  - Test scoped tools enforce write_restrictions (reviewer can't write outside `reviews/` in target dir)
  - Test the helper function returns None for empty/missing `working_dir`
  - Verify existing tests pass unchanged

## Dev Notes

- **#6 and #7 are pre-existing gaps** — not caused by Story 4.4. They exist because Story 4.2 (scoped tools) and Story 3.1 (write restrictions) were implemented independently and never integrated. Story 4.4 just made the gap visible by wiring `working_dir` through the orchestrator.
- **For Task 1**, the key change is in `spawn.py::create_agent_subgraph()` — it already has `working_dir` and calls both `build_system_prompt()` and `inject_task_context()`. Just thread it through.
- **For Task 2**, the scoped `write_file`/`edit_file` in `scoped.py` already validate the sandbox boundary. Adding write_restrictions is a second validation layer: after confirming the path is inside `target_dir`, also confirm it matches the role's allowed prefixes (reuse `_is_path_allowed()` from `src/tools/restricted.py`).
- **For Task 3**, the helper is a one-liner but eliminates a class of copy-paste bugs. Place it near the top of `orchestrator.py` with the other helpers.

## Dev Agent Record

### Implementation Plan
- Task 1: Added `working_dir` param to `_read_file_safe()`, `build_system_prompt()`, `inject_task_context()` in injection.py. Threaded through from `create_agent_subgraph()` in spawn.py.
- Task 2: Added `write_restrictions` param to `get_scoped_tools()` in scoped.py with `_check_write_restrictions()` helper that reuses `_is_path_allowed()` from restricted.py. Updated `get_tools_for_role()` to pass role's write_restrictions when working_dir is set.
- Task 3: Added `_get_working_dir(state)` helper in orchestrator.py. Replaced all ~15 sentinel patterns across every orchestrator node.
- Task 4: Changed `ReviewNodeInput.working_dir` to `NotRequired[str]`. Refactored `route_to_reviewers` to conditionally include working_dir.
- Task 5: Added 22 new tests covering all ACs.

### Completion Notes
All 5 tasks complete. 443 tests pass, 9 pre-existing failures (model tier TESTING overrides + missing src/logging dir) — none related to this story.

## File List
- src/context/injection.py (modified — added working_dir param)
- src/tools/scoped.py (modified — added write_restrictions param)
- src/multi_agent/roles.py (modified — pass write_restrictions to scoped tools)
- src/multi_agent/orchestrator.py (modified — helper, ReviewNodeInput, sentinel cleanup)
- src/multi_agent/spawn.py (modified — thread working_dir to injection functions)
- tests/test_context/test_injection.py (modified — 5 new tests)
- tests/test_tools/test_scoped.py (modified — 7 new tests)
- tests/test_multi_agent/test_roles.py (modified — 3 new tests)
- tests/test_multi_agent/test_orchestrator.py (modified — 7 new tests)

## Change Log
- Story 4.5 implemented: Fixed context injection working_dir resolution, integrated write_restrictions into scoped tools, extracted _get_working_dir helper, fixed ReviewNodeInput type (2026-03-24)

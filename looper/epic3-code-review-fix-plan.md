# Epic 3 — Code Review Fix Plan

**Date:** 2026-03-24
**Scope:** Category A issues only — clear, non-controversial fixes
**Total fixes:** 28

Items are classified **not in** `epic3-architect-review-needed.md`. No overlap.

---

## P0 — Security (1 issue)

### A-01: Path traversal bypass in `_is_path_allowed`

- **File:** `src/tools/restricted.py:27`
- **Found by:** Both agents (BMAD 3-1#1,5 + Claude 3-1#1)
- **Issue:** `lstrip("./")` strips a *character set*, not a prefix. It does not collapse `..` sequences. A path like `reviews/../src/main.py` normalizes to `reviews/../src/main.py`, which starts with `reviews/` and passes the prefix check but resolves to `src/main.py`.
- **Fix:** Add `os.path.normpath()` after slash normalization, before prefix matching:
  ```python
  import posixpath
  normalized = posixpath.normpath(file_path.replace("\\", "/"))
  ```
  Then re-strip any leading `./` that normpath may produce. Ensure `..` at the start (escaping project root) is also rejected.
- **Verify:** Add test cases: `"reviews/../src/main.py"` → rejected; `"reviews/../../etc/passwd"` → rejected; `"reviews/valid.md"` → allowed.

---

## P1 — Breaking Logic / Bugs (6 issues)

### A-02: `review_file_paths` missing `operator.add` reducer

- **File:** `src/multi_agent/orchestrator.py:72`
- **Found by:** Both agents (across stories 3-3, 3-4, 3-6)
- **Issue:** Two parallel `review_node` instances (via Send API) each return `{"review_file_paths": [path]}`. Without an `operator.add` reducer, the second overwrites the first during state merge. Masked by `collect_reviews` re-deriving paths from filesystem, but state is semantically broken.
- **Fix:** Change line 72 from:
  ```python
  review_file_paths: list[str]
  ```
  to:
  ```python
  review_file_paths: Annotated[list[str], operator.add]
  ```
- **Verify:** `ruff check`, `mypy`, existing tests pass. Optionally add a test that two review_node returns merge correctly.

### A-03: `edit_retry_count` never incremented — fix-dev retry context dead

- **File:** `src/multi_agent/orchestrator.py:78` (state), `421,432` (read only)
- **Found by:** Both agents (BMAD 3-4#1,6 + Claude 3-4#1)
- **Issue:** `fix_dev_node` reads `edit_retry_count` (line 421) and conditionally appends test failure context (line 432: `if edit_retry > 0 and last_test_output`). But no node ever increments `edit_retry_count`. The Fix Dev Agent is re-invoked blind on every retry — same instructions, no context about what broke. The retry context block is dead code.
- **Fix:** In `post_fix_test_node`, when tests fail and routing returns to `fix_dev_node`, include `edit_retry_count` increment in the returned state:
  ```python
  "edit_retry_count": state.get("edit_retry_count", 0) + 1,
  ```
- **Verify:** Add test: after `post_fix_test_node` returns failure, verify `edit_retry_count` is incremented in state. Verify `fix_dev_node` includes test output in task description when `edit_retry_count > 0`.

### A-04: SQLite connection leak — never closed

- **File:** `src/multi_agent/spawn.py:113-114`
- **Found by:** Both agents (BMAD 3-2#1.1 + Claude 3-2#1)
- **Issue:** Every call to `create_agent_subgraph()` opens `sqlite3.connect()` but the connection is never closed. `SqliteSaver` does not take ownership of closing it. Over a full pipeline (5+ sub-agents), file descriptors leak.
- **Fix:** Return the connection alongside the graph so the caller can close it, or use `SqliteSaver.from_conn_string()` which manages its own connection. Simplest fix — store `conn` in a list and close after `compiled.invoke()`:
  ```python
  # In run_sub_agent, after compiled.invoke():
  conn.close()
  ```
  This requires `create_agent_subgraph` to also return the connection object.
- **Verify:** Add test that connection is closed after `run_sub_agent` completes (mock `sqlite3.connect` and verify `.close()` called).

### A-05: Python list repr injected as YAML in review task description

- **File:** `src/multi_agent/orchestrator.py:311`
- **Found by:** BMAD 3-6#4
- **Issue:** `f"input_files: {files_to_review}\n"` produces `input_files: ['src/foo.py', 'tests/test_a.py']` — Python list repr with single quotes. This is not valid YAML. If the review agent copies this into its output frontmatter, the YAML is malformed.
- **Fix:** Format as YAML-compatible list:
  ```python
  f"input_files: [{', '.join(files_to_review)}]\n"
  ```
  Or use a multi-line YAML list format.
- **Verify:** Inspect the generated task description string for valid YAML syntax.

### A-06: `error_log` accumulator field never populated

- **File:** `src/multi_agent/orchestrator.py:86` (defined), `626` (read)
- **Found by:** BMAD 3-6#6
- **Issue:** `error_log: Annotated[list[str], operator.add]` has a reducer but no node ever returns `error_log` entries. The `error_handler_node` reads it (line 626) but it's always empty. The "Error Log" section in error reports is always "No errors captured."
- **Fix:** In each node that detects a failure, include an `error_log` entry in the return dict:
  ```python
  "error_log": [f"{current_phase}: {description_of_error}"],
  ```
  Specific nodes: `collect_reviews` (when < 2 valid reviews), `post_fix_test_node` (when tests fail), `post_fix_ci_node` (when CI fails).
- **Verify:** Add test: simulate a test failure node, verify `error_log` accumulates the message.

---

## P2 — Spec Compliance / Correctness (12 issues)

### A-07: Fix Dev prompt references wrong fix-plan path

- **File:** `src/agent/prompts.py:109`
- **Found by:** Both agents (BMAD 3-6#3 + Claude 3-6#1)
- **Issue:** FIX_DEV_AGENT_PROMPT says `"Read the fix plan from reviews/fix-plan.md"` but the orchestrator writes to `fix-plan.md` at project root (`orchestrator.py:30`: `FIX_PLAN_PATH = "fix-plan.md"`).
- **Fix:** Change line 109 from:
  ```
  1. Read the fix plan from reviews/fix-plan.md
  ```
  to:
  ```
  1. Read the fix plan from fix-plan.md
  ```
- **Verify:** Grep for `reviews/fix-plan.md` — should have zero hits after fix.

### A-08: Architect prompt says write to `reviews/` for fix plans

- **File:** `src/agent/prompts.py:82,91`
- **Found by:** Both agents (BMAD 3-6#17 + Claude 3-6#2)
- **Issue:** ARCHITECT_AGENT_PROMPT says "You CAN write fix plans to the reviews/ directory" (line 82) and "Write the fix plan to reviews/" (line 91). But the orchestrator instructs writing to `fix-plan.md` at project root. The write_restrictions correctly allow both `("reviews/", "fix-plan.md")`.
- **Fix:** Update lines 82 and 91:
  - Line 82: `"You CAN write fix plans to fix-plan.md at the project root"`
  - Line 91: `"Write the fix plan to fix-plan.md for a Dev Agent to execute"`
- **Verify:** Consistency check: `FIX_PLAN_PATH`, architect prompt, fix_dev prompt all reference `fix-plan.md` at project root.

### A-09: `PERMISSION_DENIED_MSG` text doesn't match AC#5

- **File:** `src/tools/restricted.py:19-21`
- **Found by:** Both agents (BMAD 3-1#10 + Claude 3-1#3)
- **Issue:** Code produces `"reviewer agents cannot edit source files. Write to reviews/ only."` AC#5 specifies `"Review agents cannot edit source files. Write to reviews/ directory only."` Two differences: (a) lowercase "reviewer" vs title-case "Review", (b) missing word "directory".
- **Fix:** Update the format string and ensure `role_name` parameter is passed as title-case:
  ```python
  PERMISSION_DENIED_MSG = (
      "ERROR: Permission denied: {role} agents cannot edit source files. "
      "Write to {allowed} directory only."
  )
  ```
  Also update the `create_restricted_write_file` call for reviewer to pass `role_name="Review"` (title case).
- **Verify:** Run test `test_path_validation_error_message_exact` after it's fixed to check exact equality (see A-23).

### A-10: Add "architect" to `VALID_PHASES`

- **File:** `src/multi_agent/roles.py:17`, `src/multi_agent/orchestrator.py:407`
- **Found by:** Both agents (BMAD 3-4#17 + Claude 3-4#7)
- **Issue:** `VALID_PHASES` is `{"test", "implementation", "review", "fix", "ci"}` — no "architect". The `architect_node` passes `current_phase="review"` as a workaround, causing LangSmith traces to mislabel architect activity as "review".
- **Fix:** Add "architect" to `VALID_PHASES` in `roles.py:17`. Change `architect_node` to pass `current_phase="architect"`.
- **Verify:** `build_trace_config(agent_role="architect", ..., phase="architect")` should not raise.

### A-11: Restricted tool functions lack exception handling

- **File:** `src/tools/restricted.py:57-62, 80-87`
- **Found by:** Claude 3-1#5
- **Issue:** The inner `write_file` and `edit_file` functions in restricted tool factories do not wrap `base_write_file.invoke()` / `base_edit_file.invoke()` in try/except. Per coding-standards.md: "Tools: catch all exceptions internally, return `ERROR:` strings (never let exceptions escape)."
- **Fix:** Wrap each invoke call:
  ```python
  try:
      result: str = base_write_file.invoke({"file_path": file_path, "content": content})
      return result
  except Exception as e:
      return f"ERROR: Failed to write {file_path}: {e}"
  ```
- **Verify:** `ruff check`, `mypy`. Optionally add test that triggers an exception in the base tool and verifies ERROR: string returned.

### A-12: `get_prompt()` docstring omits `fix_dev`

- **File:** `src/agent/prompts.py:134`
- **Found by:** Both agents (BMAD 3-1#4 + Claude 3-1#6)
- **Issue:** Docstring says `role: Agent role identifier (dev, test, reviewer, architect).` but `fix_dev` is also valid.
- **Fix:** Change to `(dev, test, reviewer, architect, fix_dev)`.
- **Verify:** Visual inspection.

### A-13: Restricted tool docstrings say "Used by: Dev, Architect"

- **File:** `src/tools/restricted.py:58,81`
- **Found by:** Both agents (BMAD 3-1#3 + Claude 3-1#8)
- **Issue:** The inner `write_file` says "Used by: Dev, Architect." and `edit_file` says "Used by: Dev, Architect." These are restricted versions — the "Used by" should reflect the restricted roles.
- **Fix:** Update docstrings:
  - `write_file`: `"Create or overwrite a file (path-restricted). Used by: Reviewer, Test, Architect."`
  - `edit_file`: `"Replace an exact string match (path-restricted). Used by: Test, Architect."`
- **Verify:** Visual inspection.

### A-14: Unused `logging` import in restricted.py

- **File:** `src/tools/restricted.py:10,17`
- **Found by:** Claude 3-1#7
- **Issue:** `import logging` and `logger = logging.getLogger(__name__)` defined but `logger` never used. Dead code.
- **Fix:** Remove lines 10 and 17.
- **Verify:** `ruff check` (should also flag this).

### A-15: Unnecessary f-string in `_format_allowed`

- **File:** `src/tools/restricted.py:41`
- **Found by:** Claude 3-1#11
- **Issue:** `f"{p}"` is equivalent to `str(p)`. Unnecessary f-string.
- **Fix:** Change `f"{p}" for p in allowed_prefixes` to `str(p) for p in allowed_prefixes` (or just `p` if prefixes are always strings).
- **Verify:** `ruff check`.

### A-16: `build_orchestrator` return type is `Any`

- **File:** `src/multi_agent/orchestrator.py:846`
- **Found by:** Claude 3-3#4
- **Issue:** `def build_orchestrator(checkpointer: Any = None) -> Any:` — the `Any` return type defeats mypy strict mode. Actual return type is a compiled graph.
- **Fix:** Import and use the concrete type:
  ```python
  from langgraph.graph.state import CompiledStateGraph
  def build_orchestrator(checkpointer: Any = None) -> CompiledStateGraph:
  ```
- **Verify:** `mypy src/multi_agent/orchestrator.py`.

### A-17: `create_agent_subgraph` return type uses `Any`

- **File:** `src/multi_agent/spawn.py:54`
- **Found by:** Both agents (BMAD 3-2#1.6/3.1 + Claude 3-2#8)
- **Issue:** Returns `tuple[Any, dict[str, Any]]`. The first element is a compiled graph. Story spec says `-> CompiledGraph`.
- **Fix:** Use the concrete type:
  ```python
  from langgraph.graph.state import CompiledStateGraph
  ) -> tuple[CompiledStateGraph, dict[str, Any]]:
  ```
- **Verify:** `mypy src/multi_agent/spawn.py`.

### A-18: `.gitkeep` missing `encoding="utf-8"`

- **File:** `src/multi_agent/orchestrator.py:119-120`
- **Found by:** Both agents (BMAD 3-3#1.4 + Claude 3-3#5)
- **Issue:** `with open(gitkeep, "w") as f:` omits encoding. All other file writes in the module specify `encoding="utf-8"`.
- **Fix:** Change to `with open(gitkeep, "w", encoding="utf-8") as f:`.
- **Verify:** Visual inspection.

---

## P2 continued — Additional Correctness (4 issues)

### A-19: `MAX_RETRIES` naming misleading

- **File:** `src/multi_agent/spawn.py:26`
- **Found by:** Claude 3-2#12
- **Issue:** `MAX_RETRIES = 50` is actually the max number of LLM turns per task, not retry attempts. project-context.md calls this "50 LLM turns per task".
- **Fix:** Rename to `MAX_TURNS` or `MAX_LLM_TURNS`. Update all references in spawn.py (lines 35, 45).
- **Verify:** Grep for `MAX_RETRIES` — should have zero hits after fix.

### A-20: `run_sub_agent` bypasses `build_trace_config()` validation

- **File:** `src/multi_agent/spawn.py:178-187`
- **Found by:** Both agents (BMAD 3-2#3.3 + Claude 3-2#3)
- **Issue:** `run_sub_agent` manually builds the config dict at lines 178-187. `roles.py:149-195` provides `build_trace_config()` which builds the same dict AND validates inputs against `VALID_AGENT_ROLES`, `VALID_MODEL_TIERS`, `VALID_PHASES`. The manual construction bypasses this validation.
- **Fix:** Replace manual config dict with:
  ```python
  config = build_trace_config(
      agent_role=role,
      task_id=task_id,
      model_tier=role_config.model_tier,
      phase=current_phase,
      parent_session=parent_session_id,
      thread_id=sub_thread_id,
  )
  ```
  May need to adjust `build_trace_config` signature if it doesn't accept all these params.
- **Verify:** `mypy`, existing tests pass.

### A-21: Redundant pytest instruction in `fix_dev_node`

- **File:** `src/multi_agent/orchestrator.py:429`
- **Found by:** BMAD 3-4#5
- **Issue:** Fix Dev Agent is instructed to `"Run pytest tests/ -v after all fixes"`, then the pipeline runs `post_fix_test_node` which runs pytest again. Duplicate testing wastes tokens.
- **Fix:** Remove the pytest instruction from `fix_dev_node`'s task description.
- **Verify:** Read the task description string — should not include pytest instruction.

### A-22: Ambiguous `current_phase` reuse in post-fix nodes

- **File:** `src/multi_agent/orchestrator.py:528,547`
- **Found by:** BMAD 3-6#8
- **Issue:** `post_fix_test_node` sets `current_phase: "unit_test"` and `post_fix_ci_node` sets `current_phase: "ci"` — same phase names as the initial pass. When the error handler reports "Failed Phase: ci", it's ambiguous whether first CI or post-fix CI failed.
- **Fix:** Use distinct names: `"post_fix_test"`, `"post_fix_ci"`. Add these to `VALID_PHASES` if needed.
- **Verify:** Check `error_handler_node` output distinguishes phases.

---

## P3 — Tests / Style (9 issues)

### A-23: Test `test_path_validation_error_message_exact` uses substring checks

- **File:** `tests/test_multi_agent/test_roles.py:352-359`
- **Found by:** Both agents (BMAD 3-1#12 + Claude 3-1#9)
- **Issue:** Despite its name `_exact`, the test only asserts `"ERROR: Permission denied:" in result` etc. as substrings. It would pass even with wrong casing or missing words.
- **Fix:** Assert exact string equality against the expected AC#5 message. Do this after A-09 (message text fix) is applied.
- **Verify:** Test passes with correct message, fails with wrong message.

### A-24: Tests use real `reviews/` directory instead of `tmp_path`

- **File:** `tests/test_multi_agent/test_orchestrator.py:644-689, 921-973`
- **Found by:** Both agents (BMAD 3-3#2.5 + Claude 3-3#2 + Claude 3-4#6)
- **Issue:** `TestCollectReviews`, `TestPrepareReviews`, and integration tests create/clean files in the real `reviews/` directory. Risks leaving artifacts, prevents parallel test execution, violates test isolation.
- **Fix:** Refactor to use pytest `tmp_path` fixture. Parameterize the reviews directory path so tests can inject a temp directory. May require making `REVIEWS_DIR` configurable or using `monkeypatch`.
- **Verify:** Run tests from a different CWD — they should still pass.

### A-25: Unnecessary `@patch` on test

- **File:** `tests/test_multi_agent/test_orchestrator.py:739-745`
- **Found by:** Both agents (Claude 3-3#7 + Claude 3-4#4)
- **Issue:** `test_architect_uses_opus_model_tier` applies `@patch("src.multi_agent.orchestrator.run_sub_agent")` but the `mock_run` parameter is never used.
- **Fix:** Remove the `@patch` decorator and `mock_run` parameter.
- **Verify:** Test still passes without the mock.

### A-26: `tmp_path` typed as `object` instead of `Path`

- **File:** `tests/test_multi_agent/test_spawn.py:18,101`
- **Found by:** Both agents (BMAD 3-2#3.5 + Claude 3-2#9)
- **Issue:** `tmp_path: object` forces `# type: ignore[operator]` on subsequent lines. The fixture returns `pathlib.Path`.
- **Fix:** `from pathlib import Path`, change to `tmp_path: Path`. Remove the `# type: ignore[operator]` comments.
- **Verify:** `mypy tests/test_multi_agent/test_spawn.py`.

### A-27: Test imports inside methods

- **File:** `tests/test_multi_agent/test_spawn.py:46,57,146,157,165,297`
- **Found by:** Both agents (BMAD 3-2#3.6 + Claude 3-2#10)
- **Issue:** Multiple test methods import `AIMessage`, `get_tools_for_role` inside the method body. Per coding standards, imports belong at the top of the file.
- **Fix:** Move all deferred imports to the module top-level import section.
- **Verify:** `ruff check`, `mypy`.

### A-28: `get_tools_for_role` raises raw `KeyError`

- **File:** `src/multi_agent/roles.py:144`
- **Found by:** BMAD 3-1#7
- **Issue:** `result.append(tools_by_name[tool_name])` raises raw `KeyError` if a role constant references a tool not in `tools_by_name`. Cryptic error for developers.
- **Fix:** Catch `KeyError` and raise `ValueError` with a helpful message:
  ```python
  try:
      result.append(tools_by_name[tool_name])
  except KeyError:
      raise ValueError(
          f"Tool {tool_name!r} referenced by role {role!r} not found in registered tools. "
          f"Available: {', '.join(sorted(tools_by_name))}"
      ) from None
  ```
- **Verify:** Add test: pass a role with an invalid tool name, verify `ValueError` with helpful message.

---

## Fix Order Recommendation

1. **A-01** first (security)
2. **A-03, A-02** (breaking state bugs)
3. **A-04** (resource leak)
4. **A-07, A-08, A-09** (prompt/message fixes — batch together)
5. **A-05, A-06** (state/formatting bugs)
6. Remaining P2 items
7. P3 test/style items last

---

## Verification Checklist

After all fixes applied:
- [ ] `ruff check src/ tests/` — zero violations
- [ ] `mypy src/ tests/` — zero errors
- [ ] `pytest tests/ -v` — all pass
- [ ] `bash scripts/local_ci.sh` — full pass
- [ ] Manual grep: `reviews/fix-plan.md` → zero hits
- [ ] Manual grep: `MAX_RETRIES` → zero hits (renamed)
- [ ] Path traversal test cases pass

# Epic 3 — Code Review Fix Plan

**Date:** 2026-03-24
**Scope:** Category A issues only — clear, non-controversial fixes
**Total fixes:** 44

Items are classified **not in** `epic3-architect-review-needed.md`. No overlap.

---

## P0 — Security (1 issue)

### A-01: Path traversal bypass in `_is_path_allowed`

- **File:** `src/tools/restricted.py:27`
- **Found by:** Both agents (BMAD 3-1#1,5 + Claude 3-1#1)
- **Issue:** `lstrip("./")` strips a *character set*, not a prefix. It does not collapse `..` sequences. A path like `reviews/../src/main.py` normalizes to `reviews/../src/main.py`, which starts with `reviews/` and passes the prefix check but resolves to `src/main.py`. Additionally, `lstrip` strips *any combination* of `.` and `/` characters, so `....///reviews/x` becomes `reviews/x`.
- **Fix:** Add `os.path.normpath()` after slash normalization, before prefix matching:
  ```python
  import posixpath
  normalized = posixpath.normpath(file_path.replace("\\", "/"))
  ```
  Ensure `..` at the start (escaping project root) is also rejected.
- **Verify:** Add test cases: `"reviews/../src/main.py"` → rejected; `"reviews/../../etc/passwd"` → rejected; `"....///reviews/x"` → rejected; `"reviews/valid.md"` → allowed.

---

## P1 — Breaking Logic / Bugs (5 issues)

### A-02: `review_file_paths` missing `operator.add` reducer

- **File:** `src/multi_agent/orchestrator.py:72`
- **Found by:** Both agents (across stories 3-3, 3-4, 3-6)
- **Issue:** Two parallel `review_node` instances (via Send API) each return `{"review_file_paths": [path]}`. Without an `operator.add` reducer, the second overwrites the first during state merge. Masked by `collect_reviews` re-deriving paths from filesystem, but state is semantically broken.
- **Fix:** Change line 72 from `review_file_paths: list[str]` to:
  ```python
  review_file_paths: Annotated[list[str], operator.add]
  ```
- **Verify:** `ruff check`, `mypy`, existing tests pass. Optionally add a test that two review_node returns merge correctly.

### A-03: SQLite connection leak — never closed

- **File:** `src/multi_agent/spawn.py:113-114`
- **Found by:** Both agents (BMAD 3-2#1.1 + Claude 3-2#1)
- **Issue:** Every call to `create_agent_subgraph()` opens `sqlite3.connect()` but the connection is never closed. `SqliteSaver` does not take ownership of closing it. Over a full pipeline (5+ sub-agents), file descriptors leak.
- **Fix:** Return the connection alongside the graph so the caller can close it, or use `SqliteSaver.from_conn_string()` which manages its own connection. Simplest fix — store `conn` and close after `compiled.invoke()`:
  ```python
  # In run_sub_agent, after compiled.invoke():
  conn.close()
  ```
  This requires `create_agent_subgraph` to also return the connection object.
- **Verify:** Add test that connection is closed after `run_sub_agent` completes (mock `sqlite3.connect` and verify `.close()` called).

### A-04: `edit_retry_count` never incremented — fix-dev retry context dead

- **File:** `src/multi_agent/orchestrator.py:78` (state), `421,432` (read only)
- **Found by:** Both agents (BMAD 3-4#1,6 + Claude 3-4#1)
- **Issue:** `fix_dev_node` reads `edit_retry_count` (line 421) and conditionally appends test failure context (line 432: `if edit_retry > 0 and last_test_output`). But no node ever increments `edit_retry_count`. The Fix Dev Agent is re-invoked blind on every retry — same instructions, no context about what broke. The retry context block is dead code.
- **Fix:** In `post_fix_test_node`, when tests fail and routing returns to `fix_dev_node`, include `edit_retry_count` increment in the returned state:
  ```python
  "edit_retry_count": state.get("edit_retry_count", 0) + 1,
  ```
- **Verify:** Add test: after `post_fix_test_node` returns failure, verify `edit_retry_count` is incremented in state. Verify `fix_dev_node` includes test output in task description when `edit_retry_count > 0`.

### A-05: `error_log` accumulator field never populated

- **File:** `src/multi_agent/orchestrator.py:86` (defined), `626` (read)
- **Found by:** BMAD 3-6#6
- **Issue:** `error_log: Annotated[list[str], operator.add]` has a reducer but no node ever returns `error_log` entries. The `error_handler_node` reads it (line 626) but it's always empty.
- **Fix:** In each node that detects a failure, include an `error_log` entry in the return dict:
  ```python
  "error_log": [f"{current_phase}: {description_of_error}"],
  ```
  Specific nodes: `collect_reviews` (when < 2 valid reviews), `post_fix_test_node` (when tests fail), `post_fix_ci_node` (when CI fails).
- **Verify:** Add test: simulate a test failure node, verify `error_log` accumulates the message.

### A-41: Python list repr injected as YAML in review task description

- **File:** `src/multi_agent/orchestrator.py:311`
- **Found by:** BMAD 3-6#4
- **Issue:** `f"input_files: {files_to_review}\n"` produces `input_files: ['src/foo.py', 'tests/test_a.py']` — Python list repr with single quotes, not valid YAML. If the review agent copies this into its output frontmatter, the YAML is malformed.
- **Fix:** Format as YAML-compatible list:
  ```python
  f"input_files: [{', '.join(files_to_review)}]\n"
  ```
- **Verify:** Inspect the generated task description string for valid YAML syntax.

---

## P2 — Spec Compliance / Correctness (18 issues)

### A-06: Add "architect" to `VALID_PHASES`

- **File:** `src/multi_agent/roles.py:17`, `src/multi_agent/orchestrator.py:407`
- **Found by:** Both agents (BMAD 3-4#17 + Claude 3-4#7)
- **Issue:** `VALID_PHASES` doesn't include "architect". The `architect_node` passes `current_phase="review"` as a workaround, causing LangSmith traces to mislabel architect activity.
- **Fix:** Add "architect" to `VALID_PHASES` in `roles.py:17`. Change `architect_node` to `current_phase="architect"`.
- **Verify:** `build_trace_config(agent_role="architect", ..., phase="architect")` should not raise.

### A-07: Restricted tools lack exception handling

- **File:** `src/tools/restricted.py:57-62, 80-87`
- **Found by:** Claude 3-1#5
- **Issue:** Inner `write_file` and `edit_file` functions don't wrap `base_write_file.invoke()` / `base_edit_file.invoke()` in try/except. Per coding-standards.md: "Tools: catch all exceptions internally, return `ERROR:` strings."
- **Fix:** Wrap each invoke call:
  ```python
  try:
      result: str = base_write_file.invoke({"file_path": file_path, "content": content})
      return result
  except Exception as e:
      return f"ERROR: Failed to write {file_path}: {e}"
  ```
- **Verify:** `ruff check`, `mypy`. Add test that triggers an exception in the base tool and verifies ERROR: string returned.

### A-08: `.gitkeep` missing `encoding="utf-8"`

- **File:** `src/multi_agent/orchestrator.py:119-120`
- **Found by:** Both agents (BMAD 3-3#1.4 + Claude 3-3#5)
- **Issue:** `with open(gitkeep, "w") as f:` omits encoding. All other file writes in the module specify `encoding="utf-8"`.
- **Fix:** Change to `with open(gitkeep, "w", encoding="utf-8") as f:`.
- **Verify:** Visual inspection.

### A-09: `PERMISSION_DENIED_MSG` text doesn't match AC#5

- **File:** `src/tools/restricted.py:19-21`
- **Found by:** Both agents (BMAD 3-1#10 + Claude 3-1#3)
- **Issue:** Code produces `"reviewer agents cannot edit source files. Write to reviews/ only."` AC#5 specifies `"Review agents cannot edit source files. Write to reviews/ directory only."` Differences: (a) lowercase "reviewer" vs title-case "Review", (b) missing word "directory".
- **Fix:** Update the format string and pass title-case role name:
  ```python
  PERMISSION_DENIED_MSG = (
      "ERROR: Permission denied: {role} agents cannot edit source files. "
      "Write to {allowed} directory only."
  )
  ```
- **Verify:** Run test `test_path_validation_error_message_exact` after tightening it (A-23).

### A-10: `build_orchestrator` return type is `Any`

- **File:** `src/multi_agent/orchestrator.py:846`
- **Found by:** Claude 3-3#4
- **Issue:** `-> Any` return type defeats mypy strict mode. Actual return type is a compiled graph.
- **Fix:** Import and use `from langgraph.graph.state import CompiledStateGraph` and annotate `-> CompiledStateGraph`.
- **Verify:** `mypy src/multi_agent/orchestrator.py`.

### A-11: `create_agent_subgraph` return type uses `Any`

- **File:** `src/multi_agent/spawn.py:54`
- **Found by:** Both agents (BMAD 3-2#1.6 + Claude 3-2#8)
- **Issue:** Returns `tuple[Any, dict[str, Any]]`. The first element is a compiled graph.
- **Fix:** Use `from langgraph.graph.state import CompiledStateGraph` and annotate `-> tuple[CompiledStateGraph, dict[str, Any]]`.
- **Verify:** `mypy src/multi_agent/spawn.py`.

### A-12: `get_prompt()` docstring omits `fix_dev`

- **File:** `src/agent/prompts.py:134`
- **Found by:** Both agents
- **Issue:** Docstring says `(dev, test, reviewer, architect)` but `fix_dev` is also valid.
- **Fix:** Change to `(dev, test, reviewer, architect, fix_dev)`.
- **Verify:** Visual inspection.

### A-13: Restricted tool docstrings say "Used by: Dev, Architect"

- **File:** `src/tools/restricted.py:58,81`
- **Found by:** Both agents
- **Issue:** Restricted versions say "Used by: Dev, Architect." — should reflect restricted roles.
- **Fix:** Update to `"Used by: Restricted roles (reviewer, test, architect)."`.
- **Verify:** Visual inspection.

### A-14: Unused `logging` import in restricted.py

- **File:** `src/tools/restricted.py:10,17`
- **Found by:** Claude 3-1#7
- **Issue:** `import logging` and `logger = logging.getLogger(__name__)` defined but never used.
- **Fix:** Remove both lines.
- **Verify:** `ruff check`.

### A-15: Unnecessary f-string in `_format_allowed`

- **File:** `src/tools/restricted.py:41`
- **Found by:** Claude 3-1#11
- **Issue:** `f"{p}"` is equivalent to `str(p)`.
- **Fix:** Change to `str(p)` or just `p` if prefixes are always strings.
- **Verify:** `ruff check`.

### A-16: `MAX_RETRIES` naming misleading

- **File:** `src/multi_agent/spawn.py:26`
- **Found by:** Claude 3-2#12
- **Issue:** `MAX_RETRIES = 50` is actually max LLM turns per task, not retry attempts.
- **Fix:** Rename to `MAX_TURNS` or `MAX_LLM_TURNS`. Update all references.
- **Verify:** Grep for `MAX_RETRIES` — should have zero hits.

### A-17: `run_sub_agent` bypasses `build_trace_config()` validation

- **File:** `src/multi_agent/spawn.py:178-187`
- **Found by:** Both agents (BMAD 3-2#3.3 + Claude 3-2#3)
- **Issue:** `run_sub_agent` manually builds the config dict. `roles.py:149-195` provides `build_trace_config()` which validates inputs. Manual construction bypasses validation.
- **Fix:** Replace manual config dict with `build_trace_config()` call. May need to adjust the function signature.
- **Verify:** `mypy`, existing tests pass.

### A-18: Tests use real `reviews/` directory instead of `tmp_path`

- **File:** `tests/test_multi_agent/test_orchestrator.py:644-689, 921-973`
- **Found by:** Both agents
- **Issue:** `TestCollectReviews`, `TestPrepareReviews`, and integration tests create/clean files in the real `reviews/` directory. Risks leaving artifacts, prevents parallel test execution.
- **Fix:** Refactor to use pytest `tmp_path` fixture. Monkeypatch `REVIEWS_DIR` for test scope.
- **Verify:** Run tests from different CWD — should still pass.

### A-19: `PERMISSION_DENIED_MSG` misleading for non-reviewer roles

- **File:** `src/tools/restricted.py:19-21`
- **Found by:** BMAD 3-1#2
- **Issue:** Message says "cannot edit source files" which is only accurate for reviewer role. For test role, it should say "cannot write outside allowed paths" since test files ARE source files.
- **Fix:** Generalize: `"cannot write outside allowed paths. Write to {allowed} directory only."`
- **Verify:** Verify message makes sense for reviewer, test, and architect roles.

### A-20: Missing integration test for sub-agent tool invocation

- **File:** `tests/test_multi_agent/test_spawn.py`
- **Found by:** Both agents (BMAD 3-2#3.4 + Claude 3-2#4)
- **Issue:** Story spec Task 6 requires "Integration test: spawn a Dev Agent subgraph, invoke with a simple task, verify it can call tools." No such test exists — all tests mock `create_agent_subgraph` or never invoke the compiled graph.
- **Fix:** Add integration test that creates a real subgraph and invokes it (may require LLM mock at the ChatAnthropic level).
- **Verify:** New test passes in CI.

### A-21: Redundant pytest instruction in `fix_dev_node`

- **File:** `src/multi_agent/orchestrator.py:429`
- **Found by:** BMAD 3-4#5
- **Issue:** Fix Dev Agent instructed to run pytest, then pipeline runs `post_fix_test_node` which runs pytest again.
- **Fix:** Remove the pytest instruction from the task description.
- **Verify:** Read the task description string.

### A-27: Checkpoints directory not ensured in spawn.py

- **File:** `src/multi_agent/spawn.py:109`
- **Found by:** BMAD 3-2#2.1
- **Issue:** `sqlite3.connect(checkpoints_db)` fails if `checkpoints/` dir doesn't exist.
- **Fix:** Add `os.makedirs(os.path.dirname(checkpoints_db), exist_ok=True)` before the connect call.
- **Verify:** Test in fresh environment (no checkpoints dir) succeeds.

---

## P3 — Tests / Style / Documentation (20 issues)

### A-22: Unnecessary `@patch` on test

- **File:** `tests/test_multi_agent/test_orchestrator.py:739-745`
- **Found by:** Claude (3-3#7, 3-4#4)
- **Issue:** `@patch("src.multi_agent.orchestrator.run_sub_agent")` and `mock_run` param never used.
- **Fix:** Remove the `@patch` decorator and `mock_run` parameter.
- **Verify:** Test still passes.

### A-23: Test `_exact` only checks substrings

- **File:** `tests/test_multi_agent/test_roles.py:352-359`
- **Found by:** Both agents
- **Issue:** Named `_exact` but only asserts substrings. Would pass with wrong casing or missing words.
- **Fix:** Assert exact string equality after A-09 is applied.
- **Verify:** Test passes with correct message, fails with wrong message.

### A-24: `tmp_path` typed as `object` instead of `Path`

- **File:** `tests/test_multi_agent/test_spawn.py:18,101`
- **Found by:** Both agents
- **Issue:** Forces `# type: ignore[operator]` comments. Fixture returns `pathlib.Path`.
- **Fix:** `from pathlib import Path`, change to `tmp_path: Path`. Remove `# type: ignore`.
- **Verify:** `mypy`.

### A-25: Test imports inside methods

- **File:** `tests/test_multi_agent/test_spawn.py:46,57,146,157,165,297`
- **Found by:** Both agents
- **Issue:** `AIMessage`, `get_tools_for_role` imported inside method bodies.
- **Fix:** Move to module-level imports.
- **Verify:** `ruff check`.

### A-26: `_ensure_reviews_dir` doesn't clean subdirectories

- **File:** `src/multi_agent/orchestrator.py:113`
- **Found by:** BMAD (3-3, 3-4)
- **Issue:** Only files are removed; leftover subdirectories persist.
- **Fix:** Add `elif os.path.isdir(entry_path): shutil.rmtree(entry_path)`.
- **Verify:** Test with a subdirectory present.

### A-28: `get_tools_for_role` raises raw `KeyError`

- **File:** `src/multi_agent/roles.py:144`
- **Found by:** BMAD 3-1#7
- **Issue:** `tools_by_name[tool_name]` raises raw `KeyError` if tool not registered.
- **Fix:** Catch `KeyError` and raise `ValueError` with helpful message listing available tools.
- **Verify:** Add test: pass role with invalid tool name, verify `ValueError`.

### A-29: Duplicate `get_role()` call

- **File:** `src/multi_agent/spawn.py:69,154`
- **Found by:** Claude 3-2#7
- **Issue:** `run_sub_agent()` calls `get_role(role)` then `create_agent_subgraph()` calls it again.
- **Fix:** Pass `role_config` from `run_sub_agent` into `create_agent_subgraph` or extract needed fields before calling.
- **Verify:** Existing tests pass.

### A-30: `_make_error_handler` ignores state param

- **File:** `src/multi_agent/spawn.py:43-45`
- **Found by:** BMAD 3-2#1.2
- **Issue:** Receives `state` but never uses it. Could include role/retry info in error message.
- **Fix:** Include useful context from state in the error message.
- **Verify:** Visual inspection.

### A-31: `_run_bash` truncation off by ~25 chars

- **File:** `src/multi_agent/orchestrator.py:158`
- **Found by:** BMAD 3-6#14
- **Issue:** Appended message isn't counted in the 5000-char target.
- **Fix:** Account for the appended message length.
- **Verify:** Visual inspection.

### A-32: Ambiguous `current_phase` reuse in post-fix nodes

- **File:** `src/multi_agent/orchestrator.py:528,547`
- **Found by:** BMAD 3-6#8
- **Issue:** Post-fix nodes reuse `"unit_test"` and `"ci"` phase names. Error reports are ambiguous.
- **Fix:** Use `"post_fix_test"`, `"post_fix_ci"`. Add to `VALID_PHASES` if needed.
- **Verify:** Error handler output distinguishes phases.

### A-33: Case-sensitive comparison on Windows

- **File:** `src/tools/restricted.py:28-34`
- **Found by:** BMAD 3-1#9
- **Issue:** `startswith` is case-sensitive but Windows paths are case-insensitive. `"Reviews/file.md"` rejected even though it targets the allowed directory.
- **Fix:** Add `.lower()` to both `normalized` and `norm_prefix`, or use `pathlib` which handles case.
- **Verify:** Test with mixed-case path on Windows.

### A-34: Allows writing file literally named `"reviews"`

- **File:** `src/tools/restricted.py:31`
- **Found by:** BMAD 3-1#8
- **Issue:** Exact match `normalized == norm_prefix` passes for `file_path="reviews"`, allowing creation of a file that shadows the `reviews/` directory.
- **Fix:** After normpath, reject paths that are exactly the directory name without a trailing path component.
- **Verify:** Test `file_path="reviews"` → rejected.

### A-35: Inconsistent dict access in `review_node`

- **File:** `src/multi_agent/orchestrator.py:289-296`
- **Found by:** Claude 3-3#6
- **Issue:** Mixes `state["key"]` with `state.get("key", [])` for `ReviewNodeInput` (a total `TypedDict` where all keys are required).
- **Fix:** Use bracket access for all required keys.
- **Verify:** Visual inspection.

### A-36: Test helper duplicates source logic

- **File:** `tests/test_multi_agent/test_orchestrator.py:63-78`
- **Found by:** Claude 3-3#9
- **Issue:** `_clean_reviews_dir` is a near-copy of `_ensure_reviews_dir` from source.
- **Fix:** Import and call the production function instead.
- **Verify:** Tests still pass.

### A-37: `retry_count` can become None

- **File:** `src/multi_agent/spawn.py:34`
- **Found by:** BMAD 3-2#2.5
- **Issue:** `state.get("retry_count", 0)` returns `None` if key exists with value `None`.
- **Fix:** `retry_count = state.get("retry_count", 0) or 0`.
- **Verify:** Add test with `retry_count=None` in state.

### A-38: Stale timestamp in review_node

- **File:** `src/multi_agent/orchestrator.py:300`
- **Found by:** BMAD 3-3#2.3
- **Issue:** Timestamp captured at node start, but review may take minutes.
- **Fix:** Capture timestamp closer to file write, or document that it's node-start time.
- **Verify:** Visual inspection.

### A-39: Empty `task_id` propagation

- **File:** `src/multi_agent/orchestrator.py:258`
- **Found by:** BMAD 3-3#2.4
- **Issue:** `state.get("task_id", "")` silently uses empty string. Review file YAML has `task_id: ""`.
- **Fix:** Log a warning if `task_id` is empty.
- **Verify:** Visual inspection.

### A-40: `test_passed` semantically overloaded for CI

- **File:** `src/multi_agent/orchestrator.py:492`
- **Found by:** BMAD 3-6#9
- **Issue:** `test_passed` field used for CI pass/fail, but CI includes ruff and mypy, not just tests.
- **Fix:** Consider renaming to `gate_passed` or documenting intent.
- **Verify:** Visual inspection.

### A-43: Path construction inconsistency

- **File:** `src/multi_agent/orchestrator.py:112,125`
- **Found by:** Claude 3-3#8
- **Issue:** Mixes `os.path.join` and f-string for path construction.
- **Fix:** Standardize on one approach throughout the module.
- **Verify:** Visual inspection.

### A-42/A-44: Fix Dev and Architect prompts reference wrong fix-plan path

- **Files:** `src/agent/prompts.py:109` (Fix Dev), `src/agent/prompts.py:82,91` (Architect)
- **Found by:** Both agents (3-6)
- **Issue:** Fix Dev prompt says `reviews/fix-plan.md`, Architect prompt says `reviews/`. Both should reference `fix-plan.md` at project root per `orchestrator.py:30`.
- **Fix:**
  - Line 109: Change `"Read the fix plan from reviews/fix-plan.md"` to `"Read the fix plan from fix-plan.md"`
  - Lines 82/91: Update to reference `fix-plan.md` at project root
- **Verify:** Grep for `reviews/fix-plan.md` — should have zero hits.

### A-46/A-47/A-48: CODEAGENT.md documentation fixes

- **Files:** `CODEAGENT.md:42,239,282-288`
- **Found by:** Both agents
- **Issues:**
  - A-46: `current_phase` enum doesn't match code values
  - A-47: Missing `prepare_reviews` node behavior description
  - A-48: Role Summary table uses abbreviated tool names
- **Fix:** Update documentation to match code.
- **Verify:** Visual inspection.

---

## Fix Order Recommendation

1. **A-01** first (security — path traversal)
2. **A-04, A-02** (breaking state bugs)
3. **A-03** (resource leak)
4. **A-42/A-44, A-09** (prompt/message fixes — batch together)
5. **A-05, A-41** (state/formatting bugs)
6. Remaining P2 items
7. P3 test/style items last

---

## Verification Checklist

After all fixes applied:
- [ ] `ruff check src/ tests/` — zero violations
- [ ] `mypy src/ tests/` — zero errors
- [ ] `pytest tests/ -v` — all pass
- [ ] `bash scripts/local_ci.sh` — full pass
- [ ] Grep: `reviews/fix-plan.md` → zero hits
- [ ] Grep: `MAX_RETRIES` → zero hits (renamed)
- [ ] Path traversal test cases pass
- [ ] `edit_retry_count` increment test passes

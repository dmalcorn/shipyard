# Epic 2 — Code Review Fix Plan

**Scope:** Category A issues ONLY — clear, non-controversial fixes with unambiguous implementations.
**Category B items** (architectural/controversial) are in `epic2-architect-review-needed.md`.
**Zero overlap** between the two files.

---

## P0 — Security (Fix Immediately)

### A-01: Sanitize session_id to prevent path traversal and Windows file errors

- **Files:** `src/logging/audit.py:42`, `src/main.py:80`
- **Issue:** `session_id` from the HTTP request body is used directly in `self._log_path = self._logs_dir / f"session-{session_id}.md"`. A malicious `session_id` like `../../etc/cron.d/evil` writes outside `logs/`. On Windows, characters like `:*?"<>|` cause `OSError`.
- **Found by:** BMAD 2-2 #6, #7
- **Fix:** Add a `_sanitize_session_id()` helper in `audit.py` that:
  1. Strips any character not in `[a-zA-Z0-9_-]`
  2. Rejects strings that produce empty result after sanitization
  3. Call this in `__init__` before constructing `_log_path`
  ```python
  import re

  def _sanitize_session_id(session_id: str) -> str:
      """Sanitize session_id for safe use in file paths."""
      sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
      if not sanitized:
          raise ValueError(f"session_id produces empty string after sanitization: {session_id!r}")
      return sanitized
  ```
- **Verify:** Add test cases: `session_id="../../etc/passwd"`, `session_id='foo:bar*baz'`, `session_id=""`, and a valid UUID. Confirm the log path stays within `logs/`.

---

## P1 — Bugs (Fix Before Next Release)

### A-02: Add try/finally around graph.invoke() for audit session lifecycle

- **Files:** `src/main.py:84-94` (HTTP endpoint), `src/main.py:130-162` (CLI)
- **Issue:** If `graph.invoke()` raises, `audit.end_session()` is never called, leaking the logger in `_active_loggers` and producing an incomplete log file with no summary.
- **Found by:** BMAD 2-2 #1/#2, Claude 2-2 #2
- **Fix:** Wrap the `graph.invoke()` call in try/finally in both locations:
  ```python
  # HTTP endpoint (main.py ~line 86)
  audit.start_session()
  try:
      result = graph.invoke(...)
  finally:
      audit.end_session()

  # CLI loop (main.py ~line 150)
  # Move audit.end_session() into a finally block around the while loop
  ```
- **Verify:** Write a test that mocks `graph.invoke` to raise, confirm `audit.end_session()` is still called and `_active_loggers` is empty after.

### A-03: Wrap tool_node audit logging in try/except

- **File:** `src/agent/nodes.py:76-94`
- **Issue:** If audit logging fails (e.g., disk I/O error on the log file), the exception propagates and the already-computed `result` dict from tool execution is lost. Audit logging is secondary and should not block tool results.
- **Found by:** Claude 2-2 #6
- **Fix:** Wrap the audit block (lines 76-94) in try/except:
  ```python
  # After _tool_node_inner.invoke(state) succeeds:
  try:
      # audit logging block
      ...
  except Exception as e:
      logger.warning("Audit logging failed in tool_node: %s", e)

  return result
  ```
- **Verify:** Test that tool_node returns correct results even when audit logging raises.

### A-04: Add guard against calling log methods before start_session()

- **File:** `src/logging/audit.py:116-119`
- **Issue:** `_append()` opens `self._log_path` with mode "a". If called before `start_session()` creates the `logs/` directory, it raises `FileNotFoundError`. No validation that the session is active.
- **Found by:** BMAD 2-2 #5
- **Fix:** Add a `_started` boolean flag, set in `start_session()`, checked in `_append()`:
  ```python
  def __init__(self, ...):
      ...
      self._started = False

  def start_session(self) -> None:
      ...
      self._started = True

  def _append(self, text: str) -> None:
      if not self._started:
          return  # silently skip — session not initialized
      ...
  ```
- **Verify:** Call `log_tool_call()` before `start_session()` — confirm no exception raised.

---

## P2 — Spec Violations & Documentation Accuracy

### A-05: Fix current_phase comment in state.py

- **File:** `src/agent/state.py:24`
- **Issue:** Comment says `"test", "dev", "review", "architect", "fix", "ci"` but VALID_PHASES is `{"test", "implementation", "review", "fix", "ci"}`. Comment includes non-phases ("dev", "architect") and misses "implementation".
- **Found by:** BMAD 2-1 #12, Claude 2-1 #1
- **Fix:** Change comment to:
  ```python
  current_phase: str  # "test", "implementation", "review", "fix", "ci"
  ```
- **Verify:** Comment matches `VALID_PHASES` in `src/multi_agent/roles.py:17`.

### A-06: Fix agent_role comment in state.py

- **File:** `src/agent/state.py:25`
- **Issue:** Comment says `"dev", "test", "reviewer", "architect"` but VALID_AGENT_ROLES includes `"fix_dev"`.
- **Found by:** Claude 2-1 #2, Claude 2-4 #8, BMAD 2-4 #1.4
- **Fix:** Change comment to:
  ```python
  agent_role: str  # "dev", "test", "reviewer", "architect", "fix_dev"
  ```
- **Verify:** Comment matches `VALID_AGENT_ROLES` in `src/multi_agent/roles.py:15`.

### A-07: Fix parent_session empty-string check in build_trace_config

- **File:** `src/multi_agent/roles.py:189`
- **Issue:** `if parent_session is not None:` allows empty string `""` to be included in metadata. An empty parent_session is not meaningful.
- **Found by:** BMAD 2-1 #4
- **Fix:** Change to truthy check:
  ```python
  if parent_session:
      metadata["parent_session"] = parent_session
  ```
- **Verify:** Test `build_trace_config(parent_session="")` — confirm `parent_session` key absent from metadata.

### A-08: Align parameter order between build_trace_config and create_trace_config

- **File:** `src/agent/graph.py:60-67` vs `src/multi_agent/roles.py:149-156`
- **Issue:** `build_trace_config(session_id, agent_role, task_id, ...)` vs `create_trace_config(session_id, task_id, agent_role, ...)` — `task_id` and `agent_role` are swapped. Both are called with keyword args in practice, but positional callers would get silent bugs.
- **Found by:** BMAD 2-1 #11
- **Fix:** Change `create_trace_config` to match `build_trace_config` ordering:
  ```python
  def create_trace_config(
      session_id: str,
      agent_role: str = "dev",  # moved before task_id to match build_trace_config
      task_id: str = "",
      ...
  ```
  Update all call sites (`src/main.py:81`, `src/main.py:128`) to use keyword args if not already.
- **Verify:** All callers already use keyword args — confirm with grep. Run existing tests.

### A-09: Fix test to use tmp_path instead of real filesystem path

- **File:** `tests/test_multi_agent/test_roles.py:331`
- **Issue:** `test_reviewer_write_allows_reviews_dir` calls restricted write_file with `file_path="reviews/test-review.md"` — a real relative path, not using `tmp_path` fixture. Leaves test artifacts on disk.
- **Found by:** Claude 2-1 #3
- **Fix:** Add `tmp_path` fixture parameter, construct path as `str(tmp_path / "reviews" / "test-review.md")`, and update the write restriction prefix to match `str(tmp_path / "reviews/")`.
- **Verify:** Test passes and no `reviews/test-review.md` file is created in the project root.

### A-10: Add descriptions and structure to docs/trace-links.md

- **File:** `docs/trace-links.md:1-2`
- **Issue:** File contains two bare URLs with no headings, labels, or descriptions. Story 2-3 Task 5 requires "Include a 1-sentence description of what each trace demonstrates."
- **Found by:** BMAD 2-3 #1.1/#1.2/#3.1, Claude 2-3 #1/#2
- **Fix:** Replace contents with:
  ```markdown
  # Trace Links

  ## Trace 1 — Normal Execution Path

  https://smith.langchain.com/public/9d212cc9-7537-4656-8581-f8c4bc190a98/r

  Normal execution path — agent reads a file, performs an edit, and completes successfully without errors.

  ## Trace 2 — Error Recovery Path

  https://smith.langchain.com/public/114ea778-4414-4e01-aa2a-c97d915e5cc6/r

  Error recovery path — agent encounters an edit failure (stale anchor), re-reads the file, and retries with corrected context.
  ```
- **Verify:** File has markdown headings and each URL has a description.

### A-11: Fix list_files parameters in CODEAGENT.md tool table

- **File:** `CODEAGENT.md:81`
- **Issue:** Documents `list_files` as `directory: str, pattern: str`. Actual signature is `list_files(pattern: str, path: str = ".")`.
- **Found by:** BMAD 2-4 #1.1, Claude 2-4 #1
- **Fix:** Change line 81 to:
  ```
  | `list_files` | Glob pattern matching in a directory | `pattern: str, path: str = "."` |
  ```
- **Verify:** Matches `src/tools/search.py:19`.

### A-12: Fix search_files parameters in CODEAGENT.md tool table

- **File:** `CODEAGENT.md:82`
- **Issue:** Documents `search_files` as `directory: str, regex_pattern: str`. Actual signature is `search_files(pattern: str, path: str = ".")`.
- **Found by:** BMAD 2-4 #1.2, Claude 2-4 #2
- **Fix:** Change line 82 to:
  ```
  | `search_files` | Regex search across file contents | `pattern: str, path: str = "."` |
  ```
- **Verify:** Matches `src/tools/search.py:39`.

### A-13: Add timeout parameter to run_command in CODEAGENT.md tool table

- **File:** `CODEAGENT.md:83`
- **Issue:** Documents `run_command` as `command: str`. Actual signature includes `timeout: str = "30"`.
- **Found by:** BMAD 2-4 #1.3, Claude 2-4 #3
- **Fix:** Change line 83 to:
  ```
  | `run_command` | Execute a shell command with timeout | `command: str, timeout: str = "30"` |
  ```
- **Verify:** Matches `src/tools/bash.py:21`.

### A-14: Fix Test Agent tool list in CODEAGENT.md roles table

- **File:** `CODEAGENT.md:166`
- **Issue:** Shows Test Agent tools as including `edit`, but `TEST_ROLE` at `src/multi_agent/roles.py:57` excludes `edit_file`.
- **Found by:** Claude 2-4 #4
- **Fix:** Change Test Agent tools column from `read, edit, write, list, search, bash` to:
  ```
  read, write, list, search, bash
  ```
- **Verify:** Matches `TEST_ROLE.tools` in `roles.py:57`.

### A-15: Fix Architect write restrictions in CODEAGENT.md roles table

- **File:** `CODEAGENT.md:168`
- **Issue:** Says Architect can write to "`fix-plan.md` only" but `ARCHITECT_ROLE.write_restrictions = ("reviews/", "fix-plan.md")`.
- **Found by:** Claude 2-4 #5
- **Fix:** Change Architect "Can Write" column to:
  ```
  `reviews/` directory, `fix-plan.md`
  ```
- **Verify:** Matches `ARCHITECT_ROLE.write_restrictions` in `roles.py:75`.

### A-16: Fix Architect "Can Read" in CODEAGENT.md roles table

- **File:** `CODEAGENT.md:168`
- **Issue:** Says "Review files, source" implying restricted read. Actual prompt says "You CAN read any file and search the codebase."
- **Found by:** Claude 2-4 #6
- **Fix:** Change Architect "Can Read" column to:
  ```
  All files
  ```
- **Verify:** Consistent with `src/agent/prompts.py:80`.

### A-17: Fix Review Agent write restriction in CODEAGENT.md roles table

- **File:** `CODEAGENT.md:167`
- **Issue:** Says "`reviews/review-agent-{n}.md` only" but code allows entire `reviews/` directory.
- **Found by:** Claude 2-4 #7
- **Fix:** Change Review Agent "Can Write" column to:
  ```
  `reviews/` directory only
  ```
- **Verify:** Matches `REVIEWER_ROLE.write_restrictions = ("reviews/",)` in `roles.py:67`.

### A-18: Fix Mermaid diagram node labels in CODEAGENT.md

- **File:** `CODEAGENT.md:27-33`
- **Issue:** Diagram uses `agent[agent_node<br/>...]` and `tools[tool_node<br/>...]` mixing function names with node IDs. Graph registers nodes as `"agent"` and `"tools"`.
- **Found by:** BMAD 2-4 #3.6
- **Fix:** Update diagram labels to use node names consistently:
  ```mermaid
  agent[agent<br/>Call Claude with tools]
  tools[tools<br/>Execute tool calls]
  ```
- **Verify:** Labels match `graph.add_node("agent", ...)` in `src/agent/graph.py:26-27`.

### A-19: Fix should_continue prose to include error route

- **File:** `CODEAGENT.md:21`
- **Issue:** Prose says "If tool_calls -> tool_node. Otherwise -> END." Omits the third route: retry_count >= MAX_RETRIES -> error_handler.
- **Found by:** BMAD 2-4 #3.7
- **Fix:** Update line 21 to:
  ```
  - **`should_continue`** (conditional edge): If `retry_count >= 50`, route to `error_handler`. If the AI message contains `tool_calls`, route to `tool_node`. Otherwise, route to `END`.
  ```
- **Verify:** Matches the three-way conditional in `src/agent/nodes.py:105-119` and the Mermaid diagram.

### A-20: Fix _validate_review_file to use except Exception as e

- **File:** `src/multi_agent/orchestrator.py:85-86`
- **Issue:** Uses `except Exception:` without binding. Coding standards say `except Exception as e:` minimum. The exception is silently swallowed with no logging.
- **Found by:** BMAD 2-4 #3.8
- **Fix:**
  ```python
  except Exception as e:
      logger.warning("Failed to validate review file %s: %s", file_path, e)
      return False
  ```
- **Verify:** `ruff check src/multi_agent/orchestrator.py` passes.

### A-21 (bonus): Add no-op guard to edit_file

- **File:** `src/tools/file_ops.py:67-96`
- **Issue:** No check for `old_string == new_string`. Agent could burn turns with no-op edits.
- **Found by:** BMAD 2-4 #2.2
- **Fix:** Add early return:
  ```python
  if old_string == new_string:
      return "ERROR: old_string and new_string are identical. No edit needed."
  ```
- **Verify:** Test `edit_file(path, old_string="x", new_string="x")` returns ERROR message.

---

## P3 — Test Improvements

### A-22: Add unit tests for get_logger() and _active_loggers lifecycle

- **File:** `tests/test_logging/test_audit.py` (add new tests)
- **Issue:** `get_logger()` is a public function with zero test coverage. Registration (`start_session` adds to `_active_loggers`) and deregistration (`end_session` removes) are untested.
- **Found by:** BMAD 2-2 #15, Claude 2-2 #5
- **Fix:** Add tests:
  1. `test_get_logger_returns_none_before_start` — verify `get_logger(session_id)` returns `None`
  2. `test_get_logger_returns_logger_after_start` — verify it returns the logger instance
  3. `test_get_logger_returns_none_after_end` — verify cleanup
  4. `test_get_logger_with_unknown_session` — verify returns `None`
- **Verify:** `pytest tests/test_logging/test_audit.py -v` passes with new tests.

### A-23: Improve weak markdown validity test assertion

- **File:** `tests/test_logging/test_audit.py:252-254`
- **Issue:** "Valid markdown" check is `assert "<" not in content` — doesn't actually validate markdown structure. Would fail on legitimate `<` in task descriptions.
- **Found by:** BMAD 2-2 #17, Claude 2-2 #8
- **Fix:** Replace with meaningful structure checks:
  ```python
  def test_log_is_valid_markdown(self, ...):
      ...
      # Verify markdown structure
      assert content.startswith("[Session")  # header line
      assert "└─ [Session Complete]" in content  # summary present
      assert "├─" in content  # tree structure present
      # Ensure no HTML was accidentally generated
      assert "<html" not in content.lower()
  ```
- **Verify:** Test passes against a real session log output.

---

## Fix Order Recommendation

1. **A-01** (session_id sanitization) — security P0, blocks nothing
2. **A-02** (try/finally) — prevents resource leaks, standalone fix
3. **A-03** (tool_node audit safety) — prevents data loss, standalone fix
4. **A-04** (start_session guard) — defensive robustness
5. **A-05 through A-09** (source code accuracy fixes) — batch together, all small
6. **A-10** (docs/trace-links.md) — standalone doc fix
7. **A-11 through A-19** (CODEAGENT.md fixes) — batch together, all in same file
8. **A-20** (orchestrator exception binding) — single line fix
9. **A-21** (edit_file no-op guard) — small tool improvement
10. **A-22, A-23** (test improvements) — do last, after code fixes

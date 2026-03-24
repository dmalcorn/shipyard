# Epic 1 Code Review — Fix Plan

Category A fixes only. Each fix is unambiguous with no architectural decisions required.

---

## P0 — Critical (Must Fix Immediately)

### A-01: Pre-existing ruff errors break quality gate

- **Files:** `src/agent/prompts.py`, `tests/test_context/test_injection.py`
- **Issue:** Story 1-7 completion notes acknowledge "Pre-existing ruff lint errors." `local_ci.sh` runs `ruff check src/ tests/` with `set -e` — it exits on first failure. The quality gate cannot pass in the current codebase state.
- **Source:** Claude Direct (Story 1-7, #10)
- **Fix:**
  1. Run `ruff check src/ tests/` to identify all current violations
  2. Fix each violation (likely unused imports, formatting, or style issues)
  3. Run `ruff format src/ tests/` to auto-fix formatting
  4. Verify `bash scripts/local_ci.sh` passes end-to-end
- **Verify:** `bash scripts/local_ci.sh` exits 0

---

## P1 — High (Fix Before Next Sprint)

### A-02: `_validate_path` discards resolved path — sandbox bypass

- **Files:** `src/tools/file_ops.py:28-44` (validate), `src/tools/file_ops.py:54,76,90,108` (callers)
- **Issue:** `_validate_path()` resolves the path against `_PROJECT_ROOT` and validates it, but returns `None` on success. All three tools then call `open(file_path)` with the original unresolved string. If CWD differs from `_PROJECT_ROOT`, relative paths resolve differently between validation and I/O.
- **Source:** Both agents (BMAD 1-2 findings 1.1-1.3, 1.4, 3.1; Claude 1-2 #1)
- **Fix:**
  1. Change `_validate_path` signature: `def _validate_path(file_path: str) -> Path | str:` — returns resolved `Path` on success, error `str` on failure
  2. Update callers to check `isinstance(result, str)` for error, otherwise use the returned `Path` for all I/O
  3. Replace all `open(file_path, ...)` calls with `open(resolved_path, ...)`
  4. Replace `os.makedirs(os.path.dirname(file_path), ...)` with `resolved_path.parent.mkdir(parents=True, exist_ok=True)`
- **Verify:** Add test with CWD != project root, verify file I/O uses resolved path. Run existing tests.

### A-03: Blocking sync `graph.invoke()` in async endpoint

- **File:** `src/main.py:70` (endpoint declaration)
- **Issue:** `async def instruct()` calls synchronous `graph.invoke()`, blocking the FastAPI event loop. All other requests (including `/health`) are blocked during LLM invocation.
- **Source:** Both agents (BMAD 1-6 finding 1.1/3.2; Claude 1-6 #1)
- **Fix:** Change `async def instruct(...)` to `def instruct(...)`. FastAPI automatically runs sync endpoints in a threadpool, solving the blocking problem with zero other code changes.
- **Verify:** Start server, send concurrent requests, confirm `/health` responds during active `/instruct` processing.

### A-04: `run_command` missing `cwd` sandboxing

- **File:** `src/tools/bash.py:22`
- **Issue:** `subprocess.run(command, shell=True, ...)` has no `cwd` parameter. Commands execute in whatever the current working directory is. `project-context.md` explicitly requires: "Sandbox all `run_command` tool execution — restrict to project working directory."
- **Source:** Both agents (BMAD 1-3 finding 1.3/3.1; Claude 1-3 #5)
- **Fix:**
  1. Add `_PROJECT_ROOT` constant (same pattern as `file_ops.py`): `_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent`
  2. Add `cwd=str(_PROJECT_ROOT)` to the `subprocess.run()` call
  3. Add test that verifies command runs in project directory (e.g., `run_command("pwd")` returns project root)
- **Verify:** Run test confirming CWD. Run existing `test_bash.py` tests.

### A-05: No error message in state on retry exhaustion

- **File:** `src/agent/nodes.py:65-76`, `src/agent/graph.py:33-37`
- **Issue:** When `retry_count >= MAX_RETRIES`, `should_continue` returns `"error"` which routes to `END`. But no error message is added to the state. The caller gets the last AI response with no indication the task was terminated. AC #3 requires "the loop terminates **with an error message**."
- **Source:** Both agents (BMAD 1-4 finding 3.1 CRITICAL; Claude 1-4 #5)
- **Fix:**
  1. Add an `error_handler` node function that appends an error `AIMessage` to state:
     ```python
     def error_handler(state: AgentState) -> dict:
         return {"messages": [AIMessage(content="ERROR: Agent exceeded maximum turn limit (50). Task terminated.")]}
     ```
  2. Register node: `graph.add_node("error_handler", error_handler)`
  3. Change edge mapping: `"error": "error_handler"` (instead of `"error": END`)
  4. Add edge: `graph.add_edge("error_handler", END)`
  5. Add test verifying error message appears in state at retry exhaustion
- **Verify:** Test that invokes graph with `retry_count` at limit, confirms error message in output.

### A-06: Unused `type:ignore` comments cause mypy failures

- **Files:** `tests/test_agent/test_state.py:35`, `tests/test_agent/test_nodes.py:19`
- **Issue:** Both files have `# type: ignore[typeddict-unknown-key]` that mypy strict mode reports as unused. mypy exits non-zero, failing the quality gate.
- **Source:** Claude Direct (Story 1-4, #1)
- **Fix:** Remove the `# type: ignore[typeddict-unknown-key]` comments from both files. If mypy then reports actual type errors, fix the underlying type issue.
- **Verify:** `mypy src/ tests/` exits 0.

---

## P2 — Medium (Fix During Current Sprint)

### A-07: Checkpoint DB path mismatch

- **File:** `src/agent/graph.py:19`
- **Issue:** Story spec says `checkpoints/shipyard.db`. Implementation has `checkpoints/checkpoints.db`.
- **Source:** Both agents
- **Fix:** Change `CHECKPOINTS_DB = "checkpoints/checkpoints.db"` to `CHECKPOINTS_DB = "checkpoints/shipyard.db"`
- **Verify:** Delete existing `checkpoints/checkpoints.db`, restart server, confirm new file created as `shipyard.db`.

### A-08: `CODING_STANDARDS_PATH` relative path

- **File:** `src/context/injection.py:19`
- **Issue:** `CODING_STANDARDS_PATH = "coding-standards.md"` resolves against CWD, not project root. If started from a different directory, coding standards are silently dropped from agent context.
- **Source:** Both agents
- **Fix:** Change to: `CODING_STANDARDS_PATH = str(Path(__file__).resolve().parent.parent.parent / "coding-standards.md")`
- **Verify:** Test `build_system_prompt` works when CWD is not project root.

### A-09: Missing logging in `search.py`

- **File:** `src/tools/search.py` (all error return paths)
- **Issue:** `file_ops.py` uses `logger.exception()` before returning errors. `search.py` returns `ERROR:` strings without any logging. Coding-standards.md: "Log the exception before returning the error string."
- **Source:** Claude Direct (Story 1-3, #1)
- **Fix:**
  1. Add `import logging` and `logger = logging.getLogger(__name__)` at top
  2. Add `logger.exception(...)` before each `return f"ERROR: ..."` in `list_files` and `search_files`
- **Verify:** Run tests, check that logging calls don't break anything. Grep for `ERROR:` returns to verify each has a preceding log call.

### A-10: Missing logging in `bash.py`

- **File:** `src/tools/bash.py` (all error return paths)
- **Issue:** Same as A-09 but for `bash.py`.
- **Source:** Claude Direct (Story 1-3, #2)
- **Fix:** Same pattern — add `logger` and `logger.exception()`/`logger.error()` before each error return.
- **Verify:** Same as A-09.

### A-11: `list_files` returns directories

- **File:** `src/tools/search.py:19`
- **Issue:** `Path(path).glob(pattern)` returns both files and directories. Tool is named `list_files` and AC says "matching file paths are returned."
- **Source:** BMAD (Story 1-3, findings 1.2/3.4)
- **Fix:** Change: `matches = sorted(str(p) for p in Path(path).glob(pattern))` to `matches = sorted(str(p) for p in Path(path).glob(pattern) if p.is_file())`
- **Verify:** Create test with directories matching glob pattern, confirm they're excluded.

### A-12: Conditional truncation test assertions

- **Files:** `tests/test_tools/test_search.py:44-46`, `tests/test_tools/test_search.py:92-99`
- **Issue:** Truncation assertions wrapped in `if "truncated" in result:` — may never execute if output stays under 5000 chars. Tests pass vacuously.
- **Source:** Both agents
- **Fix:** Ensure test data exceeds 5000 chars deterministically. For `test_list_truncates`, create files with very long names (200+ chars each). For `test_search_truncates`, write files with many matching lines. Remove the `if` guard and assert unconditionally.
- **Verify:** Run tests — they should now always exercise the truncation path.

### A-13: Missing `edit_file` exception handling test

- **File:** `tests/test_tools/test_file_ops.py` (new test needed)
- **Issue:** `edit_file`'s `except Exception as e` handler (line 95-97 of `file_ops.py`) has no dedicated test. `read_file` and `write_file` have exception tests.
- **Source:** Both agents (BMAD 1-2 finding 3.2; Claude 1-2 #4)
- **Fix:** Add `test_edit_general_exception` to `TestEditFile` class. Use a read-only file (set permissions via `os.chmod` on non-Windows) or mock if necessary on Windows.
- **Verify:** New test passes and exercises the `except Exception` code path.

### A-14: Negative/zero timeout validation

- **File:** `src/tools/bash.py:17`
- **Issue:** `timeout_secs = int(timeout)` accepts `"0"` or `"-5"`. Zero causes immediate timeout; negative causes confusing runtime error.
- **Source:** BMAD (Story 1-3, finding 1.8)
- **Fix:** Add validation after parsing: `if timeout_secs <= 0: return "ERROR: Timeout must be a positive integer. Provide seconds > 0."`
- **Verify:** Add test for `run_command("echo hi", "0")` and `run_command("echo hi", "-1")` — both should return `ERROR:`.

### A-15: Empty regex pattern validation

- **File:** `src/tools/search.py:38`
- **Issue:** `re.compile("")` succeeds and matches every line of every file, producing useless results that hit truncation.
- **Source:** BMAD (Story 1-3, finding 2.2)
- **Fix:** Add early return: `if not pattern.strip(): return "ERROR: Empty search pattern. Provide a regex pattern to search for."`
- **Verify:** Add test for `search_files("", ".")` — should return `ERROR:`.

### A-16: Empty messages guard in `should_continue`

- **File:** `src/agent/nodes.py:72`
- **Issue:** `state["messages"][-1]` raises `IndexError` on empty list. Unlikely in normal flow but possible on corrupted checkpoint resume.
- **Source:** BMAD (Story 1-4, finding 2.1)
- **Fix:** Add guard: `if not state.get("messages"): return "end"` before accessing `[-1]`.
- **Verify:** Add test with empty messages in state, confirm `should_continue` returns `"end"`.

### A-17: `_extract_response` doesn't handle list-type content

- **File:** `src/main.py:101-102`
- **Issue:** `AIMessage.content` can be `str | list[dict]` (for multi-modal responses). `str(msg.content)` on a list produces a repr string, not the text content.
- **Source:** BMAD (Story 1-6, finding 2.4)
- **Fix:** Replace `return str(msg.content)` with:
  ```python
  content = msg.content
  if isinstance(content, list):
      return " ".join(block.get("text", "") for block in content if isinstance(block, dict))
  return str(content)
  ```
- **Verify:** Add test with mock `AIMessage` containing list content.

---

## P3 — Low (Nice to Have)

### A-18: Inconsistent missing-file handling between Layer 1 and Layer 2

- **File:** `src/context/injection.py:62-65` vs `src/context/injection.py:93-94`
- **Issue:** Layer 1 (`build_system_prompt`) silently skips missing files. Layer 2 (`inject_task_context`) adds `"(file not available)"`. Should be consistent.
- **Source:** Both agents
- **Fix:** Update `build_system_prompt` to add a `"(file not available)"` note when a context file is missing, matching Layer 2 behavior.
- **Verify:** Test missing file in `build_system_prompt`, confirm output includes `"(file not available)"`.

### A-19: `tmp_path` typed as `object` in test fixtures

- **File:** `tests/test_context/test_injection.py:32,44`
- **Issue:** `tmp_path: object` should be `tmp_path: Path` (from `pathlib`).
- **Source:** Both agents
- **Fix:** Change annotation to `tmp_path: Path` and add `from pathlib import Path` import.
- **Verify:** `mypy tests/` passes.

### A-20: `run_command` stderr truncation lacks indicator

- **File:** `src/tools/bash.py:30`
- **Issue:** When stderr > 500 chars, it's silently truncated. stdout truncation adds `(truncated, {n} chars total)` but stderr does not.
- **Source:** BMAD (Story 1-3, finding 1.7)
- **Fix:** Change stderr truncation to include indicator when truncated:
  ```python
  if result.stderr and len(result.stderr) > 500:
      stderr_snippet = result.stderr[:500] + f" (truncated, {len(result.stderr)} chars total)"
  else:
      stderr_snippet = result.stderr or "(no stderr)"
  ```
- **Verify:** Add test with command producing >500 chars stderr, confirm truncation note.

### A-21: README `<repo-url>` placeholder

- **File:** `README.md:17`
- **Issue:** Clone command shows `<repo-url>` instead of actual URL.
- **Source:** BMAD (Story 1-7, finding 3.1)
- **Fix:** Replace `<repo-url>` with `https://github.com/dmalcorn/shipyard.git`
- **Verify:** Visual inspection.

### A-22: `write_file` exception test exercises wrong code path

- **File:** `tests/test_tools/test_file_ops.py:190-197`
- **Issue:** `test_write_exception_returns_error` uses `/\x00illegal` which triggers `_validate_path` error, not `write_file`'s own exception handler. The test doesn't exercise the intended code.
- **Source:** Claude Direct (Story 1-2, #3)
- **Fix:** Replace with a test that bypasses `_validate_path` (e.g., use a valid path in a read-only directory on non-Windows, or mock `open` to raise `PermissionError` during the write step).
- **Verify:** New test exercises `write_file`'s `except Exception` block specifically.

### A-23: `search_files` regex compilation outside main try/except

- **File:** `src/tools/search.py:38-40`
- **Issue:** `re.compile()` is outside the broader `try/except Exception` block (lines 43-66). A non-`re.error` exception would escape the tool.
- **Source:** Claude Direct (Story 1-3, #6)
- **Fix:** Move the `re.compile()` call inside the main `try/except Exception` block, or wrap the entire function body in a single `try/except`.
- **Verify:** Existing tests pass. The structural change is minor.

---

## Execution Order Recommendation

1. **A-01** first — unblocks quality gate for all other fixes
2. **A-06** next — fixes mypy gate
3. **A-02, A-03, A-04, A-05** — high-impact security and correctness fixes
4. **A-07 through A-17** — medium priority, can be batched
5. **A-18 through A-23** — low priority, address opportunistically

After each batch, run `bash scripts/local_ci.sh` to confirm no regressions.

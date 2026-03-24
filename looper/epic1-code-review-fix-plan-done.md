# Epic 1 Code Review — Fix Execution Log

[2026-03-24 10:03:00 FIX #A-01] src/agent/prompts.py, src/context/injection.py, tests/test_context/test_injection.py, tests/test_main.py
  - Ran `ruff format` to auto-fix formatting issues in 4 files

[2026-03-24 10:04:00 FIX #A-06] tests/test_agent/test_state.py, tests/test_agent/test_nodes.py, tests/test_tools/test_file_ops.py
  - Removed unused `# type: ignore[typeddict-unknown-key]` from test_state.py:35
  - Removed unused `# type: ignore[typeddict-unknown-key]` from test_nodes.py:19
  - Changed fixture return type to `Generator[None]`, removed unused `# type: ignore[misc]` in test_file_ops.py:16
  - Added `from collections.abc import Generator` import to test_file_ops.py

[2026-03-24 10:05:00 FIX #A-02] src/tools/file_ops.py
  - Changed `_validate_path` return type from `str | None` to `Path | str` — now returns resolved Path on success
  - Updated `read_file` to use `isinstance(resolved, str)` check and `open(resolved, ...)` for I/O
  - Updated `edit_file` to use resolved path for both read and write operations
  - Updated `write_file` to use `resolved.parent.mkdir()` instead of `os.makedirs`
  - Removed unused `import os`

[2026-03-24 10:06:00 FIX #A-03] src/main.py:70
  - Changed `async def instruct(...)` to `def instruct(...)` — FastAPI runs sync endpoints in a threadpool

[2026-03-24 10:06:30 FIX #A-04] src/tools/bash.py
  - Added `_PROJECT_ROOT` constant (same pattern as file_ops.py)
  - Added `cwd=str(_PROJECT_ROOT)` to `subprocess.run()` call
  - Added test `test_command_runs_in_project_root` to verify cwd

[2026-03-24 10:07:00 FIX #A-05] src/agent/nodes.py, src/agent/graph.py
  - Added `error_handler` node function that appends error AIMessage to state
  - Registered `error_handler` node in graph
  - Changed edge mapping: `"error": "error_handler"` (instead of `"error": END`)
  - Added `graph.add_edge("error_handler", END)`
  - Added test `TestErrorHandler.test_error_handler_returns_error_message`

[2026-03-24 10:07:30 FIX #A-07] src/agent/graph.py:19
  - Changed `CHECKPOINTS_DB = "checkpoints/checkpoints.db"` to `"checkpoints/shipyard.db"`

[2026-03-24 10:08:00 FIX #A-08] src/context/injection.py:19
  - Changed `CODING_STANDARDS_PATH` from relative `"coding-standards.md"` to absolute `Path(__file__).resolve().parent.parent.parent / "coding-standards.md"`

[2026-03-24 10:08:30 FIX #A-09] src/tools/search.py
  - Added `import logging` and `logger = logging.getLogger(__name__)`
  - Added `logger.exception(...)` before error returns in `list_files` and `search_files`

[2026-03-24 10:09:00 FIX #A-10] src/tools/bash.py
  - Added `import logging` and `logger = logging.getLogger(__name__)`
  - Added `logger.error(...)` before command failure return
  - Added `logger.error(...)` before timeout return
  - Added `logger.exception(...)` before general exception return

[2026-03-24 10:09:30 FIX #A-11] src/tools/search.py:19
  - Added `if p.is_file()` filter to `list_files` glob results
  - Added test `test_list_excludes_directories`

[2026-03-24 10:10:00 FIX #A-12] tests/test_tools/test_search.py:44-46, 92-99
  - Replaced conditional truncation assertions with deterministic tests
  - `test_list_truncates` now creates 100 files with 60-char names (guaranteed >5000 chars)
  - `test_search_truncates` now writes 500 padded lines (guaranteed >5000 chars)
  - Removed `if "truncated"` guards — assertions are now unconditional

[2026-03-24 10:10:30 FIX #A-13] tests/test_tools/test_file_ops.py
  - Added `test_edit_general_exception` to TestEditFile class
  - Uses `mock builtins.open` to raise `PermissionError` during edit

[2026-03-24 10:11:00 FIX #A-14] src/tools/bash.py:17
  - Added validation: `if timeout_secs <= 0: return "ERROR: Timeout must be a positive integer."`
  - Added tests `test_zero_timeout_returns_error` and `test_negative_timeout_returns_error`

[2026-03-24 10:11:30 FIX #A-15] src/tools/search.py:38
  - Added early return: `if not pattern.strip(): return "ERROR: Empty search pattern."`
  - Added tests `test_search_empty_pattern_returns_error` and `test_search_whitespace_pattern_returns_error`

[2026-03-24 10:11:45 FIX #A-16] src/agent/nodes.py:72
  - Added guard: `if not state.get("messages"): return "end"` at top of `should_continue`
  - Added test `test_routes_to_end_on_empty_messages`

[2026-03-24 10:12:00 FIX #A-17] src/main.py:101-102
  - `_extract_response` now handles `list[dict]` content from AIMessage
  - Extracts text from `{"type": "text", "text": "..."}` blocks
  - Added test `test_handles_list_content`

[2026-03-24 10:12:15 FIX #A-18] src/context/injection.py:62-65
  - `build_system_prompt` now adds `"(file not available)"` for missing context files, matching Layer 2 behavior
  - Updated test `test_missing_context_file_shows_not_available`

[2026-03-24 10:12:20 FIX #A-19] tests/test_context/test_injection.py:32,44
  - Changed `tmp_path: object` to `tmp_path: Path` in both fixtures
  - Added `from pathlib import Path` import

[2026-03-24 10:12:25 FIX #A-20] src/tools/bash.py:30
  - Stderr truncation now includes `(truncated, N chars total)` indicator when >500 chars

[2026-03-24 10:12:30 FIX #A-21] README.md:17
  - Replaced `<repo-url>` with `https://github.com/dmalcorn/shipyard.git`

[2026-03-24 10:12:35 FIX #A-22] tests/test_tools/test_file_ops.py:190-197
  - Replaced `write_file` exception test that used `/\x00illegal` (which hit `_validate_path`)
  - New test uses `mock builtins.open` to raise `PermissionError` on a valid path, exercising `write_file`'s own exception handler

[2026-03-24 10:12:40 FIX #A-23] src/tools/search.py:38-40
  - Moved `re.compile()` inside the main `try/except Exception` block
  - `re.error` is caught as a specific exception before the general `Exception`

# Completed: 23/23 fixes applied, 0 skipped

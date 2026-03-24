# Epic 4 — Fix Plan Execution Log

## P0 — Security / Core Feature

[2026-03-24 14:38:00 FIX #1] src/tools/scoped.py
  - Changed `list_files` to use `_validate(path)` instead of `_resolve(path)`, with error string check

[2026-03-24 14:38:00 FIX #2] src/tools/scoped.py
  - Changed `search_files` to use `_validate(path)` instead of `_resolve(path)`, with error string check

[2026-03-24 14:38:30 FIX #3] src/main.py
  - Sanitized `session_id` with `re.sub(r"[^a-zA-Z0-9_-]", "", ...)` before using in file path

[2026-03-24 14:39:00 FIX #4] src/intake/intervention_log.py, src/main.py
  - Changed `cli_intervention_prompt` return type from `Literal["fix","skip","abort"]` to `tuple[Literal["fix","skip","abort"], str]`
  - Updated `_run_rebuild_cli` callback to unpack tuple and return fix_instruction instead of literal "retry"
  - Updated all tests in `test_intervention_log.py` to handle tuple return

## P1 — Correctness

[2026-03-24 14:40:00 FIX #5] src/intake/pipeline.py
  - Added empty result validation in `output_node`: fails if spec_summary or epics_and_stories is blank

[2026-03-24 14:40:00 FIX #6] src/intake/pipeline.py
  - Wrapped `os.makedirs` and file writes in try/except OSError, returning pipeline_status="failed"

[2026-03-24 14:41:00 FIX #7] src/intake/rebuild.py
  - Added `check=True` to `git init`, `git add`, `git commit` subprocess calls in `_init_target_project`
  - Wrapped in try/except `subprocess.CalledProcessError` with error logging and re-raise

[2026-03-24 14:41:00 FIX #8] src/intake/rebuild.py
  - Added return code check on `git tag` in `_git_tag_epic`, logging warning on failure

[2026-03-24 14:41:30 FIX #9] src/intake/rebuild.py
  - Wrapped `load_backlog()` in try/except FileNotFoundError, returning error dict instead of raising

[2026-03-24 14:42:00 FIX #10] src/main.py
  - Passed `intervention_logger=intervention_logger` to `run_rebuild()` in `_run_rebuild_cli`

[2026-03-24 14:42:30 FIX #11] src/intake/intervention_log.py
  - Added `failure_report` field to `_format_intervention` markdown output

[2026-03-24 14:42:30 FIX #12] src/intake/intervention_log.py
  - Added `logging.getLogger(__name__).warning(...)` when `---` marker not found in `_rewrite_summary`

[2026-03-24 14:43:00 FIX #13] src/main.py
  - Removed fallback cast logic for invalid action; Pydantic Literal type (FIX-18) handles validation

[2026-03-24 14:43:00 FIX #14] src/intake/rebuild.py
  - Replaced sequential scan in `_group_by_epic` with dict-based grouping to handle non-contiguous epics

[2026-03-24 14:43:30 FIX #15] src/intake/rebuild.py
  - Added `git config user.name` and `git config user.email` after `git init` in `_init_target_project`

## P2 — Type Safety / Lint

[2026-03-24 14:44:00 FIX #16] src/intake/pipeline.py
  - Changed `compiled.invoke(initial_state)` to `compiled.invoke(dict(initial_state))` to satisfy mypy

[2026-03-24 14:44:00 FIX #17] src/intake/pipeline.py
  - Added justification comment to `type: ignore[type-arg]` on `build_intake_graph` return type

[2026-03-24 14:44:30 FIX #18] src/main.py
  - Changed `InterventionRequest.action` from `str` to `Literal["fix", "skip", "abort"]`

[2026-03-24 14:44:30 FIX #19] src/main.py
  - Changed `InterventionResponse.action` from `str` to `Literal["fix", "skip", "abort"]`

[2026-03-24 14:45:00 FIX #20] src/intake/rebuild.py
  - Changed `on_intervention` parameter from `Any | None` to `Callable[[str], str | None] | None`
  - Imported `Callable` from `collections.abc`

[2026-03-24 14:45:00 FIX #21] src/tools/scoped.py
  - Moved `import re` from inside `search_files` function body to module-level imports

[2026-03-24 14:45:30 FIX #22] src/intake/intervention_log.py
  - Changed `self.log_path = log_path` to `self.log_path = Path(log_path)` in `InterventionLogger.__init__`

[2026-03-24 14:45:30 FIX #23] src/intake/intervention_log.py
  - Changed `get_summary` return type from `dict[str, object]` to `dict[str, int | dict[str, int]]`

## P3 — Tests, Edge Cases, Consistency

[2026-03-24 14:45:30 FIX #24] tests/test_intake/test_pipeline.py
  - Changed `assert len(edges) >= 4` to `assert len(edges) == 5`

[2026-03-24 14:46:00 FIX #25] src/intake/spec_reader.py
  - Added `or file_path.is_symlink()` filter in rglob loop to prevent symlink loops

[2026-03-24 14:46:00 FIX #26] src/intake/spec_reader.py
  - Changed `file_path.relative_to(spec_path)` to `.as_posix()` for consistent forward-slash paths

[2026-03-24 14:46:00 FIX #27] src/intake/backlog.py
  - Changed criteria check from `stripped.startswith("- ")` to `line.startswith("- ")` to only capture top-level bullets

[2026-03-24 14:46:00 FIX #28] tests/test_intake/test_pipeline.py
  - Added `load_backlog()` round-trip verification at end of `test_end_to_end_with_mock_llm`

[2026-03-24 14:46:00 FIX #29] tests/test_intake/test_pipeline.py
  - Added `test_failure_propagation_node_level` test verifying read_specs_node fails correctly
  - Note: Full pipeline short-circuit test not feasible with linear LangGraph (no conditional routing)

[2026-03-24 14:46:00 FIX #30] tests/test_tools/test_scoped.py
  - Added `test_rejects_path_escape` tests for both `list_files` and `search_files`

[2026-03-24 14:46:00 FIX #31] src/intake/spec_reader.py
  - Fixed truncation to pre-compute suffix length so total output respects MAX_FILE_CHARS

[2026-03-24 14:46:00 FIX #32] src/intake/backlog.py
  - Converted `os.path.join`/`os.path.exists` to `pathlib.Path` to match spec_reader pattern

[2026-03-24 14:46:00 FIX #33] src/intake/intervention_log.py
  - Added `if entry.files_involved else "None"` check for empty files_involved list

[2026-03-24 14:46:00 FIX #34] src/intake/intervention_log.py
  - Normalized limitation category key to `.lower()` to prevent case-sensitive fragmentation

[2026-03-24 14:46:00 SKIPPED #35] Already addressed by FIX-08 (git tag failure logging)

[2026-03-24 14:46:00 FIX #36] src/multi_agent/roles.py
  - Changed `if working_dir:` to `if working_dir is not None:` to handle empty string correctly

[2026-03-24 14:46:00 FIX #37] tests/test_intake/test_rebuild.py
  - Added 3 tests for `_detect_auto_recovery`: cycle > 1 triggers, cycle <= 1 doesn't, multiple types independent

[2026-03-24 14:46:00 SKIPPED #38] API endpoint test requires TestClient infrastructure beyond scope of clear fixes

[2026-03-24 14:46:00 FIX #39] tests/test_intake/test_intervention_log.py
  - Added tests for `what_developer_did=""` and `agent_limitation=""` raising ValueError

[2026-03-24 14:46:00 FIX #40] tests/test_intake/test_intervention_log.py
  - Added `test_export_multiple_entries` with 3 entries (2 same limitation, 1 different), asserting 2 categories
  - Added `test_case_insensitive_limitation_categories` verifying case normalization

# Completed: 38/40 fixes applied, 2 skipped

# Epic 4 — Code Review Fix Plan

**Category A fixes only.** All items are clear, non-controversial, and require no architectural decisions.
For architectural/controversial items, see `epic4-architect-review-needed.md`.

---

## P0 — Critical / CI-Blocking (3 items)

### A19: Abort action does not stop the entire rebuild
- **File:** `src/intake/rebuild.py:139-156`
- **Issue:** When `on_intervention` returns `None` (abort signal), the story is marked failed but the `for story_entry in stories:` loop continues to the next story. Spec explicitly requires "Support abort to stop the entire rebuild."
- **Fix:** Add a check after `on_intervention` returns `None`: set a flag or `break` out of the story loop. Example:
  ```python
  fix_instruction = on_intervention(error)
  if fix_instruction is None:
      # Abort: stop entire rebuild
      story_results.append({"story": story_title, "status": "aborted"})
      break
  ```
- **Verify:** Add test: call `run_rebuild` with a callback that returns `None` on first failure, assert remaining stories are not executed.

### A02: output_node overwrites pipeline_status from "failed" to "completed"
- **File:** `src/intake/pipeline.py:135-157`
- **Issue:** LangGraph uses last-write-wins. When `read_specs_node` sets `pipeline_status="failed"` but subsequent LLM nodes produce non-empty output, `output_node` returns `pipeline_status: "completed"`, masking the original failure.
- **Fix:** In `output_node`, check the existing `pipeline_status` before proceeding:
  ```python
  if state.get("pipeline_status") == "failed":
      return {"pipeline_status": "failed", "error": state.get("error", "Earlier stage failed")}
  ```
- **Verify:** Add test: invoke `output_node` with state containing `pipeline_status="failed"` and non-empty content, assert it preserves "failed" status.

### A03: Import ordering violation in main.py (ruff I001)
- **File:** `src/main.py:14-16`
- **Issue:** `from pathlib import Path` is separated from other stdlib imports by a blank line. `src.audit_log.audit` import may not be alphabetically sorted with other `src.*` imports. This fails `ruff check`.
- **Fix:** Move `from pathlib import Path` into the stdlib import block (contiguous, no blank line). Sort all `src.*` imports alphabetically. Run `ruff check --fix src/main.py`.
- **Verify:** `ruff check src/main.py` passes.

---

## P1 — High Severity (3 items)

### A01: No exception handling around compiled.invoke() in run_intake_pipeline
- **File:** `src/intake/pipeline.py:222-230`
- **Issue:** If `compiled.invoke()` throws (LLM API failure, network error), `fail_pipeline()` is never called. Pipeline tracker stays in "running" status permanently.
- **Fix:** Wrap `compiled.invoke()` in try/except:
  ```python
  try:
      result = compiled.invoke(initial_state)
  except Exception as e:
      logger.error("Pipeline execution failed: %s", e)
      fail_pipeline(session_id, str(e))
      return {"pipeline_status": "failed", "error": str(e)}
  ```
- **Verify:** Add test: mock `compiled.invoke` to raise `RuntimeError`, assert `fail_pipeline` is called and error dict returned.

### A11: _init_target_project re-raises CalledProcessError — crashes run_rebuild
- **File:** `src/intake/rebuild.py:85, 364-366`
- **Issue:** `_init_target_project()` re-raises `CalledProcessError`. `run_rebuild()` calls it without try/except, so a git init failure crashes with an unhandled exception rather than returning a structured error dict.
- **Fix:** Wrap the call in `run_rebuild`:
  ```python
  try:
      _init_target_project(target_dir)
  except subprocess.CalledProcessError as e:
      fail_pipeline(session_id, str(e))
      return {"pipeline_status": "failed", "error": f"Git initialization failed: {e}"}
  ```
- **Verify:** Add test: mock `_init_target_project` to raise `CalledProcessError`, assert structured error dict returned.

### A16: git config commands missing check=True
- **File:** `src/intake/rebuild.py:333-342`
- **Issue:** `git config` commands don't use `check=True`. If they fail silently, the subsequent `git commit` at line 357 fails with a confusing "please tell me who you are" error.
- **Fix:** Add `check=True` to the `subprocess.run` calls for `git config user.name` and `git config user.email`.
- **Verify:** Add test: verify git config commands are called with `check=True` (mock subprocess).

---

## P2 — Medium Severity (12 items)

### A04: parse_epics_markdown silently returns empty list for non-conforming LLM output
- **File:** `src/intake/backlog.py:66-86`
- **Issue:** Case-sensitive regex (`^##\s+Epic\s+\d+:`) silently returns `[]` for variant LLM output formats. No warning logged.
- **Fix:** Add a `logger.warning` when the function returns an empty list from non-empty input:
  ```python
  if not backlog and lines:
      logger.warning("parse_epics_markdown returned 0 entries from %d lines of input", len(lines))
  ```
- **Verify:** Add test: pass non-conforming markdown, assert warning is logged and empty list returned.

### A05: Stories without parent epic get empty string for epic field
- **File:** `src/intake/backlog.py:56-110`
- **Issue:** If LLM output has story headers before any epic header, `current_epic` is `""`. Stories are created with `epic: ""`.
- **Fix:** Add a `logger.warning` when a story is created with empty epic:
  ```python
  if not current_epic:
      logger.warning("Story '%s' has no parent epic — defaulting to empty", story_title)
  ```
- **Verify:** Add test: input with stories before any epic header, assert warning logged.

### A06: Output files lack required YAML frontmatter
- **File:** `src/intake/pipeline.py:147-151`
- **Issue:** `spec-summary.md` and `epics.md` are written as raw LLM output without YAML frontmatter. Per coding-standards.md, all inter-agent files must have frontmatter.
- **Fix:** Add YAML frontmatter before writing:
  ```python
  frontmatter = (
      "---\n"
      f"agent_role: intake\n"
      f"task_id: {state.get('session_id', 'unknown')}\n"
      f"timestamp: {datetime.now(timezone.utc).isoformat()}\n"
      f"input_files: [{', '.join(state.get('spec_files', []))}]\n"
      "---\n\n"
  )
  ```
- **Verify:** Read output files in test, assert they start with `---\n`.

### A12: search_files regex pattern unsanitized — ReDoS risk
- **File:** `src/tools/scoped.py:175`
- **Issue:** User-supplied regex compiled without validation. Catastrophic backtracking possible.
- **Fix:** Add a timeout or limit regex complexity:
  ```python
  try:
      regex = re.compile(pattern)
  except re.error as e:
      return f"ERROR: Invalid regex pattern: {e}"
  ```
  And add a per-file timeout via `re.search` with a line-by-line approach (already the case), which limits blast radius.
- **Verify:** Add test: pass a known-bad regex pattern, assert `ERROR:` returned.

### A13: _intervention_loggers dict grows unbounded (memory leak)
- **File:** `src/main.py:279`
- **Issue:** Module-level dict accumulates an `InterventionLogger` per session, never cleaned up.
- **Fix:** Add a max size or TTL. Simplest: cap the dict size and evict oldest entries:
  ```python
  _MAX_LOGGERS = 100
  if len(_intervention_loggers) >= _MAX_LOGGERS:
      oldest_key = next(iter(_intervention_loggers))
      del _intervention_loggers[oldest_key]
  ```
- **Verify:** Add test: insert 101 loggers, assert dict size stays at 100.

### A14: rebuild_intervene uses hardcoded ./target/ path
- **File:** `src/main.py:296`
- **Issue:** Intervention log path hardcoded to `./target/` regardless of actual `target_dir`.
- **Fix:** Store `target_dir` alongside the logger (or in the logger itself) and use it for the log path. Requires threading `target_dir` through from the `/rebuild` call.
- **Verify:** Add test: call endpoint with known session, verify log path uses correct directory.

### A15: build_orchestrator() recompiled for every story
- **File:** `src/intake/rebuild.py:277`
- **Issue:** `build_orchestrator()` called inside `_run_story_pipeline()`. Identical graph compiled N times for N stories.
- **Fix:** Compile once in `run_rebuild()` and pass the compiled graph to `_run_story_pipeline()`:
  ```python
  compiled = build_orchestrator()
  for story_entry in stories:
      result = _run_story_pipeline(..., compiled=compiled)
  ```
- **Verify:** Existing tests pass; optionally add a test asserting `build_orchestrator` called once.

### A20: InterventionEntry validation bypassed by "Not specified" defaults
- **File:** `src/intake/intervention_log.py:357-361, 439-444`
- **Issue:** Callers replace empty strings with `"Not specified"` before construction, making `__post_init__` validation unreachable.
- **Fix:** Move the `"Not specified"` substitution into `__post_init__` itself, after validation warns:
  ```python
  def __post_init__(self):
      empty_fields = [f for f in _EVIDENCE_FIELDS if not getattr(self, f)]
      if empty_fields:
          logger.warning("Intervention entry has empty evidence fields: %s", empty_fields)
          for f in empty_fields:
              object.__setattr__(self, f, "Not specified")
  ```
- **Verify:** Add test: create entry with empty evidence fields, assert warning logged and fields filled.

### A21: No tests for /rebuild/intervene API endpoint
- **File:** `tests/test_main.py` (missing)
- **Issue:** The `/rebuild/intervene` endpoint is completely untested.
- **Fix:** Add a test class `TestRebuildInterveneEndpoint` with tests for: valid intervention, missing session_id, skip action, abort action.
- **Verify:** Tests pass.

### A22: _rewrite_summary fragile marker detection
- **File:** `src/intake/intervention_log.py:266-267`
- **Issue:** Uses first `---\n` as marker, which could match content inside the file.
- **Fix:** Use a more specific marker, e.g., search for `---\n` only within the first 10 lines (the frontmatter section):
  ```python
  lines = content.split("\n")
  for i, line in enumerate(lines[:10]):
      if line.strip() == "---" and i > 0:
          marker_pos = sum(len(l) + 1 for l in lines[:i+1])
          break
  ```
- **Verify:** Add test: file with `---` in content body, assert summary rewrite targets correct marker.

### A24: Missing docstrings on ~15 new test methods
- **File:** `tests/test_multi_agent/test_orchestrator.py` (lines 1150-1363)
- **Issue:** Per coding-standards.md, all public functions require docstrings. New test methods in `TestBashNodesPassWorkingDir`, `TestLLMNodesPassWorkingDir` lack them.
- **Fix:** Add single-line docstrings to each test method matching the style of existing tests in the same file.
- **Verify:** `ruff check` passes; visual inspection confirms docstrings present.

### A27: PEP 8 E302: missing blank line before _get_working_dir
- **File:** `src/multi_agent/orchestrator.py:29-31`
- **Issue:** Only 1 blank line between `logger` assignment and `_get_working_dir` function. PEP 8 requires 2.
- **Fix:** Add one more blank line before `def _get_working_dir(...)`.
- **Verify:** `ruff check src/multi_agent/orchestrator.py` passes.

### A28: No tests for spawn.py working_dir threading to injection functions
- **File:** Missing test coverage in `tests/test_multi_agent/`
- **Issue:** `spawn.py` passes `working_dir` to `build_system_prompt()` and `inject_task_context()`, but no test verifies this. Removing the kwarg would break nothing.
- **Fix:** Add tests in `test_spawn.py` (or existing test file) that mock `build_system_prompt` and `inject_task_context`, call `create_agent_subgraph` with a `working_dir`, and assert the kwarg was passed through.
- **Verify:** Tests pass; remove kwarg temporarily to confirm test catches it.

---

## P3 — Low Severity (12 items)

### A07: Brittle edge count assertion in test
- **File:** `tests/test_intake/test_pipeline.py:162-164`
- **Issue:** Asserts `len(edges) == 5` on LangGraph internal representation.
- **Fix:** Replace with assertion on specific edge pairs or remove the count assertion.
- **Verify:** Test still passes after LangGraph upgrade.

### A08: advance_stage called with empty session_id
- **File:** `src/intake/pipeline.py:45`
- **Issue:** `advance_stage("")` when `session_id` missing from state. Silently no-ops.
- **Fix:** No code change needed — document that node-level tests don't exercise tracker integration. Optionally add guard: `if session_id: advance_stage(session_id, ...)`.
- **Verify:** N/A (documentation only) or add guard and verify test coverage.

### A09: build_trace_config not used directly per dev notes
- **File:** `src/intake/pipeline.py`
- **Issue:** Dev notes say to reuse `build_trace_config()`, but `run_sub_agent` calls it internally.
- **Fix:** No code change needed — current behavior is correct (trace config set inside `run_sub_agent`). Document that this is intentional delegation.
- **Verify:** N/A.

### A10: Pipeline tests don't mock pipeline_tracker functions
- **File:** `tests/test_intake/test_pipeline.py`
- **Issue:** Tests call real `advance_stage`/`start_pipeline`/`complete_pipeline`/`fail_pipeline`, causing state leakage.
- **Fix:** Add `@patch("src.intake.pipeline.advance_stage")` (and siblings) to pipeline node tests.
- **Verify:** Tests pass with mocks; no hidden side-effect coupling.

### A17: Empty backlog leaves pipeline tracker stale
- **File:** `src/intake/rebuild.py:57-81`
- **Issue:** Early return on empty backlog doesn't call `complete_pipeline()` or `fail_pipeline()`.
- **Fix:** Add `complete_pipeline(session_id)` before the early return at line 74-81.
- **Verify:** Add test: empty backlog, assert `complete_pipeline` called.

### A18: Git tag name collision on same-named epics
- **File:** `src/intake/rebuild.py:376`
- **Issue:** Two epics with same name after normalization cause `git tag` failure (logged as warning).
- **Fix:** No code change needed — warning is already logged and epic still completes. Optionally add a counter suffix.
- **Verify:** N/A (already handled gracefully).

### A23: Redundant Path() construction
- **File:** `src/intake/intervention_log.py:96, 257, 262`
- **Issue:** `Path(self.log_path)` when `self.log_path` is already a `Path`.
- **Fix:** Use `self.log_path` directly instead of wrapping in `Path()`.
- **Verify:** Existing tests pass.

### A25: Test section comments reference "Story 4.5" instead of "Story 4.4"
- **File:** `tests/test_multi_agent/test_orchestrator.py:1425, 1450, 1484`
- **Issue:** Comments say "Story 4.5" but test Story 4.4 functionality.
- **Fix:** Change "Story 4.5" to "Story 4.4" in all three comment blocks.
- **Verify:** Visual inspection.

### A26: os.chdir in test risks parallel interference
- **File:** `tests/test_intake/test_rebuild.py:379-393`
- **Issue:** `os.chdir(tmp_path)` modifies process-global state.
- **Fix:** Replace with `monkeypatch.chdir(tmp_path)` which auto-restores.
- **Verify:** Test passes with monkeypatch; remove manual try/finally.

### A29: Cross-module import of private function _is_path_allowed
- **File:** `src/tools/scoped.py:61`
- **Issue:** Imports `_is_path_allowed` (private) from `restricted.py`.
- **Fix:** Rename `_is_path_allowed` to `is_path_allowed` in `restricted.py` and update all imports.
- **Verify:** `ruff check` and all tests pass.

### A30: _get_working_dir placed outside Helper Functions section
- **File:** `src/multi_agent/orchestrator.py:31`
- **Issue:** Function is between logger and constants, not with other helpers (lines 112-198).
- **Fix:** Move `_get_working_dir` to the Helper Functions section (after line 112).
- **Verify:** All tests pass; function referenced by same name throughout.

---

## Summary

| Priority | Count | Estimated Effort |
|---|---|---|
| P0 (Critical) | 3 | Small — each is a targeted code change |
| P1 (High) | 3 | Small-Medium — try/except wrapping + tests |
| P2 (Medium) | 12 | Medium — mix of code fixes and new tests |
| P3 (Low) | 12 | Small — cosmetic/doc/minor fixes |
| **Total** | **30** | |

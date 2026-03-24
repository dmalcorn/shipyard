# Epic 4 — Fix Plan (Category A: Clear Fixes Only)

**Scope:** Only unambiguous, non-controversial fixes. No architectural decisions. Each fix has exactly one correct approach.

**Corresponding architect review:** `epic4-architect-review-needed.md` (Category B items)

---

## P0 — Security / Blocks Core Feature

These must be fixed first. They represent security vulnerabilities or broken core functionality.

---

### FIX-01: `list_files` bypasses scope validation (Analysis #21)

- **File:** `src/tools/scoped.py:123`
- **Issue:** `list_files` calls `_resolve(path)` directly instead of `_validate(path)`. An absolute path or `../..` escapes the scoped directory.
- **Fix:** Replace `_resolve(path)` with `_validate(path)` and handle the error string return.
- **Action:**
  ```python
  # Line 123: change _resolve(path) to _validate(path)
  search_root = _validate(path)
  if isinstance(search_root, str):
      return search_root
  ```
- **Verify:** Run `tests/test_tools/test_scoped.py` + add test for path escaping (see FIX-18)

---

### FIX-02: `search_files` bypasses scope validation (Analysis #22)

- **File:** `src/tools/scoped.py:141`
- **Issue:** Same as FIX-01 but for `search_files`. Uses `_resolve(path)` instead of `_validate(path)`.
- **Fix:** Same pattern as FIX-01.
- **Action:**
  ```python
  # Line 141: change _resolve(path) to _validate(path)
  search_root = _validate(path)
  if isinstance(search_root, str):
      return search_root
  ```
- **Verify:** Run `tests/test_tools/test_scoped.py` + add test for path escaping (see FIX-18)

---

### FIX-03: Path injection via unsanitized `session_id` in file path (Analysis #43)

- **File:** `src/main.py:245`
- **Issue:** `session_id` from user request is directly interpolated into a file path: `f"./target/intervention-log-{request.session_id}.md"`. A session_id like `../../etc/cron` writes to arbitrary locations.
- **Fix:** Sanitize `session_id` using the same regex pattern already used in `src/logging/audit.py`.
- **Action:**
  ```python
  import re
  # Before using session_id in file path:
  safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", request.session_id)
  intervention_logger = InterventionLogger(
      log_path=f"./target/intervention-log-{safe_id}.md"
  )
  ```
- **Verify:** Manually test with `session_id="../../etc/test"` — should produce `intervention-log-etctest.md` in `./target/`

---

### FIX-04: `cli_intervention` returns literal `"retry"` not actual fix instruction (Analysis #33)

- **File:** `src/main.py:362`
- **Issue:** `cli_intervention` captures the developer's fix instruction via `cli_intervention_prompt()` but returns the literal string `"retry"`. At `rebuild.py:112-113`, the retry task description gets `"INTERVENTION FIX INSTRUCTION:\nretry"` instead of the actual fix the developer described.
- **Fix:** Capture and return the `what_did` input from the CLI prompt.
- **Action:**
  ```python
  # In cli_intervention callback (main.py ~line 348-362):
  # Change cli_intervention_prompt to also return what_developer_did,
  # or store what_did and return it instead of "retry"
  # Simplest fix: change the return on line 362 from:
  return "retry"
  # to:
  return what_did if what_did else "retry"
  ```
  Note: `cli_intervention_prompt` returns a Literal action, not the instruction text. The callback needs to capture the input text. The simplest approach: add `what_developer_did` as an attribute on the logger, or refactor `cli_intervention_prompt` to also return the instruction string. Since the prompt function already has `what_did` locally, change its return type to `tuple[Literal["fix", "skip", "abort"], str]` returning `(action, what_did)`.
- **Verify:** Run rebuild CLI manually, enter a fix instruction, verify it appears in the retry task description.

---

## P1 — Correctness (Fail-Loud, Error Handling)

These fix silent failures, dead code connections, and missing error handling.

---

### FIX-05: Empty LLM results propagate silently to `output_node` (Analysis #4)

- **File:** `src/intake/pipeline.py:121-143`
- **Issue:** If `run_sub_agent()` returns `{"final_message": ""}`, `output_node` writes empty files and reports `pipeline_status: "completed"`.
- **Fix:** Add validation in `output_node` before writing.
- **Action:**
  ```python
  # In output_node, after getting spec_summary and epics_and_stories:
  if not spec_summary.strip() or not epics_and_stories.strip():
      return {"pipeline_status": "failed", "error": "Intake produced empty spec summary or backlog"}
  ```
- **Verify:** Add unit test: invoke `output_node` with empty `spec_summary` → assert `pipeline_status == "failed"`

---

### FIX-06: `output_node` file writes have no exception handling (Analysis #5)

- **File:** `src/intake/pipeline.py:130-139`
- **Issue:** `os.makedirs()` and `open()` calls are unprotected. A permission error crashes the pipeline instead of setting `pipeline_status: "failed"`. Other nodes (e.g., `read_specs_node`) do catch exceptions.
- **Fix:** Wrap in try/except consistent with `read_specs_node` pattern.
- **Action:**
  ```python
  try:
      os.makedirs(output_dir, exist_ok=True)
      # ... write files ...
  except OSError as e:
      return {"pipeline_status": "failed", "error": f"Failed to write output: {e}"}
  ```
- **Verify:** Unit test: mock `os.makedirs` to raise `PermissionError` → assert `pipeline_status == "failed"`

---

### FIX-07: `_init_target_project` subprocess calls ignore return codes (Analysis #23)

- **File:** `src/intake/rebuild.py:278-298`
- **Issue:** `subprocess.run()` for `git init`, `git add`, `git commit` discard return codes. Silent failures violate fail-loud semantics.
- **Fix:** Use `check=True` on critical subprocess calls, wrapped in try/except.
- **Action:**
  ```python
  try:
      subprocess.run(["git", "init"], cwd=target_dir, capture_output=True, text=True, check=True)
      # ... scaffold files ...
      subprocess.run(["git", "add", "."], cwd=target_dir, capture_output=True, check=True)
      subprocess.run(
          ["git", "commit", "-m", "chore: initial project scaffold"],
          cwd=target_dir, capture_output=True, text=True, check=True,
      )
  except subprocess.CalledProcessError as e:
      logger.error("Git initialization failed: %s", e.stderr or e)
      raise
  ```
- **Verify:** Run `tests/test_intake/test_rebuild.py` — existing tests mock subprocess, so update mocks accordingly.

---

### FIX-08: `_git_tag_epic` subprocess call ignores return code (Analysis #24)

- **File:** `src/intake/rebuild.py:309-314`
- **Issue:** `git tag` failure (duplicate tag, no commits) is silently swallowed.
- **Fix:** Log warning on failure instead of raising (tagging is non-critical).
- **Action:**
  ```python
  result = subprocess.run(
      ["git", "tag", tag_name], cwd=target_dir, capture_output=True, text=True,
  )
  if result.returncode != 0:
      logger.warning("Git tag '%s' failed: %s", tag_name, result.stderr.strip())
  ```
- **Verify:** Run `tests/test_intake/test_rebuild.py::test_git_tag_epic_*`

---

### FIX-09: Missing `epics.md` raises unhandled `FileNotFoundError` (Analysis #29)

- **File:** `src/intake/rebuild.py:51`
- **Issue:** `load_backlog(target_dir)` raises `FileNotFoundError` if `epics.md` doesn't exist. No try/except in `run_rebuild()`.
- **Fix:** Catch the exception and return a failed result.
- **Action:**
  ```python
  try:
      backlog = load_backlog(target_dir)
  except FileNotFoundError as e:
      logger.error("Backlog not found: %s", e)
      return {
          "stories_completed": 0, "stories_failed": 0,
          "interventions": 0, "total_stories": 0,
          "elapsed_seconds": 0.0, "error": str(e),
      }
  ```
- **Verify:** Add test: call `run_rebuild()` with a directory missing `epics.md` → assert no exception, result has error.

---

### FIX-10: `_run_rebuild_cli` doesn't pass `intervention_logger` to `run_rebuild` (Analysis #36)

- **File:** `src/main.py:364`
- **Issue:** `intervention_logger` is created at line 342 but not passed to `run_rebuild()` at line 364. Auto-recovery detection is dead code in CLI mode.
- **Fix:** Pass the parameter.
- **Action:**
  ```python
  result = run_rebuild(
      target_dir=target_dir,
      session_id=session_id,
      on_intervention=cli_intervention,
      intervention_logger=intervention_logger,  # ADD THIS
  )
  ```
- **Verify:** Run `tests/test_intake/test_rebuild.py` — confirm auto-recovery path is exercised.

---

### FIX-11: `failure_report` not persisted to markdown output (Analysis #41)

- **File:** `src/intake/intervention_log.py:200-213`
- **Issue:** `_format_intervention` never writes `failure_report` to the markdown. The raw pipeline failure data is stored in memory but discarded during serialization.
- **Fix:** Add `failure_report` to the formatted output.
- **Action:**
  ```python
  # In _format_intervention, add after "Retry Counts" line:
  f"- **Failure Report:** {entry.failure_report}\n"
  ```
- **Verify:** Run `tests/test_intake/test_intervention_log.py` — update any assertions checking formatted output.

---

### FIX-12: `_rewrite_summary` silently no-ops on missing marker (Analysis #45)

- **File:** `src/intake/intervention_log.py:264-265`
- **Issue:** If `---\n` marker not found, silently returns. Violates fail-loud semantics.
- **Fix:** Add a log warning.
- **Action:**
  ```python
  if marker_pos == -1:
      import logging
      logging.getLogger(__name__).warning("Summary marker '---' not found in %s", self.log_path)
      return
  ```
- **Verify:** Run `tests/test_intake/test_intervention_log.py`

---

### FIX-13: Invalid `action` silently defaults to `"fix"` (Analysis #46)

- **File:** `src/main.py:250`
- **Issue:** Invalid action string silently becomes `"fix"` with no error. Combined with FIX-14 (Literal type), Pydantic will handle validation, but as a defense-in-depth fix:
- **Fix:** Once FIX-14 is applied (Literal type on `InterventionRequest.action`), Pydantic will reject invalid values with a 422 error automatically. This fix is then a no-op. If FIX-14 is applied, remove the fallback line entirely and use `request.action` directly.
- **Action:**
  ```python
  # Remove the fallback cast, rely on Pydantic validation:
  action = request.action  # Already validated by Pydantic Literal type
  ```
- **Verify:** POST `/rebuild/intervene` with `action: "delete"` → assert 422 response.

---

### FIX-14: `_group_by_epic` produces duplicates for non-contiguous stories (Analysis #30)

- **File:** `src/intake/rebuild.py:318-345`
- **Issue:** Sequential scan creates separate groups for same epic if stories aren't contiguous (e.g., `[Epic1-S1, Epic2-S1, Epic1-S2]` → two groups for Epic1).
- **Fix:** Use `dict` to group, then convert to list of tuples.
- **Action:**
  ```python
  def _group_by_epic(backlog):
      groups: dict[str, list[dict[str, Any]]] = {}
      for entry in backlog:
          epic = str(entry.get("epic", ""))
          if epic not in groups:
              groups[epic] = []
          groups[epic].append(entry)
      return list(groups.items())
  ```
- **Verify:** Add test with non-contiguous epics → assert single group per epic.

---

### FIX-15: Git operations fail without `user.name`/`user.email` (Analysis #31)

- **File:** `src/intake/rebuild.py:278-298`
- **Issue:** `git commit` fails on fresh environments (CI, Docker) without git user config.
- **Fix:** Set local git config before committing.
- **Action:**
  ```python
  # After git init, before git commit:
  subprocess.run(
      ["git", "config", "user.name", "Shipyard"], cwd=target_dir, capture_output=True,
  )
  subprocess.run(
      ["git", "config", "user.email", "shipyard@localhost"], cwd=target_dir, capture_output=True,
  )
  ```
- **Verify:** Run in Docker container without global git config → assert `git commit` succeeds.

---

## P2 — Type Safety / mypy / Lint

These fix type errors, suppressed warnings, and lint issues.

---

### FIX-16: mypy strict mode error at `pipeline.py:206` (Analysis #14)

- **File:** `src/intake/pipeline.py:206`
- **Issue:** `compiled.invoke(initial_state)` fails mypy strict. The `# type: ignore[arg-type]` comment is a workaround.
- **Fix:** Cast the initial state to satisfy the Pregel overload:
- **Action:**
  ```python
  result = compiled.invoke(dict(initial_state))
  ```
  Or if that doesn't work:
  ```python
  from typing import cast, Any
  result = compiled.invoke(cast(Any, initial_state))
  ```
- **Verify:** Run `mypy src/intake/pipeline.py --strict`

---

### FIX-17: `type: ignore` suppression on `build_intake_graph` return (Analysis #16)

- **File:** `src/intake/pipeline.py:151`
- **Issue:** `def build_intake_graph() -> StateGraph:  # type: ignore[type-arg]` suppresses missing generic.
- **Fix:** Provide the generic type parameter or keep `type: ignore` with a justification comment. LangGraph's `StateGraph` typing varies by version, so this may be the best option. Add a comment explaining why:
- **Action:**
  ```python
  def build_intake_graph() -> StateGraph:  # type: ignore[type-arg]  # LangGraph StateGraph generic not stable across versions
  ```
- **Verify:** Run `mypy src/intake/pipeline.py --strict`

---

### FIX-18: `InterventionRequest.action` typed as `str` not `Literal` (Analysis #47)

- **File:** `src/main.py:106`
- **Issue:** Accepts any string. Should use `Literal` for Pydantic validation.
- **Fix:**
  ```python
  action: Literal["fix", "skip", "abort"]
  ```
  Also add `from typing import Literal` if not already imported (it is — line 13).
- **Verify:** POST `/rebuild/intervene` with invalid action → assert 422.

---

### FIX-19: `InterventionResponse.action` typed as `str` not `Literal` (Analysis #48)

- **File:** `src/main.py:113`
- **Fix:**
  ```python
  action: Literal["fix", "skip", "abort"]
  ```
- **Verify:** Confirm API schema shows enum values for `action`.

---

### FIX-20: `on_intervention` parameter uses `Any` instead of `Callable` (Analysis #38)

- **File:** `src/intake/rebuild.py:27`
- **Fix:**
  ```python
  from typing import Callable
  on_intervention: Callable[[str], str | None] | None = None,
  ```
- **Verify:** Run `mypy src/intake/rebuild.py --strict`

---

### FIX-21: `import re` inside function body in `search_files` (Analysis #39)

- **File:** `src/tools/scoped.py:138`
- **Issue:** `re` imported inside the function instead of at module level.
- **Fix:** Move `import re` to the top of the file with other stdlib imports (after line 10).
- **Verify:** `ruff check src/tools/scoped.py`

---

### FIX-22: `InterventionLogger.log_path` should be `Path` not `str` (Analysis #55)

- **File:** `src/intake/intervention_log.py:83-84`
- **Issue:** Stored as `str` but used as `Path` throughout. Inconsistent with `AuditLogger` pattern.
- **Fix:**
  ```python
  def __init__(self, log_path: str) -> None:
      self.log_path = Path(log_path)
  ```
  Then update `_append_section` (line 273) which uses `open(self.log_path, ...)` — already works with `Path`.
- **Verify:** Run `tests/test_intake/test_intervention_log.py`

---

### FIX-23: `get_summary` return type uses `object` (Analysis #56)

- **File:** `src/intake/intervention_log.py:143`
- **Fix:**
  ```python
  def get_summary(self) -> dict[str, int | dict[str, int]]:
  ```
- **Verify:** Run `mypy src/intake/intervention_log.py --strict`

---

## P3 — Tests, Edge Cases, Consistency

Lower priority fixes that improve robustness and test coverage.

---

### FIX-24: Weak edge count assertion (Analysis #6)

- **File:** `tests/test_intake/test_pipeline.py:162-163`
- **Fix:** Assert exact edge count: `assert len(edges) == 5`
- **Verify:** Run `tests/test_intake/test_pipeline.py::test_graph_topology`

---

### FIX-25: Symlink loops in spec directory (Analysis #7)

- **File:** `src/intake/spec_reader.py:44`
- **Fix:** Filter out symlinks in the rglob loop:
  ```python
  for file_path in sorted(spec_path.rglob("*")):
      if not file_path.is_file() or file_path.is_symlink():
          continue
  ```
- **Verify:** Add test with symlink loop → assert no infinite hang.

---

### FIX-26: Windows path separators in file headers (Analysis #10)

- **File:** `src/intake/spec_reader.py:60`
- **Fix:** Use `as_posix()` for consistent forward-slash paths:
  ```python
  relative = file_path.relative_to(spec_path).as_posix()
  ```
- **Verify:** Run `tests/test_intake/test_spec_reader.py`

---

### FIX-27: Sub-bullets incorrectly captured as top-level criteria (Analysis #9)

- **File:** `src/intake/backlog.py:63-115`
- **Issue:** `line.strip()` removes indentation before checking `startswith("- ")`, so `    - sub-detail` becomes a top-level criterion.
- **Fix:** Check indentation before stripping:
  ```python
  # Before stripping, check if line has leading whitespace beyond 0-1 spaces
  if in_criteria and line.startswith("- "):  # only top-level bullets
      current_criteria.append(line.strip()[2:])
  ```
- **Verify:** Add test with nested bullets → assert sub-bullets not in criteria list.

---

### FIX-28: Integration test missing `load_backlog` round-trip (Analysis #12)

- **File:** `tests/test_intake/test_pipeline.py:169-203`
- **Fix:** Add `load_backlog()` call at the end of integration test to verify generated `epics.md` is parseable.
- **Verify:** Run `tests/test_intake/test_pipeline.py::test_end_to_end_with_mock_llm`

---

### FIX-29: No test for pipeline failure propagation (Analysis #13)

- **File:** `tests/test_intake/test_pipeline.py`
- **Fix:** Add test: invoke full pipeline with invalid `spec_dir` → assert `pipeline_status == "failed"` and downstream nodes were not invoked (mock `run_sub_agent` and assert not called).
- **Verify:** Run `tests/test_intake/test_pipeline.py`

---

### FIX-30: Missing tests for scoped path escaping in `list_files`/`search_files` (Analysis #37)

- **File:** `tests/test_tools/test_scoped.py`
- **Fix:** Add tests:
  ```python
  def test_list_files_rejects_path_escape(scoped_tools, tmp_path):
      result = scoped_tools["list_files"]("*", path=str(tmp_path.parent))
      assert "ERROR:" in result

  def test_search_files_rejects_path_escape(scoped_tools, tmp_path):
      result = scoped_tools["search_files"]("test", path=str(tmp_path.parent))
      assert "ERROR:" in result
  ```
- **Verify:** Tests fail before FIX-01/02, pass after.

---

### FIX-31: Truncation suffix exceeds `MAX_FILE_CHARS` (Analysis #19)

- **File:** `src/intake/spec_reader.py:57-58`
- **Fix:**
  ```python
  suffix = f"\n\n(truncated, {len(content)} chars total)"
  content = content[:MAX_FILE_CHARS - len(suffix)] + suffix
  ```
  Note: The suffix length depends on `len(content)` which is known before truncation. Pre-compute suffix, then slice.
- **Verify:** Add test: file with exactly 5001 chars → assert output length <= 5000 + header.

---

### FIX-32: Inconsistent `os.path` vs `pathlib` (Analysis #17)

- **File:** `src/intake/backlog.py:37-38`, `src/intake/pipeline.py:130-133`
- **Fix:** Convert `os.path` usage to `pathlib.Path` to match `spec_reader.py` pattern. Low priority — no functional change.
- **Verify:** Run `tests/test_intake/` suite.

---

### FIX-33: Empty `files_involved` produces trailing-space markdown (Analysis #49)

- **File:** `src/intake/intervention_log.py:202`
- **Fix:**
  ```python
  files_list = ", ".join(f"`{f}`" for f in entry.files_involved) if entry.files_involved else "None"
  ```
- **Verify:** Run `tests/test_intake/test_intervention_log.py`

---

### FIX-34: Limitation categories case-sensitive fragmentation (Analysis #50)

- **File:** `src/intake/intervention_log.py:108`
- **Fix:** Normalize key to lowercase:
  ```python
  limitation = entry.agent_limitation.strip().lower()
  ```
- **Verify:** Add test: log two entries with "Cross-module" and "cross-module" → assert single category.

---

### FIX-35: Duplicate git tags not handled (Analysis #34)

- **File:** `src/intake/rebuild.py:309-314`
- **Fix:** Already addressed by FIX-08 (logging on failure). Git tag failure is now logged as a warning.
- **Verify:** See FIX-08.

---

### FIX-36: Empty `working_dir` string treated as falsy (Analysis #32)

- **File:** `src/multi_agent/roles.py:146` (approximate)
- **Fix:** Change `if working_dir:` to `if working_dir is not None:`
- **Verify:** Run `tests/test_multi_agent/test_roles.py`

---

### FIX-37: No tests for `_detect_auto_recovery` (Analysis #53)

- **File:** `tests/test_intake/test_rebuild.py` (new tests)
- **Fix:** Add tests for `_detect_auto_recovery`:
  - `test_cycle_count > 1` triggers `log_auto_recovery`
  - `test_cycle_count <= 1` does not trigger
  - Multiple cycle types trigger independently
- **Verify:** Run `tests/test_intake/test_rebuild.py`

---

### FIX-38: No tests for `/rebuild/intervene` endpoint (Analysis #54)

- **File:** `tests/test_intake/test_intervention_log.py` or new test file
- **Fix:** Add FastAPI `TestClient` test for the endpoint:
  - Valid request → 200 with logged=True
  - Invalid action → 422 (after FIX-18)
  - Path injection session_id → sanitized (after FIX-03)
- **Verify:** Run the new test.

---

### FIX-39: Missing test for validation of other evidence fields (Analysis #57)

- **File:** `tests/test_intake/test_intervention_log.py:201-215`
- **Fix:** Add tests for `what_developer_did=""` and `agent_limitation=""` raising `ValueError`.
- **Verify:** Run `tests/test_intake/test_intervention_log.py`

---

### FIX-40: No test for `export_for_analysis` with multiple entries (Analysis #58)

- **File:** `tests/test_intake/test_intervention_log.py`
- **Fix:** Add test: log 3 interventions (2 same limitation, 1 different) → assert 2 categories, correct counts.
- **Verify:** Run `tests/test_intake/test_intervention_log.py`

---

## Implementation Order

Recommended execution sequence to minimize test breakage:

1. **P0 Security** (FIX-01, 02, 03): Scoped tools + path injection — independent, fix first
2. **P0 Core Feature** (FIX-04): CLI intervention returns fix instruction
3. **P1 Error Handling** (FIX-05 through 15): Can be done in any order, all independent
4. **P2 Types** (FIX-16 through 23): Run mypy after each
5. **P3 Tests** (FIX-24 through 40): Add after the corresponding fixes

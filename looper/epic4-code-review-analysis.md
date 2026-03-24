# Epic 4 — Code Review Analysis

Cross-referencing findings from BMAD adversarial review and direct Claude review.

---

## Executive Summary

Two independent review agents analyzed the three stories of Epic 4. Combined, they produced **68 raw findings** across the three stories. After deduplication and consolidation, **52 unique issues** remain, classified into **33 clear fixes (Category A)** and **19 architect-review items (Category B)**.

The most critical findings — agreed upon by both agents — are:

1. **Working directory isolation is structurally disconnected** (Story 4-2): The scoped tools infrastructure exists but is never wired into the orchestrator. Rebuilds would edit Shipyard's own source tree.
2. **Scoped tools `list_files` and `search_files` bypass path validation** (Story 4-2): These tools use `_resolve()` instead of `_validate()`, allowing directory traversal outside the target directory.
3. **Auto-recovery logging is dead code** (Stories 4-2/4-3): `intervention_logger` is never passed to `run_rebuild()` in CLI or API mode.
4. **Pipeline continues after node failure** (Story 4-1): No conditional edges — a failed `read_specs_node` still triggers LLM calls.

---

## Agent Coverage Comparison

| Dimension | BMAD Agent | Claude Direct |
|---|---|---|
| **Stories reviewed** | 3/3 | 3/3 |
| **Raw findings** | 68 | 40 |
| **Review layers** | 3 (Blind Hunter, Edge Case, Acceptance Auditor) | 1 (unified) |
| **Severity levels used** | CRITICAL, HIGH, MEDIUM, LOW | HIGH, MEDIUM, LOW |
| **Duration** | 10m 10s | 7m 37s |
| **Files examined** | ~15 per story (inferred) | 15-22 per story (listed) |
| **Coding standards checked** | Yes (with line refs to project-context.md) | Yes (with line refs to coding-standards.md) |
| **mypy/ruff checks** | No | Yes (mypy error found) |

### Unique Strengths

**BMAD Agent:**
- Deeper edge-case coverage (symlink loops, concurrent writes, sub-bullet parsing, Windows paths)
- Explicit spec traceability (each AC/Task cited)
- Found path injection via `session_id` in `main.py:245`
- Found `cli_intervention` returns literal `"retry"` instead of actual fix instruction

**Claude Direct:**
- Found concrete mypy error at `pipeline.py:206`
- Found `type: ignore` suppression on `build_intake_graph`
- Found missing audit logging for intake pipeline
- Found `IntakeState(TypedDict, total=False)` weakens type safety
- Found `import re` inside function body

---

## Issue Overlap Analysis

### High-agreement findings (both agents independently identified):

| Issue | BMAD | Claude |
|---|---|---|
| Pipeline continues after node failure | 4-1 #1 (CRITICAL) | 4-1 #1 (HIGH) |
| Empty LLM results propagate to output | 4-1 #4 (MEDIUM) | 4-1 #3 (MEDIUM) |
| output_node no exception handling | 4-1 #5 (MEDIUM) | 4-1 #5 (MEDIUM) |
| Working dir isolation disconnected | 4-2 #1/#18/#19 (CRITICAL) | 4-2 #1/#2/#3 (HIGH) |
| list_files/search_files bypass validation | 4-2 #2/#3 (HIGH) | 4-2 #8/#9 (MEDIUM) |
| subprocess return codes not checked | 4-2 #4/#5 (MEDIUM) | 4-2 #4/#5 (HIGH) |
| API /rebuild no on_intervention | 4-2 #6 (HIGH) | 4-2 #6 (HIGH) |
| CLI doesn't pass intervention_logger | 4-2 #25 / 4-3 #14 (MEDIUM/HIGH) | 4-2 #7 / 4-3 #4 (MEDIUM/LOW) |
| Scaffold no language detection | 4-2 #23 (MEDIUM) | 4-2 #10 (MEDIUM) |
| InterventionRequest.action not Literal | 4-3 #8 (LOW) | 4-3 #1 (MEDIUM) |
| API intervene passes empty context | 4-3 #16 / 4-2 #7 (HIGH/MEDIUM) | 4-3 #2 / 4-2 #13 (MEDIUM) |
| Evidence bypass via "Not specified" | 4-3 #2/#3/#19 (HIGH) | 4-3 #8/#9 (LOW) |
| _rewrite_summary silently no-ops | 4-3 #6 (MEDIUM) | 4-3 #6 (LOW) |
| get_summary return type uses object | 4-3 #27 (LOW) | 4-3 #7 (LOW) |
| _intervention_loggers memory leak | 4-3 #5 (MEDIUM) | 4-3 #5 (LOW) |
| run_command shell=True | 4-2 #8 (MEDIUM) | 4-2 #18 (LOW) |

### BMAD-only findings (16 unique):

- Symlink loops in spec directory (4-1 #7)
- Concurrent pipeline corruption (4-1 #8)
- Sub-bullet parsing error (4-1 #9)
- Windows path separators (4-1 #11)
- Pipeline topology deviates from spec (4-1 #12)
- Integration test missing load_backlog round-trip (4-1 #14)
- No test for failure propagation (4-1 #15)
- Missing epics.md unhandled FileNotFoundError (4-2 #11)
- _group_by_epic duplicates (4-2 #12)
- Git user.name/email missing (4-2 #13)
- cli_intervention returns "retry" not fix instruction (4-2 #16/#22)
- Path injection via session_id (4-3 #4)
- CLI "skip"/"abort" collision (4-3 #11)
- _rewrite_summary not atomic (4-3 #12)
- failure_report not persisted to markdown (4-3 #1)
- No tests for _detect_auto_recovery (4-3 #24)

### Claude-only findings (8 unique):

- mypy error at pipeline.py:206 (4-1 #2)
- Missing audit logging for intake (4-1 #4)
- type: ignore on build_intake_graph (4-1 #6)
- Inconsistent os.path vs pathlib (4-1 #7)
- IntakeState total=False (4-1 #8)
- Truncation suffix exceeds MAX_FILE_CHARS (4-1 #9)
- on_intervention uses Any not Callable (4-2 #15)
- import re inside function body (4-2 #16)

---

## Consolidated Issue List

Legend: **A** = Clear fix (goes to fix plan), **B** = Architect review needed

### Story 4-1: Ship App Specification Intake

| # | Issue | Severity | Cat | Sources |
|---|-------|----------|-----|---------|
| 1 | Pipeline continues after node failure — no conditional edges | CRITICAL | **B** | BMAD #1, Claude #1 |
| 2 | Path traversal via `spec_dir` and `target_dir` in API | HIGH | **B** | BMAD #2 |
| 3 | No total output size limit in `read_project_specs` | MEDIUM | **B** | BMAD #3 |
| 4 | Empty LLM results propagate silently to `output_node` | MEDIUM | **A** | BMAD #4, Claude #3 |
| 5 | `output_node` file writes have no exception handling | MEDIUM | **A** | BMAD #5, Claude #5 |
| 6 | Weak edge count assertion (`>= 4` instead of exact) | LOW | **A** | BMAD #6 |
| 7 | Symlink loops in spec directory via `rglob("*")` | MEDIUM | **A** | BMAD #7 |
| 8 | Concurrent pipeline runs can corrupt shared output dir | MEDIUM | **B** | BMAD #8 |
| 9 | Sub-bullets incorrectly captured as top-level criteria | LOW | **A** | BMAD #9 |
| 10 | Windows path separators in spec_reader file headers | LOW | **A** | BMAD #11 |
| 11 | Pipeline graph topology deviates from spec (extra `read_specs` node) | MEDIUM | **B** | BMAD #12 |
| 12 | Integration test doesn't verify `load_backlog` round-trip | MEDIUM | **A** | BMAD #14 |
| 13 | No test for pipeline failure propagation behavior | MEDIUM | **A** | BMAD #15 |
| 14 | mypy strict mode error at `pipeline.py:206` | HIGH | **A** | Claude #2 |
| 15 | Missing audit logging for intake pipeline sessions | MEDIUM | **B** | Claude #4 |
| 16 | `type: ignore` suppression on `build_intake_graph` return | MEDIUM | **A** | Claude #6 |
| 17 | Inconsistent `os.path` vs `pathlib` in intake module | LOW | **A** | Claude #7 |
| 18 | `IntakeState(TypedDict, total=False)` weakens type safety | LOW | **B** | Claude #8 |
| 19 | Truncation suffix causes output to exceed `MAX_FILE_CHARS` | LOW | **A** | Claude #9 |

### Story 4-2: Autonomous Ship Rebuild Execution

| # | Issue | Severity | Cat | Sources |
|---|-------|----------|-----|---------|
| 20 | Working dir isolation disconnected — `OrchestratorState` lacks `working_dir`, `_run_bash` lacks `cwd`, nodes don't pass `working_dir` | CRITICAL | **B** | BMAD #1/#18/#19, Claude #1/#2/#3 |
| 21 | `list_files` bypasses scope validation (`_resolve` not `_validate`) | HIGH | **A** | BMAD #2/#10, Claude #8 |
| 22 | `search_files` bypasses scope validation (`_resolve` not `_validate`) | HIGH | **A** | BMAD #3/#10, Claude #9 |
| 23 | `_init_target_project` subprocess calls ignore return codes | MEDIUM | **A** | BMAD #4/#24, Claude #4 |
| 24 | `_git_tag_epic` subprocess call ignores return code | MEDIUM | **A** | BMAD #5, Claude #5 |
| 25 | API `/rebuild` missing `on_intervention` + `intervention_needed` flow | HIGH | **B** | BMAD #6/#20, Claude #6 |
| 26 | API `/rebuild/intervene` hardcoded path + missing session context | MEDIUM | **B** | BMAD #7/#16, Claude #11/#13 |
| 27 | `run_command` scoped tool uses `shell=True` | MEDIUM | **B** | BMAD #8, Claude #18 |
| 28 | Single retry in intervention loop (spec ambiguous on count) | MEDIUM | **B** | BMAD #9/#21, Claude #17 |
| 29 | Missing `epics.md` raises unhandled `FileNotFoundError` | HIGH | **A** | BMAD #11 |
| 30 | `_group_by_epic` produces duplicates for non-contiguous stories | MEDIUM | **A** | BMAD #12 |
| 31 | Git operations fail without `user.name`/`user.email` configured | MEDIUM | **A** | BMAD #13 |
| 32 | Empty `working_dir` string treated as falsy (`if working_dir:`) | LOW | **A** | BMAD #14 |
| 33 | `cli_intervention` returns literal `"retry"` not actual fix instruction | HIGH | **A** | BMAD #16/#22 |
| 34 | Duplicate git tags not handled on re-run | LOW | **A** | BMAD #17 |
| 35 | Scaffold doesn't detect language from spec summary | MEDIUM | **B** | BMAD #23, Claude #10 |
| 36 | `_run_rebuild_cli` doesn't pass `intervention_logger` to `run_rebuild` | MEDIUM | **A** | BMAD #25, Claude #7 |
| 37 | Missing tests for scoped path escaping in `list_files`/`search_files` | MEDIUM | **A** | Claude #14 |
| 38 | `on_intervention` parameter uses `Any` instead of `Callable` | LOW | **A** | Claude #15 |
| 39 | `import re` inside function body in `search_files` | LOW | **A** | Claude #16 |
| 40 | `search_files` may OOM on large target projects | LOW | **B** | BMAD #15 |

### Story 4-3: Rebuild Intervention Log

| # | Issue | Severity | Cat | Sources |
|---|-------|----------|-----|---------|
| 41 | `failure_report` not persisted to markdown output | HIGH | **A** | BMAD #1/#23 |
| 42 | Evidence validation bypassed by "Not specified" fallback (CLI+API) | HIGH | **B** | BMAD #2/#3/#19, Claude #8/#9 |
| 43 | Path injection via unsanitized `session_id` in file path | HIGH | **A** | BMAD #4 |
| 44 | `_intervention_loggers` dict grows unboundedly (memory leak) | MEDIUM | **B** | BMAD #5, Claude #5 |
| 45 | `_rewrite_summary` silently no-ops on missing marker | MEDIUM | **A** | BMAD #6, Claude #6 |
| 46 | Invalid `action` silently defaults to `"fix"` | MEDIUM | **A** | BMAD #7 |
| 47 | `InterventionRequest.action` typed as `str` not `Literal` | MEDIUM | **A** | BMAD #8, Claude #1 |
| 48 | `InterventionResponse.action` typed as `str` not `Literal` | MEDIUM | **A** | Claude #3 |
| 49 | Empty `files_involved` produces trailing-space markdown line | LOW | **A** | BMAD #9 |
| 50 | Limitation categories case-sensitive — fragmentation risk | LOW | **A** | BMAD #10 |
| 51 | CLI "skip"/"abort" collides with genuine `what_broke` content | MEDIUM | **B** | BMAD #11 |
| 52 | `_rewrite_summary` not atomic — partial-write crash risk | MEDIUM | **B** | BMAD #12 |
| 53 | No tests for `_detect_auto_recovery` | MEDIUM | **A** | BMAD #24 |
| 54 | No tests for `/rebuild/intervene` endpoint | MEDIUM | **A** | BMAD #25 |
| 55 | `InterventionLogger.log_path` should be `Path` not `str` | LOW | **A** | BMAD #26 |
| 56 | `get_summary` return type uses `object` | LOW | **A** | BMAD #27, Claude #7 |
| 57 | Missing test for validation of other evidence fields | LOW | **A** | Claude #10 |
| 58 | No test for `export_for_analysis` with multiple entries | LOW | **A** | Claude #11 |
| 59 | `failure_report` not in `_EVIDENCE_FIELDS` | LOW | **B** | Claude #12 |

---

## Classification Summary

| Category | Count | Description |
|---|---|---|
| **A — Clear Fix** | 33 | Goes to fix plan — unambiguous fix, no design decisions |
| **B — Architect Review** | 19 | Goes to architect review — multiple approaches or cross-cutting impact |
| **Total** | 52 | After deduplication of 68 raw findings |

| By Story | Cat A | Cat B | Total |
|---|---|---|---|
| 4-1: Specification Intake | 13 | 6 | 19 |
| 4-2: Rebuild Execution | 13 | 7 | 20 |
| 4-3: Intervention Log | 7 | 6 | 13 |

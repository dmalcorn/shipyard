# Epic 4 — Architect Recommendations

**Date:** 2026-03-24
**Scope:** Decisions on all 18 ARCH items from `epic4-architect-review-needed.md`
**Corresponding fix plan:** `epic4-architect-fix-plan.md`

---

## Executive Summary

| Item | Decision | Action | Priority |
|---|---|---|---|
| ARCH-01 | Option B — optional `working_dir` field | Implement now | P0 |
| ARCH-02 | Option A — conditional edge after `read_specs` | Implement now | P0 |
| ARCH-03 | Option D — defer API intervention to later | Document gap | Deferred |
| ARCH-04 | Option B — resolve and validate paths | Implement now | P1 |
| ARCH-05 | Option D — accept risk, document | Add docstring | Deferred |
| ARCH-06 | Option C — skip scaffold detection | No code change | Deferred |
| ARCH-07 | Option A (CLI) + C (API) | Implement CLI re-prompt | P1 |
| ARCH-08 | Option A — keep 4-node, update spec | Update spec doc | P3 |
| ARCH-09 | Option A — configurable max retries = 3 | Implement now | P1 |
| ARCH-10 | Option C — dual limit (50 files + 100K chars) | Implement now | P2 |
| ARCH-11 | Option A — keep `total=False`, add runtime check | Implement now | P2 |
| ARCH-12 | Option C — document as single-user | No code change | Deferred |
| ARCH-13 | Option A — add AuditLogger to intake paths | Implement now | P2 |
| ARCH-14 | Option A — separate action prompt from evidence | Implement now | P1 |
| ARCH-15 | Option B — keep current, not worth platform risk | No code change | Deferred |
| ARCH-16 | Option D — defer to ARCH-03 | No code change | Deferred |
| ARCH-17 | Option C — defer, v1 targets are small | No code change | Deferred |
| ARCH-18 | Option C — defer to ARCH-03 | No code change | Deferred |

**Actionable items:** 10 (ARCH-01, 02, 04, 07, 08, 09, 10, 11, 13, 14)
**Deferred items:** 8 (ARCH-03, 05, 06, 12, 15, 16, 17, 18)

---

## Detailed Rationale

### ARCH-01: Working Directory Isolation — IMPLEMENT (Option B)

**Decision:** Add `working_dir: str` as an optional field with empty-string default to `OrchestratorState`. Thread through all agent nodes and `_run_bash`.

**Rationale:**
- This is the primary requirement of Story 4-2. Without it, scoped tools are built but never used during rebuild.
- Option B (optional with default) is the right choice because:
  - Existing non-rebuild callers continue working without changes.
  - `_run_story_pipeline` already has `target_dir` — it just needs to pass it through.
  - Agent nodes already call `run_sub_agent()` which already accepts `working_dir` — the plumbing exists.
  - The only missing piece is the state field and the threading.
- Option A (required field) rejected: would break existing Epic 3 orchestrator tests that don't provide `working_dir`.
- Option C (separate state class) rejected: code duplication for no benefit — the orchestrator is the same pipeline either way.

**Cross-cutting impact:** Epic 3 orchestrator tests pass unchanged (empty string = default tools). `_run_bash` gains a `cwd` parameter but defaults to `None` (current behavior).

---

### ARCH-02: Pipeline Conditional Edges — IMPLEMENT (Option A)

**Decision:** Add a conditional edge from `read_specs` to either `intake_specs` or `END`, routed by `pipeline_status`.

**Rationale:**
- `read_specs_node` can fail (missing dir, empty specs). When it does, `pipeline_status` is set to `"failed"` but the pipeline unconditionally proceeds to `intake_specs_node`, which sends empty `raw_specs` to the LLM — burning API credits for nothing.
- Conditional edges are the LangGraph-idiomatic approach (coding standards: "Conditional edges: Route based on state fields").
- Only the `read_specs → intake_specs` edge needs to be conditional. Downstream nodes (`intake_specs`, `create_backlog`) depend on LLM output — if the LLM returns empty, that's caught by `output_node`'s existing validation (FIX-05).
- Adding conditional edges to every transition is over-engineered for a 4-node pipeline.

---

### ARCH-03: API Rebuild Intervention — DEFER (Option D)

**Decision:** Defer full API intervention architecture. Document the gap. Ship CLI-only intervention for v1.

**Rationale:**
- Implementing async polling (Option A) requires: background threading, session state management, a `/rebuild/status` endpoint, pausing the rebuild loop mid-story, and resuming from a persisted state. This is significant scope that belongs in its own story.
- Shipyard's primary interface is CLI. The API rebuild endpoint currently runs synchronously and returns results — functional for automated/scripted usage without human intervention.
- The CLI intervention path (`--rebuild`) works correctly with `on_intervention` callbacks.
- The `/rebuild/intervene` endpoint exists for logging but is disconnected from the actual rebuild loop. This is accurately documented as a known gap.

**Gap documentation:** Add a comment in `src/main.py` above the `/rebuild` and `/rebuild/intervene` endpoints noting that API-based intervention (pause/resume) is deferred to a future epic.

---

### ARCH-04: Path Traversal Sandboxing — IMPLEMENT (Option B)

**Decision:** Resolve and validate `spec_dir` and `target_dir` in API endpoints. Reject paths that resolve outside the current working directory.

**Rationale:**
- Shipyard is a local developer tool for v1. Full `SHIPYARD_WORKSPACE` env var (Option A) is over-engineering.
- But accepting completely arbitrary paths is a bad default even for local tools — a typo in `spec_dir` could read sensitive files, a bad `target_dir` could overwrite important data.
- Simple validation: `Path(x).resolve()` must be relative to `Path.cwd()` or a configured base. No `..` traversal escaping.
- Apply to both `/intake` and `/rebuild` endpoints.

---

### ARCH-05: `shell=True` Security — DEFER (Option D)

**Decision:** Accept the risk for v1. Add a docstring note.

**Rationale:**
- Shipyard is a local developer tool. The LLM-generated commands run with the same permissions as the developer. This is the same trust model as every IDE terminal extension.
- Removing `shell=True` breaks pipes, redirections, and `&&` chains that agents legitimately need during rebuild (e.g., `cd src && python -m pytest`).
- The scoped tool already constrains `cwd` to the target directory — commands start in the right place.
- Command allowlists (Option A) are brittle and create a false sense of security.
- Container sandboxing (Option C) is the right long-term answer but requires infrastructure not in scope for Epic 4.

---

### ARCH-06: Scaffold Language Detection — DEFER (Option C)

**Decision:** Skip for now. Generic scaffold (README) is sufficient.

**Rationale:**
- The dev agent's first action when implementing Story 1 of the target project will be to read `spec-summary.md` and create appropriate files. The agent is perfectly capable of creating `setup.py`, `package.json`, or `go.mod` as part of its normal workflow.
- Adding keyword detection adds brittle code that duplicates what the LLM already does well.
- If scaffold detection becomes important, it should be an LLM-based approach (Option B) since it's more accurate — but that's a future optimization.

---

### ARCH-07: Evidence Validation — IMPLEMENT CLI (Option A), DEFER API (Option C)

**Decision:** CLI re-prompts on empty input. API keeps current behavior.

**Rationale:**
- CLI users are already interacting — re-prompting costs nothing and ensures data quality for Story 5.1 comparative analysis.
- API callers submit structured data; empty fields are a client bug, not a common accident. Forcing non-empty via 422 can wait for v1 feedback.
- Remove the `"Not specified"` fallback in CLI path. Keep it in API path (prevents crashes on empty input until API validation is designed properly with ARCH-03).

---

### ARCH-08: Intake Pipeline Topology — UPDATE SPEC (Option A)

**Decision:** Keep the 4-node topology. Update the story spec to reflect reality.

**Rationale:**
- Separating file I/O (`read_specs`) from LLM processing (`intake_specs`) is objectively cleaner — single responsibility, testable independently, enables the ARCH-02 conditional edge.
- The spec says 3 nodes but the implementation has a good reason for 4. Update the spec.
- This is a documentation-only change.

---

### ARCH-09: Intervention Retry Count — IMPLEMENT (Option A, max=3)

**Decision:** Add `MAX_INTERVENTION_RETRIES = 3` constant. Loop until success or max reached.

**Rationale:**
- Single retry (Option B) is too restrictive — a developer might need 2-3 attempts to diagnose and fix an issue, especially if the first fix partially addresses the problem.
- Unlimited retries (Option C) has no cost ceiling and could loop forever on unfixable issues.
- `MAX_INTERVENTION_RETRIES = 3` balances flexibility with cost control. Each retry is a full orchestrator invocation (expensive), so 3 is a reasonable cap.
- The constant should be in `rebuild.py` alongside the rebuild loop.

---

### ARCH-10: Total Output Size Limit — IMPLEMENT (Option C, dual limit)

**Decision:** Add `MAX_SPEC_FILES = 50` and `MAX_TOTAL_SPEC_CHARS = 100_000` to `spec_reader.py`.

**Rationale:**
- Individual file cap (5000 chars) isn't sufficient — 1000 small files still produces a massive prompt.
- File count limit (50) prevents the pathological case of many small files.
- Character limit (100K) is safe for Claude models (200K context window, minus system prompt and overhead).
- Both limits together cover all edge cases. Log a warning when either limit is hit.

---

### ARCH-11: IntakeState `total=False` — KEEP + VALIDATE (Option A)

**Decision:** Keep `total=False`. Add runtime validation for required fields in `run_intake_pipeline`.

**Rationale:**
- LangGraph nodes return partial state updates. `total=False` is the LangGraph convention — every LangGraph example in the docs uses this pattern.
- Switching to `total=True` with `NotRequired` would require every node to explicitly return all required fields, which is verbose and error-prone.
- Instead, validate required fields (`spec_dir`, `output_dir`) at pipeline entry in `run_intake_pipeline` before invoking the graph. This catches caller errors without fighting the framework.

---

### ARCH-12: Concurrent Pipeline Handling — DEFER (Option C)

**Decision:** Document as single-user tool for v1. No code change.

**Rationale:**
- CLI is inherently single-user.
- API concurrency is only a concern if Shipyard is deployed as a shared service — not the v1 use case.
- Adding file locks (Option A) or unique subdirs (Option B) adds complexity with no current consumer.

---

### ARCH-13: Audit Logging for Intake — IMPLEMENT (Option A)

**Decision:** Add `AuditLogger` to both CLI and API intake paths.

**Rationale:**
- Every other code path (`/instruct`, `_run_cli`, `_run_rebuild_cli`) uses `AuditLogger`. Intake is the outlier.
- The architecture doc says "Every agent session produces a markdown log." The intake pipeline spawns agents via `run_sub_agent` — it is an agent session.
- Simple implementation: create `AuditLogger` at the start of `_run_intake` and the `/intake` endpoint, same pattern as `_run_cli`.

---

### ARCH-14: CLI Command Word Collision — IMPLEMENT (Option A)

**Decision:** Restructure the CLI prompt to ask for action first, then evidence.

**Rationale:**
- Current behavior: if a user types "skip" as a description of what broke (e.g., "The skip logic in the router is broken"), it's interpreted as the skip command.
- Option A (separate action prompt) is the cleanest fix. Ask "Action? [fix/skip/abort]:" first, then only if "fix", ask for evidence fields.
- Option B (prefix commands) changes the interface in a non-obvious way.
- Option C (case-sensitive matching) is fragile.

---

### ARCH-15: `_rewrite_summary` Atomic Writes — DEFER (Option B)

**Decision:** Keep current behavior. Not worth the platform-specific complexity.

**Rationale:**
- The write operation is: read file, rebuild header, write file. The crash window is microseconds.
- On Windows (this project's dev environment), atomic rename has platform-specific caveats (`os.replace` works but temp file cleanup on crash is not guaranteed).
- If the file is corrupted, the next `_ensure_initialized` call on a fresh run creates a new one.
- The intervention log is supplementary — the rebuild can continue without it.

---

### ARCH-16: `_intervention_loggers` Memory Management — DEFER (Option D)

**Decision:** Defer to ARCH-03 resolution.

**Rationale:** The logger lifetime is part of the session lifecycle design, which is part of the API intervention architecture (ARCH-03). Fixing it independently would be undone when ARCH-03 is implemented.

---

### ARCH-17: `search_files` OOM — DEFER (Option C)

**Decision:** Defer. Target projects generated by Shipyard won't be large enough to OOM.

**Rationale:** Shipyard rebuilds projects from scratch. A freshly generated project has a handful of files. The OOM risk is theoretical for v1.

---

### ARCH-18: `failure_report` Validation — DEFER (Option C)

**Decision:** Defer until ARCH-03 provides the mechanism for API endpoints to supply real failure reports.

**Rationale:** Adding `failure_report` to `_EVIDENCE_FIELDS` now would break the current `/rebuild/intervene` endpoint which passes `failure_report=""`. The API endpoint is disconnected from the rebuild loop (ARCH-03 gap) — it can't provide real failure data until that's fixed.

---

## Skipped Items from Fix Phase

### SKIPPED #35 (Duplicate git tags)
**Decision:** Already addressed by FIX-08. No further action needed.

### SKIPPED #38 (API endpoint test requires TestClient)
**Decision:** Include in fix plan as P3. TestClient setup is straightforward — `from fastapi.testclient import TestClient` with the existing `app`. Not an architectural decision.

---

## Deferred Items Tracking

These items are explicitly deferred and should be tracked for future work:

| Item | Defer Reason | Trigger to Revisit |
|---|---|---|
| ARCH-03 | Significant scope, CLI works for v1 | API users need intervention support |
| ARCH-05 | Local tool trust model, no infrastructure | Hosted deployment planned |
| ARCH-06 | Dev agent handles scaffold naturally | Scaffold failures in rebuild testing |
| ARCH-12 | Single-user CLI for v1 | Multi-user API deployment |
| ARCH-15 | Tiny crash window, Windows caveats | Observed file corruption in production |
| ARCH-16 | Tied to ARCH-03 session lifecycle | ARCH-03 implementation |
| ARCH-17 | V1 targets are small | Large target projects attempted |
| ARCH-18 | Tied to ARCH-03 API plumbing | ARCH-03 implementation |

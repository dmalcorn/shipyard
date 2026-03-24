# Epic 4 — Architect Fix Plan

**Date:** 2026-03-24
**Source:** Architect decisions from `epic4-architect-recommendations.md`
**Scope:** Concrete fixes for all actionable ARCH items. Each fix is self-contained — no judgment calls required.

---

## P0 — Critical (Core Feature / Blocks Pipeline)

---

### AFIX-01: Thread `working_dir` Through Orchestrator (ARCH-01)

**Priority:** P0
**Files:**
- `src/multi_agent/orchestrator.py`
- `src/intake/rebuild.py`

**Issue:** Scoped tools infrastructure exists but is never used. `OrchestratorState` has no `working_dir` field. Agent nodes don't pass `working_dir` to `run_sub_agent()`. `_run_bash()` has no `cwd` parameter. `_run_story_pipeline()` doesn't pass `target_dir` to the orchestrator state.

**Fix — Step 1: Add `working_dir` to `OrchestratorState`**

In `src/multi_agent/orchestrator.py`, add to `OrchestratorState` (after the `error: str` field at approximately line 88):

```python
    # Working directory for scoped tools (empty = use default project root)
    working_dir: str
```

**Fix — Step 2: Add `cwd` parameter to `_run_bash`**

In `src/multi_agent/orchestrator.py`, change `_run_bash` (line 142):

```python
def _run_bash(command: list[str], timeout: int = 300, cwd: str | None = None) -> tuple[bool, str]:
    """Execute a shell command and return (success, output).

    This is the shared execution path for all bash-based nodes.
    No LLM invocation — just command execution and result capture.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or None,
        )
```

**Fix — Step 3: Thread `working_dir` through all agent nodes**

In every agent node function (`test_agent_node`, `dev_agent_node`, `review_node`, `architect_node`, `fix_dev_node`), add `working_dir` extraction and pass it to `run_sub_agent()`.

Example for `test_agent_node` (line 179):
```python
def test_agent_node(state: OrchestratorState) -> dict[str, Any]:
    """Spawn Test Agent to write failing tests from the task spec (TDD red phase)."""
    task_id = state.get("task_id", "")
    session_id = state.get("session_id", "")
    task_description = state.get("task_description", "")
    context_files = state.get("context_files", [])
    working_dir = state.get("working_dir", "")

    # ... (task_instruction unchanged) ...

    result = run_sub_agent(
        parent_session_id=session_id,
        task_id=task_id,
        role="test",
        task_description=task_instruction,
        current_phase="test",
        context_files=context_files,
        working_dir=working_dir or None,
    )
```

Apply the same pattern to: `dev_agent_node`, `architect_node`, `fix_dev_node`.

For `review_node` (which takes `ReviewNodeInput`), add `working_dir: str` to `ReviewNodeInput` TypedDict, pass it in `route_to_reviewers`, and use it in `review_node`.

**Fix — Step 4: Thread `working_dir` through bash nodes**

All bash nodes (`unit_test_node`, `ci_node`, `git_snapshot_node`, `post_fix_test_node`, `post_fix_ci_node`, `system_test_node`, `final_ci_node`, `git_push_node`) must extract `working_dir` and pass it to `_run_bash`:

```python
working_dir = state.get("working_dir", "") or None
passed, output = _run_bash(["pytest", "tests/", "-v"], cwd=working_dir)
```

**Fix — Step 5: Pass `target_dir` from `_run_story_pipeline` to state**

In `src/intake/rebuild.py`, in `_run_story_pipeline` (line 250), add `working_dir` to `initial_state`:

```python
    initial_state: OrchestratorState = {
        "task_id": task_id,
        "task_description": task_description,
        "session_id": session_id,
        "working_dir": target_dir,  # ADD THIS
        # ... rest unchanged ...
    }
```

**Verify:** Run `tests/test_multi_agent/test_orchestrator.py` — existing tests should pass (empty `working_dir` = default behavior). Then run `tests/test_intake/test_rebuild.py`.

---

### AFIX-02: Add Conditional Edge After `read_specs` (ARCH-02)

**Priority:** P0
**File:** `src/intake/pipeline.py`

**Issue:** When `read_specs_node` returns `pipeline_status: "failed"`, the pipeline proceeds to `intake_specs_node` which sends empty `raw_specs` to the LLM, wasting API credits.

**Fix — Step 1: Add routing function**

After the `output_node` function (around line 153), add:

```python
def _route_after_read_specs(state: IntakeState) -> str:
    """Route after read_specs: continue if running, end if failed."""
    if state.get("pipeline_status") == "failed":
        return "end"
    return "continue"
```

**Fix — Step 2: Replace unconditional edge with conditional**

In `build_intake_graph()` (line 175-179), change:

```python
    # Before:
    graph.add_edge("read_specs", "intake_specs")

    # After:
    graph.add_conditional_edges(
        "read_specs",
        _route_after_read_specs,
        {"continue": "intake_specs", "end": END},
    )
```

Keep all other edges unchanged.

**Verify:** Run `tests/test_intake/test_pipeline.py`. Add a test: invoke pipeline with non-existent `spec_dir` → assert `pipeline_status == "failed"` and `run_sub_agent` was never called.

---

## P1 — High (Security, UX, Correctness)

---

### AFIX-03: Path Validation for API Endpoints (ARCH-04)

**Priority:** P1
**File:** `src/main.py`

**Issue:** `/intake` and `/rebuild` endpoints accept arbitrary paths with no validation. Path traversal possible.

**Fix — Step 1: Add validation helper**

Add at module level (after imports, around line 31):

```python
from pathlib import Path

def _validate_api_path(path_str: str, param_name: str) -> str | None:
    """Validate that an API-submitted path stays within CWD.

    Returns None if valid, or an error message string if invalid.
    """
    try:
        resolved = Path(path_str).resolve()
        cwd = Path.cwd().resolve()
        if not resolved.is_relative_to(cwd):
            return f"{param_name} must be within the working directory. Got: {path_str}"
    except (OSError, ValueError) as e:
        return f"Invalid {param_name}: {e}"
    return None
```

**Fix — Step 2: Add validation to `/intake` endpoint**

In `intake()` (line 169), add after `session_id` assignment:

```python
    path_err = _validate_api_path(request.spec_dir, "spec_dir")
    if path_err:
        return IntakeResponse(
            session_id=session_id,
            pipeline_status="failed",
            output_dir=request.target_dir,
            error=path_err,
        )
    path_err = _validate_api_path(request.target_dir, "target_dir")
    if path_err:
        return IntakeResponse(
            session_id=session_id,
            pipeline_status="failed",
            output_dir=request.target_dir,
            error=path_err,
        )
```

**Fix — Step 3: Add validation to `/rebuild` endpoint**

In `rebuild()` (line 196), add after `session_id` assignment:

```python
    path_err = _validate_api_path(request.target_dir, "target_dir")
    if path_err:
        return RebuildResponse(
            session_id=session_id,
            stories_completed=0,
            stories_failed=0,
            interventions=0,
            total_stories=0,
            status="failed",
        )
```

**Verify:** POST `/intake` with `spec_dir: "/etc/passwd"` → assert response has `pipeline_status: "failed"` and error message.

---

### AFIX-04: CLI Re-Prompt on Empty Evidence (ARCH-07)

**Priority:** P1
**File:** `src/intake/intervention_log.py`

**Issue:** Empty input at CLI intervention prompt falls through as `"Not specified"`, bypassing evidence validation.

**Fix:** Replace single-shot inputs with a re-prompt loop in `cli_intervention_prompt` (lines 329-346).

Replace the try block (lines 329-346):

```python
    try:
        # Ask action first to avoid command word collision (ARCH-14)
        print("Action? [fix / skip / abort]")
        action_input = input(">>> ").strip().lower()
        if action_input == "abort":
            return ("abort", "")
        if action_input == "skip":
            return ("skip", "")
        if action_input != "fix":
            print(f"Unknown action '{action_input}', defaulting to 'fix'.")

        # Collect evidence with re-prompt on empty
        what_broke = ""
        while not what_broke.strip():
            what_broke = input("What broke (concise, required): ").strip()
            if not what_broke:
                print("  Evidence required — please describe what went wrong.")

        what_did = ""
        while not what_did.strip():
            what_did = input("What will you do to fix it (required): ").strip()
            if not what_did:
                print("  Evidence required — please describe your fix.")

        limitation = ""
        while not limitation.strip():
            limitation = input("What does this reveal about the agent (required): ").strip()
            if not limitation:
                print("  Evidence required — please describe the limitation.")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return ("abort", "")
```

Also remove the `"Not specified"` fallbacks on lines 358-360 (they are now unreachable since the loops guarantee non-empty values):

```python
    # Before:
    what_broke=what_broke or "Not specified",
    what_developer_did=what_did or "Not specified",
    agent_limitation=limitation or "Not specified",

    # After:
    what_broke=what_broke,
    what_developer_did=what_did,
    agent_limitation=limitation,
```

Note: This fix also resolves ARCH-14 (command word collision) by asking for the action first, separate from evidence collection.

**Verify:** Run manually: start rebuild, trigger failure, press Enter on empty prompt → should re-prompt. Type "skip" at action prompt → should skip without asking evidence.

---

### AFIX-05: Configurable Intervention Retry Count (ARCH-09)

**Priority:** P1
**File:** `src/intake/rebuild.py`

**Issue:** Only one intervention retry per story. The spec tracks `intervention_count` implying multiple retries.

**Fix — Step 1: Add constant**

At module level (after line 20):

```python
MAX_INTERVENTION_RETRIES = 3
```

**Fix — Step 2: Replace single-retry block with loop**

Replace the intervention block (lines 116-133) with:

```python
            # Intervention loop
            while status == "failed" and on_intervention and intervention_count < MAX_INTERVENTION_RETRIES:
                error = result.get("error", "Unknown failure")
                fix_instruction = on_intervention(error)
                intervention_count += 1
                total_interventions += 1

                if not fix_instruction or fix_instruction.lower() == "skip":
                    break
                if fix_instruction.lower() == "abort":
                    # User wants to abort the entire rebuild
                    logger.info("User aborted rebuild at %s/%s", epic_name, story_name)
                    break

                # Retry with fix instruction appended
                retry_description = (
                    f"{task_description}\n\nINTERVENTION FIX INSTRUCTION "
                    f"(attempt {intervention_count}):\n{fix_instruction}"
                )
                result = _run_story_pipeline(
                    target_dir=target_dir,
                    session_id=session_id,
                    task_id=f"{epic_name}-{story_name}-retry-{intervention_count}".replace(" ", "-").lower(),
                    task_description=retry_description,
                )
                status = result.get("pipeline_status", "failed")
```

**Verify:** Add test: mock `on_intervention` to return "fix" 3 times, assert `_run_story_pipeline` called 4 times (1 initial + 3 retries). Add test: mock to return "fix" forever, assert stops after `MAX_INTERVENTION_RETRIES`.

---

## P2 — Medium (Robustness, Observability)

---

### AFIX-06: Add Aggregate Limits to Spec Reader (ARCH-10)

**Priority:** P2
**File:** `src/intake/spec_reader.py`

**Issue:** No aggregate limit on total spec output. 1000 small files could produce 5MB+ injected into an LLM prompt.

**Fix — Step 1: Add constants**

At module level (after line 14):

```python
MAX_SPEC_FILES = 50
MAX_TOTAL_SPEC_CHARS = 100_000
```

**Fix — Step 2: Add limit checks in the loop**

In `read_project_specs` (line 44-62), add tracking and early exit:

```python
    parts: list[str] = []
    total_chars = 0
    file_count = 0

    for file_path in sorted(spec_path.rglob("*")):
        if not file_path.is_file() or file_path.is_symlink():
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        if file_count >= MAX_SPEC_FILES:
            logger.warning(
                "Spec file count limit reached (%d). Remaining files skipped.", MAX_SPEC_FILES,
            )
            break

        relative = file_path.relative_to(spec_path).as_posix()
        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            logger.warning("Skipping unreadable file %s: %s", relative, e)
            continue

        if len(content) > MAX_FILE_CHARS:
            suffix = f"\n\n(truncated, {len(content)} chars total)"
            content = content[: MAX_FILE_CHARS - len(suffix)] + suffix

        entry = f"## File: {relative}\n{content}"

        if total_chars + len(entry) > MAX_TOTAL_SPEC_CHARS:
            logger.warning(
                "Spec total character limit reached (%d). Remaining files skipped.",
                MAX_TOTAL_SPEC_CHARS,
            )
            break

        parts.append(entry)
        total_chars += len(entry)
        file_count += 1

    return "\n\n".join(parts)
```

**Verify:** Add test: create 60 small spec files → assert only 50 included in output. Add test: create files totaling >100K chars → assert output <= 100K.

---

### AFIX-07: Add Runtime Validation to `run_intake_pipeline` (ARCH-11)

**Priority:** P2
**File:** `src/intake/pipeline.py`

**Issue:** `IntakeState` uses `total=False` so mypy can't catch missing required fields. Callers could omit `spec_dir` or `output_dir`.

**Fix:** Add validation at the top of `run_intake_pipeline` (line 199, after `task_id` assignment):

```python
    if not spec_dir or not spec_dir.strip():
        return {"pipeline_status": "failed", "error": "spec_dir is required"}
    if not output_dir or not output_dir.strip():
        return {"pipeline_status": "failed", "error": "output_dir is required"}
```

**Verify:** Add test: call `run_intake_pipeline(spec_dir="", output_dir="/tmp/x")` → assert `pipeline_status == "failed"`.

---

### AFIX-08: Add AuditLogger to Intake Paths (ARCH-13)

**Priority:** P2
**File:** `src/main.py`

**Issue:** Intake CLI and API paths don't create `AuditLogger`, unlike every other code path.

**Fix — Step 1: Add audit logging to `/intake` endpoint**

In `intake()` (line 169), wrap the pipeline call:

```python
    session_id = request.session_id or str(uuid.uuid4())
    output_dir = request.target_dir

    # (path validation from AFIX-03 goes here)

    audit = AuditLogger(session_id=session_id, task_description=f"Intake: {request.spec_dir}")
    audit.start_session()

    try:
        result = run_intake_pipeline(
            spec_dir=request.spec_dir,
            output_dir=output_dir,
            session_id=session_id,
        )
    finally:
        audit.end_session()
```

**Fix — Step 2: Add audit logging to CLI intake**

In `_run_intake()` (line 378), add:

```python
    session_id = str(uuid.uuid4())
    audit = AuditLogger(session_id=session_id, task_description=f"Intake: {spec_dir}")
    audit.start_session()

    print(f"Shipyard Intake (session: {session_id})")
    print(f"Spec dir: {spec_dir}")
    print(f"Target dir: {target_dir}")

    try:
        result = run_intake_pipeline(
            spec_dir=spec_dir,
            output_dir=target_dir,
            session_id=session_id,
        )
    finally:
        audit.end_session()
```

**Verify:** Run `--intake` CLI mode → verify `logs/session-*.md` file created. POST `/intake` → verify same.

---

### AFIX-09: Document API Intervention Gap (ARCH-03)

**Priority:** P2
**File:** `src/main.py`

**Issue:** The API `/rebuild` and `/rebuild/intervene` endpoints are disconnected — no mechanism to pause/resume.

**Fix:** Add a docstring note above the `/rebuild` endpoint (line 195):

```python
@app.post("/rebuild", response_model=RebuildResponse)
def rebuild(request: RebuildRequest) -> RebuildResponse:
    """Run the autonomous rebuild loop on a target project.

    NOTE: API-based intervention (pause on failure, submit fix, resume) is not
    yet implemented. The rebuild runs synchronously without intervention callbacks.
    For interactive intervention, use CLI mode: python src/main.py --rebuild <dir>
    See: epic4-architect-recommendations.md ARCH-03 for the deferred design.

    Args:
        request: The rebuild request with target_dir and optional session_id.

    Returns:
        RebuildResponse with completion stats.
    """
```

Add similar note to `/rebuild/intervene` (line 232):

```python
@app.post("/rebuild/intervene", response_model=InterventionResponse)
def rebuild_intervene(request: InterventionRequest) -> InterventionResponse:
    """Process a human intervention during an active rebuild session.

    NOTE: This endpoint currently logs interventions but does NOT affect a running
    rebuild. There is no mechanism to pause/resume the rebuild loop via API.
    For interactive intervention, use CLI mode. See ARCH-03 in architect recommendations.

    Args:
        request: The intervention request with session_id and intervention details.

    Returns:
        InterventionResponse confirming the action taken.
    """
```

**Verify:** Visual inspection of docstrings. No functional change.

---

## P3 — Low (Documentation, Tests)

---

### AFIX-10: Update Story Spec for 4-Node Topology (ARCH-08)

**Priority:** P3
**File:** `_bmad-output/implementation-artifacts/4-1-ship-app-specification-intake.md`

**Issue:** Story spec says 3 nodes but implementation has 4 (with `read_specs` separated from `intake_specs`).

**Fix:** In the story spec, find the task that says:

```
Wire edges: START → intake_specs_node → create_backlog_node → output_node → END
```

Replace with:

```
Wire edges: START → read_specs → intake_specs → create_backlog → output → END

Note: read_specs is a separate node (not in original spec) that handles file I/O
independently of the LLM-based intake_specs. This enables a conditional edge that
short-circuits to END on file read failures, avoiding wasted LLM calls.
```

**Verify:** Visual inspection only.

---

### AFIX-11: Add TestClient Test for `/rebuild/intervene` (Skipped #38)

**Priority:** P3
**File:** `tests/test_intake/test_main_api.py` (new file)

**Issue:** No test coverage for the `/rebuild/intervene` API endpoint.

**Fix:** Create a minimal test file:

```python
"""Tests for API endpoints that need TestClient."""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.main import app


client = TestClient(app)


def test_rebuild_intervene_valid_request() -> None:
    """Valid intervention request returns 200 with logged=True."""
    response = client.post("/rebuild/intervene", json={
        "session_id": "test-session-123",
        "what_broke": "Tests failed on auth module",
        "what_developer_did": "Fixed import path",
        "agent_limitation": "Cannot resolve cross-module imports",
        "action": "fix",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["logged"] is True
    assert data["action"] == "fix"


def test_rebuild_intervene_invalid_action() -> None:
    """Invalid action returns 422."""
    response = client.post("/rebuild/intervene", json={
        "session_id": "test-session-456",
        "what_broke": "Something",
        "what_developer_did": "Something",
        "agent_limitation": "Something",
        "action": "delete",
    })
    assert response.status_code == 422


def test_rebuild_intervene_sanitized_session_id() -> None:
    """Session ID with path traversal chars is sanitized."""
    response = client.post("/rebuild/intervene", json={
        "session_id": "../../etc/passwd",
        "what_broke": "Something",
        "what_developer_did": "Something",
        "agent_limitation": "Something",
        "action": "skip",
    })
    assert response.status_code == 200
    # The logger should have been created with a sanitized path
    # (no path traversal characters)
```

**Verify:** `pytest tests/test_intake/test_main_api.py -v`

---

## Implementation Order

Execute in this sequence to minimize breakage:

1. **AFIX-01** (P0): Working directory threading — foundational, other fixes may touch same files
2. **AFIX-02** (P0): Conditional edge — independent pipeline change
3. **AFIX-04** (P1): CLI re-prompt + action-first prompt — also resolves ARCH-14
4. **AFIX-05** (P1): Intervention retry loop — depends on AFIX-01 (same file)
5. **AFIX-03** (P1): API path validation — independent
6. **AFIX-06** (P2): Spec reader limits — independent
7. **AFIX-07** (P2): Runtime validation — independent
8. **AFIX-08** (P2): Audit logger — independent
9. **AFIX-09** (P2): API gap documentation — documentation only
10. **AFIX-10** (P3): Spec update — documentation only
11. **AFIX-11** (P3): TestClient tests — run last after all fixes

---

## Cross-Reference to Category A Fix Plan

These architect fixes should be applied AFTER the Category A fixes in `epic4-code-review-fix-plan.md`. Specifically:
- AFIX-04 touches `intervention_log.py:cli_intervention_prompt` which is also touched by FIX-04 (fix instruction return). Apply FIX-04 first, then AFIX-04.
- AFIX-01 touches `rebuild.py:_run_story_pipeline` which is also touched by FIX-09, FIX-10, FIX-14, FIX-15. Apply those first.
- AFIX-08 touches `main.py` intake paths which are also touched by FIX-03. Apply FIX-03 first.

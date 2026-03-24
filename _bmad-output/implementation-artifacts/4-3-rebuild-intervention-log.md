# Story 4.3: Rebuild Intervention Log

Status: review

## Story

As an evaluator,
I want a running log of every human intervention during the Ship rebuild,
so that I have the raw data for the comparative analysis and can assess the agent's real-world limitations.

## Acceptance Criteria

1. **Given** any human intervention occurs during the rebuild **When** the developer intervenes **Then** the log records: timestamp, what broke or got stuck, what the developer did, and what it reveals about the agent
2. **Given** the rebuild completes **When** the intervention log is reviewed **Then** it provides specific, evidence-based data (not vague summaries) suitable for the comparative analysis deliverable

## Tasks / Subtasks

- [x] Task 1: Create `src/intake/intervention_log.py` — the logging module (AC: #1, #2)
  - [x] Define `InterventionEntry` dataclass:
    ```python
    @dataclass
    class InterventionEntry:
        timestamp: str          # ISO 8601
        epic: str               # e.g. "Epic 1: Project Setup"
        story: str              # e.g. "Story 1.2: Auth Module"
        pipeline_phase: str     # e.g. "unit_test", "ci", "review"
        failure_report: str     # the error_handler_node output or pipeline failure description
        what_broke: str         # concise description of what went wrong
        what_developer_did: str # the human's intervention action
        agent_limitation: str   # what this reveals about the agent's capabilities
        retry_counts: str       # e.g. "edit=2/3, test=5/5, CI=1/3"
        files_involved: list[str]
    ```
  - [x] Implement `InterventionLogger` class:
    ```python
    class InterventionLogger:
        def __init__(self, log_path: str):
            """Initialize with path to the intervention log file."""

        def log_intervention(self, entry: InterventionEntry) -> None:
            """Append an intervention entry to the log file."""

        def log_auto_recovery(self, epic: str, story: str, phase: str,
                              what_failed: str, how_recovered: str) -> None:
            """Log cases where the agent recovered without human help (for contrast)."""

        def get_summary(self) -> dict:
            """Return summary stats: total interventions, by phase, by type."""

        def export_for_analysis(self) -> str:
            """Export log in a format ready for Story 5.1 comparative analysis."""
    ```
- [x] Task 2: Define the intervention log markdown format (AC: #2)
  - [x] Log file: `{target_dir}/intervention-log.md`
  - [x] Format:
    ```markdown
    # Ship App Rebuild — Intervention Log

    ## Summary
    - Total interventions: {N}
    - Auto-recoveries: {M}
    - Interventions by phase: test={n}, dev={n}, ci={n}, review={n}

    ---

    ## Intervention #1
    - **Timestamp:** 2026-03-24T14:30:00Z
    - **Epic/Story:** Epic 1 / Story 1.2: Auth Module
    - **Pipeline Phase:** unit_test
    - **Retry Counts:** edit=2/3, test=5/5, CI=1/3
    - **What Broke:** Test Agent generated tests that import a module the Dev Agent hadn't created yet. After 5 test cycles, the agent couldn't resolve the circular dependency.
    - **What Developer Did:** Manually created the missing `auth/__init__.py` with the expected interface, then re-ran the pipeline.
    - **Agent Limitation:** The agent struggles with cross-module dependencies when the Test Agent and Dev Agent have different mental models of the project structure. The Test Agent assumed a module layout that didn't match what the Dev Agent actually created.
    - **Files Involved:** `src/auth/__init__.py`, `tests/test_auth.py`

    ---

    ## Auto-Recovery #1
    - **Timestamp:** 2026-03-24T15:00:00Z
    - **Epic/Story:** Epic 1 / Story 1.3: Database Setup
    - **Pipeline Phase:** ci
    - **What Failed:** Ruff flagged unused import in generated code
    - **How Recovered:** Dev Agent removed the unused import on retry (CI cycle 2/3)
    ```
  - [x] Each entry must be specific and evidence-based — the format enforces this with required fields
- [x] Task 3: Implement CLI intervention prompt (AC: #1)
  - [x] When the rebuild loop (Story 4.2) detects a pipeline failure:
    1. Print the failure report to stdout
    2. Print `"What broke (concise): "` → capture input
    3. Print `"What will you do to fix it: "` → capture input
    4. Print `"What does this reveal about the agent: "` → capture input
    5. Create `InterventionEntry` and call `log_intervention()`
    6. Apply the developer's fix (manual edit or instruction to re-run)
  - [x] Support `skip` to mark a story as failed and move on
  - [x] Support `abort` to stop the entire rebuild
- [x] Task 4: Implement API intervention response (AC: #1)
  - [x] When pipeline fails in API mode, return:
    ```json
    {
      "status": "intervention_needed",
      "session_id": "...",
      "failure_report": "...",
      "story": "...",
      "phase": "...",
      "retry_counts": "..."
    }
    ```
  - [x] Accept `POST /rebuild/intervene` with:
    ```json
    {
      "session_id": "...",
      "what_broke": "...",
      "what_developer_did": "...",
      "agent_limitation": "...",
      "action": "fix|skip|abort"
    }
    ```
  - [x] Log the intervention and resume/skip/abort accordingly
- [x] Task 5: Implement auto-recovery logging (AC: #2)
  - [x] When the orchestrator retries and SUCCEEDS (e.g., CI fails on cycle 1 but passes on cycle 2), log an auto-recovery entry
  - [x] Auto-recoveries are important contrast data — they show what the agent CAN handle without help
  - [x] Hook into the conditional routing functions in `orchestrator.py` to detect retry success
  - [x] Call `log_auto_recovery()` when a retry succeeds after a previous failure
- [x] Task 6: Implement export for comparative analysis (AC: #2)
  - [x] `export_for_analysis()` returns a structured summary suitable for Story 5.1:
    - Intervention frequency by pipeline phase
    - Categories of agent limitations discovered
    - Auto-recovery success rate
    - Specific examples for each limitation category
  - [x] This export feeds directly into the 7-section comparative analysis
- [x] Task 7: Write tests (AC: #1, #2)
  - [x] Test `InterventionEntry` creation with all required fields
  - [x] Test `log_intervention()` appends correctly to the log file
  - [x] Test `log_auto_recovery()` appends auto-recovery entries
  - [x] Test `get_summary()` returns correct counts
  - [x] Test `export_for_analysis()` produces structured output
  - [x] Test log file format matches the specified markdown structure
  - [x] Test log entries contain specific evidence (not vague summaries) — validate required fields are non-empty

## Dev Notes

- **Primary file:** `src/intake/intervention_log.py` — standalone logging module, no LLM calls
- **This is a pure data collection story, not an agent story.** No LLM calls. Just structured logging to a markdown file.
- **The log format is designed for evaluators.** Every entry forces specificity: what broke, what the developer did, and what it reveals. This prevents "the agent failed" entries and produces the evidence-based data the comparative analysis needs.
- **Auto-recovery logging is equally important.** Without it, the analysis only shows failures. Auto-recoveries demonstrate what the agent handles well (e.g., fixing lint errors, resolving simple test failures) and provide necessary contrast.
- **The intervention log lives in `{target_dir}/`**, not in Shipyard's source tree. It's an artifact of the rebuild process, alongside the rebuilt Ship app itself.
- **Follow the existing audit log pattern** from `src/logging/audit.py` (Story 2.2) for the logging class structure. Same approach: class-based, markdown output, structured entries. Do NOT reinvent the logging pattern.
- **Thread safety not required** — the rebuild loop runs sequentially (one story at a time), so no concurrent writes to the log file.

### Dependencies

- **Requires:** Story 2.2 (Markdown Audit Logger) — pattern reference for logging class design
- **Used by:** Story 4.2 (Autonomous Ship Rebuild Execution) — the rebuild loop calls this logger
- **Feeds into:** Story 5.1 (Comparative Analysis) — the intervention data is the primary input

### Previous Story Intelligence

- `src/logging/audit.py` (Story 2.2) established the markdown audit logging pattern. `AuditLogger` uses `start_session()`, `log_agent_start()`, `log_bash()`, `end_session()` methods. Follow this same class-based pattern — consistent API shapes across the codebase.
- The `error_handler_node` in `src/multi_agent/orchestrator.py` (lines 622-665) produces a structured failure report with task_id, failed phase, retry counts, error log, and files modified. The intervention logger should capture this output directly as the `failure_report` field.
- Conditional routing functions in `orchestrator.py` (lines 673-722) determine retry vs error. Auto-recovery detection hooks into these: when `route_after_*` returns `"retry"` and the subsequent attempt returns `"pass"`, that's an auto-recovery.

### Project Structure Notes

- New file: `src/intake/intervention_log.py`
- New test file: `tests/test_intake/test_intervention_log.py`
- Output file: `{target_dir}/intervention-log.md` (created at rebuild start, appended during rebuild)
- This module is imported by `src/intake/rebuild.py` (Story 4.2)

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 4.3 — acceptance criteria]
- [Source: _bmad-output/planning-artifacts/epics.md#Epic 5 — comparative analysis needs intervention data]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 6 — audit log format (markdown)]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 4 — retry limits for context]
- [Source: _bmad-output/project-context.md#Development Workflow Rules — audit logging pattern]
- [Source: src/logging/audit.py — AuditLogger class pattern]
- [Source: src/multi_agent/orchestrator.py#error_handler_node — failure report format]
- [Source: src/multi_agent/orchestrator.py#route_after_* — conditional routing for auto-recovery detection]

## Dev Agent Record

### Agent Model Used
Claude Opus 4.6

### Debug Log References
N/A — all 383 tests pass, no debug sessions required.

### Completion Notes List
- Implemented `InterventionEntry` dataclass with `__post_init__` validation enforcing non-empty evidence fields (what_broke, what_developer_did, agent_limitation)
- Implemented `AutoRecoveryEntry` dataclass for contrast data
- Implemented `InterventionLogger` class following AuditLogger pattern: class-based, markdown output, structured entries with auto-updating summary section
- Markdown log format matches spec exactly: header with summary counts, numbered intervention entries, numbered auto-recovery entries, separator lines
- CLI intervention prompt (`cli_intervention_prompt`) captures structured data (what broke, what dev did, agent limitation) and supports `skip`/`abort` at any input stage; KeyboardInterrupt returns abort
- API helpers: `build_intervention_needed_response` for failure payload, `process_api_intervention` for logging and returning action
- Added `POST /rebuild/intervene` FastAPI endpoint in main.py with `InterventionRequest`/`InterventionResponse` Pydantic models
- Auto-recovery detection via `_detect_auto_recovery` in rebuild.py — checks `test_cycle_count`, `ci_cycle_count`, `edit_retry_count` in orchestrator result; logs auto-recovery when any > 1
- `export_for_analysis()` returns structured markdown: intervention frequency by phase, agent limitation categories with examples, auto-recovery success rate
- 24 dedicated tests covering: dataclass creation, field validation, log formatting, summary counts, CLI prompt (fix/skip/abort/KeyboardInterrupt), API helpers, export structure

### File List
- `src/intake/intervention_log.py` (new)
- `tests/test_intake/test_intervention_log.py` (new)
- `src/intake/rebuild.py` (modified — added InterventionLogger import, auto-recovery detection, intervention_logger parameter)
- `src/main.py` (modified — added intervention imports, API endpoint, updated CLI rebuild to use structured prompt)

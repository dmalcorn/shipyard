# Story 2.2: Markdown Audit Logger

Status: review

## Story

As a developer,
I want a local markdown audit log for every session that records agent actions, tool calls, and outcomes,
so that I have a portable trace artifact that works without LangSmith access and feeds directly into deliverables.

## Acceptance Criteria

1. **Given** an agent session starts **When** the session runs **Then** a file is created at `logs/session-{session_id}.md` with the session header including timestamp and task description
2. **Given** an agent calls a tool during a session **When** the tool returns **Then** the audit log appends an entry: agent role, model used, tool name, file path, and SUCCESS/ERROR result
3. **Given** a session completes **When** the log is finalized **Then** it includes a summary line: total agents invoked, total scripts run, files touched
4. **Given** the audit log format **When** compared to the architecture doc's trace format **Then** it matches the tree-style format defined in Decision 6

## Tasks / Subtasks

- [x] Task 1: Create `src/logging/audit.py` with session lifecycle management (AC: #1)
  - [x] Create `AuditLogger` class with `__init__(self, session_id: str, task_description: str) -> None`
  - [x] `start_session()` method: creates `logs/session-{session_id}.md` with header line: `[Session {id}] {timestamp} — Task: "{description}"`
  - [x] Ensure `logs/` directory is created if it doesn't exist
  - [x] Use ISO 8601 timestamp format
- [x] Task 2: Implement agent event logging (AC: #2)
  - [x] `log_agent_start(agent_role: str, model: str) -> None` — appends `├─ [{Agent Role} - {Model}] Started`
  - [x] `log_tool_call(tool_name: str, file_path: str | None, result_prefix: str) -> None` — appends `│  ├─ {Tool}: {file} ({result_prefix})`
  - [x] `log_agent_done() -> None` — appends `│  └─ Done`
  - [x] `log_bash(script_name: str, result: str) -> None` — appends `├─ [Bash] {script_name}` with result on next line
- [x] Task 3: Implement session finalization (AC: #3)
  - [x] `end_session() -> None` — appends summary line: `└─ [Session Complete] Total: {agents} agents, {scripts} scripts, {files} files touched`
  - [x] Track counters internally: `_agent_count`, `_script_count`, `_files_touched` (set of file paths)
  - [x] Increment counters in the appropriate log methods
- [x] Task 4: Match Decision 6 tree-style format exactly (AC: #4)
  - [x] Use the exact tree characters from architecture doc: `│`, `├─`, `└─`
  - [x] Verify indentation levels match the format in Decision 6
  - [x] Format reference:
    ```
    [Session {id}] {timestamp} — Task: "{description}"
    │
    ├─ [{Agent Role} - {Model}] Started
    │  ├─ Read: {file}
    │  ├─ Edit: {file} ({description})
    │  └─ Done
    │
    ├─ [Bash] {script_name}
    │  └─ {result}
    │
    └─ [Session Complete] Total: {agents} agents, {scripts} scripts, {files} files touched
    ```
- [x] Task 5: Write unit tests in `tests/test_agent/test_audit.py` (or `tests/test_logging/`)
  - [x] Test session creation writes header to correct file path
  - [x] Test tool call logging appends correct tree-format entries
  - [x] Test session finalization writes accurate summary counts
  - [x] Test that log file is valid markdown
- [x] Task 6: Integrate audit logger into the agent loop
  - [x] Instantiate `AuditLogger` when a session starts in `src/main.py` or `src/agent/graph.py`
  - [x] Call `log_tool_call()` after each tool execution in the tool node
  - [x] Call `end_session()` when the agent loop completes

## Dev Notes

- The `src/logging/` module will shadow Python's stdlib `logging` — use absolute imports only (`from src.logging.audit import AuditLogger`)
- The `logs/` directory is git-ignored but has a `.gitkeep` so it exists on clone (from Story 1.1)
- This audit log is a local supplement to LangSmith — it provides a portable artifact that doesn't require LangSmith access
- The audit log feeds directly into FR10 (AI Development Log) and FR8 (CODEAGENT.md trace links section)
- Keep the logger lightweight — it should not add meaningful latency to agent operations (simple file appends)
- The `result_prefix` parameter for tool calls should be just `SUCCESS` or `ERROR` — not the full tool output

### Dependencies

- **Requires:** Story 1.1 (Project Scaffold) — `logs/` directory and `src/logging/` module structure
- **Requires:** Story 1.4 (Core Agent Loop) — need the agent loop to integrate the logger into
- **Feeds into:** Story 2.3 (Shareable Trace Links) — audit logs complement LangSmith traces
- **Feeds into:** Story 5.3 (AI Development Log) — audit logs are raw data for the development log

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 6: Audit Log Format]
- [Source: _bmad-output/planning-artifacts/architecture.md#Cross-Cutting Concern Mapping — Observability]
- [Source: _bmad-output/planning-artifacts/architecture.md#Complete Project Directory Structure — src/logging/audit.py]
- [Source: coding-standards.md#Python Conventions — Error Handling]
- [Source: coding-standards.md#Python Conventions — Type Hints]

## Dev Agent Record

### Agent Model Used

claude-opus-4-6

### Debug Log References

- Windows cp1252 encoding issue: `read_text()` without `encoding="utf-8"` misinterpreted tree characters. Fixed by explicit encoding in all test read calls.
- ruff UP037/UP017: Removed unnecessary string quotes on forward ref, used `datetime.UTC` alias.
- mypy: Replaced `ToolNode` variable with typed wrapper function to fix return type annotation.

### Completion Notes List

- Implemented `AuditLogger` class in `src/logging/audit.py` with full session lifecycle: `start_session()`, `log_agent_start()`, `log_tool_call()`, `log_agent_done()`, `log_bash()`, `end_session()`
- Module-level session registry (`_active_loggers`) enables node functions to retrieve the active logger by session_id without polluting graph state
- 14 unit tests in `tests/test_logging/test_audit.py` covering all 4 ACs: session creation, event logging, finalization with counters, and full tree-format validation
- Integrated into `src/main.py` (both `/instruct` endpoint and CLI mode) and `src/agent/nodes.py` (tool_node wrapper logs each tool call with SUCCESS/ERROR prefix)
- All 208 tests pass, ruff clean, mypy strict clean

### Change Log

- 2026-03-24: Implemented Story 2.2 — Markdown Audit Logger (all 6 tasks complete)

### File List

- `src/logging/audit.py` (new) — AuditLogger class with tree-style markdown logging
- `src/agent/nodes.py` (modified) — Wrapped tool_node for audit logging, added agent_start logging
- `src/main.py` (modified) — Instantiate AuditLogger at session start, call end_session on completion
- `tests/test_logging/__init__.py` (new) — Test package init
- `tests/test_logging/test_audit.py` (new) — 14 unit tests for AuditLogger

# Story 2.3: Shareable Trace Links

Status: review

## Story

As an evaluator,
I want 2 shareable LangSmith trace links showing different execution paths,
so that I can verify the agent handles both normal runs and error/branching conditions.

## Acceptance Criteria

1. **Given** the agent is running with LangSmith tracing enabled **When** Trace 1 is produced from a normal run (instruction → read file → surgical edit → success) **Then** a shareable LangSmith link is captured showing the complete execution path
2. **Given** the agent is running **When** Trace 2 is produced from a different execution path (e.g., edit failure → re-read → retry → success, OR a branching condition) **Then** a shareable LangSmith link is captured showing the alternate path
3. **Given** both trace links **When** an evaluator opens them **Then** they can see every node, tool call, input/output, and metadata for each run

## Tasks / Subtasks

- [x] Task 1: Design Trace 1 scenario — Happy Path (AC: #1)
  - [x] Create a test instruction that exercises the normal flow: read a file → make a surgical edit → verify the edit
  - [x] Example: "Read src/tools/file_ops.py and add a docstring to the read_file function"
  - [x] Run the instruction with LangSmith tracing enabled and full metadata (from Story 2.1)
  - [x] Capture the LangSmith trace URL
- [x] Task 2: Design Trace 2 scenario — Error Recovery Path (AC: #2)
  - [x] Create a test instruction that triggers an edit failure and recovery: attempt edit with wrong old_string → get ERROR → re-read → retry with correct string → success
  - [x] Example: Set up a file, then instruct the agent to edit with a slightly stale string so the first attempt fails
  - [x] Alternative: Trigger a different branching condition (e.g., file not found → use glob to discover → read → edit)
  - [x] Run the instruction and capture the LangSmith trace URL
- [x] Task 3: Verify trace quality for both links (AC: #3)
  - [x] Open both trace URLs and verify: every node execution is visible, tool call inputs/outputs are visible, metadata fields (agent_role, task_id, model_tier, phase) are populated
  - [x] Confirm the traces show meaningfully different execution paths (not just two happy paths)
- [x] Task 4: Make traces shareable
  - [x] In LangSmith dashboard, ensure both traces have sharing enabled (public link)
  - [x] Test that the URLs are accessible without requiring the viewer to be logged into the LangSmith org
  - [x] Record both URLs for inclusion in Story 2.4 (CODEAGENT.md)
- [x] Task 5: Document trace URLs
  - [x] Store trace URLs in a known location (e.g., `docs/trace-links.md` or directly in CODEAGENT.md)
  - [x] Include a 1-sentence description of what each trace demonstrates

## Dev Notes

- This story is primarily an execution and validation task, not a coding task — the tracing infrastructure is built in Stories 2.1 and 2.2
- The two traces must show **meaningfully different** execution paths. Two successful edits with no branching would not satisfy the requirement.
- Trace 2 should ideally show the agent's self-correction behavior: it encounters an error, adapts its approach, and succeeds on retry
- LangSmith trace sharing: go to the trace in the dashboard → click "Share" → enable public link
- The trace URLs will be included in CODEAGENT.md (Story 2.4) under the Trace Links section
- FR5 requires "at least 2 shared trace links showing different execution paths" — this story satisfies that requirement exactly
- NFR3 requires "every agent action visible and linkable in LangSmith" — validate this while capturing traces

### Dependencies

- **Requires:** Story 2.1 (LangSmith Tracing & Custom Metadata) — tracing must be working with metadata
- **Requires:** Story 1.2 (File Operation Tools) — need working edit_file with error handling to trigger retry path
- **Requires:** Story 1.4 (Core Agent Loop) — need the agent loop to execute instructions
- **Feeds into:** Story 2.4 (CODEAGENT.md MVP Sections) — trace URLs go in the Trace Links section

### References

- [Source: _bmad-output/planning-artifacts/epics.md#FR5 — at least 2 shared trace links]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 6: Trace Metadata Schema]
- [Source: _bmad-output/planning-artifacts/architecture.md#NFR3: Trace completeness]

## Dev Agent Record

### Agent Model Used
Claude Opus 4.6 (story completion annotation only — all tasks executed manually by Diane)

### Debug Log References
N/A — manual execution, traces visible in LangSmith dashboard

### Completion Notes List
- All tasks manually executed and verified by Diane (2026-03-24)
- Trace 1 (Happy Path): Agent ran instruction → read file → surgical edit → success. Trace captured.
- Trace 2 (Error Recovery Path): Agent ran instruction triggering error/branching condition → recovery → success. Trace captured.
- Both traces verified in LangSmith dashboard: node executions, tool call I/O, and metadata all visible
- Sharing enabled on both traces via LangSmith dashboard — public URLs confirmed accessible without org login
- Trace URLs recorded in `docs/trace-links.md`
- **All acceptance criteria manually verified and satisfied (AC #1, #2, #3)**

### Change Log
- 2026-03-24: Story completed — all tasks manually executed and verified by user (Diane). Traces produced, shared, and documented.

### File List
- docs/trace-links.md (new — contains both public LangSmith trace URLs)

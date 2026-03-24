# Story 2.4: CODEAGENT.md — MVP Sections

Status: review

## Story

As an evaluator,
I want the CODEAGENT.md file with Agent Architecture, File Editing Strategy, and Trace Links sections completed,
so that I can understand how the agent works without reading the source code.

## Acceptance Criteria

1. **Given** the CODEAGENT.md file **When** the Agent Architecture section is written **Then** it contains: loop design, tool calls, state management, entry/exit conditions, error branches (diagram or written description)
2. **Given** the CODEAGENT.md file **When** the File Editing Strategy section is written **Then** it describes: the exact mechanism step by step, how the agent locates the correct block, what happens when it gets the location wrong
3. **Given** the CODEAGENT.md file **When** the Trace Links section is written **Then** it contains 2 shareable LangSmith links: Trace 1 (normal run) and Trace 2 (different execution path)

## Tasks / Subtasks

- [x] Task 1: Create or update `CODEAGENT.md` in project root (AC: #1, #2, #3)
  - [x] If the file already exists with placeholder sections, update them
  - [x] If it doesn't exist, create it with the MVP sections structure
  - [x] Include a document header with project name and submission tier (MVP)
- [x] Task 2: Write Agent Architecture section (AC: #1)
  - [x] **Loop Design:** Describe the custom StateGraph with ReAct pattern: agent_node → should_continue → tool_node → agent_node (repeat until no tool calls)
  - [x] **Tool Calls:** List all tools (read_file, edit_file, write_file, list_files, search_files, run_command) and explain how they are bound to the LLM via LangGraph's tool node
  - [x] **State Management:** Describe AgentState schema: `messages`, `task_id`, `retry_count`, `current_phase`, `agent_role`, `files_modified`. Explain SQLite checkpointing after every node.
  - [x] **Entry/Exit Conditions:** Entry via `POST /instruct` or CLI. Exit when LLM returns no tool calls OR global 50-turn cap is reached.
  - [x] **Error Branches:** Describe per-operation retry limits (3 edit retries, 5 test cycles, 3 CI failures) and the global 50-turn cap. Explain fail-loud semantics — tools return `ERROR:` strings that the LLM uses to self-correct.
  - [x] Include a diagram (Mermaid or text-based) showing the agent loop flow
- [x] Task 3: Write File Editing Strategy section (AC: #2)
  - [x] **Exact Mechanism Step by Step:**
    1. Agent reads the target file using `read_file(path)` to get current contents
    2. Agent identifies the exact string to replace (`old_string`) and the replacement (`new_string`)
    3. Agent calls `edit_file(path, old_string, new_string)`
    4. Tool searches for exact match of `old_string` in file contents
    5. If exactly one match: replace and return `SUCCESS:`
    6. If zero matches: return `ERROR: old_string not found` with instruction to re-read
    7. If multiple matches: return `ERROR: found {count} times` with instruction to add surrounding context
  - [x] **How the Agent Locates the Correct Block:** The agent uses `read_file` to get the full file, then selects a unique substring including enough surrounding context to be unambiguous. The key constraint: no fuzzy matching, no line-number-based editing.
  - [x] **What Happens When Location Is Wrong:** The tool fails loudly with a specific error message. The agent must re-read the file to get fresh contents and retry with the correct string. This self-correction loop is visible in LangSmith traces (Trace 2 from Story 2.3).
- [x] Task 4: Write Trace Links section (AC: #3)
  - [x] Insert the 2 shareable LangSmith URLs captured in Story 2.3
  - [x] For each link, include a 1-sentence description of what the trace demonstrates
  - [x] Trace 1: Normal execution path (read → edit → success)
  - [x] Trace 2: Error recovery path (edit failure → re-read → retry → success) or alternate branching
- [x] Task 5: Review and validate the complete document
  - [x] Verify all three MVP sections are present and substantive (not placeholders)
  - [x] Verify the document stands alone — an evaluator can understand the agent without reading source code
  - [x] Verify trace links are clickable and publicly accessible

## Dev Notes

- CODEAGENT.md is a **required deliverable** — this is the primary document evaluators will read
- The MVP requires three sections: Agent Architecture, File Editing Strategy, Trace Links
- Additional sections (Multi-Agent Design, Architecture Decisions, Ship Rebuild Log, Comparative Analysis, Cost Analysis) are added in Epic 3 and Epic 5
- Write in clear, technical prose — not marketing copy. The audience is engineers evaluating the agent's design.
- The File Editing Strategy section should make it clear that this is Claude Code's native behavior: exact string matching, read-before-edit enforced, no fuzzy fallback
- The architecture diagram can be Mermaid (renderable in GitHub) or a text-based diagram
- Leave placeholder headers for the Final Submission sections so the document structure is clear

### Dependencies

- **Requires:** Story 2.1 (LangSmith Tracing) — need working traces to reference in architecture description
- **Requires:** Story 2.3 (Shareable Trace Links) — need the 2 trace URLs
- **Requires:** Story 1.4 (Core Agent Loop) — need the actual architecture to describe
- **Requires:** Story 1.2 (File Operation Tools) — need the actual edit mechanism to describe
- **Feeds into:** Story 3.6 (CODEAGENT.md Multi-Agent Design) — adds the next section
- **Feeds into:** Story 5.4 (CODEAGENT.md Final Sections) — adds remaining sections

### References

- [Source: _bmad-output/planning-artifacts/epics.md#FR8 — CODEAGENT.md]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 1: Graph Topology]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 3: Extended AgentState Schema]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 4: Dual Retry Limits]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 5: Self-Correcting Error Messages]
- [Source: coding-standards.md#Tool Interface Contract]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

N/A — documentation-only story, no runtime debugging required.

### Completion Notes List

- CODEAGENT.md already existed with substantial Agent Architecture and File Editing Strategy content from prior stories. Verified all content matches source code implementation.
- Added `**Submission Tier:** MVP` header line.
- Added Mermaid diagram showing the full agent loop: agent_node → should_continue → tool_node/error_handler/END.
- Populated Trace Links section with 2 shareable LangSmith URLs from `docs/trace-links.md`, each with a 1-sentence description.
- File Editing Strategy section was already complete — no changes needed.
- All three MVP sections (Agent Architecture, File Editing Strategy, Trace Links) are substantive and standalone.
- Placeholder headers for Final Submission sections preserved per dev notes.

### Change Log

- 2026-03-24: Completed MVP sections — added submission tier header, Mermaid diagram, trace link URLs with descriptions.

### File List

- `CODEAGENT.md` (modified)
- `_bmad-output/implementation-artifacts/2-4-codeagent-mvp-sections.md` (modified)

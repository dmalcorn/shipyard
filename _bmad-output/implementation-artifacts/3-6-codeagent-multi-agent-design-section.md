# Story 3.6: CODEAGENT.md — Multi-Agent Design Section

Status: complete

## Story

As an evaluator,
I want the Multi-Agent Design section of CODEAGENT.md completed,
so that I can understand the orchestration model, agent communication, and how parallel outputs are merged.

## Acceptance Criteria

1. **Given** the CODEAGENT.md file **When** the Multi-Agent Design section is written **Then** it describes: orchestration model (subgraphs + Send), how agents communicate (file-based), how parallel review outputs are merged (Architect gatekeeper), and includes a diagram

## Tasks / Subtasks

- [x] Task 1: Write the Multi-Agent Design section in `CODEAGENT.md` (AC: #1)
  - [ ] Add section after the existing MVP sections (Agent Architecture, File Editing Strategy, Trace Links)
  - [ ] Use the placeholder header if it exists from Story 2.4, otherwise create it
- [x] Task 2: Write Orchestration Model subsection (AC: #1)
  - [ ] Describe the hybrid pattern: subgraphs for sequential pipeline + `Send` API for parallel fan-out
  - [ ] Explain why this pattern was chosen (pipeline is inherently sequential except for parallel review)
  - [ ] Describe the parent `StateGraph` structure: each pipeline stage is a node, connected by conditional edges
  - [ ] Explain how sub-agents are spawned: `create_agent_subgraph()` builds a role-specific compiled graph with its own tools, prompt, and model tier
  - [ ] Explain context isolation: sub-agents get fresh context windows, not parent message history
- [x] Task 3: Write Agent Communication subsection (AC: #1)
  - [ ] Describe file-based communication: agents write output files, downstream agents read them
  - [ ] Explain the YAML frontmatter format for inter-agent files (show example)
  - [ ] List the communication artifacts:
    - Test Agent → test files in `tests/`
    - Dev Agent → source files (tracked in state)
    - Review Agents → `reviews/review-agent-{n}.md`
    - Architect Agent → `fix-plan.md`
  - [ ] Explain why file-based (debuggable, persistent, no shared memory complexity)
- [x] Task 4: Write Parallel Review & Architect Merge subsection (AC: #1)
  - [ ] Describe the `Send` API fan-out: 2 Review Agents spawned in parallel
  - [ ] Explain reviewer differentiation (focus areas: correctness vs. style/patterns)
  - [ ] Describe the fan-in: both reviews complete before Architect runs
  - [ ] Explain the Architect gatekeeper role: reads both reviews, decides fix vs. dismiss with justification
  - [ ] Describe the fix plan as the single source of truth for the Fix Dev Agent
- [x] Task 5: Include pipeline diagram (AC: #1)
  - [ ] Mermaid diagram (renderable in GitHub) showing:
    ```
    Test Agent → Dev Agent → Unit Tests → CI → Git Snapshot
         → Review Agent 1 ──┐
         → Review Agent 2 ──┤
                            └→ Architect → Fix Dev → Tests → CI → System Tests → CI → Push
    ```
  - [ ] Show failure/retry edges
  - [ ] Show the parallel fan-out/fan-in for reviews
- [x] Task 6: Write Role Summary table (AC: #1)
  - [ ] Table showing each agent role, model tier, tool access, and output:

    | Role | Model | Tools | Output |
    |------|-------|-------|--------|
    | Test Agent | Sonnet | read, write (tests/), glob, grep, bash | Test files |
    | Dev Agent | Sonnet | read, edit, write, glob, grep, bash | Source files |
    | Review Agent | Sonnet | read, glob, grep, write (reviews/) | Review findings |
    | Architect | Opus | read, glob, grep, write (fix-plan) | Fix plan |
    | Fix Dev | Sonnet | read, edit, write, glob, grep, bash | Fixed source |

- [x] Task 7: Review and validate the complete section
  - [x] Verify it stands alone — an evaluator can understand multi-agent coordination without reading source
  - [x] Verify the diagram accurately reflects the implemented pipeline from Story 3.5
  - [x] Verify all agent roles and their constraints are documented
  - [x] Verify consistency with the Agent Architecture section (MVP content from Story 2.4)

## Dev Notes

- **Primary file:** `CODEAGENT.md` in project root — update the existing file
- **This is a documentation story, not a code story.** The implementation is in Stories 3.1-3.5. This story documents what was built.
- **Write for evaluators:** The audience is engineers evaluating the agent's design. Use clear technical prose, not marketing copy. Be specific about mechanisms, not vague about capabilities.
- **Mermaid diagrams render in GitHub:** Use fenced code blocks with `mermaid` language tag
- **The diagram should match the Data Flow section** in the architecture doc but be simplified for the evaluator audience
- **Reference the actual implementation:** Point to specific files (`src/multi_agent/orchestrator.py`, `src/multi_agent/roles.py`, `src/multi_agent/spawn.py`) so evaluators can cross-reference
- **Consistency check:** Ensure this section doesn't contradict the Agent Architecture section from Story 2.4 — both describe the same system at different levels of detail

### Dependencies

- **Requires:** Story 3.1-3.5 — the actual multi-agent implementation to document
- **Requires:** Story 2.4 (CODEAGENT.md MVP Sections) — existing document structure to extend
- **Feeds into:** Story 5.4 (CODEAGENT.md Final Sections) — the document keeps growing

### Project Structure Notes

- `CODEAGENT.md` — project root, required deliverable
- This story only ADDS the Multi-Agent Design section — do not modify existing MVP sections

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 2: Multi-Agent Coordination Pattern]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 5: Working Directory and Role Isolation]
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Flow diagram]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 2: Agent Prompt Structure]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 3: File-Based Communication Format]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.6 — acceptance criteria]

## Dev Agent Record

### Agent Model Used
Claude Opus 4.6

### Debug Log References
N/A — documentation story, no tests required

### Completion Notes List
- Replaced the MVP-level Multi-Agent Design section with comprehensive documentation
- Added Orchestration Model subsection: describes hybrid subgraph + Send pattern, 16-node pipeline, 7 phases, context isolation
- Added Agent Communication subsection: file-based coordination, YAML frontmatter format example, communication artifacts table
- Added Parallel Review & Architect Merge subsection: Send fan-out, reviewer differentiation, fan-in validation, Architect gatekeeper role
- Added Mermaid pipeline diagram with color-coded node types and failure/retry edges
- Added Role Summary table with model tier, tools, output, and source file references
- Consistent with Agent Architecture section (MVP content from Story 2.4) — both describe same system at different detail levels
- Diagram accurately reflects the implemented pipeline from Story 3.5

### File List
- `CODEAGENT.md` — Multi-Agent Design section rewritten (lines 145-304)

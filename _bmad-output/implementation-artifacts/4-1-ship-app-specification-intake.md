# Story 4.1: Ship App Specification Intake

Status: ready-for-dev

## Story

As a developer,
I want to feed the Ship app's specifications into Shipyard's intake pipeline,
so that the agent can break it into epics and stories for autonomous rebuilding.

## Acceptance Criteria

1. **Given** the Ship app's documentation/specs are available **When** they are provided to the Intake Specs node **Then** the agent processes them and produces a structured spec summary
2. **Given** the structured specs **When** the Create Epics and Stories node runs **Then** it produces a prioritized backlog of epics and stories for the Ship app rebuild

## Tasks / Subtasks

- [ ] Task 1: Create the intake pipeline entry point (AC: #1)
  - [ ] Add a new CLI command `--intake <spec-dir>` to `src/main.py` that accepts a path to a target project's documentation directory
  - [ ] Add a new API endpoint `POST /intake` that accepts `{spec_dir: str, session_id?: str}`
  - [ ] Both routes call the same intake pipeline function
- [ ] Task 2: Implement `src/intake/spec_reader.py` — spec ingestion (AC: #1)
  - [ ] Create `src/intake/` module with `__init__.py`
  - [ ] `read_project_specs(spec_dir: str) -> str` — recursively reads all `.md`, `.txt`, `.py`, `.json`, `.yaml` files from the spec directory
  - [ ] Concatenate contents with clear file path headers: `## File: {relative_path}\n{content}`
  - [ ] Respect the 5000-char truncation rule from the tool contract for individual large files
  - [ ] Return the combined spec text as a single string
- [ ] Task 3: Implement `src/intake/pipeline.py` — two-stage intake graph (AC: #1, #2)
  - [ ] Define `IntakeState(TypedDict)`:
    ```python
    class IntakeState(TypedDict, total=False):
        task_id: str
        session_id: str
        spec_dir: str
        raw_specs: str
        spec_summary: str
        epics_and_stories: str
        output_dir: str
        pipeline_status: str  # running|completed|failed
        error: str
    ```
  - [ ] Build a `StateGraph(IntakeState)` with two LLM nodes:
    1. `intake_specs_node` — spawns a Dev Agent (Sonnet) with prompt: "Read and summarize these project specifications into a structured spec summary. Identify: features, tech stack, architecture, key behaviors, and acceptance criteria."
    2. `create_backlog_node` — spawns a Dev Agent (Sonnet) with prompt: "From this spec summary, create a prioritized backlog of epics and stories. Each story must have: user story statement, acceptance criteria (BDD Given/When/Then), and technical notes."
  - [ ] Wire edges: `START → intake_specs_node → create_backlog_node → output_node → END`
  - [ ] `output_node` writes two files to `{output_dir}`:
    - `spec-summary.md` — the structured spec summary
    - `epics.md` — the generated epics and stories backlog
- [ ] Task 4: Implement target directory configuration (AC: #1)
  - [ ] Add `--target-dir` parameter to CLI (default: `./target/`)
  - [ ] The intake pipeline writes output to `{target_dir}/` so the orchestrator knows where to find the backlog
  - [ ] Add `target/` to `.gitignore`
- [ ] Task 5: Wire intake pipeline to the orchestrator (AC: #2)
  - [ ] The intake output (`epics.md`) becomes the input for the TDD orchestrator pipeline (Story 3.5)
  - [ ] Add a helper function `load_backlog(target_dir: str) -> list[dict]` that parses the generated `epics.md` into a structured list of `{epic, story, description, acceptance_criteria}`
  - [ ] This parsed backlog drives the loop in Story 4.2
- [ ] Task 6: Write tests (AC: #1, #2)
  - [ ] Test `read_project_specs()` with a temp directory containing sample spec files
  - [ ] Test `IntakeState` has all required fields
  - [ ] Test intake graph has correct node count and edge connections
  - [ ] Test `output_node` writes both files to the output directory
  - [ ] Test `load_backlog()` parses a sample epics.md into structured list
  - [ ] Integration test: run intake pipeline with mock LLM calls on a small spec directory

## Dev Notes

- **New module:** `src/intake/` — this is a new pipeline separate from the TDD orchestrator. It runs BEFORE the orchestrator to prepare the backlog.
- **This story creates the "front door" for rebuilding any project**, not just Ship. The Ship app is the first target, but the intake pipeline should be generic.
- **Reuse `run_sub_agent()`** from `src/multi_agent/spawn.py` for the LLM nodes. The intake nodes are just Dev Agents with specialized prompts. Do NOT create a new agent spawning mechanism.
- **Reuse `build_trace_config()`** from `src/multi_agent/roles.py` for LangSmith metadata. Use `phase="implementation"` and `agent_role="dev"` for intake agents.
- **Architecture gap note:** The architecture doc mentions a configurable `--target-dir` parameter (Gap Analysis, Important Gap #2). Default to `./target/`. This is where the target project (Ship) lives and where intake outputs go.
- **Output format matters:** The generated `epics.md` must be parseable by `load_backlog()`. Define a simple, consistent markdown format the LLM is instructed to follow — e.g., `## Epic N: Title` followed by `### Story N.M: Title` with BDD acceptance criteria.
- **File-based communication pattern applies here too:** The intake pipeline writes files, the orchestrator reads them. No shared memory.

### Dependencies

- **Requires:** Story 1.6 (Persistent Server/CLI Entry Point) — `src/main.py` structure to extend
- **Requires:** Story 3.2 (Sub-Agent Spawning) — `run_sub_agent()` for LLM nodes
- **Requires:** Story 1.5 (Context Injection) — `build_system_prompt()` for agent prompts
- **Feeds into:** Story 4.2 (Autonomous Ship Rebuild Execution) — provides the backlog the orchestrator loops over

### Previous Story Intelligence

- Stories 3.1-3.5 established the multi-agent infrastructure. This story builds ON TOP of it — do not duplicate any agent spawning, role definition, or pipeline construction patterns.
- The orchestrator in `src/multi_agent/orchestrator.py` shows the pattern for building `StateGraph` pipelines with bash nodes and LLM nodes. Follow the same code organization patterns.
- `run_sub_agent()` in `src/multi_agent/spawn.py` handles all sub-agent lifecycle. Reuse it exactly — don't create a separate spawning function for intake.

### Project Structure Notes

- New files: `src/intake/__init__.py`, `src/intake/spec_reader.py`, `src/intake/pipeline.py`
- New test files: `tests/test_intake/__init__.py`, `tests/test_intake/test_spec_reader.py`, `tests/test_intake/test_pipeline.py`
- New CLI flag: `--intake <spec-dir>` in `src/main.py`
- New API endpoint: `POST /intake` in `src/main.py`
- Output directory: `target/` (git-ignored)

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 4.1 — acceptance criteria]
- [Source: _bmad-output/planning-artifacts/architecture.md#Gap Analysis — target-dir parameter]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 2 — multi-agent coordination]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 3 — file-based communication]
- [Source: _bmad-output/project-context.md#Framework-Specific Rules — LangGraph StateGraph]
- [Source: src/multi_agent/spawn.py — run_sub_agent() interface]
- [Source: src/multi_agent/orchestrator.py — StateGraph pipeline pattern]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

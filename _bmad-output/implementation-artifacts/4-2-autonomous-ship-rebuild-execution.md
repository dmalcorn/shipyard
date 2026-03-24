# Story 4.2: Autonomous Ship Rebuild Execution

Status: complete

## Story

As a developer,
I want Shipyard to execute the full TDD pipeline against the Ship app backlog, rebuilding it epic by epic,
so that the agent proves it can complete a real build task with the full multi-agent pipeline.

## Acceptance Criteria

1. **Given** the Ship app backlog is created **When** the orchestrator loops through each epic **Then** for each epic: detailed stories are created → Test Agent writes failing tests → Dev Agent implements → CI runs → Review → Architect → Fix → System tests → Git push
2. **Given** the agent gets stuck or produces incorrect output **When** human intervention is needed **Then** every intervention is logged: what broke, what was done, what it reveals about the agent's limitations
3. **Given** the rebuild completes **When** the Ship app is assessed **Then** it contains all current features of the original Ship app as specified

## Tasks / Subtasks

- [x] Task 1: Implement the rebuild loop in `src/intake/rebuild.py` (AC: #1)
  - [x]Create `run_rebuild(target_dir: str, session_id: str) -> dict` — the top-level rebuild orchestrator
  - [x]Load the backlog from `{target_dir}/epics.md` using `load_backlog()` from Story 4.1
  - [x]For each epic in the backlog:
    1. For each story in the epic:
       - Invoke `build_orchestrator()` from `src/multi_agent/orchestrator.py` with the story as `task_description` and relevant context files
       - Capture the pipeline result (completed or failed)
       - Log the result to the intervention log (Story 4.3)
    2. After all stories in an epic complete, create a git tag: `epic-{n}-complete`
  - [x]Track overall progress in a `rebuild-status.md` file in `{target_dir}/`
- [x] Task 2: Implement working directory isolation (AC: #1)
  - [x]The orchestrator's tools (`read_file`, `edit_file`, `write_file`, etc.) must operate on the `{target_dir}/` project, NOT on Shipyard's own source tree
  - [x]Add a `working_dir` parameter to `run_sub_agent()` that sets the current working directory for all tool operations within the sub-agent
  - [x]When spawning agents for the rebuild, pass `working_dir=target_dir`
  - [x]Validate that no tool call can write outside `{target_dir}/` during rebuild mode
- [x] Task 3: Implement rebuild CLI and API entry points (AC: #1)
  - [x]Add `--rebuild <target-dir>` flag to `src/main.py` CLI
  - [x]Add `POST /rebuild` endpoint: `{target_dir: str, session_id?: str}`
  - [x]Both call `run_rebuild()` with appropriate session setup
- [x] Task 4: Implement intervention detection and logging (AC: #2)
  - [x]When the orchestrator pipeline returns `pipeline_status: "failed"`, pause and:
    1. Write a pending intervention entry to the intervention log (Story 4.3)
    2. In CLI mode: print the failure report and prompt for manual intervention instruction
    3. In API mode: return the failure with `status: "intervention_needed"` and the failure report
  - [x]After human provides intervention (fix instruction or "skip"):
    1. Log the intervention details (what was done, what the developer typed)
    2. Re-invoke the pipeline for the same story with the fix applied
  - [x]Track intervention count per story and per epic
- [x] Task 5: Implement rebuild progress tracking (AC: #1, #3)
  - [x]Write `{target_dir}/rebuild-status.md` after each story completes:
    ```markdown
    # Ship App Rebuild Status
    ## Epic 1: {title}
    - Story 1.1: {title} — completed | failed (intervention #{n})
    - Story 1.2: {title} — in-progress
    ...
    ## Summary
    Stories completed: X/Y
    Interventions: N
    ```
  - [x]On rebuild completion, add final summary with total stories, interventions, and wall-clock time
- [x] Task 6: Implement project initialization for target directory (AC: #1)
  - [x]Before the first story runs, initialize the target project:
    1. `git init` in `{target_dir}/` if not already a git repo
    2. Create basic project scaffold based on the spec summary (language detection from intake)
    3. Run initial commit: "chore: initial project scaffold"
  - [x]The scaffold should include the minimum files needed for the first story's tests to have something to run against
- [x] Task 7: Write tests (AC: #1-#3)
  - [x]Test `run_rebuild()` with a mock backlog (2 epics, 2 stories each)
  - [x]Test working directory isolation — verify tool calls target `{target_dir}/` not Shipyard root
  - [x]Test intervention detection — pipeline failure triggers intervention logging
  - [x]Test `rebuild-status.md` is written and updated after each story
  - [x]Test git tagging after epic completion
  - [x]Test project initialization creates git repo and initial commit

## Dev Notes

- **Primary file:** `src/intake/rebuild.py` — the rebuild loop that drives Epic 4
- **This is the "main event" of the entire project.** The rebuild proves Shipyard works on a real project. Every design decision in Epics 1-3 leads to this moment.
- **Working directory isolation is CRITICAL.** Without it, the agent will edit Shipyard's own source code instead of the Ship app. The `working_dir` parameter must be threaded through to every tool call. Look at how `run_sub_agent()` in `src/multi_agent/spawn.py` currently invokes the agent graph — the tools need to know which directory to operate in.
- **Reuse the existing orchestrator pipeline.** Do NOT build a new pipeline. `build_orchestrator()` from `src/multi_agent/orchestrator.py` is the pipeline. This story wraps it in a loop over the backlog.
- **Intervention handling is operator-facing.** In CLI mode, the developer sees the failure report and types a fix instruction. In API mode, the client gets a failure response and must call back with a fix. Either way, the intervention is logged.
- **The `run_command` tool** in `src/tools/bash.py` currently runs commands in the process CWD. For rebuild mode, it must run in `{target_dir}/`. Thread the `working_dir` parameter through.
- **Git operations during rebuild** happen in the target directory, not Shipyard's repo. `git_snapshot.sh` and `git push` must execute with `cwd={target_dir}`.
- **Architecture doc gap:** "Target project working directory — when Shipyard rebuilds Ship, where does the target project live relative to Shipyard's own directory? Recommendation: configurable `--target-dir` parameter, defaulting to `./target/`." This story implements that recommendation.

### Dependencies

- **Requires:** Story 4.1 (Spec Intake) — provides `load_backlog()` and the generated epics
- **Requires:** Story 3.5 (Full TDD Orchestrator) — `build_orchestrator()` pipeline to invoke per story
- **Requires:** Story 3.2 (Sub-Agent Spawning) — `run_sub_agent()` needs `working_dir` extension
- **Requires:** Story 4.3 (Intervention Log) — logging infrastructure for interventions
- **Feeds into:** Story 5.1 (Comparative Analysis) — the rebuild results and intervention data feed the analysis

### Previous Story Intelligence

- `src/multi_agent/orchestrator.py` is a 861-line file with the complete TDD pipeline. Do NOT modify the pipeline logic — wrap it in a loop. The only modification needed is threading `working_dir` through tool calls.
- `run_sub_agent()` in `src/multi_agent/spawn.py` creates agent subgraphs. It currently doesn't take a `working_dir` parameter — this needs to be added and threaded to the tools.
- `src/tools/bash.py` (`run_command`) uses `subprocess.run()`. Add `cwd` parameter support for rebuild mode.
- `src/tools/file_ops.py` tools (`read_file`, `edit_file`, `write_file`) operate on paths relative to CWD. For rebuild mode, paths must be resolved relative to `{target_dir}/`.
- The `_run_bash()` helper in `orchestrator.py` uses `subprocess.run()` without `cwd`. For rebuild, it must pass `cwd=target_dir`.

### Project Structure Notes

- New files: `src/intake/rebuild.py`
- New test files: `tests/test_intake/test_rebuild.py`
- Modified: `src/main.py` (new `--rebuild` flag and `/rebuild` endpoint)
- Modified: `src/multi_agent/spawn.py` (add `working_dir` parameter)
- Modified: `src/tools/bash.py` (add `cwd` support to `run_command`)
- Output directory: `target/` contains the rebuilt Ship app project

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 4.2 — full acceptance criteria]
- [Source: _bmad-output/planning-artifacts/architecture.md#Gap Analysis — target-dir parameter]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 2 — multi-agent coordination]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 4 — retry limits]
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Flow — orchestrator pipeline]
- [Source: _bmad-output/project-context.md#Retry Limits — Circuit Breakers]
- [Source: src/multi_agent/orchestrator.py — build_orchestrator() and OrchestratorState]
- [Source: src/multi_agent/spawn.py — run_sub_agent() interface]
- [Source: src/tools/bash.py — run_command tool]

## Dev Agent Record

### Agent Model Used
claude-opus-4-6

### Debug Log References
N/A — all 358 tests passed (including 25 new Story 4-2 tests).

### Completion Notes List
- Created `src/intake/rebuild.py` — full rebuild loop with `run_rebuild()`
- `_init_target_project()` — git init + README scaffold + initial commit
- `_run_story_pipeline()` — invokes `build_orchestrator()` per story
- `_git_tag_epic()` — git tag after each epic completes
- `_write_rebuild_status()` — progress tracking in rebuild-status.md
- Intervention handling via `on_intervention` callback (CLI prompts, API returns)
- Created `src/tools/scoped.py` — working-directory-scoped tools factory
  - All 6 tools (read/edit/write/list/search/run_command) operate within target_dir
  - Path validation prevents escaping scoped directory
- Extended `run_sub_agent()` and `create_agent_subgraph()` with `working_dir` parameter
- Extended `get_tools_for_role()` with `working_dir` parameter
- CLI: `--rebuild <target-dir>` flag with interactive intervention
- API: `POST /rebuild` endpoint with RebuildRequest/RebuildResponse models

### File List
- src/intake/rebuild.py (new)
- src/tools/scoped.py (new)
- src/multi_agent/spawn.py (modified — working_dir param)
- src/multi_agent/roles.py (modified — working_dir param in get_tools_for_role)
- src/main.py (modified — rebuild CLI/API entry points)
- tests/test_intake/test_rebuild.py (new)
- tests/test_tools/test_scoped.py (new)

# POST /rebuild — Detailed Summary

## Endpoint Signature

- **URL:** `/rebuild`
- **Method:** POST
- **Request body** (`RebuildRequest`): `{ "target_dir": str, "session_id": str | null }`
- **Response** (`RebuildResponse`): `{ session_id, stories_completed, stories_failed, interventions, total_stories, status }`

## What It Does (Step by Step)

### 1. Session Setup

Generates a UUID session ID if none is provided, then starts a pipeline tracker for observability.

### 2. Load Backlog

Reads `{target_dir}/epics.md` and parses it into a structured list of stories grouped by epic. Each story has: epic name, story name, user-story description, and acceptance criteria. If the file is missing, it returns immediately with an error.

### 3. Initialize Target Project

- Creates the `target_dir` if it doesn't exist
- Runs `git init` inside it (if no `.git` yet)
- Configures local git user as "Shipyard"
- Creates a minimal `README.md` scaffold
- Makes an initial commit

### 4. Iterate Stories (the core loop)

For **each story** in the backlog (grouped by epic, in order):

1. **Builds a task description** from the story name, epic, description, and acceptance criteria
2. **Invokes the full TDD orchestrator pipeline** (a LangGraph `StateGraph`) for that story. The pipeline's happy path is:
   - **Test Agent** — writes failing tests (TDD red phase)
   - **Dev Agent** — writes implementation to make tests pass (TDD green phase)
   - **Unit Test** — runs tests (bash, no LLM)
   - **CI** — runs CI checks (bash, no LLM)
   - **Git Snapshot** — commits the passing code
   - **Prepare Reviews** — sets up parallel code reviews
   - **Review Nodes** — two parallel code reviews (Send API)
   - **Collect Reviews** — merges review results
   - **Architect** — creates a fix plan from review findings
   - **Fix Dev** — applies review fixes
   - **Post-Fix Test + CI** — re-validates after fixes
   - **System Test** — end-to-end validation
   - **Final CI** — last CI gate
   - **Git Push** — pushes the final result

   Each failure point has conditional routing back to the appropriate agent, governed by retry limits (tracked via `test_cycle_count`, `ci_cycle_count`, `edit_retry_count`).

3. **Auto-recovery detection** — if the pipeline succeeded but had retry cycles > 1, it logs that the agent self-recovered (useful for tracking agent reliability).

4. **Intervention handling** — if the pipeline fails and an `on_intervention` callback is provided (CLI mode only, not the API endpoint), it prompts for a human fix instruction and retries once. The API endpoint does **not** wire up `on_intervention`, so via the API, failed stories just fail.

5. **Progress tracking** — after each story, writes `{target_dir}/rebuild-status.md` with per-story results.

### 5. Tag Epic Completion

After all stories in an epic complete, creates a git tag like `epic-<name>-complete` in the target repo.

### 6. Final Summary

Writes a final `rebuild-status.md` with total elapsed time, then returns the response:

- `status`: `"completed"` (all stories passed), `"partial"` (some failed), or `"empty"` (no stories)
- Counts: `stories_completed`, `stories_failed`, `interventions`, `total_stories`

## Key Distinction: API vs CLI

The **API endpoint** (`POST /rebuild`) runs the loop **without** intervention support — if a story's pipeline fails, it's recorded as failed and the loop moves on. The **CLI** (`--rebuild`) wires up an interactive prompt so a human can provide fix instructions mid-loop. There is a separate `POST /rebuild/intervene` endpoint for API-based intervention, but it's not wired into the synchronous rebuild call.

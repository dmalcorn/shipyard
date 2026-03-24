# Story 3.3: Parallel Review Pipeline (Send API)

Status: complete

## Story

As a developer,
I want two independent Review Agents to analyze code in parallel and write their findings to separate files,
so that I get broader review coverage without groupthink between reviewers.

## Acceptance Criteria

1. **Given** code has been committed (git snapshot) **When** the orchestrator reaches the review phase **Then** it uses LangGraph's `Send` API to spawn 2 Review Agents in parallel
2. **Given** Review Agent 1 and Review Agent 2 running in parallel **When** each completes its review **Then** Agent 1 writes to `reviews/review-agent-1.md` and Agent 2 writes to `reviews/review-agent-2.md` **And** both files follow the inter-agent communication format (YAML frontmatter, numbered findings, severity levels)
3. **Given** both reviews are complete **When** the orchestrator proceeds **Then** it invokes the Architect Agent sequentially, passing both review files as input

## Tasks / Subtasks

- [x] Task 1: Implement `Send` API fan-out node in orchestrator (AC: #1)
  - [x] Import `Send` from `langgraph.types` (updated from deprecated `langgraph.constants`)
  - [x] Create a `route_to_reviewers` function that returns a list of `Send` objects
  - [x] Wire as conditional edge from prepare_reviews node: `graph.add_conditional_edges("prepare_reviews", route_to_reviewers)`
  - [x] Both `Send` targets point to the same `review_node` — LangGraph executes them in parallel
- [x] Task 2: Implement `review_node` function (AC: #1, #2)
  - [x] Node receives state with `reviewer_id` to differentiate the two instances
  - [x] Spawns a Review Agent subgraph via `run_sub_agent(role="reviewer", ...)`
  - [x] Passes task with output format instructions for `reviews/review-agent-{reviewer_id}.md`
  - [x] Include context files: list of modified source files and test files for the agent to review
  - [x] Review Agent has read-only source access + write to `reviews/` only (enforced by Story 3.1)
- [x] Task 3: Implement review output file format (AC: #2)
  - [x] Task description instructs reviewer to produce YAML frontmatter format
  - [x] Differentiate reviewer focus areas: Reviewer 1 focuses on correctness/logic, Reviewer 2 focuses on style/patterns/edge cases (via different focus area strings)
- [x] Task 4: Implement fan-in collector node (AC: #3)
  - [x] Create `collect_reviews` node that runs after both review nodes complete
  - [x] LangGraph's `Send` API automatically waits for all parallel branches before proceeding
  - [x] Node reads `reviews/review-agent-1.md` and `reviews/review-agent-2.md` from filesystem
  - [x] Validates both files exist and have correct YAML frontmatter
  - [x] Updates orchestrator state with review file paths for the Architect node
  - [x] Wire edge: `collect_reviews` → `architect_node`
- [x] Task 5: Ensure `reviews/` directory exists and is clean (AC: #2)
  - [x] Before spawning reviewers, clear any existing review files from previous runs (preserving .gitkeep)
  - [x] Ensure `reviews/` directory exists (create if needed)
  - [x] `reviews/` already in `.gitignore`; added `fix-plan.md` for Story 3.4
- [x] Task 6: Write tests in `tests/test_multi_agent/test_orchestrator.py` (AC: #1-#3)
  - [x] Test `route_to_reviewers` returns exactly 2 `Send` objects
  - [x] Test both `Send` objects target `review_node` with different `reviewer_id` values
  - [x] Test `review_node` spawns a Review Agent with correct role config
  - [x] Test `collect_reviews` reads both review files and updates state
  - [x] Test review output file format has required YAML frontmatter fields
  - [x] Integration test: run review pipeline with mock agent, verify 2 files created

## Dev Notes

- **Primary files:** `src/multi_agent/orchestrator.py` (extend), `src/multi_agent/spawn.py` (use)
- **LangGraph Send API:** The `Send` API is LangGraph's mechanism for dynamic fan-out. It allows a conditional edge to return multiple `Send` objects, each targeting a node with different input. LangGraph runs them in parallel and waits for all to complete before proceeding.
- **Key import:** `from langgraph.constants import Send` — verify this import path against the installed langgraph version (1.1.0)
- **Reviewer differentiation:** Give each reviewer a slightly different system prompt focus to avoid duplicate findings:
  - Reviewer 1: "Focus on correctness, logic errors, missing edge cases, and test coverage gaps"
  - Reviewer 2: "Focus on code style, architectural patterns, naming conventions, and maintainability"
- **File-based coordination:** Reviewers write to disk; the collect node reads from disk. This is the filesystem-as-coordination-primitive pattern from the architecture.
- **Do NOT share message history** between the two reviewers — each gets an independent context
- **Severity levels are fixed:** `critical`, `major`, `minor` — per architecture Pattern 3
- **Cost optimization:** Both reviewers use Sonnet (not Opus) — Opus is reserved for the Architect

### Dependencies

- **Requires:** Story 3.1 (Agent Role Definitions) — Reviewer role config with read-only + reviews/ write
- **Requires:** Story 3.2 (Sub-Agent Spawning) — `create_agent_subgraph()` for spawning reviewers
- **Feeds into:** Story 3.4 (Architect Decision) — Architect reads the review files
- **Feeds into:** Story 3.5 (Full TDD Orchestrator) — review pipeline is a stage in the full pipeline

### Project Structure Notes

- `src/multi_agent/orchestrator.py` — this is where the parent `StateGraph` lives
- `reviews/` — runtime artifact directory, git-ignored, created at runtime
- Review files are ephemeral per pipeline run — cleared before each review phase

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 2: Multi-Agent Coordination Pattern — Send API for parallel review]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 3: File-Based Communication Format]
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Flow diagram — Send(reviewer_1, reviewer_2)]
- [Source: coding-standards.md#File-Based Communication Format — YAML frontmatter structure]
- [Source: _bmad-output/project-context.md#Inter-Agent Communication]

## Dev Agent Record

### Agent Model Used
claude-opus-4-6

### Debug Log References
N/A

### Completion Notes List
- Used `from langgraph.types import Send` (not deprecated `langgraph.constants`)
- `_ensure_reviews_dir()` preserves `.gitkeep` during cleanup for scaffold test compatibility
- `OrchestratorState` uses `TypedDict(total=False)` for optional fields
- `ReviewNodeInput` is a separate TypedDict for Send API payloads
- Review file paths use forward slashes (not `os.path.join`) for cross-platform consistency

### File List
- `src/multi_agent/orchestrator.py` — new: orchestrator graph with all nodes
- `tests/test_multi_agent/test_orchestrator.py` — new: 32 tests
- `.gitignore` — modified: added `fix-plan.md`
- `reviews/.gitkeep` — recreated after test cleanup

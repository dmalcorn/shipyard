---
stepsCompleted: [1, 2, 3, 4]
status: complete
completedAt: '2026-03-23'
inputDocuments:
  - _bmad-output/planning-artifacts/product-brief-shipyard-2026-03-23.md
  - _bmad-output/planning-artifacts/architecture.md
  - gauntlet_docs/PRESEARCH.md
  - gauntlet_docs/shipyard_prd.pdf
  - coding-standards.md
---

# Shipyard - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Shipyard, decomposing the requirements from the Product Brief, Architecture, PRESEARCH, and assignment PRD into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: Persistent Agent Loop — Agent runs in a persistent loop (FastAPI server or CLI), accepts new instructions continuously without restarting. LangGraph state checkpointing (SQLite) for session persistence across restarts.

FR2: Surgical File Editing — `edit_file(path, old_string, new_string)` with exact string matching. Fails loudly on no-match or non-unique match. No fuzzy fallback. Read-before-edit enforced.

FR3: Context Injection — 3-layer system: Layer 1 (always-present role/conventions in system prompt), Layer 2 (task-specific files passed per instruction), Layer 3 (on-demand via Read/Grep/Glob tools). Context demonstrably changes agent behavior.

FR4: Multi-Agent Coordination — Spawn and coordinate multiple agents working in parallel or sequence. File-based communication, no shared memory. Minimum 2 agents for MVP; full TDD pipeline (Test → Dev → 2 Review → Architect → Fix Dev) for Early Submission.

FR5: LangSmith Tracing — Zero-config auto-tracing via environment variables. Every node, LLM call, tool call traced. Custom metadata tags. At least 2 shared trace links showing different execution paths.

FR6: Tool Suite — Read, Edit, Write, Glob, Grep, Bash tools wired as Claude tool-use functions via Anthropic SDK. Role-based tool subsets per agent.

FR7: Ship App Rebuild — Agent rebuilds the Ship app from scratch as integration test. Document every intervention. This is the data source for the comparative analysis. (Early Submission)

FR8: CODEAGENT.md — Agent Architecture + File Editing Strategy sections for MVP. Multi-Agent Design + Trace Links for MVP. Architecture Decisions, Ship Rebuild Log, Comparative Analysis, Cost Analysis for Final.

FR9: Comparative Analysis — 7-section structured written analysis comparing agent-built Ship vs original: Executive Summary, Architectural Comparison, Performance Benchmarks, Shortcomings, Advances, Trade-off Analysis, If You Built It Again. (Final Submission)

FR10: AI Development Log — 1-page document: Tools & Workflow, Effective Prompts (3-5 actual prompts), Code Analysis, Strengths & Limitations, Key Learnings. (Final Submission)

FR11: AI Cost Analysis — Dev spend (input/output tokens, invocations, total spend) + production projections for 100/1K/10K users with assumptions. (Final Submission)

FR12: Demo Video — 3-5 min showing agent making a surgical edit, completing a multi-agent task, and at least one Ship rebuild example. (Final Submission)

FR13: Deployed Application — Agent and agent-built Ship app both publicly accessible. (Final Submission)

FR14: Social Post — X or LinkedIn post with description, features, demo/screenshots, tag @GauntletAI. (Final Submission)

FR15: GitHub Repository — Setup guide, architecture overview. Another engineer can clone and run without asking questions. Accessible via GitHub for all phases.

### NonFunctional Requirements

NFR1: Edit Reliability — >90% first-attempt surgical edit success rate (measured via LangSmith: edit calls vs retries)

NFR2: Loop Stability — 30+ minutes continuous operation without crash

NFR3: Trace Completeness — Every agent action visible and linkable in LangSmith

NFR4: Fail-Loud Semantics — Edits must fail explicitly, never silently corrupt. No fuzzy matching fallbacks.

NFR5: Token Cost Awareness — Model routing (Haiku for reads/search, Sonnet for coding/review, Opus for Architect). No hard budget cap but cost tracked for analysis deliverable.

NFR6: Reproducibility — Another engineer can clone, set env vars, and run locally in <10 minutes

### Additional Requirements

- Custom `StateGraph` from day one — no `create_react_agent` then refactor
- Hybrid multi-agent pattern: Subgraphs (sequential) + `Send` API (parallel review)
- Extended `AgentState` schema: `task_id`, `retry_count`, `current_phase`, `agent_role`, `files_modified`
- Dual retry limits: global 50-turn cap + per-operation (3 edit retries, 5 test cycles, 3 CI failures)
- Shared working directory with role-based write restrictions per agent
- Markdown audit log format (`logs/session-{id}.md`)
- Tool contract: string in, string out, `SUCCESS:`/`ERROR:` prefix
- Agent prompt template: Role, Constraints, Process, Output sections
- File-based communication with YAML frontmatter format
- Manual scaffold — specific project structure defined in architecture doc
- Docker + docker-compose for containerization (local for MVP, Railway for Final)
- FastAPI + CLI dual-mode entry point (both call same `agent.invoke()`)

### UX Design Requirements

N/A — Shipyard is a backend/agent system with no UI beyond CLI and HTTP API.

### FR Coverage Map

| FR | Epic | Description |
|---|---|---|
| FR1: Persistent Agent Loop | Epic 1 | FastAPI + CLI loop with SQLite checkpointing |
| FR2: Surgical File Editing | Epic 1 | edit_file tool with exact string matching |
| FR3: Context Injection | Epic 1 | 3-layer context system |
| FR4: Multi-Agent Coordination | Epic 3 | Subgraphs + Send API, full TDD pipeline |
| FR5: LangSmith Tracing | Epic 2 | Auto-tracing + custom metadata + 2 trace links |
| FR6: Tool Suite | Epic 1 | Read, Edit, Write, Glob, Grep, Bash tools |
| FR7: Ship App Rebuild | Epic 4 | Agent rebuilds Ship, interventions documented |
| FR8: CODEAGENT.md | Epic 2 + 3 + 5 | MVP sections in E2/E3, Final sections in E5 |
| FR9: Comparative Analysis | Epic 5 | 7-section structured analysis |
| FR10: AI Development Log | Epic 5 | 1-page document with prompts and learnings |
| FR11: AI Cost Analysis | Epic 5 | Dev spend + 100/1K/10K user projections |
| FR12: Demo Video | Epic 6 | 3-5 min video showing key capabilities |
| FR13: Deployed Application | Epic 6 | Agent + Ship app publicly accessible |
| FR14: Social Post | Epic 6 | X/LinkedIn post with demo |
| FR15: GitHub Repository | Epic 1 | Setup guide, architecture overview, clone-and-run |

**Milestone Alignment:**
- **MVP (Tuesday 11:59 PM):** Epic 1 + Epic 2
- **Early Submission (Thursday 11:59 PM):** + Epic 3 + Epic 4
- **Final Submission (Sunday 11:59 PM):** + Epic 5 + Epic 6

## Epic List

### Epic 1: Core Agent Foundation
A developer can send an instruction to Shipyard and watch it read files, make a surgical edit, and persist state — the agent loop works end-to-end with a single agent. Includes project scaffold, all tools, StateGraph core loop, FastAPI + CLI entry points, context injection, and LangSmith tracing setup.
**FRs covered:** FR1, FR2, FR3, FR6, FR15

### Epic 2: Observability & Tracing
An evaluator can click a LangSmith trace link and see exactly what the agent did — every tool call, every decision, every retry — with meaningful metadata tags. Produces the 2 required shareable trace links and writes the MVP sections of CODEAGENT.md (Agent Architecture, File Editing Strategy).
**FRs covered:** FR5, FR8 (MVP sections)

### Epic 3: Multi-Agent Pipeline
A developer can give Shipyard a feature spec and the system orchestrates Test Agent → Dev Agent → Review Agents → Architect → Fix Dev automatically, producing tested, reviewed, working code. Builds the parent orchestrator graph with subgraphs + Send API for parallel review.
**FRs covered:** FR4, FR8 (Multi-Agent Design section)

### Epic 4: Ship App Rebuild
Shipyard autonomously rebuilds the Ship app from scratch, proving it works on a real project. Every intervention is documented, producing the raw data for all analysis deliverables.
**FRs covered:** FR7

### Epic 5: Analysis & Documentation
Evaluators receive a complete analysis package — comparative analysis with specific evidence from the rebuild log, cost analysis with projections, development log with actual prompts — demonstrating deep understanding of the agent's capabilities and limitations.
**FRs covered:** FR8 (remaining CODEAGENT.md sections), FR9, FR10, FR11

### Epic 6: Deployment & Presentation
Anyone can access the running agent and Ship app live, watch a demo video showing the agent in action, and see the social post. Complete submission package delivered.
**FRs covered:** FR12, FR13, FR14

---

## Epic 1: Core Agent Foundation

A developer can send an instruction to Shipyard and watch it read files, make a surgical edit, and persist state — the agent loop works end-to-end with a single agent.

### Story 1.1: Project Scaffold & Dev Environment

As a developer,
I want to clone the Shipyard repo and have a working Python environment with all dependencies installed,
So that I can begin building the agent immediately.

**Acceptance Criteria:**

**Given** a fresh clone of the repository
**When** I run `pip install -r requirements.txt`
**Then** all dependencies install successfully (langgraph, langchain-anthropic, langgraph-checkpoint-sqlite, python-dotenv, fastapi, uvicorn)
**And** the project structure matches the architecture doc (`src/agent/`, `src/tools/`, `src/multi_agent/`, `src/context/`, `src/logging/`, `scripts/`, `tests/`)
**And** `.env.example` contains all required environment variables (ANTHROPIC_API_KEY, LANGCHAIN_TRACING_V2, LANGCHAIN_API_KEY, LANGCHAIN_PROJECT)
**And** `pyproject.toml` configures ruff and mypy
**And** `Dockerfile` and `docker-compose.yml` are present and buildable

### Story 1.2: File Operation Tools (Read, Edit, Write)

As a developer using the agent,
I want the agent to read files, make surgical edits via exact string replacement, and write new files,
So that the agent can modify code precisely without rewriting entire files.

**Acceptance Criteria:**

**Given** a file exists at a specified path
**When** the agent calls `read_file(file_path)`
**Then** the file contents are returned as a string prefixed with `SUCCESS:`
**And** files exceeding 5000 chars are truncated with a note

**Given** a file has been read and contains an exact match for `old_string`
**When** the agent calls `edit_file(file_path, old_string, new_string)`
**Then** only the matched string is replaced and the result starts with `SUCCESS:`

**Given** `old_string` does not exist in the file
**When** the agent calls `edit_file`
**Then** the tool returns `ERROR: old_string not found in {file_path}. Re-read the file to get current contents.`

**Given** `old_string` matches multiple locations in the file
**When** the agent calls `edit_file`
**Then** the tool returns `ERROR: old_string found {count} times in {file_path}. Provide more surrounding context to make the match unique.`

**Given** any path
**When** the agent calls `write_file(file_path, content)`
**Then** the file is created/overwritten and the result starts with `SUCCESS:`

### Story 1.3: Search & Execution Tools (Glob, Grep, Bash)

As a developer using the agent,
I want the agent to find files by pattern, search file contents, and run shell commands,
So that the agent can explore the codebase and execute build/test/lint operations.

**Acceptance Criteria:**

**Given** a directory with files
**When** the agent calls `list_files(pattern)` with a glob pattern
**Then** matching file paths are returned as a `SUCCESS:` string

**Given** files with content
**When** the agent calls `search_files(pattern, path)` with a regex
**Then** matching lines with file paths and line numbers are returned

**Given** a valid shell command
**When** the agent calls `run_command(command)`
**Then** the command executes with a configurable timeout and stdout/stderr are returned
**And** commands exceeding timeout return an `ERROR:` with the timeout duration

**Given** all tools
**When** any tool encounters an exception
**Then** the exception is caught and returned as an `ERROR:` string — no exceptions escape tools

### Story 1.4: Core Agent Loop (StateGraph)

As a developer,
I want a working LangGraph agent that accepts an instruction, reasons about it, calls tools, and returns a result,
So that I have the foundational agent loop that all multi-agent features will build on.

**Acceptance Criteria:**

**Given** the agent is initialized with a custom `StateGraph` (not `create_react_agent`)
**When** the agent receives a message
**Then** it enters the ReAct loop: agent_node → should_continue → tool_node → agent_node (repeat)
**And** the loop terminates when the LLM returns no tool calls

**Given** the `AgentState` schema
**When** a session runs
**Then** state includes `messages`, `task_id`, `retry_count`, `current_phase`, `agent_role`, `files_modified`

**Given** a global turn cap of 50
**When** the agent exceeds 50 LLM turns in a single task
**Then** the loop terminates with an error message rather than running indefinitely

**Given** SQLite checkpointing is configured
**When** the agent processes a message
**Then** state is persisted after every node execution
**And** the session can be resumed with the same `thread_id`

### Story 1.5: Context Injection System

As a developer,
I want to inject context (role descriptions, task specs, coding standards) into the agent so it follows project conventions,
So that the agent's behavior changes based on the context provided.

**Acceptance Criteria:**

**Given** Layer 1 context files exist (agent role description, coding standards, orchestration guidance)
**When** the agent starts a session
**Then** Layer 1 context is included in the system prompt for every invocation

**Given** a task instruction includes Layer 2 context (specific file paths, task specs)
**When** the agent receives the instruction
**Then** the task-specific files are read and included in the message context

**Given** the agent is running
**When** it needs additional information during execution
**Then** it can use Read, Grep, and Glob tools (Layer 3) to pull on-demand context

**Given** the same instruction sent with different Layer 1 context (e.g., "You are a Dev Agent" vs. "You are a Review Agent")
**When** both agents process the instruction
**Then** their outputs demonstrably differ based on the injected role context

### Story 1.6: Persistent Server & CLI Entry Point

As a developer,
I want to interact with Shipyard via HTTP API or CLI, with the agent staying alive between instructions,
So that I can send multiple instructions without restarting the agent.

**Acceptance Criteria:**

**Given** the FastAPI server is running
**When** I send `POST /instruct` with `{message: str, session_id?: str}`
**Then** the agent processes the instruction and returns `{session_id: str, response: str, messages_count: int}`

**Given** an existing session_id
**When** I send another instruction with the same session_id
**Then** the agent resumes from its checkpointed state with full conversation history

**Given** CLI mode is started with `python src/main.py --cli`
**When** I type an instruction
**Then** the agent processes it using the same `agent.invoke()` path as the HTTP API

**Given** either mode
**When** I send a second instruction after the first completes
**Then** the agent processes it without restarting — persistent loop confirmed

### Story 1.7: Repository Documentation & Setup Guide

As an evaluator,
I want to clone the repo, follow the README, and have the agent running locally in under 10 minutes,
So that I can evaluate the agent without asking the developer any questions.

**Acceptance Criteria:**

**Given** the README.md exists
**When** an evaluator reads it
**Then** it contains: project overview, prerequisites, environment setup steps, how to run (CLI and server modes), example usage with sample instruction

**Given** `.env.example` exists
**When** the evaluator copies it to `.env` and fills in API keys
**Then** the agent starts successfully with LangSmith tracing enabled

**Given** `.gitignore` exists
**When** checking the repository
**Then** runtime artifacts are excluded: `logs/`, `reviews/`, `checkpoints/`, `.env`, `__pycache__/`, `.venv/`

---

## Epic 2: Observability & Tracing

An evaluator can click a LangSmith trace link and see exactly what the agent did — every tool call, every decision, every retry — with meaningful metadata tags.

### Story 2.1: LangSmith Tracing & Custom Metadata

As an evaluator,
I want every agent action traced in LangSmith with meaningful metadata (agent role, task ID, model tier, phase),
So that I can filter, search, and understand agent behavior from the trace UI.

**Acceptance Criteria:**

**Given** LangSmith environment variables are set (LANGCHAIN_TRACING_V2=true, LANGCHAIN_API_KEY, LANGCHAIN_PROJECT)
**When** the agent processes an instruction
**Then** LangSmith automatically traces every node execution, LLM call, and tool call

**Given** any agent invocation
**When** the trace is recorded
**Then** it includes metadata: `agent_role` (dev|test|reviewer|architect|fix_dev), `task_id`, `model_tier` (haiku|sonnet|opus), `phase` (test|implementation|review|fix|ci)

**Given** a sub-agent is spawned
**When** its trace is recorded
**Then** it includes `parent_session` linking it to the parent trace

### Story 2.2: Markdown Audit Logger

As a developer,
I want a local markdown audit log for every session that records agent actions, tool calls, and outcomes,
So that I have a portable trace artifact that works without LangSmith access and feeds directly into deliverables.

**Acceptance Criteria:**

**Given** an agent session starts
**When** the session runs
**Then** a file is created at `logs/session-{session_id}.md` with the session header including timestamp and task description

**Given** an agent calls a tool during a session
**When** the tool returns
**Then** the audit log appends an entry: agent role, model used, tool name, file path, and SUCCESS/ERROR result

**Given** a session completes
**When** the log is finalized
**Then** it includes a summary line: total agents invoked, total scripts run, files touched

**Given** the audit log format
**When** compared to the architecture doc's trace format
**Then** it matches the tree-style format defined in Decision 6

### Story 2.3: Shareable Trace Links

As an evaluator,
I want 2 shareable LangSmith trace links showing different execution paths,
So that I can verify the agent handles both normal runs and error/branching conditions.

**Acceptance Criteria:**

**Given** the agent is running with LangSmith tracing enabled
**When** Trace 1 is produced from a normal run (instruction → read file → surgical edit → success)
**Then** a shareable LangSmith link is captured showing the complete execution path

**Given** the agent is running
**When** Trace 2 is produced from a different execution path (e.g., edit failure → re-read → retry → success, OR a branching condition)
**Then** a shareable LangSmith link is captured showing the alternate path

**Given** both trace links
**When** an evaluator opens them
**Then** they can see every node, tool call, input/output, and metadata for each run

### Story 2.4: CODEAGENT.md — MVP Sections

As an evaluator,
I want the CODEAGENT.md file with Agent Architecture and File Editing Strategy sections completed,
So that I can understand how the agent works without reading the source code.

**Acceptance Criteria:**

**Given** the CODEAGENT.md file
**When** the Agent Architecture section is written
**Then** it contains: loop design, tool calls, state management, entry/exit conditions, error branches (diagram or written description)

**Given** the CODEAGENT.md file
**When** the File Editing Strategy section is written
**Then** it describes: the exact mechanism step by step, how the agent locates the correct block, what happens when it gets the location wrong

**Given** the CODEAGENT.md file
**When** the Trace Links section is written
**Then** it contains 2 shareable LangSmith links: Trace 1 (normal run) and Trace 2 (different execution path)

---

## Epic 3: Multi-Agent Pipeline

A developer can give Shipyard a feature spec and the system orchestrates specialized agents automatically through the full TDD pipeline.

### Story 3.1: Agent Role Definitions & Tool Subsets

As a developer,
I want each agent role (Dev, Test, Reviewer, Architect) to have its own system prompt, model tier, and tool permissions,
So that agents are specialized and constrained to their responsibilities.

**Acceptance Criteria:**

**Given** the roles module
**When** a Dev Agent is configured
**Then** it uses Sonnet, has full tool access (read, edit, write, glob, grep, bash), and follows the Dev Agent prompt template

**Given** the roles module
**When** a Test Agent is configured
**Then** it uses Sonnet, can write test files and read source, and follows the Test Agent prompt template

**Given** the roles module
**When** a Review Agent is configured
**Then** it uses Sonnet, has read-only access to source + tests, can only write to `reviews/` directory, and follows the Review Agent prompt template

**Given** the roles module
**When** an Architect Agent is configured
**Then** it uses Opus, can read review files, can write fix plan files, cannot edit source, and follows the Architect prompt template

**Given** a Review Agent
**When** it attempts to call `edit_file` on a source file
**Then** the tool returns `ERROR: Permission denied: Review agents cannot edit source files. Write to reviews/ directory only.`

### Story 3.2: Sub-Agent Spawning with Subgraphs

As a developer,
I want the orchestrator to spawn specialized agents as LangGraph subgraphs that run independently with their own context,
So that each agent gets a fresh context window with only its task and injected files.

**Acceptance Criteria:**

**Given** the orchestrator parent graph
**When** it spawns a sub-agent (e.g., Dev Agent)
**Then** a new compiled subgraph is created with the role's tool subset, system prompt, and model tier

**Given** a sub-agent subgraph
**When** it runs
**Then** it does NOT share message history with the parent — it starts fresh with only its task description and injected context files

**Given** a sub-agent
**When** it produces output
**Then** the output is written to the filesystem (the coordination primitive) and the parent graph reads it

**Given** sub-agent state
**When** traced in LangSmith
**Then** the sub-agent trace is linked to the parent via `parent_session` metadata

### Story 3.3: Parallel Review Pipeline (Send API)

As a developer,
I want two independent Review Agents to analyze code in parallel and write their findings to separate files,
So that I get broader review coverage without groupthink between reviewers.

**Acceptance Criteria:**

**Given** code has been committed (git snapshot)
**When** the orchestrator reaches the review phase
**Then** it uses LangGraph's `Send` API to spawn 2 Review Agents in parallel

**Given** Review Agent 1 and Review Agent 2 running in parallel
**When** each completes its review
**Then** Agent 1 writes to `reviews/review-agent-1.md` and Agent 2 writes to `reviews/review-agent-2.md`
**And** both files follow the inter-agent communication format (YAML frontmatter, numbered findings, severity levels)

**Given** both reviews are complete
**When** the orchestrator proceeds
**Then** it invokes the Architect Agent sequentially, passing both review files as input

### Story 3.4: Architect Decision & Fix Pipeline

As a developer,
I want an Architect Agent to evaluate review findings and produce a fix plan that a fresh Dev Agent executes,
So that only validated issues are fixed and the fix agent isn't polluted by the original implementation context.

**Acceptance Criteria:**

**Given** the Architect Agent receives both review files
**When** it evaluates findings
**Then** it produces a `fix-plan.md` with: which findings to fix (with justification), which to dismiss (with justification), and specific fix instructions per item

**Given** a fix plan exists
**When** the orchestrator spawns a Fix Dev Agent
**Then** it is a fresh Dev Agent (no shared history with original Dev) that reads the fix plan and executes the approved fixes

**Given** the Fix Dev Agent completes fixes
**When** unit tests are run
**Then** all tests pass before proceeding to CI

### Story 3.5: Full TDD Orchestrator Pipeline

As a developer,
I want the complete pipeline (Test → Dev → CI → Review → Architect → Fix → CI → System Tests → Push) wired as a parent StateGraph,
So that I can give Shipyard a feature spec and it delivers tested, reviewed, committed code.

**Acceptance Criteria:**

**Given** the orchestrator receives a task (epic/story spec)
**When** the pipeline runs
**Then** it executes in this order: Test Agent → Dev Agent → unit tests → local CI → git snapshot → 2 Review Agents (parallel) → Architect → Fix Dev → unit tests → local CI → system tests → local CI (final gate) → git commit and push

**Given** any test or CI failure in the pipeline
**When** the failure occurs
**Then** it routes back to the appropriate agent for correction (per retry limits: 3 edit, 5 test, 3 CI)

**Given** retry limits are exceeded
**When** the error handler fires
**Then** it halts the pipeline and produces a failure report with what went wrong

**Given** bash scripts for CI, testing, and git
**When** they run
**Then** they execute as bash commands (not LLM calls) to conserve token cost

### Story 3.6: CODEAGENT.md — Multi-Agent Design Section

As an evaluator,
I want the Multi-Agent Design section of CODEAGENT.md completed,
So that I can understand the orchestration model, agent communication, and how parallel outputs are merged.

**Acceptance Criteria:**

**Given** the CODEAGENT.md file
**When** the Multi-Agent Design section is written
**Then** it describes: orchestration model (subgraphs + Send), how agents communicate (file-based), how parallel review outputs are merged (Architect gatekeeper), and includes a diagram

---

## Epic 4: Ship App Rebuild

Shipyard autonomously rebuilds the Ship app from scratch, proving it works on a real project with every intervention documented.

### Story 4.1: Ship App Specification Intake

As a developer,
I want to feed the Ship app's specifications into Shipyard's intake pipeline,
So that the agent can break it into epics and stories for autonomous rebuilding.

**Acceptance Criteria:**

**Given** the Ship app's documentation/specs are available
**When** they are provided to the Intake Specs node
**Then** the agent processes them and produces a structured spec summary

**Given** the structured specs
**When** the Create Epics and Stories node runs
**Then** it produces a prioritized backlog of epics and stories for the Ship app rebuild

### Story 4.2: Autonomous Ship Rebuild Execution

As a developer,
I want Shipyard to execute the full TDD pipeline against the Ship app backlog, rebuilding it epic by epic,
So that the agent proves it can complete a real build task with the full multi-agent pipeline.

**Acceptance Criteria:**

**Given** the Ship app backlog is created
**When** the orchestrator loops through each epic
**Then** for each epic: detailed stories are created → Test Agent writes failing tests → Dev Agent implements → CI runs → Review → Architect → Fix → System tests → Git push

**Given** the agent gets stuck or produces incorrect output
**When** human intervention is needed
**Then** every intervention is logged: what broke, what was done, what it reveals about the agent's limitations

**Given** the rebuild completes
**When** the Ship app is assessed
**Then** it contains all current features of the original Ship app as specified

### Story 4.3: Rebuild Intervention Log

As an evaluator,
I want a running log of every human intervention during the Ship rebuild,
So that I have the raw data for the comparative analysis and can assess the agent's real-world limitations.

**Acceptance Criteria:**

**Given** any human intervention occurs during the rebuild
**When** the developer intervenes
**Then** the log records: timestamp, what broke or got stuck, what the developer did, and what it reveals about the agent

**Given** the rebuild completes
**When** the intervention log is reviewed
**Then** it provides specific, evidence-based data (not vague summaries) suitable for the comparative analysis deliverable

---

## Epic 5: Analysis & Documentation

Evaluators receive a complete analysis package demonstrating deep understanding of the agent's capabilities and limitations.

### Story 5.1: Comparative Analysis (7 Sections)

As an evaluator,
I want a structured written analysis comparing the agent-built Ship app against the original,
So that I can assess the quality of the agent's output with specific evidence.

**Acceptance Criteria:**

**Given** the Ship rebuild is complete with intervention log data
**When** the comparative analysis is written
**Then** it contains all 7 required sections: Executive Summary, Architectural Comparison, Performance Benchmarks, Shortcomings, Advances, Trade-off Analysis, If You Built It Again

**Given** each section
**When** reviewed
**Then** it contains specific claims backed by evidence from the rebuild log — no vague summaries

### Story 5.2: AI Cost Analysis

As an evaluator,
I want a cost analysis with actual dev spend and production projections,
So that I can assess the economic viability of the agent at scale.

**Acceptance Criteria:**

**Given** development is complete
**When** the cost analysis is written
**Then** it includes: Claude API input/output token costs, total invocations during development, total development spend

**Given** production scaling assumptions
**When** projections are calculated
**Then** it includes monthly cost estimates for 100, 1,000, and 10,000 users
**And** assumptions are documented: average invocations per user per day, average tokens per invocation, cost per invocation

### Story 5.3: AI Development Log

As an evaluator,
I want a 1-page development log documenting the AI-first development process,
So that I can understand how AI tools were used and what was learned.

**Acceptance Criteria:**

**Given** the development process is complete
**When** the log is written
**Then** it contains: Tools & Workflow, Effective Prompts (3-5 actual prompts, not descriptions), Code Analysis (AI-generated vs hand-written %), Strengths & Limitations, Key Learnings

### Story 5.4: CODEAGENT.md — Final Sections

As an evaluator,
I want the remaining CODEAGENT.md sections completed (Architecture Decisions, Ship Rebuild Log, Comparative Analysis, Cost Analysis),
So that I have the complete submission document.

**Acceptance Criteria:**

**Given** the CODEAGENT.md file
**When** all Final Submission sections are written
**Then** Architecture Decisions describes key decisions, what was considered, and why the call was made
**And** Ship Rebuild Log contains the rebuild intervention log
**And** Comparative Analysis contains the 7-section analysis
**And** Cost Analysis contains dev spend + projections

---

## Epic 6: Deployment & Presentation

Anyone can access the running agent and Ship app live, watch a demo video, and see the social post. Complete submission package delivered.

### Story 6.1: Cloud Deployment

As an evaluator,
I want the Shipyard agent and the agent-built Ship app both publicly accessible,
So that I can interact with them live without cloning the repo.

**Acceptance Criteria:**

**Given** the Docker container runs locally
**When** deployed to Railway (or equivalent hosting)
**Then** the Shipyard agent is accessible via public URL with the `/instruct` endpoint working

**Given** the Ship app was rebuilt by the agent
**When** it is deployed
**Then** the Ship app is publicly accessible at its own URL

### Story 6.2: Demo Video

As an evaluator,
I want a 3-5 minute demo video showing the agent in action,
So that I can see surgical editing, multi-agent coordination, and Ship rebuild without running anything myself.

**Acceptance Criteria:**

**Given** the agent is functional
**When** the demo video is recorded
**Then** it shows: the agent making a surgical edit, completing a multi-agent task, and at least one example from the Ship rebuild

**Given** the video
**When** reviewed
**Then** it is 3-5 minutes long and clearly demonstrates the agent's key capabilities

### Story 6.3: Social Post

As the Gauntlet program,
I want a social media post about Shipyard on X or LinkedIn,
So that the project gets visibility and demonstrates communication skills.

**Acceptance Criteria:**

**Given** the project is complete
**When** a post is published on X or LinkedIn
**Then** it includes: project description, key features, demo or screenshots, and tags @GauntletAI

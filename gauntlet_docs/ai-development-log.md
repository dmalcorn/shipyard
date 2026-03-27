# AI Development Log

## Tools & Workflow

**AI Tools Used:** Claude Code (Opus 4.6 via CLI and VS Code extension — primary development tool), Claude API via `langchain-anthropic` (runtime model calls within Shipyard's agent framework), Claude CLI subprocess invocations (BMAD agent execution in the rebuild pipeline), LangSmith (trace visualization and debugging).

**Development Workflow:** All code was written through Claude Code operating as a CLI pair-programmer. The workflow followed BMAD method phases: product brief → architecture decisions → epics/stories → story-by-story implementation. Each story was specified with acceptance criteria and task breakdowns, then handed to Claude Code for TDD-style execution. Human review happened at story boundaries — corrections were fed back as code-review findings for the next iteration.

**Development timeline:** 2026-03-23 to 2026-03-27 (5 days), 31 commits across 4 epics + infrastructure hardening.

**IDE/Editor:** VS Code with Claude Code extension. Ruff (linter/formatter) and mypy (type checker) ran as pre-commit gates via `scripts/local_ci.sh`.

**Key development phases:**

1. **Epic 1 — Core Agent Framework** (Day 1): Scaffold, 6 tools, ReAct agent loop, context injection, CLI entry point
2. **Epic 2 — Observability** (Day 1-2): LangSmith tracing, audit logger, trace links, CODEAGENT.md MVP sections
3. **Epic 3 — Multi-Agent Orchestration** (Day 2-3): 5 agent roles, role-based tool permissions, spawn/subgraph factory, orchestrator pipeline
4. **Epic 4 — Rebuild Pipeline** (Day 3-4): Intake pipeline, backlog parser, three-level LangGraph rebuild architecture, BMAD agent invocation via Claude CLI
5. **Infrastructure Hardening** (Day 4-5): Docker rebuild container, public monitoring dashboard with Postgres log relay, graceful pause/resume, cost tracking, epic-level Category A/B review redesign, bug fixes from integration testing

## Effective Prompts

**1. Role-Constrained Agent System Prompt** (from `src/agent/prompts.py`):
```
You are a Dev Agent. You write production code and fix bugs using surgical file edits.
You CAN read any file, search the codebase, and run bash commands.
You CANNOT edit files under reviews/ — that is for Review Agents only.
You MUST use exact string matching for edits — no fuzzy matching.
```
*Why effective:* Explicit CAN/CANNOT boundaries prevented agents from overstepping their role. The Review Agent's inverse constraint (read-only on `src/`) enforced separation of concerns at the prompt level.

**2. BMAD Agent Invocation Wrapper** (from `src/multi_agent/bmad_invoke.py`):
```
IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Use the Skill tool to invoke 'bmad-dev-story'
Step 2: Execute command: develop story 2-1
Step 3: After completing your work, end your response with this AGENT IDENTIFICATION block:
  === AGENT IDENTIFICATION ===
  Agent: [Your agent type]
  Persona: [Your persona name from the agent file]
  Loaded files: [exact path to each file you read during activation]
  === END IDENTIFICATION ===

Mode: Automated, no menus, no questions, always fix issues automatically, no waiting for user input.
```
*Why effective:* BMAD skills were designed for interactive use — they display menus and wait for input. This wrapper forces immediate execution and appends "Mode: Automated" to override interactive behavior. Combined with `stdin=DEVNULL` in the subprocess call, this eliminated all pipeline stalls from agents waiting for human input. The identification block provided traceability for which agent persona actually loaded.

**3. Coding Standards as Injected Context** (from `coding-standards.md`, injected every call):
```
These conventions apply to all code written in this project. When this file is injected
as agent context, follow every rule exactly.
- Tool interface: String parameters in, string results out
- Return SUCCESS: {result} or ERROR: {description}. {recovery_hint}
- Never bare except: — always except Exception as e:
```
*Why effective:* Defining the tool interface contract (`SUCCESS:`/`ERROR:` strings) in a file that was mechanically injected every time eliminated format drift across agent sessions. This file served double duty: it governed Claude Code during development AND was injected as Layer 1 context for Shipyard's own agents at runtime.

**4. PIPELINE MODE Directive** (from `.claude/skills/bmad-dev-story/workflow.md`):
```xml
<critical>PIPELINE MODE: Do NOT search for or discover stories. The orchestrator
  specifies exactly which story to develop via {{story_path}} or the command
  prompt. Use that story — no status checks, no filtering, no alternatives.</critical>
```
*Why effective:* The default BMAD dev-story workflow contained ~40 lines of story discovery logic that searched for "ready-for-dev" stories. In the automated pipeline, this caused the agent to skip the orchestrator's assigned story and pick its own. Replacing discovery with a direct "use what you're told" directive eliminated a class of pipeline failures where the wrong story was implemented.

**5. BMAD Story Specification** (structure used for every implementation story):
```
As a [role], I want [feature], so that [value].
Acceptance Criteria: Given/When/Then format
Tasks/Subtasks: Ordered checklist with AC references
Dev Notes: Architecture constraints, dependencies, previous learnings
```
*Why effective:* The structured format gave the AI agent unambiguous scope. The task-to-AC mapping prevented gold-plating — every line of code traced back to a specific requirement.

## Code Analysis

| Category | Files | Lines | % of Code |
|---|---|---|---|
| Source code (`src/`) | 35 | 7,788 | 61% |
| Test code (`tests/`) | 29 | 5,027 | 39% |
| **Total** | **64** | **12,815** | 100% |

**Growth from MVP to Final:** The codebase grew from 8,889 lines (27 source + 27 test files) at MVP to 12,815 lines (35 source + 29 test files) — a 44% increase driven primarily by the rebuild pipeline infrastructure (BMAD invocation, epic graph, rebuild graph, log relay, web relay, cost tracker, pause control).

**AI-generated:** ~95% — all source and test code was written by Claude Code from story specifications. **Human-written:** ~5% — configuration files (`pyproject.toml`, `Dockerfile`, `.env.example`, `docker-compose.rebuild.yml`), BMAD planning artifacts, skill customizations, and targeted manual fixes during code review. **AI-assisted:** 100% — even "hand-written" edits were made through Claude Code's edit interface with human direction.

**Commit distribution:** 31 total commits — 4 epic implementation commits, 6 code review fix commits, 12 feature additions (dashboard, monitoring, pause/resume, cost tracking, epic redesign, pipeline refactor), 9 bug fixes and infrastructure.

## Strengths & Limitations

**Strengths:**
- **Boilerplate velocity** — scaffolding 6 tool functions with tests, type hints, and docstrings took minutes, not hours. The three-level LangGraph rebuild architecture (rebuild_graph → epic_graph → orchestrator) was designed and implemented in a single session.
- **Standard adherence** — with coding standards injected every call, the agent never drifted from conventions (import ordering, error format, naming) across 31 commits and 12,815 lines.
- **Test coverage** — the agent wrote comprehensive test code (39% of codebase), covering both `SUCCESS:` and `ERROR:` paths for every tool, plus integration tests for the multi-agent orchestrator and rebuild pipeline.
- **Architecture consistency** — the three-level graph hierarchy, tool scoping per phase, and file-based inter-agent communication were all maintained coherently across multiple development sessions without structural drift.

**Limitations:**
- **Over-engineering by default** — without explicit "keep it minimal" constraints, the agent added unnecessary abstractions (e.g., factory patterns for single-use classes). The initial orchestrator design had a per-story pipeline with 16 nodes and 7 phases when a simpler "bash first, LLM on failure" pattern would have been more efficient.
- **Context window pressure** — multi-file refactors across 5+ files required careful context management; the agent sometimes lost track of earlier changes. The epic-graph redesign (Category A/B classification) required multiple passes because the agent couldn't hold the full node inventory in context.
- **Prompt sensitivity** — "write tests" produced different results than "write failing tests first, then implement" — the TDD framing produced significantly better code. Similarly, BMAD skill behavior was highly sensitive to whether "PIPELINE MODE" directives were placed at the top vs bottom of workflow steps.
- **Interactive skill adaptation** — BMAD skills designed for human interaction required non-obvious customizations to work autonomously. Three skills needed modification (`bmad-dev`, `bmad-dev-story`, and the invocation wrapper), and the failure mode was silent — agents would simply hang for 25 minutes waiting for input that would never come.

## Key Learnings

1. **Constraints > capabilities in prompts.** Telling the agent what it CANNOT do (e.g., "cannot edit src/") was more reliable than describing what it should do. Negative constraints are harder to accidentally violate.
2. **Mechanical context injection beats hoping the agent remembers.** Injecting `coding-standards.md` on every call was the single highest-ROI decision — zero convention drift across 50+ agent sessions. This extended to the rebuild pipeline: the same coding-standards file is injected as Layer 1 context for every agent Shipyard spawns.
3. **Story specs are the real prompt engineering.** The BMAD task breakdown (with AC references on each subtask) was more effective than any system prompt tweak. Structured specs eliminated ambiguity.
4. **TDD framing changes output quality.** Asking for "failing tests first" produced cleaner implementations than "write code and tests." The red-green cycle naturally constrained scope. This insight directly shaped the orchestrator design: `write_tests → implement → run_tests` as the core loop.
5. **Code review is non-negotiable.** AI-generated code passed its own tests but still contained edge cases and over-engineering that only adversarial review caught. This led to the epic-level Category A/B review system — obvious fixes applied automatically, design decisions routed to an Opus-tier architect agent.
6. **Bash first, LLM on failure.** The most impactful architecture insight was that mechanical operations (running tests, running CI, git commits) should be bash nodes, not LLM invocations. LLMs should only be called when something fails and needs reasoning to fix. This cut the per-story LLM cost roughly in half for the happy path.
7. **Interactive → autonomous requires explicit opt-out.** Adapting interactive tools (BMAD skills) for autonomous pipelines is not just about removing menus — every HALT condition, story discovery path, and completion prompt must be audited and replaced. The `stdin=DEVNULL` subprocess flag is a necessary safety net but not sufficient; the skills themselves must be modified.

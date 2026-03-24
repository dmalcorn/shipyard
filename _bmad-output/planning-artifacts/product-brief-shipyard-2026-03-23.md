---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments:
  - gauntlet_docs/PRESEARCH.md
  - gauntlet_docs/shipyard_prd.pdf
  - gauntlet_docs/system-flow.mmd
date: 2026-03-23
author: Diane
status: complete
---

# Product Brief: Shipyard

## Executive Summary

Shipyard is an autonomous coding agent that reads a codebase, understands what needs to change, and makes targeted surgical edits without rewriting entire files. Built on LangGraph with Claude (Anthropic SDK), it runs in a persistent loop accepting instructions continuously, coordinates multiple specialized agents (Dev, Test, Review, Architect) through a file-based communication model, and produces fully traceable execution logs via LangSmith. The agent will be validated by using it to rebuild the Ship app from scratch — serving as both integration test and the data source for a rigorous comparative analysis.

---

## Core Vision

### Problem Statement

Building and modifying software requires understanding large codebases, identifying precisely what needs to change, and making targeted edits without breaking everything around the change. Current AI coding tools either rewrite entire files (destroying surrounding context) or require constant human supervision to avoid hallucinated imports, broken references, and silent corruption. The engineering challenge — making a targeted change to one function in a 2,000-line file without touching anything else — is deceptively hard and requires deliberate design.

### Problem Impact

Developers waste significant time on manual code edits that could be automated, but existing tools create as many problems as they solve when edits are imprecise. Silent file corruption from fuzzy matching or full-file rewrites erodes trust. Without surgical editing, multi-agent coordination, and traceable execution, AI coding agents remain toys rather than tools.

### Why Existing Solutions Fall Short

- **Full-file rewrite agents** are code generators with filesystem wrappers — they break surrounding code and lose context on every change
- **Single-shot agents** (fire-and-forget) can't maintain state, accept follow-up instructions, or coordinate across tasks
- **Agents without tracing** are black boxes — when something goes wrong, there's no way to diagnose what happened, in what order, with what inputs
- **Agents without multi-agent coordination** can't divide complex tasks across specialized roles (testing, reviewing, architecting)

### Proposed Solution

A LangGraph-based autonomous coding agent with four core capabilities:
1. **Persistent loop** — runs continuously, accepts new instructions without restarting
2. **Surgical file editing** — anchor-based exact string replacement that fails loudly rather than corrupting silently
3. **Multi-agent coordination** — specialized agents (Dev, Test, Review, Architect) communicate through files, with parallel review pipelines and an Architect gatekeeper
4. **Context injection** — layered context system (always-present role/conventions, task-specific specs, on-demand codebase exploration) that keeps token costs manageable

### Key Differentiators

- **Fail-loud editing** — unlike agents that use fuzzy matching fallbacks, Shipyard's anchor-based replacement fails explicitly on no-match or non-unique match, forcing a re-read and retry rather than silently corrupting files
- **File-based agent communication** — no message-passing or shared memory; agents write output to files, downstream agents read those files, and an Architect agent makes deliberate merge decisions rather than blind auto-merging
- **TDD-first pipeline** — Test Agent writes failing tests before Dev Agent writes implementation, ensuring tests are specification-driven not implementation-driven
- **Bash for deterministic tasks** — linting, CI, git operations, and test execution run as bash scripts, reserving LLM tokens for tasks that require reasoning
- **Built-in tracing via LangSmith** — every node execution, LLM call, tool call, and token usage is automatically traced with zero custom code

---

## Target Users

### Primary Users

**"Diane" — The Gauntlet Participant**
- An intermediate developer under intense time pressure, tasked with building a complex software project within a one-week sprint
- Needs an agent that can take high-level instructions ("build a login handler with input validation"), break them into subtasks, write tests, implement code, review its own work, and push clean results — all with minimal intervention
- Success looks like: giving the agent a spec, watching it work through the TDD pipeline, intervening only when it truly gets stuck, and getting shippable code at the end
- Current pain: manually coordinating between writing tests, implementing features, reviewing code, and running CI — all of which could be parallelized and automated

### Secondary Users

**Evaluators / Reviewers**
- Technical evaluators who will assess the agent's output quality, trace logs, and comparative analysis
- Need clear tracing (LangSmith trace links), well-documented architecture (CODEAGENT.md), and reproducible local setup (clone and run)
- Success: they can clone the repo, run the agent locally, see surgical edits happening, view trace logs, and understand the architecture from documentation alone

### User Journey

1. **Setup** — Clone repo, set environment variables (Anthropic API key, LangSmith keys), run `docker compose up` or `python main.py`
2. **Instruction** — Send a task via CLI/HTTP: "Build a React login form with validation"
3. **Execution** — Agent enters TDD loop: Test Agent writes failing tests → Dev Agent implements → Local CI runs → Review Agents analyze → Architect decides fixes → Fix Dev patches → System tests pass → Git commit
4. **Observation** — User monitors via LangSmith traces showing each agent's actions, tool calls, and decisions in real-time
5. **Intervention** — When agent gets stuck (bad edit loop, test it can't fix), user provides guidance. Every intervention is logged
6. **Result** — Working code, passing tests, clean CI, pushed to git — with full trace history

---

## Success Metrics

### MVP Hard Gate (All Required by Tuesday 11:59 PM)

- [ ] Agent runs in persistent loop accepting new instructions without restarting
- [ ] Surgical file editing via anchor-based replacement — targeted changes, not file rewrites
- [ ] Context injection functional — accepts injected context at runtime and uses it in generation
- [ ] Tracing enabled — at least 2 shared LangSmith trace links showing different execution paths
- [ ] PRESEARCH.md submitted with research notes and architecture artifacts
- [ ] Accessible via GitHub, runs locally
- [ ] CODEAGENT.md with Agent Architecture and File Editing Strategy sections complete

### Business Objectives

- **Immediate:** Pass MVP gate to continue in the Gauntlet program
- **Early Submission (Thursday):** Ship app rebuild complete, comparative analysis drafted, multi-agent coordination working
- **Final Submission (Sunday):** All deliverables complete — demo video, deployment, AI development log, cost analysis, social post

### Key Performance Indicators

| KPI | Target | Measurement |
|---|---|---|
| Surgical edit success rate | >90% first-attempt success | LangSmith traces: edit tool calls vs. retries |
| Agent loop stability | Runs 30+ minutes without crash | Manual observation + logs |
| Multi-agent task completion | 2+ agents coordinate on a single task | LangSmith trace showing parallel agent execution |
| Trace completeness | Every agent action visible in trace | LangSmith trace link review |
| Human intervention rate | Document every intervention | Rebuild log entries |

---

## MVP Scope

### Core Features (Must Have for Tuesday)

1. **Persistent Agent Loop** — FastAPI server (or simple CLI loop) that accepts instructions continuously without restarting. LangGraph state checkpointing to survive restarts.
2. **Tool Definitions** — `read_file`, `edit_file` (anchor-based exact string replacement), `write_file`, `glob`, `grep`, `bash` — wired as Claude tool-use functions via the Anthropic SDK
3. **Surgical File Editing** — `edit_file(path, old_string, new_string)` implementation. Fails on no-match or non-unique match. Returns error with match count for LLM self-correction.
4. **Context Injection** — Layer 1 (always-present role/conventions), Layer 2 (task-specific specs/files passed with instruction). Agent uses injected context in its reasoning and generation.
5. **Multi-Agent Coordination** — At minimum: spawn 2 agents that work on related tasks and produce merged output. File-based communication.
6. **LangSmith Tracing** — Environment variables set, LangGraph auto-traces all nodes. Produce 2 shareable trace links showing different execution paths.
7. **CODEAGENT.md** — Agent Architecture section + File Editing Strategy section completed.

### Out of Scope for MVP

- Ship app rebuild (Early Submission)
- Comparative analysis (Final Submission)
- Deployment to cloud hosting (Final Submission)
- Demo video (Final Submission)
- AI Cost Analysis document (Final Submission)
- Full TDD pipeline with Test/Review/Architect agents (nice-to-have for MVP, required for Early)
- Git integration within the agent loop (can be manual for MVP)

### MVP Success Criteria

- Another engineer can clone the repo, follow the README, and have the agent running locally in under 10 minutes
- Agent accepts an instruction, reads relevant files, makes a surgical edit, and the edit is correct
- Agent accepts a second instruction without restarting
- Context injection demonstrably changes agent behavior (same instruction, different context → different output)
- 2 LangSmith trace links show distinct execution paths

### Future Vision

- **Early Submission:** Full TDD pipeline (Test Agent → Dev Agent → Review Agents → Architect → Fix Dev), Ship app rebuilt from scratch by the agent, multi-agent coordination with parallel review
- **Final Submission:** Cloud deployment, demo video, comparative analysis, cost analysis, AI development log
- **Beyond:** Reusable autonomous coding agent framework that can be pointed at any project — configurable agent roles, pluggable tool sets, project-specific conventions injected via context

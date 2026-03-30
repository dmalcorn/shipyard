# Shipyard Software Factory - First Full Run Summary

**Date:** March 28-29, 2026
**Product Built:** CMO Go For Achievement (CMOgfa) - a project management web application with Go backend and React frontend
**Pipeline:** Shipyard rebuild pipeline running in Docker on a local Windows machine, with Claude AI agents executing each story

---

## High-Level Results

| Metric | Value |
|--------|-------|
| Total stories completed | **40 of 40** |
| Total epics | **9** |
| Total wall-clock time (pipeline running) | **28h 35m** |
| Gap between runs (fixing credits + restart issues) | **~3 hours** |
| Total elapsed time (start to finish) | **~31.5 hours** |
| Total API cost | **$495.36** |
| Average cost per story | **$12.08** |
| Total agent invocations | **225** |
| Total agent turns | **10,793** |
| Total log events recorded | **34,827** |

---

## The Two Runs

### Run 1: Initial Start (failed - prepaid credit card exhausted)

| | |
|---|---|
| **Start** | March 28, 2026 12:30 AM CDT (05:30 UTC) |
| **End** | March 28, 2026 7:19 AM CDT (12:19 UTC) |
| **Duration** | 6 hours 48 minutes |
| **Stories completed** | 12 (stories 1-1 through 2-7) |
| **Epics completed** | 2 of 9 (Epic 1 and Epic 2) |
| **API cost** | $71.56 |
| **Agent invocations** | 59 |
| **Log events** | 6,648 |

The run was stopped when the Anthropic API prepaid credit balance was exhausted. All code from the completed stories was safely committed to git.

### Downtime (~3 hours)

Resolving the credit issue and dealing with a corrupted checkpoint file (caused by an accidental non-resume restart) took approximately 3 hours. See `process_failure_analysis.md` for details.

### Run 2: Resume (successful completion)

| | |
|---|---|
| **Start** | March 28, 2026 10:24 AM CDT (15:24 UTC) |
| **End** | March 29, 2026 8:11 AM CDT (13:11 UTC) |
| **Duration** | 21 hours 46 minutes |
| **Stories completed** | 29 (story 2-7 re-done, then 3-1 through 9-2) |
| **Epics completed** | 7 remaining (Epics 3 through 9), plus re-doing story 2-7 |
| **API cost** | $423.80 |
| **Agent invocations** | 166 |
| **Log events** | 28,179 |

The pipeline's final log entry: *"Rebuild completed: 40/40 stories completed in 1306.8 minutes"*

---

## Epic Breakdown

| Epic | Description | Stories | Wall-Clock Time | API Cost |
|------|-------------|---------|----------------|----------|
| 1 | Project Foundation & CI Scaffold | 5 | 3h 01m | $34.66 |
| 2 | Authentication & Workspace Management | 7 | 4h 36m* | $53.32* |
| 3 | Programs & Projects | 5 | 4h 16m | $78.02 |
| 4 | Issues & Sprint Planning | 6 | 4h 16m | $85.80 |
| 5 | Wiki & Rich Text Editing | 3 | 2h 11m | $40.58 |
| 6 | Navigation, Search & My Work | 4 | 2h 15m | $39.14 |
| 7 | Audit Trail & History | 2 | 1h 28m | $31.72 |
| 8 | Accountability Cycle | 6 | 4h 31m | $98.04 |
| 9 | Seed Data & Migration | 2 | 1h 56m | $34.07 |

*\*Epic 2 spans both runs: stories 2-1 through 2-6 in Run 1, story 2-7 re-done in Run 2.*

---

## Story-by-Story Detail

Each story goes through a multi-agent loop: **create_story** (spec writing) -> **testarch-atdd** (acceptance test generation) -> **dev-story** (implementation) -> **dev** (fix-up passes) -> **code-review** -> **architect review** -> CI verification.

### Run 1 Stories

| Story | Duration | Cost | Turns |
|-------|----------|------|-------|
| 1-1: Go Backend Project Scaffold | 24m 01s | $4.45 | 227 |
| 1-2: React Frontend Project Scaffold | 26m 38s | $5.06 | 221 |
| 1-3: Database & Migration Setup | 55m 35s | $9.54 | 312 |
| 1-4: CI Pipeline & Quality Gates | 24m 31s | $4.25 | 176 |
| 1-5: Dev Environment & Docker Compose | 50m 41s | $11.36 | 422 |
| 2-1: User Registration & Login | 37m 02s | $6.04 | 221 |
| 2-2: Session Management | 40m 57s | $8.87 | 210 |
| 2-3: Workspace CRUD | 32m 07s | $4.80 | 179 |
| 2-4: Workspace Membership | 38m 13s | $4.88 | 163 |
| 2-5: Role-Based Access Control | 32m 34s | $3.38 | 127 |
| 2-6: Workspace Settings UI | 35m 25s | $7.42 | 178 |
| 2-7: Invitation System | 9m 59s | $1.52 | 59 |

### Run 2 Stories

| Story | Duration | Cost | Turns |
|-------|----------|------|-------|
| 2-7: Invitation System (re-run) | 49m 32s | $16.41 | 346 |
| 3-1: Program CRUD | 1h 01m | $14.04 | 270 |
| 3-2: Project CRUD & ICE Scoring | 27m 38s | $8.83 | 217 |
| 3-3: Project-Program Linking | 27m 07s | $7.96 | 189 |
| 3-4: Lifecycle State Machine | 29m 52s | $10.61 | 237 |
| 3-5: Hypothesis & ICE Dashboard | 1h 50m | $36.59 | 573 |
| 4-1: Issue CRUD & Types | 40m 36s | $14.14 | 363 |
| 4-2: Issue-Project Assignment | 29m 22s | $9.69 | 216 |
| 4-3: Sprint CRUD | 37m 33s | $12.30 | 239 |
| 4-4: Sprint Board View | 46m 15s | $12.69 | 271 |
| 4-5: Drag-and-Drop Kanban | 33m 27s | $9.94 | 219 |
| 4-6: Sprint Planning Workflow | 1h 09m | $27.04 | 507 |
| 5-1: Wiki Page CRUD | 34m 22s | $11.05 | 217 |
| 5-2: Rich Text Editor | 39m 02s | $10.59 | 237 |
| 5-3: Wiki Tree Navigation | 58m 05s | $18.94 | 467 |
| 6-1: Global Navigation | 28m 51s | $7.18 | 186 |
| 6-2: Full-Text Search | 27m 58s | $7.06 | 189 |
| 6-3: My Work Dashboard | 34m 23s | $12.11 | 207 |
| 6-4: Notification System | 44m 26s | $12.80 | 337 |
| 7-1: Document History Tracking | 40m 15s | $16.02 | 266 |
| 7-2: Audit Log Viewer | 48m 40s | $15.70 | 370 |
| 8-1: Standup Entry & View | 41m 15s | $15.89 | 261 |
| 8-2: Weekly Plan CRUD | 36m 52s | $13.59 | 263 |
| 8-3: Weekly Retrospective | 37m 24s | $10.05 | 168 |
| 8-4: Manager Review & OPM Rating | 38m 56s | $9.22 | 178 |
| 8-5: Approval Workflow | 33m 03s | $12.47 | 261 |
| 8-6: Accountability Dashboard | 1h 23m | $36.80 | 427 |
| 9-1: Seed Data & ETL Tool | 43m 11s | $14.64 | 253 |
| 9-2: Data Validation & Integrity | 1h 13m | $19.43 | 364 |

---

## Story Duration Statistics

| Metric | Value |
|--------|-------|
| Average story duration | **41m 49s** |
| Median story duration | **37m 33s** |
| Shortest story | **9m 59s** (story 2-7, Run 1 - cut short by credit exhaustion) |
| Longest story | **1h 50m** (story 3-5: Hypothesis & ICE Dashboard) |
| Average cost per story | **$12.08** |

---

## Agent Workload Breakdown

The pipeline orchestrates multiple specialized AI agents per story. Here is how the work was distributed across all 225 agent invocations:

| Agent | Invocations | Total Cost | Total Turns | Avg Time/Call |
|-------|-------------|-----------|-------------|---------------|
| bmad-dev (fix-up & CI repair) | 53 | $142.59 | 2,872 | 9m 13s |
| bmad-dev-story (implementation) | 44 | $151.42 | 3,120 | 13m 24s |
| bmad-testarch-atdd (test generation) | 42 | $92.07 | 1,847 | 8m 18s |
| bmad-create-story (spec writing) | 41 | $48.18 | 1,535 | 4m 58s |
| fix-cat-a (category A fix agent) | 10 | $23.30 | 577 | 6m 28s |
| bmad-code-review | 8 | $15.64 | 292 | 4m 42s |
| claude-review | 8 | $12.54 | 332 | 5m 04s |
| architect (epic review) | 9 | $4.71 | 135 | 2m 24s |
| analyze-reviews | 9 | $4.64 | 67 | 3m 06s |
| fix-architect | 1 | $0.25 | 16 | 1m 05s |

**Most expensive phase:** Implementation (bmad-dev-story) at $151.42 total, averaging $3.44 per story.
**Most frequently called:** Fix-up agent (bmad-dev) with 53 invocations, reflecting the iterative fix/verify cycle.

---

## Reliability

- **Zero failed agent invocations** across both runs (all 225 returned `RESULT: success`)
- CI retries were needed occasionally (the pipeline allows up to 4 CI attempts per checkpoint); most passed on attempt 1 or 2
- The only pipeline-level failure was the external credit exhaustion, not an agent or code failure

---

## Cost Analysis

| Category | Amount | % of Total |
|----------|--------|-----------|
| Implementation (dev-story + dev) | $294.01 | 59.4% |
| Test generation (testarch-atdd) | $92.07 | 18.6% |
| Story spec creation | $48.18 | 9.7% |
| Code review & architecture review | $37.53 | 7.6% |
| Fix agents (cat-a, fix-architect) | $23.55 | 4.8% |
| **Total** | **$495.36** | **100%** |

**Effective rate:** $495.36 for a 40-story, 9-epic full-stack web application built from planning artifacts to working code in ~29 hours of pipeline time.

---

## Key Observations

1. **Consistency:** The median story time (37m 33s) is close to the average (41m 49s), indicating a fairly predictable per-story cadence. Most stories fall in the 25-50 minute range.

2. **Outliers:** The longest stories (3-5 at 1h 50m, 8-6 at 1h 23m, 9-2 at 1h 13m) all involve dashboard/reporting features with complex UI and data aggregation - these are genuinely harder stories.

3. **Later epics cost more per story:** Epic 8 (Accountability Cycle) averaged $16.34/story vs Epic 1 (Foundation) at $6.93/story. As the codebase grows, agents need more context and the integration surface area increases.

4. **Implementation dominates cost:** Nearly 60% of the total spend goes to the dev-story and dev agents. Test generation is a distant second at 18.6%.

5. **The pipeline is self-correcting:** With zero failed invocations and only occasional CI retries, the multi-agent loop (implement -> test -> review -> fix) is effective at converging to passing code.

6. **Fully autonomous:** Once started, the pipeline required zero human intervention during either run. The only stop was an external billing constraint, not a pipeline failure.

---

*Raw log data preserved in `gauntlet_docs/retrospective/` for deeper analysis.*
*Log extraction method documented in `gauntlet_docs/How-to-extract-db-logs.md`.*

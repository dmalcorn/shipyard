# Story 5.1: Comparative Analysis (7 Sections)

Status: ready-for-dev

## Story

As an evaluator,
I want a structured written analysis comparing the agent-built Ship app against the original,
so that I can assess the quality of the agent's output with specific evidence.

## Acceptance Criteria

1. **Given** the Ship rebuild is complete with intervention log data **When** the comparative analysis is written **Then** it contains all 7 required sections: Executive Summary, Architectural Comparison, Performance Benchmarks, Shortcomings, Advances, Trade-off Analysis, If You Built It Again
2. **Given** each section **When** reviewed **Then** it contains specific claims backed by evidence from the rebuild log — no vague summaries

## Tasks / Subtasks

- [ ] Task 1: Gather source data for the analysis (AC: #1, #2)
  - [ ] Read the intervention log from `{target_dir}/intervention-log.md` (produced by Story 4.3's `InterventionLogger`)
  - [ ] Read the rebuild session audit logs from `logs/session-*.md` (produced by Story 2.2's `AuditLogger`)
  - [ ] Read the original Ship app source (provided as specs in Story 4.1)
  - [ ] Read the agent-rebuilt Ship app source in `{target_dir}/`
  - [ ] Extract `InterventionLogger.export_for_analysis()` output — structured summary of interventions by phase, limitation categories, auto-recovery rate
- [ ] Task 2: Write Section 1 — Executive Summary (AC: #1, #2)
  - [ ] High-level summary of what was rebuilt, how long it took, and the overall quality assessment
  - [ ] Key metrics: total stories completed, intervention count, auto-recovery count, completion rate
  - [ ] One-paragraph verdict on whether the agent-built version is functionally equivalent
- [ ] Task 3: Write Section 2 — Architectural Comparison (AC: #1, #2)
  - [ ] Compare the original Ship app's architecture to the agent-rebuilt version
  - [ ] Identify structural differences: file organization, module boundaries, naming conventions
  - [ ] Note where the agent followed the spec faithfully vs where it diverged and why
  - [ ] Reference specific files and code patterns as evidence
- [ ] Task 4: Write Section 3 — Performance Benchmarks (AC: #1, #2)
  - [ ] Define measurable comparison points: build time, test pass rate, code size (LOC), dependency count
  - [ ] Compare agent development speed (wall-clock time per story) vs estimated manual effort
  - [ ] Token cost per story/epic as a proxy for computational effort
  - [ ] If applicable, runtime performance comparison (response times, resource usage)
- [ ] Task 5: Write Section 4 — Shortcomings (AC: #1, #2)
  - [ ] Catalog every agent limitation discovered during the rebuild, sourced from intervention log entries
  - [ ] Group by category: context window limits, cross-module reasoning, test-code dependency ordering, style/convention drift, etc.
  - [ ] For each shortcoming, cite the specific intervention entry that revealed it
  - [ ] Assess severity: which shortcomings are blockers vs annoyances
- [ ] Task 6: Write Section 5 — Advances (AC: #1, #2)
  - [ ] Catalog what the agent did well, sourced from auto-recovery entries and successful pipeline runs
  - [ ] Highlight cases where the agent produced code that was arguably better than a manual approach
  - [ ] Note speed advantages: stories that completed autonomously without intervention
  - [ ] Identify patterns the agent excelled at (e.g., boilerplate generation, test scaffolding, consistent style)
- [ ] Task 7: Write Section 6 — Trade-off Analysis (AC: #1, #2)
  - [ ] Token cost vs manual developer time
  - [ ] Agent consistency (follows conventions perfectly) vs flexibility (struggles with ambiguous specs)
  - [ ] Speed of generation vs quality of output (did fast stories have more issues?)
  - [ ] Autonomy level: what percentage of work required zero intervention?
  - [ ] When is agent-assisted development worth it vs pure manual development?
- [ ] Task 8: Write Section 7 — If You Built It Again (AC: #1, #2)
  - [ ] Retrospective: what would change about the agent's architecture based on rebuild lessons
  - [ ] Prompt engineering improvements: which agent prompts needed the most iteration?
  - [ ] Pipeline improvements: which pipeline phases caused the most friction?
  - [ ] Tool improvements: did any tools need changes during the rebuild?
  - [ ] Scope decisions: which features are genuinely agent-appropriate vs better done manually?
- [ ] Task 9: Assemble the final document (AC: #1)
  - [ ] Output file: `docs/comparative-analysis.md`
  - [ ] Ensure all 7 sections are present and clearly headed
  - [ ] Verify every claim has a specific evidence citation (intervention log entry #, audit log session, file path, or metric)
  - [ ] Add a References section linking to source artifacts

## Dev Notes

- **This is a writing/analysis story, not a code story.** The output is a markdown document, not source code. The dev agent should use `read_file` to gather data and `write_file` to produce the final document.
- **Primary data source is the intervention log** from Story 4.3 (`{target_dir}/intervention-log.md`). The `export_for_analysis()` method provides a pre-structured summary. Use it as the backbone, then enrich with specific examples.
- **Auto-recovery entries are critical.** They provide the positive evidence for the Advances section. Without them, the analysis becomes a one-sided list of failures.
- **No vague summaries.** The acceptance criteria explicitly require "specific claims backed by evidence." Every shortcoming must cite an intervention entry. Every advance must cite a successful run or auto-recovery. The evaluator will check this.
- **Output location:** `docs/comparative-analysis.md` — this is a deliverable document, not a runtime artifact. It also feeds into CODEAGENT.md (Story 5.4).
- **FR9 compliance:** This story directly satisfies FR9 in the requirements. The 7 sections are non-negotiable — all must be present.

### Dependencies

- **Requires:** Story 4.2 (Autonomous Ship Rebuild Execution) — the rebuild must be complete to have data
- **Requires:** Story 4.3 (Rebuild Intervention Log) — the intervention log is the primary data source
- **Requires:** Story 2.2 (Markdown Audit Logger) — session logs provide supplementary data
- **Feeds into:** Story 5.4 (CODEAGENT.md Final Sections) — the comparative analysis is embedded in CODEAGENT.md

### Previous Story Intelligence

- Story 4.3 defined `InterventionEntry` with fields: `timestamp`, `epic`, `story`, `pipeline_phase`, `failure_report`, `what_broke`, `what_developer_did`, `agent_limitation`, `retry_counts`, `files_involved`. These fields map directly to the evidence citations needed in this analysis.
- `InterventionLogger.export_for_analysis()` returns: intervention frequency by phase, categories of agent limitations, auto-recovery success rate, and specific examples per category. This is the structured backbone for Sections 4 (Shortcomings), 5 (Advances), and 6 (Trade-offs).
- The audit logs at `logs/session-{id}.md` (Story 2.2) contain per-session metrics: agents invoked, scripts run, files touched. Use these for the Performance Benchmarks section.

### Project Structure Notes

- Output: `docs/comparative-analysis.md`
- Source data: `{target_dir}/intervention-log.md`, `logs/session-*.md`, `{target_dir}/` (rebuilt app)
- This document is referenced by CODEAGENT.md in Story 5.4

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 5.1 — acceptance criteria and 7-section requirement]
- [Source: _bmad-output/planning-artifacts/epics.md#FR9 — Comparative Analysis requirement]
- [Source: _bmad-output/implementation-artifacts/4-3-rebuild-intervention-log.md — InterventionLogger API and log format]
- [Source: _bmad-output/implementation-artifacts/2-2-markdown-audit-logger.md — AuditLogger session log format]
- [Source: CODEAGENT.md#Comparative Analysis — placeholder section to be filled by Story 5.4]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

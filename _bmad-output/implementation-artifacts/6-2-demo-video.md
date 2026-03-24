# Story 6.2: Demo Video

Status: ready-for-dev

## Story

As an evaluator,
I want a 3-5 minute demo video showing the agent in action,
so that I can see surgical editing, multi-agent coordination, and Ship rebuild without running anything myself.

## Acceptance Criteria

1. **Given** the agent is functional **When** the demo video is recorded **Then** it shows: the agent making a surgical edit, completing a multi-agent task, and at least one example from the Ship rebuild
2. **Given** the video **When** reviewed **Then** it is 3-5 minutes long and clearly demonstrates the agent's key capabilities

## Tasks / Subtasks

- [ ] Task 1: Plan the demo script and flow (AC: #1, #2)
  - [ ] Outline 3-4 demo segments that fit within 3-5 minutes total
  - [ ] Segment 1: Surgical edit — show the agent receiving an `/instruct` request to make a targeted code change, executing it via `edit_file`, and verifying with tests
  - [ ] Segment 2: Multi-agent task — show the orchestrator spawning multiple agent roles (e.g., coder + reviewer + architect) for a TDD pipeline run
  - [ ] Segment 3: Ship rebuild excerpt — show at least one story from the autonomous rebuild executing, including intervention log entries if applicable
  - [ ] Optional Segment 4: Brief walkthrough of LangSmith traces and audit logs for observability
  - [ ] Time each segment to ensure total stays within 3-5 minutes
- [ ] Task 2: Prepare the demo environment (AC: #1)
  - [ ] Ensure the agent is running (locally or deployed) with all tools functional
  - [ ] Prepare a clean target repo or use the Ship app repo in a known state
  - [ ] Pre-stage any tasks or prompts to avoid dead time during recording
  - [ ] Verify LangSmith dashboard is accessible for the observability segment (if included)
- [ ] Task 3: Record the demo video (AC: #1, #2)
  - [ ] Use screen recording software (OBS, Loom, or equivalent)
  - [ ] Record each segment, using the planned script
  - [ ] Include brief narration or text overlays explaining what the agent is doing at each step
  - [ ] Show terminal output, API responses, and/or the deployed UI as appropriate
- [ ] Task 4: Edit and finalize the video (AC: #2)
  - [ ] Trim dead time, errors, or retakes
  - [ ] Add title card with project name ("Shipyard") and a brief description
  - [ ] Verify final runtime is 3-5 minutes
  - [ ] Export in a standard format (MP4, 1080p recommended)
- [ ] Task 5: Make the video accessible (AC: #1, #2)
  - [ ] Upload to YouTube (unlisted or public), Loom, or equivalent hosting
  - [ ] Add the video URL to README.md
  - [ ] Ensure the video link works without authentication

## Dev Notes

- **This is a recording/production story, not a code story.** The deliverable is a video file/URL, not source code. The dev agent cannot record video — this story requires human execution with the agent running in the background.
- **Three required demo segments are non-negotiable:** (1) surgical edit, (2) multi-agent task, (3) Ship rebuild example. All three must appear in the video per FR12.
- **Keep it tight.** 3-5 minutes means no lengthy setup or explanation. Jump straight into the action. Use text overlays or brief voiceover to provide context.
- **Pre-stage everything.** The demo should show the agent working, not the human configuring the environment. Have tasks ready to go before hitting record.
- **FR12 compliance:** This story directly satisfies FR12 — "3-5 min showing agent making a surgical edit, completing a multi-agent task, and at least one Ship rebuild example."

### Dependencies

- **Requires:** Story 1.6 (Persistent Server + CLI Entry Point) — the agent must be running
- **Requires:** Story 3.5 (Full TDD Orchestrator Pipeline) — multi-agent coordination must be functional for the demo
- **Requires:** Story 4.2 (Autonomous Ship Rebuild Execution) — Ship rebuild must be complete for demo footage
- **Requires:** Story 6.1 (Cloud Deployment) — ideally demo against the deployed instance, but local is acceptable

### Previous Story Intelligence

- Story 1.6 established the `/instruct` endpoint for submitting tasks to the agent.
- Story 3.5 built the full TDD orchestrator pipeline with coder, reviewer, and architect roles — this is the multi-agent task to demo.
- Story 4.2 produced the autonomous Ship rebuild — the intervention log and session audit logs provide narrative material for the demo.
- Story 2.1 set up LangSmith tracing — the trace dashboard can provide a visual "under the hood" view.

### Project Structure Notes

- Video output: uploaded to external hosting (YouTube/Loom), linked in README.md
- Demo runs against: deployed agent (Story 6.1) or local `docker compose up`
- Key endpoints to demo: `POST /instruct`, LangSmith dashboard, audit logs at `logs/`

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 6.2 — acceptance criteria]
- [Source: _bmad-output/planning-artifacts/epics.md#FR12 — Demo Video requirement]
- [Source: _bmad-output/implementation-artifacts/1-6-persistent-server-cli-entry-point.md — /instruct endpoint]
- [Source: _bmad-output/implementation-artifacts/3-5-full-tdd-orchestrator-pipeline.md — multi-agent pipeline]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

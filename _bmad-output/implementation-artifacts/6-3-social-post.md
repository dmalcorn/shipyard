# Story 6.3: Social Post

Status: ready-for-dev

## Story

As the Gauntlet program,
I want a social media post about Shipyard on X or LinkedIn,
so that the project gets visibility and demonstrates communication skills.

## Acceptance Criteria

1. **Given** the project is complete **When** a post is published on X or LinkedIn **Then** it includes: project description, key features, demo or screenshots, and tags @GauntletAI

## Tasks / Subtasks

- [ ] Task 1: Draft the social post content (AC: #1)
  - [ ] Write a concise project description: what Shipyard is and what it does (AI-powered coding agent built with LangGraph)
  - [ ] Highlight 2-3 key features: surgical code editing, multi-agent orchestration (TDD pipeline), autonomous app rebuild
  - [ ] Include a call to action or link to the live deployment (Story 6.1) and/or demo video (Story 6.2)
  - [ ] Tag @GauntletAI as required
  - [ ] Keep within platform character limits (280 chars for X main post, or use thread; LinkedIn is more flexible)
- [ ] Task 2: Prepare visual assets (AC: #1)
  - [ ] Take screenshots of: the agent processing a task (terminal or API response), LangSmith trace view, the deployed Ship app
  - [ ] Alternatively, use a short clip or GIF from the demo video
  - [ ] Ensure images are clear and readable at social media resolution
- [ ] Task 3: Choose platform and publish (AC: #1)
  - [ ] Select X or LinkedIn (or both)
  - [ ] Attach visual assets to the post
  - [ ] Publish the post
  - [ ] Save the post URL
- [ ] Task 4: Document the post (AC: #1)
  - [ ] Add the published post URL to README.md or a project deliverables section
  - [ ] Take a screenshot of the live post as a backup record

## Dev Notes

- **This is a content/marketing story, not a code story.** The deliverable is a published social media post with a URL. The dev agent cannot publish social media posts — this story requires human execution.
- **All four elements are required:** project description, key features, demo or screenshots, and @GauntletAI tag. Missing any one of these fails the acceptance criteria.
- **Timing matters.** Publish after the demo video and deployment are live so the post can link to them. This should be one of the last tasks completed.
- **FR14 compliance:** This story directly satisfies FR14 — "X or LinkedIn post with description, features, demo/screenshots, tag @GauntletAI."

### Dependencies

- **Requires:** Story 6.1 (Cloud Deployment) — need the live URLs to link in the post
- **Requires:** Story 6.2 (Demo Video) — need the video link or screenshots from it
- **Should follow:** All other epics complete — the post describes the finished project

### Previous Story Intelligence

- Story 6.1 produces the public URLs for the agent and Ship app — these are the links to include in the post.
- Story 6.2 produces the demo video — a clip, GIF, or link from it serves as the visual asset.
- The product brief describes Shipyard as: "an AI-powered software development agent that can understand, modify, and test code repositories using LangGraph for agent orchestration."

### Project Structure Notes

- No code artifacts produced by this story
- Post URL should be added to README.md
- Visual assets (screenshots) can be stored in `docs/` if needed for the project record

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 6.3 — acceptance criteria]
- [Source: _bmad-output/planning-artifacts/epics.md#FR14 — Social Post requirement]
- [Source: _bmad-output/planning-artifacts/product-brief-shipyard-2026-03-23.md — project description for post content]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

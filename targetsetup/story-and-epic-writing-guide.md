# Story and Epic Writing Guide (Target Template)

This document describes how `epics.md` and the planning artifacts under `_bmad-output/planning-artifacts/` should be structured for the Shipyard factory to build a project successfully. It is the human-authored input to the factory; the BMAD dev agent reads each story and produces the code that satisfies it.

This is a copy-into-target template. Place it at `_bmad-output/planning-artifacts/story-and-epic-writing-guide.md` before authoring `epics.md` and reference it when reviewing the spec for completeness.

## Why this matters

The single largest predictor of a successful factory build is **the quality of `epics.md`**. The chat2diagram run (April 2026) hit two stories that failed exactly because their acceptance criteria were under-specified at the cross-cutting level:

- **Story 13-2** (Interview Exclusion) added 4 columns to the `interview_sessions` table. Its acceptance criteria didn't mention test mocks anywhere else in the codebase — but every test that constructed an `InterviewSession` fixture broke on `tsc --noEmit`. The fix_ci agent burned 4 cycles trying to satisfy the story's own ACs while the wider codebase was failing to typecheck.
- **Story 13-6** (Identity Verification) added `interviewSecurity` (a JSONB column on `projects`). Same pattern: every project-mock in the test suite fell over on a global typecheck. The story's ACs didn't anticipate the cascade.

Both stories were code-correct in their primary scope. They failed the global pipeline because the **planning** did not name "every project-shaped mock in the test suite" as something the implementation must touch. **A better-written story would have said so**, and the dev agent would have done the cascade fix in the same pass.

This guide is how to write stories that don't have those gaps.

## Core principle: vertical slices

**Every story spans the full stack.** Acceptance criteria verify end-to-end behavior, not layer-internal correctness. A story that says "the user can log in" must specify what happens at every layer: the frontend form, the API endpoint, the database session, the redirect on success, the error path on failure.

Why vertical slices win:

- The factory commits, pushes, and (optionally) deploys after each story. If a story is purely backend, the operator can't _test_ it until later stories provide the UI. By that time, ten more stories have landed and the integration mess is unrecoverable.
- AI-generated code is most reliable when the AC is concrete and testable end-to-end. Vague ACs ("the user can authenticate") leave too much room for the agent to interpret — vertical-slice ACs leave none.
- The factory's epic-review chain works _across_ the stack; reviews look at how stories integrate. Horizontal slices defeat that — Epic 1 is "all backend, no frontend yet" so there's nothing to review.

**Anti-pattern**: "Build all the User models" as Story 1.1. **Better**: "User Authentication: Story 1.1 covers Django User model, DRF login endpoint, frontend login form, session establishment, and integration test that exercises all four."

## Story anatomy

Every story should have these sections:

```markdown
### Story X.Y: <Short Descriptive Title>

**Status:** ready-for-dev | review | done
**Epic:** <epic number> — <epic name>
**Story Key:** X-Y-<kebab-case-slug>
**Components:** [backend] [frontend] [integration] (use [tags])

## Story

As a <user role>,
I want to <capability>,
So that <user value>.

## Acceptance Criteria

**Given** <precondition>
**When** <action>
**Then** <observable outcome>
**And** <additional outcome>

(Repeat the Given/When/Then block for each scenario, including edge cases and error paths)

## Files Likely Touched

- `backend/apps/auth/models.py` — User model additions
- `backend/apps/auth/views.py` — login/logout endpoints
- `backend/apps/auth/tests/test_login.py` — backend tests
- `frontend/src/app/login/page.tsx` — login UI
- `frontend/src/app/login/page.test.tsx` — frontend test
- `frontend/src/lib/api/auth.ts` — API client
- (etc.)

## Cross-cutting Considerations

(Anything that touches files outside this story's primary scope)

- Adding a User type field requires updating User mocks in: <list test files>
- Adding a new auth route requires updating: <list of router files>

## References

- FR-1.2 (PRD)
- ARCH-Auth-Section-3 (architecture.md)
- UX-DR42 (UX design)
```

The `Cross-cutting Considerations` section is the most important and the most often missed. It is what would have prevented chat2diagram's 13-2/13-6 cascade. Authors should ask: "what shared types, mocks, fixtures, or generated code does this story's change ripple into?" — and list them, even if the answer feels obvious.

## Acceptance criteria conventions

Use **Given/When/Then** format consistently. It forces concreteness:

- **DON'T**: "The user can log in." (vague — what counts as login? what error states?)
- **DO**:
  - **Given** a user with email "alice@example.com" exists in the database
  - **When** the user submits the login form with that email and the correct password
  - **Then** a session cookie is set with `httpOnly` and `Secure` flags
  - **And** the user is redirected to `/dashboard`
  - **And** the response sets `X-Auth-Source: password` header (for audit)

Each "Given" scenario is one atomic behavior. Three scenarios with one Given each is better than one scenario with three Givens.

Acceptance criteria MUST cover:

- The happy path (one or more Given/When/Then blocks)
- Error paths the dev agent would otherwise have to invent (e.g., "what if the password is wrong?", "what if the email doesn't exist?")
- Cross-layer integration where applicable ("frontend posts to /api/login, backend validates, response sets cookie")
- The test the dev agent should write to verify the behavior — explicit acceptance criteria are testable acceptance criteria

## Multi-component stories

Projects spanning `backend/` + `frontend/` (or more) need explicit component tags so the dev agent knows what's involved.

**Pattern**: tag each story with the components it touches:

```markdown
### Story 1.4: Email Verification Flow

**Components:** [backend] [frontend] [email-service]
```

ACs for multi-component stories MUST verify integration, not just per-component behavior:

```markdown
**Given** an unverified user
**When** they request a new verification email via the frontend "Resend" button
**Then** the frontend POSTs to `/api/auth/verify/resend`
**And** the backend creates a one-time token (24-hour TTL)
**And** the email-service sends a verification email to the user's address
**And** clicking the link in the email POSTs to `/api/auth/verify/confirm` with the token
**And** the backend marks the user verified and redirects the frontend to `/dashboard`
```

Note that the AC traces the request across all three components. The dev agent gets a complete picture of what to implement.

## Story sequencing within an epic

A typical epic structure:

1. **Story X.1 — Spike or UX/Architecture pattern**. Doc-only or near-doc-only. Establishes the patterns for the rest of the epic. Examples:
   - "UX Compliance Spike — Login flow design and component conventions"
   - "Architecture decision — How sessions are managed across the stack"

2. **Stories X.2 through X.N — Code stories**. Each builds on the patterns from X.1 and previous stories. Vertical slices.

3. **Story X.M (last) — Integration / Polish**. Ties together loose ends, addresses cross-cutting concerns identified during the epic.

The rationale for X.1 being a spike: it's _cheap_ (CI passes in <2s with the doc-only short-circuit), and it forces the operator to make stack-wide decisions BEFORE any code is written. The chat2diagram run had X.1 spikes for every Phase 2 epic (12-1, 13-1, 14-1, 15-1, 16-1, 17-1) — they paid for themselves on every subsequent story by reducing churn.

## Spike stories — what they look like

A spike story is doc-only. Its sole deliverable is markdown updates to `_bmad-output/planning-artifacts/`:

```markdown
### Story 14-1: UX Compliance Spike — Skill Pack Cards, Docs Page Structure, API Key Management

**Status:** review (after dev agent completes)
**Epic:** 14 — Skill & API Extensibility
**Components:** [docs] (no code components)

## Story

As a designer,
I want to extend the UX Design Specification with patterns for skill pack cards, the docs page structure, and API key management,
So that subsequent stories in this epic have canonical UX references.

## Acceptance Criteria

**Given** the UX spec at `_bmad-output/planning-artifacts/ux-design-specification.md`
**When** this story completes
**Then** new UX-DR entries are added covering:

- Skill pack card layout (border, density, status badge)
- Docs page structure (left rail, content, right TOC)
- API key management (creation, revocation, fingerprint display)
  **And** each new UX-DR cites a UX-DR pattern number that the dev agent can reference in subsequent stories
  **And** the spec's table-of-contents is updated

## Files Likely Touched

- `_bmad-output/planning-artifacts/ux-design-specification.md` (modified)
- `_bmad-output/implementation-artifacts/14-1-...md` (new — story file)

## Cross-cutting Considerations

None — doc-only.
```

The CI script's Phase 0 short-circuit recognizes these immediately and exits 0 in <2 seconds.

## Anti-patterns (with chat2diagram receipts)

| Anti-pattern                                                       | Story it bit                                                                | Why it hurt                                                                       | Fix                                                                                                         |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Adding a required column to a shared type without naming all mocks | 13-2                                                                        | tsc --noEmit failed in 8+ unrelated test files                                    | Add a "Cross-cutting Considerations" section listing every mock factory or fixture that constructs the type |
| "User can authenticate" (vague AC)                                 | (averted in 17-2 by careful planning)                                       | Dev agent has to guess what counts as success                                     | Use Given/When/Then with explicit observable outcomes                                                       |
| Implicit dependency between stories                                | (sequential build assumed)                                                  | Story X.5 fails because Story X.3 didn't establish a pattern                      | Make dependencies explicit in the "References" section                                                      |
| Horizontal slicing ("all the models first")                        | (this is what the chat2diagram operator avoided by writing vertical slices) | Project isn't demoable until late epics                                           | Vertical slices, end-to-end ACs                                                                             |
| Story ACs that don't include tests                                 | (occasional in chat2diagram)                                                | Dev agent writes code but no tests; CI passes vacuously; integration breaks later | ACs must specify a test the dev agent will write                                                            |
| Spike story tagged as code story                                   | (averted with `[docs]` convention)                                          | CI runs full suite for a doc edit, costs 5+ min and risks timeout                 | Tag spike stories `[docs]` and use Phase 0 short-circuit                                                    |
| "We'll fix that in the next epic"                                  | (always tempting, never works)                                              | Bug accumulates, becomes unrecoverable mess                                       | If a story exposes a problem, fix it in this epic — even if a follow-up story is also needed                |

## Epic structure

An epic should:

1. **Have a clear demo at the end** — what does the operator see working that wasn't working before?
2. **Not gate on a future epic** — every epic must be useful when committed even if no further work happens
3. **Cover all stack layers** — typically 5-10 stories, each a vertical slice
4. **Start with a spike** (story X.1) for cross-cutting decisions, end with integration polish (story X.M)
5. **Have epic-level acceptance criteria** that the epic-review chain can verify across all stories

Example epic structure:

```markdown
## Epic 14: User Authentication

**Goal:** Operators can log in and authenticate API requests with session-based auth.

**Demo at end of epic:** Operator visits the deployed app, registers an account, logs in, makes an API call that requires auth, logs out. Every step works end-to-end.

### Story 14.1: UX Compliance Spike — Login/Registration Pages, Session Display

### Story 14.2: User Registration (Backend Model + DRF Endpoint + Frontend Form)

### Story 14.3: Login Endpoint + Frontend Form + Session Cookie Establishment

### Story 14.4: Authenticated API Middleware + Logout Endpoint + Session Display

### Story 14.5: Password Reset Flow (Email Token + Reset Page + Test)

### Story 14.6: Integration & E2E Tests for Auth Flow
```

Each story is a vertical slice. Story 14.1 is the spike. Story 14.6 is the integration sweep.

## How the bmad-pm and bmad-dev agents use this document

The bmad-pm agent (or the human PM) writing `epics.md` MUST:

- Match the story anatomy template (status, epic, components, story, ACs, files, cross-cutting, refs)
- Include `Cross-cutting Considerations` for every story that changes a shared type, schema, fixture, or generated artifact
- Use Given/When/Then for ACs
- Tag multi-component stories with `[backend]` `[frontend]` etc.
- Sequence stories so each epic ends in a demoable state

The bmad-dev agent reads the story for each implementation pass. Stories that follow this guide produce dramatically better code in fewer fix_ci cycles.

## How the operator validates `epics.md` before kickoff

1. Spot-check three randomly chosen stories:
   - Are ACs in Given/When/Then?
   - Is there a `Cross-cutting Considerations` section even if it says "None"?
   - Are component tags present?
2. Read the FIRST story of each epic. Is it a spike (doc-only)? If not, add one.
3. Read the LAST story of each epic. Does it tie integration together, or is it just one more feature?
4. Search for anti-patterns: any AC starting with "the user can" without specifying observable outcomes? Any story that says "fix in the next epic"?
5. Confirm that every epic ends in something demoable.

## Updating this guide

When a future build surfaces a new story-quality lesson worth carrying forward, update this document AND the bmad-pm agent's prompt that references it. Track the source of each lesson — "from chat2diagram's 13-2 incident" — so the lesson stays grounded.

## See also

- [factory-lessons-from-chat2diagram.md](../factory-lessons-from-chat2diagram.md) — the recovery patterns this guide is trying to prevent
- [ci-script-specification.md](ci-script-specification.md) — what CI must do to enforce these story patterns at build time
- [test-structure-guide.md](test-structure-guide.md) — how the tests that ACs reference should be organized
- BMAD epic + story templates that come bundled with the BMAD agents — these guide the _form_; this guide describes the _factory-friendly content_

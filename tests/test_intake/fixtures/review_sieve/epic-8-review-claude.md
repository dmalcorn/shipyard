I'll wait for the background agents to complete while also reading more files in parallel.
Continuing to read more files while waiting.
Continuing to read more files.
Continuing to read review/comparison API routes and UI components.
Reading the UI components while waiting.
Reading remaining files while waiting.
Reading the remaining process synthesis routes and implementation artifacts.
Reading the implementation artifacts while waiting for the other agents.
Reading the test files while waiting.
All background agents are running. Let me check on the completed ones.
The output files appear empty. Let me read the files directly instead.
Now I have enough to produce a thorough review. Let me also quickly check the approve route's double-update bug and the synthesis-state-machine TOCTOU issue.
I now have enough context from all the key files to produce a comprehensive review. Let me synthesize my findings.

---
agent_role: reviewer
task_id: epic-8-review
timestamp: 2026-04-12T18:45:00.000000+00:00
input_files: [src/app/api/auth/login/route.ts, src/app/api/auth/session/route.ts, src/app/api/projects/[projectId]/supervisors/route.ts, src/app/api/projects/[projectId]/supervisors/[supervisorId]/route.ts, src/app/api/projects/[projectId]/synthesis/approve/route.ts, src/app/api/projects/[projectId]/synthesis/review/comparison/route.ts, src/app/api/projects/[projectId]/synthesis/review/edits/route.ts, src/app/api/projects/[projectId]/synthesis/review/individuals/route.ts, src/app/api/projects/[projectId]/synthesis/review/messages/route.ts, src/app/api/projects/[projectId]/synthesis/status/route.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/review/route.ts, src/app/supervisor/projects/page.tsx, src/app/supervisor/projects/[projectId]/review/page.tsx, src/components/auth/login-form.tsx, src/components/project/supervisor-management.tsx, src/components/project/synthesis-status-panel.tsx, src/components/supervisor/project-list.tsx, src/components/synthesis/approval-controls.tsx, src/components/synthesis/comparison-view.tsx, src/components/synthesis/edit-history.tsx, src/components/synthesis/individual-carousel.tsx, src/components/synthesis/review-agent-panel.tsx, src/components/synthesis/review-summary.tsx, src/components/synthesis/status-indicator.tsx, src/lib/auth/middleware.ts, src/lib/auth/session.ts, src/lib/db/queries/individual-process-schemas.ts, src/lib/db/queries/revision-requests.ts, src/lib/db/queries/supervisors.ts, src/lib/db/queries/synthesis-edits.ts, src/lib/db/queries/synthesis-results.ts, src/lib/db/schema.ts, src/lib/schema/api-requests.ts, src/lib/synthesis/review-agent.ts, src/lib/synthesis/synthesis-state-machine.ts]
reviewer_type: claude
review_scope: epic

---

# Epic Code Review — CLAUDE Reviewer

## Summary

Epic 8 implements supervisor authentication, individual diagram carousel, comparison view, conversational review agent, approval/revision flow, and synthesis state machine extensions. The architecture is coherent and the security model is sound overall, but there are several critical correctness bugs — most seriously a double-write in the approve transaction and an unauthorized state-machine access in `withSupervisorProjectAccess` that uses the supervisor's own row ID as the project-membership key — plus a cluster of major issues around error handling, duplicate code, and spec gaps.

---

## Findings

### 1. Approve route performs redundant double-write outside transaction — approve path
- **File:** `src/app/api/projects/[projectId]/synthesis/approve/route.ts:64–76`
- **Issue:** The `approve` branch calls `transitionSynthesisStatus(resultId, "in_review", "approved", tx)` inside a `db.transaction()`, which already `UPDATE`s the `status` column (line 68–70 in `synthesis-state-machine.ts`). The very next line then calls `updateSynthesisResultStatus(resultId, "approved", { approvedAt, approvedBy })` **outside the transaction scope** (it constructs its own `db.update()` against the non-`tx` `db` instance). This means `approvedAt` and `approvedBy` are set in a separate, non-atomic update that can fail silently after the status transition already committed, leaving the row with `status = "approved"` but `approvedAt = null` and `approvedBy = null`.
- **Severity:** critical
- **Action:** Pass `tx` as a parameter to `updateSynthesisResultStatus`, or consolidate by having `transitionSynthesisStatus` accept an optional `{ approvedAt, approvedBy }` options map. Remove the standalone `updateSynthesisResultStatus` call and include the approval metadata inside the single `tx.update()`.

---

### 2. `withSupervisorProjectAccess` uses `session.userId` (supervisorId) as the project-membership lookup key — but login stores `supervisor.supervisorId` as `userId`
- **File:** `src/lib/auth/middleware.ts:101–104`, `src/app/api/auth/login/route.ts:95`
- **Issue:** The login route stores `supervisor.supervisorId` as the session's `userId` field (`createSession(supervisor.supervisorId, ...)`). The middleware then calls `findSupervisorByProjectAndId(projectId, session.userId)`, which queries `supervisorId = session.userId`. This is **actually correct** — but it is fragile and undocumented. The concern is that `projectSupervisors.supervisorId` is the PK of the allowlist row, not the `users.id` FK. If the intent were ever to link supervisors to `users`, the lookup would silently break. More concretely: if a supervisor is added to **multiple projects**, `findSupervisorByEmail` during login returns only the **first** matching row (`.limit(1)`), so `session.userId` will be set to the `supervisorId` of that one row. When the supervisor then navigates to a **different project** they are also on, the middleware will look for a row where `supervisorId = <first-project's-supervisorId>` for the second project — which does not exist — and the access check will correctly deny. But the supervisor's review page (`/supervisor/projects/[projectId]/review`) also re-checks with `findSupervisorByProjectAndId(projectId, session.userId)`, which will **fail** for any project other than the one whose supervisorId was captured at login time. This means a supervisor enrolled in multiple projects can only review the first one they happened to match during login.
- **Severity:** critical
- **Action:** Either: (a) store the supervisor's email in the session and perform the allowlist check by email+project (changing `findSupervisorByProjectAndId` to `findSupervisorByProjectAndEmail`), or (b) document that a supervisor may only be enrolled in one project per login session. Option (a) is the correct fix; it also fixes the review page redirect logic.

---

### 3. Approve route — `revision_requested` branch fetches `projectId` from DB outside the transaction, then passes it into the transaction
- **File:** `src/app/api/projects/[projectId]/synthesis/approve/route.ts:80–104`
- **Issue:** The `revision_requested` branch performs a dynamic `import` and DB read for `projectId` **before** opening the transaction on line 90. The `projectId` is already available from `context.params` (the route already extracted it from the URL in `withSupervisorProjectAccess`). This extra round-trip is wasted work. It also creates a subtle bug: `updateSynthesisResultStatus(resultId, "revision_requested")` on line 97 is called **inside** the transaction but against the global `db` instance (same issue as Finding 1) rather than `tx`.
- **Severity:** critical
- **Action:** Extract `projectId` from `context.params` at the top of the handler (it is already accessible). Remove the inner `import`/`findSynthesisResultById` block. Pass `tx` to `updateSynthesisResultStatus` or remove it if `transitionSynthesisStatus` already writes status (it does — see Finding 1).

---

### 4. `synthesisResults` table columns missing explicit snake_case names (schema convention violation)
- **File:** `src/lib/db/schema.ts:403–437`
- **Issue:** The `synthesisResults` table mixes naming conventions. The schema header comment (lines 1–17) and CLAUDE.md explicitly state: "For all new tables going forward, follow the `depth_flags` pattern: provide explicit snake_case column name strings." Epic 8 added `synthesisEdits` and `revisionRequests` correctly with explicit names — but `synthesisResults` (added in an earlier epic and used heavily in Epic 8) still lacks explicit column name strings for most columns (e.g., `resultId`, `projectId`, `processNodeId`, `synthesisVersion`, `workflowJson`, `interviewsIncluded`, `approvedAt` is given an explicit name but `resultId` is not). This is a pre-existing issue brought into sharp relief by Epic 8's heavy use of this table — all new migration SQL for this table uses camelCase column names instead of snake_case.
- **Severity:** major
- **Action:** Add explicit snake_case column name strings to all columns in `synthesisResults` (e.g., `uuid("result_id")`, `uuid("project_id")`, etc.) and generate a migration to rename existing columns. This is deferred debt that now directly impacts the tables added in Epic 8 which reference it.

---

### 5. `findSupervisorByEmail` returns first match across all projects — login is non-deterministic for multi-project supervisors
- **File:** `src/lib/db/queries/supervisors.ts:11–20`
- **Issue:** `findSupervisorByEmail` uses `.limit(1)` and returns the first `project_supervisors` row matching the email. If a supervisor email appears in multiple projects (which is permitted by the schema since the unique constraint is on `(project_id, email)`, not just `email`), the row returned is arbitrary (no ORDER BY). This feeds into the critical identity bug described in Finding 2, and also means the `passwordHash` used for login verification is from whichever row happens to come back first — which may differ if each project gave the supervisor a different password.
- **Severity:** major
- **Action:** If the design intent is one password per supervisor identity across projects, normalize supervisor identity to a separate table. If per-project passwords are intentional, document the limitation and consider adding an `ORDER BY createdAt` to make the behavior deterministic. Either way, the authentication model needs clarification in the supervisor identity design.

---

### 6. Status badge duplication: `STATUS_LABELS` / `STATUS_CLASSES` defined in three places
- **File:** `src/components/synthesis/status-indicator.tsx:11–28`, `src/components/supervisor/project-list.tsx:17–36`
- **Issue:** Synthesis status labels and badge styling are defined independently in `status-indicator.tsx` (with Tailwind class overrides) and `project-list.tsx` (with shadcn `Badge` variant strings). CLAUDE.md rule: "When two or more files define identical Tailwind class maps, badge color constants, or small helper functions, extract them to a shared module on the second occurrence — never allow three-way duplication to ship across stories." Two definitions already exist; a third appears in `comparison-view.tsx` implicitly through `StatusIndicator`. The `project-list.tsx` uses `Badge variant` instead of `StatusIndicator`, creating visual inconsistency for the same status values.
- **Severity:** major
- **Action:** Replace the `STATUS_LABELS`/`STATUS_VARIANT` maps in `project-list.tsx` with `StatusIndicator` from `src/components/synthesis/status-indicator.tsx`. Extract the shared constants to a `src/lib/synthesis/status-labels.ts` module.

---

### 7. Approve route has both `transitionSynthesisStatus` and `updateSynthesisResultStatus` updating the same `status` column
- **File:** `src/app/api/projects/[projectId]/synthesis/approve/route.ts:65–74`, `src/lib/synthesis/synthesis-state-machine.ts:66–70`, `src/lib/db/queries/synthesis-results.ts:163–183`
- **Issue:** `transitionSynthesisStatus` already calls `dbCtx.update(synthesisResults).set({ status: to })`. Then `updateSynthesisResultStatus` is called again to set `{ status, approvedAt, approvedBy }` — this performs a second UPDATE on the same row, which re-sets `status` redundantly (and as noted in Finding 1, outside the transaction). The `updateSynthesisResultStatus` function signature accepts `status: string` along with optional metadata — it should only ever be called with approval metadata, not a redundant status value. The state machine and the status-setter are architecturally confused about their responsibilities.
- **Severity:** major
- **Action:** Refactor `updateSynthesisResultStatus` to only accept `{ approvedAt, approvedBy }` (no `status` param), and call it inside the transaction after `transitionSynthesisStatus`. Or extend `transitionSynthesisStatus` to accept optional metadata columns to set atomically on transition.

---

### 8. `ComparisonViewShell` enters review mode without checking current synthesis status — supervisor can enter review on already-approved synthesis
- **File:** `src/components/synthesis/comparison-view.tsx:66–94, 177–206`
- **Issue:** The "Enter Review" button is conditionally rendered only when `localSynthesis?.status === "draft"` (line 177). However, the `onReviewToggle` prop passed to `IndividualCarousel` (line 198–202) uses `localSynthesis && !terminalStatus` — if `localSynthesis.status` is `"in_review"` (e.g., a different supervisor already opened review), the button is visible and wired. Clicking it calls `setMode("review")` directly **without** calling `handleEnterReview` (which posts to the state machine). So a supervisor can bypass the `draft → in_review` transition and open the review agent against an `in_review` synthesis without any transition — which is actually correct behavior — but also against an already-`approved` synthesis if `terminalStatus` was set in a prior visit but `localSynthesis.status` hasn't been refreshed from the server. The client-side `localSynthesis` is stale server-rendered data.
- **Severity:** major
- **Action:** On the review page, gate `onReviewToggle` on `localSynthesis.status === "draft" || localSynthesis.status === "in_review"` (not just `!terminalStatus`). Consider refreshing synthesis status from the API when the page becomes visible after a review session completes.

---

### 9. `review-agent.ts` `applyReviewEdit` uses a raw `db.update()` inside the transaction instead of the query-layer function
- **File:** `src/lib/synthesis/review-agent.ts:61–67`
- **Issue:** `applyReviewEdit` performs `tx.update(synthesisResults).set({ workflowJson: afterJson })` directly, bypassing `updateSynthesisResultWorkflowJson` in the query layer. CLAUDE.md forbids importing Drizzle outside `src/lib/db/` — however, `review-agent.ts` lives in `src/lib/synthesis/`, not `src/lib/db/`, and it imports from `drizzle-orm` (`eq`). While it does import `db` from `@/lib/db`, direct schema manipulation (`synthesisResults` table) from outside the `db/` boundary violates the service boundary intent. The function `updateSynthesisResultWorkflowJson` in the query layer exists for exactly this purpose but is not used here.
- **Severity:** major
- **Action:** Move the `tx.update(synthesisResults)` block in `applyReviewEdit` to use `updateSynthesisResultWorkflowJson` (passing `tx` as a parameter, which requires adding an optional `tx` param to that function), then import and call it. Remove the `synthesisResults` schema import from `review-agent.ts`.

---

### 10. `supervisors/route.ts` detects unique constraint by matching on `err.message` string
- **File:** `src/app/api/projects/[projectId]/supervisors/route.ts:86–95`
- **Issue:** The catch block checks `err.message.toLowerCase().includes("unique")` to detect a duplicate-email constraint violation. CLAUDE.md explicitly prohibits this: "Never classify errors by matching on `error.message` strings — use typed error classes... and `instanceof` checks." This pattern is brittle: it will silently misclassify any other error whose message contains the word "unique" and will fail to match if the Postgres driver or Drizzle changes its error format.
- **Severity:** major
- **Action:** Check for `err.code === "23505"` (Postgres unique violation code) on the raw error, or wrap the insert in a try/catch that detects `postgres.PostgresError` with `code === "23505"` and throws `ConstraintViolationError`. Remove the string-matching branch.

---

### 11. `synthesis/review/messages/route.ts` truncates `workflowJson` at 2000 characters — may corrupt JSON sent to the LLM
- **File:** `src/app/api/projects/[projectId]/synthesis/review/messages/route.ts:117–121`
- **Issue:** `JSON.stringify(synthesisResult.workflowJson, null, 2).slice(0, 2000)` blindly truncates the JSON string mid-character. The LLM receives a non-parseable partial JSON blob as context. This degrades review quality for any synthesis result whose JSON exceeds ~2000 characters (which is nearly all non-trivial syntheses). There is no indication to the LLM that the context is truncated.
- **Severity:** major
- **Action:** Instead of slicing raw JSON, construct a condensed summary object (step labels only, divergence IDs) and stringify that. If truncation is necessary, append a `"... [truncated]"` suffix and clarify in the system prompt that the summary may be incomplete.

---

### 12. `synthesis-state-machine.ts` — `SynthesisStatus` type includes `"collecting"` and `"synthesizing"` which are `discoveryStatus` values, not synthesis result statuses
- **File:** `src/lib/synthesis/synthesis-state-machine.ts:11–17`
- **Issue:** The `synthesisResults.status` column is `text()` with no enum constraint. The state machine `SynthesisStatus` type includes `"collecting"` and `"synthesizing"` as valid transitions FROM `revision_requested`. But these values correspond to `projects.discoveryStatus` values, not `synthesisResults.status` values. No existing code actually writes `"collecting"` or `"synthesizing"` to a `synthesis_results.status` column — the synthesis status route (`synthesis/status/route.ts`) transitions TO these values, but they map to the project's status conceptually, not the result row's status. Storing `"collecting"` in a `synthesis_results` row is semantically incorrect: once a synthesis result is created, it is either `draft`, `in_review`, `approved`, or `revision_requested`.
- **Severity:** major
- **Action:** Remove `"collecting"` and `"synthesizing"` from `SynthesisStatus`. The PM's "reopen" and "resynthesize" actions should transition the **project's** `discoveryStatus`, not the synthesis result's status. The state machine should be split or scoped accordingly.

---

### 13. `review/page.tsx` server component does access check redundantly — also calls DB directly without going through query layer (minor)
- **File:** `src/app/supervisor/projects/[projectId]/review/page.tsx:22–29`
- **Issue:** The page performs `findSupervisorByProjectAndId(projectId, session.userId)` as an inline access check — a guard that is also performed by `withSupervisorProjectAccess` middleware on every API call. This is correct security in depth, but the pattern creates inconsistency with how other server pages handle authorization (they rely solely on `validateSession` and role check). More importantly, because of the multi-project supervisor identity bug in Finding 2, this check will correctly fail even when the supervisor is legitimately enrolled in the project (if their `session.userId` is from a different project's row).
- **Severity:** minor
- **Action:** Document the dependency on Finding 2's fix. Once the identity model is corrected (email-based lookup), update this check to match.

---

### 14. `computeTally` in `review-summary.tsx` classifies edits by string-matching `description` — brittle and always returns 0 for `stepsUnchanged`
- **File:** `src/components/synthesis/review-summary.tsx:22–36`
- **Issue:** The tally logic parses `edit.description` with `.includes("add")`, `.includes("reclassif")` etc. — this is the same error-classification anti-pattern applied to business logic. A description like "reclassify divergence to add context" would hit both branches. Additionally, `stepsUnchanged` is hardcoded to `0` — the displayed metric is always meaningless.
- **Severity:** minor
- **Action:** Use `SynthesisEditRow.changeType` (or derive it from `ProposedEdit.changeType` persisted in the edit record) rather than parsing description strings. Add `changeType` to the `synthesis_edits` table as a `text` column and persist it in `createSynthesisEdit`.

---

### 15. `review-agent-panel.tsx` imports `ProjectSynthesisSummary` type from `src/lib/db/queries/synthesis-results` — violates client boundary rule
- **File:** `src/components/synthesis/review-agent-panel.tsx:21`
- **Issue:** `import type { ProjectSynthesisSummary } from "@/lib/db/queries/synthesis-results"` — this is a `"use client"` component importing a type from the DB query layer (`src/lib/db/`). CLAUDE.md rule: "Client Components access data ONLY through `/api/` routes — never import from `src/lib/`." Type-only imports do not generate runtime code in TypeScript, but the rule exists to prevent the import graph from pulling DB layer into client bundles. The import is a type import so it will be erased at compile time, but it still establishes a forbidden dependency edge in the module graph that `next build` may warn on or that future changes can accidentally convert to a value import.
- **Severity:** minor
- **Action:** Define `ProjectSynthesisSummary` (or a client-safe subset) in a shared `src/types/synthesis.ts` or `src/lib/schema/synthesis-types.ts` file that does not import Drizzle. Import the type from there in both the query layer and the client component.

---

### 16. `review-agent-panel.tsx` imports `ProposedEdit` type from `src/lib/synthesis/review-agent` — same client boundary violation
- **File:** `src/components/synthesis/review-agent-panel.tsx:23`
- **Issue:** Same as Finding 15 — `"use client"` component imports from `src/lib/synthesis/`. `review-agent.ts` imports `db` and `synthesisEdits` at the top level; while TypeScript will tree-shake type imports, the module still lives behind a boundary that CLAUDE.md prohibits client components from crossing.
- **Severity:** minor
- **Action:** Extract `ProposedEdit` type to a shared types module (same solution as Finding 15).

---

### 17. `ComparisonView` has duplicate pan/zoom handler blocks (synthesis + individual panels) — 80+ lines of identical logic
- **File:** `src/components/synthesis/comparison-view.tsx:391–470`
- **Issue:** Eight nearly-identical pan/zoom handler functions are duplicated for the synthesis panel and individual panel (zoom in/out, fit to view, mouse down/move/up, wheel). `IndividualCarousel` has its own third copy. This is exactly the pattern CLAUDE.md prohibits: "When two or more files define identical Tailwind class maps, badge color constants, or small helper functions, extract them to a shared module on the second occurrence."
- **Severity:** minor
- **Action:** Extract pan/zoom state and handlers to a `usePanZoom()` custom hook in `src/hooks/use-pan-zoom.ts`. `ComparisonView` already imports from `@/lib/types/diagram` for `PanZoomState` — the hook can live alongside.

---

### 18. `SupervisorProjectList` links to review page for `"approved"` status projects — review is post-terminal
- **File:** `src/components/supervisor/project-list.tsx:70–79`
- **Issue:** The condition `["draft", "in_review", "approved"].includes(project.discoveryStatus)` renders an "Open Review Interface" link for already-approved projects. An approved synthesis has no actionable review workflow — the supervisor has already approved it. Navigating there would show a stale "approved" state with no available actions, which is confusing.
- **Severity:** minor
- **Action:** Limit the link to `["draft", "in_review", "revision_requested"]`. For `"approved"`, display a read-only "Approved — view outputs" link or omit the action link.
I now have enough context from all the key files to produce a comprehensive review. Let me synthesize my findings.

---
agent_role: reviewer
task_id: epic-8-review
timestamp: 2026-04-12T18:45:00.000000+00:00
input_files: [src/app/api/auth/login/route.ts, src/app/api/auth/session/route.ts, src/app/api/projects/[projectId]/supervisors/route.ts, src/app/api/projects/[projectId]/supervisors/[supervisorId]/route.ts, src/app/api/projects/[projectId]/synthesis/approve/route.ts, src/app/api/projects/[projectId]/synthesis/review/comparison/route.ts, src/app/api/projects/[projectId]/synthesis/review/edits/route.ts, src/app/api/projects/[projectId]/synthesis/review/individuals/route.ts, src/app/api/projects/[projectId]/synthesis/review/messages/route.ts, src/app/api/projects/[projectId]/synthesis/status/route.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/review/route.ts, src/app/supervisor/projects/page.tsx, src/app/supervisor/projects/[projectId]/review/page.tsx, src/components/auth/login-form.tsx, src/components/project/supervisor-management.tsx, src/components/project/synthesis-status-panel.tsx, src/components/supervisor/project-list.tsx, src/components/synthesis/approval-controls.tsx, src/components/synthesis/comparison-view.tsx, src/components/synthesis/edit-history.tsx, src/components/synthesis/individual-carousel.tsx, src/components/synthesis/review-agent-panel.tsx, src/components/synthesis/review-summary.tsx, src/components/synthesis/status-indicator.tsx, src/lib/auth/middleware.ts, src/lib/auth/session.ts, src/lib/db/queries/individual-process-schemas.ts, src/lib/db/queries/revision-requests.ts, src/lib/db/queries/supervisors.ts, src/lib/db/queries/synthesis-edits.ts, src/lib/db/queries/synthesis-results.ts, src/lib/db/schema.ts, src/lib/schema/api-requests.ts, src/lib/synthesis/review-agent.ts, src/lib/synthesis/synthesis-state-machine.ts]
reviewer_type: claude
review_scope: epic

---

# Epic Code Review — CLAUDE Reviewer

## Summary

Epic 8 implements supervisor authentication, individual diagram carousel, comparison view, conversational review agent, approval/revision flow, and synthesis state machine extensions. The architecture is coherent and the security model is sound overall, but there are several critical correctness bugs — most seriously a double-write in the approve transaction and an unauthorized state-machine access in `withSupervisorProjectAccess` that uses the supervisor's own row ID as the project-membership key — plus a cluster of major issues around error handling, duplicate code, and spec gaps.

---

## Findings

### 1. Approve route performs redundant double-write outside transaction — approve path
- **File:** `src/app/api/projects/[projectId]/synthesis/approve/route.ts:64–76`
- **Issue:** The `approve` branch calls `transitionSynthesisStatus(resultId, "in_review", "approved", tx)` inside a `db.transaction()`, which already `UPDATE`s the `status` column (line 68–70 in `synthesis-state-machine.ts`). The very next line then calls `updateSynthesisResultStatus(resultId, "approved", { approvedAt, approvedBy })` **outside the transaction scope** (it constructs its own `db.update()` against the non-`tx` `db` instance). This means `approvedAt` and `approvedBy` are set in a separate, non-atomic update that can fail silently after the status transition already committed, leaving the row with `status = "approved"` but `approvedAt = null` and `approvedBy = null`.
- **Severity:** critical
- **Action:** Pass `tx` as a parameter to `updateSynthesisResultStatus`, or consolidate by having `transitionSynthesisStatus` accept an optional `{ approvedAt, approvedBy }` options map. Remove the standalone `updateSynthesisResultStatus` call and include the approval metadata inside the single `tx.update()`.

---

### 2. `withSupervisorProjectAccess` uses `session.userId` (supervisorId) as the project-membership lookup key — but login stores `supervisor.supervisorId` as `userId`
- **File:** `src/lib/auth/middleware.ts:101–104`, `src/app/api/auth/login/route.ts:95`
- **Issue:** The login route stores `supervisor.supervisorId` as the session's `userId` field (`createSession(supervisor.supervisorId, ...)`). The middleware then calls `findSupervisorByProjectAndId(projectId, session.userId)`, which queries `supervisorId = session.userId`. This is **actually correct** — but it is fragile and undocumented. The concern is that `projectSupervisors.supervisorId` is the PK of the allowlist row, not the `users.id` FK. If the intent were ever to link supervisors to `users`, the lookup would silently break. More concretely: if a supervisor is added to **multiple projects**, `findSupervisorByEmail` during login returns only the **first** matching row (`.limit(1)`), so `session.userId` will be set to the `supervisorId` of that one row. When the supervisor then navigates to a **different project** they are also on, the middleware will look for a row where `supervisorId = <first-project's-supervisorId>` for the second project — which does not exist — and the access check will correctly deny. But the supervisor's review page (`/supervisor/projects/[projectId]/review`) also re-checks with `findSupervisorByProjectAndId(projectId, session.userId)`, which will **fail** for any project other than the one whose supervisorId was captured at login time. This means a supervisor enrolled in multiple projects can only review the first one they happened to match during login.
- **Severity:** critical
- **Action:** Either: (a) store the supervisor's email in the session and perform the allowlist check by email+project (changing `findSupervisorByProjectAndId` to `findSupervisorByProjectAndEmail`), or (b) document that a supervisor may only be enrolled in one project per login session. Option (a) is the correct fix; it also fixes the review page redirect logic.

---

### 3. Approve route — `revision_requested` branch fetches `projectId` from DB outside the transaction, then passes it into the transaction
- **File:** `src/app/api/projects/[projectId]/synthesis/approve/route.ts:80–104`
- **Issue:** The `revision_requested` branch performs a dynamic `import` and DB read for `projectId` **before** opening the transaction on line 90. The `projectId` is already available from `context.params` (the route already extracted it from the URL in `withSupervisorProjectAccess`). This extra round-trip is wasted work. It also creates a subtle bug: `updateSynthesisResultStatus(resultId, "revision_requested")` on line 97 is called **inside** the transaction but against the global `db` instance (same issue as Finding 1) rather than `tx`.
- **Severity:** critical
- **Action:** Extract `projectId` from `context.params` at the top of the handler (it is already accessible). Remove the inner `import`/`findSynthesisResultById` block. Pass `tx` to `updateSynthesisResultStatus` or remove it if `transitionSynthesisStatus` already writes status (it does — see Finding 1).

---

### 4. `synthesisResults` table columns missing explicit snake_case names (schema convention violation)
- **File:** `src/lib/db/schema.ts:403–437`
- **Issue:** The `synthesisResults` table mixes naming conventions. The schema header comment (lines 1–17) and CLAUDE.md explicitly state: "For all new tables going forward, follow the `depth_flags` pattern: provide explicit snake_case column name strings." Epic 8 added `synthesisEdits` and `revisionRequests` correctly with explicit names — but `synthesisResults` (added in an earlier epic and used heavily in Epic 8) still lacks explicit column name strings for most columns (e.g., `resultId`, `projectId`, `processNodeId`, `synthesisVersion`, `workflowJson`, `interviewsIncluded`, `approvedAt` is given an explicit name but `resultId` is not). This is a pre-existing issue brought into sharp relief by Epic 8's heavy use of this table — all new migration SQL for this table uses camelCase column names instead of snake_case.
- **Severity:** major
- **Action:** Add explicit snake_case column name strings to all columns in `synthesisResults` (e.g., `uuid("result_id")`, `uuid("project_id")`, etc.) and generate a migration to rename existing columns. This is deferred debt that now directly impacts the tables added in Epic 8 which reference it.

---

### 5. `findSupervisorByEmail` returns first match across all projects — login is non-deterministic for multi-project supervisors
- **File:** `src/lib/db/queries/supervisors.ts:11–20`
- **Issue:** `findSupervisorByEmail` uses `.limit(1)` and returns the first `project_supervisors` row matching the email. If a supervisor email appears in multiple projects (which is permitted by the schema since the unique constraint is on `(project_id, email)`, not just `email`), the row returned is arbitrary (no ORDER BY). This feeds into the critical identity bug described in Finding 2, and also means the `passwordHash` used for login verification is from whichever row happens to come back first — which may differ if each project gave the supervisor a different password.
- **Severity:** major
- **Action:** If the design intent is one password per supervisor identity across projects, normalize supervisor identity to a separate table. If per-project passwords are intentional, document the limitation and consider adding an `ORDER BY createdAt` to make the behavior deterministic. Either way, the authentication model needs clarification in the supervisor identity design.

---

### 6. Status badge duplication: `STATUS_LABELS` / `STATUS_CLASSES` defined in three places
- **File:** `src/components/synthesis/status-indicator.tsx:11–28`, `src/components/supervisor/project-list.tsx:17–36`
- **Issue:** Synthesis status labels and badge styling are defined independently in `status-indicator.tsx` (with Tailwind class overrides) and `project-list.tsx` (with shadcn `Badge` variant strings). CLAUDE.md rule: "When two or more files define identical Tailwind class maps, badge color constants, or small helper functions, extract them to a shared module on the second occurrence — never allow three-way duplication to ship across stories." Two definitions already exist; a third appears in `comparison-view.tsx` implicitly through `StatusIndicator`. The `project-list.tsx` uses `Badge variant` instead of `StatusIndicator`, creating visual inconsistency for the same status values.
- **Severity:** major
- **Action:** Replace the `STATUS_LABELS`/`STATUS_VARIANT` maps in `project-list.tsx` with `StatusIndicator` from `src/components/synthesis/status-indicator.tsx`. Extract the shared constants to a `src/lib/synthesis/status-labels.ts` module.

---

### 7. Approve route has both `transitionSynthesisStatus` and `updateSynthesisResultStatus` updating the same `status` column
- **File:** `src/app/api/projects/[projectId]/synthesis/approve/route.ts:65–74`, `src/lib/synthesis/synthesis-state-machine.ts:66–70`, `src/lib/db/queries/synthesis-results.ts:163–183`
- **Issue:** `transitionSynthesisStatus` already calls `dbCtx.update(synthesisResults).set({ status: to })`. Then `updateSynthesisResultStatus` is called again to set `{ status, approvedAt, approvedBy }` — this performs a second UPDATE on the same row, which re-sets `status` redundantly (and as noted in Finding 1, outside the transaction). The `updateSynthesisResultStatus` function signature accepts `status: string` along with optional metadata — it should only ever be called with approval metadata, not a redundant status value. The state machine and the status-setter are architecturally confused about their responsibilities.
- **Severity:** major
- **Action:** Refactor `updateSynthesisResultStatus` to only accept `{ approvedAt, approvedBy }` (no `status` param), and call it inside the transaction after `transitionSynthesisStatus`. Or extend `transitionSynthesisStatus` to accept optional metadata columns to set atomically on transition.

---

### 8. `ComparisonViewShell` enters review mode without checking current synthesis status — supervisor can enter review on already-approved synthesis
- **File:** `src/components/synthesis/comparison-view.tsx:66–94, 177–206`
- **Issue:** The "Enter Review" button is conditionally rendered only when `localSynthesis?.status === "draft"` (line 177). However, the `onReviewToggle` prop passed to `IndividualCarousel` (line 198–202) uses `localSynthesis && !terminalStatus` — if `localSynthesis.status` is `"in_review"` (e.g., a different supervisor already opened review), the button is visible and wired. Clicking it calls `setMode("review")` directly **without** calling `handleEnterReview` (which posts to the state machine). So a supervisor can bypass the `draft → in_review` transition and open the review agent against an `in_review` synthesis without any transition — which is actually correct behavior — but also against an already-`approved` synthesis if `terminalStatus` was set in a prior visit but `localSynthesis.status` hasn't been refreshed from the server. The client-side `localSynthesis` is stale server-rendered data.
- **Severity:** major
- **Action:** On the review page, gate `onReviewToggle` on `localSynthesis.status === "draft" || localSynthesis.status === "in_review"` (not just `!terminalStatus`). Consider refreshing synthesis status from the API when the page becomes visible after a review session completes.

---

### 9. `review-agent.ts` `applyReviewEdit` uses a raw `db.update()` inside the transaction instead of the query-layer function
- **File:** `src/lib/synthesis/review-agent.ts:61–67`
- **Issue:** `applyReviewEdit` performs `tx.update(synthesisResults).set({ workflowJson: afterJson })` directly, bypassing `updateSynthesisResultWorkflowJson` in the query layer. CLAUDE.md forbids importing Drizzle outside `src/lib/db/` — however, `review-agent.ts` lives in `src/lib/synthesis/`, not `src/lib/db/`, and it imports from `drizzle-orm` (`eq`). While it does import `db` from `@/lib/db`, direct schema manipulation (`synthesisResults` table) from outside the `db/` boundary violates the service boundary intent. The function `updateSynthesisResultWorkflowJson` in the query layer exists for exactly this purpose but is not used here.
- **Severity:** major
- **Action:** Move the `tx.update(synthesisResults)` block in `applyReviewEdit` to use `updateSynthesisResultWorkflowJson` (passing `tx` as a parameter, which requires adding an optional `tx` param to that function), then import and call it. Remove the `synthesisResults` schema import from `review-agent.ts`.

---

### 10. `supervisors/route.ts` detects unique constraint by matching on `err.message` string
- **File:** `src/app/api/projects/[projectId]/supervisors/route.ts:86–95`
- **Issue:** The catch block checks `err.message.toLowerCase().includes("unique")` to detect a duplicate-email constraint violation. CLAUDE.md explicitly prohibits this: "Never classify errors by matching on `error.message` strings — use typed error classes... and `instanceof` checks." This pattern is brittle: it will silently misclassify any other error whose message contains the word "unique" and will fail to match if the Postgres driver or Drizzle changes its error format.
- **Severity:** major
- **Action:** Check for `err.code === "23505"` (Postgres unique violation code) on the raw error, or wrap the insert in a try/catch that detects `postgres.PostgresError` with `code === "23505"` and throws `ConstraintViolationError`. Remove the string-matching branch.

---

### 11. `synthesis/review/messages/route.ts` truncates `workflowJson` at 2000 characters — may corrupt JSON sent to the LLM
- **File:** `src/app/api/projects/[projectId]/synthesis/review/messages/route.ts:117–121`
- **Issue:** `JSON.stringify(synthesisResult.workflowJson, null, 2).slice(0, 2000)` blindly truncates the JSON string mid-character. The LLM receives a non-parseable partial JSON blob as context. This degrades review quality for any synthesis result whose JSON exceeds ~2000 characters (which is nearly all non-trivial syntheses). There is no indication to the LLM that the context is truncated.
- **Severity:** major
- **Action:** Instead of slicing raw JSON, construct a condensed summary object (step labels only, divergence IDs) and stringify that. If truncation is necessary, append a `"... [truncated]"` suffix and clarify in the system prompt that the summary may be incomplete.

---

### 12. `synthesis-state-machine.ts` — `SynthesisStatus` type includes `"collecting"` and `"synthesizing"` which are `discoveryStatus` values, not synthesis result statuses
- **File:** `src/lib/synthesis/synthesis-state-machine.ts:11–17`
- **Issue:** The `synthesisResults.status` column is `text()` with no enum constraint. The state machine `SynthesisStatus` type includes `"collecting"` and `"synthesizing"` as valid transitions FROM `revision_requested`. But these values correspond to `projects.discoveryStatus` values, not `synthesisResults.status` values. No existing code actually writes `"collecting"` or `"synthesizing"` to a `synthesis_results.status` column — the synthesis status route (`synthesis/status/route.ts`) transitions TO these values, but they map to the project's status conceptually, not the result row's status. Storing `"collecting"` in a `synthesis_results` row is semantically incorrect: once a synthesis result is created, it is either `draft`, `in_review`, `approved`, or `revision_requested`.
- **Severity:** major
- **Action:** Remove `"collecting"` and `"synthesizing"` from `SynthesisStatus`. The PM's "reopen" and "resynthesize" actions should transition the **project's** `discoveryStatus`, not the synthesis result's status. The state machine should be split or scoped accordingly.

---

### 13. `review/page.tsx` server component does access check redundantly — also calls DB directly without going through query layer (minor)
- **File:** `src/app/supervisor/projects/[projectId]/review/page.tsx:22–29`
- **Issue:** The page performs `findSupervisorByProjectAndId(projectId, session.userId)` as an inline access check — a guard that is also performed by `withSupervisorProjectAccess` middleware on every API call. This is correct security in depth, but the pattern creates inconsistency with how other server pages handle authorization (they rely solely on `validateSession` and role check). More importantly, because of the multi-project supervisor identity bug in Finding 2, this check will correctly fail even when the supervisor is legitimately enrolled in the project (if their `session.userId` is from a different project's row).
- **Severity:** minor
- **Action:** Document the dependency on Finding 2's fix. Once the identity model is corrected (email-based lookup), update this check to match.

---

### 14. `computeTally` in `review-summary.tsx` classifies edits by string-matching `description` — brittle and always returns 0 for `stepsUnchanged`
- **File:** `src/components/synthesis/review-summary.tsx:22–36`
- **Issue:** The tally logic parses `edit.description` with `.includes("add")`, `.includes("reclassif")` etc. — this is the same error-classification anti-pattern applied to business logic. A description like "reclassify divergence to add context" would hit both branches. Additionally, `stepsUnchanged` is hardcoded to `0` — the displayed metric is always meaningless.
- **Severity:** minor
- **Action:** Use `SynthesisEditRow.changeType` (or derive it from `ProposedEdit.changeType` persisted in the edit record) rather than parsing description strings. Add `changeType` to the `synthesis_edits` table as a `text` column and persist it in `createSynthesisEdit`.

---

### 15. `review-agent-panel.tsx` imports `ProjectSynthesisSummary` type from `src/lib/db/queries/synthesis-results` — violates client boundary rule
- **File:** `src/components/synthesis/review-agent-panel.tsx:21`
- **Issue:** `import type { ProjectSynthesisSummary } from "@/lib/db/queries/synthesis-results"` — this is a `"use client"` component importing a type from the DB query layer (`src/lib/db/`). CLAUDE.md rule: "Client Components access data ONLY through `/api/` routes — never import from `src/lib/`." Type-only imports do not generate runtime code in TypeScript, but the rule exists to prevent the import graph from pulling DB layer into client bundles. The import is a type import so it will be erased at compile time, but it still establishes a forbidden dependency edge in the module graph that `next build` may warn on or that future changes can accidentally convert to a value import.
- **Severity:** minor
- **Action:** Define `ProjectSynthesisSummary` (or a client-safe subset) in a shared `src/types/synthesis.ts` or `src/lib/schema/synthesis-types.ts` file that does not import Drizzle. Import the type from there in both the query layer and the client component.

---

### 16. `review-agent-panel.tsx` imports `ProposedEdit` type from `src/lib/synthesis/review-agent` — same client boundary violation
- **File:** `src/components/synthesis/review-agent-panel.tsx:23`
- **Issue:** Same as Finding 15 — `"use client"` component imports from `src/lib/synthesis/`. `review-agent.ts` imports `db` and `synthesisEdits` at the top level; while TypeScript will tree-shake type imports, the module still lives behind a boundary that CLAUDE.md prohibits client components from crossing.
- **Severity:** minor
- **Action:** Extract `ProposedEdit` type to a shared types module (same solution as Finding 15).

---

### 17. `ComparisonView` has duplicate pan/zoom handler blocks (synthesis + individual panels) — 80+ lines of identical logic
- **File:** `src/components/synthesis/comparison-view.tsx:391–470`
- **Issue:** Eight nearly-identical pan/zoom handler functions are duplicated for the synthesis panel and individual panel (zoom in/out, fit to view, mouse down/move/up, wheel). `IndividualCarousel` has its own third copy. This is exactly the pattern CLAUDE.md prohibits: "When two or more files define identical Tailwind class maps, badge color constants, or small helper functions, extract them to a shared module on the second occurrence."
- **Severity:** minor
- **Action:** Extract pan/zoom state and handlers to a `usePanZoom()` custom hook in `src/hooks/use-pan-zoom.ts`. `ComparisonView` already imports from `@/lib/types/diagram` for `PanZoomState` — the hook can live alongside.

---

### 18. `SupervisorProjectList` links to review page for `"approved"` status projects — review is post-terminal
- **File:** `src/components/supervisor/project-list.tsx:70–79`
- **Issue:** The condition `["draft", "in_review", "approved"].includes(project.discoveryStatus)` renders an "Open Review Interface" link for already-approved projects. An approved synthesis has no actionable review workflow — the supervisor has already approved it. Navigating there would show a stale "approved" state with no available actions, which is confusing.
- **Severity:** minor
- **Action:** Limit the link to `["draft", "in_review", "revision_requested"]`. For `"approved"`, display a read-only "Approved — view outputs" link or omit the action link.
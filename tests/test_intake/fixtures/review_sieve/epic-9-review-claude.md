I'll wait for the background agents to complete while also reading the source files directly.
All 5 background agents are running. I'll wait for them to complete before synthesizing the review.
The output files seem empty. Let me read the files directly while waiting for the other agents.
Good. Now let me read the actual source files while waiting for the remaining agents:
Now I have enough data to produce a thorough review. Let me check a few more key files:
I now have enough information to write a comprehensive review. Let me compile all findings:

---
agent_role: reviewer
task_id: epic-9-review
timestamp: 2026-04-13T15:49:42.236557+00:00
input_files: [CLAUDE.md, _bmad-output/implementation-artifacts/9-1-responsive-layout-tablet-desktop.md, _bmad-output/implementation-artifacts/9-2-keyboard-navigation-focus-management.md, _bmad-output/implementation-artifacts/9-3-color-contrast-aria-labels-text-alternatives.md, _bmad-output/implementation-artifacts/9-4-visual-polish-design-system-consistency.md, _bmad-output/implementation-artifacts/9-5-performance-audit-page-load-optimization.md, _bmad-output/implementation-artifacts/deferred-work.md, next.config.ts, rebuild-status.md, scripts/ci.sh, src/app/api/auth/login/route.test.ts, src/app/api/auth/login/route.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/review/route.test.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/review/route.ts, src/app/api/projects/[projectId]/settings/route.test.ts, src/app/api/projects/[projectId]/supervisors/route.test.ts, src/app/api/projects/[projectId]/supervisors/route.ts, src/app/api/projects/[projectId]/synthesis/approve/route.test.ts, src/app/api/projects/[projectId]/synthesis/approve/route.ts, src/app/api/projects/[projectId]/synthesis/review/comparison/route.test.ts, src/app/api/projects/[projectId]/synthesis/review/comparison/route.ts, src/app/api/projects/[projectId]/synthesis/review/edits/route.test.ts, src/app/api/projects/[projectId]/synthesis/review/individuals/route.test.ts, src/app/api/projects/[projectId]/synthesis/review/messages/route.test.ts, src/app/api/projects/[projectId]/synthesis/review/messages/route.ts, src/app/api/projects/[projectId]/synthesis/status/route.test.ts, src/app/api/projects/[projectId]/synthesis/status/route.ts, src/app/globals.css, src/app/interview/[token]/active/page.tsx, src/app/interview/[token]/loading.tsx, src/app/projects/[projectId]/loading.tsx, src/app/projects/loading.tsx, src/app/supervisor/projects/[projectId]/review/page.tsx, src/app/supervisor/projects/loading.tsx, src/components/interview/conversation-thread.test.tsx, src/components/interview/diagram-panel.tsx, src/components/interview/diagram-text-alternative.test.tsx, src/components/interview/diagram-text-alternative.tsx, src/components/interview/interview-input-controls.test.tsx, src/components/interview/interview-input-controls.tsx, src/components/interview/interview-toolbar.test.tsx, src/components/interview/interview-toolbar.tsx, src/components/interview/read-only-view.test.tsx, src/components/interview/speech-card.test.tsx, src/components/interview/speech-card.tsx, src/components/interview/typed-input-area.test.tsx, src/components/interview/typed-input-area.tsx, src/components/interview/voice-input-area.tsx, src/components/project/interview-list-view.test.tsx, src/components/project/interview-list-view.tsx, src/components/project/process-tree.test.tsx, src/components/project/process-tree.tsx, src/components/project/project-detail-layout.test.tsx, src/components/project/project-detail-layout.tsx, src/components/project/synthesis-readiness.test.tsx, src/components/project/synthesis-readiness.tsx, src/components/supervisor/project-list.test.tsx, src/components/supervisor/project-list.tsx, src/components/synthesis/approval-controls.tsx, src/components/synthesis/bpmn-chart.test.tsx, src/components/synthesis/bpmn-chart.tsx, src/components/synthesis/chart-controls.test.tsx, src/components/synthesis/comparison-view.tsx, src/components/synthesis/divergence-panel.test.tsx, src/components/synthesis/divergence-panel.tsx, src/components/synthesis/edit-history.test.tsx, src/components/synthesis/edit-history.tsx, src/components/synthesis/individual-carousel.tsx, src/components/synthesis/review-agent-panel.tsx, src/components/synthesis/review-summary.test.tsx, src/components/synthesis/review-summary.tsx, src/components/synthesis/status-indicator.tsx, src/components/synthesis/synthesis-viewer.test.tsx, src/components/synthesis/synthesis-viewer.tsx, src/components/synthesis/text-alternative.tsx, src/hooks/use-pan-zoom.ts, src/lib/api/error-handler.test.ts, src/lib/api/error-handler.ts, src/lib/auth/middleware.ts, src/lib/db/queries/projects.ts, src/lib/db/queries/revision-requests.ts, src/lib/db/queries/supervisors.ts, src/lib/db/queries/synthesis-edits.test.ts, src/lib/db/queries/synthesis-edits.ts, src/lib/db/queries/synthesis-results.test.ts, src/lib/db/queries/synthesis-results.ts, src/lib/db/schema.ts, src/lib/synthesis/review-agent.test.ts, src/lib/synthesis/review-agent.ts, src/lib/synthesis/status-labels.ts, src/lib/synthesis/synthesis-state-machine.test.ts, src/lib/synthesis/synthesis-state-machine.ts, src/types/synthesis.ts, vitest.config.ts]
reviewer_type: claude
review_scope: epic

---

# Epic Code Review — CLAUDE Reviewer

## Summary

Epic 9 successfully delivers responsive layout, keyboard accessibility, ARIA improvements, design system token compliance, and performance polish. The implementations are largely correct and follow CLAUDE.md rules well; however, a meaningful security gap exists in the `processes/[nodeId]/synthesis/review` route (IDOR), the `StatusIndicator` component silently swallows unrecognized `SynthesisStatus` values, the `status-labels.ts` `DiscoveryStatus` type definition diverges from the DB enum, and the loading skeleton files contain a minor but spec-violating breakpoint mismatch.

---

## Findings

### 1. IDOR: `review` route uses non-scoped `findSynthesisResultById` before project membership check
- **File:** `src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/review/route.ts:48–71`
- **Issue:** The route calls `findSynthesisResultById(resultId)` (unscoped, no `projectId` filter) then manually compares `result.projectId !== projectId` at line 61. This is a two-step load-then-check pattern — a TOCTOU window exists between the read and the manual comparison, and it violates the CLAUDE.md rule: *"always verify the entity belongs to that project before performing any mutations — use a scoped query function that includes `projectId` in the WHERE clause rather than relying on per-route manual checks."* The function `findSynthesisResultByIdAndProject` already exists and is used correctly in all other routes. A `findSynthesisResultById` call here crosses project data boundaries before the check completes.
- **Severity:** major
- **Action:** Replace `findSynthesisResultById` + manual `result.projectId !== projectId` check with a single call to `findSynthesisResultByIdAndProject(resultId, projectId)`, returning 404 if null. Remove the manual comparison block (lines 61–71).

---

### 2. `StatusIndicator` silently treats unknown `SynthesisStatus` values as `DiscoveryStatus`
- **File:** `src/components/synthesis/status-indicator.tsx:22–26`
- **Issue:** The component accepts `status: string` and does `STATUS_LABELS[status as keyof typeof STATUS_LABELS]`. `STATUS_LABELS` is typed `Record<DiscoveryStatus, string>` (only `DiscoveryStatus` keys). When called with a `SynthesisStatus` value like `"in_review"` (which happens to overlap) it works accidentally; when called with `"draft"` or `"revision_requested"` it falls back to displaying the raw string. This is the exact "never mix status columns" anti-pattern documented in CLAUDE.md and in `deferred-work.md` (epic-8 deferred item: *"Status constants duplicated across… status-indicator.tsx"*). The component currently works for the overlapping values but is structurally incorrect and fragile — `SynthesisStatus` values `"draft"` and `"revision_requested"` have no entry in `STATUS_LABELS`, so they display as raw strings.
- **Severity:** major
- **Action:** Either (a) add `SynthesisStatus` entries to `status-labels.ts` (creating a `SYNTHESIS_STATUS_LABELS` map and `SYNTHESIS_STATUS_BADGE_CLASSES` map) and update `StatusIndicator` to accept the discriminated union, or (b) restrict `StatusIndicator` to `DiscoveryStatus` only and create a separate `SynthesisStatusIndicator` that uses `SynthesisStatus` maps. Option (a) aligns with the existing shared-module pattern. This issue was flagged as deferred from Epic 8; it should be resolved before demo since `synthesis-viewer.tsx` passes `status: string` from a `SynthesisResultRow` to display.

---

### 3. `DiscoveryStatus` type in `status-labels.ts` is missing the `"revision_requested"` value from the DB enum — ordering differs
- **File:** `src/lib/synthesis/status-labels.ts:15–21` vs `src/lib/db/schema.ts:43–50`
- **Issue:** The `discoveryStatusEnum` in schema defines values in this order: `["collecting", "synthesizing", "draft", "in_review", "revision_requested", "approved"]`. The `DiscoveryStatus` union type in `status-labels.ts` defines: `"collecting" | "synthesizing" | "draft" | "in_review" | "approved" | "revision_requested"` — the order differs (`"approved"` comes before `"revision_requested"` in the type, opposite of the enum). While TypeScript unions are unordered, the ordering creates an inconsistency that makes auditing difficult. More critically, `projects.ts` re-exports its own `DiscoveryStatus` derived directly from the schema (`typeof discoveryStatusEnum.enumValues`), meaning there are now two `DiscoveryStatus` definitions in the codebase that could diverge if the enum changes.
- **Severity:** minor
- **Action:** Ensure only one canonical `DiscoveryStatus` type exists. Derive the type in `status-labels.ts` from the DB schema source of truth: `import { discoveryStatusEnum } from "@/lib/db/schema"; export type DiscoveryStatus = (typeof discoveryStatusEnum.enumValues)[number];` — then delete the manually written union. This matches the pattern already used in `projects.ts`.

---

### 4. `SpeechCard` body text uses `text-muted-foreground` for primary readable content
- **File:** `src/components/interview/speech-card.tsx:30`
- **Issue:** `<p className="text-muted-foreground text-base leading-relaxed whitespace-pre-wrap">{content}</p>`. The speech card body text — the user's actual transcribed interview response — is rendered in `text-muted-foreground` (#71717A). Per UX-DR11 and the explicit fix applied in Story 9.3, `text-muted-foreground` is reserved strictly for timestamps, metadata, and helper labels. The transcribed speech content is primary readable body text and should use `text-foreground`. This was the exact class-on-body-text pattern fixed in `text-alternative.tsx` and `diagram-text-alternative.tsx` in Story 9.3, but was missed in `speech-card.tsx`. WCAG AA technically passes (~5.3:1 on white), but this violates UX-DR11 which permits `muted-foreground` only for timestamps/metadata.
- **Severity:** minor
- **Action:** Change `text-muted-foreground` to `text-foreground` on the content `<p>` element in `speech-card.tsx`. The timestamp `<span>` correctly keeps `text-muted-foreground`.

---

### 5. Interview `loading.tsx` breakpoints use `md:` instead of `lg:` — mismatches actual page layout
- **File:** `src/app/interview/[token]/loading.tsx:3–47`
- **Issue:** The loading skeleton uses `md:flex-row`, `md:max-w-[55%]`, `md:border-r`, and the diagram panel uses `md:flex md:w-[45%]` (visible at 768px+). The actual `active/page.tsx` uses `lg:flex-row` and `lg:w-[55%]`, `lg:block` for the diagram panel — the split only occurs at 1024px+. The breakpoint system documented in story 9.1 (and implemented throughout) is: tablet (768px–1023px) = stacked layout with overlay; desktop (1024px+) = side-by-side. The skeleton gives the wrong visual impression on tablet: it shows a side-by-side layout when the real page would show stacked layout. This is a functional mismatch, not just cosmetic.
- **Severity:** minor
- **Action:** Change `md:flex-row` → `lg:flex-row`, `md:max-w-[55%]` → `lg:max-w-[55%]`, `md:border-r md:border-b-0` → `lg:border-r lg:border-b-0`, `hidden … md:flex md:w-[45%]` → `hidden lg:flex lg:w-[45%]` to match the actual `active/page.tsx` layout classes.

---

### 6. `error-handler.ts` still only handles 2 of the 6+ typed error classes
- **File:** `src/lib/api/error-handler.ts:10–29`
- **Issue:** `handleRouteError` handles only `NotFoundError` and `ConstraintViolationError`. Epic 9 routes use `StateTransitionError` (approve route, review route), `ValidationError`, `AuthorizationError`, and `LLMError` — all of which fall through to the generic 500 handler. The `approve/route.ts` and `processes/[nodeId]/synthesis/review/route.ts` work around this by catching `StateTransitionError` inline before calling `throw err`, but the comparison route uses `handleRouteError` directly. This pre-existing gap (flagged in `deferred-work.md` from Epic 8) was not addressed in Epic 9 despite new routes depending on it. Routes that reach uncaught `StateTransitionError` through `handleRouteError` will return 500 instead of 409.
- **Severity:** major
- **Action:** Add missing handlers to `handleRouteError`: `StateTransitionError` → 409, `ValidationError` → 400, `AuthorizationError` → 403, `LLMError` → 502. This resolves the deferred Epic 8 item and prevents the fallthrough 500 on correctible errors.

---

### 7. `synthesis/status/route.ts` POST does not guard `updateProjectDiscoveryStatus` zero-row update
- **File:** `src/app/api/projects/[projectId]/synthesis/status/route.ts:138–142`
- **Issue:** The POST handler verifies `result.status === "revision_requested"` (line 122), then calls `updateProjectDiscoveryStatus(projectId, targetDiscoveryStatus)`. No check is performed whether the project itself was deleted between the synthesis result lookup and the status update. The CLAUDE.md rule: *"when a service function performs a `db.update()` that may match zero rows, check the result length or affected-row count and either log a warning or throw — never let a zero-row UPDATE succeed silently."* This is a low-probability edge case but violates the explicit coding rule, and the error is caught only by the `NotFoundError` branch below — which would only fire if `updateProjectDiscoveryStatus` already throws `NotFoundError` on zero rows.
- **Severity:** minor
- **Action:** Confirm `updateProjectDiscoveryStatus` in `src/lib/db/queries/projects.ts` has a zero-row UPDATE guard that throws `NotFoundError`. If not, add one. The route's existing `catch` block already handles `NotFoundError` → 404, so the behavior would be correct once the guard is present.

---

### 8. `process-tree.tsx` keyboard handler calls `getVisibleNodeIds()` on every keydown — O(n) rebuild not memoized
- **File:** `src/components/project/process-tree.tsx:144–148`
- **Issue:** `handleKeyDown` calls `getVisibleNodeIds()` (a depth-first tree traversal) on every keyboard event. `getVisibleNodeIds` itself calls `getChildren` (which filters the `nodes` array) for every visible node. For a moderately large process tree (30+ nodes), this is O(n²) per keydown. The function is not memoized with `useMemo` and is not derived from a stable ref — it always re-traverses the entire tree on each Arrow key press.
- **Severity:** minor
- **Action:** Memoize `getVisibleNodeIds()` using `useMemo` with `[nodes, expandedIds]` as dependencies. The result only needs to change when the tree structure or expand state changes, not on every render or keydown.

---

### 9. `review-agent-panel.tsx` `sendMessage` includes full `messages` state in LLM payload but does not deduplicate the in-flight placeholder
- **File:** `src/components/synthesis/review-agent-panel.tsx:128–131`
- **Issue:** The `sendMessage` callback sends `conversationHistory: messages` in the POST body. However, at call time (line 116), an empty assistant message `{ role: "assistant", content: "" }` has already been pushed to `messages`. The `messages` state read by the closure includes this blank assistant entry appended before the fetch starts, meaning the conversation history sent to the API contains a trailing `{ role: "assistant", content: "" }` that was not yet produced by the LLM. This is a stale-closure issue: `messages` in `sendMessage` is captured at call time via the `useCallback` dep array `[inputText, isStreaming, messages, ...]`, so the blank placeholder is included in the payload.
- **Severity:** minor
- **Action:** Capture the history snapshot before appending the assistant placeholder, and pass that snapshot to the fetch body:
  ```ts
  const historySnapshot = [...messages]; // before appending placeholder
  setMessages((prev) => [...prev, userMessage]);
  setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
  // ... use historySnapshot in fetch body, not messages
  ```

---

### 10. `vitest.config.ts` global `environment: "node"` overrides per-file `@vitest-environment jsdom` in some test files
- **File:** `vitest.config.ts:6`
- **Issue:** The config sets `environment: "node"` as the default. Tests that need DOM APIs (all React component tests, including the newly created `diagram-text-alternative.test.tsx`, `speech-card.test.tsx`, `process-tree.test.tsx`) must have `/** @vitest-environment jsdom */` at the top of each file. The story dev notes confirm this pattern is used (e.g., `diagram-text-alternative.test.tsx` includes the docblock). However, if any new test file added during Epic 9 omits the docblock, it will fail with obscure `document is not defined` errors rather than a clear config error. Additionally, the project-wide default should arguably be `jsdom` since the overwhelming majority of test files are component tests — each of the 142 test files must opt in individually.
- **Severity:** minor
- **Action:** Consider changing the global `environment` to `"jsdom"` and adding `/** @vitest-environment node */` only on the true server-side test files (query functions, state machines, error handlers). This inverts the boilerplate burden and prevents future test files from silently running in the wrong environment. Alternatively, document the required docblock in `CLAUDE.md` coding rules.

---

### 11. `interview-toolbar.tsx` "View Diagram" button uses `md:flex` which shows it at 768px+ including desktop
- **File:** `src/components/interview/interview-toolbar.tsx:28`
- **Issue:** The button has `className="min-h-[44px] md:flex lg:hidden"`. Starting from `md:flex`, the button is visible from 768px all the way through 1023px (tablet range) — correct. However, the class combination `md:flex lg:hidden` means the button also briefly appears in the 768px–1023px window while the overlay is the only valid diagram path. This is the spec-correct behavior per story 9.1. However, the button is missing a `hidden` base class — without it, on mobile (<768px), the button renders even though interviews should be blocked on mobile (UnsupportedDevice). On mobile the interview page itself is blocked upstream, so this is low risk, but the missing `hidden` base class means in tests or any code path where the component is rendered outside the interview page, the button renders unconditionally.
- **Severity:** minor
- **Action:** Add `hidden` as the base class: `className="hidden min-h-[44px] md:flex lg:hidden"` to ensure the button is invisible by default below tablet breakpoint.

---

### 12. `process-tree.tsx` roving tabindex fallback logic has edge case when `focusedNodeId` is stale after tree refresh
- **File:** `src/components/project/process-tree.tsx:330–333`
- **Issue:** The roving tabindex logic: `const isFocused = focusedNodeId ? focusedNodeId === node.nodeId : isSelected`. After a tree refresh (`fetchTree`), `focusedNodeId` state is not reset. If the node that had keyboard focus was deleted or its `nodeId` changed, `focusedNodeId` points to a non-existent node, causing no node to receive `tabIndex=0` — the entire tree becomes unreachable via Tab key until the user clicks a node. The ref map (`nodeButtonRefs`) is cleaned up correctly via the `ref` callback, but the stale `focusedNodeId` state is never cleared.
- **Severity:** minor
- **Action:** In `fetchTree`'s `setNodes` callback (or after it), validate that `focusedNodeId` still exists in the new `treeNodes` array. If not, reset `setFocusedNodeId(null)` so the fallback `isSelected` logic takes over.

---

### 13. `synthesis/approve/route.ts` passes `session.userId` as `approvedBy` but `session.userId` for supervisor is the `supervisorId` UUID
- **File:** `src/app/api/projects/[projectId]/synthesis/approve/route.ts:96–98`
- **Issue:** `setApprovalMetadata(resultId, { approvedAt: new Date(), approvedBy: session.userId }, tx)`. The `approvedBy` column references `projectSupervisors.supervisorId` (FK). The `session.userId` for a supervisor session is set to `supervisor.supervisorId` (confirmed in `login/route.ts:95`). This is correct and consistent. However, the `setApprovalMetadata` function signature uses `approvedBy: string` with no type enforcement that this is a `supervisorId` — a PM accidentally calling this path would store a PM `userId` into a column that FK-references `projectSupervisors`. The route is guarded by `withSupervisorProjectAccess` so in practice this cannot happen through the current API, but the type safety gap is worth noting.
- **Severity:** minor
- **Action:** No immediate fix required — the auth middleware prevents the misuse. For defensive improvement, consider narrowing `setApprovalMetadata`'s type signature to require a verified supervisor context, or add a comment documenting that `approvedBy` must be a `supervisorId`.

---

### 14. `deferred-work.md` Epic 8 item on `STATUS_LABELS`/`STATUS_BADGE_CLASSES` duplication still open — Story 9.4 partially closed it but not fully
- **File:** `src/components/project/interview-list-view.tsx:23–29`, `src/lib/synthesis/status-labels.ts`
- **Issue:** The deferred Epic 8 item reads: *"STATUS_LABELS, STATUS_BADGE_CLASSES, and status arrays appear in 3+ files — extract them to a shared module on the second occurrence."* Story 9.4 consolidated `STATUS_BADGE_CLASSES` for `DiscoveryStatus` in `status-labels.ts` (already shared to `StatusIndicator` and `SupervisorProjectList`). However, `interview-list-view.tsx` still defines its own local `STATUS_BADGE_CLASS` map for interview statuses (`active`, `completed`, `captured`, `paused`, `pending`). This is a second, parallel badge-class map covering `interviewStatusEnum` values — it is not shared anywhere. Per CLAUDE.md: *"When two or more files define identical Tailwind class maps… extract them to a shared module on the second occurrence — never allow three-way duplication."* Currently only one instance exists for interview statuses, so the rule is not yet triggered, but this is exactly the pattern that tends to expand.
- **Severity:** minor
- **Action:** Update `deferred-work.md` to note that `interview-list-view.tsx`'s `STATUS_BADGE_CLASS` for `interviewStatusEnum` values is a candidate for the next shared-module extraction if a second component using interview-status badge classes is added.
I now have enough information to write a comprehensive review. Let me compile all findings:

---
agent_role: reviewer
task_id: epic-9-review
timestamp: 2026-04-13T15:49:42.236557+00:00
input_files: [CLAUDE.md, _bmad-output/implementation-artifacts/9-1-responsive-layout-tablet-desktop.md, _bmad-output/implementation-artifacts/9-2-keyboard-navigation-focus-management.md, _bmad-output/implementation-artifacts/9-3-color-contrast-aria-labels-text-alternatives.md, _bmad-output/implementation-artifacts/9-4-visual-polish-design-system-consistency.md, _bmad-output/implementation-artifacts/9-5-performance-audit-page-load-optimization.md, _bmad-output/implementation-artifacts/deferred-work.md, next.config.ts, rebuild-status.md, scripts/ci.sh, src/app/api/auth/login/route.test.ts, src/app/api/auth/login/route.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/review/route.test.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/review/route.ts, src/app/api/projects/[projectId]/settings/route.test.ts, src/app/api/projects/[projectId]/supervisors/route.test.ts, src/app/api/projects/[projectId]/supervisors/route.ts, src/app/api/projects/[projectId]/synthesis/approve/route.test.ts, src/app/api/projects/[projectId]/synthesis/approve/route.ts, src/app/api/projects/[projectId]/synthesis/review/comparison/route.test.ts, src/app/api/projects/[projectId]/synthesis/review/comparison/route.ts, src/app/api/projects/[projectId]/synthesis/review/edits/route.test.ts, src/app/api/projects/[projectId]/synthesis/review/individuals/route.test.ts, src/app/api/projects/[projectId]/synthesis/review/messages/route.test.ts, src/app/api/projects/[projectId]/synthesis/review/messages/route.ts, src/app/api/projects/[projectId]/synthesis/status/route.test.ts, src/app/api/projects/[projectId]/synthesis/status/route.ts, src/app/globals.css, src/app/interview/[token]/active/page.tsx, src/app/interview/[token]/loading.tsx, src/app/projects/[projectId]/loading.tsx, src/app/projects/loading.tsx, src/app/supervisor/projects/[projectId]/review/page.tsx, src/app/supervisor/projects/loading.tsx, src/components/interview/conversation-thread.test.tsx, src/components/interview/diagram-panel.tsx, src/components/interview/diagram-text-alternative.test.tsx, src/components/interview/diagram-text-alternative.tsx, src/components/interview/interview-input-controls.test.tsx, src/components/interview/interview-input-controls.tsx, src/components/interview/interview-toolbar.test.tsx, src/components/interview/interview-toolbar.tsx, src/components/interview/read-only-view.test.tsx, src/components/interview/speech-card.test.tsx, src/components/interview/speech-card.tsx, src/components/interview/typed-input-area.test.tsx, src/components/interview/typed-input-area.tsx, src/components/interview/voice-input-area.tsx, src/components/project/interview-list-view.test.tsx, src/components/project/interview-list-view.tsx, src/components/project/process-tree.test.tsx, src/components/project/process-tree.tsx, src/components/project/project-detail-layout.test.tsx, src/components/project/project-detail-layout.tsx, src/components/project/synthesis-readiness.test.tsx, src/components/project/synthesis-readiness.tsx, src/components/supervisor/project-list.test.tsx, src/components/supervisor/project-list.tsx, src/components/synthesis/approval-controls.tsx, src/components/synthesis/bpmn-chart.test.tsx, src/components/synthesis/bpmn-chart.tsx, src/components/synthesis/chart-controls.test.tsx, src/components/synthesis/comparison-view.tsx, src/components/synthesis/divergence-panel.test.tsx, src/components/synthesis/divergence-panel.tsx, src/components/synthesis/edit-history.test.tsx, src/components/synthesis/edit-history.tsx, src/components/synthesis/individual-carousel.tsx, src/components/synthesis/review-agent-panel.tsx, src/components/synthesis/review-summary.test.tsx, src/components/synthesis/review-summary.tsx, src/components/synthesis/status-indicator.tsx, src/components/synthesis/synthesis-viewer.test.tsx, src/components/synthesis/synthesis-viewer.tsx, src/components/synthesis/text-alternative.tsx, src/hooks/use-pan-zoom.ts, src/lib/api/error-handler.test.ts, src/lib/api/error-handler.ts, src/lib/auth/middleware.ts, src/lib/db/queries/projects.ts, src/lib/db/queries/revision-requests.ts, src/lib/db/queries/supervisors.ts, src/lib/db/queries/synthesis-edits.test.ts, src/lib/db/queries/synthesis-edits.ts, src/lib/db/queries/synthesis-results.test.ts, src/lib/db/queries/synthesis-results.ts, src/lib/db/schema.ts, src/lib/synthesis/review-agent.test.ts, src/lib/synthesis/review-agent.ts, src/lib/synthesis/status-labels.ts, src/lib/synthesis/synthesis-state-machine.test.ts, src/lib/synthesis/synthesis-state-machine.ts, src/types/synthesis.ts, vitest.config.ts]
reviewer_type: claude
review_scope: epic

---

# Epic Code Review — CLAUDE Reviewer

## Summary

Epic 9 successfully delivers responsive layout, keyboard accessibility, ARIA improvements, design system token compliance, and performance polish. The implementations are largely correct and follow CLAUDE.md rules well; however, a meaningful security gap exists in the `processes/[nodeId]/synthesis/review` route (IDOR), the `StatusIndicator` component silently swallows unrecognized `SynthesisStatus` values, the `status-labels.ts` `DiscoveryStatus` type definition diverges from the DB enum, and the loading skeleton files contain a minor but spec-violating breakpoint mismatch.

---

## Findings

### 1. IDOR: `review` route uses non-scoped `findSynthesisResultById` before project membership check
- **File:** `src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/review/route.ts:48–71`
- **Issue:** The route calls `findSynthesisResultById(resultId)` (unscoped, no `projectId` filter) then manually compares `result.projectId !== projectId` at line 61. This is a two-step load-then-check pattern — a TOCTOU window exists between the read and the manual comparison, and it violates the CLAUDE.md rule: *"always verify the entity belongs to that project before performing any mutations — use a scoped query function that includes `projectId` in the WHERE clause rather than relying on per-route manual checks."* The function `findSynthesisResultByIdAndProject` already exists and is used correctly in all other routes. A `findSynthesisResultById` call here crosses project data boundaries before the check completes.
- **Severity:** major
- **Action:** Replace `findSynthesisResultById` + manual `result.projectId !== projectId` check with a single call to `findSynthesisResultByIdAndProject(resultId, projectId)`, returning 404 if null. Remove the manual comparison block (lines 61–71).

---

### 2. `StatusIndicator` silently treats unknown `SynthesisStatus` values as `DiscoveryStatus`
- **File:** `src/components/synthesis/status-indicator.tsx:22–26`
- **Issue:** The component accepts `status: string` and does `STATUS_LABELS[status as keyof typeof STATUS_LABELS]`. `STATUS_LABELS` is typed `Record<DiscoveryStatus, string>` (only `DiscoveryStatus` keys). When called with a `SynthesisStatus` value like `"in_review"` (which happens to overlap) it works accidentally; when called with `"draft"` or `"revision_requested"` it falls back to displaying the raw string. This is the exact "never mix status columns" anti-pattern documented in CLAUDE.md and in `deferred-work.md` (epic-8 deferred item: *"Status constants duplicated across… status-indicator.tsx"*). The component currently works for the overlapping values but is structurally incorrect and fragile — `SynthesisStatus` values `"draft"` and `"revision_requested"` have no entry in `STATUS_LABELS`, so they display as raw strings.
- **Severity:** major
- **Action:** Either (a) add `SynthesisStatus` entries to `status-labels.ts` (creating a `SYNTHESIS_STATUS_LABELS` map and `SYNTHESIS_STATUS_BADGE_CLASSES` map) and update `StatusIndicator` to accept the discriminated union, or (b) restrict `StatusIndicator` to `DiscoveryStatus` only and create a separate `SynthesisStatusIndicator` that uses `SynthesisStatus` maps. Option (a) aligns with the existing shared-module pattern. This issue was flagged as deferred from Epic 8; it should be resolved before demo since `synthesis-viewer.tsx` passes `status: string` from a `SynthesisResultRow` to display.

---

### 3. `DiscoveryStatus` type in `status-labels.ts` is missing the `"revision_requested"` value from the DB enum — ordering differs
- **File:** `src/lib/synthesis/status-labels.ts:15–21` vs `src/lib/db/schema.ts:43–50`
- **Issue:** The `discoveryStatusEnum` in schema defines values in this order: `["collecting", "synthesizing", "draft", "in_review", "revision_requested", "approved"]`. The `DiscoveryStatus` union type in `status-labels.ts` defines: `"collecting" | "synthesizing" | "draft" | "in_review" | "approved" | "revision_requested"` — the order differs (`"approved"` comes before `"revision_requested"` in the type, opposite of the enum). While TypeScript unions are unordered, the ordering creates an inconsistency that makes auditing difficult. More critically, `projects.ts` re-exports its own `DiscoveryStatus` derived directly from the schema (`typeof discoveryStatusEnum.enumValues`), meaning there are now two `DiscoveryStatus` definitions in the codebase that could diverge if the enum changes.
- **Severity:** minor
- **Action:** Ensure only one canonical `DiscoveryStatus` type exists. Derive the type in `status-labels.ts` from the DB schema source of truth: `import { discoveryStatusEnum } from "@/lib/db/schema"; export type DiscoveryStatus = (typeof discoveryStatusEnum.enumValues)[number];` — then delete the manually written union. This matches the pattern already used in `projects.ts`.

---

### 4. `SpeechCard` body text uses `text-muted-foreground` for primary readable content
- **File:** `src/components/interview/speech-card.tsx:30`
- **Issue:** `<p className="text-muted-foreground text-base leading-relaxed whitespace-pre-wrap">{content}</p>`. The speech card body text — the user's actual transcribed interview response — is rendered in `text-muted-foreground` (#71717A). Per UX-DR11 and the explicit fix applied in Story 9.3, `text-muted-foreground` is reserved strictly for timestamps, metadata, and helper labels. The transcribed speech content is primary readable body text and should use `text-foreground`. This was the exact class-on-body-text pattern fixed in `text-alternative.tsx` and `diagram-text-alternative.tsx` in Story 9.3, but was missed in `speech-card.tsx`. WCAG AA technically passes (~5.3:1 on white), but this violates UX-DR11 which permits `muted-foreground` only for timestamps/metadata.
- **Severity:** minor
- **Action:** Change `text-muted-foreground` to `text-foreground` on the content `<p>` element in `speech-card.tsx`. The timestamp `<span>` correctly keeps `text-muted-foreground`.

---

### 5. Interview `loading.tsx` breakpoints use `md:` instead of `lg:` — mismatches actual page layout
- **File:** `src/app/interview/[token]/loading.tsx:3–47`
- **Issue:** The loading skeleton uses `md:flex-row`, `md:max-w-[55%]`, `md:border-r`, and the diagram panel uses `md:flex md:w-[45%]` (visible at 768px+). The actual `active/page.tsx` uses `lg:flex-row` and `lg:w-[55%]`, `lg:block` for the diagram panel — the split only occurs at 1024px+. The breakpoint system documented in story 9.1 (and implemented throughout) is: tablet (768px–1023px) = stacked layout with overlay; desktop (1024px+) = side-by-side. The skeleton gives the wrong visual impression on tablet: it shows a side-by-side layout when the real page would show stacked layout. This is a functional mismatch, not just cosmetic.
- **Severity:** minor
- **Action:** Change `md:flex-row` → `lg:flex-row`, `md:max-w-[55%]` → `lg:max-w-[55%]`, `md:border-r md:border-b-0` → `lg:border-r lg:border-b-0`, `hidden … md:flex md:w-[45%]` → `hidden lg:flex lg:w-[45%]` to match the actual `active/page.tsx` layout classes.

---

### 6. `error-handler.ts` still only handles 2 of the 6+ typed error classes
- **File:** `src/lib/api/error-handler.ts:10–29`
- **Issue:** `handleRouteError` handles only `NotFoundError` and `ConstraintViolationError`. Epic 9 routes use `StateTransitionError` (approve route, review route), `ValidationError`, `AuthorizationError`, and `LLMError` — all of which fall through to the generic 500 handler. The `approve/route.ts` and `processes/[nodeId]/synthesis/review/route.ts` work around this by catching `StateTransitionError` inline before calling `throw err`, but the comparison route uses `handleRouteError` directly. This pre-existing gap (flagged in `deferred-work.md` from Epic 8) was not addressed in Epic 9 despite new routes depending on it. Routes that reach uncaught `StateTransitionError` through `handleRouteError` will return 500 instead of 409.
- **Severity:** major
- **Action:** Add missing handlers to `handleRouteError`: `StateTransitionError` → 409, `ValidationError` → 400, `AuthorizationError` → 403, `LLMError` → 502. This resolves the deferred Epic 8 item and prevents the fallthrough 500 on correctible errors.

---

### 7. `synthesis/status/route.ts` POST does not guard `updateProjectDiscoveryStatus` zero-row update
- **File:** `src/app/api/projects/[projectId]/synthesis/status/route.ts:138–142`
- **Issue:** The POST handler verifies `result.status === "revision_requested"` (line 122), then calls `updateProjectDiscoveryStatus(projectId, targetDiscoveryStatus)`. No check is performed whether the project itself was deleted between the synthesis result lookup and the status update. The CLAUDE.md rule: *"when a service function performs a `db.update()` that may match zero rows, check the result length or affected-row count and either log a warning or throw — never let a zero-row UPDATE succeed silently."* This is a low-probability edge case but violates the explicit coding rule, and the error is caught only by the `NotFoundError` branch below — which would only fire if `updateProjectDiscoveryStatus` already throws `NotFoundError` on zero rows.
- **Severity:** minor
- **Action:** Confirm `updateProjectDiscoveryStatus` in `src/lib/db/queries/projects.ts` has a zero-row UPDATE guard that throws `NotFoundError`. If not, add one. The route's existing `catch` block already handles `NotFoundError` → 404, so the behavior would be correct once the guard is present.

---

### 8. `process-tree.tsx` keyboard handler calls `getVisibleNodeIds()` on every keydown — O(n) rebuild not memoized
- **File:** `src/components/project/process-tree.tsx:144–148`
- **Issue:** `handleKeyDown` calls `getVisibleNodeIds()` (a depth-first tree traversal) on every keyboard event. `getVisibleNodeIds` itself calls `getChildren` (which filters the `nodes` array) for every visible node. For a moderately large process tree (30+ nodes), this is O(n²) per keydown. The function is not memoized with `useMemo` and is not derived from a stable ref — it always re-traverses the entire tree on each Arrow key press.
- **Severity:** minor
- **Action:** Memoize `getVisibleNodeIds()` using `useMemo` with `[nodes, expandedIds]` as dependencies. The result only needs to change when the tree structure or expand state changes, not on every render or keydown.

---

### 9. `review-agent-panel.tsx` `sendMessage` includes full `messages` state in LLM payload but does not deduplicate the in-flight placeholder
- **File:** `src/components/synthesis/review-agent-panel.tsx:128–131`
- **Issue:** The `sendMessage` callback sends `conversationHistory: messages` in the POST body. However, at call time (line 116), an empty assistant message `{ role: "assistant", content: "" }` has already been pushed to `messages`. The `messages` state read by the closure includes this blank assistant entry appended before the fetch starts, meaning the conversation history sent to the API contains a trailing `{ role: "assistant", content: "" }` that was not yet produced by the LLM. This is a stale-closure issue: `messages` in `sendMessage` is captured at call time via the `useCallback` dep array `[inputText, isStreaming, messages, ...]`, so the blank placeholder is included in the payload.
- **Severity:** minor
- **Action:** Capture the history snapshot before appending the assistant placeholder, and pass that snapshot to the fetch body:
  ```ts
  const historySnapshot = [...messages]; // before appending placeholder
  setMessages((prev) => [...prev, userMessage]);
  setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
  // ... use historySnapshot in fetch body, not messages
  ```

---

### 10. `vitest.config.ts` global `environment: "node"` overrides per-file `@vitest-environment jsdom` in some test files
- **File:** `vitest.config.ts:6`
- **Issue:** The config sets `environment: "node"` as the default. Tests that need DOM APIs (all React component tests, including the newly created `diagram-text-alternative.test.tsx`, `speech-card.test.tsx`, `process-tree.test.tsx`) must have `/** @vitest-environment jsdom */` at the top of each file. The story dev notes confirm this pattern is used (e.g., `diagram-text-alternative.test.tsx` includes the docblock). However, if any new test file added during Epic 9 omits the docblock, it will fail with obscure `document is not defined` errors rather than a clear config error. Additionally, the project-wide default should arguably be `jsdom` since the overwhelming majority of test files are component tests — each of the 142 test files must opt in individually.
- **Severity:** minor
- **Action:** Consider changing the global `environment` to `"jsdom"` and adding `/** @vitest-environment node */` only on the true server-side test files (query functions, state machines, error handlers). This inverts the boilerplate burden and prevents future test files from silently running in the wrong environment. Alternatively, document the required docblock in `CLAUDE.md` coding rules.

---

### 11. `interview-toolbar.tsx` "View Diagram" button uses `md:flex` which shows it at 768px+ including desktop
- **File:** `src/components/interview/interview-toolbar.tsx:28`
- **Issue:** The button has `className="min-h-[44px] md:flex lg:hidden"`. Starting from `md:flex`, the button is visible from 768px all the way through 1023px (tablet range) — correct. However, the class combination `md:flex lg:hidden` means the button also briefly appears in the 768px–1023px window while the overlay is the only valid diagram path. This is the spec-correct behavior per story 9.1. However, the button is missing a `hidden` base class — without it, on mobile (<768px), the button renders even though interviews should be blocked on mobile (UnsupportedDevice). On mobile the interview page itself is blocked upstream, so this is low risk, but the missing `hidden` base class means in tests or any code path where the component is rendered outside the interview page, the button renders unconditionally.
- **Severity:** minor
- **Action:** Add `hidden` as the base class: `className="hidden min-h-[44px] md:flex lg:hidden"` to ensure the button is invisible by default below tablet breakpoint.

---

### 12. `process-tree.tsx` roving tabindex fallback logic has edge case when `focusedNodeId` is stale after tree refresh
- **File:** `src/components/project/process-tree.tsx:330–333`
- **Issue:** The roving tabindex logic: `const isFocused = focusedNodeId ? focusedNodeId === node.nodeId : isSelected`. After a tree refresh (`fetchTree`), `focusedNodeId` state is not reset. If the node that had keyboard focus was deleted or its `nodeId` changed, `focusedNodeId` points to a non-existent node, causing no node to receive `tabIndex=0` — the entire tree becomes unreachable via Tab key until the user clicks a node. The ref map (`nodeButtonRefs`) is cleaned up correctly via the `ref` callback, but the stale `focusedNodeId` state is never cleared.
- **Severity:** minor
- **Action:** In `fetchTree`'s `setNodes` callback (or after it), validate that `focusedNodeId` still exists in the new `treeNodes` array. If not, reset `setFocusedNodeId(null)` so the fallback `isSelected` logic takes over.

---

### 13. `synthesis/approve/route.ts` passes `session.userId` as `approvedBy` but `session.userId` for supervisor is the `supervisorId` UUID
- **File:** `src/app/api/projects/[projectId]/synthesis/approve/route.ts:96–98`
- **Issue:** `setApprovalMetadata(resultId, { approvedAt: new Date(), approvedBy: session.userId }, tx)`. The `approvedBy` column references `projectSupervisors.supervisorId` (FK). The `session.userId` for a supervisor session is set to `supervisor.supervisorId` (confirmed in `login/route.ts:95`). This is correct and consistent. However, the `setApprovalMetadata` function signature uses `approvedBy: string` with no type enforcement that this is a `supervisorId` — a PM accidentally calling this path would store a PM `userId` into a column that FK-references `projectSupervisors`. The route is guarded by `withSupervisorProjectAccess` so in practice this cannot happen through the current API, but the type safety gap is worth noting.
- **Severity:** minor
- **Action:** No immediate fix required — the auth middleware prevents the misuse. For defensive improvement, consider narrowing `setApprovalMetadata`'s type signature to require a verified supervisor context, or add a comment documenting that `approvedBy` must be a `supervisorId`.

---

### 14. `deferred-work.md` Epic 8 item on `STATUS_LABELS`/`STATUS_BADGE_CLASSES` duplication still open — Story 9.4 partially closed it but not fully
- **File:** `src/components/project/interview-list-view.tsx:23–29`, `src/lib/synthesis/status-labels.ts`
- **Issue:** The deferred Epic 8 item reads: *"STATUS_LABELS, STATUS_BADGE_CLASSES, and status arrays appear in 3+ files — extract them to a shared module on the second occurrence."* Story 9.4 consolidated `STATUS_BADGE_CLASSES` for `DiscoveryStatus` in `status-labels.ts` (already shared to `StatusIndicator` and `SupervisorProjectList`). However, `interview-list-view.tsx` still defines its own local `STATUS_BADGE_CLASS` map for interview statuses (`active`, `completed`, `captured`, `paused`, `pending`). This is a second, parallel badge-class map covering `interviewStatusEnum` values — it is not shared anywhere. Per CLAUDE.md: *"When two or more files define identical Tailwind class maps… extract them to a shared module on the second occurrence — never allow three-way duplication."* Currently only one instance exists for interview statuses, so the rule is not yet triggered, but this is exactly the pattern that tends to expand.
- **Severity:** minor
- **Action:** Update `deferred-work.md` to note that `interview-list-view.tsx`'s `STATUS_BADGE_CLASS` for `interviewStatusEnum` values is a candidate for the next shared-module extraction if a second component using interview-status badge classes is added.
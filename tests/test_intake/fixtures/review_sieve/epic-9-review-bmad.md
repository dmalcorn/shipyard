I'll activate as Amelia and immediately execute the code review as instructed.
In AUTOMATED PIPELINE MODE — no human input available. The review target is an explicit file list provided in the pipeline command. Proceeding directly with the review using the provided file list.

**Resolution:** Tier 1 — Explicit file list provided. Constructing diff from provided files.
Now let me read the remaining key files for the review — particularly the test files and remaining route files to verify correctness.
Now I have sufficient context to perform a thorough code review. Let me read the step-02 file to understand the review structure I should follow.
I now have sufficient context to perform all three review layers and produce the complete report. This is AUTOMATED PIPELINE MODE — no human input, no spec file provided (no-spec mode). I'll execute all three review layers internally and triage.

---

## Code Review — Epic 9 (Stories 9-1 through 9-5)

**Review Mode:** `no-spec` (no spec file provided)
**Diff Stats:** 94 files changed, 4,281 insertions, 735 deletions
**Acceptance Auditor:** Skipped — no spec file provided.

---

### LAYER 1: Blind Hunter (Adversarial Review)

**B-01 — `usePanZoom`: stale closure in `onMouseMove`**
`src/hooks/use-pan-zoom.ts:67-77`
`onMouseMove` captures `isPanning` and `panStart` via closure but these are React state values. Because `handlers` is constructed synchronously on each render without `useCallback`, the closure is fresh each render — acceptable. However `onMouseDown` sets `isPanning` + `panStart` state, and `onMouseMove` reads them in the same render cycle's closure. There is a known React pitfall: if `onMouseDown` and `onMouseMove` fire faster than React batches state, `isPanning` may still be `false` inside `onMouseMove`. This is a latent bug on fast pointer events but not blocking.

**B-02 — `StatusIndicator` silently renders stale status string for unknown values**
`src/components/synthesis/status-indicator.tsx:22-25`
The fallback `?? status` means any typo in `status` passed from a DB row silently renders raw DB string. This is acceptable for robustness but is a potential XSS-safe leak of internal DB state to users.

**B-03 — `handleSynthSvgClick` divergence matching is fragile**
`src/components/synthesis/comparison-view.tsx:370-377`
Node ID matching uses `nodeId.startsWith("S_") && nodeId.includes("_${sanitized}")` — this can produce false positives when a sanitized step ID substring appears in a different node ID. If two step IDs share a common prefix after sanitization, the wrong step is matched. Low probability but deterministic bug.

**B-04 — `parseProposalFromResponse` does not validate `changeType` against known enum**
`src/app/api/projects/[projectId]/synthesis/review/messages/route.ts:44-46`
The parsed `changeType` string from LLM output is forwarded to the client without validating it against `ProposedEdit.changeType` enum values. An LLM hallucinating an unknown `changeType` (e.g. `"delete_all"`) would be forwarded to the edits route, which calls `applyReviewEdit`, which would hit the default `throw new ConstraintViolationError("Unknown changeType")` — so data integrity is preserved server-side, but the client receives a 400 error with no user-friendly guidance. Medium UX defect, not a security bug.

**B-05 — `review-agent.ts` `applyAddStep` always auto-assigns sequence, ignoring LLM-provided sequence**
`src/lib/synthesis/review-agent.ts:130-135`
Comment says "Always auto-assign sequence to prevent LLM-hallucinated duplicates (A-10)". But this means if a supervisor explicitly asks the LLM to insert a step at sequence 2 between existing steps 1 and 3, the LLM sets `sequence: 2` but the server ignores it and sets `maxSeq + 1 = 4` (appending). The proposed edit description says "insert at position 2" but the result is appended. Functional regression vs. user intent.

**B-06 — `getMostRecentSynthesisAcrossProject` has undocumented multi-node limitation**
`src/lib/db/queries/synthesis-results.ts:401-410`
The function now has a note in the docstring acknowledging this is wrong for multi-node projects, but the actual query has no `processNodeId` filtering. Callers (synthesis status route, supervisor review page) may silently return the wrong node's synthesis for multi-node projects. Noted as Phase 2, acceptable for MVP.

**B-07 — `review-agent-panel.tsx` sends entire conversation history on every message**
`src/components/synthesis/review-agent-panel.tsx:130-132`
`conversationHistory: messages` sends the full accumulated message array on every request. This grows without bound across a review session. No size cap enforced client-side (server caps at 50 entries via Zod, but client sends all). The first 50 messages are sent; beyond 50 the server silently truncates. The client has no feedback that history was truncated. Low severity.

**B-08 — Inconsistent `dangerouslySetInnerHTML` aria role missing**
`src/components/synthesis/comparison-view.tsx:507-519` and `src/components/synthesis/individual-carousel.tsx:255-264`
SVG diagram containers rendered via `dangerouslySetInnerHTML` lack `role="img"` and `aria-label`. The parent `div` has `role="region"` and `aria-label` but the inner SVG content itself is not accessible to screen readers navigating by landmark. The `DiagramTextAlternative` / `TextAlternative` components partially address this but are not always present alongside these canvases.

**B-09 — `synthesis-state-machine.ts` second SELECT after zero-row UPDATE is not scoped by projectId**
`src/lib/synthesis/synthesis-state-machine.ts:80-92`
The follow-up `SELECT` to distinguish "not found" vs "wrong status" only checks `eq(synthesisResults.resultId, resultId)` — not `projectId`. This is purely diagnostic (doesn't mutate), so no IDOR risk, but it could expose status of a row belonging to a different project in error messages. Low.

**B-10 — `comparison-view.tsx` hardcoded `bg-green-50 border-green-200 text-green-800` colors**
`src/components/synthesis/comparison-view.tsx:170-178`
Status banners use raw Tailwind color literals instead of design system CSS variables (`--success`, `--success-soft`). Breaks dark mode and design system consistency.

**B-11 — Missing `aria-label` on hamburger button text**
`src/components/project/project-detail-layout.tsx:138`
The hamburger button renders a `☰` Unicode character as its visible label. `aria-label="Open navigation"` is present, but the `☰` character renders as text to some screen readers (announced as "trigram for heaven"). `aria-hidden="true"` should be on the `☰` span. This is a minor accessibility defect.

---

### LAYER 2: Edge Case Hunter

**E-01 — `transitionSynthesisStatus` TOCTOU between UPDATE and fallback SELECT**
`src/lib/synthesis/synthesis-state-machine.ts:66-95`
When the UPDATE returns zero rows and the follow-up SELECT also returns zero rows, the error thrown is "not found". But in a concurrent request scenario: Request A transitions `draft→in_review` (UPDATE succeeds, returns 1 row). Request B (race) also attempts `draft→in_review`, UPDATE returns 0 rows (status is now `in_review`, not `draft`). The follow-up SELECT finds the row, returns `existing.status = "in_review"`. Error message: `"expected draft — transition to in_review rejected"`. This is correct behavior. The TOCTOU is benign here because the WHERE clause enforcing `from` status prevents double-transition. ✓ Handled.

**E-02 — `applyReviewEdit` status guard checks `in_review` but `applyAddStep` etc. do not re-validate after transaction starts**
`src/lib/synthesis/review-agent.ts:42-47`
Status is validated before the transaction (`row.status !== "in_review"`). Inside the transaction, `updateSynthesisResultWorkflowJson` does a blind UPDATE by `resultId` only (no status check). A concurrent approval that transitions to `approved` between the status check and the UPDATE would allow a workflow mutation on an already-approved result. This is a real TOCTOU window.

- The inner UPDATE (`updateSynthesisResultWorkflowJson`) does not include a status condition in its WHERE clause.
- Mitigation requires either: (a) `SELECT FOR UPDATE` / advisory lock, or (b) including `AND status = 'in_review'` in the workflow JSON UPDATE.
- **Severity: Medium** — requires concurrent requests from the same supervisor session, unlikely but possible.

**E-03 — `processTree.tsx` `getVisibleNodeIds()` called inline inside `handleKeyDown` on every keystroke**
`src/components/project/process-tree.tsx:148`
`getVisibleNodeIds()` traverses `nodes` and `expandedIds` on every keydown event. For large trees (50+ nodes), this is O(n) per keystroke with nested `getChildren` calls that also filter the full nodes array. `getChildren` itself uses `Array.filter` (O(n)) inside `traverse`, making `getVisibleNodeIds` O(n²). For typical process trees (5-20 nodes) this is negligible, but should be noted.

**E-04 — `DiagramTextAlternative` regex for step matching is overly broad**
`src/components/interview/diagram-text-alternative.tsx:36-42`
The regex `/(\w+)[[\]({]+["']?([^"\]})]+)["']?[\]})]+/` will match inside connection lines too (e.g., `A --> B[Label]`). The code checks `!steps.find((s) => s.id === id)` for deduplication, which handles this, but a connection line with a bracket syntax like `A --> B["text"]` may add `B` as a step before the connection matcher runs on that same line, causing `B` to appear twice in steps (once from step-match, once from connection-match adding the `from` node). Low severity, display-only.

**E-05 — `withSupervisorProjectAccess` PM path — does NOT verify project exists before calling `getProjectById`**
`src/lib/auth/middleware.ts:121-133`
In the PM branch of `withSupervisorProjectAccess`, `getProjectById(projectId)` is called. If the project doesn't exist, `!project` returns 403 "no access" instead of 404 "not found". This is a minor UX inconsistency (403 vs 404) but prevents information leakage (correct security behavior).

**E-06 — `loadingScreen` skeletons use hardcoded `md:` breakpoints, page uses `lg:`**
`src/app/interview/[token]/loading.tsx` vs `src/app/interview/[token]/active/page.tsx`
The loading skeleton uses `md:flex-row` / `md:max-w-[55%]` (768px breakpoint) but the actual page uses `lg:flex-row` / `lg:w-[55%]` (1024px breakpoint). This means there is a layout mismatch between the loading skeleton and the actual page at 768-1024px viewport widths. The skeleton shows a side-by-side layout but the actual page shows stacked. The skeleton also uses `md:flex` for the diagram panel while the page uses `lg:block`.

**E-07 — `getSvgElement` called synchronously after `importXml` resolves — bpmn-js may not have completed rendering**
`src/components/synthesis/bpmn-chart.tsx:70`
`getSvgElement()` is called immediately after `importXml(bpmnXml).then(result => ...)`. The `bpmn-js` `importXml` resolves when the XML is parsed and the diagram model is created, but the SVG may still be in the DOM rendering queue. This is a known bpmn-js timing issue. The SVG element ref captured by `onSvgRendered` may be incomplete on first render.

**E-08 — `handleMove` in process-tree uses `sortOrder` swap without atomicity guarantee**
`src/components/project/process-tree.tsx:291-321`
The PUT request sends `{ sortOrder: targetSortOrder }` — it writes the clicked node's sort order to the sibling's sort order value. If two rapid move operations are made before the first fetchTree completes, the UI may show a stale nodes array and the second PUT may operate on the wrong sibling `sortOrder` value. Race condition between `fetchTree` completion and next move action.

**E-09 — `status` field in `synthesis-status/route.ts` POST returns `targetDiscoveryStatus` (project-level) not synthesis row status**
`src/app/api/projects/[projectId]/synthesis/status/route.ts:141`
The POST response `{ data: { status: targetDiscoveryStatus } }` returns the project `discoveryStatus` ("collecting" or "synthesizing"), not the synthesis result status. The client (`SynthesisStatusPanel`) consumes this to update its UI. If the PM panel displays "collecting" as the synthesis status this creates a conceptual mismatch — it is actually the project lifecycle status. The distinction is correct per the route's design intent but may confuse callers.

**E-10 — `review-agent-panel.tsx` SSE buffer splitting on `\n\n` may split multi-line SSE events**
`src/components/synthesis/review-agent-panel.tsx:154-155`
The SSE parser splits on `\n\n` but if a JSON payload contains a literal `\n\n` (e.g., inside a `description` field with paragraph breaks), the part-splitting would incorrectly split the SSE event. Standard SSE parsers handle this by only treating line-level `data:` prefixes as delimiters. This is a rare but real edge case for long LLM responses.

---

### LAYER 3: Acceptance Auditor — Skipped (no spec file provided)

---

## TRIAGE

| ID | Source | Title | Location | Category |
|----|--------|-------|----------|----------|
| B-01 | blind | `usePanZoom` stale closure: `isPanning` may not reflect latest state in `onMouseMove` | `src/hooks/use-pan-zoom.ts:67` | defer |
| B-02 | blind | `StatusIndicator` renders raw DB status string for unknown values | `src/components/synthesis/status-indicator.tsx:22` | dismiss |
| B-03 | blind | `handleSynthSvgClick` divergence node matching can false-positive on shared step ID substrings | `src/components/synthesis/comparison-view.tsx:370` | patch |
| B-04 | blind | `parseProposalFromResponse` forwards unvalidated `changeType` from LLM | `src/app/api/projects/[projectId]/synthesis/review/messages/route.ts:44` | patch |
| B-05 | blind | `applyAddStep` ignores LLM-provided sequence — always appends | `src/lib/synthesis/review-agent.ts:130` | patch |
| B-06 | blind | `getMostRecentSynthesisAcrossProject` returns wrong node for multi-node projects | `src/lib/db/queries/synthesis-results.ts:401` | defer |
| B-07 | blind | `review-agent-panel` sends unbounded conversation history — silent truncation beyond 50 | `src/components/synthesis/review-agent-panel.tsx:130` | defer |
| B-08 | blind | Diagram SVG containers lack `role="img"` and inner `aria-label` | `comparison-view.tsx:507`, `individual-carousel.tsx:255` | patch |
| B-09 | blind | Fallback SELECT in state machine not scoped by `projectId` — minor info leak in error messages | `src/lib/synthesis/synthesis-state-machine.ts:80` | defer |
| B-10 | blind | Approval banners use hardcoded Tailwind colors, not design-system CSS vars | `src/components/synthesis/comparison-view.tsx:170` | patch |
| B-11 | blind | Hamburger `☰` character not `aria-hidden` | `src/components/project/project-detail-layout.tsx:138` | patch |
| E-02 | edge | `applyReviewEdit` TOCTOU: workflow JSON updated without status check in transaction | `src/lib/synthesis/review-agent.ts:62` | patch |
| E-06 | edge | Loading skeleton uses `md:` breakpoints, actual page uses `lg:` — layout mismatch at 768–1024px | `src/app/interview/[token]/loading.tsx:3` | patch |
| E-07 | edge | `getSvgElement()` called before bpmn-js SVG rendering completes — stale ref | `src/components/synthesis/bpmn-chart.tsx:70` | defer |
| E-08 | edge | `handleMove` race: rapid clicks may use stale `sortOrder` from pre-refresh nodes array | `src/components/project/process-tree.tsx:291` | defer |
| E-10 | edge | SSE buffer split on `\n\n` breaks on multi-line JSON values in LLM response | `src/components/synthesis/review-agent-panel.tsx:154` | defer |

**Dismissed:** B-02 (fallback to raw string is safe, explicit design intent), E-01 (TOCTOU is benign — WHERE clause guards), E-03 (O(n²) on small trees, negligible), E-04 (display-only regex quirk, deduplication handles it), E-05 (correct security behavior), E-09 (design intent, not a bug).

---

## FINAL REPORT

**Code review complete.** 7 `patch`, 6 `defer`, 3 dismissed as noise. No spec file provided — no Acceptance Auditor run.

Findings are listed below. No story file was provided, so nothing was persisted to a file.

---

### PATCH FINDINGS (must fix)

---

**[P-1] `handleSynthSvgClick` can false-positive on step ID substrings**
`src/components/synthesis/comparison-view.tsx:370–377`

The Mermaid node ID matching logic:
```ts
if (nodeId.startsWith(`S_`) && nodeId.includes(`_${sanitized}`)) {
```
If two steps have IDs where one sanitized ID is a substring of another (e.g., `step_abc` and `step_abcdef`), the shorter step's pattern matches both Mermaid node elements. The check should require the sanitized segment to be followed by `_` or end of string (or a digit for Mermaid's uniqueness suffix):

**Fix:** Change to a stricter match, e.g.:
```ts
const pattern = new RegExp(`_${sanitized}(_\\d+)?$`);
if (nodeId.startsWith("S_") && pattern.test(nodeId)) {
```

---

**[P-2] `parseProposalFromResponse` forwards unvalidated `changeType` to client**
`src/app/api/projects/[projectId]/synthesis/review/messages/route.ts:44–46`

`changeType` from the LLM JSON block is forwarded in the SSE `proposal` event without validation against the `ProposedEdit.changeType` enum. The edits route rejects unknown types server-side with a 400, but with no user-facing explanation.

**Fix:** Add a `VALID_CHANGE_TYPES` set check inside `parseProposalFromResponse` and return `null` (skip proposal emission) if `changeType` is not in the allowed set. This prevents a confusing error when the user clicks "Apply".

---

**[P-3] `applyAddStep` ignores LLM-provided sequence — always appends**
`src/lib/synthesis/review-agent.ts:130–135`

The comment says "Always auto-assign sequence to prevent LLM-hallucinated duplicates" but this discards the supervisor's explicit intent when they ask to insert a step at a specific position. The actual concern (duplicate sequences) can be addressed by normalizing sequences post-insert rather than discarding the target position.

**Fix:** Use the LLM-provided `sequence` when it is within valid range (`1 <= seq <= maxSeq + 1`); fall back to `maxSeq + 1` only when out of range or absent. After inserting, normalize sequences to maintain a contiguous 1…N ordering.

---

**[P-4] Diagram SVG containers lack accessible `role` and `aria-label`**
`src/components/synthesis/comparison-view.tsx:493–519`
`src/components/synthesis/individual-carousel.tsx:245–265`

The `div` containers receiving `dangerouslySetInnerHTML` SVG content have no `role="img"` or `aria-label`. Screen reader users cannot identify these as diagrams. The outer `role="region"` landmark exists on the panel, but the diagram canvas itself is invisible to AT.

**Fix:** Add `role="img"` and `aria-label="Synthesis workflow diagram"` (or per-context label) to the inner div wrapping the `dangerouslySetInnerHTML` SVG. Pair with the existing `TextAlternative`/`DiagramTextAlternative` component via `aria-describedby`.

---

**[P-5] Approval banners use hardcoded Tailwind colors instead of CSS variables**
`src/components/synthesis/comparison-view.tsx:169–181`

```tsx
className="m-4 rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-800"
className="m-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
```

These bypass the design system (`--success`, `--success-soft`, `--warning`, `--warning-soft`) and break dark mode. Every other status badge in the codebase uses CSS variable-backed classes.

**Fix:**
```tsx
className="m-4 rounded-lg border border-[var(--success)] bg-[var(--success-soft)] p-4 text-sm text-[var(--success)]"
className="m-4 rounded-lg border border-[var(--warning)] bg-[var(--warning-soft)] p-4 text-sm text-[var(--warning)]"
```

---

**[P-6] `applyReviewEdit` TOCTOU: `updateSynthesisResultWorkflowJson` has no status guard in WHERE clause**
`src/lib/synthesis/review-agent.ts:62–85` / `src/lib/db/queries/synthesis-results.ts:160–177`

The status check (`row.status !== "in_review"`) occurs before the transaction. Inside the transaction, `updateSynthesisResultWorkflowJson` performs a blind `UPDATE WHERE resultId = ?` with no status condition. A concurrent approval that transitions `in_review → approved` between the pre-check and the UPDATE would mutate the workflow of an already-approved synthesis result.

**Fix:** Either:
(a) Add `AND status = 'in_review'` to the UPDATE WHERE clause in `updateSynthesisResultWorkflowJson` (requires a new `tx`-aware function variant), or
(b) Re-fetch and re-validate the row status inside the transaction using `SELECT FOR UPDATE` semantics.

The simplest correct fix: add a `requiredStatus` optional parameter to `updateSynthesisResultWorkflowJson` that appends `eq(synthesisResults.status, requiredStatus)` to the WHERE clause, and throw `StateTransitionError` when zero rows return.

---

**[P-7] Loading skeleton breakpoints mismatch actual page layout**
`src/app/interview/[token]/loading.tsx:3–49`

The loading skeleton uses `md:` (768px) breakpoints for the two-column layout and diagram panel visibility:
```tsx
<div className="... md:flex-row">
<div className="... md:max-w-[55%] md:border-r ...">
<div className="hidden ... md:flex md:w-[45%]">
```

The actual `active/page.tsx` uses `lg:` (1024px) breakpoints:
```tsx
<div className="flex h-screen flex-col lg:flex-row">
<div className="flex flex-1 flex-col lg:w-[55%]">
<div className="hidden border-l lg:block lg:w-[45%]">
```

At 768–1023px the skeleton shows a horizontal layout but the actual page shows stacked. Users see a layout flash on hydration.

**Fix:** Update `loading.tsx` to use `lg:` breakpoints consistently with `active/page.tsx`.

---

**[P-8] Hamburger `☰` character not `aria-hidden`**
`src/components/project/project-detail-layout.tsx:138–140`

```tsx
<Button ... aria-label="Open navigation" ...>
  ☰
</Button>
```

The `☰` Unicode character (U+2630 TRIGRAM FOR HEAVEN) is visible text content. Browsers vary in how they expose this to AT — some announce "trigram for heaven", others skip it. Since `aria-label` is already set on the button, the character should be wrapped in `<span aria-hidden="true">`.

**Fix:**
```tsx
<Button ... aria-label="Open navigation" ...>
  <span aria-hidden="true">☰</span>
</Button>
```

---

### DEFER FINDINGS (pre-existing or out-of-scope)

- **[D-1]** `usePanZoom` stale closure: React state in closure may lag on fast pointer events (`src/hooks/use-pan-zoom.ts:67`). Pre-existing pattern, common to all mouse-drag implementations without `useRef`. Acceptable for MVP.

- **[D-2]** `getMostRecentSynthesisAcrossProject` returns wrong synthesis for multi-node projects (`src/lib/db/queries/synthesis-results.ts:401`). Explicitly documented in the function's docstring as Phase 2 scope. Do not fix until multi-node project UI is built.

- **[D-3]** `review-agent-panel` sends full unbounded message history; silent server-side truncation at 50 entries (`src/components/synthesis/review-agent-panel.tsx:130`). Low operational impact for typical review sessions. Add client-side cap in a future polish pass.

- **[D-4]** Fallback SELECT in `transitionSynthesisStatus` diagnostic path not scoped by `projectId` (`src/lib/synthesis/synthesis-state-machine.ts:80`). Read-only diagnostic path, no mutation risk. Minor information leak in error messages. Acceptable.

- **[D-5]** `getSvgElement()` called before bpmn-js SVG rendering finalizes (`src/components/synthesis/bpmn-chart.tsx:70`). bpmn-js timing behavior is library-dependent. Export may capture partial SVG on first render. Deferred to bpmn-js-specific testing.

- **[D-6]** `handleMove` in ProcessTree can operate on stale `sortOrder` if rapid clicks precede `fetchTree` completion (`src/components/project/process-tree.tsx:291`). Requires optimistic locking or debounce. Defer to UX polish.

- **[D-7]** SSE buffer splitting on `\n\n` may fragment multi-line JSON in LLM responses (`src/components/synthesis/review-agent-panel.tsx:154`). Rare in practice; requires LLM to emit literal CRLF in a JSON field. Defer to SSE parser hardening task.

---

### Summary

| Category | Count |
|----------|-------|
| Patch (must fix) | 8 |
| Defer (pre-existing / phase 2) | 7 |
| Dismissed | 3 |

**Highest priority fixes:**
1. **P-6** — TOCTOU on workflow mutation (data integrity, medium severity)
2. **P-7** — Loading skeleton breakpoint mismatch (regression, layout flash)
3. **P-4** — Missing `role="img"` on SVG containers (accessibility, WCAG 2.1 failure)
4. **P-5** — Design-system color bypass in approval banners (dark mode break)
5. **P-8** — Hamburger character not `aria-hidden` (accessibility)
6. **P-1** — SVG click node ID matching false positive (functional bug, low probability)
7. **P-2** — Unvalidated `changeType` from LLM forwarded to client (UX regression)
8. **P-3** — `applyAddStep` ignores explicit sequence intent (functional regression)

---

Findings are listed above. No story file was provided, so nothing was persisted to a file.

=== AGENT IDENTIFICATION ===
Agent: DEV Agent
Persona: Amelia
Loaded files:
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-agent-dev\(activation via skill)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\workflow.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-01-gather-context.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-02-review.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-03-triage.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-04-present.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\_bmad\bmm\config.yaml
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\schema.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\types\synthesis.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\status-labels.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\synthesis-state-machine.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\review-agent.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\synthesis-results.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\synthesis-edits.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\supervisors.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\projects.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\revision-requests.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\approve\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\status\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\auth\middleware.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\review\messages\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\supervisors\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\auth\login\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\project\process-tree.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\hooks\use-pan-zoom.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\comparison-view.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\review-agent-panel.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\synthesis-viewer.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\status-indicator.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\supervisor\project-list.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\api\error-handler.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\interview\[token]\active\page.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\interview\[token]\loading.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\projects\[projectId]\loading.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\projects\loading.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\globals.css
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\interview\interview-toolbar.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\interview\diagram-text-alternative.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\text-alternative.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\edit-history.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\review-summary.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\individual-carousel.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\project\project-detail-layout.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\supervisor\projects\[projectId]\review\page.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\approval-controls.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-panel.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\bpmn-chart.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\next.config.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\review-agent.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\synthesis-state-machine.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\approve\route.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\status\route.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\synthesis-results.test.ts
=== END IDENTIFICATION ===
I now have sufficient context to perform all three review layers and produce the complete report. This is AUTOMATED PIPELINE MODE — no human input, no spec file provided (no-spec mode). I'll execute all three review layers internally and triage.

---

## Code Review — Epic 9 (Stories 9-1 through 9-5)

**Review Mode:** `no-spec` (no spec file provided)
**Diff Stats:** 94 files changed, 4,281 insertions, 735 deletions
**Acceptance Auditor:** Skipped — no spec file provided.

---

### LAYER 1: Blind Hunter (Adversarial Review)

**B-01 — `usePanZoom`: stale closure in `onMouseMove`**
`src/hooks/use-pan-zoom.ts:67-77`
`onMouseMove` captures `isPanning` and `panStart` via closure but these are React state values. Because `handlers` is constructed synchronously on each render without `useCallback`, the closure is fresh each render — acceptable. However `onMouseDown` sets `isPanning` + `panStart` state, and `onMouseMove` reads them in the same render cycle's closure. There is a known React pitfall: if `onMouseDown` and `onMouseMove` fire faster than React batches state, `isPanning` may still be `false` inside `onMouseMove`. This is a latent bug on fast pointer events but not blocking.

**B-02 — `StatusIndicator` silently renders stale status string for unknown values**
`src/components/synthesis/status-indicator.tsx:22-25`
The fallback `?? status` means any typo in `status` passed from a DB row silently renders raw DB string. This is acceptable for robustness but is a potential XSS-safe leak of internal DB state to users.

**B-03 — `handleSynthSvgClick` divergence matching is fragile**
`src/components/synthesis/comparison-view.tsx:370-377`
Node ID matching uses `nodeId.startsWith("S_") && nodeId.includes("_${sanitized}")` — this can produce false positives when a sanitized step ID substring appears in a different node ID. If two step IDs share a common prefix after sanitization, the wrong step is matched. Low probability but deterministic bug.

**B-04 — `parseProposalFromResponse` does not validate `changeType` against known enum**
`src/app/api/projects/[projectId]/synthesis/review/messages/route.ts:44-46`
The parsed `changeType` string from LLM output is forwarded to the client without validating it against `ProposedEdit.changeType` enum values. An LLM hallucinating an unknown `changeType` (e.g. `"delete_all"`) would be forwarded to the edits route, which calls `applyReviewEdit`, which would hit the default `throw new ConstraintViolationError("Unknown changeType")` — so data integrity is preserved server-side, but the client receives a 400 error with no user-friendly guidance. Medium UX defect, not a security bug.

**B-05 — `review-agent.ts` `applyAddStep` always auto-assigns sequence, ignoring LLM-provided sequence**
`src/lib/synthesis/review-agent.ts:130-135`
Comment says "Always auto-assign sequence to prevent LLM-hallucinated duplicates (A-10)". But this means if a supervisor explicitly asks the LLM to insert a step at sequence 2 between existing steps 1 and 3, the LLM sets `sequence: 2` but the server ignores it and sets `maxSeq + 1 = 4` (appending). The proposed edit description says "insert at position 2" but the result is appended. Functional regression vs. user intent.

**B-06 — `getMostRecentSynthesisAcrossProject` has undocumented multi-node limitation**
`src/lib/db/queries/synthesis-results.ts:401-410`
The function now has a note in the docstring acknowledging this is wrong for multi-node projects, but the actual query has no `processNodeId` filtering. Callers (synthesis status route, supervisor review page) may silently return the wrong node's synthesis for multi-node projects. Noted as Phase 2, acceptable for MVP.

**B-07 — `review-agent-panel.tsx` sends entire conversation history on every message**
`src/components/synthesis/review-agent-panel.tsx:130-132`
`conversationHistory: messages` sends the full accumulated message array on every request. This grows without bound across a review session. No size cap enforced client-side (server caps at 50 entries via Zod, but client sends all). The first 50 messages are sent; beyond 50 the server silently truncates. The client has no feedback that history was truncated. Low severity.

**B-08 — Inconsistent `dangerouslySetInnerHTML` aria role missing**
`src/components/synthesis/comparison-view.tsx:507-519` and `src/components/synthesis/individual-carousel.tsx:255-264`
SVG diagram containers rendered via `dangerouslySetInnerHTML` lack `role="img"` and `aria-label`. The parent `div` has `role="region"` and `aria-label` but the inner SVG content itself is not accessible to screen readers navigating by landmark. The `DiagramTextAlternative` / `TextAlternative` components partially address this but are not always present alongside these canvases.

**B-09 — `synthesis-state-machine.ts` second SELECT after zero-row UPDATE is not scoped by projectId**
`src/lib/synthesis/synthesis-state-machine.ts:80-92`
The follow-up `SELECT` to distinguish "not found" vs "wrong status" only checks `eq(synthesisResults.resultId, resultId)` — not `projectId`. This is purely diagnostic (doesn't mutate), so no IDOR risk, but it could expose status of a row belonging to a different project in error messages. Low.

**B-10 — `comparison-view.tsx` hardcoded `bg-green-50 border-green-200 text-green-800` colors**
`src/components/synthesis/comparison-view.tsx:170-178`
Status banners use raw Tailwind color literals instead of design system CSS variables (`--success`, `--success-soft`). Breaks dark mode and design system consistency.

**B-11 — Missing `aria-label` on hamburger button text**
`src/components/project/project-detail-layout.tsx:138`
The hamburger button renders a `☰` Unicode character as its visible label. `aria-label="Open navigation"` is present, but the `☰` character renders as text to some screen readers (announced as "trigram for heaven"). `aria-hidden="true"` should be on the `☰` span. This is a minor accessibility defect.

---

### LAYER 2: Edge Case Hunter

**E-01 — `transitionSynthesisStatus` TOCTOU between UPDATE and fallback SELECT**
`src/lib/synthesis/synthesis-state-machine.ts:66-95`
When the UPDATE returns zero rows and the follow-up SELECT also returns zero rows, the error thrown is "not found". But in a concurrent request scenario: Request A transitions `draft→in_review` (UPDATE succeeds, returns 1 row). Request B (race) also attempts `draft→in_review`, UPDATE returns 0 rows (status is now `in_review`, not `draft`). The follow-up SELECT finds the row, returns `existing.status = "in_review"`. Error message: `"expected draft — transition to in_review rejected"`. This is correct behavior. The TOCTOU is benign here because the WHERE clause enforcing `from` status prevents double-transition. ✓ Handled.

**E-02 — `applyReviewEdit` status guard checks `in_review` but `applyAddStep` etc. do not re-validate after transaction starts**
`src/lib/synthesis/review-agent.ts:42-47`
Status is validated before the transaction (`row.status !== "in_review"`). Inside the transaction, `updateSynthesisResultWorkflowJson` does a blind UPDATE by `resultId` only (no status check). A concurrent approval that transitions to `approved` between the status check and the UPDATE would allow a workflow mutation on an already-approved result. This is a real TOCTOU window.

- The inner UPDATE (`updateSynthesisResultWorkflowJson`) does not include a status condition in its WHERE clause.
- Mitigation requires either: (a) `SELECT FOR UPDATE` / advisory lock, or (b) including `AND status = 'in_review'` in the workflow JSON UPDATE.
- **Severity: Medium** — requires concurrent requests from the same supervisor session, unlikely but possible.

**E-03 — `processTree.tsx` `getVisibleNodeIds()` called inline inside `handleKeyDown` on every keystroke**
`src/components/project/process-tree.tsx:148`
`getVisibleNodeIds()` traverses `nodes` and `expandedIds` on every keydown event. For large trees (50+ nodes), this is O(n) per keystroke with nested `getChildren` calls that also filter the full nodes array. `getChildren` itself uses `Array.filter` (O(n)) inside `traverse`, making `getVisibleNodeIds` O(n²). For typical process trees (5-20 nodes) this is negligible, but should be noted.

**E-04 — `DiagramTextAlternative` regex for step matching is overly broad**
`src/components/interview/diagram-text-alternative.tsx:36-42`
The regex `/(\w+)[[\]({]+["']?([^"\]})]+)["']?[\]})]+/` will match inside connection lines too (e.g., `A --> B[Label]`). The code checks `!steps.find((s) => s.id === id)` for deduplication, which handles this, but a connection line with a bracket syntax like `A --> B["text"]` may add `B` as a step before the connection matcher runs on that same line, causing `B` to appear twice in steps (once from step-match, once from connection-match adding the `from` node). Low severity, display-only.

**E-05 — `withSupervisorProjectAccess` PM path — does NOT verify project exists before calling `getProjectById`**
`src/lib/auth/middleware.ts:121-133`
In the PM branch of `withSupervisorProjectAccess`, `getProjectById(projectId)` is called. If the project doesn't exist, `!project` returns 403 "no access" instead of 404 "not found". This is a minor UX inconsistency (403 vs 404) but prevents information leakage (correct security behavior).

**E-06 — `loadingScreen` skeletons use hardcoded `md:` breakpoints, page uses `lg:`**
`src/app/interview/[token]/loading.tsx` vs `src/app/interview/[token]/active/page.tsx`
The loading skeleton uses `md:flex-row` / `md:max-w-[55%]` (768px breakpoint) but the actual page uses `lg:flex-row` / `lg:w-[55%]` (1024px breakpoint). This means there is a layout mismatch between the loading skeleton and the actual page at 768-1024px viewport widths. The skeleton shows a side-by-side layout but the actual page shows stacked. The skeleton also uses `md:flex` for the diagram panel while the page uses `lg:block`.

**E-07 — `getSvgElement` called synchronously after `importXml` resolves — bpmn-js may not have completed rendering**
`src/components/synthesis/bpmn-chart.tsx:70`
`getSvgElement()` is called immediately after `importXml(bpmnXml).then(result => ...)`. The `bpmn-js` `importXml` resolves when the XML is parsed and the diagram model is created, but the SVG may still be in the DOM rendering queue. This is a known bpmn-js timing issue. The SVG element ref captured by `onSvgRendered` may be incomplete on first render.

**E-08 — `handleMove` in process-tree uses `sortOrder` swap without atomicity guarantee**
`src/components/project/process-tree.tsx:291-321`
The PUT request sends `{ sortOrder: targetSortOrder }` — it writes the clicked node's sort order to the sibling's sort order value. If two rapid move operations are made before the first fetchTree completes, the UI may show a stale nodes array and the second PUT may operate on the wrong sibling `sortOrder` value. Race condition between `fetchTree` completion and next move action.

**E-09 — `status` field in `synthesis-status/route.ts` POST returns `targetDiscoveryStatus` (project-level) not synthesis row status**
`src/app/api/projects/[projectId]/synthesis/status/route.ts:141`
The POST response `{ data: { status: targetDiscoveryStatus } }` returns the project `discoveryStatus` ("collecting" or "synthesizing"), not the synthesis result status. The client (`SynthesisStatusPanel`) consumes this to update its UI. If the PM panel displays "collecting" as the synthesis status this creates a conceptual mismatch — it is actually the project lifecycle status. The distinction is correct per the route's design intent but may confuse callers.

**E-10 — `review-agent-panel.tsx` SSE buffer splitting on `\n\n` may split multi-line SSE events**
`src/components/synthesis/review-agent-panel.tsx:154-155`
The SSE parser splits on `\n\n` but if a JSON payload contains a literal `\n\n` (e.g., inside a `description` field with paragraph breaks), the part-splitting would incorrectly split the SSE event. Standard SSE parsers handle this by only treating line-level `data:` prefixes as delimiters. This is a rare but real edge case for long LLM responses.

---

### LAYER 3: Acceptance Auditor — Skipped (no spec file provided)

---

## TRIAGE

| ID | Source | Title | Location | Category |
|----|--------|-------|----------|----------|
| B-01 | blind | `usePanZoom` stale closure: `isPanning` may not reflect latest state in `onMouseMove` | `src/hooks/use-pan-zoom.ts:67` | defer |
| B-02 | blind | `StatusIndicator` renders raw DB status string for unknown values | `src/components/synthesis/status-indicator.tsx:22` | dismiss |
| B-03 | blind | `handleSynthSvgClick` divergence node matching can false-positive on shared step ID substrings | `src/components/synthesis/comparison-view.tsx:370` | patch |
| B-04 | blind | `parseProposalFromResponse` forwards unvalidated `changeType` from LLM | `src/app/api/projects/[projectId]/synthesis/review/messages/route.ts:44` | patch |
| B-05 | blind | `applyAddStep` ignores LLM-provided sequence — always appends | `src/lib/synthesis/review-agent.ts:130` | patch |
| B-06 | blind | `getMostRecentSynthesisAcrossProject` returns wrong node for multi-node projects | `src/lib/db/queries/synthesis-results.ts:401` | defer |
| B-07 | blind | `review-agent-panel` sends unbounded conversation history — silent truncation beyond 50 | `src/components/synthesis/review-agent-panel.tsx:130` | defer |
| B-08 | blind | Diagram SVG containers lack `role="img"` and inner `aria-label` | `comparison-view.tsx:507`, `individual-carousel.tsx:255` | patch |
| B-09 | blind | Fallback SELECT in state machine not scoped by `projectId` — minor info leak in error messages | `src/lib/synthesis/synthesis-state-machine.ts:80` | defer |
| B-10 | blind | Approval banners use hardcoded Tailwind colors, not design-system CSS vars | `src/components/synthesis/comparison-view.tsx:170` | patch |
| B-11 | blind | Hamburger `☰` character not `aria-hidden` | `src/components/project/project-detail-layout.tsx:138` | patch |
| E-02 | edge | `applyReviewEdit` TOCTOU: workflow JSON updated without status check in transaction | `src/lib/synthesis/review-agent.ts:62` | patch |
| E-06 | edge | Loading skeleton uses `md:` breakpoints, actual page uses `lg:` — layout mismatch at 768–1024px | `src/app/interview/[token]/loading.tsx:3` | patch |
| E-07 | edge | `getSvgElement()` called before bpmn-js SVG rendering completes — stale ref | `src/components/synthesis/bpmn-chart.tsx:70` | defer |
| E-08 | edge | `handleMove` race: rapid clicks may use stale `sortOrder` from pre-refresh nodes array | `src/components/project/process-tree.tsx:291` | defer |
| E-10 | edge | SSE buffer split on `\n\n` breaks on multi-line JSON values in LLM response | `src/components/synthesis/review-agent-panel.tsx:154` | defer |

**Dismissed:** B-02 (fallback to raw string is safe, explicit design intent), E-01 (TOCTOU is benign — WHERE clause guards), E-03 (O(n²) on small trees, negligible), E-04 (display-only regex quirk, deduplication handles it), E-05 (correct security behavior), E-09 (design intent, not a bug).

---

## FINAL REPORT

**Code review complete.** 7 `patch`, 6 `defer`, 3 dismissed as noise. No spec file provided — no Acceptance Auditor run.

Findings are listed below. No story file was provided, so nothing was persisted to a file.

---

### PATCH FINDINGS (must fix)

---

**[P-1] `handleSynthSvgClick` can false-positive on step ID substrings**
`src/components/synthesis/comparison-view.tsx:370–377`

The Mermaid node ID matching logic:
```ts
if (nodeId.startsWith(`S_`) && nodeId.includes(`_${sanitized}`)) {
```
If two steps have IDs where one sanitized ID is a substring of another (e.g., `step_abc` and `step_abcdef`), the shorter step's pattern matches both Mermaid node elements. The check should require the sanitized segment to be followed by `_` or end of string (or a digit for Mermaid's uniqueness suffix):

**Fix:** Change to a stricter match, e.g.:
```ts
const pattern = new RegExp(`_${sanitized}(_\\d+)?$`);
if (nodeId.startsWith("S_") && pattern.test(nodeId)) {
```

---

**[P-2] `parseProposalFromResponse` forwards unvalidated `changeType` to client**
`src/app/api/projects/[projectId]/synthesis/review/messages/route.ts:44–46`

`changeType` from the LLM JSON block is forwarded in the SSE `proposal` event without validation against the `ProposedEdit.changeType` enum. The edits route rejects unknown types server-side with a 400, but with no user-facing explanation.

**Fix:** Add a `VALID_CHANGE_TYPES` set check inside `parseProposalFromResponse` and return `null` (skip proposal emission) if `changeType` is not in the allowed set. This prevents a confusing error when the user clicks "Apply".

---

**[P-3] `applyAddStep` ignores LLM-provided sequence — always appends**
`src/lib/synthesis/review-agent.ts:130–135`

The comment says "Always auto-assign sequence to prevent LLM-hallucinated duplicates" but this discards the supervisor's explicit intent when they ask to insert a step at a specific position. The actual concern (duplicate sequences) can be addressed by normalizing sequences post-insert rather than discarding the target position.

**Fix:** Use the LLM-provided `sequence` when it is within valid range (`1 <= seq <= maxSeq + 1`); fall back to `maxSeq + 1` only when out of range or absent. After inserting, normalize sequences to maintain a contiguous 1…N ordering.

---

**[P-4] Diagram SVG containers lack accessible `role` and `aria-label`**
`src/components/synthesis/comparison-view.tsx:493–519`
`src/components/synthesis/individual-carousel.tsx:245–265`

The `div` containers receiving `dangerouslySetInnerHTML` SVG content have no `role="img"` or `aria-label`. Screen reader users cannot identify these as diagrams. The outer `role="region"` landmark exists on the panel, but the diagram canvas itself is invisible to AT.

**Fix:** Add `role="img"` and `aria-label="Synthesis workflow diagram"` (or per-context label) to the inner div wrapping the `dangerouslySetInnerHTML` SVG. Pair with the existing `TextAlternative`/`DiagramTextAlternative` component via `aria-describedby`.

---

**[P-5] Approval banners use hardcoded Tailwind colors instead of CSS variables**
`src/components/synthesis/comparison-view.tsx:169–181`

```tsx
className="m-4 rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-800"
className="m-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
```

These bypass the design system (`--success`, `--success-soft`, `--warning`, `--warning-soft`) and break dark mode. Every other status badge in the codebase uses CSS variable-backed classes.

**Fix:**
```tsx
className="m-4 rounded-lg border border-[var(--success)] bg-[var(--success-soft)] p-4 text-sm text-[var(--success)]"
className="m-4 rounded-lg border border-[var(--warning)] bg-[var(--warning-soft)] p-4 text-sm text-[var(--warning)]"
```

---

**[P-6] `applyReviewEdit` TOCTOU: `updateSynthesisResultWorkflowJson` has no status guard in WHERE clause**
`src/lib/synthesis/review-agent.ts:62–85` / `src/lib/db/queries/synthesis-results.ts:160–177`

The status check (`row.status !== "in_review"`) occurs before the transaction. Inside the transaction, `updateSynthesisResultWorkflowJson` performs a blind `UPDATE WHERE resultId = ?` with no status condition. A concurrent approval that transitions `in_review → approved` between the pre-check and the UPDATE would mutate the workflow of an already-approved synthesis result.

**Fix:** Either:
(a) Add `AND status = 'in_review'` to the UPDATE WHERE clause in `updateSynthesisResultWorkflowJson` (requires a new `tx`-aware function variant), or
(b) Re-fetch and re-validate the row status inside the transaction using `SELECT FOR UPDATE` semantics.

The simplest correct fix: add a `requiredStatus` optional parameter to `updateSynthesisResultWorkflowJson` that appends `eq(synthesisResults.status, requiredStatus)` to the WHERE clause, and throw `StateTransitionError` when zero rows return.

---

**[P-7] Loading skeleton breakpoints mismatch actual page layout**
`src/app/interview/[token]/loading.tsx:3–49`

The loading skeleton uses `md:` (768px) breakpoints for the two-column layout and diagram panel visibility:
```tsx
<div className="... md:flex-row">
<div className="... md:max-w-[55%] md:border-r ...">
<div className="hidden ... md:flex md:w-[45%]">
```

The actual `active/page.tsx` uses `lg:` (1024px) breakpoints:
```tsx
<div className="flex h-screen flex-col lg:flex-row">
<div className="flex flex-1 flex-col lg:w-[55%]">
<div className="hidden border-l lg:block lg:w-[45%]">
```

At 768–1023px the skeleton shows a horizontal layout but the actual page shows stacked. Users see a layout flash on hydration.

**Fix:** Update `loading.tsx` to use `lg:` breakpoints consistently with `active/page.tsx`.

---

**[P-8] Hamburger `☰` character not `aria-hidden`**
`src/components/project/project-detail-layout.tsx:138–140`

```tsx
<Button ... aria-label="Open navigation" ...>
  ☰
</Button>
```

The `☰` Unicode character (U+2630 TRIGRAM FOR HEAVEN) is visible text content. Browsers vary in how they expose this to AT — some announce "trigram for heaven", others skip it. Since `aria-label` is already set on the button, the character should be wrapped in `<span aria-hidden="true">`.

**Fix:**
```tsx
<Button ... aria-label="Open navigation" ...>
  <span aria-hidden="true">☰</span>
</Button>
```

---

### DEFER FINDINGS (pre-existing or out-of-scope)

- **[D-1]** `usePanZoom` stale closure: React state in closure may lag on fast pointer events (`src/hooks/use-pan-zoom.ts:67`). Pre-existing pattern, common to all mouse-drag implementations without `useRef`. Acceptable for MVP.

- **[D-2]** `getMostRecentSynthesisAcrossProject` returns wrong synthesis for multi-node projects (`src/lib/db/queries/synthesis-results.ts:401`). Explicitly documented in the function's docstring as Phase 2 scope. Do not fix until multi-node project UI is built.

- **[D-3]** `review-agent-panel` sends full unbounded message history; silent server-side truncation at 50 entries (`src/components/synthesis/review-agent-panel.tsx:130`). Low operational impact for typical review sessions. Add client-side cap in a future polish pass.

- **[D-4]** Fallback SELECT in `transitionSynthesisStatus` diagnostic path not scoped by `projectId` (`src/lib/synthesis/synthesis-state-machine.ts:80`). Read-only diagnostic path, no mutation risk. Minor information leak in error messages. Acceptable.

- **[D-5]** `getSvgElement()` called before bpmn-js SVG rendering finalizes (`src/components/synthesis/bpmn-chart.tsx:70`). bpmn-js timing behavior is library-dependent. Export may capture partial SVG on first render. Deferred to bpmn-js-specific testing.

- **[D-6]** `handleMove` in ProcessTree can operate on stale `sortOrder` if rapid clicks precede `fetchTree` completion (`src/components/project/process-tree.tsx:291`). Requires optimistic locking or debounce. Defer to UX polish.

- **[D-7]** SSE buffer splitting on `\n\n` may fragment multi-line JSON in LLM responses (`src/components/synthesis/review-agent-panel.tsx:154`). Rare in practice; requires LLM to emit literal CRLF in a JSON field. Defer to SSE parser hardening task.

---

### Summary

| Category | Count |
|----------|-------|
| Patch (must fix) | 8 |
| Defer (pre-existing / phase 2) | 7 |
| Dismissed | 3 |

**Highest priority fixes:**
1. **P-6** — TOCTOU on workflow mutation (data integrity, medium severity)
2. **P-7** — Loading skeleton breakpoint mismatch (regression, layout flash)
3. **P-4** — Missing `role="img"` on SVG containers (accessibility, WCAG 2.1 failure)
4. **P-5** — Design-system color bypass in approval banners (dark mode break)
5. **P-8** — Hamburger character not `aria-hidden` (accessibility)
6. **P-1** — SVG click node ID matching false positive (functional bug, low probability)
7. **P-2** — Unvalidated `changeType` from LLM forwarded to client (UX regression)
8. **P-3** — `applyAddStep` ignores explicit sequence intent (functional regression)

---

Findings are listed above. No story file was provided, so nothing was persisted to a file.

=== AGENT IDENTIFICATION ===
Agent: DEV Agent
Persona: Amelia
Loaded files:
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-agent-dev\(activation via skill)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\workflow.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-01-gather-context.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-02-review.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-03-triage.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-04-present.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\_bmad\bmm\config.yaml
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\schema.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\types\synthesis.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\status-labels.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\synthesis-state-machine.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\review-agent.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\synthesis-results.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\synthesis-edits.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\supervisors.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\projects.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\revision-requests.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\approve\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\status\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\auth\middleware.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\review\messages\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\supervisors\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\auth\login\route.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\project\process-tree.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\hooks\use-pan-zoom.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\comparison-view.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\review-agent-panel.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\synthesis-viewer.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\status-indicator.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\supervisor\project-list.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\api\error-handler.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\interview\[token]\active\page.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\interview\[token]\loading.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\projects\[projectId]\loading.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\projects\loading.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\globals.css
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\interview\interview-toolbar.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\interview\diagram-text-alternative.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\text-alternative.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\edit-history.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\review-summary.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\individual-carousel.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\project\project-detail-layout.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\supervisor\projects\[projectId]\review\page.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\approval-controls.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-panel.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\bpmn-chart.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\next.config.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\review-agent.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\synthesis-state-machine.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\approve\route.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\api\projects\[projectId]\synthesis\status\route.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\db\queries\synthesis-results.test.ts
=== END IDENTIFICATION ===
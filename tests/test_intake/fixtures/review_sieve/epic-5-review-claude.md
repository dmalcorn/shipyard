I'll wait for both agents to complete before proceeding with the review. Let me also read the test files and implementation artifacts in parallel.
I'll also read the implementation artifacts and epic review files while waiting.
I'll wait for all agents to complete. Let me check on their progress.
Let me read the files directly while the agents complete.
Now let me also check a few additional implementation artifact files and the schema definitions:
Now let me check a few final files to complete the review:
Now let me check a couple of remaining files and look at the lib/mermaid/renderer reference:
I now have enough context to write the complete review. Here is my analysis:

---
agent_role: reviewer
task_id: epic-5-review
timestamp: 2026-04-12T15:36:36.072878+00:00
input_files: [_bmad-output/implementation-artifacts/5-1-mermaid-flowchart-rendering-with-divergence-annotations.md, _bmad-output/implementation-artifacts/5-2-flowchart-pan-zoom-interactive-controls.md, _bmad-output/implementation-artifacts/5-3-divergence-drill-down-and-source-attribution.md, _bmad-output/implementation-artifacts/5-4-framework-matrix-view.md, _bmad-output/implementation-artifacts/5-5-source-data-tab-interview-evidence.md, _bmad-output/implementation-artifacts/5-6-mermaid-svg-png-export-and-json-export-gating.md, epic-reviews-archive/epic-4/epic-4-analysis.md, epic-reviews-archive/epic-4/epic-4-category-a-fix-done.md, epic-reviews-archive/epic-4/epic-4-category-a-fix-plan.md, epic-reviews-archive/epic-4/epic-4-category-b-architect-review.md, epic-reviews-archive/epic-4/epic-4-fix-plan.md, epic-reviews-archive/epic-4/epic-4-review-bmad.md, epic-reviews-archive/epic-4/epic-4-review-claude.md, rebuild-status.md, src/app/projects/[projectId]/processes/[nodeId]/synthesis/page.tsx, src/components/project/process-node-detail.tsx, src/components/synthesis/chart-controls.test.tsx, src/components/synthesis/chart-controls.tsx, src/components/synthesis/divergence-detail.test.tsx, src/components/synthesis/divergence-detail.tsx, src/components/synthesis/divergence-panel.test.tsx, src/components/synthesis/divergence-panel.tsx, src/components/synthesis/export-controls.test.tsx, src/components/synthesis/export-controls.tsx, src/components/synthesis/framework-matrix.test.tsx, src/components/synthesis/framework-matrix.tsx, src/components/synthesis/mermaid-chart.test.tsx, src/components/synthesis/mermaid-chart.tsx, src/components/synthesis/source-attribution.test.tsx, src/components/synthesis/source-attribution.tsx, src/components/synthesis/source-data-tab.test.tsx, src/components/synthesis/source-data-tab.tsx, src/components/synthesis/synthesis-viewer.test.tsx, src/components/synthesis/synthesis-viewer.tsx, src/components/synthesis/text-alternative.test.tsx, src/components/synthesis/text-alternative.tsx, src/hooks/use-mermaid.ts, src/lib/synthesis/mermaid-generator.test.ts, src/lib/synthesis/mermaid-generator.ts]
reviewer_type: claude
review_scope: epic
---

# Epic Code Review — CLAUDE Reviewer

## Summary

Epic 5 delivers a well-structured synthesis visualization suite with solid spec compliance and strong test coverage across all six stories. The implementation is coherent, service boundaries are respected, and accessibility requirements are generally met — with several issues of varying severity documented below that warrant attention before moving to Epic 6.

---

## Findings

### 1. Duplicate divergence badge rendering — MermaidChart and DivergencePanel both render all divergences

- **File:** `src/components/synthesis/mermaid-chart.tsx`, `src/components/synthesis/divergence-panel.tsx`
- **Issue:** `SynthesisViewer` renders `<MermaidChart>` which contains its own divergence badge list (the "Divergence Annotations" section at the bottom), AND also renders `<DivergencePanel>` immediately below it in the same `flowchart` tab. Both components iterate `schema.divergences` independently and render expand/collapse UIs. This means every divergence appears twice on screen: once in the MermaidChart's inline list and once in DivergencePanel's roster. The architecture comment in `mermaid-chart.tsx` ("Full divergence roster — all synthesis divergences with expand/collapse (Story 5.3, AC4)") and the story-split comments ("Badge overlay strategy: divergence badges appear as a structured list below the SVG. Floating overlay on SVG node positions is Story 5.3 scope") suggest Story 5.1 added the badge list inside MermaidChart as a temporary approach, and Story 5.3 added DivergencePanel as the "proper" implementation — but the Story 5.1 code inside MermaidChart was never removed. The user sees two identical divergence lists.
- **Severity:** major
- **Action:** Remove the divergence badge list block (`{divergentSteps.length > 0 && ...}`) from `mermaid-chart.tsx` — `DivergencePanel` in `synthesis-viewer.tsx` is the canonical rendering point per Story 5.3. The `getDivergentStepIds`, `getDivergenceForStep`, `getDivergenceBadgeLabel`, `getDivergenceBadgeVariant` imports in `mermaid-chart.tsx` that are only used by the inline badge list can also be removed (the SVG styling via `generateMermaidFromSchema` is still needed).

---

### 2. `MermaidChart` imports divergence helpers it no longer needs after the Story 5.1 badge list is removed — but also uses them for current functionality

- **File:** `src/components/synthesis/mermaid-chart.tsx` (lines 21–27)
- **Issue:** After removing the inline divergence list (Finding 1), `getDivergentStepIds`, `getDivergenceForStep`, `getDivergenceBadgeLabel`, and `getDivergenceBadgeVariant` would all become unused imports. Additionally `getMatchConfidenceForStep` at line 39 is a file-local helper used only by the badge list. None of these are needed for SVG rendering — the CSS classes are already baked into the SVG by `generateMermaidFromSchema`. If the badge list remains (if intentional duplication), this is not an issue; but if it's removed per Finding 1, these dead imports and the dead helper must also be cleaned up.
- **Severity:** minor
- **Action:** Contingent on Finding 1. Remove unused imports and the `getMatchConfidenceForStep` helper if the inline badge list is removed from `MermaidChart`.

---

### 3. `MermaidChart` test suite mocks `getDivergentStepIds`, `getDivergenceForStep`, etc., meaning it can never catch the duplication regression

- **File:** `src/components/synthesis/mermaid-chart.test.tsx`
- **Issue:** The `mermaid-chart.test.tsx` mocks the entire `@/lib/synthesis/mermaid-generator` module and returns a stub SVG. The tests verify that clicking divergence badges in MermaidChart's inline list expands a `DivergenceDetail` panel. But if the design intent is that MermaidChart should NOT render that list (per Finding 1), then these divergence-expansion tests (AC2, AC3) in `mermaid-chart.test.tsx` are testing code that should be deleted. The real test coverage for divergence expand/collapse lives correctly in `divergence-panel.test.tsx`. The MermaidChart tests provide a false sense of coverage for behavior that should live elsewhere.
- **Severity:** minor
- **Action:** After resolving Finding 1, remove the divergence expand/collapse test cases from `mermaid-chart.test.tsx` (tests starting at line 277 through 443). The SVG rendering, error state, ChartControls presence, TextAlternative, and `onSvgRendered` callback tests should remain.

---

### 4. `SourceDataTab` step accumulation bug — duplicate steps added per interviewee per step

- **File:** `src/components/synthesis/source-data-tab.tsx` (lines 30–51)
- **Issue:** The outer loop iterates `schema.workflow` steps; the inner loop iterates `step.sources`. For each `source` entry, a new step object is pushed to `existing.steps` (line 38). If a step has two sources from the same interviewee (which is valid per schema — `sources` is `StepSource[]` with no uniqueness constraint on `intervieweeName`), that step will be pushed twice to the interviewee's steps list, resulting in duplicate step rows in the expanded view. Additionally, `existing.steps.push(...)` pushes once per source rather than once per step-per-interviewee: even for different interviewees, if `step.sources` has entries for Alice then Bob, Alice gets the step pushed once (correct), but if Alice has two sources for the same step, she gets two step entries in her list. The intended behavior is one row per step in the expanded view, showing all sources for that step together.
- **Severity:** major
- **Action:** Restructure the loop to push a step entry once per (interviewee, step) pair. Track seen `stepId`s per interviewee using a nested `Set`, or outer-loop over steps and inner-loop over sources, only pushing to `existing.steps` when `stepId` has not yet been seen for that interviewee. The sources filter on line 41 (`step.sources.filter(s => s.intervieweeName === source.intervieweeName)`) is correct and should be preserved — it just needs to run once per step, not once per source.

---

### 5. `SourceDataTab` — "View diagram ↗" link navigates to interview token URL, not synthesis viewer

- **File:** `src/components/synthesis/source-data-tab.tsx` (line 128)
- **Issue:** The link uses `href={'/interview/${interviewId}'}` where `interviewId` comes from `schema.interviewsIncluded`. The `/interview/[token]` route is the **interviewee-facing** token-authenticated route (Epic 3, FR78c). PM-plane users viewing the Source Data tab are not interviewees and likely do not have valid tokens. The correct PM-side URL for viewing interview details would be something like `/projects/[projectId]/interviews/[interviewId]` (if that route exists) or the individual schema/exchange viewer. Linking to `/interview/[interviewId]` with a raw UUID (not a token) will likely result in a "token not found" or 404 error.
- **Severity:** major
- **Action:** Verify whether a PM-accessible individual interview detail route exists. If so, use that URL. If not, either remove the link until the PM interview viewer route is implemented, or link to the project-level interview list. Do not link to the interviewee-facing `/interview/` route with a raw UUID that is not a hub token.

---

### 6. `renderer.ts` validates syntax contains `"flowchart"` keyword — this rejects valid Mermaid diagram types

- **File:** `src/lib/mermaid/renderer.ts` (lines 91–97)
- **Issue:** `renderDiagram` returns a failure result if the syntax does not contain the literal string `"flowchart"`. This is a fragile guard that would reject other valid Mermaid diagram types (e.g., `sequenceDiagram`, `graph TD`, `gantt`) and would also fail for synthesis diagrams if the generator were ever changed to produce `graph TD` syntax (which Mermaid supports equivalently). The synthesis generator always produces `flowchart TD` so this currently never fires in the happy path, but it is also incorrect as a defensive check — `"flowchart"` being absent is not evidence of invalid syntax.
- **Severity:** minor
- **Action:** Remove the `"flowchart"` keyword check (lines 91–97). The `mermaidInstance.render()` call will throw on genuinely invalid syntax and the `catch` block at line 120 already handles that. The empty-string guard (lines 83–89) is sufficient and correct.

---

### 7. `SourceDataTab` — `resultId` prop is declared but never used

- **File:** `src/components/synthesis/source-data-tab.tsx` (line 23)
- **Issue:** `SourceDataTabProps` declares `resultId: string` and the component signature destructures it, but `resultId` is never referenced anywhere in the component body. The "View diagram ↗" link (Finding 5) uses `interviewId` not `resultId`. If `resultId` was intended to enable a link to the synthesis result itself, that link is missing. If it was scaffolding for a future feature, it should be documented; as-is it is dead interface surface that adds confusion.
- **Severity:** minor
- **Action:** Either use `resultId` for its intended purpose (e.g., link to the synthesis result page), or remove it from the interface and component props. Do not leave unreferenced props in an interface.

---

### 8. `MermaidChart` pan/zoom uses CSS `transform` on `svgContainerRef` div which contains the SVG via `dangerouslySetInnerHTML` — `onSvgRendered` fires after `svgContent` state update but before DOM paint

- **File:** `src/components/synthesis/mermaid-chart.tsx` (lines 92–100)
- **Issue:** The `useEffect` that calls `onSvgRendered` (lines 92–100) depends on `[svgContent, onSvgRendered]`. When `svgContent` is set in state, React schedules a re-render; `useEffect` fires after that render and calls `svgContainerRef.current.querySelector("svg")`. However, because `dangerouslySetInnerHTML` content is parsed by React synchronously during render, the SVG element should be present in the DOM by the time the effect fires. This is correct. However, if `svgContent` changes (e.g., schema prop changes and a new render fires), the `svgContainerRef` will momentarily hold the old SVG while the new render is in-flight. The stale render guard (`renderId !== renderIdRef.current`) prevents `setSvgContent` from being called for stale renders, but a rapid schema change could produce a brief window where `svgRef.current` in `SynthesisViewer` points to a detached old SVG element. The export buttons would then export a stale diagram.
- **Severity:** minor
- **Action:** This is an edge case unlikely to occur in practice (schema changes require a new synthesis run, not a live update). No action required unless the synthesis viewer gains live-updating capability. Document the assumption that `schema` is stable for the lifetime of a `SynthesisViewer` instance.

---

### 9. `DivergenceDetail` and `DivergencePanel` both define identical `BADGE_CLASSES` record — duplication across story boundary

- **File:** `src/components/synthesis/divergence-detail.tsx` (lines 22–26), `src/components/synthesis/divergence-panel.tsx` (lines 32–36)
- **Issue:** Both files define `const BADGE_CLASSES: Record<"teal" | "amber" | "muted", string>` with identical Tailwind class strings. `DivergenceBadge` in `mermaid-chart.tsx` (lines 340–345) also duplicates the same badge className logic inline. This three-way duplication of badge styling means a color change to the "teal" divergence badge requires three file edits and makes the design system fragile.
- **Severity:** minor
- **Action:** Extract badge and border class mappings to a shared constant or utility in `src/lib/types/diagram.ts` or a new `src/lib/synthesis/divergence-utils.ts`, and import it into all three consumers. Alternatively, promote `DivergenceBadge` from a file-local component in `mermaid-chart.tsx` to a shared component in `src/components/synthesis/divergence-badge.tsx` that encapsulates the class logic. Since `DivergenceBadge` is already defined in `mermaid-chart.tsx` as a local component and `DivergencePanel` doesn't use it, either export it or create the shared module.

---

### 10. `SynthesisPage` does not catch Zod parse errors — throws unhandled exception on malformed JSONB data

- **File:** `src/app/projects/[projectId]/processes/[nodeId]/synthesis/page.tsx` (line 52)
- **Issue:** `ProcessSchemaSchema.parse(latest.workflowJson)` is a `.parse()` call (not `.safeParse()`). If `latest.workflowJson` contains data that was persisted by an earlier schema version or a partial synthesis write, `parse()` will throw a `ZodError`. In a Next.js Server Component, an unhandled thrown error will trigger the nearest `error.tsx` boundary — but if no such boundary exists on this route segment, it will surface as a 500 with no user-facing message. Per CLAUDE.md: "Never write empty catch{} blocks — always surface errors to the user."
- **Severity:** major
- **Action:** Replace `.parse()` with `.safeParse()` and handle the failure case explicitly — either redirect to an error state with a clear message ("Synthesis data is in an incompatible format — please re-run synthesis") or throw a structured error that a co-located `error.tsx` boundary can render gracefully. Add an `error.tsx` to the synthesis route segment if one does not already exist.

---

### 11. `ChartControls` comment incorrectly claims it is "the integration point for export buttons in Story 5.6"

- **File:** `src/components/synthesis/chart-controls.tsx` (lines 7–9)
- **Issue:** The JSDoc comment on `ChartControls` states: *"Kept separate because this component is the integration point for export buttons in Story 5.6 (SVG/PNG/JSON/BPMN export)"*. The story 5.6 implementation artifact explicitly states the opposite: *"chart-controls.tsx — Existing file — do NOT add export buttons here; export lives in ExportControls, chart-controls owns only zoom/pan."* Export buttons live in `ExportControls`, not `ChartControls`. The comment is wrong and will mislead future developers.
- **Severity:** minor
- **Action:** Replace the misleading comment with accurate documentation: `ChartControls` owns zoom/pan controls only. Export functionality lives in `ExportControls` (`export-controls.tsx`).

---

### 12. `mermaid-generator.ts` — `getDivergenceForStep` uses `Array.includes` inside a `.find()` call — O(n²) for steps with many affected step IDs

- **File:** `src/lib/synthesis/mermaid-generator.ts` (line 96)
- **Issue:** `getDivergenceForStep` calls `schema.divergences.find(d => d.affectedStepIds.includes(stepId))`. For each step rendered in the diagram, this iterates all divergences and for each divergence calls `Array.includes` on `affectedStepIds`. With M divergences and K affected steps each, the lookup is O(M × K) per step call. CLAUDE.md mandates: *"When checking membership of IDs in a collection inside a loop or `.find()`/`.filter()`/`.some()`, use a Set for the lookup collection."* The function is also called from within the `divergentSteps.map()` loop in `mermaid-chart.tsx` (line 267), making this O(N × M × K) overall where N = number of divergent steps. In practice synthesis outputs are small, so this won't cause performance issues, but it violates an explicit CLAUDE.md rule.
- **Severity:** minor
- **Action:** Build a `Map<stepId, Divergence>` once from `schema.divergences` (iterating `affectedStepIds` for each) and use that for O(1) lookup in `getDivergenceForStep`. Alternatively, since `getDivergentStepIds` already builds a `Set`, the two can be combined into a single `Map<stepId, Divergence>` helper.

---

### 13. `process-node-detail.tsx` has three empty `catch {}` blocks that silently swallow errors

- **File:** `src/components/project/process-node-detail.tsx` (lines 88–90, 106–108, 122–124)
- **Issue:** `fetchNodeDetail`, `fetchCapturedCount`, and `fetchSynthesisResult` all have empty `catch` blocks (with comments like `// Non-critical — guidance just won't be pre-populated`). CLAUDE.md states: *"Never write empty catch {} blocks — always surface errors to the user (inline error state, toast, or re-throw); silent failures are bugs."* The comments argue these are non-critical, but this reasoning is flawed — if `fetchSynthesisResult` silently fails, the "View Synthesis Results" button never appears even though synthesis exists, and the user has no indication something went wrong.
- **Severity:** major
- **Action:** At minimum, add `console.error` logging in each catch block so failures appear in browser devtools. Preferably surface these as UI error states. For `fetchSynthesisResult` specifically, the failure should set an error state that renders a fallback message to the user (e.g., "Could not check synthesis status") rather than silently hiding the button.

---

### 14. `TextAlternative` marks itself as `"use client"` but contains no client-only code

- **File:** `src/components/synthesis/text-alternative.tsx` (line 1)
- **Issue:** `TextAlternative` is marked `"use client"` but uses no hooks, no browser APIs, no event handlers, and no React context that requires client-side rendering. It is a pure render function of `ProcessSchema` → JSX using only the native `<details>` element. Per CLAUDE.md: *"Server Components by default; 'use client' only at leaf components that need interactivity, hooks, or browser APIs."* The `"use client"` directive is unnecessary and forces React to include this component in the client bundle.
- **Severity:** minor
- **Action:** Remove `"use client"` from `text-alternative.tsx`. The `<details>/<summary>` disclosure pattern is native HTML and functions without JavaScript — it does not require a client component boundary. Note that `TextAlternative` is rendered by `MermaidChart` which is `"use client"`, so this change won't break rendering; it will simply allow `TextAlternative` to be pre-rendered on the server when used in non-client contexts.

---

### 15. `SourceAttribution` also has unnecessary `"use client"` directive

- **File:** `src/components/synthesis/source-attribution.tsx` (line 1)
- **Issue:** Same pattern as Finding 14. `SourceAttribution` is `"use client"` but contains no hooks, no browser APIs, and no interactivity — it is a pure render of `StepSource[]` → JSX.
- **Severity:** minor
- **Action:** Remove `"use client"`. The component is consumed by `DivergenceDetail` which is `"use client"`, so no rendering behavior changes.
I now have enough context to write the complete review. Here is my analysis:

---
agent_role: reviewer
task_id: epic-5-review
timestamp: 2026-04-12T15:36:36.072878+00:00
input_files: [_bmad-output/implementation-artifacts/5-1-mermaid-flowchart-rendering-with-divergence-annotations.md, _bmad-output/implementation-artifacts/5-2-flowchart-pan-zoom-interactive-controls.md, _bmad-output/implementation-artifacts/5-3-divergence-drill-down-and-source-attribution.md, _bmad-output/implementation-artifacts/5-4-framework-matrix-view.md, _bmad-output/implementation-artifacts/5-5-source-data-tab-interview-evidence.md, _bmad-output/implementation-artifacts/5-6-mermaid-svg-png-export-and-json-export-gating.md, epic-reviews-archive/epic-4/epic-4-analysis.md, epic-reviews-archive/epic-4/epic-4-category-a-fix-done.md, epic-reviews-archive/epic-4/epic-4-category-a-fix-plan.md, epic-reviews-archive/epic-4/epic-4-category-b-architect-review.md, epic-reviews-archive/epic-4/epic-4-fix-plan.md, epic-reviews-archive/epic-4/epic-4-review-bmad.md, epic-reviews-archive/epic-4/epic-4-review-claude.md, rebuild-status.md, src/app/projects/[projectId]/processes/[nodeId]/synthesis/page.tsx, src/components/project/process-node-detail.tsx, src/components/synthesis/chart-controls.test.tsx, src/components/synthesis/chart-controls.tsx, src/components/synthesis/divergence-detail.test.tsx, src/components/synthesis/divergence-detail.tsx, src/components/synthesis/divergence-panel.test.tsx, src/components/synthesis/divergence-panel.tsx, src/components/synthesis/export-controls.test.tsx, src/components/synthesis/export-controls.tsx, src/components/synthesis/framework-matrix.test.tsx, src/components/synthesis/framework-matrix.tsx, src/components/synthesis/mermaid-chart.test.tsx, src/components/synthesis/mermaid-chart.tsx, src/components/synthesis/source-attribution.test.tsx, src/components/synthesis/source-attribution.tsx, src/components/synthesis/source-data-tab.test.tsx, src/components/synthesis/source-data-tab.tsx, src/components/synthesis/synthesis-viewer.test.tsx, src/components/synthesis/synthesis-viewer.tsx, src/components/synthesis/text-alternative.test.tsx, src/components/synthesis/text-alternative.tsx, src/hooks/use-mermaid.ts, src/lib/synthesis/mermaid-generator.test.ts, src/lib/synthesis/mermaid-generator.ts]
reviewer_type: claude
review_scope: epic
---

# Epic Code Review — CLAUDE Reviewer

## Summary

Epic 5 delivers a well-structured synthesis visualization suite with solid spec compliance and strong test coverage across all six stories. The implementation is coherent, service boundaries are respected, and accessibility requirements are generally met — with several issues of varying severity documented below that warrant attention before moving to Epic 6.

---

## Findings

### 1. Duplicate divergence badge rendering — MermaidChart and DivergencePanel both render all divergences

- **File:** `src/components/synthesis/mermaid-chart.tsx`, `src/components/synthesis/divergence-panel.tsx`
- **Issue:** `SynthesisViewer` renders `<MermaidChart>` which contains its own divergence badge list (the "Divergence Annotations" section at the bottom), AND also renders `<DivergencePanel>` immediately below it in the same `flowchart` tab. Both components iterate `schema.divergences` independently and render expand/collapse UIs. This means every divergence appears twice on screen: once in the MermaidChart's inline list and once in DivergencePanel's roster. The architecture comment in `mermaid-chart.tsx` ("Full divergence roster — all synthesis divergences with expand/collapse (Story 5.3, AC4)") and the story-split comments ("Badge overlay strategy: divergence badges appear as a structured list below the SVG. Floating overlay on SVG node positions is Story 5.3 scope") suggest Story 5.1 added the badge list inside MermaidChart as a temporary approach, and Story 5.3 added DivergencePanel as the "proper" implementation — but the Story 5.1 code inside MermaidChart was never removed. The user sees two identical divergence lists.
- **Severity:** major
- **Action:** Remove the divergence badge list block (`{divergentSteps.length > 0 && ...}`) from `mermaid-chart.tsx` — `DivergencePanel` in `synthesis-viewer.tsx` is the canonical rendering point per Story 5.3. The `getDivergentStepIds`, `getDivergenceForStep`, `getDivergenceBadgeLabel`, `getDivergenceBadgeVariant` imports in `mermaid-chart.tsx` that are only used by the inline badge list can also be removed (the SVG styling via `generateMermaidFromSchema` is still needed).

---

### 2. `MermaidChart` imports divergence helpers it no longer needs after the Story 5.1 badge list is removed — but also uses them for current functionality

- **File:** `src/components/synthesis/mermaid-chart.tsx` (lines 21–27)
- **Issue:** After removing the inline divergence list (Finding 1), `getDivergentStepIds`, `getDivergenceForStep`, `getDivergenceBadgeLabel`, and `getDivergenceBadgeVariant` would all become unused imports. Additionally `getMatchConfidenceForStep` at line 39 is a file-local helper used only by the badge list. None of these are needed for SVG rendering — the CSS classes are already baked into the SVG by `generateMermaidFromSchema`. If the badge list remains (if intentional duplication), this is not an issue; but if it's removed per Finding 1, these dead imports and the dead helper must also be cleaned up.
- **Severity:** minor
- **Action:** Contingent on Finding 1. Remove unused imports and the `getMatchConfidenceForStep` helper if the inline badge list is removed from `MermaidChart`.

---

### 3. `MermaidChart` test suite mocks `getDivergentStepIds`, `getDivergenceForStep`, etc., meaning it can never catch the duplication regression

- **File:** `src/components/synthesis/mermaid-chart.test.tsx`
- **Issue:** The `mermaid-chart.test.tsx` mocks the entire `@/lib/synthesis/mermaid-generator` module and returns a stub SVG. The tests verify that clicking divergence badges in MermaidChart's inline list expands a `DivergenceDetail` panel. But if the design intent is that MermaidChart should NOT render that list (per Finding 1), then these divergence-expansion tests (AC2, AC3) in `mermaid-chart.test.tsx` are testing code that should be deleted. The real test coverage for divergence expand/collapse lives correctly in `divergence-panel.test.tsx`. The MermaidChart tests provide a false sense of coverage for behavior that should live elsewhere.
- **Severity:** minor
- **Action:** After resolving Finding 1, remove the divergence expand/collapse test cases from `mermaid-chart.test.tsx` (tests starting at line 277 through 443). The SVG rendering, error state, ChartControls presence, TextAlternative, and `onSvgRendered` callback tests should remain.

---

### 4. `SourceDataTab` step accumulation bug — duplicate steps added per interviewee per step

- **File:** `src/components/synthesis/source-data-tab.tsx` (lines 30–51)
- **Issue:** The outer loop iterates `schema.workflow` steps; the inner loop iterates `step.sources`. For each `source` entry, a new step object is pushed to `existing.steps` (line 38). If a step has two sources from the same interviewee (which is valid per schema — `sources` is `StepSource[]` with no uniqueness constraint on `intervieweeName`), that step will be pushed twice to the interviewee's steps list, resulting in duplicate step rows in the expanded view. Additionally, `existing.steps.push(...)` pushes once per source rather than once per step-per-interviewee: even for different interviewees, if `step.sources` has entries for Alice then Bob, Alice gets the step pushed once (correct), but if Alice has two sources for the same step, she gets two step entries in her list. The intended behavior is one row per step in the expanded view, showing all sources for that step together.
- **Severity:** major
- **Action:** Restructure the loop to push a step entry once per (interviewee, step) pair. Track seen `stepId`s per interviewee using a nested `Set`, or outer-loop over steps and inner-loop over sources, only pushing to `existing.steps` when `stepId` has not yet been seen for that interviewee. The sources filter on line 41 (`step.sources.filter(s => s.intervieweeName === source.intervieweeName)`) is correct and should be preserved — it just needs to run once per step, not once per source.

---

### 5. `SourceDataTab` — "View diagram ↗" link navigates to interview token URL, not synthesis viewer

- **File:** `src/components/synthesis/source-data-tab.tsx` (line 128)
- **Issue:** The link uses `href={'/interview/${interviewId}'}` where `interviewId` comes from `schema.interviewsIncluded`. The `/interview/[token]` route is the **interviewee-facing** token-authenticated route (Epic 3, FR78c). PM-plane users viewing the Source Data tab are not interviewees and likely do not have valid tokens. The correct PM-side URL for viewing interview details would be something like `/projects/[projectId]/interviews/[interviewId]` (if that route exists) or the individual schema/exchange viewer. Linking to `/interview/[interviewId]` with a raw UUID (not a token) will likely result in a "token not found" or 404 error.
- **Severity:** major
- **Action:** Verify whether a PM-accessible individual interview detail route exists. If so, use that URL. If not, either remove the link until the PM interview viewer route is implemented, or link to the project-level interview list. Do not link to the interviewee-facing `/interview/` route with a raw UUID that is not a hub token.

---

### 6. `renderer.ts` validates syntax contains `"flowchart"` keyword — this rejects valid Mermaid diagram types

- **File:** `src/lib/mermaid/renderer.ts` (lines 91–97)
- **Issue:** `renderDiagram` returns a failure result if the syntax does not contain the literal string `"flowchart"`. This is a fragile guard that would reject other valid Mermaid diagram types (e.g., `sequenceDiagram`, `graph TD`, `gantt`) and would also fail for synthesis diagrams if the generator were ever changed to produce `graph TD` syntax (which Mermaid supports equivalently). The synthesis generator always produces `flowchart TD` so this currently never fires in the happy path, but it is also incorrect as a defensive check — `"flowchart"` being absent is not evidence of invalid syntax.
- **Severity:** minor
- **Action:** Remove the `"flowchart"` keyword check (lines 91–97). The `mermaidInstance.render()` call will throw on genuinely invalid syntax and the `catch` block at line 120 already handles that. The empty-string guard (lines 83–89) is sufficient and correct.

---

### 7. `SourceDataTab` — `resultId` prop is declared but never used

- **File:** `src/components/synthesis/source-data-tab.tsx` (line 23)
- **Issue:** `SourceDataTabProps` declares `resultId: string` and the component signature destructures it, but `resultId` is never referenced anywhere in the component body. The "View diagram ↗" link (Finding 5) uses `interviewId` not `resultId`. If `resultId` was intended to enable a link to the synthesis result itself, that link is missing. If it was scaffolding for a future feature, it should be documented; as-is it is dead interface surface that adds confusion.
- **Severity:** minor
- **Action:** Either use `resultId` for its intended purpose (e.g., link to the synthesis result page), or remove it from the interface and component props. Do not leave unreferenced props in an interface.

---

### 8. `MermaidChart` pan/zoom uses CSS `transform` on `svgContainerRef` div which contains the SVG via `dangerouslySetInnerHTML` — `onSvgRendered` fires after `svgContent` state update but before DOM paint

- **File:** `src/components/synthesis/mermaid-chart.tsx` (lines 92–100)
- **Issue:** The `useEffect` that calls `onSvgRendered` (lines 92–100) depends on `[svgContent, onSvgRendered]`. When `svgContent` is set in state, React schedules a re-render; `useEffect` fires after that render and calls `svgContainerRef.current.querySelector("svg")`. However, because `dangerouslySetInnerHTML` content is parsed by React synchronously during render, the SVG element should be present in the DOM by the time the effect fires. This is correct. However, if `svgContent` changes (e.g., schema prop changes and a new render fires), the `svgContainerRef` will momentarily hold the old SVG while the new render is in-flight. The stale render guard (`renderId !== renderIdRef.current`) prevents `setSvgContent` from being called for stale renders, but a rapid schema change could produce a brief window where `svgRef.current` in `SynthesisViewer` points to a detached old SVG element. The export buttons would then export a stale diagram.
- **Severity:** minor
- **Action:** This is an edge case unlikely to occur in practice (schema changes require a new synthesis run, not a live update). No action required unless the synthesis viewer gains live-updating capability. Document the assumption that `schema` is stable for the lifetime of a `SynthesisViewer` instance.

---

### 9. `DivergenceDetail` and `DivergencePanel` both define identical `BADGE_CLASSES` record — duplication across story boundary

- **File:** `src/components/synthesis/divergence-detail.tsx` (lines 22–26), `src/components/synthesis/divergence-panel.tsx` (lines 32–36)
- **Issue:** Both files define `const BADGE_CLASSES: Record<"teal" | "amber" | "muted", string>` with identical Tailwind class strings. `DivergenceBadge` in `mermaid-chart.tsx` (lines 340–345) also duplicates the same badge className logic inline. This three-way duplication of badge styling means a color change to the "teal" divergence badge requires three file edits and makes the design system fragile.
- **Severity:** minor
- **Action:** Extract badge and border class mappings to a shared constant or utility in `src/lib/types/diagram.ts` or a new `src/lib/synthesis/divergence-utils.ts`, and import it into all three consumers. Alternatively, promote `DivergenceBadge` from a file-local component in `mermaid-chart.tsx` to a shared component in `src/components/synthesis/divergence-badge.tsx` that encapsulates the class logic. Since `DivergenceBadge` is already defined in `mermaid-chart.tsx` as a local component and `DivergencePanel` doesn't use it, either export it or create the shared module.

---

### 10. `SynthesisPage` does not catch Zod parse errors — throws unhandled exception on malformed JSONB data

- **File:** `src/app/projects/[projectId]/processes/[nodeId]/synthesis/page.tsx` (line 52)
- **Issue:** `ProcessSchemaSchema.parse(latest.workflowJson)` is a `.parse()` call (not `.safeParse()`). If `latest.workflowJson` contains data that was persisted by an earlier schema version or a partial synthesis write, `parse()` will throw a `ZodError`. In a Next.js Server Component, an unhandled thrown error will trigger the nearest `error.tsx` boundary — but if no such boundary exists on this route segment, it will surface as a 500 with no user-facing message. Per CLAUDE.md: "Never write empty catch{} blocks — always surface errors to the user."
- **Severity:** major
- **Action:** Replace `.parse()` with `.safeParse()` and handle the failure case explicitly — either redirect to an error state with a clear message ("Synthesis data is in an incompatible format — please re-run synthesis") or throw a structured error that a co-located `error.tsx` boundary can render gracefully. Add an `error.tsx` to the synthesis route segment if one does not already exist.

---

### 11. `ChartControls` comment incorrectly claims it is "the integration point for export buttons in Story 5.6"

- **File:** `src/components/synthesis/chart-controls.tsx` (lines 7–9)
- **Issue:** The JSDoc comment on `ChartControls` states: *"Kept separate because this component is the integration point for export buttons in Story 5.6 (SVG/PNG/JSON/BPMN export)"*. The story 5.6 implementation artifact explicitly states the opposite: *"chart-controls.tsx — Existing file — do NOT add export buttons here; export lives in ExportControls, chart-controls owns only zoom/pan."* Export buttons live in `ExportControls`, not `ChartControls`. The comment is wrong and will mislead future developers.
- **Severity:** minor
- **Action:** Replace the misleading comment with accurate documentation: `ChartControls` owns zoom/pan controls only. Export functionality lives in `ExportControls` (`export-controls.tsx`).

---

### 12. `mermaid-generator.ts` — `getDivergenceForStep` uses `Array.includes` inside a `.find()` call — O(n²) for steps with many affected step IDs

- **File:** `src/lib/synthesis/mermaid-generator.ts` (line 96)
- **Issue:** `getDivergenceForStep` calls `schema.divergences.find(d => d.affectedStepIds.includes(stepId))`. For each step rendered in the diagram, this iterates all divergences and for each divergence calls `Array.includes` on `affectedStepIds`. With M divergences and K affected steps each, the lookup is O(M × K) per step call. CLAUDE.md mandates: *"When checking membership of IDs in a collection inside a loop or `.find()`/`.filter()`/`.some()`, use a Set for the lookup collection."* The function is also called from within the `divergentSteps.map()` loop in `mermaid-chart.tsx` (line 267), making this O(N × M × K) overall where N = number of divergent steps. In practice synthesis outputs are small, so this won't cause performance issues, but it violates an explicit CLAUDE.md rule.
- **Severity:** minor
- **Action:** Build a `Map<stepId, Divergence>` once from `schema.divergences` (iterating `affectedStepIds` for each) and use that for O(1) lookup in `getDivergenceForStep`. Alternatively, since `getDivergentStepIds` already builds a `Set`, the two can be combined into a single `Map<stepId, Divergence>` helper.

---

### 13. `process-node-detail.tsx` has three empty `catch {}` blocks that silently swallow errors

- **File:** `src/components/project/process-node-detail.tsx` (lines 88–90, 106–108, 122–124)
- **Issue:** `fetchNodeDetail`, `fetchCapturedCount`, and `fetchSynthesisResult` all have empty `catch` blocks (with comments like `// Non-critical — guidance just won't be pre-populated`). CLAUDE.md states: *"Never write empty catch {} blocks — always surface errors to the user (inline error state, toast, or re-throw); silent failures are bugs."* The comments argue these are non-critical, but this reasoning is flawed — if `fetchSynthesisResult` silently fails, the "View Synthesis Results" button never appears even though synthesis exists, and the user has no indication something went wrong.
- **Severity:** major
- **Action:** At minimum, add `console.error` logging in each catch block so failures appear in browser devtools. Preferably surface these as UI error states. For `fetchSynthesisResult` specifically, the failure should set an error state that renders a fallback message to the user (e.g., "Could not check synthesis status") rather than silently hiding the button.

---

### 14. `TextAlternative` marks itself as `"use client"` but contains no client-only code

- **File:** `src/components/synthesis/text-alternative.tsx` (line 1)
- **Issue:** `TextAlternative` is marked `"use client"` but uses no hooks, no browser APIs, no event handlers, and no React context that requires client-side rendering. It is a pure render function of `ProcessSchema` → JSX using only the native `<details>` element. Per CLAUDE.md: *"Server Components by default; 'use client' only at leaf components that need interactivity, hooks, or browser APIs."* The `"use client"` directive is unnecessary and forces React to include this component in the client bundle.
- **Severity:** minor
- **Action:** Remove `"use client"` from `text-alternative.tsx`. The `<details>/<summary>` disclosure pattern is native HTML and functions without JavaScript — it does not require a client component boundary. Note that `TextAlternative` is rendered by `MermaidChart` which is `"use client"`, so this change won't break rendering; it will simply allow `TextAlternative` to be pre-rendered on the server when used in non-client contexts.

---

### 15. `SourceAttribution` also has unnecessary `"use client"` directive

- **File:** `src/components/synthesis/source-attribution.tsx` (line 1)
- **Issue:** Same pattern as Finding 14. `SourceAttribution` is `"use client"` but contains no hooks, no browser APIs, and no interactivity — it is a pure render of `StepSource[]` → JSX.
- **Severity:** minor
- **Action:** Remove `"use client"`. The component is consumed by `DivergenceDetail` which is `"use client"`, so no rendering behavior changes.
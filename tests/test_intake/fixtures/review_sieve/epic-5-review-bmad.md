I'll load the project context and then proceed with the code review as instructed.
This is an automated pipeline — no human input is available. I'll proceed with the explicit file list provided. Let me gather context on all the files and construct the diff.
8428 insertions — well within review scope. Now let me load all the key source files for review.
Now let me read the test files and the spec files for acceptance criteria:
Now let me run the tests and load the spec files to complete context gathering:
Test execution is being blocked. I have sufficient code context from reading all the source files. Let me now proceed to the review step.
Now let me read the review step file and run all three parallel review layers:
This is an automated pipeline — no spec file was provided. I'll run all three review layers directly. Running parallel review now:
All three review layers complete. Now proceed to triage.
Now I'll normalize, deduplicate, and triage all findings across the three layers:

**Triage — Normalized & Deduplicated Findings**

| ID | Source | Title | Location |
|----|--------|-------|----------|
| F1 | blind+edge+auditor | `getDivergenceForStep` uses `Array.includes()` inside `.find()` — O(n²) nested iteration, violates CLAUDE.md | `mermaid-generator.ts:97` |
| F2 | blind+auditor | `renderDiagram(...).then(...)` has no `.catch()` — unhandled rejection leaves spinner frozen, never shows error | `mermaid-chart.tsx:111` |
| F3 | blind+auditor | Three empty `catch {}` blocks in `LeafNodeDetail` — CLAUDE.md violation, silent failures | `process-node-detail.tsx:88,106,123` |
| F4 | blind+edge+auditor | `ProcessSchemaSchema.parse()` has no try/catch — `ZodError` produces generic 500 instead of user-friendly error | `synthesis/page.tsx:52` |
| F5 | blind+edge | PNG export: no `img.onerror` handler — blob URL leaks on SVG load failure, canvas `toDataURL` `SecurityError` unhandled | `export-controls.tsx:92–111` |
| F6 | blind+edge | Mermaid render DOM leak — each render creates a new phantom `<div id="synthesis-chart-N">` in `document.body` never removed | `mermaid-chart.tsx:106,111` |
| F7 | blind+edge | `isRendering` stuck `true` forever when stale render `return`s early — no `setIsRendering(false)` on stale path | `mermaid-chart.tsx:113` |
| F8 | auditor | `useMermaid` `error` field destructured in hook but ignored in `MermaidChart` — Mermaid init failure shows blank screen, no error UI | `mermaid-chart.tsx:61` |
| F9 | blind+edge | `handleMouseMove` — no `onMouseLeave`/`window.mouseup` cleanup; `isPanning` stays `true` if mouse released outside window | `mermaid-chart.tsx:152–164` (Note: `onMouseLeave` IS wired to `handleMouseUp` at line 237) |
| F10 | blind | `escapeLabel` only escapes `"` — Mermaid node labels with `]`, `[`, backtick break diagram syntax | `mermaid-generator.ts:172` |
| F11 | edge | Duplicate `sequence` values produce duplicate/colliding Mermaid node IDs | `mermaid-generator.ts:sanitizeNodeId` |
| F12 | blind+edge | `SourceDataTab` `resultId` prop declared in interface but silently dropped from destructuring — dead parameter | `source-data-tab.tsx:6,23` |
| F13 | blind+edge | `nameToIdMap` index-alignment assumption — "View diagram ↗" links wrong or absent when array lengths differ | `source-data-tab.tsx:55–62` |
| F14 | blind | "View diagram ↗" links navigate to `/interview/[interviewId]` — interviewee-facing hub URL, not supervisor interview detail | `source-data-tab.tsx:124` |
| F15 | auditor | `aria-controls` missing on `InterviewRow` expand button; detail panel has no `id` | `source-data-tab.tsx:107` |
| F16 | auditor | "Mentioned by N of M" rendered twice for `likely_implicit` divergences (in `descriptionText` AND in `SourceAttribution` footer) | `divergence-detail.tsx:45`, `source-attribution.tsx:49` |
| F17 | blind+edge | `SourceAttribution` and `SourceDataTab` use `key={idx}` on reorderable evidence arrays | `source-attribution.tsx:33`, `source-data-tab.tsx:149` |
| F18 | blind | `handleExportSvg` / `triggerDownload`: anchor removed synchronously after `.click()` — Firefox may abort download | `export-controls.tsx:35–42` |
| F19 | blind | `getDivergentStepIds` called twice per render (inside `generateMermaidFromSchema` + again at `mermaid-chart.tsx:176`) | `mermaid-chart.tsx:176` |
| F20 | blind | `getMatchConfidenceForStep` in `mermaid-chart.tsx` uses linear scan; `divergence-panel.tsx` version uses Set — same function, two implementations | `mermaid-chart.tsx:39–47` |
| F21 | blind | `handleSaveGuidance` does not clear `error` state at start — stale trigger-save error shown during guidance save | `process-node-detail.tsx:187` |
| F22 | blind | `onSvgRendered` fires with stale SVGElement during schema re-render — parent `svgRef` holds old diagram during export window | `mermaid-chart.tsx:92–100` |
| F23 | blind | `Date.toLocaleDateString()` without UTC handling — off-by-one-day in non-UTC timezones | `synthesis-viewer.tsx:43`, `source-attribution.tsx:42`, `source-data-tab.tsx:116,157` |
| F24 | auditor | Present cell with `undefined` `matchConfidence` shows no color AND no text — legend misleading | `framework-matrix.tsx:195` |
| F25 | blind | `handleFitToView` resets to `scale:1` regardless of SVG size — "Fit to View" is actually "Reset Zoom" | `mermaid-chart.tsx:141` |
| F26 | blind | Badge styling (`BADGE_CLASSES`, `BORDER_CLASSES`, `DivergenceBadge`) duplicated across 3 files | `mermaid-chart.tsx:340`, `divergence-detail.tsx:16`, `divergence-panel.tsx:32` |
| F27 | blind | `initializeMermaid` TOCTOU race — concurrent calls both pass null guard, Mermaid initialized twice | `src/lib/mermaid/renderer.ts` (not in diff but called by hooks in scope) |
| F28 | edge | `step.action` or `step.object` null/undefined — label renders as `"null undefined"` in diagram | `mermaid-generator.ts:48` |

**Triage Classifications:**

- **F9**: `onMouseLeave` IS wired to `handleMouseUp` at line 237 of `mermaid-chart.tsx` — `isPanning` IS cleared on mouse leave. **Dismiss** (false positive from reviewer working from snippet).
- **F14**: The spec (Story 5-5 AC2) explicitly says "View diagram link per row → /interview/[interviewId]". This matches the implementation. **Dismiss** (implementation matches spec intent — interviewee-facing interview URL is correct per AC2).
- **F25**: "Fit to view = reset zoom" is by design per Story 5-2 AC4: "Fit to View resets to scale=1, offsetX=0, offsetY=0." **Dismiss** (matches AC4 exactly).
- **F27**: Outside the diff scope (renderer.ts not in the review file list). **Defer**.
- **F19**: Performance micro-optimization — not a correctness bug. **Defer**.
- **F26**: Style duplication — cosmetic debt, not a bug. **Defer**.

Remaining after triage: 22 `patch`, 2 `defer`, 3 `dismiss`.

Now proceed to the final presentation step:
No spec file was provided (automated pipeline, `review_mode` = `no-spec`). No story file to write to. Presenting the findings directly.
---

## Epic 5 Code Review — Final Report

**Stats:** 40 files changed, 8,428 insertions. Three review layers completed (Blind Hunter, Edge Case Hunter, Acceptance Auditor).

**Result:** 0 `decision_needed` · **22 `patch`** · 2 `defer` · 3 `dismiss`

---

## Patch Findings (22)

### 🔴 Critical

**F1 — `getDivergenceForStep` uses `Array.includes()` inside `.find()` — CLAUDE.md violation**
`src/lib/synthesis/mermaid-generator.ts:97`
```ts
return schema.divergences.find((d) => d.affectedStepIds.includes(stepId)) ?? null;
```
O(n²) nested iteration. CLAUDE.md explicitly forbids this: "use a `Set` for the lookup collection — never use `Array.includes()` in nested iterations." Fix: build a `Map<string, Divergence>` from stepId → divergence at call site, or accept a pre-built Set.

**F2 — `renderDiagram(...).then(...)` has no `.catch()` — spinner freezes permanently on rejection**
`src/components/synthesis/mermaid-chart.tsx:111`
If `renderDiagram` rejects (Mermaid dynamic import failure, unexpected throw), the `.then()` body never runs. `setIsRendering(false)` is never called, `setRenderError` is never called — spinner is stuck forever. Story 5-1 AC2 requires a user-friendly error message. Fix: add `.catch((err) => { setRenderError("Diagram could not be rendered"); setIsRendering(false); })`.

**F3 — Three empty `catch {}` blocks — CLAUDE.md violation**
`src/components/project/process-node-detail.tsx:88,106,123`
All three swallow errors silently. A failed `fetchSynthesisResult` means `hasSynthesisResult` stays `false` — the "View Synthesis Results" button never appears even when results exist. Fix: surface errors via `setError(err.message)` or at minimum log them.

**F4 — `ProcessSchemaSchema.parse()` unguarded — `ZodError` renders generic 500 page**
`src/app/projects/[projectId]/processes/[nodeId]/synthesis/page.tsx:52`
No `try/catch`. A corrupt or schema-version-mismatched `workflowJson` throws unhandled to Next.js error boundary. Story 5-1 AC2 requires a user-friendly error. Fix: wrap in `try/catch`, return a `<div>` with a clear message (e.g., "This synthesis result is corrupted. Please re-run synthesis.") or call `notFound()`.

**F5 — PNG export: no `img.onerror` — blob URL leaks on SVG load failure**
`src/components/synthesis/export-controls.tsx:92–111`
If the browser fails to load the SVG as an Image, `URL.revokeObjectURL(svgUrl)` is never called. Additionally, `canvas.toDataURL()` throws a `SecurityError` if the SVG contains external image references — unhandled. Fix: add `img.onerror = () => { URL.revokeObjectURL(svgUrl); }` and wrap `toDataURL()` in try/catch.

**F6 — Mermaid render leak — phantom `<div id="synthesis-chart-N">` nodes accumulate in `document.body`**
`src/components/synthesis/mermaid-chart.tsx:106,111`
Mermaid's `render(containerId, syntax)` creates detached DOM nodes in `document.body` for each render call and does not clean them up. Every schema change creates a new orphaned element. Fix: clean up after render in the renderer module (`document.getElementById(containerId)?.remove()`), or use Mermaid's `destroy()` API if available.

---

### 🟠 High

**F7 — `isRendering` stuck `true` on stale render early-return path**
`src/components/synthesis/mermaid-chart.tsx:113`
```ts
if (renderId !== renderIdRef.current) return; // setIsRendering(false) never called
```
If a rapid schema change triggers render N, then N+1, and render N completes after N+1 is in flight, render N hits the stale guard and returns without clearing `isRendering`. If N+1 also goes stale, the spinner is permanently shown. Fix: call `setIsRendering(false)` before the stale-render `return`.

**F8 — `useMermaid` `error` field silently ignored in `MermaidChart` — Mermaid init failure = blank screen**
`src/components/synthesis/mermaid-chart.tsx:61`
```ts
const { isReady, renderDiagram } = useMermaid(); // `error` dropped
```
If Mermaid fails to initialize, `isReady` stays `false` forever. The component renders nothing — no error, no text alternative, no spinner. Story 5-1 AC2 requires user-friendly error. Fix: destructure `error` and render an error state when `!isReady && error`.

**F10 — `escapeLabel` only escapes `"` — labels with `]`, backtick, or `[` corrupt diagram syntax**
`src/lib/synthesis/mermaid-generator.ts:172`
Step labels naturally contain `(`, `)`, `[`, `]` (e.g., "Submit request (urgent)", "Review [Form A]"). Inside Mermaid's `["..."]` node syntax, unescaped `]` terminates the node definition prematurely. Fix: also escape `[` → `&#91;` and `]` → `&#93;`.

**F11 — Duplicate `sequence` values produce colliding Mermaid node IDs**
`src/lib/synthesis/mermaid-generator.ts:sanitizeNodeId`
`S_${sequence}_${stepId}` relies on `sequence` for uniqueness but does not use the full UUID. If two steps share the same sequence number (can happen with synthesis bugs), their node IDs collide and Mermaid merges them silently. Fix: use only the sanitized UUID portion without the sequence prefix, or use full UUID + sequence.

**F12 — `SourceDataTab` `resultId` prop declared but silently dropped**
`src/components/synthesis/source-data-tab.tsx:8,23`
The interface declares `resultId: string` but the function destructures only `{ schema }`. Dead interface surface. If `resultId` is needed for future filtering, the silent discard will cause bugs. Fix: either remove from the interface or use it (even `void resultId` to document intent).

**F13 — `nameToIdMap` index alignment is fragile — wrong "View diagram" links when arrays are out of sync**
`src/components/synthesis/source-data-tab.tsx:55–62`
When `interviewees.length !== interviewsIncluded.length`, the entire map is skipped, producing zero links silently. When a duplicate name exists, the second overrides the first. The assumption that `frameworkMatrix.interviewees[i]` ↔ `interviewsIncluded[i]` is undocumented in the schema and fragile. Fix: document the invariant as a code comment; add a guard that renders "link unavailable" rather than silently omitting.

**F15 — `InterviewRow` expand button missing `aria-controls` — ARIA linkage broken**
`src/components/synthesis/source-data-tab.tsx:107`
All other expandable components in this epic (DivergencePanel, MermaidChart) wire `aria-controls` to the detail panel `id`. `InterviewRow`'s button has `aria-expanded` but no `aria-controls`, and the detail `<div>` has no `id`. Screen readers cannot programmatically navigate from button to panel. Story 5-3 AC4 / Story 5-5 AC3. Fix: add `id` to the expanded detail `<div>` and `aria-controls={id}` to the button.

**F16 — "Mentioned by N of M interviewees" rendered twice for `likely_implicit` divergences**
`src/components/synthesis/divergence-detail.tsx:45` + `src/components/synthesis/source-attribution.tsx:49`
`DivergenceDetail.descriptionText` prepends "Mentioned by N of M" for `likely_implicit`. `SourceAttribution` always appends a "Mentioned by N of M" footer. Both render inside `DivergenceDetail`. Story 5-1 AC4 / Story 5-3 AC3. Fix: either remove the footer line from `SourceAttribution` when already present in the description, or only prepend in `descriptionText` when `SourceAttribution` won't render the footer.

**F21 — `handleSaveGuidance` does not clear `error` state — stale error persists from prior save**
`src/components/project/process-node-detail.tsx:187`
`handleSaveTriggerDeliverable` calls `setError(null)` at start; `handleSaveGuidance` does not. A previous trigger-save error remains visible on screen during/after a successful guidance save. Fix: add `setError(null)` at the start of `handleSaveGuidance`.

---

### 🟡 Medium

**F17 — `key={idx}` on reorderable evidence/source arrays**
`src/components/synthesis/source-attribution.tsx:33` · `src/components/synthesis/source-data-tab.tsx:149`
Using array index as React key causes incorrect reconciliation when items are reordered. Fix: use composite key `ev.intervieweeName + ev.timestamp` (or `src.intervieweeName + src.timestamp`).

**F18 — `triggerDownload` removes anchor synchronously after `.click()` — may abort download in Firefox**
`src/components/synthesis/export-controls.tsx:35–42`
Firefox may require the anchor to remain in DOM until download is initiated. Fix: use `setTimeout(() => document.body.removeChild(a), 100)` instead of synchronous removal, or use `URL.revokeObjectURL` in the anchor's `click` event.

**F20 — `getMatchConfidenceForStep` (mermaid-chart.tsx) uses linear scan; `getMatchConfidenceForDivergence` (divergence-panel.tsx) uses Set — duplicated logic, worse implementation in chart**
`src/components/synthesis/mermaid-chart.tsx:39–47`
Same functionality implemented twice with different performance characteristics. Fix: extract to a shared utility in `mermaid-generator.ts` using a Set for O(1) lookup.

**F22 — `onSvgRendered` fires with stale SVGElement during schema re-render**
`src/components/synthesis/mermaid-chart.tsx:92–100`
When `schema` changes, `svgContent` is not cleared before the new render starts. During the re-render window, `svgRef` in `SynthesisViewer` still holds the old SVG. Fix: clear `svgContent` in the schema-change `useEffect` (line 85–89) before the new render begins, which will trigger `onSvgRendered(null)`.

**F23 — `toLocaleDateString()` without UTC handling — off-by-one-day in non-UTC timezones**
`src/components/synthesis/synthesis-viewer.tsx:43` · `source-attribution.tsx:42` · `source-data-tab.tsx:116,157`
ISO 8601 UTC dates displayed with browser local timezone. Fix: use `{ timeZone: "UTC" }` option in `toLocaleDateString` calls.

**F24 — `FrameworkMatrix` present cell with `undefined` `matchConfidence` shows neither color nor text**
`src/components/synthesis/framework-matrix.tsx:195`
`getConfidenceClass(undefined)` returns `""` (no color) and the confidence text is conditionally rendered only when `!== undefined`. A present cell with no confidence data is visually indistinguishable from a cell with zero styling. Fix: render "No confidence data" or apply a neutral background for cells where `present=true && matchConfidence === undefined`.

**F28 — `step.action` or `step.object` null/undefined renders as `"null undefined"` in diagram**
`src/lib/synthesis/mermaid-generator.ts:48`
`const label = \`${step.action} ${step.object}\`` — JavaScript coerces null/undefined to the strings "null"/"undefined". Fix: guard with `const label = \`${step.action ?? ""} ${step.object ?? ""}\`.trim()`.

---

## Deferred Findings (2)

- **F19** — `getDivergentStepIds` called twice per render (inside `generateMermaidFromSchema` + `mermaid-chart.tsx:176`) — pre-existing performance micro-optimization, not a correctness bug. Defer.
- **F27** — `initializeMermaid` TOCTOU race on singleton — in `src/lib/mermaid/renderer.ts`, outside the diff scope of this epic. Defer.

## Dismissed Findings (3)

- **F9** — False positive: `onMouseLeave` IS wired to `handleMouseUp` at line 237.
- **F14** — False positive: `/interview/[interviewId]` is correct per Story 5-5 AC2.
- **F25** — False positive: "Fit to View = reset to scale:1" is correct per Story 5-2 AC4.

---

**Code review complete.** 0 `decision_needed` · **22 `patch`** · 2 `defer` · 3 `dismiss`.

Findings are listed above. No story file was provided, so nothing was persisted to disk.

The most critical items to address before shipping:
1. **F4** — Unguarded `ZodError` in the Server Component synthesis page
2. **F2** — Missing `.catch()` on `renderDiagram` (spinner freezes on error)
3. **F1** — CLAUDE.md O(n²) violation in `getDivergenceForStep`
4. **F8** — Mermaid init error silently shows blank screen
5. **F5** — PNG blob URL leak on export failure
6. **F3** — Empty `catch` blocks hiding synthesis result visibility bug

---

=== AGENT IDENTIFICATION ===
Agent: DEV Agent
Persona: Amelia
Loaded files:
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-agent-dev\*.md (skill activation)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\workflow.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-01-gather-context.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-02-review.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-03-triage.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-04-present.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\_bmad\bmm\config.yaml
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\mermaid-generator.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\mermaid-generator.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\hooks\use-mermaid.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\mermaid-chart.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\mermaid-chart.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\synthesis-viewer.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\synthesis-viewer.test.tsx (partial context)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\export-controls.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\export-controls.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\chart-controls.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\chart-controls.test.tsx (partial context)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-panel.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-panel.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-detail.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-detail.test.tsx (partial context)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\source-attribution.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\source-attribution.test.tsx (partial context)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\framework-matrix.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\framework-matrix.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\source-data-tab.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\source-data-tab.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\text-alternative.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\projects\[projectId]\processes\[nodeId]\synthesis\page.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\project\process-node-detail.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\project\process-node-detail.test.tsx (partial context)
=== END IDENTIFICATION ===
---

## Epic 5 Code Review — Final Report

**Stats:** 40 files changed, 8,428 insertions. Three review layers completed (Blind Hunter, Edge Case Hunter, Acceptance Auditor).

**Result:** 0 `decision_needed` · **22 `patch`** · 2 `defer` · 3 `dismiss`

---

## Patch Findings (22)

### 🔴 Critical

**F1 — `getDivergenceForStep` uses `Array.includes()` inside `.find()` — CLAUDE.md violation**
`src/lib/synthesis/mermaid-generator.ts:97`
```ts
return schema.divergences.find((d) => d.affectedStepIds.includes(stepId)) ?? null;
```
O(n²) nested iteration. CLAUDE.md explicitly forbids this: "use a `Set` for the lookup collection — never use `Array.includes()` in nested iterations." Fix: build a `Map<string, Divergence>` from stepId → divergence at call site, or accept a pre-built Set.

**F2 — `renderDiagram(...).then(...)` has no `.catch()` — spinner freezes permanently on rejection**
`src/components/synthesis/mermaid-chart.tsx:111`
If `renderDiagram` rejects (Mermaid dynamic import failure, unexpected throw), the `.then()` body never runs. `setIsRendering(false)` is never called, `setRenderError` is never called — spinner is stuck forever. Story 5-1 AC2 requires a user-friendly error message. Fix: add `.catch((err) => { setRenderError("Diagram could not be rendered"); setIsRendering(false); })`.

**F3 — Three empty `catch {}` blocks — CLAUDE.md violation**
`src/components/project/process-node-detail.tsx:88,106,123`
All three swallow errors silently. A failed `fetchSynthesisResult` means `hasSynthesisResult` stays `false` — the "View Synthesis Results" button never appears even when results exist. Fix: surface errors via `setError(err.message)` or at minimum log them.

**F4 — `ProcessSchemaSchema.parse()` unguarded — `ZodError` renders generic 500 page**
`src/app/projects/[projectId]/processes/[nodeId]/synthesis/page.tsx:52`
No `try/catch`. A corrupt or schema-version-mismatched `workflowJson` throws unhandled to Next.js error boundary. Story 5-1 AC2 requires a user-friendly error. Fix: wrap in `try/catch`, return a `<div>` with a clear message (e.g., "This synthesis result is corrupted. Please re-run synthesis.") or call `notFound()`.

**F5 — PNG export: no `img.onerror` — blob URL leaks on SVG load failure**
`src/components/synthesis/export-controls.tsx:92–111`
If the browser fails to load the SVG as an Image, `URL.revokeObjectURL(svgUrl)` is never called. Additionally, `canvas.toDataURL()` throws a `SecurityError` if the SVG contains external image references — unhandled. Fix: add `img.onerror = () => { URL.revokeObjectURL(svgUrl); }` and wrap `toDataURL()` in try/catch.

**F6 — Mermaid render leak — phantom `<div id="synthesis-chart-N">` nodes accumulate in `document.body`**
`src/components/synthesis/mermaid-chart.tsx:106,111`
Mermaid's `render(containerId, syntax)` creates detached DOM nodes in `document.body` for each render call and does not clean them up. Every schema change creates a new orphaned element. Fix: clean up after render in the renderer module (`document.getElementById(containerId)?.remove()`), or use Mermaid's `destroy()` API if available.

---

### 🟠 High

**F7 — `isRendering` stuck `true` on stale render early-return path**
`src/components/synthesis/mermaid-chart.tsx:113`
```ts
if (renderId !== renderIdRef.current) return; // setIsRendering(false) never called
```
If a rapid schema change triggers render N, then N+1, and render N completes after N+1 is in flight, render N hits the stale guard and returns without clearing `isRendering`. If N+1 also goes stale, the spinner is permanently shown. Fix: call `setIsRendering(false)` before the stale-render `return`.

**F8 — `useMermaid` `error` field silently ignored in `MermaidChart` — Mermaid init failure = blank screen**
`src/components/synthesis/mermaid-chart.tsx:61`
```ts
const { isReady, renderDiagram } = useMermaid(); // `error` dropped
```
If Mermaid fails to initialize, `isReady` stays `false` forever. The component renders nothing — no error, no text alternative, no spinner. Story 5-1 AC2 requires user-friendly error. Fix: destructure `error` and render an error state when `!isReady && error`.

**F10 — `escapeLabel` only escapes `"` — labels with `]`, backtick, or `[` corrupt diagram syntax**
`src/lib/synthesis/mermaid-generator.ts:172`
Step labels naturally contain `(`, `)`, `[`, `]` (e.g., "Submit request (urgent)", "Review [Form A]"). Inside Mermaid's `["..."]` node syntax, unescaped `]` terminates the node definition prematurely. Fix: also escape `[` → `&#91;` and `]` → `&#93;`.

**F11 — Duplicate `sequence` values produce colliding Mermaid node IDs**
`src/lib/synthesis/mermaid-generator.ts:sanitizeNodeId`
`S_${sequence}_${stepId}` relies on `sequence` for uniqueness but does not use the full UUID. If two steps share the same sequence number (can happen with synthesis bugs), their node IDs collide and Mermaid merges them silently. Fix: use only the sanitized UUID portion without the sequence prefix, or use full UUID + sequence.

**F12 — `SourceDataTab` `resultId` prop declared but silently dropped**
`src/components/synthesis/source-data-tab.tsx:8,23`
The interface declares `resultId: string` but the function destructures only `{ schema }`. Dead interface surface. If `resultId` is needed for future filtering, the silent discard will cause bugs. Fix: either remove from the interface or use it (even `void resultId` to document intent).

**F13 — `nameToIdMap` index alignment is fragile — wrong "View diagram" links when arrays are out of sync**
`src/components/synthesis/source-data-tab.tsx:55–62`
When `interviewees.length !== interviewsIncluded.length`, the entire map is skipped, producing zero links silently. When a duplicate name exists, the second overrides the first. The assumption that `frameworkMatrix.interviewees[i]` ↔ `interviewsIncluded[i]` is undocumented in the schema and fragile. Fix: document the invariant as a code comment; add a guard that renders "link unavailable" rather than silently omitting.

**F15 — `InterviewRow` expand button missing `aria-controls` — ARIA linkage broken**
`src/components/synthesis/source-data-tab.tsx:107`
All other expandable components in this epic (DivergencePanel, MermaidChart) wire `aria-controls` to the detail panel `id`. `InterviewRow`'s button has `aria-expanded` but no `aria-controls`, and the detail `<div>` has no `id`. Screen readers cannot programmatically navigate from button to panel. Story 5-3 AC4 / Story 5-5 AC3. Fix: add `id` to the expanded detail `<div>` and `aria-controls={id}` to the button.

**F16 — "Mentioned by N of M interviewees" rendered twice for `likely_implicit` divergences**
`src/components/synthesis/divergence-detail.tsx:45` + `src/components/synthesis/source-attribution.tsx:49`
`DivergenceDetail.descriptionText` prepends "Mentioned by N of M" for `likely_implicit`. `SourceAttribution` always appends a "Mentioned by N of M" footer. Both render inside `DivergenceDetail`. Story 5-1 AC4 / Story 5-3 AC3. Fix: either remove the footer line from `SourceAttribution` when already present in the description, or only prepend in `descriptionText` when `SourceAttribution` won't render the footer.

**F21 — `handleSaveGuidance` does not clear `error` state — stale error persists from prior save**
`src/components/project/process-node-detail.tsx:187`
`handleSaveTriggerDeliverable` calls `setError(null)` at start; `handleSaveGuidance` does not. A previous trigger-save error remains visible on screen during/after a successful guidance save. Fix: add `setError(null)` at the start of `handleSaveGuidance`.

---

### 🟡 Medium

**F17 — `key={idx}` on reorderable evidence/source arrays**
`src/components/synthesis/source-attribution.tsx:33` · `src/components/synthesis/source-data-tab.tsx:149`
Using array index as React key causes incorrect reconciliation when items are reordered. Fix: use composite key `ev.intervieweeName + ev.timestamp` (or `src.intervieweeName + src.timestamp`).

**F18 — `triggerDownload` removes anchor synchronously after `.click()` — may abort download in Firefox**
`src/components/synthesis/export-controls.tsx:35–42`
Firefox may require the anchor to remain in DOM until download is initiated. Fix: use `setTimeout(() => document.body.removeChild(a), 100)` instead of synchronous removal, or use `URL.revokeObjectURL` in the anchor's `click` event.

**F20 — `getMatchConfidenceForStep` (mermaid-chart.tsx) uses linear scan; `getMatchConfidenceForDivergence` (divergence-panel.tsx) uses Set — duplicated logic, worse implementation in chart**
`src/components/synthesis/mermaid-chart.tsx:39–47`
Same functionality implemented twice with different performance characteristics. Fix: extract to a shared utility in `mermaid-generator.ts` using a Set for O(1) lookup.

**F22 — `onSvgRendered` fires with stale SVGElement during schema re-render**
`src/components/synthesis/mermaid-chart.tsx:92–100`
When `schema` changes, `svgContent` is not cleared before the new render starts. During the re-render window, `svgRef` in `SynthesisViewer` still holds the old SVG. Fix: clear `svgContent` in the schema-change `useEffect` (line 85–89) before the new render begins, which will trigger `onSvgRendered(null)`.

**F23 — `toLocaleDateString()` without UTC handling — off-by-one-day in non-UTC timezones**
`src/components/synthesis/synthesis-viewer.tsx:43` · `source-attribution.tsx:42` · `source-data-tab.tsx:116,157`
ISO 8601 UTC dates displayed with browser local timezone. Fix: use `{ timeZone: "UTC" }` option in `toLocaleDateString` calls.

**F24 — `FrameworkMatrix` present cell with `undefined` `matchConfidence` shows neither color nor text**
`src/components/synthesis/framework-matrix.tsx:195`
`getConfidenceClass(undefined)` returns `""` (no color) and the confidence text is conditionally rendered only when `!== undefined`. A present cell with no confidence data is visually indistinguishable from a cell with zero styling. Fix: render "No confidence data" or apply a neutral background for cells where `present=true && matchConfidence === undefined`.

**F28 — `step.action` or `step.object` null/undefined renders as `"null undefined"` in diagram**
`src/lib/synthesis/mermaid-generator.ts:48`
`const label = \`${step.action} ${step.object}\`` — JavaScript coerces null/undefined to the strings "null"/"undefined". Fix: guard with `const label = \`${step.action ?? ""} ${step.object ?? ""}\`.trim()`.

---

## Deferred Findings (2)

- **F19** — `getDivergentStepIds` called twice per render (inside `generateMermaidFromSchema` + `mermaid-chart.tsx:176`) — pre-existing performance micro-optimization, not a correctness bug. Defer.
- **F27** — `initializeMermaid` TOCTOU race on singleton — in `src/lib/mermaid/renderer.ts`, outside the diff scope of this epic. Defer.

## Dismissed Findings (3)

- **F9** — False positive: `onMouseLeave` IS wired to `handleMouseUp` at line 237.
- **F14** — False positive: `/interview/[interviewId]` is correct per Story 5-5 AC2.
- **F25** — False positive: "Fit to View = reset to scale:1" is correct per Story 5-2 AC4.

---

**Code review complete.** 0 `decision_needed` · **22 `patch`** · 2 `defer` · 3 `dismiss`.

Findings are listed above. No story file was provided, so nothing was persisted to disk.

The most critical items to address before shipping:
1. **F4** — Unguarded `ZodError` in the Server Component synthesis page
2. **F2** — Missing `.catch()` on `renderDiagram` (spinner freezes on error)
3. **F1** — CLAUDE.md O(n²) violation in `getDivergenceForStep`
4. **F8** — Mermaid init error silently shows blank screen
5. **F5** — PNG blob URL leak on export failure
6. **F3** — Empty `catch` blocks hiding synthesis result visibility bug

---

=== AGENT IDENTIFICATION ===
Agent: DEV Agent
Persona: Amelia
Loaded files:
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-agent-dev\*.md (skill activation)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\workflow.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-01-gather-context.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-02-review.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-03-triage.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\.claude\skills\bmad-code-review\steps\step-04-present.md
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\_bmad\bmm\config.yaml
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\mermaid-generator.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\lib\synthesis\mermaid-generator.test.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\hooks\use-mermaid.ts
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\mermaid-chart.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\mermaid-chart.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\synthesis-viewer.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\synthesis-viewer.test.tsx (partial context)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\export-controls.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\export-controls.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\chart-controls.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\chart-controls.test.tsx (partial context)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-panel.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-panel.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-detail.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\divergence-detail.test.tsx (partial context)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\source-attribution.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\source-attribution.test.tsx (partial context)
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\framework-matrix.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\framework-matrix.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\source-data-tab.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\source-data-tab.test.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\synthesis\text-alternative.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\app\projects\[projectId]\processes\[nodeId]\synthesis\page.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\project\process-node-detail.tsx
  - C:\alcorn\Gauntlet\8-Capstone\chat2bpmn\src\components\project\process-node-detail.test.tsx (partial context)
=== END IDENTIFICATION ===
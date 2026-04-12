I'll wait for the background agents to complete before proceeding with the full review. Let me also start reading the source files in parallel.
Let me also kick off reading of the remaining source files while waiting.
Let me read the remaining files while waiting.
Waiting for all background agents to complete their file reading.
The agent output files seem to be empty. Let me read the source files directly instead while waiting.
Now let me check a few more critical files before writing the review.
I now have enough information to write a comprehensive review. Let me check one more critical item:
Now I have enough to write the complete review. Let me check a couple more issues:
I have sufficient information for a thorough review. Here is the complete review:

---

```
agent_role: reviewer
task_id: epic-4-review
timestamp: 2026-04-12T12:01:47.766826+00:00
input_files: [_bmad-output/implementation-artifacts/4-1-stage-1-extraction-diagram-exchange-decomposition.md, _bmad-output/implementation-artifacts/4-2-process-schema-definition-and-validation.md, _bmad-output/implementation-artifacts/4-3-stage-3-match-llm-step-matching.md, _bmad-output/implementation-artifacts/4-4-stage-4-classify-divergence-implicit-step-classification.md, _bmad-output/implementation-artifacts/4-5-stage-5-narrate-explanation-output-generation.md, _bmad-output/implementation-artifacts/4-6-synthesis-pipeline-orchestration.md, _bmad-output/implementation-artifacts/4-7-audit-trail-three-source-attribution.md, eslint.config.js, rebuild-status.md, src/app/api/interview/[token]/schema/route.test.ts, src/app/api/interview/[token]/schema/route.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/[resultId]/provenance/[stepId]/route.test.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/[resultId]/provenance/[stepId]/route.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/route.test.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/route.ts, src/app/api/projects/[projectId]/skill-overrides/route.test.ts, src/app/api/projects/[projectId]/skill-preview/route.test.ts, src/app/api/schema/route.test.ts, src/app/api/schema/route.ts, src/components/project/process-node-detail.test.tsx, src/components/project/process-node-detail.tsx, src/components/project/synthesis-readiness.test.tsx, src/components/project/synthesis-readiness.tsx, src/lib/ai/prompts/synthesis/classify-template.test.ts, src/lib/ai/prompts/synthesis/classify-template.ts, src/lib/ai/prompts/synthesis/extract-template.test.ts, src/lib/ai/prompts/synthesis/extract-template.ts, src/lib/ai/prompts/synthesis/match-template.test.ts, src/lib/ai/prompts/synthesis/match-template.ts, src/lib/ai/prompts/synthesis/narrate-template.test.ts, src/lib/ai/prompts/synthesis/narrate-template.ts, src/lib/db/queries/interview-exchanges.test.ts, src/lib/db/queries/interview-exchanges.ts, src/lib/db/queries/interviews.ts, src/lib/db/queries/projects.ts, src/lib/db/queries/structured-captures.test.ts, src/lib/db/queries/structured-captures.ts, src/lib/db/queries/synthesis-checkpoints.test.ts, src/lib/db/queries/synthesis-checkpoints.ts, src/lib/db/queries/synthesis-results.test.ts, src/lib/db/queries/synthesis-results.ts, src/lib/db/schema.ts, src/lib/interview/capture.test.ts, src/lib/interview/capture.ts, src/lib/schema/workflow-debug.test.ts, src/lib/schema/workflow.test.ts, src/lib/schema/workflow.ts, src/lib/synthesis/correlator.test.ts, src/lib/synthesis/correlator.ts, src/lib/synthesis/divergence.test.ts, src/lib/synthesis/divergence.ts, src/lib/synthesis/engine.test.ts, src/lib/synthesis/engine.ts, src/lib/synthesis/narrator.test.ts, src/lib/synthesis/narrator.ts]
reviewer_type: claude
review_scope: epic
---

# Epic Code Review — CLAUDE Reviewer

## Summary

Epic 4 delivers a well-structured five-stage synthesis pipeline (Extract → Match → Classify → Narrate + Audit) with strong schema validation, typed error handling, and checkpoint resumption. The implementation is largely coherent, but carries several correctness bugs and one significant CLAUDE.md rule violation that need addressing before this code is production-safe.

## Findings

### 1. Wrong skill stage passed to `assembleSynthesisPrompt` in Stage 1 extraction
- **File:** `src/lib/interview/capture.ts:82`
- **Issue:** The call is `assembleSynthesisPrompt("match", skill)` but this is Stage 1 (Extract). The stage argument controls which skill context section is injected into the prompt. Passing `"match"` injects match-stage instructions into an extract-stage LLM call, producing a semantically wrong prompt.
- **Severity:** critical
- **Action:** Change the argument to `"extract"` (or the equivalent stage key recognized by `prompt-assembler.ts`). This is a cross-story integration defect: Story 4.1 (Extract) implemented the call before Story 4.3 (Match) defined the stage key, and the wrong key was carried forward.

### 2. Stage 5 (Narrate) drops `_durationMs` — LLM attribution is incomplete
- **File:** `src/lib/synthesis/narrator.ts:288`
- **Issue:** `_durationMs` is computed but never persisted. Unlike Stages 3 and 4 (correlator.ts, divergence.ts), which both pass `durationMs` to `createSynthesisCheckpoint`, Stage 5 discards the measurement entirely. Stage 5 does not write a checkpoint — it writes a `synthesis_results` row — but the duration is still useful for audit/monitoring and the architecture spec calls for it. The leading underscore signals "unused" and should be a compile warning rather than silently ignored data loss.
- **Severity:** minor
- **Action:** Either pass `durationMs` to `createSynthesisResult` (requires a schema column) or remove the computation entirely. Do not leave an `_`-prefixed variable that silently discards audit data in production code.

### 3. `childStepIds` from Stage 3 LLM output is parsed but silently dropped on mapping
- **File:** `src/lib/synthesis/correlator.ts:133–153`
- **Issue:** `MatchLLMPairSchema` accepts `childStepIds` (line 44) from the LLM, but `mapToMatchMetadata` omits it when constructing the `MatchMetadata` object. `MatchPairSchema` in `workflow.ts` does not include a `childStepIds` field — so the data the LLM provides is discarded without error or warning. Stage 4 (classify) receives `matchMetadata.matchPairs` to identify subsumption pairs but has no `childStepIds` to enrich its analysis. The classify template instructs the LLM to derive parent/child relationships anew.
- **Severity:** major
- **Action:** Either (a) add `childStepIds` to `MatchPairSchema` in `workflow.ts` so it flows through to Stage 4, or (b) remove `childStepIds` from `MatchLLMPairSchema` if it is intentionally a prompt-only hint. Document the design decision explicitly. Silent data loss in a data pipeline is always a defect.

### 4. `divergence.ts` and `narrator.ts` do not call their own template functions
- **File:** `src/lib/synthesis/divergence.ts`, `src/lib/synthesis/narrator.ts`
- **Issue:** `getClassifyTemplate()` in `classify-template.ts` and `getNarrateTemplate()` in `narrate-template.ts` are defined but never imported or called in `divergence.ts` or `narrator.ts`. Both files rely entirely on `assembleSynthesisPrompt()` to assemble the prompt, which injects skill context but not the stage-specific instruction block. The match stage correctly calls `getMatchTemplate()` (correlator.ts:6,122). The extract stage calls `getExtractTemplate()` (capture.ts:17,82). The classify and narrate stages omit this step, meaning the LLM receives domain skill context but no structural instructions for what to output.
- **Severity:** critical
- **Action:** Import and call `getClassifyTemplate()` and `getNarrateTemplate()` in their respective stage runners and prepend them to the assembled prompt, consistent with the pattern in correlator.ts and capture.ts. The test mocks for these functions confirm they exist and are expected to be called — but the tests themselves mock the functions and do not catch the missing call.

### 5. Schema confirmation transaction in `[token]/schema/route.ts` does not include status transitions
- **File:** `src/app/api/interview/[token]/schema/route.ts:50–63`
- **Issue:** The code wraps only the `individual_process_schemas` update in a `db.transaction()` (lines 50–58), then calls `transitionInterviewStatus` twice outside the transaction (lines 62–63). If the process crashes or the DB connection drops between confirming the schema and transitioning status, the individual_process_schema is confirmed but the interview remains `active` — permanently stuck. CLAUDE.md requires: "When a route handler or service function performs 2+ DB mutations, wrap them in a `db.transaction()`." Three mutations occur across two calls; only one is wrapped.
- **Severity:** critical
- **Action:** Extend the transaction to include both `transitionInterviewStatus` calls. If `transitionInterviewStatus` in `state-machine.ts` does not accept a transaction object, expose a transaction-aware variant or inline the update.

### 6. `capture.ts` null-checks `provider` but `registry.resolveProvider` is typed to never return null
- **File:** `src/lib/interview/capture.ts:103–111`
- **Issue:** The code calls `registry.resolveProvider(...)` then immediately checks `if (!provider)` and throws an `LLMError`. The identical call pattern in `correlator.ts`, `divergence.ts`, and `narrator.ts` does not include this null check. Either the registry can return null (in which case all three stage runners are missing the guard), or it cannot (in which case the guard in `capture.ts` is dead code and misleads readers). The inconsistency suggests copy-paste divergence across stories.
- **Severity:** minor
- **Action:** Decide at the registry contract level: `resolveProvider` either throws on missing config (preferred, consistent with CLAUDE.md "functions that return fallback values must validate at module load time") or returns null. Remove the inconsistent null check from `capture.ts` if the registry throws, or add the check uniformly to all stage runners.

### 7. `traceStepProvenance` provenance matching uses exchange-ID overlap instead of direct step ID linkage
- **File:** `src/lib/db/queries/synthesis-results.ts:193–195`
- **Issue:** `traceStepProvenance` finds the `StructuredStep` for each interview by checking `s.sourceExchangeIds.some((id) => allExchangeIds.includes(id))`. This is an O(n²) membership check with a linear scan inside `.includes()`. For large captures with many steps and exchanges, this degrades noticeably. More critically, it can produce false positives: if two different structured steps in the same interview reference an exchange that happens to be in `allExchangeIds` (e.g., a multi-step exchange), both steps match and the first one wins arbitrarily. The correct anchor would be the `stepId` from the `WorkflowStep.sources` array if it were persisted, or matching by `intervieweeName` + `sourceExchangeIds` intersection rather than union membership.
- **Severity:** major
- **Action:** Replace `.includes(id)` with a `Set` lookup (`allExchangeIdsSet.has(id)`) to fix the O(n²) performance issue. Consider whether the matching semantics are correct for the provenance accuracy guarantee; if a step maps to multiple structured steps via exchange overlap, the audit trail silently drops all but the first.

### 8. `structuredCaptures` table has a redundant index alongside its unique constraint
- **File:** `src/lib/db/schema.ts:255–274`
- **Issue:** `structuredCaptures` declares `interviewId` as both `unique()` (column-level, line 261) and indexed again via `index("idx_structured_captures_interview_id")` in the table constraints (line 269). The unique constraint already creates an implicit B-tree index in PostgreSQL; the explicit `index()` is redundant and wastes storage. CLAUDE.md: "Use `index()` for query-performance indexes and `unique()` only when the column(s) must enforce a uniqueness constraint."
- **Severity:** minor
- **Action:** Remove the `index("idx_structured_captures_interview_id")` entry from the table constraints block — the unique constraint on `interviewId` already provides the query-performance benefit.

### 9. `StructuredCaptureSchema` in `workflow.ts` is inconsistent with `capture.ts` persistence
- **File:** `src/lib/interview/capture.ts:146–150`, `src/lib/schema/workflow.ts:58–69`
- **Issue:** `createStructuredCapture` is called with `captureJson: steps` — just an array of `StructuredStep[]`. But `StructuredCaptureSchema` expects a full object with `captureId`, `interviewId`, `steps`, `stepCount`, and `createdAt`. When the engine later calls `StructuredCaptureSchema.parse(captureRow.captureJson)` (engine.ts:67), it will throw a Zod validation error because the stored JSON is a bare array, not the `StructuredCaptureSchema` envelope shape. This is a latent critical bug masked by the fact that the schema route endpoint and engine both call the same `findStructuredCaptureByInterview`, but the actual `captureJson` column stores a raw `StructuredStep[]` array, not a `StructuredCapture` object.
- **Severity:** critical
- **Action:** Either (a) persist the full `StructuredCapture` envelope (with `captureId`, `interviewId`, `stepCount`, `createdAt`, `steps`) into `captureJson`, or (b) update `engine.ts:67` to parse `captureRow.captureJson` as `z.array(StructuredStepSchema)` and reconstruct the envelope from the DB row's own fields (`captureId`, `interviewId`, `stepCount`, `createdAt`). Option (b) is less brittle as it keeps the canonical shape in the DB columns rather than duplicated in JSONB.

### 10. `SynthesisReadiness` component is rendered with a hard-coded `capturedCount` that resets to 0 on node change
- **File:** `src/components/project/process-node-detail.tsx:71,122`
- **Issue:** `capturedCount` is initialized to `0` and is reset to `0` every time the node changes (line 122 in the `useEffect` that syncs with `node.nodeId`). The async `fetchCapturedCount` then runs, but there is a race: if the user triggers synthesis immediately after switching nodes (before the fetch resolves), `capturedCount` will be `0` and the `SynthesisReadiness` button will be disabled. This is an existing UX timing gap, not a data-correctness issue, but it can confuse users.
- **Severity:** minor
- **Action:** Accept as a known UX limitation or track a loading state that disables the synthesis button while `fetchCapturedCount` is in flight.

### 11. `SynthesisCheckpointRow.stage` type is narrower than the DB enum
- **File:** `src/lib/db/queries/synthesis-checkpoints.ts:10`
- **Issue:** `SynthesisCheckpointRow.stage` is typed as `"match" | "classify"` but the DB enum `synthesisStageEnum` includes `"narrate"` as well. Stage 5 (Narrate) does not write a checkpoint (by design), but if it ever did — or if the DB is queried directly — rows with `stage = "narrate"` would fail the TypeScript type and produce a runtime cast error. More immediately, `findLatestCheckpoint` accepts only `"match" | "classify"` as input, which is correct by spec, but the `SynthesisCheckpointRow` type should mirror the full enum to avoid future type drift.
- **Severity:** minor
- **Action:** Update `SynthesisCheckpointRow.stage` to include `"narrate"` so the type accurately reflects the DB schema, even if no current code writes narrate checkpoints.

### 12. `process-node-detail.tsx` has a dead state variable `hasInterviews`
- **File:** `src/components/project/process-node-detail.tsx:70`
- **Issue:** `const [hasInterviews] = useState(false)` is initialized to `false` and never updated. It is used on line 299 to conditionally render a UI note ("Changes apply to new interviews only"), which will therefore never render. This is dead code from a stub left in place.
- **Severity:** minor
- **Action:** Either remove `hasInterviews` and the conditional block, or populate it from the interviews API response alongside `capturedCount`.
```

I have sufficient information for a thorough review. Here is the complete review:

---

```
agent_role: reviewer
task_id: epic-4-review
timestamp: 2026-04-12T12:01:47.766826+00:00
input_files: [_bmad-output/implementation-artifacts/4-1-stage-1-extraction-diagram-exchange-decomposition.md, _bmad-output/implementation-artifacts/4-2-process-schema-definition-and-validation.md, _bmad-output/implementation-artifacts/4-3-stage-3-match-llm-step-matching.md, _bmad-output/implementation-artifacts/4-4-stage-4-classify-divergence-implicit-step-classification.md, _bmad-output/implementation-artifacts/4-5-stage-5-narrate-explanation-output-generation.md, _bmad-output/implementation-artifacts/4-6-synthesis-pipeline-orchestration.md, _bmad-output/implementation-artifacts/4-7-audit-trail-three-source-attribution.md, eslint.config.js, rebuild-status.md, src/app/api/interview/[token]/schema/route.test.ts, src/app/api/interview/[token]/schema/route.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/[resultId]/provenance/[stepId]/route.test.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/[resultId]/provenance/[stepId]/route.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/route.test.ts, src/app/api/projects/[projectId]/processes/[nodeId]/synthesis/route.ts, src/app/api/projects/[projectId]/skill-overrides/route.test.ts, src/app/api/projects/[projectId]/skill-preview/route.test.ts, src/app/api/schema/route.test.ts, src/app/api/schema/route.ts, src/components/project/process-node-detail.test.tsx, src/components/project/process-node-detail.tsx, src/components/project/synthesis-readiness.test.tsx, src/components/project/synthesis-readiness.tsx, src/lib/ai/prompts/synthesis/classify-template.test.ts, src/lib/ai/prompts/synthesis/classify-template.ts, src/lib/ai/prompts/synthesis/extract-template.test.ts, src/lib/ai/prompts/synthesis/extract-template.ts, src/lib/ai/prompts/synthesis/match-template.test.ts, src/lib/ai/prompts/synthesis/match-template.ts, src/lib/ai/prompts/synthesis/narrate-template.test.ts, src/lib/ai/prompts/synthesis/narrate-template.ts, src/lib/db/queries/interview-exchanges.test.ts, src/lib/db/queries/interview-exchanges.ts, src/lib/db/queries/interviews.ts, src/lib/db/queries/projects.ts, src/lib/db/queries/structured-captures.test.ts, src/lib/db/queries/structured-captures.ts, src/lib/db/queries/synthesis-checkpoints.test.ts, src/lib/db/queries/synthesis-checkpoints.ts, src/lib/db/queries/synthesis-results.test.ts, src/lib/db/queries/synthesis-results.ts, src/lib/db/schema.ts, src/lib/interview/capture.test.ts, src/lib/interview/capture.ts, src/lib/schema/workflow-debug.test.ts, src/lib/schema/workflow.test.ts, src/lib/schema/workflow.ts, src/lib/synthesis/correlator.test.ts, src/lib/synthesis/correlator.ts, src/lib/synthesis/divergence.test.ts, src/lib/synthesis/divergence.ts, src/lib/synthesis/engine.test.ts, src/lib/synthesis/engine.ts, src/lib/synthesis/narrator.test.ts, src/lib/synthesis/narrator.ts]
reviewer_type: claude
review_scope: epic
---

# Epic Code Review — CLAUDE Reviewer

## Summary

Epic 4 delivers a well-structured five-stage synthesis pipeline (Extract → Match → Classify → Narrate + Audit) with strong schema validation, typed error handling, and checkpoint resumption. The implementation is largely coherent, but carries several correctness bugs and one significant CLAUDE.md rule violation that need addressing before this code is production-safe.

## Findings

### 1. Wrong skill stage passed to `assembleSynthesisPrompt` in Stage 1 extraction
- **File:** `src/lib/interview/capture.ts:82`
- **Issue:** The call is `assembleSynthesisPrompt("match", skill)` but this is Stage 1 (Extract). The stage argument controls which skill context section is injected into the prompt. Passing `"match"` injects match-stage instructions into an extract-stage LLM call, producing a semantically wrong prompt.
- **Severity:** critical
- **Action:** Change the argument to `"extract"` (or the equivalent stage key recognized by `prompt-assembler.ts`). This is a cross-story integration defect: Story 4.1 (Extract) implemented the call before Story 4.3 (Match) defined the stage key, and the wrong key was carried forward.

### 2. Stage 5 (Narrate) drops `_durationMs` — LLM attribution is incomplete
- **File:** `src/lib/synthesis/narrator.ts:288`
- **Issue:** `_durationMs` is computed but never persisted. Unlike Stages 3 and 4 (correlator.ts, divergence.ts), which both pass `durationMs` to `createSynthesisCheckpoint`, Stage 5 discards the measurement entirely. Stage 5 does not write a checkpoint — it writes a `synthesis_results` row — but the duration is still useful for audit/monitoring and the architecture spec calls for it. The leading underscore signals "unused" and should be a compile warning rather than silently ignored data loss.
- **Severity:** minor
- **Action:** Either pass `durationMs` to `createSynthesisResult` (requires a schema column) or remove the computation entirely. Do not leave an `_`-prefixed variable that silently discards audit data in production code.

### 3. `childStepIds` from Stage 3 LLM output is parsed but silently dropped on mapping
- **File:** `src/lib/synthesis/correlator.ts:133–153`
- **Issue:** `MatchLLMPairSchema` accepts `childStepIds` (line 44) from the LLM, but `mapToMatchMetadata` omits it when constructing the `MatchMetadata` object. `MatchPairSchema` in `workflow.ts` does not include a `childStepIds` field — so the data the LLM provides is discarded without error or warning. Stage 4 (classify) receives `matchMetadata.matchPairs` to identify subsumption pairs but has no `childStepIds` to enrich its analysis. The classify template instructs the LLM to derive parent/child relationships anew.
- **Severity:** major
- **Action:** Either (a) add `childStepIds` to `MatchPairSchema` in `workflow.ts` so it flows through to Stage 4, or (b) remove `childStepIds` from `MatchLLMPairSchema` if it is intentionally a prompt-only hint. Document the design decision explicitly. Silent data loss in a data pipeline is always a defect.

### 4. `divergence.ts` and `narrator.ts` do not call their own template functions
- **File:** `src/lib/synthesis/divergence.ts`, `src/lib/synthesis/narrator.ts`
- **Issue:** `getClassifyTemplate()` in `classify-template.ts` and `getNarrateTemplate()` in `narrate-template.ts` are defined but never imported or called in `divergence.ts` or `narrator.ts`. Both files rely entirely on `assembleSynthesisPrompt()` to assemble the prompt, which injects skill context but not the stage-specific instruction block. The match stage correctly calls `getMatchTemplate()` (correlator.ts:6,122). The extract stage calls `getExtractTemplate()` (capture.ts:17,82). The classify and narrate stages omit this step, meaning the LLM receives domain skill context but no structural instructions for what to output.
- **Severity:** critical
- **Action:** Import and call `getClassifyTemplate()` and `getNarrateTemplate()` in their respective stage runners and prepend them to the assembled prompt, consistent with the pattern in correlator.ts and capture.ts. The test mocks for these functions confirm they exist and are expected to be called — but the tests themselves mock the functions and do not catch the missing call.

### 5. Schema confirmation transaction in `[token]/schema/route.ts` does not include status transitions
- **File:** `src/app/api/interview/[token]/schema/route.ts:50–63`
- **Issue:** The code wraps only the `individual_process_schemas` update in a `db.transaction()` (lines 50–58), then calls `transitionInterviewStatus` twice outside the transaction (lines 62–63). If the process crashes or the DB connection drops between confirming the schema and transitioning status, the individual_process_schema is confirmed but the interview remains `active` — permanently stuck. CLAUDE.md requires: "When a route handler or service function performs 2+ DB mutations, wrap them in a `db.transaction()`." Three mutations occur across two calls; only one is wrapped.
- **Severity:** critical
- **Action:** Extend the transaction to include both `transitionInterviewStatus` calls. If `transitionInterviewStatus` in `state-machine.ts` does not accept a transaction object, expose a transaction-aware variant or inline the update.

### 6. `capture.ts` null-checks `provider` but `registry.resolveProvider` is typed to never return null
- **File:** `src/lib/interview/capture.ts:103–111`
- **Issue:** The code calls `registry.resolveProvider(...)` then immediately checks `if (!provider)` and throws an `LLMError`. The identical call pattern in `correlator.ts`, `divergence.ts`, and `narrator.ts` does not include this null check. Either the registry can return null (in which case all three stage runners are missing the guard), or it cannot (in which case the guard in `capture.ts` is dead code and misleads readers). The inconsistency suggests copy-paste divergence across stories.
- **Severity:** minor
- **Action:** Decide at the registry contract level: `resolveProvider` either throws on missing config (preferred, consistent with CLAUDE.md "functions that return fallback values must validate at module load time") or returns null. Remove the inconsistent null check from `capture.ts` if the registry throws, or add the check uniformly to all stage runners.

### 7. `traceStepProvenance` provenance matching uses exchange-ID overlap instead of direct step ID linkage
- **File:** `src/lib/db/queries/synthesis-results.ts:193–195`
- **Issue:** `traceStepProvenance` finds the `StructuredStep` for each interview by checking `s.sourceExchangeIds.some((id) => allExchangeIds.includes(id))`. This is an O(n²) membership check with a linear scan inside `.includes()`. For large captures with many steps and exchanges, this degrades noticeably. More critically, it can produce false positives: if two different structured steps in the same interview reference an exchange that happens to be in `allExchangeIds` (e.g., a multi-step exchange), both steps match and the first one wins arbitrarily. The correct anchor would be the `stepId` from the `WorkflowStep.sources` array if it were persisted, or matching by `intervieweeName` + `sourceExchangeIds` intersection rather than union membership.
- **Severity:** major
- **Action:** Replace `.includes(id)` with a `Set` lookup (`allExchangeIdsSet.has(id)`) to fix the O(n²) performance issue. Consider whether the matching semantics are correct for the provenance accuracy guarantee; if a step maps to multiple structured steps via exchange overlap, the audit trail silently drops all but the first.

### 8. `structuredCaptures` table has a redundant index alongside its unique constraint
- **File:** `src/lib/db/schema.ts:255–274`
- **Issue:** `structuredCaptures` declares `interviewId` as both `unique()` (column-level, line 261) and indexed again via `index("idx_structured_captures_interview_id")` in the table constraints (line 269). The unique constraint already creates an implicit B-tree index in PostgreSQL; the explicit `index()` is redundant and wastes storage. CLAUDE.md: "Use `index()` for query-performance indexes and `unique()` only when the column(s) must enforce a uniqueness constraint."
- **Severity:** minor
- **Action:** Remove the `index("idx_structured_captures_interview_id")` entry from the table constraints block — the unique constraint on `interviewId` already provides the query-performance benefit.

### 9. `StructuredCaptureSchema` in `workflow.ts` is inconsistent with `capture.ts` persistence
- **File:** `src/lib/interview/capture.ts:146–150`, `src/lib/schema/workflow.ts:58–69`
- **Issue:** `createStructuredCapture` is called with `captureJson: steps` — just an array of `StructuredStep[]`. But `StructuredCaptureSchema` expects a full object with `captureId`, `interviewId`, `steps`, `stepCount`, and `createdAt`. When the engine later calls `StructuredCaptureSchema.parse(captureRow.captureJson)` (engine.ts:67), it will throw a Zod validation error because the stored JSON is a bare array, not the `StructuredCaptureSchema` envelope shape. This is a latent critical bug masked by the fact that the schema route endpoint and engine both call the same `findStructuredCaptureByInterview`, but the actual `captureJson` column stores a raw `StructuredStep[]` array, not a `StructuredCapture` object.
- **Severity:** critical
- **Action:** Either (a) persist the full `StructuredCapture` envelope (with `captureId`, `interviewId`, `stepCount`, `createdAt`, `steps`) into `captureJson`, or (b) update `engine.ts:67` to parse `captureRow.captureJson` as `z.array(StructuredStepSchema)` and reconstruct the envelope from the DB row's own fields (`captureId`, `interviewId`, `stepCount`, `createdAt`). Option (b) is less brittle as it keeps the canonical shape in the DB columns rather than duplicated in JSONB.

### 10. `SynthesisReadiness` component is rendered with a hard-coded `capturedCount` that resets to 0 on node change
- **File:** `src/components/project/process-node-detail.tsx:71,122`
- **Issue:** `capturedCount` is initialized to `0` and is reset to `0` every time the node changes (line 122 in the `useEffect` that syncs with `node.nodeId`). The async `fetchCapturedCount` then runs, but there is a race: if the user triggers synthesis immediately after switching nodes (before the fetch resolves), `capturedCount` will be `0` and the `SynthesisReadiness` button will be disabled. This is an existing UX timing gap, not a data-correctness issue, but it can confuse users.
- **Severity:** minor
- **Action:** Accept as a known UX limitation or track a loading state that disables the synthesis button while `fetchCapturedCount` is in flight.

### 11. `SynthesisCheckpointRow.stage` type is narrower than the DB enum
- **File:** `src/lib/db/queries/synthesis-checkpoints.ts:10`
- **Issue:** `SynthesisCheckpointRow.stage` is typed as `"match" | "classify"` but the DB enum `synthesisStageEnum` includes `"narrate"` as well. Stage 5 (Narrate) does not write a checkpoint (by design), but if it ever did — or if the DB is queried directly — rows with `stage = "narrate"` would fail the TypeScript type and produce a runtime cast error. More immediately, `findLatestCheckpoint` accepts only `"match" | "classify"` as input, which is correct by spec, but the `SynthesisCheckpointRow` type should mirror the full enum to avoid future type drift.
- **Severity:** minor
- **Action:** Update `SynthesisCheckpointRow.stage` to include `"narrate"` so the type accurately reflects the DB schema, even if no current code writes narrate checkpoints.

### 12. `process-node-detail.tsx` has a dead state variable `hasInterviews`
- **File:** `src/components/project/process-node-detail.tsx:70`
- **Issue:** `const [hasInterviews] = useState(false)` is initialized to `false` and never updated. It is used on line 299 to conditionally render a UI note ("Changes apply to new interviews only"), which will therefore never render. This is dead code from a stub left in place.
- **Severity:** minor
- **Action:** Either remove `hasInterviews` and the conditional block, or populate it from the interviews API response alongside `capturedCount`.
```

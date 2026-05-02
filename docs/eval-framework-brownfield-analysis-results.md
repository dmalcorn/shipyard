# Eval Framework Analysis: chat2bpmn Testing Posture

**Analysis date:** 2026-04-13  
**Framework applied:** Five Eval Categories (Production Evals Cookbook)  
**Project:** chat2bpmn — AI-powered workflow discovery and BPMN generation

---

## 1. Test Inventory

### Infrastructure

| Item | Finding |
|---|---|
| Test framework | Vitest 4.1.4 |
| Test environment | Node.js (not browser) |
| Setup file | `vitest.setup.ts` — env stubs only |
| Workers | Forks pool, max 4 workers, 2 GB heap |
| Coverage reporting | **None configured** |
| CI/CD pipeline | **None** (no `.github/workflows/` directory) |
| Fixture files | **None** |
| Snapshot files (`.snap`) | **None** |
| Test utilities | **None** (no shared test-utils or test-helpers) |
| npm test scripts | `vitest run` (single pass), `vitest` (watch) — no coverage script |

### Test File Summary

| Domain | Files | Approximate test cases |
|---|---|---|
| Smoke / bootstrap | 1 | 2 |
| Middleware and auth | 3 | ~21 |
| Auth API routes | 3 | ~13 |
| Project API routes | 4 | ~25 |
| Interview and exchange API routes | 6 | ~30 |
| Process and synthesis API routes | 11 | ~50 |
| AI providers and model registry | 5 | ~75 |
| Synthesis pipeline (engine, correlator, divergence, BPMN, Mermaid, narrator) | 7 | ~120 |
| Schema and Zod validation | 3 | ~165 |
| Database query functions | 14 | ~100 |
| Interview session and capture | 5 | ~40 |
| Process tree operations | 5 | ~40 |
| LLM prompt assembly and synthesis templates | 6 | ~65 |
| Error handling | 1 | 3 |
| React hooks | 2 | ~10 |
| STT providers | 2 | ~15 |
| Environment and type definitions | 2 | ~11 |
| **Totals** | **93** | **~785** |

---

## 2. Classification by Eval Category

### Golden Set

**Definition:** Small (10–20 cases), hand-verified, always blocking, dual assertions (positive and negative), covers core value proposition.

**Findings:**

The project has **no explicitly designated golden set tier.** No tests are labeled "smoke" (meaningfully), "sanity," "critical," or "happy path" with respect to domain behavior. The one file named `smoke.test.ts` tests basic arithmetic and TypeScript runtime — it verifies the test runner, not the application.

The closest approximations to golden set behavior are:

| File | Cases | Golden Set Signals |
|---|---|---|
| `src/lib/api/error-handler.test.ts` | 3 | Small, critical, dual-assertion (error code + HTTP status), covers a non-negotiable invariant |
| `src/lib/auth/config.test.ts` | 7 | Small, real bcrypt (not mocked), dual-assertion (success + failure paths), covers auth primitive |
| `src/lib/env.test.ts` | 7 | Small, Zod safeParse, dual-assertion (valid config + individual field failures), blocking correctness |
| `src/lib/synthesis/state-machine.test.ts` | 19 | Critical invariant (illegal status transitions), dual-assertion, covers a core lifecycle rule from the architecture spec |
| `src/middleware.test.ts` | 10 | Route protection — defines who can access what, dual-assertion (redirect + pass-through) |
| `src/lib/interview/depth-flag-parser.test.ts` | 13 | XML/JSON parse from LLM output, dual-assertion (valid + malformed inputs) |

**Assessment:** These six suites collectively exhibit golden set quality — small, hand-verified, dual-assertion, covering critical invariants. However, they are **not designated or treated as blocking.** There is no CI pipeline that runs them as a mandatory gate. They are mixed into the same undifferentiated `vitest run` that executes all 93 test files. A regression in the state machine or error handler would not surface as a distinct blocking signal; it would appear as one failure in a run of ~785 tests.

**Estimated count meeting golden set criteria:** ~60 cases across 6 suites

---

### Labeled Scenarios

**Definition:** Larger suites (30–100+ cases) organized by domain, type, or complexity. May have some acceptable failures. Results show coverage shape, not just pass/fail.

**Findings:**

The project's test organization is strongly domain-structured. Test files are co-located with source files and mirror the directory hierarchy. This implicit labeling creates a reasonable coverage map by directory:

| Domain label (via directory) | Representative suites |
|---|---|
| Authentication | `api/auth/login`, `api/auth/session`, `api/auth/logout` |
| Project management | `api/projects/route`, `api/projects/[projectId]/route` |
| Process tree | `lib/process/validation`, `lib/process/tree`, `lib/process/status-rollup` |
| Interview lifecycle | `lib/interview/session`, `lib/interview/capture`, `lib/interview/depth-flag-service` |
| Synthesis pipeline | `lib/synthesis/engine`, `lib/synthesis/correlator`, `lib/synthesis/divergence`, `lib/synthesis/narrator`, `lib/synthesis/bpmn-generator`, `lib/synthesis/mermaid-generator` |
| AI providers | `lib/ai/claude-provider`, `lib/ai/openai-provider`, `lib/ai/gemini-provider`, `lib/ai/model-registry` |
| Schema validation | `lib/schema/workflow` (150+ cases covering all schema variants) |
| Database queries | 14 files covering every entity type |

`src/lib/schema/workflow.test.ts` is the clearest labeled scenario suite: 150+ cases covering different schema shapes, field constraints, and optional structures. The coverage spans the schema domain systematically.

**Missing labeled scenario characteristics:**
- No explicit difficulty or complexity tagging on individual test cases
- No parametrized/data-driven test patterns — each case is written out in full
- No coverage report attached to CI (no CI exists)
- No per-release test plan distinguishing which suites must pass vs. which are tracking-only
- No test case metadata describing what category of input each case exercises

**Estimated count with labeled scenario characteristics:** ~550 cases across ~75 suites

---

### Replay Harnesses

**Definition:** Recorded session fixtures (JSON/YAML) captured from real interactions. Mocks backed by those recordings. Tests compute numeric metrics (precision, recall, F1, groundedness, faithfulness) rather than boolean pass/fail.

**Findings:**

**This category is entirely absent.**

| Replay harness component | Status |
|---|---|
| Fixture files capturing real API responses | None |
| VCR cassettes or recorded HTTP sessions | None |
| Fixture directories (`fixtures/`, `__fixtures__/`) | None |
| Snapshot tests (`.snap`) | None |
| Tests computing precision, recall, or accuracy metrics | None |
| Tests comparing current output against a stored baseline | None |
| Mocks populated from recorded real interactions | None |

All mocking in the project uses hand-crafted `vi.fn().mockResolvedValue(...)` responses. This means:

1. The LLM provider mocks (Claude, OpenAI, Gemini) return developer-authored strings, not actual provider responses. There is no guarantee the mocked behavior matches what real providers return.
2. The synthesis pipeline tests run against fabricated structured steps — they do not replay real interview transcript → structured output conversions.
3. If a real provider changes its response shape (e.g., a new field added to the streaming API), tests will not detect it.

The BPMN generator tests (`src/lib/synthesis/bpmn-generator.test.ts`) are the closest approximation: they assert XML structural correctness against expected output. But the inputs are hand-authored, not recorded from real synthesis runs.

**Estimated count meeting replay harness criteria:** 0

---

### Rubric-Based Evaluation

**Definition:** Multi-dimensional quality scoring on a numeric scale. Dimensions include relevance, accuracy, completeness, and clarity. Scores tracked over time. LLM-as-Judge or human rater applies rubric. Fails when quality drops below threshold.

**Findings:**

**This category is entirely absent.**

| Rubric component | Status |
|---|---|
| Numeric quality scores in any test | None |
| Multiple quality dimensions evaluated independently | None |
| Weighted scoring aggregation | None |
| LLM-as-Judge evaluation | None |
| Human rater checklists attached to tests | None |
| Quality trend tracking over time | None |
| Tests asserting a score above a threshold | None |

This is the most critical gap relative to the project's risk profile. chat2bpmn's primary value proposition is:

1. **Interview quality:** Does the AI agent ask useful probing questions? Does it elicit complete step descriptions?
2. **Synthesis accuracy:** Does the correlator correctly match steps across interviews? Does the divergence classifier correctly identify variants vs. errors?
3. **BPMN correctness:** Is the generated BPMN valid and structurally sound?
4. **Narrative quality:** Is the synthesized process narrative accurate and clear?

None of these quality dimensions are currently measurable from the test suite. The synthesis pipeline tests verify that functions execute and return data — they do not measure whether the output is good. A prompt change that degrades synthesis quality by 40% would produce no test failures.

**Estimated count meeting rubric criteria:** 0

---

### Experiments

**Definition:** Same test suite run against multiple named configurations (model versions, prompt variants, temperature settings). Results compared across pass rate, quality score, latency, and cost. Variant definitions version-controlled. Decisions data-driven.

**Findings:**

**This category is entirely absent.**

| Experiment component | Status |
|---|---|
| Named configuration variants | None |
| Same test suite run against multiple configs | None |
| Latency or cost measurement in tests | None |
| A/B test framework | None |
| Feature flag tests with quality tracking | None |
| CI matrix varying env/config combinations | None |
| Benchmark suites for prompt or model comparison | None |

The project stores model and skill configuration in the database (`project.defaultLlmProvider`, `interview.configSnapshot.skillName`) and supports multiple LLM providers (Claude, OpenAI, Gemini). The architecture is explicitly designed for two-dimensional provider/skill separation. However, there is no mechanism to:

- Systematically compare synthesis quality across Claude vs. OpenAI vs. Gemini
- Compare the effect of prompt changes (narrate temperature 0.35 vs. 0.2) on output quality
- Benchmark BPMN structural correctness before and after a prompt update
- Track whether a new model version improves or degrades interview quality

Provider-specific tests exist (`claude-provider.test.ts`, `openai-provider.test.ts`, `gemini-provider.test.ts`), but these test the adapter interface contract — they do not compare quality across providers on the same inputs.

**Estimated count meeting experiment criteria:** 0

---

## 3. Coverage Matrix

```
Eval Category       | Count  | CI Stage        | Blocking? | Notes
--------------------|--------|-----------------|-----------|-------------------------------------------
Golden Set          | ~60    | vitest run      | No        | Not designated; mixed into full suite run
Labeled Scenario    | ~550   | vitest run      | No        | Implicit via directory structure only
Replay Harness      | 0      | —               | —         | Entirely absent
Rubric              | 0      | —               | —         | Entirely absent
Experiment          | 0      | —               | —         | Entirely absent
```

**Total classified tests:** ~610 of ~785  
**Unclassified (test-runner sanity only):** ~2 (`smoke.test.ts`)  
**Estimated uncounted in sampling:** ~173

---

## 4. Gap Analysis

### Gap 1 — No golden set designation or blocking CI gate (High)

The six suites with golden set quality are not protected by any mechanism that distinguishes them from the rest. They run in the same `vitest run` command as 87 other test files. If the state machine or error handler regresses, the signal is one failure in a long run — not a red gate that halts everything.

Additionally, there is no CI pipeline. `vitest run` must be invoked manually. A broken core invariant could be committed and pushed without any automated detection.

**Risk:** Silent regression in a non-negotiable invariant (status transitions, auth routing, error code mapping).

### Gap 2 — No replay harnesses; all mocks hand-crafted (High)

Every LLM provider mock returns developer-authored strings. Every synthesis stage mock returns developer-authored structured data. No test verifies behavior against a recorded real interaction.

The practical consequence: the synthesis pipeline tests (`engine.test.ts`, `narrator.test.ts`, `correlator.test.ts`) verify orchestration logic but cannot detect quality regressions in AI output. If the LLM begins returning malformed step structures, or if the correlator's similarity scoring drifts, tests pass.

Additionally, the BPMN generator tests are the only place where output structure is asserted in detail — but the inputs are fabricated. There are no tests that start from a realistic interview transcript and assert that the generated BPMN meets structural requirements.

**Risk:** Undetected regressions in AI output quality; mocks diverging from real provider behavior over time.

### Gap 3 — No rubric-based evaluation for AI output (Critical)

This is the most significant gap given the project's domain. The entire value chain — from interview transcript to synthesis to BPMN — is AI-generated and cannot be evaluated with boolean assertions alone. "Did it return a response?" and "Is the response valid JSON?" are necessary but not sufficient. "Is the narrative accurate?", "Are the divergences correctly identified?", "Is the BPMN a faithful representation of the synthesized process?" require qualitative scoring.

Without a rubric layer, there is no way to:
- Detect quality drift as prompts evolve
- Compare LLM providers on output quality
- Set a quality bar for the synthesis pipeline before shipping
- Give stakeholders evidence that the system produces reliable output

**Risk:** Shipping synthesis output that is structurally valid but semantically wrong, with no mechanism to detect the degradation.

### Gap 4 — No experiment infrastructure for prompt and model changes (Medium)

The project supports three LLM providers and configures synthesis temperatures per stage. Prompt changes are the primary mechanism for improving AI behavior. Without a comparison harness, every prompt change is deployed on intuition. The current temperatures (`match=0.15`, `classify=0.15`, `narrate=0.35`) were presumably chosen by judgment — there is no record of what alternatives were tested or what quality difference they produced.

**Risk:** Prompt and model changes made without evidence; inability to answer "did this change make the system better?"

### Gap 5 — No coverage measurement (Low-Medium)

`vitest.config.ts` has no coverage section. `package.json` has no coverage script. There is no way to answer "what percentage of the synthesis engine is exercised by tests?" or "which branches in the BPMN generator are not reached?"

This is a lower priority than gaps 1–4 because the test suite is large and domain-organized, but without coverage data the team cannot know where the labeled scenario coverage is thin.

---

## 5. Prioritized Recommendations

### Priority 1 — Designate and gate the golden set

**What:** Identify the ~60 existing tests across the six suites listed in the Golden Set section. Create a Vitest project configuration that marks these as a separate "golden" project, runnable via `npm run test:golden`. Configure that command to run first and fail fast.

**Why now:** This costs almost nothing — the tests already exist. The only missing piece is the designation and the CI gate. The state machine, error handler, middleware, auth config, env validation, and depth-flag parser represent the non-negotiable behavioral contracts of the system. They must be visibly blocking.

**When to ship:** Before the next story begins.

### Priority 2 — Stand up a CI pipeline

**What:** A minimal GitHub Actions workflow that runs `npm run test:golden` on every push to main and every PR. A second job that runs `npm test` (full suite) on PR, non-blocking for now.

**Why now:** Without CI, the golden set designation in Priority 1 is advisory only. Automated enforcement is what makes it a gate.

**When to ship:** Immediately after Priority 1.

### Priority 3 — Record real LLM interactions as test fixtures

**What:** Run the synthesis pipeline against 3–5 realistic multi-interview scenarios using real LLM providers. Save the full interaction (input transcript, each stage's LLM call, structured output) as JSON fixture files in `src/lib/synthesis/__fixtures__/`. Rewrite the synthesis engine tests to replay from these fixtures rather than hand-crafted mocks.

**Why now:** The synthesis pipeline is the core of the product. Hand-crafted mocks currently verify orchestration, not accuracy. Recorded fixtures would allow the tests to detect when a code change breaks the pipeline's ability to correctly process realistic inputs.

**Scope:** Start with 3 fixtures: a simple 2-step linear process, a 4-step process with one divergence, and a complex 6-step process with multiple actors.

**When to ship:** During the next synthesis-related story.

### Priority 4 — Add rubric evaluation for synthesis output quality

**What:** Define a 4-dimension rubric for synthesis output:
1. **Step completeness** — does the synthesized process capture all steps mentioned across interviews? (scored 0–5)
2. **Divergence accuracy** — are identified divergences genuine variants vs. equivalent steps described differently? (scored 0–5)
3. **BPMN structural validity** — does the BPMN pass formal structural validation (correct lane references, collaboration plane reference, all flow nodes in lanes)? (scored 0–5, currently partially tested in `bpmn-generator.test.ts`)
4. **Narrative fidelity** — does the process narrative accurately reflect the structured steps? (scored 0–5, requires LLM-as-Judge or manual review)

Instrument dimensions 1–3 as automated scored tests against the recorded fixtures from Priority 3. Dimension 4 can begin as a manual review checklist.

**Why now:** This is the largest quality blind spot. BPMN structural validity is partially addressable now with automated assertions; the first three dimensions are addressable once fixtures exist.

**When to ship:** After Priority 3 fixtures are in place.

### Priority 5 — Add a coverage report

**What:** Add `@vitest/coverage-v8` to devDependencies. Add a `coverage` section to `vitest.config.ts` with `include: ['src/**/*.ts']` and `exclude: ['**/*.test.ts']`. Add `"test:coverage": "vitest run --coverage"` to `package.json`. Add coverage report as a CI job artifact.

**Why now:** Low effort, high information value. Reveals which paths in the synthesis engine and BPMN generator are not exercised by any test.

**When to ship:** During any story that touches `vitest.config.ts`.

### Priority 6 — Experiment harness for model and prompt comparisons

**What:** Using the recorded fixtures from Priority 3 and the rubric from Priority 4, define a named baseline configuration (e.g., Claude Sonnet, current temperatures). Before any prompt change or model upgrade, run the same fixture set against the proposed configuration and compare rubric scores, latency, and token count.

**Why:** The project has three providers and configurable temperatures. Without a comparison harness, every change is a bet. This gives the team evidence-based decisions on AI configuration.

**When to ship:** After Priorities 3 and 4 are in place — this depends on both fixtures and rubric scoring existing.

---

## Summary

The chat2bpmn test suite is substantial and well-organized for a project at this stage. The domain-structured unit tests (93 files, ~785 cases) cover the non-AI code paths thoroughly. The foundation is solid.

The critical gap is that the project has no testing posture for its AI-generated outputs. The three absent categories — Replay Harnesses, Rubric-Based Evaluation, and Experiments — are exactly the three that matter most for an AI-powered system. The project can currently answer "did the synthesis pipeline execute?" but not "did it produce a correct result?" and not "is this better or worse than last week?"

Given the project's risk profile (AI-generated BPMN diagrams as the primary output, multiple LLM providers, evolving prompts), the highest-leverage investment is Priorities 3 and 4 together: record realistic fixtures and score synthesis outputs on defined quality dimensions.

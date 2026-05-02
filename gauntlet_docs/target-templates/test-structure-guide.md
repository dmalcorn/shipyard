# Test Structure Guide (Target Template)

This document describes how the test suite of a Shipyard-built project should be organized and what each test should look like. It is partially derived from the eval-framework brownfield analysis ([docs/eval-framework-brownfield-analysis.md](../../docs/eval-framework-brownfield-analysis.md), [docs/eval-framework-brownfield-analysis-results.md](../../docs/eval-framework-brownfield-analysis-results.md)) — those docs analyzed an existing test suite; this one tells you how to *build* one from scratch in a way that respects the same five eval categories.

This is a copy-into-target template. Place it at `_bmad-output/planning-artifacts/test-structure-guide.md` before kickoff. Both the bmad-architect (when generating CI) and the bmad-dev (when writing test files for each story) should read it.

## Why this matters

Three patterns from chat2diagram's run that this guide aims to prevent:

1. **Mock drift**: Stories 13-2 and 13-6 added required columns to shared types. Eight unrelated test files broke because their hand-built mocks didn't have the new columns. This is solved by **central mock factories** rather than ad-hoc per-test mocks.
2. **Test discoverability for story-scoping**: The factory's CI script tries to filter tests by story name (`-t "story_2_1|Story_2_1|2-1"`). If tests aren't named consistently, the filter silently matches zero and the script falls back to the full suite — which is OK for correctness but wastes 90+ seconds per cycle.
3. **No clear test gating**: Without a designated golden set, every test is treated as equally important. When a flaky integration test fails, fix_ci waste a cycle on it. With a clear gate hierarchy, the factory can be told "fail fast on golden set, defer flaky integration to epic review."

## The five eval categories, applied to a fresh project

(Adapted from [docs/eval-framework-brownfield-analysis.md](../../docs/eval-framework-brownfield-analysis.md) — see that doc for the full conceptual treatment.)

### 1. Golden Set

**What it is here:** 10–20 small, fast tests that gate every commit. They cover the system's primary value proposition. Failure is non-negotiable; if they're red, no story passes CI.

**How to identify them in a project:** Tests covering the user journey described in the PRD's headline use case. For chat2diagram-style systems: tests that exercise the main flow end-to-end (login → create project → run primary feature → see output).

**Convention for marking them:**
```typescript
// tests/golden/auth-login.test.ts
import { describe, it } from "vitest";
describe("[GOLDEN] Authentication: login happy path", () => {
  it("logs in a valid user and sets session cookie", async () => {
    // Implementation
  });
});
```

**CI behavior**: Runs on every story. Failure blocks the story commit. The factory's full-suite-fallback path (when zero story-tagged tests match) hits the golden set first; if it passes, proceed to other tests.

**Aim**: ≤5 minutes total, 10–20 tests, 100% must pass.

### 2. Labeled Scenarios

**What they are here:** The bulk of your test suite — 50-200+ tests organized by feature, user role, or scenario type. Each is tagged with the story it belongs to (and optionally a difficulty / category tag).

**Convention**: tests live next to the code they test, named per the story:

```typescript
// src/lib/auth/login.test.ts
describe("Login (story_3_2)", () => {
  it("rejects invalid passwords", async () => { ... });
  it("rate-limits after 5 failed attempts", async () => { ... });
  it("[edge case] handles empty email field", async () => { ... });
});
```

The factory's filter `-t "story_3_2|Story_3_2|3-2"` matches the `(story_3_2)` suffix. Always include exactly one of those forms in every test name.

**CI behavior**: Story-scoped runs match these by story tag. Epic reviews run all of them. Some can be marked `it.skip()` or `it.todo()` if they're not yet ready — the suite tracks coverage breadth, not just pass count.

### 3. Replay Harnesses (when applicable)

**What they are here:** Tests that capture real LLM/API/DB interactions as fixtures and replay them deterministically. Used for any system that talks to non-deterministic external services.

**For chat2diagram-style systems** (LLM-heavy):
- Record real LLM calls during dev as JSON fixtures under `tests/fixtures/llm-replays/`
- Tests load the fixtures and replay against a mocked LLM client
- The mocked client returns the recorded responses verbatim
- Re-record only when the prompt or model changes

**For backend-heavy systems** (DB-heavy):
- Record real database fixtures from the dev DB once, store under `tests/fixtures/db/`
- Tests load fixtures into a fresh test DB before each run
- Avoids the test-db-drift problem where in-memory mocks slowly diverge from prod schema

**Convention**:
```typescript
// tests/replays/synthesis-stage-1-2024-04-15.test.ts
describe("[REPLAY] Synthesis stage 1: extraction (story_4_1)", () => {
  it("extracts diagram from recorded interview transcript", async () => {
    const fixture = await loadFixture("synthesis-stage-1/transcript-1.json");
    // ...
  });
});
```

### 4. Rubric-Based Evaluation (for AI output)

**What it is here:** When the system produces AI-generated content (synthesized text, generated diagrams, model responses), tests should evaluate output against a rubric — a multi-dimensional check that captures correctness, faithfulness, and absence of hallucination.

**Convention**: a small library under `src/lib/evals/rubrics/` defines reusable rubric functions:

```typescript
// src/lib/evals/rubrics/synthesis-output.ts
export function scoreSynthesisOutput(actual: string, expected: SynthesisRubric): RubricScore {
  return {
    contains: expected.must_contain.every(s => actual.includes(s)),
    excludes: !expected.must_not_contain.some(s => actual.includes(s)),
    cites_sources: actual.match(/\[interview_\d+\]/g)?.length ?? 0 >= expected.min_citations,
    no_hallucinations: !actual.match(/\[hallucination_marker\]/),
  };
}
```

Tests in `tests/rubrics/` apply these to recorded outputs:

```typescript
describe("[RUBRIC] Synthesis output quality (story_4_5)", () => {
  it("scores >= 0.85 on the rubric for sample input A", async () => {
    const score = scoreSynthesisOutput(actualOutput, rubricA);
    expect(rubricScore(score)).toBeGreaterThan(0.85);
  });
});
```

If your project doesn't generate AI output, this category is N/A. Skip it and document why in `epics.md`.

### 5. Experiments / Configuration Comparison

**What it is here:** Infrastructure for swapping a config (model, prompt, retrieval threshold) and measuring the difference. Most projects don't need this from day one — defer until you have a stable golden set + rubrics.

**When you DO need it**: Stand up an `experiments/` directory with configs like `experiments/prompt-v1.yaml`, `experiments/prompt-v2.yaml`, and a runner that scores each against the golden set + rubrics. Compare metrics, not anecdotes.

## Test pyramid for factory builds

The factory's CI loop benefits from a clear pyramid:

```
       /\
      /  \    e2e tests        — slow, end-to-end, gate epic-review
     /----\
    /      \  integration     — moderate, cross-component, gate epic
   /--------\
  /          \ unit + golden  — fast, isolated, gate every story
 /____________\
```

| Tier | Speed | Where | When | Failure means |
|---|---|---|---|---|
| Unit + Golden | <100ms each | next to code as `*.test.ts` / `tests/golden/` | every story | Block commit |
| Integration | <5s each | `tests/integration/` | every story (filtered to current story) | Block commit |
| E2E (Playwright/Cypress) | <30s each | `e2e/` | epic review only | Block epic tag |

The CI script's `--story X-Y` mode runs the first two tiers (filtered). The full-project / epic-review mode runs all three. A doc-only short-circuit skips all of them.

## Story tagging — the only convention the factory hard-depends on

Every test MUST include exactly one of these patterns in its describe name or filename:
- `story_X_Y` (preferred — lowercase + underscores)
- `Story_X_Y`
- `X-Y` (story-id form)

The factory uses `vitest -t "story_X_Y|Story_X_Y|X-Y"` (or pytest equivalent) to filter. Inconsistent tagging means stories that should have failing tests pass vacuously because no tests matched and the full-suite fallback never tripped.

**Recommended convention**: tag at the `describe()` level, not per-test:

```typescript
describe("Login API (story_3_2)", () => {
  // all tests inside automatically inherit the tag
  it("...", () => {});
});
```

For files that contain multi-story tests:
```typescript
describe("Auth shared utilities", () => {
  describe("getCurrentUser (story_3_1)", () => { ... });
  describe("requireAuth middleware (story_3_2)", () => { ... });
});
```

## Mock and fixture organization

The single most important pattern for avoiding the chat2diagram 13-2/13-6 cascade: **central mock factories**, not per-test mocks.

### DON'T (per-test ad-hoc mocks)

```typescript
// ❌ 50 test files each with their own InterviewSession mock
// When a column gets added to the schema, all 50 break.

it("does something", () => {
  const mockSession = {
    id: "abc", tokenId: "tok", projectId: "proj",
    status: "captured", llmProvider: "anthropic", /* etc. */
  };
  // ...
});
```

### DO (central mock factory)

```typescript
// ✅ tests/factories/interview-session.ts — ONE place to update
import { type InterviewSession } from "@/lib/db/schema";

export function makeInterviewSession(overrides?: Partial<InterviewSession>): InterviewSession {
  return {
    id: "abc",
    tokenId: "tok",
    projectId: "proj",
    status: "captured",
    llmProvider: "anthropic",
    // ... all fields from schema, with sensible defaults
    excludedFromSynthesis: false,
    identityVerified: false,
    ...overrides,
  };
}
```

```typescript
// ✅ Then 50 test files do this:
import { makeInterviewSession } from "tests/factories/interview-session";

it("does something", () => {
  const mockSession = makeInterviewSession({ status: "completed" });
});
```

Adding a column = updating the factory function once. Every test file picks it up automatically. **This is what would have saved chat2diagram's 13-2 cascade.**

Convention:
- One factory per shared type (`tests/factories/<type-name>.ts`)
- Factory exports a `make<TypeName>(overrides?)` function with sensible defaults
- Defaults are explicit (no random UUIDs unless intentional)
- Tests override only the fields they care about
- Schema changes update the factory

For Django:
```python
# tests/factories/user.py
def make_user(**overrides):
    defaults = {"email": "test@example.com", "is_active": True, ...}
    return User.objects.create(**{**defaults, **overrides})
```

## Test file organization

Single-stack project (Next.js):
```
src/
├── lib/
│   ├── auth/
│   │   ├── login.ts
│   │   ├── login.test.ts        # co-located unit tests
│   │   └── ...
tests/
├── factories/                    # central mock factories
├── golden/                       # golden set
├── integration/                  # integration tests
├── replays/                      # replay-harness fixtures + tests
├── rubrics/                      # rubric-based eval tests
└── helpers/                      # test utilities (NOT factories)
e2e/                              # Playwright tests
```

Multi-stack project (Django + Next.js):
```
backend/
├── apps/
│   └── auth/
│       ├── models.py
│       ├── views.py
│       └── tests/                # backend tests live near their code
│           ├── test_models.py
│           └── test_views.py
├── tests/
│   ├── factories.py              # backend mock factories
│   ├── golden/                   # backend golden set
│   └── ...
frontend/
├── src/
│   └── (per-file *.test.ts)
└── tests/
    ├── factories/                # frontend mock factories
    ├── golden/                   # frontend golden set
    └── ...
e2e/                              # cross-stack e2e tests
```

The CI script knows where to look in each: `cd backend && pytest`, then `cd frontend && npx vitest run`.

## Anti-patterns (with chat2diagram receipts)

| Anti-pattern | Why it hurts | Fix |
|---|---|---|
| Per-test ad-hoc mocks of shared types | Schema change cascades into N broken tests | Central mock factory under `tests/factories/` |
| Tests not tagged with story ID | Story-filter matches zero, fallback to full suite, +90s per cycle | Always include `(story_X_Y)` in describe name |
| Tests that depend on each other | Order-dependence, flakiness | Each test sets up and tears down its own state |
| Tests that mock over the actual integration | "Pass" but real integration broken | Have at least 1-2 e2e tests per story validating the real path |
| Tests that hang on failure (no timeout) | Factory's `_run_bash` hits 300s timeout, looks like a hang | All test runners must enforce per-test timeout |
| Tests that swallow assertion errors | Vacuous "pass" | Use `expect.assertions(N)` to enforce assertion count |
| Tests with no clear category | Treated equally → flaky test fails epic review | Tag every test as `[GOLDEN]`, `[INTEGRATION]`, `[E2E]`, or implicit unit |
| Snapshot tests as the ONLY assertion | Drift over time, snapshots get blindly updated | Combine with explicit `expect(...).toBe(...)` for critical fields |

## How the bmad-dev agent should use this guide

When implementing a story, the dev agent MUST:

1. Tag every new test with the story ID at the `describe()` level
2. Use mock factories from `tests/factories/` rather than building mocks inline
3. If the story changes a shared type, update the matching mock factory in the same commit
4. If the story is in the "Cross-cutting Considerations" of another story, add a test that exercises the cross-cut
5. Add at least one happy-path test (every story); add error-path tests for ACs that mention errors
6. Mark tests appropriately (unit | golden | integration | replay | rubric | e2e)

The factory's `git_commit` phase doesn't currently enforce these patterns — it relies on the agent following them. Future v2 work can add a pre-commit lint that flags untagged tests or hand-built mocks of factory-managed types.

## How the operator validates test layout before kickoff

(For brownfield projects only — greenfield projects start empty.)

1. Run [docs/eval-framework-brownfield-analysis.md](../../docs/eval-framework-brownfield-analysis.md) on the existing test suite. Identify gaps.
2. If there's no central mock factory, add one before the first story runs. Refactor existing inline mocks lazily as related stories touch them.
3. Confirm at least one test exists per epic in the golden set tag.
4. Confirm story-tag filtering works: `npx vitest run -t "story_1_1"` should produce a non-empty result for at least one existing test.

For greenfield: the bmad-architect agent should generate the directory structure (factories/, golden/, integration/, etc.) as part of the project scaffold in story 1.1 of epic 1.

## Updating this guide

Add lessons here when:
- A factory build surfaces a test-pattern bug that wasted multiple fix_ci cycles
- A new stack is supported by the factory and needs different conventions (e.g. when the Django adapter is written, add Django-specific subsection)
- The eval framework gains new categories or refines existing ones

Keep the doc focused on **conventions for test code**, not eval theory. Theory lives in [docs/eval-framework-brownfield-analysis.md](../../docs/eval-framework-brownfield-analysis.md).

## See also

- [docs/eval-framework-brownfield-analysis.md](../../docs/eval-framework-brownfield-analysis.md) — methodology this guide derives from
- [docs/eval-framework-brownfield-analysis-results.md](../../docs/eval-framework-brownfield-analysis-results.md) — chat2diagram's actual posture (a worked example)
- [ci-script-specification.md](ci-script-specification.md) — how CI invokes the test suite
- [story-and-epic-writing-guide.md](story-and-epic-writing-guide.md) — story patterns that produce well-tested code
- [factory-lessons-from-chat2diagram.md](../factory-lessons-from-chat2diagram.md) — recovery patterns these conventions try to prevent

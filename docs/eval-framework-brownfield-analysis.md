# Eval Framework Analysis: Applying the Five Eval Categories to a Brownfield Project

## Purpose

This document analyzes the five evaluation categories defined in the Production Evals Cookbook and translates them into a practical framework for auditing the testing posture of an existing brownfield project. The goal is to use this framework as a lens — read the existing tests in a target project, classify each test by eval category, and produce a coverage map that shows where the testing environment is strong, where it has gaps, and what types of evals are entirely missing.

---

## The Five Eval Categories

### 1. Golden Sets

**What they are**

Golden sets are small, hand-curated collections of input/output pairs that define baseline correctness. Think of them as unit tests for AI behavior: each case specifies a query or input, what tools or code paths should be invoked, what sources or data should be consulted, what the response must contain, and what it must never say. They are meant to be fast (under five minutes), authoritative, and run on every commit.

**Characteristics to look for**

- Small in count (10–20 cases is the target)
- Every case is manually verified as correct
- Failures are treated as blocking — all must pass
- Test both positive assertions (must_contain) and negative guards (must_not_contain, no hallucination markers)
- Cover the "happy path" core use cases the system was built for

**Brownfield application**

In a brownfield project, golden set equivalents are the tests that have existed since early in the project's life, that the team treats as non-negotiable, and that are run in CI on every push. They are usually few in number, tightly scoped, and directly tied to the system's primary value proposition.

**What to look for when auditing**

- Tests that are always expected to pass and are considered regressions if they fail
- Tests explicitly labeled "smoke," "sanity," or "critical"
- Tests covering the exact scenarios described in the original requirements or acceptance criteria
- Tests that assert both that correct output appears AND that incorrect output (error strings, fallback messages, wrong values) does not appear

**Mapping signal**

| Signal in code | Likely category |
|---|---|
| Small suite, always run in CI | Golden set candidate |
| Hard-coded expected values verified by hand | Golden set |
| Dual assertion: contains X AND does not contain Y | Golden set |
| Test name includes "smoke", "sanity", "critical", "happy path" | Golden set |
| Fails on first introduced regression, treated as blocking | Golden set |

---

### 2. Labeled Scenarios

**What they are**

Labeled scenarios extend golden sets by organizing test cases into a coverage matrix. Cases are tagged along multiple dimensions — tool type, query complexity, difficulty level — so the team can see which combinations are well-tested and which are entirely dark. The goal is not to make every test pass but to see the shape of coverage.

**Characteristics to look for**

- Larger in count (30–100+ cases)
- Each case tagged with categorical metadata (type, complexity, difficulty)
- Some failures are acceptable — the point is coverage visibility
- Run on releases or before major changes, not necessarily every commit
- Results produce a coverage grid, not just a pass/fail count

**Brownfield application**

In a brownfield project, labeled scenario equivalents are test suites that have grown to cover multiple feature areas, user roles, or system behaviors. They are typically found in integration test suites, acceptance test suites, or feature-level test directories organized by domain. The labeling may be implicit (via directory structure or file name) rather than explicit metadata tags.

**What to look for when auditing**

- Tests grouped into directories or files by feature, domain, or user persona
- Tests with names that imply a category: "admin workflow," "guest user," "edge case," "error handling"
- Test matrices or parametrized tests that vary a dimension systematically
- Suites where some failures are tracked but not necessarily blocking
- Coverage reports attached to CI that show which branches or paths are hit

**Mapping signal**

| Signal in code | Likely category |
|---|---|
| Tests organized into subdirectories by domain or feature | Labeled scenario |
| Parametrized tests varying input type or complexity | Labeled scenario |
| Test names describe user role, scenario type, or difficulty | Labeled scenario |
| Coverage matrix referenced in CI config or README | Labeled scenario |
| Some tests marked xfail, skip, or known-failure | Labeled scenario |

---

### 3. Replay Harnesses

**What they are**

Replay harnesses record a live session (with all tool calls, intermediate responses, and final output), annotate it with ground truth, then replay it later with cached responses — no live API calls. This makes tests deterministic and cheap. The key insight is that you decouple capturing the interaction from evaluating it, enabling rich ML-style metrics: precision, recall, F1, MRR, groundedness, faithfulness.

**Characteristics to look for**

- Recorded session fixtures stored as files (JSON, YAML, or similar)
- Replay executes against mocked or cached external dependencies
- Evaluation computes numeric metrics, not just pass/fail
- Metrics include retrieval quality (precision, recall) and generation quality (groundedness, faithfulness)
- Sessions can be replayed identically across different code versions to compare metrics over time

**Brownfield application**

In a brownfield project, replay harness equivalents are tests that mock or stub external dependencies using recorded fixtures rather than live calls. They are common in projects that interact with third-party APIs, databases, or message queues. The key differentiator from ordinary mocked tests is that the fixtures were recorded from real interactions, and the tests compute comparative metrics rather than boolean assertions.

**What to look for when auditing**

- VCR cassettes, recorded HTTP responses, or fixture files that capture real API responses
- Tests that use mock libraries (responses, httpretty, nock, WireMock) with fixture-backed responses
- Tests that compute numeric scores, accuracy rates, or performance metrics
- Tests that compare current behavior against a recorded baseline
- Snapshot tests that diff current output against a stored expected output

**Mapping signal**

| Signal in code | Likely category |
|---|---|
| Fixture files capturing real API or DB responses | Replay harness candidate |
| VCR cassettes or recorded HTTP sessions | Replay harness |
| Tests computing precision, recall, or accuracy rates | Replay harness |
| Snapshot or baseline comparison tests | Replay harness |
| Mocks populated from a real recorded interaction | Replay harness |

---

### 4. Rubric-Based Evaluation

**What they are**

Rubric-based evaluation uses structured, multi-dimensional scoring to answer not just "did it pass?" but "how well did it perform?" Each dimension (relevance, accuracy, completeness, clarity) is scored on a 0–5 scale with defined anchor points for each score. Dimensions are weighted by importance for the specific domain. An LLM-as-Judge or a human rater applies the rubric. The output is a quality level (Excellent, Good, Acceptable, Poor, Critical) that supports trend detection over time.

**Characteristics to look for**

- Multiple scoring dimensions evaluated independently
- Each dimension has defined criteria or anchor points
- Scores are weighted and aggregated into an overall quality level
- Results tracked over time to detect quality drift
- Evaluation is qualitative or LLM-assisted, not purely rule-based

**Brownfield application**

In a brownfield project, rubric-based evaluation equivalents are any tests or review processes where output is graded on quality rather than binary correctness. This includes code review checklists with scored criteria, performance benchmarks with acceptable ranges, user acceptance testing with structured feedback forms, or automated quality gates that score output against multiple criteria before approval.

**What to look for when auditing**

- Code quality metrics tracked per PR (cyclomatic complexity, coverage %, lint score)
- Performance benchmarks with acceptable thresholds per scenario category
- Tests that score output on a scale rather than asserting exact values
- Structured review checklists attached to release or deploy processes
- A/B test result evaluators that compare quality dimensions across variants

**Mapping signal**

| Signal in code | Likely category |
|---|---|
| Tests asserting a numeric score above a threshold | Rubric candidate |
| Multiple quality dimensions checked independently | Rubric |
| Quality gates with weighted criteria | Rubric |
| Tests using LLM-as-Judge or human rater | Rubric |
| Trend-tracking in CI with quality level thresholds | Rubric |

---

### 5. Experiments and Configuration Comparison

**What they are**

Experiments compare different configurations of the system — model versions, prompt variants, temperature settings, feature flags, enabled tool sets — against the same evaluation suite. The goal is data-driven decision-making: which configuration produces the best quality at acceptable cost and latency? Each variant is run against the same test set, and results are compared across pass rate, rubric scores, latency, token usage, and cost.

**Characteristics to look for**

- Multiple configurations or variants defined and named
- Same test suite run against all variants
- Results include cost, latency, and quality dimensions side by side
- Variant definitions are version-controlled
- Experiment results drive decisions about what to ship

**Brownfield application**

In a brownfield project, experiment equivalents are A/B tests, feature flag comparisons, canary deployments with metric collection, or benchmark suites run against multiple library/model/config versions before a major upgrade. The defining characteristic is that the same workload is run against multiple configurations and the results are systematically compared.

**What to look for when auditing**

- Feature flag infrastructure with per-flag test coverage
- A/B test framework with evaluation metrics attached
- Benchmark suites comparing library versions or configuration changes
- Load tests run against multiple deployment configurations
- CI pipelines that run the same tests against multiple environment configs (e.g., different DB versions, different model endpoints)

**Mapping signal**

| Signal in code | Likely category |
|---|---|
| Tests parametrized over configuration variants | Experiment candidate |
| Benchmark suites comparing versions or configs | Experiment |
| A/B test evaluation code | Experiment |
| Feature flag tests with quality metric tracking | Experiment |
| CI matrix running tests across multiple env/config combos | Experiment |

---

## How to Apply This Framework to a Brownfield Project

### Step 1 — Inventory the existing tests

Collect all test files in the project. Group them by:
- Test runner or framework (pytest, Jest, JUnit, RSpec, etc.)
- Directory location (unit/, integration/, e2e/, acceptance/)
- File name patterns (test_smoke_*, *_critical_test, etc.)
- CI pipeline stage (every commit, nightly, pre-release)

### Step 2 — Classify each test or suite

For each test file or logical suite, apply the mapping signals above to assign one of the five eval categories. A test can exhibit characteristics of more than one category — note the primary classification and any secondary signals.

Use this classification table:

| Eval Category | Primary Signal | Secondary Signals |
|---|---|---|
| Golden Set | Blocking, tiny, hand-verified, dual-assertion | Smoke/sanity label, always in CI |
| Labeled Scenario | Organized by domain/type/difficulty | Parametrized, coverage matrix |
| Replay Harness | Fixture-backed, recorded interactions | Snapshot tests, metric computation |
| Rubric | Multi-dimensional quality scoring | Weighted thresholds, trend tracking |
| Experiment | Variant comparison, same suite multiple configs | A/B test, benchmark, feature flag |

### Step 3 — Build the coverage map

Produce a matrix showing which eval categories exist, how many tests fall into each, and which categories are entirely absent.

```
Eval Category       | Count | CI Stage        | Blocking? | Notes
--------------------|-------|-----------------|-----------|-------
Golden Set          |       |                 |           |
Labeled Scenario    |       |                 |           |
Replay Harness      |       |                 |           |
Rubric              |       |                 |           |
Experiment          |       |                 |           |
```

### Step 4 — Assess the testing posture

Interpret the coverage map:

**If Golden Sets are missing or sparse:** The project has no reliable regression baseline. Any change may silently break core behavior. Priority: identify the 10–15 most critical behaviors and write or designate golden set tests for them immediately.

**If Labeled Scenarios are missing:** The project cannot answer "what types of inputs are we testing?" Coverage may be accidentally biased toward a narrow slice of real-world usage. Priority: categorize existing tests, identify uncovered input types, and add representative cases.

**If Replay Harnesses are absent:** All tests against external dependencies are either live (slow, expensive, flaky) or mocked with hand-crafted responses (potentially wrong). Priority: record real interactions and back mocks with those recordings. Add metric computation to move beyond pass/fail.

**If Rubric-based evaluation is absent:** The project can only say "it passed" — not "how good is it?" This is acceptable for deterministic systems but is a significant gap for any system with AI-generated, user-facing, or probabilistic output. Priority: define quality dimensions relevant to the domain and instrument key tests with dimensional scoring.

**If Experiments are absent:** Configuration changes (model upgrades, prompt changes, library updates) are made without systematic comparison. Decisions rely on intuition. Priority: establish a baseline variant, define the test set used for comparison, and run new configurations against it before shipping.

### Step 5 — Produce the analysis report for the target project

The deliverable for the target project is:

1. **Test inventory** — complete list of test files and suites
2. **Classification** — each suite labeled with its eval category (or "unclassified")
3. **Coverage matrix** — which categories are represented and how many tests
4. **Gap analysis** — which categories are missing or thin
5. **Prioritized recommendations** — what to add first, with rationale tied to the project's risk profile

---

## Quick Reference: Eval Category Cheat Sheet

```
GOLDEN SET
  Size:      10–20 cases
  Frequency: Every commit
  Fails:     All must pass (blocking)
  Checks:    Tools + sources + must_contain + must_not_contain
  Signal:    "smoke", "sanity", "critical", dual-assertion

LABELED SCENARIO
  Size:      30–100+ cases
  Frequency: Per release or major change
  Fails:     Some acceptable (gap visibility)
  Checks:    Category × complexity × difficulty matrix
  Signal:    Subdirs by domain, parametrized, coverage report

REPLAY HARNESS
  Size:      Recorded session fixtures
  Frequency: Weekly or per feature
  Fails:     Metric thresholds
  Checks:    Precision, recall, F1, groundedness, faithfulness
  Signal:    VCR cassettes, fixture JSON, snapshot tests

RUBRIC
  Size:      Any — applied as scoring layer
  Frequency: Continuous, trend-tracked
  Fails:     Quality level below threshold
  Checks:    Relevance, accuracy, completeness, clarity (weighted)
  Signal:    Numeric scores, thresholds, LLM-as-Judge

EXPERIMENT
  Size:      Same suite across N variants
  Frequency: Before major releases or config changes
  Fails:     Relative comparison, not absolute
  Checks:    Pass rate, rubric score, latency, cost per variant
  Signal:    Variant definitions, A/B test, benchmark, CI matrix
```

---

## Notes on Brownfield Realities

**Tests may not cleanly fit one category.** A parametrized integration test backed by VCR cassettes that also computes a coverage report is part Labeled Scenario, part Replay Harness. Classify by dominant characteristic; note secondary signals.

**Naming conventions are unreliable.** A file called `test_smoke.py` may contain 400 tests that are not golden-set quality. A file called `test_integration.py` may contain 5 hand-verified cases that function exactly as golden sets. Read the tests, not just the names.

**Absence of a category is valuable data.** A project with only golden sets and labeled scenarios — and nothing in the replay, rubric, or experiment categories — is likely stable for deterministic behavior but completely unequipped for AI or probabilistic components. The gap analysis tells you what the team knows how to test versus what they are flying blind on.

**The framework is additive, not prescriptive.** The cookbook builds these categories as progressive stages. In a brownfield project, you are not expected to implement all five. The audit tells you where you are; the gap analysis tells you which category to add next based on the project's specific risks.

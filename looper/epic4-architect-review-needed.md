# Epic 4 — Architect Review Needed (Category B Only)

**Scope:** Issues where multiple valid approaches exist, security design decisions are needed, API contracts may change, or fixes could affect other epics/stories. Each item requires an explicit decision before implementation.

**Corresponding fix plan:** `epic4-code-review-fix-plan.md` (Category A items — no overlap)

---

## ARCH-01: Working Directory Isolation Disconnected from Orchestrator

**Analysis ref:** #20 | **Severity:** CRITICAL | **Story:** 4-2

### Current State
- **`src/tools/scoped.py`** — Scoped tools infrastructure is fully built and functional.
- **`src/multi_agent/spawn.py:54,140`** — `create_agent_subgraph()` and `run_sub_agent()` accept `working_dir` parameter.
- **`src/multi_agent/roles.py:124,146`** — `get_tools_for_role()` accepts `working_dir` and calls `get_scoped_tools()`.
- **`src/multi_agent/orchestrator.py:50-88`** — `OrchestratorState` has NO `working_dir` field.
- **`src/multi_agent/orchestrator.py:142-164`** — `_run_bash()` has NO `cwd` parameter.
- **`src/multi_agent/orchestrator.py:179-458`** — All agent nodes call `run_sub_agent()` WITHOUT `working_dir`.
- **`src/intake/rebuild.py:236-258`** — `_run_story_pipeline()` accepts `target_dir` but never passes it to orchestrator.

### Why Architect Review
This is the story's primary requirement and requires coordinated changes across 3 files:
1. Add `working_dir` to `OrchestratorState` TypedDict
2. Thread `working_dir` through every agent node to `run_sub_agent()`
3. Add `cwd` parameter to `_run_bash()` and all bash-calling nodes
4. Pass `target_dir` from `_run_story_pipeline()` into the initial state

Impact: Changes `OrchestratorState` contract (used by Epic 3's orchestrator tests), modifies every node function signature, affects `_run_bash()` which is also used in non-rebuild mode.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | Add `working_dir: str` to `OrchestratorState`, thread through all nodes | Clean but touches many node functions; breaks if non-rebuild callers don't provide it |
| B | Add `working_dir: str = ""` (optional) to `OrchestratorState`, nodes check `if working_dir:` | Backwards-compatible, but adds conditional logic to every node |
| C | Create a separate `RebuildOrchestratorState` extending `OrchestratorState` with `working_dir`, and a `build_rebuild_orchestrator()` graph builder | No impact on existing orchestrator, but code duplication |

**Recommendation:** Option B — optional field with empty-string default preserves existing behavior.

**Decision question:** Should `working_dir` be optional (empty = use default tools) or required (callers must always specify it)?

---

## ARCH-02: Pipeline Conditional Edges on Failure

**Analysis ref:** #1 | **Severity:** CRITICAL | **Story:** 4-1

### Current State
- **`src/intake/pipeline.py:166-170`** — All edges are unconditional: `START → read_specs → intake_specs → create_backlog → output → END`
- When `read_specs_node` returns `pipeline_status: "failed"`, the pipeline proceeds to `intake_specs_node` which sends empty `raw_specs` to LLM, wasting API credits.

### Why Architect Review
Conditional routing is an architectural pattern choice in LangGraph. The approach affects graph topology, testability, and the state contract.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | Add conditional edges: `read_specs → (failed? END : intake_specs)` | LangGraph-idiomatic, but adds routing functions |
| B | Check `pipeline_status` at entry of each node, return early if failed | Simpler, no graph changes, but silently skips nodes |
| C | Add an `error_handler` node that all failure paths route to | Consistent error handling, but over-engineered for a 4-node pipeline |

**Recommendation:** Option A — conditional edges. This is the LangGraph-idiomatic approach and matches the coding standards ("Conditional edges: Route based on state fields").

**Decision question:** Should only `read_specs → intake_specs` have a conditional edge (the only node that can fail before LLM calls), or should every edge be conditional?

---

## ARCH-03: API Rebuild Intervention Architecture

**Analysis ref:** #25, #26 | **Severity:** HIGH | **Story:** 4-2, 4-3

### Current State
- **`src/main.py:194-224`** — `/rebuild` endpoint runs synchronously with no `on_intervention` callback and no `intervention_logger`.
- **`src/main.py:231-270`** — `/rebuild/intervene` endpoint operates in isolation with hardcoded empty strings for `epic`, `story`, `failure_report`.
- **`src/intake/intervention_log.py:363-389`** — `build_intervention_needed_response()` exists but is never called.
- There is no mechanism for `/rebuild` to pause and return `intervention_needed`, nor for `/rebuild/intervene` to resume the running rebuild.

### Why Architect Review
This requires designing an async communication protocol between the rebuild loop and the API client. Multiple valid architectures exist, and the choice affects the API contract (which is a public interface).

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Async with polling:** `/rebuild` runs in background thread, returns immediately with `session_id`. Client polls `/rebuild/status` for progress. On failure, status returns `intervention_needed`. Client submits via `/rebuild/intervene`, rebuild resumes. | Standard REST pattern, stateless client, but requires background threading and session state management |
| B | **WebSocket:** `/rebuild/ws` establishes a WebSocket. Server pushes status updates and intervention requests. Client sends intervention responses on same connection. | Real-time, but adds WebSocket dependency and complexity |
| C | **Synchronous with callbacks:** Keep `/rebuild` synchronous but have it return `intervention_needed` on first failure. Client re-calls `/rebuild/resume` after intervening. Rebuild state persisted to disk. | Simplest server-side, but slow (HTTP roundtrips per failure) |
| D | **Defer to Epic 5:** Mark API intervention as a known gap, document it, ship CLI-only intervention for now. | Pragmatic, but deviates from the story spec |

**Recommendation:** Option A — it's the standard pattern for long-running API operations and aligns with the existing `session_id` model.

**Decision question:** Should API intervention be fully implemented now (significant scope), or deferred to a follow-up with the gap documented?

---

## ARCH-04: Path Traversal Sandboxing for Intake API

**Analysis ref:** #2 | **Severity:** HIGH | **Story:** 4-1

### Current State
- **`src/main.py:65-69`** — `IntakeRequest` accepts arbitrary `spec_dir: str` and `target_dir: str`.
- No path validation or sandboxing. `spec_dir` can read any directory, `target_dir` can write anywhere.

### Why Architect Review
The scope of sandboxing is a security architecture decision. It depends on deployment model (local dev tool vs. hosted service) and affects the API contract.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Allowlist directory:** Configure a `SHIPYARD_WORKSPACE` env var. Both `spec_dir` and `target_dir` must be under this directory. | Simple, secure, but requires configuration |
| B | **Resolve and validate:** Resolve both paths and reject if they contain `..` or are absolute paths outside CWD. | No config needed, but CWD-dependent |
| C | **No sandboxing (document risk):** Accept any path, document that Shipyard should run in a sandboxed environment (Docker, etc.). | Zero code change, but shifts responsibility to operator |

**Recommendation:** Option B for now (minimal code), with Option A as a follow-up.

**Decision question:** Is Shipyard intended to be a local-only tool (sandboxing less critical) or a hosted service (sandboxing mandatory)?

---

## ARCH-05: `run_command` Scoped Tool Uses `shell=True`

**Analysis ref:** #27 | **Severity:** MEDIUM | **Story:** 4-2

### Current State
- **`src/tools/scoped.py:178-180`** — `subprocess.run(command, shell=True, cwd=str(root), ...)`. While `cwd` restricts the starting directory, `shell=True` allows shell metacharacter injection (e.g., `cd / && rm -rf *`).
- **`src/tools/bash.py`** — Existing `run_command` tool also uses `shell=True` (consistency).

### Why Architect Review
Removing `shell=True` breaks shell features (pipes, redirection, `&&`) that agents legitimately use. The security model for LLM-driven tool execution is an architectural decision.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Keep `shell=True`, add command allowlist:** Parse the command and reject dangerous patterns (`rm -rf`, `cd /`, etc.). | Preserves shell features, but allowlists are brittle and bypassable |
| B | **Remove `shell=True`, use `shlex.split()`:** Commands become list-based. No shell injection possible. | Secure, but breaks pipes/redirections that agents need |
| C | **Keep `shell=True`, restrict via seccomp/namespace:** Deploy in a container with filesystem restrictions. | Best security, but requires container infrastructure |
| D | **Keep `shell=True` (accept risk, document):** The agent is running locally on the developer's machine — same trust model as the developer. | Pragmatic for current use case, unacceptable for hosted service |

**Recommendation:** Option D for local tool, Option C if hosted deployment is planned.

**Decision question:** What is Shipyard's trust model for LLM-generated shell commands during rebuild?

---

## ARCH-06: Scaffold Language Detection from Spec

**Analysis ref:** #35 | **Severity:** MEDIUM | **Story:** 4-2

### Current State
- **`src/intake/rebuild.py:268-298`** — `_init_target_project` creates only a generic `README.md`.
- Story spec says: "Create basic project scaffold based on the spec summary (language detection from intake)."
- The spec summary is available in `{target_dir}/spec-summary.md` but is never consulted.

### Why Architect Review
Language detection and scaffold generation is a feature design decision. It affects what the first story's tests have to work with.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Keyword search in spec summary:** Scan for "Python", "TypeScript", "Go", etc. Create language-appropriate scaffold (`setup.py`, `package.json`, `go.mod`). | Simple, covers common cases, but brittle for ambiguous specs |
| B | **LLM-based detection:** Ask the LLM to identify the language from the spec summary and return a scaffold plan. | More accurate, but adds an LLM call (cost/latency) |
| C | **Skip for now (document gap):** The first story's dev agent will create the scaffold as part of its implementation. The generic README is sufficient to start. | Pragmatic, but the test agent may fail if there's no test runner configured |

**Recommendation:** Option A — simple keyword detection for the top 5 languages.

**Decision question:** Is a minimal scaffold (README + language marker files) sufficient, or does the first story need a fully configured project (build system, test runner, etc.)?

---

## ARCH-07: Evidence Validation — "Not Specified" Bypass

**Analysis ref:** #42 | **Severity:** HIGH | **Story:** 4-3

### Current State
- **`src/intake/intervention_log.py:348-350`** — CLI: empty input → `"Not specified"` fallback.
- **`src/intake/intervention_log.py:430-432`** — API: same fallback.
- **`src/intake/intervention_log.py:45-49`** — `__post_init__` validates non-empty, but `"Not specified"` passes.
- Story spec AC #2: "provides specific, evidence-based data (not vague summaries)."

### Why Architect Review
This is a UX design decision. Forcing evidence-based input could frustrate developers during long rebuilds. But allowing empty input undermines the comparative analysis in Story 5.1.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Remove fallback, let validation reject empty:** CLI re-prompts until non-empty input is provided. API returns 422 on empty fields. | Enforces data quality, but may be frustrating during long rebuilds |
| B | **Keep fallback but flag it:** Allow "Not specified" but add `is_incomplete: bool` flag to the entry. Filter these out of comparative analysis. | Permissive UX, but adds complexity to analysis |
| C | **Keep current behavior (accept gap):** "Not specified" is good enough for v1. The data quality concern matters more in Story 5.1 when analysis actually runs. | Simplest, but accumulates tech debt |

**Recommendation:** Option A for CLI (re-prompt), Option C for API (defer to v1 feedback).

**Decision question:** Should intervention logging enforce evidence-based input, or should it prioritize developer convenience?

---

## ARCH-08: Intake Pipeline Graph Topology vs. Spec

**Analysis ref:** #11 | **Severity:** MEDIUM | **Story:** 4-1

### Current State
- Story spec Task 3 says: "Wire edges: `START → intake_specs_node → create_backlog_node → output_node → END`" (3 nodes).
- Implementation has 4 nodes: `START → read_specs → intake_specs → create_backlog → output → END`.
- The extra `read_specs` node separates file reading from LLM processing, which is reasonable.

### Why Architect Review
The spec deviation is intentional and arguably better, but undocumented. If the spec is the source of truth, the implementation should match or the spec should be updated.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Keep 4-node topology, update spec:** The separation is cleaner — file I/O in `read_specs`, LLM in `intake_specs`. Document the deviation. | Better architecture, but spec drift |
| B | **Merge back to 3 nodes:** Move file reading into `intake_specs_node`. | Matches spec, but makes the node do two things |

**Recommendation:** Option A — keep the cleaner architecture, update the story spec.

**Decision question:** Should the story spec be updated to reflect the actual implementation, or should the code be changed to match the spec?

---

## ARCH-09: Intervention Retry Count

**Analysis ref:** #28 | **Severity:** MEDIUM | **Story:** 4-2

### Current State
- **`src/intake/rebuild.py:104-121`** — On story failure, one intervention is offered. If the retry also fails, the story is marked failed.
- Story spec says "Re-invoke the pipeline for the same story with the fix applied" and tracks `intervention_count` per story (implying multiple).
- `intervention_count` is tracked but the loop only runs once.

### Why Architect Review
The number of retries affects cost (each retry is a full orchestrator invocation with LLM calls) and user experience.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Allow configurable max retries:** `MAX_INTERVENTION_RETRIES = 3` (or config param). Loop until success or max reached. | Flexible, but potentially expensive |
| B | **Keep single retry:** One chance per story. If it fails again, move on. | Simple, predictable cost, but may leave fixable stories behind |
| C | **Unlimited retries until user aborts:** Keep retrying as long as the user provides "fix" instructions. | Most permissive, but could loop forever on unfixable issues |

**Recommendation:** Option A with `MAX_INTERVENTION_RETRIES = 3`.

**Decision question:** What's the maximum number of intervention retries per story before auto-skipping?

---

## ARCH-10: Total Output Size Limit for Spec Reader

**Analysis ref:** #3 | **Severity:** MEDIUM | **Story:** 4-1

### Current State
- **`src/intake/spec_reader.py:44-62`** — Individual files capped at 5000 chars, but no aggregate limit. 1000 small files → 5MB+ injected into LLM prompt.

### Why Architect Review
The aggregate limit depends on the target LLM's context window and the prompt structure. Setting it too low loses information; too high causes API errors.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Hard cap at 100K chars total:** Truncate after reaching limit, log warning. | Simple, works for most models |
| B | **Configurable via env/param:** `MAX_TOTAL_SPEC_CHARS` env var, default 100K. | Flexible for different models |
| C | **File count limit + char limit:** Max 50 files AND 100K chars. | Prevents edge case of many small files |

**Recommendation:** Option C — dual limit.

**Decision question:** What total spec size limit is appropriate given the target model's context window?

---

## ARCH-11: `IntakeState` TypedDict `total=False` Design

**Analysis ref:** #18 | **Severity:** LOW | **Story:** 4-1

### Current State
- **`src/intake/pipeline.py:23`** — `class IntakeState(TypedDict, total=False)` makes ALL fields optional.
- mypy won't catch missing required fields like `spec_dir` in the initial state.

### Why Architect Review
LangGraph state often uses `total=False` because nodes return partial updates. Changing to `total=True` would require every node to return ALL fields (or use `NotRequired` for optional ones). This is a state management pattern decision.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | Keep `total=False` (current) | Convenient for partial node returns, but weak type safety |
| B | Use `total=True` with `NotRequired` on optional fields | Stronger type safety, but more verbose |

**Recommendation:** Option A — LangGraph idiom. Add runtime validation in `run_intake_pipeline` for required fields instead.

**Decision question:** Accept weaker type safety for LangGraph idiom compatibility, or enforce strict TypedDict?

---

## ARCH-12: Concurrent Pipeline Handling

**Analysis ref:** #8 | **Severity:** MEDIUM | **Story:** 4-1

### Current State
- **`src/intake/pipeline.py:130-139`** — Two simultaneous `/intake` requests with the same `target_dir` can corrupt each other's output files.

### Why Architect Review
Concurrency model depends on deployment: single-user CLI (no issue) vs. multi-user API server (needs protection).

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **File lock per target_dir** | Prevents corruption, adds lock management |
| B | **Unique output subdirs per session** | No locks needed, but changes output path convention |
| C | **Document as single-user tool** | No code change, but limits deployment options |

**Recommendation:** Option C for v1, Option B for future multi-user support.

**Decision question:** Is concurrent API access a v1 requirement?

---

## ARCH-13: Missing Audit Logging for Intake Pipeline

**Analysis ref:** #15 | **Severity:** MEDIUM | **Story:** 4-1

### Current State
- **`src/main.py:377-396`** (CLI) and **`src/main.py:167-191`** (API) — Intake paths create no `AuditLogger`.
- Project-context.md says "Every agent session produces a markdown log."
- The `/instruct` and CLI paths DO use `AuditLogger`.

### Why Architect Review
Intake is a pipeline (not an agent session), so the "agent session" audit rule may not apply directly. What to log and at what granularity is a design choice.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Add AuditLogger to intake paths** | Consistent with convention, but intake has different structure than agent sessions |
| B | **Intake logs to its own format** | Tailored to pipeline stages, but new logging format to maintain |
| C | **Skip (pipeline output IS the audit trail)** | The output files (`spec-summary.md`, `epics.md`) serve as the record |

**Recommendation:** Option A — wrap intake in AuditLogger for consistency.

**Decision question:** Should intake pipeline sessions produce audit logs in the same format as agent sessions?

---

## ARCH-14: CLI Command Word Collision in Intervention Prompt

**Analysis ref:** #51 | **Severity:** MEDIUM | **Story:** 4-3

### Current State
- **`src/intake/intervention_log.py:321-324`** — If the user types "skip" or "abort" as the `what_broke` description, it's interpreted as an action command, not as content.

### Why Architect Review
This is a UX interaction design decision for the CLI prompt flow.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Separate action prompt:** Ask for action first ("fix/skip/abort?"), then ask for details only if "fix". | Clear separation, but changes prompt flow |
| B | **Prefix commands:** Require `/skip` or `/abort` with a slash prefix. Plain text is always content. | Unambiguous, but changes the interface |
| C | **Accept current behavior:** Users who want to describe "skip logic broken" can write "Skip logic was broken" (capital S won't match `.lower() == "skip"`). | Technically works but fragile and confusing |

**Recommendation:** Option A — ask action first.

**Decision question:** Should the CLI prompt flow be restructured to separate action choice from evidence collection?

---

## ARCH-15: `_rewrite_summary` Atomic Writes

**Analysis ref:** #52 | **Severity:** MEDIUM | **Story:** 4-3

### Current State
- **`src/intake/intervention_log.py:256-269`** — Reads full file, rewrites entirely. Not crash-safe during multi-hour rebuilds.

### Why Architect Review
Atomic write patterns (write-to-temp-then-rename) add complexity. Whether it's worth it depends on the expected reliability requirements.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Write to temp file, then atomic rename** | Crash-safe, standard pattern |
| B | **Keep current behavior, add recovery** | Simpler, but file can be corrupted on crash |
| C | **Append-only log (no summary rewrite)** | No rewrite risk, but harder to read |

**Recommendation:** Option A if multi-hour rebuilds are expected; Option B if rebuilds are typically short.

**Decision question:** Are multi-hour unattended rebuilds a realistic scenario for v1?

---

## ARCH-16: `_intervention_loggers` Memory Management

**Analysis ref:** #44 | **Severity:** MEDIUM | **Story:** 4-3

### Current State
- **`src/main.py:228`** — Module-level dict accumulates `InterventionLogger` instances, never cleaned up.

### Why Architect Review
Cleanup strategy depends on session lifecycle design (which ties to ARCH-03 API intervention architecture).

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **TTL-based cleanup:** Remove loggers not accessed in 1 hour. | Automatic, but adds timer complexity |
| B | **Explicit cleanup endpoint:** `DELETE /rebuild/session/{id}` removes the logger. | Clean, but requires client cooperation |
| C | **WeakValueDictionary:** Let GC handle it when no references remain. | Automatic, but loggers may be collected too early |
| D | **Defer (part of ARCH-03):** Fix as part of the API intervention redesign. | No extra work now |

**Recommendation:** Option D — defer to ARCH-03 resolution.

**Decision question:** Defer to ARCH-03, or implement a quick TTL fix independently?

---

## ARCH-17: `search_files` OOM on Large Projects

**Analysis ref:** #40 | **Severity:** LOW | **Story:** 4-2

### Current State
- **`src/tools/scoped.py:146-163`** — Reads ALL files recursively into memory. No file count or size limit.

### Why Architect Review
The right limits depend on expected target project sizes and the tool's performance requirements.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | **Max file size + max files:** Skip files > 1MB, stop after 1000 files. | Simple, covers most cases |
| B | **Streaming search:** Read files line-by-line instead of `read_text()`. | Memory-efficient, but slower |
| C | **Defer (unlikely for v1 targets):** Target projects generated by Shipyard won't be large enough to OOM. | No code change |

**Recommendation:** Option C for v1.

**Decision question:** Are target projects expected to be large enough to cause memory issues?

---

## ARCH-18: `failure_report` in `_EVIDENCE_FIELDS` Validation

**Analysis ref:** #59 | **Severity:** LOW | **Story:** 4-3

### Current State
- **`src/intake/intervention_log.py:14`** — `_EVIDENCE_FIELDS = ("what_broke", "what_developer_did", "agent_limitation")`
- `failure_report` is NOT validated as non-empty.
- It's sometimes legitimately empty (e.g., when the API endpoint passes `""` because it doesn't have the pipeline context yet — see ARCH-03).

### Why Architect Review
Adding `failure_report` to `_EVIDENCE_FIELDS` would break the current API `/rebuild/intervene` endpoint which passes `failure_report=""`.

### Options

| Option | Approach | Trade-off |
|---|---|---|
| A | Add to `_EVIDENCE_FIELDS` | Enforces data quality, breaks current API endpoint |
| B | Keep out of `_EVIDENCE_FIELDS` | Allows empty, but failure_report is key context |
| C | Add after ARCH-03 is resolved | The API endpoint will then provide real failure reports |

**Recommendation:** Option C — defer until ARCH-03 provides the mechanism.

**Decision question:** Defer to ARCH-03, or add validation now and accept the API breakage?

---

## Decision Priority

| Priority | Items | Rationale |
|---|---|---|
| **Must decide before fixes** | ARCH-01, ARCH-02 | Fix plan items depend on these architectural choices |
| **Should decide soon** | ARCH-03, ARCH-04, ARCH-05 | Security and API contract decisions |
| **Can defer to later sprint** | ARCH-06 through ARCH-18 | Lower severity or can ship without |

---

## Items Skipped During Fix Phase

*Added: 2026-03-24 14:48:15*

### 1. SKIPPED #35
- **Source:** Fix phase execution
- **Reason:** Already addressed by FIX-08 (git tag failure logging)
- **Decision Required:** Determine the correct fix approach

### 2. SKIPPED #38
- **Source:** Fix phase execution
- **Reason:** API endpoint test requires TestClient infrastructure beyond scope of clear fixes
- **Decision Required:** Determine the correct fix approach


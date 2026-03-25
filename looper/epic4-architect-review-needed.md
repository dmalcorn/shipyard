# Epic 4 — Architect Review Required

**Category B items only.** These require architectural decisions — multiple valid approaches exist, security implications need expert review, or the fix could affect other epics/stories.
For clear, non-controversial fixes, see `epic4-code-review-fix-plan.md`.

---

## B01: Pipeline Graph Failure Routing Strategy
**Severity:** CRITICAL | **Stories:** 4-1, 4-2 | **Found by:** Both agents

### Current State
- **File:** `src/intake/pipeline.py:180-184`
- The intake pipeline uses unconditional edges: `START → read_specs → intake_specs → create_backlog → output → END`
- When `read_specs_node` fails (returns `pipeline_status: "failed"`), the graph unconditionally continues to LLM nodes
- Two wasted Sonnet API calls occur on empty/failed input
- Combined with A02 (output_node overwrite), failures are completely masked

### Why Architect Review
- The current 4-node topology **deviates from the story spec** (which specified 3 nodes: `START → intake_specs → create_backlog → output → END`)
- Adding conditional edges changes the graph topology, which is a design decision affecting testability and debuggability
- The coding standard says "Conditional edges: Route based on state fields" — this confirms the need, but the routing logic design needs a decision

### Options

| Option | Approach | Pros | Cons |
|---|---|---|---|
| A | Add conditional edges after each node | Follows coding standard; fails fast | More complex graph; each node needs a router function |
| B | Single conditional edge after `read_specs` only | Minimal change; catches the main failure mode | Doesn't catch failures in `intake_specs` or `create_backlog` |
| C | Merge `read_specs` back into `intake_specs` (match original spec) | Matches spec topology; fewer edges | Loses separation of I/O vs LLM logic |
| D | Add a global `should_continue` router function | DRY; single check function reused | Slightly unconventional LangGraph pattern |

**Recommendation:** Option B — add one conditional edge after `read_specs` that routes to END on failure. This fixes the critical bug with minimal topology change.

**Decision needed:** Which routing strategy? Does the 4-node deviation from spec need correction?

---

## B02: API spec_dir Allows Arbitrary Directory Reads
**Severity:** MEDIUM | **Story:** 4-1 | **Found by:** BMAD only

### Current State
- **File:** `src/main.py:218-242` and `src/intake/spec_reader.py:35`
- `POST /intake` accepts any `spec_dir` path with no validation
- `spec_reader.py` resolves to absolute path and recursively reads `.md`, `.txt`, `.py`, `.json`, `.yaml`, `.yml` files
- Combined with LLM summarization, file contents are reflected in output
- project-context.md mandates sandboxing for `run_command` but not for spec reading

### Why Architect Review
- Security boundary definition: should the API be restricted to a specific base directory?
- This is a design-time vs runtime validation decision
- The intake pipeline is user-invoked (not agent-invoked), so threat model differs from rebuild-mode sandbox

### Options

| Option | Approach | Pros | Cons |
|---|---|---|---|
| A | Validate `spec_dir` is under a configured `PROJECTS_BASE` dir | Clear security boundary | Requires new config; breaks existing users who pass arbitrary paths |
| B | Validate `spec_dir` exists and is a directory (no path traversal check) | Simple; catches obvious errors | Doesn't prevent reading sensitive dirs |
| C | No change — accept as designed for a developer CLI tool | Zero work; developers control their own machine | Fails security audits; inconsistent with sandbox principle |

**Recommendation:** Option B for now, Option A as a future enhancement.

**Decision needed:** What security boundary applies to the intake spec reader?

---

## B03: No Aggregate Size Limit on Combined Spec Text
**Severity:** MEDIUM | **Story:** 4-1 | **Found by:** BMAD only

### Current State
- **File:** `src/intake/spec_reader.py:44-63`
- Individual files capped at 5000 chars, but no limit on total combined output
- A spec directory with hundreds of files could produce megabytes of text
- This is then passed verbatim into the LLM prompt, potentially exceeding context limits

### Why Architect Review
- The limit value affects user experience (too low = truncated specs, too high = API errors)
- Truncation strategy matters (first N chars? first N files? error message?)
- May need coordination with the model's context window size

### Options

| Option | Approach | Limit |
|---|---|---|
| A | Hard cap on total chars (e.g., 100K) | Truncate combined output |
| B | Cap on number of files (e.g., 50) | Skip files beyond limit |
| C | Token-aware limit using tiktoken | Most accurate; adds dependency |

**Recommendation:** Option A with a configurable constant (e.g., `MAX_COMBINED_SPEC_CHARS = 100_000`).

**Decision needed:** What limit value? Truncate or error?

---

## B04: Graph Topology Deviates From Task 3 Spec (4 nodes vs 3)
**Severity:** MEDIUM | **Story:** 4-1 | **Found by:** BMAD only

### Current State
- **File:** `src/intake/pipeline.py:175-184`
- Story spec defines 3 nodes: `intake_specs → create_backlog → output`
- Implementation has 4 nodes: `read_specs → intake_specs → create_backlog → output`
- The separation is reasonable (I/O vs LLM logic) but creates the failure propagation gap

### Why Architect Review
- Spec compliance question: was this an intentional design improvement or a deviation?
- Tied to B01 — the routing strategy decision affects whether 4 nodes is acceptable
- If spec is authoritative, the fix is to merge `read_specs` into `intake_specs`

**Decision needed:** Accept 4-node topology as intentional improvement, or revert to spec's 3-node design?

---

## B05: API Intervention Architecture (Disconnected Endpoints)
**Severity:** CRITICAL | **Stories:** 4-2, 4-3 | **Found by:** Both agents

### Current State
- **File:** `src/main.py:245-318`
- `POST /rebuild` calls `run_rebuild()` synchronously without `on_intervention` callback
- `POST /rebuild/intervene` writes to a separate, disconnected `InterventionLogger`
- No mechanism exists to pause a running rebuild, accept an intervention, and resume
- AC#2 for Story 4-2 explicitly requires returning `status: 'intervention_needed'`
- AC#1 for Story 4-3 requires intervention logging in API mode

### Why Architect Review
- This is a **fundamental architectural gap**, not a bug fix
- Multiple valid approaches exist, each with significant implementation effort
- The solution must coordinate with B07 (/rebuild blocking)
- Affects the entire API contract for rebuild operations

### Options

| Option | Approach | Effort | Pros | Cons |
|---|---|---|---|---|
| A | Async rebuild with polling: `/rebuild` starts background task, `/rebuild/status` returns current state, `/rebuild/intervene` injects fixes | HIGH | Clean REST API; non-blocking | Requires async task management, session state |
| B | WebSocket-based: `/rebuild` opens WS, streams progress, accepts interventions inline | HIGH | Real-time; natural for long-running ops | More complex client; new dependency |
| C | Synchronous with early-exit: `/rebuild` stops on first failure, returns `intervention_needed` + context; client re-calls with fix | MEDIUM | Simple; stateless | Multiple round-trips; client must manage state |
| D | Accept as-is: document that API mode doesn't support intervention | LOW | No code change | Violates AC#2; reduces API utility |

**Recommendation:** Option C — it matches the story spec's language most closely and avoids the complexity of async task management.

**Decision needed:** Which API intervention pattern? This is the single highest-impact architectural decision in Epic 4.

---

## B06: Callback Signature Lacks Epic/Story Context
**Severity:** HIGH | **Stories:** 4-2, 4-3 | **Found by:** Both agents

### Current State
- **File:** `src/intake/rebuild.py:35`
  ```python
  on_intervention: Callable[[str], str | None] | None = None
  ```
- The callback only receives the failure report string
- Both CLI and API callers pass empty strings for `epic`, `story`, `retry_counts`
- Intervention log entries lack the structured context required by AC#2

### Why Architect Review
- Changing the callback signature is a breaking API change for all callers
- Tied to B05 — the intervention architecture decision affects what context is needed
- Multiple valid approaches: expand callback params, pass a context object, use a different pattern

### Options

| Option | Approach |
|---|---|
| A | Expand callback signature: `Callable[[str, str, str, str], str \| None]` (error, epic, story, phase) |
| B | Pass a dataclass/dict context object: `Callable[[InterventionContext], str \| None]` |
| C | Make the callback a method on an object that already has context |

**Recommendation:** Option B — a context dataclass is extensible and self-documenting.

**Decision needed:** What context fields should the intervention callback receive?

---

## B07: /rebuild Endpoint Blocks Server Indefinitely
**Severity:** HIGH | **Story:** 4-2 | **Found by:** BMAD only

### Current State
- **File:** `src/main.py:245-260`
- `POST /rebuild` is a synchronous FastAPI endpoint that calls `run_rebuild()`
- A full rebuild (all stories) could take hours
- While blocked, the server is unresponsive to health checks, dashboard, and stage polling

### Why Architect Review
- Tied directly to B05 — the intervention architecture decision determines the async strategy
- FastAPI has built-in async support, but the underlying LangGraph calls are synchronous
- Background task approaches have different trade-offs (threading, multiprocessing, Celery)

### Options

| Option | Approach |
|---|---|
| A | `BackgroundTasks` — FastAPI built-in; runs after response | Simple but limited control |
| B | `asyncio.to_thread()` — run synchronous code in thread pool | Async endpoint; non-blocking |
| C | Dedicated worker process (e.g., `multiprocessing`, Celery) | Full isolation; complex setup |
| D | Accept blocking — document as CLI-primary with API as convenience | No change; may be acceptable for MVP |

**Recommendation:** Option B for MVP, Option C for production.

**Decision needed:** Is blocking acceptable for MVP? If not, which async pattern?

---

## B08: run_command Security Model (shell=True + Denylist Bypass)
**Severity:** HIGH | **Stories:** 4-2, 4-5 | **Found by:** Both agents

### Current State
- **File:** `src/tools/scoped.py:197-226`
- `run_command` passes user-provided command to `subprocess.run(command, shell=True, ...)`
- `BLOCKED_PATTERNS` denylist is trivially bypassable (double spaces, split flags, backtick substitution, base64, etc.)
- `cwd` is set to scoped root, but shell commands can use absolute paths to escape
- Story spec Task 2 requires: "Validate that no tool call can write outside {target_dir}/"

### Why Architect Review
- **Fundamental security architecture decision** — denylist vs allowlist vs sandboxing
- Affects all roles that have `run_command` in their tool list
- The fix could range from minor (better denylist) to major (process-level sandboxing)
- Interacts with B14 (write_restrictions bypass)

### Options

| Option | Approach | Security Level | Effort |
|---|---|---|---|
| A | Improved denylist + path validation on command output | LOW | LOW |
| B | Allowlist: only permit specific command prefixes (git, pytest, ruff, etc.) | MEDIUM | MEDIUM |
| C | Drop `shell=True`, use `shlex.split()` + allowlist | HIGH | MEDIUM |
| D | Process-level sandbox (nsjail, firejail, Docker) | HIGHEST | HIGH |
| E | Accept risk: document that LLM agents are trusted within target_dir | N/A | NONE |

**Recommendation:** Option C — removes shell injection entirely and enables proper command allowlisting.

**Decision needed:** What security model for agent command execution? How strict does the sandbox need to be?

---

## B09: Intervention Retry Policy (Single Retry)
**Severity:** MEDIUM | **Story:** 4-2 | **Found by:** Both agents

### Current State
- **File:** `src/intake/rebuild.py:139-156`
- When a story fails and intervention provides a fix, the pipeline retries exactly once
- If the retry also fails, the story is marked failed with no further intervention opportunity
- Spec says "Re-invoke the pipeline" but doesn't explicitly cap retries

### Why Architect Review
- Retry count affects user experience and cost (each retry = full LLM pipeline)
- No clear spec guidance — needs a design decision
- Infinite retries could waste API credits; zero retries defeats intervention purpose

### Options

| Option | Max Retries |
|---|---|
| A | Keep single retry (current) — document as intentional |
| B | Configurable retry limit (e.g., `MAX_INTERVENTION_RETRIES = 3`) |
| C | Unlimited retries until user explicitly skips/aborts |

**Recommendation:** Option B with default of 3.

**Decision needed:** How many intervention retries per story?

---

## B10: Target_dir Validation Strategy
**Severity:** MEDIUM | **Story:** 4-2 | **Found by:** BMAD only

### Current State
- **File:** `src/intake/rebuild.py:32-55` and `src/main.py:246-260`
- Neither the API endpoint nor `run_rebuild()` validates `target_dir`
- An attacker could pass `/` or the Shipyard source tree itself
- `_init_target_project` runs `git init` and `git commit` directly on the path

### Why Architect Review
- Security boundary: what paths are valid targets?
- Validation strategy must not break legitimate use cases (relative paths, new directories)
- Tied to B02 (spec_dir validation) — should use consistent approach

### Options

| Option | Approach |
|---|---|
| A | Validate target_dir is under a configured base directory |
| B | Validate target_dir is not a system directory and not the Shipyard source tree |
| C | Create target_dir if it doesn't exist; only validate it's not a protected path |

**Recommendation:** Option C — most user-friendly while preventing obvious mistakes.

**Decision needed:** What paths should be rejected?

---

## B11: No Language Detection in Project Scaffold
**Severity:** MEDIUM | **Story:** 4-2 | **Found by:** BMAD only

### Current State
- **File:** `src/intake/rebuild.py:344-348`
- Task 6 specifies: "Create basic project scaffold based on the spec summary (language detection from intake)"
- Current implementation only creates a `README.md` with static content
- No reading of `spec-summary.md`, no language detection, no dynamic scaffold

### Why Architect Review
- Scaffold design affects all downstream stories (agents write code into this structure)
- Language detection strategy: parse spec-summary.md? Rely on LLM classification? Use file extensions?
- Scaffold templates needed per language (Python, Node.js, Go, etc.)

### Options

| Option | Approach |
|---|---|
| A | Parse spec-summary.md for language keywords, generate appropriate scaffold |
| B | Add a `language` field to the intake pipeline output, use it in scaffold |
| C | Keep minimal scaffold (README only) — let agents create structure as needed |

**Recommendation:** Option B — cleanest separation of concerns.

**Decision needed:** Should scaffold be language-aware? If yes, which languages to support?

---

## B12: No Checkpointing During Rebuild Orchestrator
**Severity:** LOW | **Story:** 4-2 | **Found by:** BMAD only

### Current State
- **File:** `src/intake/rebuild.py:277`
- `build_orchestrator()` called with no `checkpointer` argument
- If process crashes mid-pipeline, no recovery point exists
- Sub-agents (via `run_sub_agent`) do use `SqliteSaver`
- Project context mandates "Checkpointing: SqliteSaver from langgraph-checkpoint-sqlite"

### Why Architect Review
- Adding checkpointing to the rebuild orchestrator affects state management and recovery semantics
- The rebuild loop already provides story-level recovery (retry on failure) — checkpointing adds node-level recovery
- May conflict with the "compile once, reuse" optimization (B15/A15)

**Decision needed:** Is story-level retry sufficient, or does the orchestrator need node-level checkpointing?

---

## B13: route_to_reviewers Empty Send List Hangs Pipeline (Pre-existing)
**Severity:** MEDIUM | **Story:** 4-4 | **Found by:** BMAD only

### Current State
- **File:** `src/multi_agent/orchestrator.py:296-298, 876`
- When no files exist to review, `route_to_reviewers` returns `[]`
- No forward path exists from `prepare_reviews` to `collect_reviews` when Send list is empty
- Pipeline hangs indefinitely

### Why Architect Review
- Pre-existing issue, not introduced by Epic 4
- Fix requires adding a fallback edge from `prepare_reviews` to skip reviews when no files exist
- This changes the graph topology, which is an architectural decision

**Decision needed:** Add a fallback edge bypassing review when no files exist? Which node should it route to?

---

## B14: run_command Ignores write_restrictions for Restricted Roles
**Severity:** HIGH | **Story:** 4-5 | **Found by:** Both agents

### Current State
- **File:** `src/tools/scoped.py:204-241`
- `run_command` never calls `_check_write_restrictions`
- `TEST_ROLE` has both `run_command` and `write_restrictions=("tests/",)`
- Test Agent can execute `echo "malicious" > src/main.py` to bypass restrictions

### Why Architect Review
- Tied directly to B08 — the `run_command` security model decision
- Story Task 2 explicitly scopes write restrictions to `write_file` and `edit_file` only
- But AC#2 says restrictions are "enforced" broadly — spec gap
- Three valid approaches: enforce in run_command, remove run_command from TEST_ROLE, or accept as designed

### Options

| Option | Approach |
|---|---|
| A | Add output path validation to `run_command` (hard — requires parsing shell commands) |
| B | Remove `run_command` from `TEST_ROLE` tools list |
| C | Accept risk — LLM system prompt already constrains behavior |
| D | Solve via B08 (allowlist/no-shell approach naturally restricts writes) |

**Recommendation:** Option D — solve this as part of the broader `run_command` security decision.

**Decision needed:** Should write_restrictions apply to run_command? If yes, how?

---

## Summary

| Priority | Count | Key Theme |
|---|---|---|
| CRITICAL | 2 | Pipeline failure routing (B01), API intervention architecture (B05) |
| HIGH | 4 | Callback context (B06), server blocking (B07), shell security (B08), write restrictions (B14) |
| MEDIUM | 5 | Input validation (B02, B03, B10), retry policy (B09), scaffold (B11) |
| LOW | 2 | Checkpointing (B12), pre-existing hang (B13) |
| Spec interpretation | 1 | Graph topology (B04) |
| **Total** | **14** | |

### Recommended Review Order
1. **B05 + B06 + B07** — API intervention cluster (interdependent, highest impact)
2. **B08 + B14** — run_command security cluster (interdependent)
3. **B01 + B04** — Pipeline graph design (interdependent)
4. **B02 + B03 + B10** — Input validation cluster (related theme)
5. **B09, B11, B12, B13** — Independent items (lower priority)

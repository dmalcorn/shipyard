# MVP Requirements Map — Project Shipyard

> PRD requirements for the MVP hard gate (Tuesday 11:59 PM), mapped to PRESEARCH decisions and implementation status.
>
> All examples reference files in `sandbox/` — safe test files that are not part of the production codebase.

---

## MVP Hard Gate Checklist

All 7 items required to pass. Source: PRD § "MVP Requirements (36 Hours)"

| # | PRD Requirement | PRESEARCH Decision | Implementation | Status |
|---|---|---|---|---|
| 1 | **Persistent loop** — agent runs continuously, accepts new instructions without restarting | Docker + FastAPI server (Q10). LangGraph checkpointing for session resumption. | FastAPI server + CLI entry point. SQLite checkpoints for state persistence. | DONE |
| 2 | **Surgical file editing** — targeted changes without rewriting entire files | Anchor-based replacement / exact string match (Q2). Fail loudly on no-match or non-unique. | `edit_file` tool with `old_string`/`new_string` contract. See examples below using `sandbox/hello.py`. | DONE |
| 3 | **Context injection** — accepts injected context at runtime, uses it in generation | 3-layer injection: always-present, task-specific, on-demand (Q6). | 3-layer context injection system. See examples below using `sandbox/` files. | DONE |
| 4 | **Tracing enabled** — at least 2 shared trace links showing different execution paths | LangSmith auto-tracing + custom metadata tags + file audit log (Q13). | LangSmith integration + local audit log. `docs/trace-links.md` has links. | DONE |
| 5 | **PRESEARCH.md submitted** — research notes and all architecture artifacts | Completed all 13 questions across 3 phases. | `gauntlet_docs/PRESEARCH.md` — all questions answered. | DONE |
| 6 | **Accessible via GitHub** — runs locally, no deployment required at this stage | Local Docker + `docker compose up` or CLI mode. | `Dockerfile`, `docker-compose.yml`, `README.md` with setup guide. | DONE |
| 7 | **CODEAGENT.md submitted** — Agent Architecture and File Editing Strategy sections complete | Architecture: LangGraph StateGraph. Editing: exact string match. | `CODEAGENT.md` exists with architecture details. | DONE |

---

## CODEAGENT.md — MVP Sections

These 4 sections are due at MVP. Source: PRD Appendix "CODEAGENT.md"

| Section | What's Required | Status |
|---|---|---|
| **Agent Architecture** | Diagram or description of full agent architecture — loop design, tool calls, state management, entry/exit conditions, error branches | DONE |
| **File Editing Strategy** | Step-by-step mechanism for surgical edits. How it locates the correct block. What happens when it gets the location wrong. | DONE |
| **Multi-Agent Design** | Orchestration model, how agents communicate, how parallel outputs are merged. Diagram if helpful. | DONE |
| **Trace Links** | Trace 1 (normal run) + Trace 2 (different execution path — error, branching, or different task type) | DONE |

---

## Supporting Detail: File Editing Strategy

Source: PRD § "File Editing", PRESEARCH Q2 + Q4

| Aspect | PRESEARCH/Implementation |
|---|---|
| **Strategy** | Anchor-based replacement (exact string match). Industry-proven, fails loudly, robust to line drift, language-agnostic. |
| **Failure: non-unique match** | Return error with match count. LLM provides more context to disambiguate, retries. |
| **Failure: no match (stale)** | Force re-read of file, retry with accurate content. |
| **Failure: no match (hallucinated)** | Force re-read. Read-before-edit requirement minimizes this. |
| **Failure: whitespace mismatch** | Fail loudly. NO fuzzy matching. Re-read and retry with byte-accurate content. |
| **Mechanism** | Claude reads file → selects unique `old_string` anchor → produces `new_string` → tool executes replacement. On error, Claude self-corrects via re-read + retry. |

### Example: Surgical Edit on `sandbox/hello.py`

**Scenario:** Change the `greet` function to add an exclamation and a timestamp.

1. **Agent reads** `sandbox/hello.py` — sees current content:
   ```python
   def greet(name: str) -> str:
       """Return a greeting string."""
       return f"Hello, {name}!"
   ```

2. **Agent calls `edit_file`** with:
   - `file_path`: `sandbox/hello.py`
   - `old_string`: `return f"Hello, {name}!"`
   - `new_string`: `return f"Hello, {name}! Welcome aboard."`

3. **Tool finds exactly 1 match** → replaces it → returns `SUCCESS: edited sandbox/hello.py`

4. **Agent re-reads** `sandbox/hello.py` to verify the edit landed correctly.

### Example: Edit Failure and Recovery

**Scenario:** Agent tries to edit `sandbox/hello.py` but uses stale content.

1. **Agent calls `edit_file`** with:
   - `old_string`: `return f"Hi, {name}!"` (wrong — file actually says `"Hello, {name}!"`)

2. **Tool returns** `ERROR: old_string not found in sandbox/hello.py`

3. **Agent self-corrects:** re-reads `sandbox/hello.py`, sees actual content, retries with correct `old_string`.

### Example: Non-Unique Match

**Scenario:** Agent tries to edit `sandbox/config_sample.yaml` but the anchor is ambiguous.

1. **Agent calls `edit_file`** with:
   - `file_path`: `sandbox/config_sample.yaml`
   - `old_string`: `name:` (matches both `app.name` on line 3 and `database.name` on line 10)

2. **Tool returns** `ERROR: old_string found 2 times in sandbox/config_sample.yaml — must be unique`

3. **Agent self-corrects:** expands anchor to include surrounding context:
   - `old_string`: `  name: "sandbox-app"` → now unique, edit succeeds.

**PRD warning:** Test against files >200 lines — behavior often breaks above that size.

---

## Supporting Detail: Multi-Agent Coordination

Source: PRD § "Multi-Agent Coordination", PRESEARCH Q5

| Aspect | PRESEARCH/Implementation |
|---|---|
| **Minimum** | Spawn and coordinate at least 2 agents. Implemented: Test, Dev, 2 Review (parallel), Architect, Fix Dev. |
| **Communication** | Filesystem as coordination primitive — agents write to files, downstream agents read those files. |
| **Output merging** | No automatic merge. Architect Agent reads all upstream files, makes deliberate decisions. |
| **Conflict resolution** | Architect Agent is gatekeeper — evaluates findings, approves/dismisses, produces fix plan. |
| **Framework** | LangGraph (Python). Built-in LangSmith tracing. |

### Example: Two-Agent Review of `sandbox/hello.py`

1. **Dev Agent** edits `sandbox/hello.py` — adds input validation to the `fibonacci` function.

2. **Two Review Agents spawn in parallel**, both read `sandbox/hello.py`:
   - Review Agent 1 writes findings to `sandbox/review-1.md` (e.g., "missing type guard for negative inputs")
   - Review Agent 2 writes findings to `sandbox/review-2.md` (e.g., "no docstring update for new behavior")

3. **Architect Agent** reads both review files, decides which findings warrant fixes, writes `sandbox/fix-plan.md`.

4. **Fix Dev Agent** reads `sandbox/fix-plan.md`, applies approved edits to `sandbox/hello.py`.

---

## Supporting Detail: Context Injection

Source: PRD § "Context Injection", PRESEARCH Q6

| Layer | What's Injected | When | Example with Sandbox Files |
|---|---|---|---|
| **Layer 1 — Always Present** | Agent role, orchestration guidance, project conventions | At agent start | `coding-standards.md` loaded into every agent's system prompt |
| **Layer 2 — Task-Specific** | Task description, relevant file paths, prior agent output | With task assignment | "Edit `sandbox/hello.py` to add input validation to `fibonacci`. Here is the review from `sandbox/review-1.md`." |
| **Layer 3 — On-Demand** | Agent reads files as needed during execution | During execution | Agent uses `read_file` on `sandbox/config_sample.yaml` to check database settings before editing |

---

## Supporting Detail: Observability

Source: PRD § "Observability", PRESEARCH Q13

| Requirement | Implementation |
|---|---|
| **Every run traceable** | LangSmith auto-tracing + custom metadata tags (role, task ID, file paths, git refs, model) + local audit log in `logs/`. |
| **At least 2 trace links** | `docs/trace-links.md` — must show two different execution paths. |

### Example Trace: Editing `sandbox/hello.py`

```
[Session abc123] — Task: "Add input validation to fibonacci"
│
├─ [Dev Agent - Sonnet] Started
│  ├─ Read: sandbox/hello.py
│  ├─ Edit: sandbox/hello.py (add guard clause to fibonacci)
│  ├─ Read: sandbox/hello.py (verify edit)
│  └─ Done
│
├─ [Review Agent 1 - Sonnet] Started (parallel)
│  ├─ Read: sandbox/hello.py
│  ├─ Write: sandbox/review-1.md
│  └─ Done
│
├─ [Review Agent 2 - Sonnet] Started (parallel)
│  ├─ Read: sandbox/hello.py
│  ├─ Write: sandbox/review-2.md
│  └─ Done
│
├─ [Architect Agent - Opus] Started
│  ├─ Read: sandbox/review-1.md
│  ├─ Read: sandbox/review-2.md
│  ├─ Write: sandbox/fix-plan.md
│  └─ Done
│
└─ [Fix Dev Agent - Sonnet] Started
   ├─ Read: sandbox/fix-plan.md
   ├─ Edit: sandbox/hello.py (apply approved fixes)
   └─ Done
```

---

## Clone-and-Run Verification

The PRD says "another engineer can clone and run without asking you questions." Verify before submission:

- [ ] `README.md` has setup instructions (env vars, dependencies, Docker)
- [ ] `docker compose up` works out of the box (or clear alternative)
- [ ] `.env.example` or equivalent documents required environment variables
- [ ] No hardcoded paths or secrets in committed code

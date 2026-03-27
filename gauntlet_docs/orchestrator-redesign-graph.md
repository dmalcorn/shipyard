# Orchestrator Redesign: Graph Sketch

## Architecture: Three Graphs

The system keeps its three-level LangGraph architecture:

- **Level 1 — rebuild_graph**: Iterates epics, tags git after each
- **Level 2 — epic_graph**: Iterates stories within an epic, runs post-epic review
- **Level 3 — orchestrator**: Processes a single story (THIS IS WHAT WE'RE REDESIGNING)

---

## Level 3: Redesigned Story Orchestrator

Maps directly from `build-loop.sh` phases 1-8.

### Node Inventory

```
Node Name         Type    What It Does                              Script Equivalent
─────────────────────────────────────────────────────────────────────────────────────
create_story      LLM     BMAD SM agent: CS for story X-Y           Phase 1 (SM:CS)
write_tests       LLM     BMAD TEA agent: AT for story X-Y          Phase 2 (TEA:AT)
implement         LLM     BMAD DEV agent: DS for story X-Y          Phase 3 (DEV:DS)
test_automation   LLM     BMAD TEA agent: TA for story X-Y          Phase 4 (TEA:TA)
run_tests         BASH    pytest tests/ -v                          Phase 5 (pre-check)
test_review       LLM     BMAD TEA agent: RV for story X-Y          Phase 5 (TEA:RV)
check_review      BASH    Parse review file for P1/P2 issues        Phase 5b (gate)
fix_review        LLM     BMAD TEA agent: fix P1/P2 from review     Phase 5b (conditional)
code_review       LLM     BMAD DEV agent: CR for story X-Y          Phase 6 (DEV:CR)
run_ci            BASH    scripts/local_ci.sh (or pytest fallback)  Phase 7 (CI)
fix_ci            LLM     BMAD DEV agent: fix CI failures           Phase 7 (conditional)
git_commit        BASH    git add + git commit                      Phase 8 (Commit)
error_handler     BASH    Structured failure report                  (circuit breaker)
```

### Graph Edges (Happy Path)

```
START
  │
  ▼
create_story ──► write_tests ──► implement ──► test_automation
                                                    │
                                                    ▼
                                               run_tests
                                                    │
                                            ┌───────┴───────┐
                                            │               │
                                         [PASS]          [FAIL]
                                            │               │
                                            ▼               ▼
                                      test_review      implement (retry)
                                            │           or error_handler
                                            ▼
                                       check_review
                                            │
                                    ┌───────┴───────┐
                                    │               │
                                [NO ISSUES]    [HAS P1/P2]
                                    │               │
                                    │               ▼
                                    │          fix_review
                                    │               │
                                    └───────┬───────┘
                                            │
                                            ▼
                                       code_review
                                            │
                                            ▼
                                         run_ci
                                            │
                                    ┌───────┴───────┐
                                    │               │
                                 [PASS]          [FAIL]
                                    │               │
                                    ▼               ▼
                                git_commit      fix_ci ──► run_ci (retry)
                                    │               or error_handler
                                    ▼
                                   END
```

### Key Design Decisions

#### 1. "Bash First, LLM on Failure" Pattern

Two nodes use this pattern:

**run_tests → conditional:**
```python
def route_after_tests(state) -> str:
    if state["test_passed"]:
        return "pass"                      # → test_review (skip LLM fix)
    if state["test_cycle_count"] >= MAX_TEST_CYCLES:
        return "error"                     # → error_handler
    return "retry"                         # → implement (LLM fixes code)
```

**run_ci → conditional:**
```python
def route_after_ci(state) -> str:
    if state["test_passed"]:
        return "pass"                      # → git_commit (skip LLM fix)
    if state["ci_cycle_count"] >= MAX_CI_CYCLES:
        return "error"                     # → error_handler
    return "retry"                         # → fix_ci (LLM fixes CI issues)
```

The fix_ci node loops back to run_ci, creating a bash→LLM→bash retry cycle
(exactly matching the `while [[ $ci_attempt -lt $MAX_CI_ATTEMPTS ]]` loop
in build-loop.sh Phase 7).

#### 2. "Invoke BMAD Agent" Pattern

Every LLM node follows the same structure — a thin wrapper that invokes the
appropriate BMAD agent, not a hand-crafted prompt:

```python
def implement_node(state: OrchestratorState) -> dict[str, Any]:
    """Invoke BMAD DEV agent to implement the story."""
    story_id = state["task_id"]
    session_id = state.get("session_id", "")
    working_dir = _get_working_dir(state)

    result = invoke_bmad_agent(
        agent="bmad-dev",               # Which BMAD agent
        command=f"DS for story {story_id}",  # What command to run
        tools=TOOLS_DEV,                # Scoped permissions
        session_id=session_id,
        working_dir=working_dir,
    )

    return {
        "current_phase": "implement",
        "files_modified": result.get("files_modified", []),
    }
```

The `invoke_bmad_agent()` function replaces both `run_sub_agent()` and the
30-line prompt strings. It either:

- **Option A**: Shells out to `claude --print --allowedTools` (like the bash
  scripts do). Simple, proven, matches existing behavior. Each call gets a
  fresh Claude session — no context bleed between phases.

- **Option B**: Uses `run_sub_agent()` but with a standardized BMAD-invoking
  prompt template instead of per-node prompt construction. Stays within the
  LangGraph process.

Recommendation: **Start with Option A** since it's proven (the scripts use it
successfully) and gives us process isolation for free. Move to Option B later
if we need tighter LangGraph integration (e.g., streaming state updates).

#### 3. Scoped Tool Permissions Per Phase

Each node type gets only the tools it needs (matching the bash scripts):

```python
# Read-only phases (review, analysis)
TOOLS_REVIEW = "Read,Glob,Grep,Task,TodoWrite"

# Test writing phases (TEA agent)
TOOLS_TEA = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(pytest *),Skill"

# Implementation phases (DEV agent)
TOOLS_DEV = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pytest *),Bash(git *),Skill"

# CI fix (needs linting tools)
TOOLS_CI_FIX = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pytest *),Bash(ruff *),Bash(mypy *),Skill"
```

#### 4. check_review: Bash Gate Before LLM

The `check_review` node is pure bash — it parses the review file for P1/P2
severity findings (grep for patterns like `Severity.*P1`). If none found,
routes directly to `code_review`, skipping the `fix_review` LLM call entirely.

```python
def check_review_node(state: OrchestratorState) -> dict[str, Any]:
    """Parse review file for actionable findings. No LLM."""
    review_path = state.get("review_file_path", "")
    working_dir = _get_working_dir(state)

    if not review_path or not os.path.exists(review_path):
        return {"has_review_issues": False}

    with open(review_path) as f:
        content = f.read()

    has_issues = bool(re.search(
        r"(Severity.*P[12]|Must Fix|critical|high)",
        content, re.IGNORECASE
    ))

    return {"has_review_issues": has_issues}

def route_after_check_review(state) -> str:
    if state.get("has_review_issues", False):
        return "fix"           # → fix_review (LLM)
    return "skip"              # → code_review (bypass fix_review)
```

This directly mirrors build-loop.sh Phase 5b where it greps the review file
before deciding whether to invoke Claude for fixes.

---

## Level 2: Redesigned Epic Graph (Post-Epic Review)

Maps from `code-review-analysis-fix.sh` phases 0-6.

After all stories in an epic complete, the epic graph runs a post-epic
review pipeline. This is a SEPARATE subgraph, not part of the per-story
orchestrator:

```
epic_stories_complete
        │
        ▼
  run_reviews (parallel: BMAD review + Claude review)
        │
        ▼
  analyze_reviews (LLM: compare findings, create fix plan + architect review)
        │
        ▼
  apply_clear_fixes (LLM: apply Category A fixes from fix plan)
        │
        ▼
  architect_review (LLM: evaluate Category B controversial items)
        │
        ▼
  apply_architect_fixes (LLM: apply architect-approved fixes)
        │
        ▼
  run_ci ──► [PASS] ──► git_commit ──► END
    │
  [FAIL] ──► fix_ci ──► run_ci (retry, up to MAX_CI_ATTEMPTS)
```

This maps 1:1 to the seven phases of code-review-analysis-fix.sh.

Key difference from current orchestrator: the review/architect/fix pipeline
lives HERE (epic level), not in the per-story orchestrator. Per-story
gets a lightweight code review (Phase 6 DEV:CR) but the heavy dual-agent
review with architect triage happens once per epic.

---

## What Changes vs Current Implementation

### Nodes REMOVED from per-story orchestrator:
- `review_node` x2 (parallel reviewers) → moves to epic-level post-processing
- `architect_node` → moves to epic-level post-processing
- `fix_dev_node` → replaced by `fix_review` (conditional) and `fix_ci` (conditional)
- `prepare_reviews` / `collect_reviews` → moves to epic-level
- `post_fix_test` / `post_fix_ci` → unnecessary (fix_ci loops back to run_ci)
- `system_test` / `final_ci` → consolidated into single `run_ci`
- `git_snapshot` → unnecessary (commit happens once at end)

### Nodes ADDED to per-story orchestrator:
- `create_story` — BMAD SM agent (was implicit)
- `test_automation` — BMAD TEA agent (was missing)
- `test_review` — BMAD TEA agent (was missing)
- `check_review` — bash gate (new pattern)
- `fix_review` — conditional LLM (new pattern)
- `code_review` — BMAD DEV agent (replaces dual reviewer + architect)
- `fix_ci` — conditional LLM, only on CI failure (replaces unconditional fix_dev)

### Net effect on LLM calls per story:

**Current (worst case):** 6 LLM calls always fire
```
test_agent + dev_agent + reviewer_1 + reviewer_2 + architect + fix_dev = 6
```

**Redesigned (happy path — tests pass, no review issues, CI passes):**
```
create_story + write_tests + implement + test_automation + test_review + code_review = 6
```

Same count, but DIFFERENT work: every call produces value (writes code, writes
tests, reviews). No calls are wasted on reviewing/fixing nothing.

**Redesigned (happy path, rebuild mode where story specs already exist):**
```
write_tests + implement + test_automation + test_review + code_review = 5
```

`create_story` can be skipped when story specs already exist (rebuild from epics.md).

**Plus:** The heavy review pipeline (dual review + architect triage + fix cycle)
runs ONCE per epic instead of per story. For an epic with 5 stories, that's
5 x 4 = 20 LLM calls saved.

---

## Implementation Order

1. **Create `invoke_bmad_agent()`** — the shared function that all LLM nodes call
2. **Rewrite orchestrator nodes** — thin wrappers using invoke_bmad_agent
3. **Add conditional edges** — bash-first pattern for run_tests and run_ci
4. **Add check_review gate** — bash parsing before fix_review
5. **Move review pipeline to epic_graph** — post-epic review subgraph
6. **Test with hello-world** — same testdir, compare timing and output quality

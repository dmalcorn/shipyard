# Factory Comparison: Shipyard vs ChatBridge

_Generated 2026-04-11_

---

## Overview

| Dimension | Shipyard (8-Capstone) | ChatBridge (7-ChatBridge) |
|-----------|----------------------|--------------------------|
| **Location** | `c:\alcorn\Gauntlet\8-Capstone\factory\shipyard` | `c:\alcorn\Gauntlet\7-ChatBridge\factory` |
| **Target built** | Ship (Go app, 40 stories), chat2bpmn (in progress) | Chatbox |
| **Production results** | 40/40 stories, 28.5h, $495 | Unknown |
| **Graph levels** | 4 (Intake → Rebuild → Epic → Orchestrator) + ReAct core | 3 (Rebuild → Epic → Orchestrator) + ReAct core |

---

## 1. Graph Topology

### Shipyard
```
Level 0: Intake Pipeline (read_specs → intake_specs → create_backlog → output)
Level 1: Rebuild Graph (preflight → load_backlog → [epic loop via Send] → post_rebuild)
Level 2: Epic Graph (story loop + epic post-processing with parallel reviews)
Level 3: Orchestrator (check_story → create_story → check_dev → implement → code_review → run_ci → fix_ci → git_commit)
Core:    ReAct agent loop (agent → tools → agent)
```

### ChatBridge
```
Level 1: Rebuild Graph (preflight → init_project → load_backlog → [epic loop via Send] → finalize)
Level 2: Epic Graph (story loop + epic post-processing with parallel reviews)
Level 3: Orchestrator (phase_router → create_story → write_tests → implement → code_review → run_ci → fix_ci → git_commit)
Core:    ReAct agent loop (agent → tools → agent)
```

### Key Differences

| Feature | Shipyard | ChatBridge |
|---------|----------|------------|
| Intake pipeline | Has Level 0 (spec reading + backlog creation) | No intake; assumes backlog exists |
| Story skip checks | `check_story` + `check_dev` nodes skip already-done work | `phase_router` node routes to starting phase |
| Write tests node | **Removed** (was invoking missing BMAD skill) | **Present** (`write_tests_node` using `bmad-testarch-atdd`) |
| Test retry loop | implement → run_tests → [fail] → implement (up to 5x) | implement → run_tests → [fail] → implement (up to 5x) |
| CI retry loop | run_ci → [fail] → fix_ci → run_ci (up to 4x) | run_ci → [fail] → fix_ci → run_ci (up to 4x) |
| Phase-level resume | Via story status checks (check_story, check_dev) | Via `resume_phase` field + `phase_router` node |
| Human intervention | Not visible in current code | `LangGraph.interrupt()` with retry/skip/abort options |
| Graceful shutdown | Not visible | Two-level Ctrl+C (graceful pause → force quit) |

**Verdict:** ChatBridge has more sophisticated resume/intervention handling (phase_router, interrupt, graceful shutdown). Shipyard has simpler skip-check logic but added a dedicated Intake pipeline.

---

## 2. Agent Invocation

### Both factories use the same core mechanism:
- **Subprocess** to `claude --print --output-format stream-json --allowedTools {tools}`
- Real-time stream parsing of JSON events
- BMAD-style prompt wrapping (`invoke_bmad_agent()`)
- Plain CLI invocation (`invoke_claude_cli()`) for non-BMAD tasks

### Differences

| Feature | Shipyard | ChatBridge |
|---------|----------|------------|
| Primary invocation | `invoke_bmad_agent()` + `invoke_claude_cli()` | `invoke_bmad_agent()` + `invoke_claude_cli()` |
| SDK direct calls | Yes — `ChatAnthropic` in `spawn.py` for sub-agents | No evidence of direct SDK usage |
| Sub-agent spawning | `spawn.py` creates LangGraph subgraphs with `ChatAnthropic(model=model_id)` | Sub-agents via CLI subprocess only |
| CI with fix | Separate `fix_ci_node` in graph | `invoke_ci_with_fix()` helper (bash + LLM loop in one function) |
| Scoped CI fixes | No scope constraint mentioned | Scope constraint: "Only fix failures related to story {id}" |
| Pre-existing error detection | Not visible | Detects "all errors are pre-existing" and skips further fix cycles |
| Fix history injection | Not visible | Injects fix history into retry cycles to prevent rediscovery |

**Verdict:** ChatBridge's CI fix loop is more mature — scoped constraints, pre-existing error detection, and fix history injection prevent wasted LLM calls. Shipyard has a unique SDK-direct path for sub-agents that ChatBridge lacks.

---

## 3. Model Selection

### Shipyard
- **Orchestrator nodes:** No `model` parameter passed — uses CLI default
- **Sub-agents (spawn.py):** Uses role-based tiers from `roles.py`
- **roles.py tiers:** dev=sonnet, test=sonnet, reviewer=sonnet, architect=opus, fix_dev=sonnet

### ChatBridge
- **Orchestrator nodes:** No `model` parameter passed — uses CLI default
- **roles.py tiers:** Same mapping (dev=sonnet, architect=opus)
- **No per-node override in YAML** — all hardcoded in Python

### Both factories have the same gap:
**Neither factory specifies models per graph node.** The `invoke_bmad_agent()` function accepts a `model` parameter, but no caller uses it. Everything runs on the CLI's default model (likely Sonnet).

The `roles.py` model tiers are only used by `spawn.py` sub-agents (Shipyard) — not by the orchestrator's BMAD invocations.

**Opportunity:** Both could benefit from explicit per-node model assignment. For example:
- `create_story` → haiku (simple spec formatting)
- `implement` → sonnet (coding)
- `code_review` → sonnet (analysis)
- `fix_ci` → haiku (usually simple formatting fixes)
- Epic architect review → opus (complex judgment)

---

## 4. State Management & Persistence

| Feature | Shipyard | ChatBridge |
|---------|----------|------------|
| LangGraph checkpointer | SQLite (`checkpoints/shipyard.db`) | SQLite (`checkpoints/factory.db`) |
| Pipeline checkpoint | Via state fields (`resume_epic_index`, etc.) | Dual: Postgres (primary) + filesystem JSON (fallback) |
| Phase-level checkpoint | Story status file checks | Dedicated `checkpoints/phase.json` per story |
| Epic phase checkpoint | Not visible | `checkpoints/epic-phase.json` with ordered phase list |
| Test output persistence | In state (`last_test_output`) | Written to `checkpoints/test-{task_id}.txt` |
| CI output persistence | In state (`last_ci_output`) | Written to `checkpoints/ci-output-{scope}.txt` |

**Verdict:** ChatBridge has significantly more robust persistence — dual-backend (Postgres + filesystem), dedicated phase files, and file-based test/CI output that survives process crashes. Shipyard relies more on in-memory LangGraph state.

---

## 5. Epic-Level Review & Triage

Both factories implement the same dual-review + architect triage pattern:

```
Parallel Reviews (BMAD + Claude) → Analysis (Category A/B) → 
Auto-fix Category A → Architect reviews Category B (Opus) → 
Apply approved fixes → Epic CI → Commit
```

### Differences

| Feature | Shipyard | ChatBridge |
|---------|----------|------------|
| Max fix cycles | Not visible | 2 (`MAX_EPIC_FIX_CYCLES = 2`) |
| Category B handling | Logged for review | Logged for review |
| Epic CI | Full CI after fixes | Full CI after fixes |
| Review parallelism | Send API | Send API |

**Verdict:** Essentially identical. This pattern was likely developed in one and copied to the other.

---

## 6. Configuration

| Feature | Shipyard | ChatBridge |
|---------|----------|------------|
| Config file | Environment variables + `.env` | `factory.yaml` (structured) + `.env` |
| Operator identity | Env vars | YAML (`operator.first_name`, etc.) |
| GitHub config | Env vars | YAML (`github.username`, `factory_repo`, etc.) |
| Git identity | Env vars | YAML (`git.author_name`, etc.) |
| Target project | Env vars / CLI args | YAML (`target.dir`) |
| Railway config | Env vars | YAML (`railway.target_name`, etc.) |
| LangSmith | Env vars | YAML (`langsmith.project`) |
| Model overrides | Not configurable | Not configurable (hardcoded in roles.py) |
| Retry limits | Hardcoded constants | Hardcoded constants |

**Verdict:** ChatBridge's `factory.yaml` is cleaner for operator configuration — everything in one file. Shipyard scatters config across env vars. Neither makes model selection or retry limits configurable.

---

## 7. Unique Strengths

### Shipyard Only
1. **Intake Pipeline (Level 0)** — can read raw specs and generate the backlog, not just consume one
2. **SDK-direct sub-agent spawning** — `spawn.py` creates LangGraph subgraphs with `ChatAnthropic`, enabling tighter integration than CLI subprocess
3. **3-layer context injection** — role prompts + coding standards + task files, injected systematically
4. **LangSmith trace metadata** — agent_role, model_tier, phase, parent_session in every trace
5. **Production-proven at scale** — 40 stories, 28.5h, $495, zero failed invocations
6. **Auto-format CI phase** — Prettier + ESLint auto-fix before check (added post-analysis)
7. **Story/dev skip checks** — smart nodes that skip already-done work without phase_router complexity

### ChatBridge Only
1. **factory.yaml** — structured config file for operator/project settings
2. **Dual checkpoint backend** — Postgres primary + filesystem fallback
3. **Phase-level checkpoint files** — granular resume from exact phase
4. **LangGraph.interrupt()** — human-in-the-loop intervention with retry/skip/abort
5. **Graceful shutdown** — two-level Ctrl+C (pause then force-quit)
6. **Scoped CI fix constraints** — "only fix failures related to story X"
7. **Pre-existing error detection** — skips fix cycles when errors aren't from current work
8. **Fix history injection** — prevents agents from rediscovering same issues
9. **Migration auto-generation** — detects and generates DB migrations before tests
10. **Write tests node** — TDD red phase still functional (removed in Shipyard)

---

## 8. Recommended Consolidation Strategy

### Chassis: Shipyard

Shipyard should be the base because:
- Production-proven (40 stories shipped successfully)
- Has the Intake pipeline (ChatBridge doesn't)
- SDK-direct spawning path gives more flexibility
- Better observability (LangSmith metadata)
- Active development (chat2bpmn run, ongoing optimizations)

### Cherry-pick from ChatBridge

These capabilities should be ported to Shipyard:

| Priority | Feature | Effort | Impact |
|----------|---------|--------|--------|
| **P0** | Scoped CI fix constraints | Small | Prevents wasted LLM calls on unrelated errors |
| **P0** | Pre-existing error detection | Small | Eliminates futile fix cycles |
| **P0** | Fix history injection | Small | Prevents agents rediscovering same issues |
| **P1** | factory.yaml config | Medium | Cleaner operator setup, single source of truth |
| **P1** | Graceful shutdown (Ctrl+C) | Medium | Essential for long runs |
| **P1** | Phase-level checkpoint files | Medium | Survives crashes better than in-memory state |
| **P2** | LangGraph.interrupt() | Medium | Human intervention without killing the run |
| **P2** | Dual checkpoint backend (Postgres) | Medium | Railway container resilience |
| **P2** | Per-node model configuration | Medium | Cost optimization (haiku for simple tasks) |
| **P3** | Migration auto-generation | Small | Useful for DB-heavy targets |
| **P3** | Write tests node (TDD) | Small | Restore when BMAD skill is available |

### New capabilities (neither factory has)

| Feature | Impact |
|---------|--------|
| Per-node model selection in config | Major cost savings |
| Batch code reviews (from analysis doc) | ~5 hours saved per run |
| Context preloading for dev agent | ~1-2 min/story saved |
| Cost budget / circuit breaker | Prevents runaway spending |

---

## 9. File Cross-Reference

| Component | Shipyard Path | ChatBridge Path |
|-----------|--------------|-----------------|
| Orchestrator | `src/multi_agent/orchestrator.py` | `src/multi_agent/orchestrator.py` |
| BMAD invoke | `src/multi_agent/bmad_invoke.py` | `src/multi_agent/bmad_invoke.py` |
| Roles | `src/multi_agent/roles.py` | `src/multi_agent/roles.py` |
| Sub-agent spawn | `src/multi_agent/spawn.py` | `src/multi_agent/spawn.py` |
| Rebuild graph | `src/intake/rebuild_graph.py` | `src/intake/rebuild_graph.py` |
| Epic graph | `src/intake/epic_graph.py` | `src/intake/epic_graph.py` |
| Checkpoint | _(in-state)_ | `src/intake/checkpoint.py` |
| Cost tracker | `src/intake/cost_tracker.py` | `src/intake/cost_tracker.py` |
| Audit log | `src/audit_log/audit.py` | `src/audit_log/audit.py` |
| Config | `.env` | `factory.yaml` + `.env` |
| Core agent | `src/agent/graph.py` | `src/agent/graph.py` |
| Context injection | `src/context/injection.py` | _(not found)_ |
| Intervention | _(not found)_ | `src/intake/intervention_log.py` |
| Pause control | _(not found)_ | `src/intake/pause.py` |
| Pipeline tracker | `src/pipeline_tracker.py` | _(not found)_ |

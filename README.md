# Shipyard

A software factory powered by LangGraph that autonomously implements software projects from planning artifacts. Shipyard orchestrates specialized AI agents (dev, test architect, reviewer, architect) through a structured TDD pipeline to produce working, tested, committed code — epic by epic, story by story.

**Latest build:** [chat2diagram](https://github.com/dmalcorn/chat2diagram) — 101/101 stories, 17/17 epics, ~30h, all epic-N-complete tags applied. See [factory-lessons-from-chat2diagram.md](gauntlet_docs/factory-lessons-from-chat2diagram.md) for the retrospective and [factory-replication-guide.md](gauntlet_docs/factory-replication-guide.md) for how to reproduce against a new target. Reference state for v2 work is tagged [`v1-chat2diagram-baseline`](https://github.com/dmalcorn/shipyard/tree/v1-chat2diagram-baseline).

Earlier proof-of-concept: [Ship rebuild](https://github.com/dmalcorn/shiprebuild) — 40/40 stories, 9/9 epics, 28h 35m, $495.36, zero failed invocations.

## What It Does

Shipyard takes a set of BMAD planning artifacts (product brief, architecture, epics/stories, approved tech stack) and autonomously:

1. **Generates a CI script** from the approved tech stack via bmad-architect
2. **Iterates through epics** with pause/resume checkpointing
3. **For each story:** creates spec → writes tests → implements → runs tests → code reviews → runs CI → fixes failures → commits
4. **After each epic:** runs dual parallel code reviews, triages findings, applies fixes, runs full CI
5. **Pushes to remote** and tags each completed epic

## Prerequisites

- Python 3.13+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (for BMAD agent invocations)
- Docker (optional — for containerized deployment)
- [Anthropic API key](https://console.anthropic.com/)
- [LangSmith API key](https://smith.langchain.com/) (for tracing)

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/dmalcorn/shipyard.git shipyard
cd shipyard
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — fill in your API keys
```

Required variables:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude model access |
| `LANGCHAIN_API_KEY` | LangSmith trace collection |
| `LANGCHAIN_TRACING_V2` | Set `true` to enable tracing |
| `LANGCHAIN_PROJECT` | LangSmith project name (default: `shipyard`) |
| `SHIPYARD_RELAY_URL` | Public dashboard relay endpoint (optional) |
| `SHIPYARD_RELAY_KEY` | Shared secret for relay auth (optional) |

### 3. Run a build

Each target keeps its own `factory.yaml` and `.env`. The pre-flight wrapper stages the per-target config into shipyard root, runs smoke tests, prompts for confirmation, then kicks off the rebuild:

```bash
bash scripts/preflight.sh /path/to/target/project
```

Resume after interruption:

```bash
bash scripts/preflight.sh /path/to/target/project --resume
```

The target directory must be **outside** Shipyard's source tree, must contain `_bmad-output/planning-artifacts/epics.md`, and must contain either `_bmad-output/approved-tech-stack.md` (so the architect can generate `scripts/ci.sh`) or a hand-written `scripts/ci.sh` that conforms to [targetsetup/ci-script-specification.md](targetsetup/ci-script-specification.md). All agent file operations, bash commands, and git operations are scoped to the target directory.

**Docker rebuild** — runs the pipeline in a container with the target project mounted:

```bash
docker compose -f docker-compose.rebuild.yml up
```

**Relay/dashboard deployment** — the public monitoring dashboard at <https://shipyard-production-29ae.up.railway.app/> runs the same FastAPI app on Railway via `uvicorn src.main:app`. Operators don't run the FastAPI server locally; the local factory invocation goes through `preflight.sh` → `python -m src.main --rebuild`.

See [docs/how-to-setup-factory-harness.md](docs/how-to-setup-factory-harness.md) for the full pre-flight checklist (Railway provisioning, target repo state, the four authentications), [factory-replication-guide.md](gauntlet_docs/factory-replication-guide.md) for the deeper architecture and host-vs-Docker decision, [api-reference.md](gauntlet_docs/api-reference.md) for HTTP endpoints, and [railway-setup-guide.md](gauntlet_docs/railway-setup-guide.md) for target Railway provisioning.

## Architecture

Shipyard uses a 4-level hierarchical LangGraph architecture. Each level invokes the next as a wrapper node. See [LangGraph diagrams](gauntlet_docs/langgraph-diagrams.md) for Mermaid visualizations.

### Pipeline Hierarchy

| Level | Graph | Source | Purpose |
|---|---|---|---|
| 0 | Intake Pipeline | [src/intake/pipeline.py](src/intake/pipeline.py) | Reads specs, generates epics.md |
| 1 | Rebuild Graph | [src/intake/rebuild_graph.py](src/intake/rebuild_graph.py) | Iterates epics, pause/resume, checkpointing |
| 2 | Epic Graph | [src/intake/epic_graph.py](src/intake/epic_graph.py) | Iterates stories, epic post-processing with dual review |
| 3 | Story Orchestrator | [src/multi_agent/orchestrator.py](src/multi_agent/orchestrator.py) | Per-story TDD: create → test → implement → review → CI → commit |

### Per-Story Pipeline

```
create_story → write_tests → implement → run_tests →
code_review → run_ci → [fix_ci retry loop] → git_commit
```

Each LLM node invokes a specific BMAD agent via [bmad_invoke.py](src/multi_agent/bmad_invoke.py) with scoped tool permissions. Bash nodes (tests, CI, git) run without LLM involvement.

### Project Layout

```
src/
├── main.py                  # FastAPI app (relay/dashboard) + --rebuild CLI entry point
├── agent/prompts.py         # Role-based system prompt templates (Layer 1 context)
├── context/                 # 3-layer context injection system
├── intake/                  # Rebuild pipeline, backlog parsing, cost tracking
│   ├── rebuild_graph.py     # Level 1: epic loop with checkpointing
│   ├── epic_graph.py        # Level 2: story loop + epic post-processing
│   ├── pipeline.py          # Level 0: intake spec processing
│   ├── cost_tracker.py      # Thread-safe cost accumulator
│   └── pause.py             # Graceful pause/resume via signal handler
├── multi_agent/             # BMAD agent invocation + orchestration
│   ├── orchestrator.py      # Level 3: per-story TDD pipeline
│   ├── bmad_invoke.py       # Claude CLI subprocess with scoped tools
│   └── roles.py             # Role definitions + LangSmith trace metadata
├── audit_log/               # Structured markdown audit logger
├── static/                  # Public monitoring dashboard (Command Bridge)
├── log_relay.py             # Postgres log relay for dashboard streaming
└── web_relay.py             # Web relay client for pushing events to Railway
```

## Public Monitoring Dashboard (Command Bridge)

**Live at:** [shipyard-production-29ae.up.railway.app](https://shipyard-production-29ae.up.railway.app/) — no login required.

The Command Bridge is a real-time monitoring dashboard where anyone can watch Shipyard's software factory builds as they happen, or replay any previous run.

**Header** — Shipyard logo, health badge (polls `/health` every 30s, green/red status dot), and a pulsing amber LIVE indicator when a pipeline is actively running.

**Pipeline Output** — full-screen terminal viewer streaming real-time log output from the running pipeline. A session dropdown lets you select any previous run to replay its complete log. Mode tag shows LIVE during active builds or REPLAY when viewing past sessions.

**Rebuild Pipeline Flow Graph** — visual node graph showing pipeline stages: Load Backlog → Init Project → [per story: TDD Pipeline → Test → Review → Git Tag] → Complete. Each node lights up as the pipeline progresses (idle → active → completed/failed). A story label shows which story is currently being processed.

**Stats Bar** — four counters at the bottom: Completed, Failed, Interventions, and Total stories. A progress bar fills as stories complete.

**How it works:** During a rebuild, [web_relay.py](src/web_relay.py) pushes log events from the local Docker pipeline to Railway's [log_relay.py](src/log_relay.py), which stores them in Postgres. The dashboard connects via SSE (`/api/stream/{session_id}`) for real-time streaming. For past runs, all stored events are fetched and replayed into the terminal viewer. The dashboard auto-detects active sessions and switches to live mode automatically.

**Design:** Industrial/naval theme — dark hull background, amber accents, JetBrains Mono for terminal output, Outfit for headings, steel-plate panel borders. Source: [src/static/index.html](src/static/index.html).

## Observability

- **LangSmith tracing** — every agent run auto-traced with custom metadata (role, task_id, phase, model_tier)
- **Markdown audit logs** — `logs/session-{id}.md` with tree-style tool call traces
- **SSE live streaming** — real-time log events pushed to browser via `/api/stream/{session_id}`

## Development

### Run tests

```bash
pytest tests/ -v
# 428 tests, 100% pass rate
```

### Lint and type check

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
```

### Local CI (all checks)

```bash
bash scripts/local_ci.sh
```

Runs ruff, mypy, and pytest in sequence — all must pass before committing. GitHub Actions is disabled; all CI runs locally.

## Key Documentation

### Operating the factory

| Document | Description |
|---|---|
| [factory-replication-guide.md](gauntlet_docs/factory-replication-guide.md) | Setup from zero: prerequisites, the four authentications, the host-vs-Docker question, first run, common gotchas |
| [factory-lessons-from-chat2diagram.md](gauntlet_docs/factory-lessons-from-chat2diagram.md) | Retrospective on the chat2diagram build: architectural patterns that worked, recovery patterns, factory hardenings shipped during the run |
| [api-reference.md](gauntlet_docs/api-reference.md) | HTTP endpoints exposed by the FastAPI server: `/rebuild/intervene` for human interventions during a build, plus the relay endpoints used by the Command Bridge dashboard |
| [git-remote-setup-guide.md](gauntlet_docs/git-remote-setup-guide.md) | Configuring target-repo remotes for Docker and host-mode runs |
| [railway-setup-guide.md](gauntlet_docs/railway-setup-guide.md) | Pre-build provisioning of a target's Railway project (Postgres, Mailpit, app service) via the Railway CLI. Includes the single-attempt-then-verify protocol that prevents duplicate-service creation |
| [How-to-extract-db-logs.md](gauntlet_docs/How-to-extract-db-logs.md) | Pulling pipeline logs off the Railway relay for forensic analysis |

### Target templates (copy into target's `_bmad-output/planning-artifacts/`)

| Document | Description |
|---|---|
| [targetsetup/README.md](targetsetup/README.md) | Why these templates exist and how to use them |
| [targetsetup/ci-script-specification.md](targetsetup/ci-script-specification.md) | CI behavior the factory expects: required CLI flags, phases, story-scoping, doc-only short-circuit, multi-stack patterns, pre-commit hook coordination, anti-patterns |
| [targetsetup/story-and-epic-writing-guide.md](targetsetup/story-and-epic-writing-guide.md) | Vertical-slice principle, story anatomy with Cross-cutting Considerations, multi-component conventions, anti-patterns from chat2diagram |
| [targetsetup/test-structure-guide.md](targetsetup/test-structure-guide.md) | Five eval categories applied greenfield, story-tagging conventions, central mock factories (the schema-drift fix), test pyramid for factory builds |
| [targetsetup/local-dev-docker-guide.md](targetsetup/local-dev-docker-guide.md) | Three-container local dev topology (app + Postgres + Mailpit) in Docker Desktop with bind-mounted source. Eliminates the chat2bpmn/chat2diagram failure mode where dev pointed at Railway directly |
| [targetsetup/email-testing-guide.md](targetsetup/email-testing-guide.md) | Mailpit-based end-to-end pattern for email-touching features (password reset, verification, magic-link). Catches the failure mode where mock-based tests pass but production email is broken |
| [targetsetup/lessons-learned-protocol.md](targetsetup/lessons-learned-protocol.md) | Two-tier system for capturing build lessons: forensic `lessons-learned/NNN-*.md` files (Tier 1, auto-distilled by factory after multi-cycle CI) and prescriptive `## Agent Coding Rules` in target `CLAUDE.md` (Tier 2, promoted by architect at epic review) |

### Architecture references

| Document | Description |
|---|---|
| [LangGraph Diagrams](gauntlet_docs/langgraph-diagrams.md) | Mermaid visualizations of all 5 pipeline graphs |
| [orchestrator-redesign-rationale.md](gauntlet_docs/orchestrator-redesign-rationale.md) / [orchestrator-redesign-graph.md](gauntlet_docs/orchestrator-redesign-graph.md) | Architecture decision records for the multi-graph orchestrator |
| [epic-review-redesign.md](gauntlet_docs/epic-review-redesign.md) | ADR for the per-epic dual-review subgraph |
| [Coding Standards](coding-standards.md) | Conventions enforced across all agent-generated code |

### Operating costs

| Document | Description |
|---|---|
| [cost-analysis.md](gauntlet_docs/cost-analysis.md) | Cost methodology and per-node tier selection (numbers will be refreshed with chat2diagram run data in v2) |
| [ai-development-log.md](gauntlet_docs/ai-development-log.md) | Tools, prompts, workflow notes |

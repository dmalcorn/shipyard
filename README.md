# Shipyard

A software factory powered by LangGraph that autonomously implements software projects from planning artifacts. Shipyard orchestrates specialized AI agents (dev, test architect, reviewer, architect) through a structured TDD pipeline to produce working, tested, committed code — epic by epic, story by story.

**Factory run:** 40/40 stories, 9/9 epics, 28h 35m, $495.36, zero failed invocations.

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

### 3. Run

**CLI mode** — interactive REPL:

```bash
python src/main.py --cli
```

**Server mode** — FastAPI with auto-reload:

```bash
uvicorn src.main:app --reload --port 8000
```

**Docker:**

```bash
docker compose up
```

## Autonomous Rebuild Pipeline

Rebuild a project from planning artifacts:

```bash
python -m src.main --rebuild /path/to/target/project
```

The target directory must contain `_bmad-output/approved-tech-stack.md` listing all technologies the project uses. The pipeline reads this to generate a comprehensive CI script before any code is written.

The `target_dir` must be **outside** Shipyard's source tree. All agent file operations, bash commands, and git operations are scoped to the target directory.

**Docker rebuild** — runs the pipeline in a container with the target project mounted:

```bash
docker compose -f docker-compose.rebuild.yml up
```

**Resume after interruption:**

```bash
python -m src.main --rebuild /path/to/target/project --resume
```

See [User's Guide](gauntlet_docs/users-guide.md) for full rebuild documentation.

## Architecture

Shipyard uses a 4-level hierarchical LangGraph architecture. Each level invokes the next as a wrapper node. See [LangGraph diagrams](gauntlet_docs/langgraph-diagrams.md) for Mermaid visualizations of all 5 graphs.

### Pipeline Hierarchy

| Level | Graph | Source | Purpose |
|---|---|---|---|
| 0 | Intake Pipeline | [src/intake/pipeline.py](src/intake/pipeline.py) | Reads specs, generates epics.md |
| 1 | Rebuild Graph | [src/intake/rebuild_graph.py](src/intake/rebuild_graph.py) | Iterates epics, pause/resume, checkpointing |
| 2 | Epic Graph | [src/intake/epic_graph.py](src/intake/epic_graph.py) | Iterates stories, epic post-processing with dual review |
| 3 | Story Orchestrator | [src/multi_agent/orchestrator.py](src/multi_agent/orchestrator.py) | Per-story TDD: create → test → implement → review → CI → commit |
| Core | Agent Loop | [src/agent/graph.py](src/agent/graph.py) | ReAct tool-calling loop (foundation for all LLM nodes) |

### Per-Story Pipeline

```
create_story → write_tests → implement → run_tests →
code_review → run_ci → [fix_ci retry loop] → git_commit
```

Each LLM node invokes a specific BMAD agent via [bmad_invoke.py](src/multi_agent/bmad_invoke.py) with scoped tool permissions. Bash nodes (tests, CI, git) run without LLM involvement.

### Project Layout

```
src/
├── main.py                  # FastAPI server + CLI entry point
├── agent/                   # LangGraph graph, state, prompts
├── tools/                   # File ops, search, execution tools
├── context/                 # 3-layer context injection system
├── intake/                  # Rebuild pipeline, backlog parsing, cost tracking
│   ├── rebuild_graph.py     # Level 1: epic loop with checkpointing
│   ├── epic_graph.py        # Level 2: story loop + epic post-processing
│   ├── pipeline.py          # Level 0: intake spec processing
│   ├── cost_tracker.py      # Thread-safe cost accumulator
│   └── pause.py             # Graceful pause/resume via signal handler
├── multi_agent/             # Sub-agent spawning + orchestration
│   ├── orchestrator.py      # Level 3: per-story TDD pipeline
│   └── bmad_invoke.py       # Claude CLI subprocess with scoped tools
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
- **Trace links** — [docs/trace-links.md](docs/trace-links.md) with 2 LangSmith traces (normal run + error recovery)

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

| Document | Description |
|---|---|
| [CODEAGENT.md](CODEAGENT.md) | Agent architecture, file editing strategy, multi-agent design, trace links |
| [User's Guide](gauntlet_docs/users-guide.md) | Comprehensive usage documentation |
| [LangGraph Diagrams](gauntlet_docs/langgraph-diagrams.md) | Mermaid visualizations of all 5 pipeline graphs |
| [Comparative Analysis](gauntlet_docs/comparative-analysis.md) | 7-section analysis of Ship vs ShipRebuild |
| [AI Cost Analysis](gauntlet_docs/cost-analysis.md) | Development spend, rebuild costs, production projections |
| [AI Development Log](gauntlet_docs/ai-development-log.md) | Tools, prompts, code analysis, learnings |
| [Coding Standards](coding-standards.md) | Conventions enforced across all agent-generated code |
| [Requirements Map](gauntlet_docs/FINAL-requirements-map.md) | PRD requirements mapped to implementation status |
| [BMAD Skill Setup](gauntlet_docs/bmad-skill-setup-guide.md) | Guide for adapting BMAD skills to autonomous pipelines |

## Ship App Rebuild Results

Shipyard rebuilt [Ship](https://github.com/dmalcorn/shiprebuild) — a government-grade project management platform — from planning artifacts:

| Metric | Value |
|---|---|
| Stories | 40/40 (100%) |
| Epics | 9/9 (100%) |
| Pipeline time | 28h 35m |
| API cost | $495.36 |
| Agent invocations | 225 |
| Failed invocations | 0 |
| Human interventions | 1 (credit card exhaustion, not code) |
| Go backend | ~49,500 LOC |
| React frontend | ~14,700 LOC |
| Database | PostgreSQL, 18 migrations, 42 seed documents |
| Deployed | [shiprebuild-production.up.railway.app](https://shiprebuild-production.up.railway.app/) |

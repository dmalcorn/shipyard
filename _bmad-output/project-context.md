---
project_name: 'shipyard'
user_name: 'Diane'
date: '2026-03-23'
sections_completed: ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'code_quality', 'workflow_rules', 'critical_rules']
status: 'complete'
rule_count: 42
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

### Core Runtime
- **Python** ==3.13
- **langgraph** ==1.1.0
- **langchain-anthropic** ==1.4.0
- **langgraph-checkpoint-sqlite** ==3.0.3
- **fastapi** ==0.135.1
- **uvicorn** ==0.42.0
- **python-dotenv** ==1.2.2

### Dev / Quality
- **ruff** ==0.15.7 (linter + formatter, line-length=100, 2026 style guide)
- **mypy** ==1.19.1 (strict mode)
- **pytest** ==9.0.2

### Infrastructure
- **Docker** — base image `python:3.13-slim`, expose port 8000
- **docker-compose** — service `agent`, volume for checkpoints
- **LangSmith** — auto-tracing via `LANGCHAIN_TRACING_V2=true`

### Model Routing
- **Haiku** — file reads, search, low-stakes operations
- **Sonnet** — code generation, editing, test writing
- **Opus** — Architect decisions, complex multi-file reasoning

## Critical Implementation Rules

### Python Language Rules
- **Naming:** `snake_case` (functions/vars/modules), `PascalCase` (classes), `UPPER_SNAKE_CASE` (constants)
- **Type hints:** Required on all function signatures; inferred on local variables is fine
- **Imports:** stdlib → 3rd-party → local; absolute only (`from src.tools.file_ops import read_file`); no relative imports; no wildcard imports
- **Docstrings:** Required on all public functions/classes; Google-style for complex functions; private helpers (`_name`) exempt
- **Error handling:** Never bare `except:` — always `except Exception as e:`; tools catch all exceptions and return `ERROR:` strings; no exceptions escape from tool functions
- **String formatting:** f-strings preferred
- **Async:** Follow LangGraph patterns — graph nodes can be sync or async; tools are sync unless IO-bound

### Framework-Specific Rules

#### LangGraph
- **Graph topology:** Custom `StateGraph` only — never use `create_react_agent`
- **State schema:** Extend `MessagesState` with custom fields: `task_id`, `retry_count`, `current_phase`, `agent_role`, `files_modified`
- **Reducers:** Use `Annotated[list[str], operator.add]` for accumulating fields like `files_modified`
- **Tool decorator:** All tools use `@tool` from `langchain_core.tools`
- **Tool interface contract:** String parameters in, string results out; return `SUCCESS: {result}` or `ERROR: {description}. {recovery_hint}`
- **Checkpointing:** `SqliteSaver` from `langgraph-checkpoint-sqlite`; checkpoints dir is git-ignored
- **Multi-agent:** Subgraphs for sequential pipeline stages; `Send` API for parallel fan-out (e.g., dual code review)
- **Conditional edges:** Route based on state fields (`current_phase`, `retry_count`), not by parsing message content

#### FastAPI
- **Entry point:** `src/main.py` serves both HTTP API and CLI
- **Port:** 8000 (mapped in docker-compose)
- **Purpose:** Accepts task instructions; not a full REST API — minimal endpoints

#### Inter-Agent Communication
- **File-based handoffs:** Agents write output files, downstream agents read them — no shared memory
- **YAML frontmatter:** All inter-agent files use structured metadata header (`agent_role`, `task_id`, `timestamp`, `input_files`)
- **Architect decides:** Only the Architect agent merges conflicting recommendations

### Testing Rules
- **Framework:** pytest; tests live in `tests/` mirroring `src/` structure (e.g., `tests/test_tools/`, `tests/test_agent/`)
- **Test file naming:** `test_{module}.py` matching the source module name
- **Run before every commit:** All tests must pass before git commit
- **Tool testing:** Test both `SUCCESS:` and `ERROR:` return paths; verify string output format
- **Graph testing:** Test node functions in isolation first, then test graph edges/routing with mock state
- **No mocks for file I/O in tool tests:** Use temp directories (`tmp_path` fixture) with real file operations
- **Quality gate:** `bash scripts/local_ci.sh` runs ruff → mypy → pytest in sequence; all three must pass

### Code Quality & Style Rules
- **Linting:** ruff enforces PEP 8, import ordering, unused imports; line-length=100
- **Formatting:** ruff format (replaces Black); 2026 style guide
- **Type checking:** mypy strict mode — all function signatures must have type annotations
- **File organization:** All source in `src/` with domain-based modules (`agent/`, `tools/`, `multi_agent/`, `context/`, `logging/`)
- **Runtime artifacts:** `logs/`, `reviews/`, `checkpoints/` are git-ignored; never commit runtime output
- **Configuration:** Project root only (`pyproject.toml`, `requirements.txt`, `.env.example`, `Dockerfile`, `docker-compose.yml`)
- **No dead code:** Remove unused imports, variables, and functions — don't comment them out

### Development Workflow Rules
- **Local CI:** Always run `bash scripts/local_ci.sh` (ruff + mypy + pytest) before committing
- **Commit gate:** All three checks must pass — no skipping with `--no-verify`
- **Audit logging:** Every agent session produces a markdown log at `logs/session-{id}.md`
- **LangSmith traces:** Supplemental to audit logs — used for interactive debugging, not primary record
- **Environment variables:** Never commit `.env`; use `.env.example` as template with `ANTHROPIC_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`
- **Docker workflow:** `docker-compose up` for running; mount `.env` and persist `checkpoints/` volume
- **Fail-loud semantics:** Non-negotiable — errors must surface immediately, never silently swallowed

### Critical Don't-Miss Rules

#### Anti-Patterns — NEVER Do These
- **Never use `create_react_agent`** — always custom `StateGraph`; this is a core architectural decision
- **Never parse message content for routing** — use state fields (`current_phase`, `retry_count`) for conditional edges
- **Never use fuzzy/regex file editing** — exact string match (anchor-based replacement) only; >90% first-attempt success required
- **Never let exceptions escape tools** — every `@tool` function must catch and return `ERROR:` string
- **Never share state between agents via memory** — file-based handoffs only; Architect merges conflicts
- **Never skip the quality gate** — ruff + mypy + pytest must all pass; no `--no-verify`

#### Retry Limits — Circuit Breakers
- **Global:** 50 LLM turns per task (hard stop)
- **Per-operation:** 3 edit retries, 5 test cycles, 3 CI failures
- **On limit hit:** Fail loud with clear error, don't silently continue

#### File Editing Strategy
- **Anchor-based replacement:** Exact string match with sufficient context lines
- **Never fall back to fuzzy matching** — if exact match fails, report error and let agent retry with better anchors
- **Verify after edit:** Always read the file back after editing to confirm the change landed correctly

#### Security
- **Never commit `.env` or credentials** — `.env.example` only
- **Sandbox all `run_command` tool execution** — restrict to project working directory
- **Role-based write restrictions** — agents can only write to directories appropriate for their role

---

## Usage Guidelines

**For AI Agents:**
- Read this file before implementing any code
- Follow ALL rules exactly as documented
- When in doubt, prefer the more restrictive option
- Update this file if new patterns emerge

**For Humans:**
- Keep this file lean and focused on agent needs
- Update when technology stack changes
- Review periodically for outdated rules
- Remove rules that become obvious over time

Last Updated: 2026-03-23

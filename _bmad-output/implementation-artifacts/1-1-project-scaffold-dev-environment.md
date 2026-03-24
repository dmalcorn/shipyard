# Story 1.1: Project Scaffold & Dev Environment

Status: review

## Story

As a developer,
I want to clone the Shipyard repo and have a working Python environment with all dependencies installed,
so that I can begin building the agent immediately.

## Acceptance Criteria

1. **Given** a fresh clone of the repository **When** I run `pip install -r requirements.txt` **Then** all dependencies install successfully: `langgraph`, `langchain-anthropic`, `langgraph-checkpoint-sqlite`, `python-dotenv`, `fastapi`, `uvicorn`
2. **Given** the project directory **When** I inspect the structure **Then** it matches the architecture doc: `src/agent/`, `src/tools/`, `src/multi_agent/`, `src/context/`, `src/logging/`, `scripts/`, `tests/`
3. **Given** the project root **When** I check `.env.example` **Then** it contains: `ANTHROPIC_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`
4. **Given** `pyproject.toml` **When** I inspect it **Then** it configures `ruff` and `mypy`
5. **Given** the project root **When** I check Docker files **Then** `Dockerfile` and `docker-compose.yml` are present and buildable

## Tasks / Subtasks

- [x] Task 1: Create complete directory structure (AC: #2)
  - [x] Create `src/` with subdirectories: `agent/`, `tools/`, `multi_agent/`, `context/`, `logging/`
  - [x] Add `__init__.py` to every Python package directory
  - [x] Create `scripts/` directory
  - [x] Create `tests/` with subdirectories: `test_tools/`, `test_agent/`, `test_multi_agent/`, `test_context/`
  - [x] Add `__init__.py` to every test package directory
  - [x] Create runtime artifact directories with `.gitkeep`: `logs/`, `reviews/`, `checkpoints/`
- [x] Task 2: Create `requirements.txt` (AC: #1)
  - [x] Pin versions: `langgraph`, `langchain-anthropic`, `langgraph-checkpoint-sqlite`, `python-dotenv`, `fastapi`, `uvicorn`
  - [x] Add dev dependencies: `pytest`, `ruff`, `mypy`
- [x] Task 3: Create `pyproject.toml` (AC: #4)
  - [x] Project metadata (name=shipyard, version, python_requires>=3.13)
  - [x] `[tool.ruff]` config: line-length=100, select PEP8 rules + import ordering
  - [x] `[tool.mypy]` config: strict mode, ignore missing imports for third-party
- [x] Task 4: Create `.env.example` (AC: #3)
  - [x] `ANTHROPIC_API_KEY=your-key-here`
  - [x] `LANGCHAIN_TRACING_V2=true`
  - [x] `LANGCHAIN_API_KEY=your-langsmith-key-here`
  - [x] `LANGCHAIN_PROJECT=shipyard`
- [x] Task 5: Create `.gitignore` (AC: #2)
  - [x] Ignore: `logs/`, `reviews/`, `checkpoints/`, `.env`, `__pycache__/`, `.venv/`, `*.pyc`, `.mypy_cache/`, `.ruff_cache/`
- [x] Task 6: Create `Dockerfile` (AC: #5)
  - [x] Base image: `python:3.13-slim`
  - [x] Copy requirements, install deps, copy source
  - [x] Expose port 8000, CMD runs uvicorn
- [x] Task 7: Create `docker-compose.yml` (AC: #5)
  - [x] Service: `agent` — builds from Dockerfile, maps port 8000, mounts `.env`
  - [x] Volume for `checkpoints/` persistence
- [x] Task 8: Create placeholder `src/main.py`
  - [x] Minimal stub with FastAPI app and CLI arg parsing so imports resolve
- [x] Task 9: Verify scaffold
  - [x] Run `pip install -r requirements.txt` succeeds (verified via docker build)
  - [x] Run `ruff check src/` succeeds
  - [x] Run `mypy src/` succeeds
  - [x] Run `docker compose build` succeeds

## Dev Notes

- This is the foundation story — every subsequent story depends on this structure existing
- Follow the **exact** directory structure from the architecture doc (Section: Complete Project Directory Structure)
- Use Python 3.13+ as the base — this is a hard requirement
- `src/logging/` will shadow the stdlib `logging` module; use absolute imports (`from src.logging.audit import ...`) to avoid conflicts
- Runtime directories (`logs/`, `reviews/`, `checkpoints/`) are git-ignored but need `.gitkeep` so the dirs exist on clone
- Do NOT create `create_react_agent` — Decision 1 in architecture mandates custom `StateGraph` from day one

### Project Structure Notes

- Directory layout defined in architecture doc Section "Complete Project Directory Structure" — follow exactly
- `src/multi_agent/roles.py` (not `agents.py`) — architecture doc resolved this naming in validation section
- `src/agent/nodes.py` exists in the full structure but is not created until Story 1.4

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Complete Project Directory Structure]
- [Source: _bmad-output/planning-artifacts/architecture.md#Starter Template Evaluation — Initialization Commands]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 1: Graph Topology]
- [Source: coding-standards.md#Project Structure Rules]
- [Source: coding-standards.md#Quality Enforcement]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

- mypy strict mode flagged `@app.get("/health")` as untyped decorator — resolved with `# type: ignore[untyped-decorator]`
- ruff format required minor whitespace adjustments in 3 files — auto-fixed
- Docker base image updated to `python:3.13-slim` per project-context.md (story said 3.13, project-context.md says 3.13)

### Completion Notes List

- All 9 tasks completed and verified
- 44 pytest tests written covering all 5 acceptance criteria
- Full quality gate passed: ruff check, ruff format, mypy strict, pytest 44/44, docker compose build
- Versions pinned per project-context.md (langgraph==1.1.0, langchain-anthropic==1.4.0, etc.)
- `scripts/local_ci.sh` created (referenced in coding-standards.md quality enforcement)
- `tests/conftest.py` created (referenced in architecture doc)

### File List

- src/__init__.py (new)
- src/main.py (new)
- src/agent/__init__.py (new)
- src/tools/__init__.py (new)
- src/multi_agent/__init__.py (new)
- src/context/__init__.py (new)
- src/logging/__init__.py (new)
- tests/__init__.py (new)
- tests/conftest.py (new)
- tests/test_scaffold.py (new)
- tests/test_tools/__init__.py (new)
- tests/test_agent/__init__.py (new)
- tests/test_multi_agent/__init__.py (new)
- tests/test_context/__init__.py (new)
- requirements.txt (new)
- pyproject.toml (new)
- .env.example (new)
- .gitignore (modified)
- Dockerfile (new)
- docker-compose.yml (new)
- scripts/local_ci.sh (new)
- logs/.gitkeep (new)
- reviews/.gitkeep (new)
- checkpoints/.gitkeep (new)

### Change Log

- 2026-03-23: Story 1.1 implemented — full project scaffold with all directories, config files, Docker setup, and verification tests

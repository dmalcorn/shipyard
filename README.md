# Shipyard

Multi-agent coding assistant powered by LangGraph. Shipyard orchestrates specialized AI agents (dev, reviewer, architect, tester) to analyze, review, and modify codebases through a structured pipeline.

## Prerequisites

- Python 3.13+
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

## Usage

### CLI example

```
$ python src/main.py --cli
Shipyard CLI (session: abc-123)
Type "exit" or "quit" to stop.

>>> Read the README.md file
[Agent reads the file and returns its contents]

>>> Review src/main.py for code quality issues
[Agent dispatches reviewer agents and returns findings]
```

### API example

```bash
curl -X POST http://localhost:8000/instruct \
  -H "Content-Type: application/json" \
  -d '{"message": "Read the README.md file"}'
```

## Architecture

Shipyard uses a LangGraph state machine with tool-calling agents. The core loop: receive instruction → plan → execute tools → return result. Checkpoints persist conversation state in SQLite.

For detailed architecture and multi-agent design, see `CODEAGENT.md` (Epic 2).

```
src/
├── main.py              # FastAPI server + CLI entry point
├── agent/               # LangGraph graph, state, prompts
├── tools/               # File ops, search, execution tools
├── context/             # Context injection system
├── logging/             # LangSmith tracing + audit logger
└── multi_agent/         # Sub-agent spawning + orchestration
```

## Development

### Run tests

```bash
pytest tests/ -v
# or use the helper script:
bash scripts/run_tests.sh
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

This runs ruff, mypy, and pytest in sequence — all must pass before committing.

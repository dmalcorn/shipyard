# Coding Standards

These conventions apply to all code written in this project. When this file is injected as agent context, follow every rule exactly.

---

## Python Conventions

### Naming

- `snake_case` — functions, variables, modules, file names
- `PascalCase` — classes only (`InterventionLogger`, `RebuildState`)
- `UPPER_SNAKE_CASE` — constants (`MAX_CI_CYCLES`, `DEFAULT_MODEL`)

### Type Hints

- Required on all function signatures (parameters and return type)
- Not required on local variables — type inference is fine
- Use `from __future__ import annotations` for forward references

```python
# Correct
def build_prompt(role: str, context_files: list[str]) -> str:
    result = ""  # no type hint needed on locals
    ...
    return result

# Wrong — missing return type
def build_prompt(role: str, context_files: list[str]):
    ...
```

### Imports

- Order: standard library, then third-party, then local — separated by blank lines
- Absolute imports only (`from src.intake.checkpoint import save_phase`)
- No relative imports (`from .intake import ...`)
- No wildcard imports (`from x import *`)

```python
import os
import subprocess
from typing import Literal

from langgraph.graph import StateGraph, START, END

from src.intake.checkpoint import save_phase
from src.multi_agent.bmad_invoke import invoke_bmad_agent
```

### Docstrings

- Required on all public functions and classes
- Not required on private helpers (`_prefixed` functions)
- Single-line for simple functions
- Google-style for complex functions

```python
def save_phase(target_dir: str, phase: str) -> None:
    """Persist the current phase to <target_dir>/checkpoints/phase.json."""
    ...

def build_system_prompt(role: str, context_files: list[str] | None = None) -> str:
    """Build a system prompt for the given agent role.

    Args:
        role: Agent role identifier (dev, test, reviewer, architect).
        context_files: Optional list of file paths to include as context.

    Returns:
        Complete system prompt string with role description and injected context.
    """
    ...
```

### Error Handling

- Never use bare `except:` — always `except Exception as e:` minimum
- Catch exceptions where you can do something useful with them; don't catch just to re-raise
- Graph nodes: let LangGraph handle retries via state — don't add try/except around node logic
- Log the exception before swallowing or transforming it

```python
# Correct — narrow except, log, re-raise as a typed exception
try:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
except FileNotFoundError:
    logger.error("Backlog not found at %s", path)
    raise

# Wrong — bare except
except:
    return "something went wrong"
```

---

## File-Based Communication Format

All inter-agent files (reviews, fix plans, test specs) use this structure:

```markdown
---
agent_role: {role}
task_id: {task_id}
timestamp: {ISO 8601}
input_files: [{list of files read}]
---

# {Title}

## Summary
{1-2 sentence overview}

## Findings / Plan / Spec

### 1. {Item title}
- **File:** {relative path from project root}
- **Issue/Change:** {description}
- **Severity:** {critical|major|minor}
- **Action:** {what to do}
```

Rules:
- YAML frontmatter is required on every inter-agent file
- File paths are always relative to project root
- Severity uses a fixed 3-level scale: `critical`, `major`, `minor`
- Summary section is always present

---

## Project Structure Rules

- Source code lives in `src/` with domain-based modules: `agent/` (prompts only), `multi_agent/` (BMAD agent invocation + orchestrator), `intake/` (rebuild graph + checkpointing), `context/` (Layer-1 prompt injection), `audit_log/`, `adapters/`
- Tests live in `tests/` mirroring the `src/` structure (`test_intake/`, `test_multi_agent/`, etc.)
- Scripts live in `scripts/` — `preflight.sh` for kickoff, `ci.sh`/`local_ci.sh` for testing, `extract_log.py` + `log_analysis/` for forensics
- Runtime artifacts are git-ignored: `logs/`, `reviews/`. Per-build checkpoints live in `<target>/checkpoints/`, NOT in shipyard root
- Configuration at project root: `pyproject.toml`, `requirements.txt`, `.env.shared`, `.env.example`

---

## Quality Enforcement

- **Linting:** `ruff` — PEP 8 compliance, import ordering, unused imports
- **Type checking:** `mypy` — enforces type hint requirement
- **Testing:** `pytest` — run before every commit
- **Local CI:** `bash scripts/local_ci.sh` runs all three checks in sequence

All three must pass before any git commit. These replace GitHub Actions to avoid burning CI quota.

---

## What Not To Do

| Don't | Do Instead |
|---|---|
| Use bare `except:` | Use `except Exception as e:` |
| Use relative imports | Use absolute imports from `src.` |
| Use wildcard imports | Import specific names |
| Skip type hints on function signatures | Always annotate params and return type |
| Write unstructured inter-agent files | Use YAML frontmatter + numbered findings |

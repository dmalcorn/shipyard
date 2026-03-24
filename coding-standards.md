# Coding Standards

These conventions apply to all code written in this project. When this file is injected as agent context, follow every rule exactly.

---

## Python Conventions

### Naming

- `snake_case` — functions, variables, modules, file names
- `PascalCase` — classes only (`AgentState`, `SqliteSaver`)
- `UPPER_SNAKE_CASE` — constants (`MAX_RETRIES`, `DEFAULT_MODEL`)

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
- Absolute imports only (`from src.tools.file_ops import read_file`)
- No relative imports (`from .tools import ...`)
- No wildcard imports (`from x import *`)

```python
import os
import subprocess
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, START, END

from src.agent.state import AgentState
from src.tools.file_ops import read_file, edit_file
```

### Docstrings

- Required on all public functions and classes
- Not required on private helpers (`_prefixed` functions)
- Single-line for simple functions
- Google-style for complex functions

```python
def read_file(file_path: str) -> str:
    """Read the contents of a file at the given path."""
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
- Tools: catch all exceptions internally, return `ERROR:` strings (never let exceptions escape)
- Graph nodes: let LangGraph handle retries via state — don't add try/except around node logic
- Log the exception before returning the error string

```python
# Correct — inside a tool
try:
    with open(file_path, 'r') as f:
        content = f.read()
    return f"SUCCESS: {content}"
except FileNotFoundError:
    return f"ERROR: File not found: {file_path}. Use list_files to discover available files."
except Exception as e:
    return f"ERROR: Failed to read {file_path}: {e}"

# Wrong — bare except
except:
    return "ERROR: something went wrong"
```

---

## Tool Interface Contract

Every tool follows the same pattern:

1. Parameters are strings (LLM-consumable types)
2. Return value is always a string
3. Success responses start with `SUCCESS:`
4. Error responses start with `ERROR:` followed by what went wrong and a recovery hint
5. No exceptions escape — all errors are caught and returned as strings
6. Large outputs (>5000 chars) are truncated: `(truncated, {n} chars total)`

```python
@tool
def tool_name(param1: str, param2: str) -> str:
    """One-line description. Used by: [which agent roles]."""
    try:
        # ... implementation ...
        return f"SUCCESS: {description_of_result}"
    except Exception as e:
        return f"ERROR: {description_of_failure}. {recovery_hint}"
```

### Error Messages Must Be Self-Correcting

The error tells the LLM exactly what went wrong and what to do next:

```
ERROR: old_string not found in {file_path}. Re-read the file to get current contents.
ERROR: old_string found {count} times in {file_path}. Provide more surrounding context to make the match unique.
ERROR: Command failed with exit code {code}: {stderr_first_500_chars}
ERROR: File not found: {file_path}. Use list_files to discover available files.
ERROR: Permission denied: Review agents cannot edit source files. Write to reviews/ directory only.
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

- Source code lives in `src/` with domain-based modules: `agent/`, `tools/`, `multi_agent/`, `context/`, `logging/`
- Tests live in `tests/` mirroring the `src/` structure (`test_tools/`, `test_agent/`, etc.)
- Scripts live in `scripts/` — bash scripts for CI, testing, git operations
- Runtime artifacts are git-ignored: `logs/`, `reviews/`, `checkpoints/`
- Configuration at project root: `pyproject.toml`, `requirements.txt`, `.env.example`

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
| Raise exceptions from tools | Catch exceptions, return `ERROR:` string |
| Use bare `except:` | Use `except Exception as e:` |
| Use relative imports | Use absolute imports from `src.` |
| Use wildcard imports | Import specific names |
| Skip type hints on function signatures | Always annotate params and return type |
| Write unstructured inter-agent files | Use YAML frontmatter + numbered findings |
| Use fuzzy matching for edits | Use exact string match, fail loudly |
| Rewrite entire files | Use surgical `edit_file` with `old_string`/`new_string` |

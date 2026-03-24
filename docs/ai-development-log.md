# AI Development Log

## Tools & Workflow

**AI Tools Used:** Claude Code (CLI agent for all implementation), Claude API via `langchain-anthropic` (runtime model calls within Shipyard's agent framework), LangSmith (trace visualization and debugging).

**Development Workflow:** All code was written through Claude Code operating as a CLI pair-programmer. The workflow followed BMAD method phases: product brief → architecture decisions → epics/stories → story-by-story implementation. Each story was specified with acceptance criteria and task breakdowns, then handed to Claude Code for TDD-style execution. Human review happened at story boundaries — corrections were fed back as code-review findings for the next iteration.

**IDE/Editor:** VS Code with Claude Code extension. Ruff (linter/formatter) and mypy (type checker) ran as pre-commit gates via `scripts/local_ci.sh`.

## Effective Prompts

**1. Role-Constrained Agent System Prompt** (from `src/agent/prompts.py`):
```
You are a Dev Agent. You write production code and fix bugs using surgical file edits.
You CAN read any file, search the codebase, and run bash commands.
You CANNOT edit files under reviews/ — that is for Review Agents only.
You MUST use exact string matching for edits — no fuzzy matching.
```
*Why effective:* Explicit CAN/CANNOT boundaries prevented agents from overstepping their role. The Review Agent's inverse constraint (read-only on `src/`) enforced separation of concerns at the prompt level.

**2. 3-Layer Context Injection Template** (from `src/context/injection.py`):
```python
def build_system_prompt(role: str, context_files: list[str] | None = None) -> str:
    parts = [get_prompt(role)]  # Layer 1: role prompt
    standards = _read_file_safe(CODING_STANDARDS_PATH)  # Layer 1: always-injected standards
    if context_files:  # Layer 2: task-specific files
        for file_path in context_files:
            parts.append(f"## Context: {basename}\n{content}")
```
*Why effective:* Coding standards were always present (Layer 1), so the agent never "forgot" conventions. Task-specific files (Layer 2) kept context focused without overloading the window.

**3. Coding Standards as Injected Context** (from `coding-standards.md`, injected every call):
```
These conventions apply to all code written in this project. When this file is injected
as agent context, follow every rule exactly.
- Tool interface: String parameters in, string results out
- Return SUCCESS: {result} or ERROR: {description}. {recovery_hint}
- Never bare except: — always except Exception as e:
```
*Why effective:* Defining the tool interface contract (`SUCCESS:`/`ERROR:` strings) in a file that was mechanically injected every time eliminated format drift across agent sessions.

**4. BMAD Story Specification** (structure used for every implementation story):
```
As a [role], I want [feature], so that [value].
Acceptance Criteria: Given/When/Then format
Tasks/Subtasks: Ordered checklist with AC references
Dev Notes: Architecture constraints, dependencies, previous learnings
```
*Why effective:* The structured format gave the AI agent unambiguous scope. The task→AC mapping prevented gold-plating — every line of code traced back to a specific requirement.

## Code Analysis

| Category | Lines | % |
|---|---|---|
| Source code (`src/`) | 4,234 | 48% |
| Test code (`tests/`) | 4,655 | 52% |
| **Total** | **8,889** | 100% |

**AI-generated:** ~95% — all source and test code was written by Claude Code from story specifications. **Human-written:** ~5% — configuration files (`pyproject.toml`, `Dockerfile`, `.env.example`), BMAD planning artifacts, and targeted manual fixes during code review. **AI-assisted:** 100% — even "hand-written" edits were made through Claude Code's edit interface with human direction.

## Strengths & Limitations

**Strengths:**
- **Boilerplate velocity** — scaffolding 6 tool functions with tests, type hints, and docstrings took minutes, not hours.
- **Standard adherence** — with coding standards injected every call, the agent never drifted from conventions (import ordering, error format, naming).
- **Test coverage** — the agent wrote more test code than source code (52% vs 48%), covering both `SUCCESS:` and `ERROR:` paths for every tool.

**Limitations:**
- **Over-engineering by default** — without explicit "keep it minimal" constraints, the agent added unnecessary abstractions (e.g., factory patterns for single-use classes).
- **Context window pressure** — multi-file refactors across 5+ files required careful context management; the agent sometimes lost track of earlier changes.
- **Prompt sensitivity** — "write tests" produced different results than "write failing tests first, then implement" — the TDD framing produced significantly better code.

## Key Learnings

1. **Constraints > capabilities in prompts.** Telling the agent what it CANNOT do (e.g., "cannot edit src/") was more reliable than describing what it should do. Negative constraints are harder to accidentally violate.
2. **Mechanical context injection beats hoping the agent remembers.** Injecting `coding-standards.md` on every call was the single highest-ROI decision — zero convention drift across 50+ agent sessions.
3. **Story specs are the real prompt engineering.** The BMAD task breakdown (with AC references on each subtask) was more effective than any system prompt tweak. Structured specs eliminated ambiguity.
4. **TDD framing changes output quality.** Asking for "failing tests first" produced cleaner implementations than "write code and tests." The red-green cycle naturally constrained scope.
5. **Code review is non-negotiable.** AI-generated code passed its own tests but still contained edge cases and over-engineering that only adversarial review caught.

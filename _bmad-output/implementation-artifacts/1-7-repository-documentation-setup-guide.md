# Story 1.7: Repository Documentation & Setup Guide

Status: complete

## Story

As an evaluator,
I want to clone the repo, follow the README, and have the agent running locally in under 10 minutes,
so that I can evaluate the agent without asking the developer any questions.

## Acceptance Criteria

1. **Given** the `README.md` exists **When** an evaluator reads it **Then** it contains: project overview, prerequisites, environment setup steps, how to run (CLI and server modes), example usage with sample instruction
2. **Given** `.env.example` exists **When** the evaluator copies it to `.env` and fills in API keys **Then** the agent starts successfully with LangSmith tracing enabled
3. **Given** `.gitignore` exists **When** checking the repository **Then** runtime artifacts are excluded: `logs/`, `reviews/`, `checkpoints/`, `.env`, `__pycache__/`, `.venv/`

## Tasks / Subtasks

- [x] Task 1: Create `README.md` (AC: #1)
  - [x] Project title and one-line description
  - [x] Prerequisites: Python 3.13+, Docker (optional), Anthropic API key, LangSmith API key
  - [x] Quick Start section:
    - [x] Clone, create venv, install dependencies
    - [x] Copy `.env.example` → `.env`, fill in keys
    - [x] Run CLI mode: `python src/main.py --cli`
    - [x] Run server mode: `uvicorn src.main:app --reload --port 8000`
    - [x] Run with Docker: `docker compose up`
  - [x] Usage section with example instruction and expected output
  - [x] Architecture overview (brief — point to CODEAGENT.md for details)
  - [x] Development section: running tests (`pytest`), linting (`ruff`), type checking (`mypy`), local CI (`bash scripts/local_ci.sh`)
- [x] Task 2: Create `scripts/local_ci.sh` (AC: #1)
  - [x] Run `ruff check src/ tests/`
  - [x] Run `mypy src/`
  - [x] Run `pytest tests/ -v`
  - [x] Exit on first failure (`set -e`)
  - [x] Print pass/fail summary
- [x] Task 3: Verify `.env.example` completeness (AC: #2)
  - [x] Confirm all required vars present: `ANTHROPIC_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`
  - [x] Add inline comments explaining each variable
- [x] Task 4: Verify `.gitignore` completeness (AC: #3)
  - [x] Confirm ignores: `logs/`, `reviews/`, `checkpoints/`, `.env`, `__pycache__/`, `.venv/`, `*.pyc`, `.mypy_cache/`, `.ruff_cache/`
  - [x] Add any missing entries
- [x] Task 5: Create `scripts/run_tests.sh`
  - [x] `pytest tests/ -v --tb=short`
  - [x] Add coverage if `pytest-cov` is available
- [x] Task 6: Create `scripts/git_snapshot.sh`
  - [x] Takes commit message as argument
  - [x] `git add -A && git commit -m "$1"`
  - [x] Used by agent pipeline for automated commits
- [x] Task 7: End-to-end verification
  - [x] Fresh clone → install → configure .env → run CLI → send "Read the README.md file" → verify response
  - [x] Total time under 10 minutes (NFR6)

## Dev Notes

- This is the final story in Epic 1 — everything should be working end-to-end before writing docs
- README should be concise and action-oriented — evaluators want to run, not read essays
- `scripts/local_ci.sh` is the single command that runs all quality checks — this replaces GitHub Actions
- All three scripts (`local_ci.sh`, `run_tests.sh`, `git_snapshot.sh`) are referenced in the architecture doc
- NFR6 requires clone-and-run in <10 minutes — the README must make this achievable
- Do NOT create CODEAGENT.md content yet — that's Epic 2 (Story 2.4)

### Project Structure Notes

- `README.md` at project root
- `scripts/local_ci.sh`, `scripts/run_tests.sh`, `scripts/git_snapshot.sh`
- Depends on all previous Epic 1 stories (1.1-1.6) being complete

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Development Workflow]
- [Source: _bmad-output/planning-artifacts/architecture.md#Complete Project Directory Structure — scripts/]
- [Source: _bmad-output/planning-artifacts/architecture.md#NFR6: Reproducibility]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.7: Repository Documentation & Setup Guide]
- [Source: coding-standards.md#Quality Enforcement]

## Dev Agent Record

### Agent Model Used
Claude Opus 4.6

### Debug Log References
N/A — docs/scripts story, no debug issues encountered.

### Completion Notes List
- README.md created with all required sections: overview, prerequisites, quick start (CLI/server/Docker), usage examples (CLI + API curl), architecture overview pointing to CODEAGENT.md, and development section with test/lint/CI commands.
- `scripts/local_ci.sh` already existed from Story 1.1 — verified it meets AC#1 (ruff + mypy + pytest, set -euo pipefail, pass/fail summary).
- `.env.example` updated with inline comments explaining each variable. All 4 required vars confirmed present.
- `.gitignore` verified complete — all required entries present (logs/, reviews/, checkpoints/, .env, __pycache__/, .venv/, *.pyc, .mypy_cache/, .ruff_cache/).
- `scripts/run_tests.sh` created with pytest-cov conditional coverage support.
- `scripts/git_snapshot.sh` created with argument validation and usage message.
- 135 tests passing, no regressions.
- Pre-existing ruff lint errors noted in src/agent/prompts.py and tests/test_context/test_injection.py (from earlier stories) — not introduced by this story.

### File List
- `README.md` (created)
- `.env.example` (modified — added inline comments)
- `scripts/run_tests.sh` (created)
- `scripts/git_snapshot.sh` (created)
- `_bmad-output/implementation-artifacts/1-7-repository-documentation-setup-guide.md` (updated)

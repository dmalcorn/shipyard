# Customized BMAD Skills for Automated Pipeline

## Context

Shipyard's orchestrator runs BMAD skills as LangGraph nodes in a fully automated
pipeline with no human operator. Several BMAD skill prompts were written for
interactive use and contain instructions that block on user input. This document
records the analysis and changes made to ensure uninterrupted pipeline execution.

## Skills In Use

The orchestrator invokes three BMAD skills:

| Skill | Used By Node(s) | Original Risk |
|---|---|---|
| `bmad-dev` | `code_review_node`, `fix_ci_node` | **HIGH** — menu + "WAIT for user input" |
| `bmad-dev-story` | `implement_node` | **MEDIUM** — HALT conditions on edge cases |
| `bmad-testarch-atdd` | `write_tests_node` | **LOW** — autonomous mode, no blocking waits |

---

## Analysis

### bmad-dev (HIGH risk)

**File:** `_bmad/bmm/agents/dev.md`

The agent activation sequence includes:
- **Step 12**: Display greeting and numbered menu to the user
- **Step 14**: "STOP and WAIT for user input - do NOT execute menu items automatically"
- **Step 15**: Accept number or text command from user before proceeding

This is designed as an interactive assistant. In the automated pipeline, there is
no human to respond, so the agent will hang until the 25-minute timeout expires
every time it is invoked.

### bmad-dev-story (MEDIUM risk)

**File:** `.claude/skills/bmad-dev-story/workflow.md`

The workflow is designed for continuous execution (`autonomous: true`) but defines
HALT conditions that block on user input:
- No ready-for-dev stories found -> asks user to choose (Step 1)
- New dependencies required beyond story specs -> HALT for approval (Step 5)
- 3 consecutive implementation failures -> HALT for guidance (Step 5)
- Missing configuration -> HALT (Step 5)
- Completion step asks if user needs explanations (Step 10)

These are situational but any one of them will stall the pipeline if triggered.

### bmad-testarch-atdd (LOW risk)

**File:** `.claude/skills/bmad-testarch-atdd/workflow.md`

Explicitly configured with `interactive: false` and `autonomous: true`. Status
confirmations are brief displays followed by automatic progression. No changes
needed.

---

## Changes Made

### 1. `_bmad/bmm/agents/dev.md` — Replaced interactive menu with pipeline mode

**Removed (steps 12-16):**
- Step 12: Show greeting and display numbered menu
- Step 13: Tell user about bmad-help skill
- Step 14: "STOP and WAIT for user input - do NOT execute menu items automatically"
- Step 15: Accept number/text input, fuzzy match, ask for clarification
- Step 16: Process menu item via menu-handlers

**Replaced with (step 12):**
- "PIPELINE MODE: Skip greeting, menu display, and user input. Immediately execute
  the command provided in the prompt. Do NOT wait for user input — this agent is
  invoked programmatically by an automated orchestrator."

### 2. `.claude/skills/bmad-dev-story/workflow.md` — Removed blocking HALTs

**Step 1 — Story discovery (two locations):**

Removed interactive menus that presented 3-4 options and waited for user choice
when no ready-for-dev stories were found (both sprint-based and non-sprint discovery
paths). Replaced with: "PIPELINE MODE: No ready-for-dev story found. Report failure
and exit immediately — do NOT prompt for user input."

**Step 5 — Implementation HALT conditions:**

| Original | Replacement |
|---|---|
| HALT for user approval on new dependencies | Log in Dev Agent Record, proceed with best judgment |
| HALT and request guidance after 3 failures | Log failures, exit with failure status |
| HALT on missing configuration | Log missing config, exit with failure status |

**Step 10 — Completion communication:**

Removed the interactive block that asked the user if they needed explanations about
the implementation, waited for responses, provided tailored explanations, and
suggested next steps. Replaced with: "PIPELINE MODE: Log completion summary in Dev
Agent Record and exit. Do NOT ask the user questions or wait for input."

### 3. `.claude/skills/bmad-dev-story/workflow.md` — Removed story discovery entirely

Step 1 originally contained ~40 lines of story discovery logic that searched
sprint-status.yaml or scanned story files for "ready-for-dev" status. This caused
two problems: (1) stories without the exact status label were skipped, and (2) the
agent made its own decisions about what to work on instead of following strict
orchestrator instructions.

**Removed:** All sprint-based and non-sprint discovery logic, status filtering, and
fallback menus.

**Replaced with:** A simple directive to use exactly the story specified by the
orchestrator via `{{story_path}}` or the command prompt. No searching, no status
checks, no alternatives.

### 4. `bmad-testarch-atdd` — No changes needed

Already configured with `interactive: false` and `autonomous: true`.

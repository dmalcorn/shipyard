# BMAD Skill Setup Guide for Autonomous Pipelines

How to configure BMAD skills so they run unattended in a LangGraph-based build pipeline. This guide uses Shipyard's rebuild pipeline as the reference implementation but applies to any project that invokes BMAD agents programmatically.

## The Problem

BMAD skills are designed for interactive use. They display menus, wait for user input, ask clarifying questions, and halt on edge cases. When you invoke them from an automated pipeline — where there is no human at the keyboard — these interactive behaviors cause the agent to hang until its timeout expires (typically 25 minutes) without doing any useful work.

To use BMAD skills in an automated flow, you need to:

1. Identify which skills your pipeline invokes
2. Find every point where each skill blocks on user input
3. Replace those blocks with autonomous behavior (proceed with best judgment, or exit with a clear error)
4. Ensure the invocation layer prevents interactive input at the subprocess level

## Architecture Overview

Shipyard's rebuild pipeline is a three-level LangGraph hierarchy. Understanding which level invokes which BMAD agent tells you what needs to be modified.

### Level 3 — Story Orchestrator (per-story TDD pipeline)

Defined in `src/multi_agent/orchestrator.py`. This is where most BMAD agents are invoked:

```
create_story → write_tests → implement → run_tests →
code_review → run_ci → git_commit
```

| Pipeline Node | BMAD Skill Invoked | Tool Scope | Timeout |
|---|---|---|---|
| `create_story` | `bmad-create-story` | `TOOLS_SM` (Read, Edit, Write, Glob, Grep, Task, Skill) | 15 min |
| `write_tests` | `bmad-testarch-atdd` | `TOOLS_TEA` (+Bash for npm, pytest, make) | 15 min |
| `implement` | `bmad-dev-story` | `TOOLS_DEV` (+Bash for python, pip, git) | 25 min |
| `code_review` | `bmad-dev` | `TOOLS_CODE_REVIEW` (+Bash for npm, pytest) | 25 min |
| `fix_ci` | `bmad-dev` | `TOOLS_CI_FIX` (+Bash for ruff, mypy) | 25 min |
| `review_tests` | `bmad-qa` | `TOOLS_TEA` | 25 min |
| `fix_review` | `bmad-qa` | `TOOLS_TEA_FIX` (+Bash for python) | 25 min |

Bash-only nodes (`run_tests`, `run_ci`, `git_commit`) do not invoke any BMAD agent.

### Level 2 — Epic Graph (post-epic processing)

Defined in `src/intake/epic_graph.py`. After all stories in an epic complete, runs:

| Pipeline Phase | Agent | Tool Scope |
|---|---|---|
| Epic review (parallel) | `bmad-code-review` | `TOOLS_REVIEW_READONLY` (Read, Glob, Grep only) |
| Epic review (parallel) | Plain Claude CLI | `TOOLS_REVIEW_READONLY` |
| Analysis & categorization | Plain Claude CLI | Read, Write, Glob, Grep |
| Category A fixes | Plain Claude CLI | `TOOLS_DEV` |
| Category B architect review | Plain Claude CLI (Opus) | Read, Write, Edit, Glob, Grep |
| Epic fix cycle | Plain Claude CLI | `TOOLS_DEV` |

The epic-level processing mostly uses plain Claude CLI invocations (not BMAD skills), so it requires fewer customizations.

### Level 1 — Rebuild Graph (epic loop)

Defined in `src/intake/rebuild_graph.py`. Iterates through epics, handles pause/resume. No direct BMAD agent invocations.

## Skills That Need Modification

### 1. `bmad-dev` — HIGH risk (will hang every time)

**File:** `_bmad/bmm/agents/dev.md`

This is the developer agent persona. It is invoked for code review and CI fix tasks. The default activation sequence includes:

- **Step 12:** Display a greeting and numbered menu to the user
- **Step 14:** "STOP and WAIT for user input — do NOT execute menu items automatically"
- **Step 15:** Accept a number or text command from the user before proceeding

In the pipeline, there is no human to respond. The agent will sit idle until the 25-minute timeout.

**What to change:**

Replace steps 12-16 (the menu display, wait, and input processing) with a single step:

```xml
<step n="12">PIPELINE MODE: Skip greeting, menu display, and user input.
  Immediately execute the command provided in the prompt. Do NOT wait
  for user input — this agent is invoked programmatically by an
  automated orchestrator.</step>
```

Leave all other steps intact — the persona, principles, and execution rules (steps 1-11) are still valuable for guiding agent behavior.

### 2. `bmad-dev-story` — MEDIUM risk (will hang on edge cases)

**File:** `.claude/skills/bmad-dev-story/workflow.md`

This is the main implementation workflow. It is configured with continuous execution (`autonomous: true`) but defines several HALT conditions that block on user input:

**Step 1 — Story discovery:** The default workflow contains ~40 lines of logic to search for "ready-for-dev" stories in sprint-status.yaml or story files. This causes problems because:
- Stories without the exact status label are skipped
- The agent makes its own decisions about what to work on instead of following orchestrator instructions

**What to change (Step 1):** Remove all story discovery logic. Replace with a directive to use the exact story specified by the orchestrator:

```xml
<critical>PIPELINE MODE: Do NOT search for or discover stories. The orchestrator
  specifies exactly which story to develop via {{story_path}} or the command
  prompt. Use that story — no status checks, no filtering, no alternatives.</critical>
```

**Step 5 — Implementation HALT conditions:** Three conditions that block on input:

| Original Behavior | Pipeline Replacement |
|---|---|
| New dependencies needed → HALT for user approval | Log in Dev Agent Record, proceed with best judgment |
| 3 consecutive failures → HALT for user guidance | Log failures in Dev Agent Record, exit with failure status |
| Missing configuration → HALT for user input | Log missing config, exit with failure status |

Example replacement:

```xml
<action if="new dependencies required beyond story specifications">PIPELINE MODE:
  Log the dependency requirement in Dev Agent Record and proceed with best
  judgment — do NOT wait for user approval.</action>
<action if="3 consecutive implementation failures occur">PIPELINE MODE:
  Log failures in Dev Agent Record and exit with failure status — do NOT
  wait for user guidance.</action>
<action if="required configuration is missing">PIPELINE MODE:
  Log missing configuration in Dev Agent Record and exit with failure
  status — do NOT wait for user input.</action>
```

**Step 10 — Completion communication:** The default asks the user if they need explanations, waits for responses, and suggests next steps.

**What to change (Step 10):** Replace with:

```xml
<action>PIPELINE MODE: Log completion summary in Dev Agent Record and exit.
  Do NOT ask the user questions or wait for input.</action>
```

### 3. `bmad-testarch-atdd` — LOW risk (no changes needed)

**File:** `.claude/skills/bmad-testarch-atdd/workflow.md`

Already configured with `interactive: false` and `autonomous: true`. Status confirmations are brief displays followed by automatic progression. No modifications required.

### 4. `bmad-create-story` — LOW risk (no changes needed)

Invoked with a direct command ("create story {task_id}"). The skill generates a story spec file from the epic description without interactive prompts.

### 5. `bmad-qa` — LOW risk (no changes needed)

Used for test review and fix. Invoked with a direct command and scoped tools. No interactive menus in the standard flow.

### 6. `bmad-code-review` — LOW risk (no changes needed)

Used at the epic level with read-only tools. The review skill produces a markdown report without user interaction.

## The Invocation Layer

The modifications above handle the skill side. The invocation layer (`src/multi_agent/bmad_invoke.py`) adds three additional safeguards:

### 1. Prompt Wrapper

Every BMAD agent invocation is wrapped in a prompt that forces immediate execution:

```
IMMEDIATE ACTION REQUIRED - YOUR VERY FIRST ACTION MUST BE TO INVOKE THE BMAD AGENT.

Step 1: Use the Skill tool to invoke '{bmad_agent}'
Step 2: Execute command: {agent_command}
Step 3: After completing your work, end your response with this AGENT IDENTIFICATION block:
  === AGENT IDENTIFICATION ===
  Agent: [Your agent type]
  Persona: [Your persona name]
  Loaded files: [list]
  === END IDENTIFICATION ===

Mode: Automated, no menus, no questions, always fix issues automatically, no waiting for user input.
```

The "Mode: Automated" line at the end reinforces the pipeline behavior even if the skill's own PIPELINE MODE directives are somehow missed.

### 2. stdin=DEVNULL

The subprocess call uses `stdin=subprocess.DEVNULL`, which makes it physically impossible for the agent to receive interactive input. If the agent tries to wait for input, it gets an immediate EOF.

### 3. Tool Scoping

Each phase gets only the tools it needs. This is configured via `--allowedTools` on the Claude CLI invocation:

```python
TOOLS_SM = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Skill"
TOOLS_DEV = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pip *),Bash(npm *),Bash(npx *),Bash(pytest *),Bash(make *),Bash(git *),Skill"
TOOLS_CODE_REVIEW = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(npm *),Bash(npx *),Bash(pytest *),Bash(make *),Skill"
TOOLS_CI_FIX = "Read,Edit,Write,Glob,Grep,Task,TodoWrite,Bash(python *),Bash(pip *),Bash(npm *),Bash(npx *),Bash(pytest *),Bash(ruff *),Bash(mypy *),Skill"
TOOLS_REVIEW_READONLY = "Read,Glob,Grep,Task,TodoWrite"
```

Review agents cannot modify code. Dev agents cannot run arbitrary bash commands — only whitelisted tools. This prevents agents from doing unexpected things even in autonomous mode.

## Step-by-Step Setup Checklist

Use this checklist when adding BMAD skills to a new automated pipeline.

### 1. Identify your pipeline's agents

Map each pipeline node to the BMAD skill it invokes. For each skill, note:
- The skill file path (agent definition or workflow file)
- Whether it is invoked interactively or with a direct command
- What tools it needs access to

### 2. Audit each skill for blocking behaviors

Search each skill file for these patterns:
- **"WAIT"** or **"STOP"** — explicit waits for user input
- **"menu"** or **"display"** — interactive menus
- **"HALT"** — edge case halts that ask for guidance
- **"ask"** or **"clarify"** — questions directed at the user
- **"user input"** or **"user choice"** — any user interaction
- **Step completion prompts** — "would you like me to explain?" or "what would you like to do next?"

### 3. Classify each blocking point

For each blocking behavior found:

| Classification | Action |
|---|---|
| **Menu/greeting** | Remove entirely — replace with "immediately execute the command" |
| **Story/task discovery** | Remove — the orchestrator specifies exactly what to work on |
| **Approval gate** | Replace with "proceed with best judgment, log the decision" |
| **Failure halt** | Replace with "log the failure and exit with error status" |
| **Completion prompt** | Replace with "log summary and exit" |

### 4. Add PIPELINE MODE directives

For each replacement, use the phrase "PIPELINE MODE:" as a prefix. This makes it easy to search for all pipeline customizations later and clearly signals to the LLM that this behavior overrides the default interactive mode.

### 5. Configure the invocation layer

Ensure your invocation code:
- Uses `stdin=DEVNULL` (or equivalent) to prevent interactive input
- Wraps the prompt with an "automated, no menus, no questions" directive
- Scopes tools to the minimum required for each phase
- Sets appropriate timeouts per agent type

### 6. Test each agent in isolation

Before running the full pipeline, test each modified agent individually:

```bash
claude --print --verbose --allowedTools "Read,Edit,Write,Glob,Grep" \
  -- "Use the Skill tool to invoke 'bmad-dev-story'. Execute command: develop story 1-1. Mode: Automated."
```

Verify that:
- The agent starts immediately without displaying a menu
- It does not wait for input at any point
- It completes or exits with an error within the expected timeout
- The AGENT IDENTIFICATION block appears in the output

### 7. Run the full pipeline

Start with a single story to verify end-to-end flow before running the full backlog.

## File Reference

| File | Purpose | Customized? |
|---|---|---|
| `_bmad/bmm/agents/dev.md` | Dev agent persona + activation | Yes — step 12 replaced with PIPELINE MODE |
| `.claude/skills/bmad-dev-story/workflow.md` | Story implementation workflow | Yes — steps 1, 5, 10 modified for autonomous execution |
| `.claude/skills/bmad-testarch-atdd/workflow.md` | Acceptance test generation | No — already autonomous |
| `.claude/skills/bmad-create-story/` | Story spec generation | No — direct command, no interactive prompts |
| `.claude/skills/bmad-qa/` | Test review + fix | No — direct command, no interactive prompts |
| `.claude/skills/bmad-code-review/` | Code review | No — direct command, read-only tools |
| `src/multi_agent/bmad_invoke.py` | Invocation layer (prompt wrapping, tool scoping, stdin) | N/A — this is the pipeline infrastructure |
| `src/multi_agent/orchestrator.py` | Per-story pipeline graph (Level 3) | N/A — defines which agents run at each node |
| `src/intake/epic_graph.py` | Epic-level review + fix graph (Level 2) | N/A — uses plain Claude CLI for most post-processing |

## Troubleshooting

**Agent hangs and times out after 25 minutes:**
The agent is waiting for user input. Search the skill file for WAIT, STOP, HALT, menu, or ask patterns that were not converted to PIPELINE MODE.

**Agent skips the story and does something else:**
The story discovery logic is still active. Ensure Step 1 of bmad-dev-story uses only the orchestrator-provided story path, not its own discovery logic.

**Agent displays a menu in the output but continues:**
The PIPELINE MODE directive in the agent file (dev.md step 12) may not have been applied. Also verify the prompt wrapper includes "Mode: Automated, no menus, no questions."

**Agent exits immediately with no work done:**
Check the tool scope. The agent may be missing a tool it needs (e.g., Bash for running tests). Review the TOOLS_ constants in bmad_invoke.py.

**Agent creates files outside the target directory:**
Tool scoping should prevent this, but verify that `working_dir` is being passed through correctly and that scoped tools are being used for rebuild mode.

# Orchestrator Redesign Rationale

## The Problem

The LangGraph orchestrator pipeline processes every story through a fixed sequence of 6 LLM agent calls plus retry cycles:

| Node | Type | Purpose |
|------|------|---------|
| `test_agent` | LLM | Write failing tests (TDD red phase) |
| `dev_agent` | LLM | Implement code to pass tests (TDD green phase) |
| `review_node` x2 | LLM | Parallel code review from two perspectives |
| `architect_node` | LLM | Evaluate review findings, produce fix plan |
| `fix_dev_node` | LLM | Execute approved fixes |

The bash-based nodes (unit tests, CI, git snapshot, system tests) are already efficient — they run shell commands with no LLM invocation. The waste is entirely in the LLM layer.

In testing with a simple hello-world project (2 epics, 3 stories), the first dev agent produced correct, passing code on the first attempt. The pipeline then spent 25+ additional minutes running review agents, an architect agent, and a fix agent — all of which found nothing meaningful to change. Every story paid the full cost of 6 LLM calls regardless of whether the code needed attention.

## The Prior Art: A Bash Script That Got It Right

Before the LangGraph rewrite, a working software factory existed as a bash script invoking the Claude CLI. That script followed a fundamentally better pattern:

**Bash-first, LLM-only-on-failure.** The script handled all mechanical work (running tests, checking CI, committing code) itself. It only invoked an LLM agent when something went wrong — a test failed, a review found issues. The happy path was almost entirely bash, and the LLM was a fallback for judgment calls, not the driver of every step.

**Battle-tested BMAD agents instead of raw prompts.** When the script did need an LLM, it invoked well-configured BMAD agents that already knew their workflows, file conventions, and output formats. A code review was as simple as "run code review on story 2-3" — the agent took it from there. No elaborate prompt construction, no format templates, no manual file listing.

## What the LangGraph Rewrite Lost

The rewrite preserved the process steps but lost both efficiencies:

1. **Unconditional LLM invocation.** Every node always fires. The review/architect/fix pipeline has no conditional entry — it runs even when tests and CI passed on the first attempt with zero issues.

2. **Replaced proven agents with raw prompts.** The orchestrator constructs elaborate prompt strings with format templates, manually lists files, and specifies YAML frontmatter structure in nodes like `review_node` and `architect_node`. This reinvents what the BMAD agents already know how to do — and does it worse, because those agents have been refined through use while these inline prompts were written once.

## The Redesign Approach

Keep LangGraph for what it does well — graph structure, checkpointing, state management, conditional routing, and parallel fan-out. But make the nodes work like the original bash script:

### Principle 1: Bash First, LLM on Failure

Mechanical tasks (run tests, run CI, commit, push) stay as bash nodes. The key change is **conditional routing into LLM nodes**. After each bash check, the graph evaluates: did it pass? If yes, proceed to the next step. If no, route to the appropriate LLM agent to diagnose and fix.

This means the happy path for a well-implemented story is:
```
test_agent -> dev_agent -> [run tests: pass] -> [run CI: pass] -> [commit] ->
[run review: no critical findings] -> [system test: pass] -> [push]
```

Only 2 LLM calls (test_agent + dev_agent) instead of 6.

### Principle 2: Invoke BMAD Agents, Don't Reinvent Them

When the graph does need an LLM, invoke the existing BMAD agents rather than constructing prompts inline. The orchestrator becomes a **coordinator** — it decides *when* to call an agent and *which* agent to call, but delegates the *how* to agents that already know their job.

This simplifies node implementations from 30-line prompt constructions to clean agent invocations, and leverages agents that have been tested and refined rather than one-off prompt strings.

### Principle 3: Keep Every Process Step

No nodes are removed. The review, architect, and fix steps remain in the graph because they represent genuinely valuable quality gates. The change is making them **conditional** — they fire when there's something to act on, and short-circuit when there isn't.

## Why LangGraph Still Earns Its Place

With these changes, LangGraph provides value that a pure bash script cannot:

- **Checkpointing**: Resume a multi-epic rebuild after a crash or timeout without re-running completed stories
- **State management**: Track retry counts, test outputs, file modifications, and error logs across the pipeline
- **Conditional routing**: The graph structure makes the bash-first/LLM-on-failure pattern explicit and debuggable
- **Parallel fan-out**: The Send API enables parallel review agents when reviews do fire
- **Visualization**: The graph can be rendered to understand and explain the pipeline flow

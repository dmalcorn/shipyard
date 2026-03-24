# AI Cost Analysis

## Overview

This document provides a cost analysis for the Shipyard multi-agent coding system, covering actual development spend and production scaling projections. All figures use Anthropic's published API pricing as of March 2026.

**Development period:** 2026-03-23 to 2026-03-24 (2 days)
**Codebase:** 27 source files (4,187 lines), 27 test files (4,655 lines) — 8,842 total lines

---

## 1. Development Cost

### Data Source Findings

| Source | Result |
|---|---|
| LangSmith project `shipyard` | 0 LLM runs; only tool-type traces from pytest |
| Audit logs (`logs/session-*.md`) | 49 session files, all trivial test stubs ("hello", "do stuff") |
| Direct Anthropic API usage | No LLM invocations recorded through Shipyard's agent loop |

**Why zero Shipyard agent API spend:** Shipyard was developed using Claude Code (Anthropic's CLI tool), not by running Shipyard's own agent loop against the Anthropic API. The agent's LangSmith traces contain only tool invocations from unit/integration tests — no actual Claude model calls. The audit logs confirm this: every session completed with "0 agents, 0 scripts, 0 files touched."

### Shipyard Agent API Spend: $0.00

The Shipyard agent made **zero LLM API calls** during the development period. All 49 session logs are test stubs. The LangSmith project contains tool traces only (from pytest runs), with 0 prompt tokens, 0 completion tokens, and $0.00 total cost.

### Development Tooling Cost (Claude Code)

Shipyard was built using Claude Code (Opus 4.6). This cost is external to Shipyard's own API usage but represents the actual development investment:

| Model | Est. Interactions | Avg Input Tokens | Avg Output Tokens | Input Cost | Output Cost | Total |
|---|---|---|---|---|---|---|
| Claude Opus 4.6 | ~250 | 15,000 | 4,000 | $56.25 | $75.00 | $131.25 |

**Estimation basis:** 8 commits across 4 epics over 2 days, producing 8,842 lines of code and test coverage. Estimated 250 Claude Code interactions (prompts + code generation + review cycles). Token estimates reflect typical Claude Code session patterns: ~15K input tokens per prompt (system context + file contents + user instruction) and ~4K output tokens per response (code + explanation).

| Metric | Value |
|---|---|
| Total estimated interactions | ~250 |
| Total estimated input tokens | ~3.75M |
| Total estimated output tokens | ~1.0M |
| Estimated development tooling cost | ~$131.25 |
| Cost per line of code | ~$0.015 |
| Cost per commit | ~$16.41 |

### Anthropic API Pricing (March 2026)

| Model Tier | Input (per MTok) | Output (per MTok) |
|---|---|---|
| Claude Haiku 4.5 | $0.80 | $4.00 |
| Claude Sonnet 4.6 | $3.00 | $15.00 |
| Claude Opus 4.6 | $15.00 | $75.00 |

---

## 2. Production Scaling Assumptions

### Model Routing Baseline

Shipyard routes agents to model tiers as configured in `src/multi_agent/roles.py`:

| Agent Role | Model Tier | Usage Pattern |
|---|---|---|
| Dev | Sonnet | Code implementation, file edits |
| Test | Sonnet | Test generation, test execution |
| Reviewer | Sonnet | Code review, finding analysis |
| Architect | Opus | Architecture decisions, fix plans |
| Fix Dev | Sonnet | Applying review fixes |

**Production model distribution:** ~80% Sonnet, ~5% Opus, ~15% Haiku (if read/search operations are routed to Haiku in a future optimization).

### Per-Instruction Token Estimates

A single user instruction (e.g., "fix the login bug") triggers a multi-agent workflow. Estimated tokens per workflow:

| Agent Phase | LLM Calls | Avg Input Tokens | Avg Output Tokens | Probability |
|---|---|---|---|---|
| Dev agent | 5 | 30,000 | 3,000 | 100% |
| Test agent | 3 | 30,000 | 3,000 | 100% |
| Reviewer | 3 | 30,000 | 3,000 | 100% |
| Fix Dev (rework) | 3 | 30,000 | 3,000 | 50% |
| Architect (escalation) | 1 | 40,000 | 5,000 | 20% |

**Derivation of token estimates:**
- **30K input tokens per call:** System prompt (~2K) + coding standards injection (~1.5K) + file contents read by tools (~20K) + conversation history (~6.5K)
- **3K output tokens per call:** Code generation or analysis response
- **40K input for Architect:** Larger context window needed for architecture-level decisions
- **Probability weights:** Fix Dev triggers ~50% of the time (when reviewer finds issues); Architect escalation occurs ~20% (complex decisions only)

### Weighted Average Per Instruction

| Model | Weighted Input Tokens | Weighted Output Tokens |
|---|---|---|
| Sonnet | 375,000 | 37,500 |
| Opus | 8,000 | 1,000 |
| **Total** | **383,000** | **38,500** |

### Cost Per Instruction

| Model | Input Cost | Output Cost | Subtotal |
|---|---|---|---|
| Sonnet | $1.125 | $0.563 | $1.688 |
| Opus | $0.120 | $0.075 | $0.195 |
| **Total** | **$1.245** | **$0.638** | **$1.883** |

### Usage Assumptions

| Parameter | Value | Rationale |
|---|---|---|
| Instructions per user per day | 10 | Moderate usage: developer issuing 10 multi-agent coding tasks per workday |
| Working days per month | 22 | Standard business month |
| Average tokens per instruction | 383K input + 38.5K output | Derived from agent workflow analysis above |
| Cost per instruction | $1.88 | Sum of Sonnet + Opus weighted costs |

---

## 3. Production Cost Projections

### Monthly Cost by Scale

| Scale | Monthly Instructions | Monthly Input Tokens | Monthly Output Tokens | Monthly Cost | Cost/User/Month |
|---|---|---|---|---|---|
| 100 users | 22,000 | 8.43B | 847M | **$41,426** | $414.26 |
| 1,000 users | 220,000 | 84.3B | 8.47B | **$414,260** | $414.26 |
| 10,000 users | 2,200,000 | 843B | 84.7B | **$4,142,600** | $414.26 |

### Cost Breakdown by Model Tier

| Scale | Sonnet Cost | Opus Cost | Sonnet % | Opus % |
|---|---|---|---|---|
| 100 users | $37,136 | $4,290 | 89.6% | 10.4% |
| 1,000 users | $371,360 | $42,900 | 89.6% | 10.4% |
| 10,000 users | $3,713,600 | $429,000 | 89.6% | 10.4% |

### Cost Per User Per Month: $414.26

At 10 instructions/day and 22 working days/month, each user generates ~220 multi-agent workflows per month. The cost scales linearly — no volume discounts apply to Anthropic API pricing at this time.

---

## 4. Analysis and Recommendations

### Model Routing Effectiveness

Current routing sends 80% of calls to Sonnet and 20% to Opus (by probability-weighted invocation). If all calls used Sonnet instead:

| Scenario | Cost Per Instruction | Monthly Cost (100 users) |
|---|---|---|
| **Current routing** (Sonnet + Opus) | $1.883 | $41,426 |
| **All Sonnet** (no Opus) | $1.688 | $37,136 |
| **Haiku-optimized** (40% Haiku, 40% Sonnet, 20% Opus) | $1.320 | $29,040 |

**Model routing savings:** The current Architect→Opus routing adds ~$0.195/instruction (10.4% overhead). This is justified if Opus produces measurably better architecture decisions. If quality parity is acceptable with Sonnet, eliminating Opus saves ~$4,290/month at 100 users.

**Haiku optimization opportunity:** Routing read-heavy operations (file reads, searches, list operations) to Haiku 4.5 could reduce costs by ~30%. Estimated 40% of agent LLM calls are context-gathering that Haiku can handle. This would save ~$12,386/month at 100 users.

### Token Efficiency

| Metric | Value |
|---|---|
| Input-to-output ratio | 10:1 |
| Input cost share | 66% of total |
| Output cost share | 34% of total |

The 10:1 input-to-output ratio indicates most cost comes from context injection (system prompts, file contents, conversation history), not from generated code. **Reducing context window size is the highest-leverage cost optimization.**

Potential optimizations:
- **Context pruning:** Only inject files relevant to the current task, not the full codebase context. Could reduce input tokens by 30-50%.
- **Conversation summarization:** Compress multi-turn history instead of passing raw messages. Could reduce input tokens by 20-30%.
- **Caching:** Anthropic's prompt caching can reduce repeat context costs by up to 90% for cached prefixes. System prompts and coding standards are prime caching candidates.

### With Prompt Caching (Estimated)

Anthropic prompt caching charges 10% of base input price for cache hits. If 60% of input tokens are cacheable (system prompts, coding standards, stable file contents):

| Scale | Without Caching | With Caching (60% hit rate) | Savings |
|---|---|---|---|
| 100 users | $41,426 | $24,028 | 42% |
| 1,000 users | $414,260 | $240,280 | 42% |
| 10,000 users | $4,142,600 | $2,402,800 | 42% |

### Break-Even Analysis

| Metric | Value |
|---|---|
| Cost per user per month (current) | $414.26 |
| Cost per user per month (Haiku-optimized + caching) | ~$145 |
| Junior developer salary (monthly, US) | ~$6,000-$8,000 |
| Senior developer salary (monthly, US) | ~$10,000-$15,000 |

**Break-even point:** If Shipyard handles tasks that would otherwise require 30-60 minutes of developer time each, and a developer costs ~$60-$90/hour, then 10 instructions/day saving 30 minutes each = 5 hours/day of developer time saved = ~$300-$450/day or ~$6,600-$9,900/month. At the optimized cost of ~$145/user/month, Shipyard would cost **2-3% of the developer time it replaces**.

Even at the unoptimized cost of $414/user/month, the agent costs **4-6% of equivalent developer time** — a strong return if task completion quality is acceptable.

### Recommendations

1. **Implement prompt caching immediately.** System prompts and coding standards are identical across calls — caching them alone could save 30-40% on input costs.
2. **Route read operations to Haiku.** File reads, searches, and list operations don't require Sonnet-level reasoning. Haiku at $0.80/MTok input vs Sonnet at $3.00/MTok is a 73% reduction for these calls.
3. **Evaluate Opus necessity.** The Architect role uses Opus ($15/$75 per MTok) for 20% of workflows. Benchmark Sonnet on architecture decisions — if quality is comparable, eliminate Opus to save 10% overall.
4. **Optimize context injection.** The 10:1 input-to-output ratio means context is the dominant cost driver. Implement smart context selection (only load files referenced in the task) rather than broad codebase injection.
5. **Monitor token usage in production.** LangSmith tracing (Story 2.1) captures model tier metadata per trace. Use this to validate these projections against real usage patterns and adjust routing accordingly.

---

## 5. Summary

| Category | Value |
|---|---|
| **Actual Shipyard agent API spend** | $0.00 (no LLM calls during development) |
| **Estimated Claude Code development cost** | ~$131.25 |
| **Cost per production instruction** | $1.88 (current) / $1.32 (Haiku-optimized) |
| **Cost per user per month (10 instr/day)** | $414.26 (current) / ~$145 (fully optimized) |
| **Monthly cost at 100 users** | $41,426 (current) / ~$14,500 (fully optimized) |
| **Monthly cost at 1,000 users** | $414,260 (current) / ~$145,000 (fully optimized) |
| **Monthly cost at 10,000 users** | $4,142,600 (current) / ~$1,450,000 (fully optimized) |
| **Break-even vs developer** | 2-6% of equivalent developer cost |

**Bottom line:** Shipyard's multi-agent architecture is token-intensive ($1.88/instruction) due to context injection across multiple agent roles. However, with prompt caching and Haiku routing, costs can be reduced by ~65% to ~$0.66/instruction. At any scale, the agent costs a small fraction of the developer time it replaces — making it economically viable if task completion quality meets production standards.

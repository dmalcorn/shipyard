# Story 5.2: AI Cost Analysis

Status: ready-for-dev

## Story

As an evaluator,
I want a cost analysis with actual development spend and production projections,
so that I can assess the economic viability of the agent at scale.

## Acceptance Criteria

1. **Given** development is complete **When** the cost analysis is written **Then** it includes: Claude API input/output token costs, total invocations during development, total development spend
2. **Given** production scaling assumptions **When** projections are calculated **Then** it includes monthly cost estimates for 100, 1,000, and 10,000 users **And** assumptions are documented: average invocations per user per day, average tokens per invocation, cost per invocation

## Tasks / Subtasks

- [ ] Task 1: Gather actual development cost data (AC: #1)
  - [ ] Query LangSmith project for total token usage across all traces:
    - Total input tokens (by model tier: Haiku, Sonnet, Opus)
    - Total output tokens (by model tier)
    - Total LLM invocations count
  - [ ] If LangSmith API is unavailable, extract from audit logs (`logs/session-*.md`) — session logs record model used per agent call
  - [ ] Look up current Anthropic API pricing for each model tier:
    - Claude Haiku 4.5: input/output token rates
    - Claude Sonnet 4.6: input/output token rates
    - Claude Opus 4.6: input/output token rates
  - [ ] Calculate total development spend = sum of (tokens × rate) for each model tier
- [ ] Task 2: Write Development Cost section (AC: #1)
  - [ ] Table: Model tier | Input tokens | Output tokens | Input cost | Output cost | Total cost
  - [ ] Total invocations count (broken down by agent role if possible)
  - [ ] Total development spend (sum of all model costs)
  - [ ] Note the development period (start date to end date)
  - [ ] Optional: cost per epic, cost per story (if traceable from audit logs)
- [ ] Task 3: Define production scaling assumptions (AC: #2)
  - [ ] Average invocations per user per day — estimate based on typical developer workflow (e.g., 5-20 instructions per day)
  - [ ] Average tokens per invocation — derive from actual development data (total tokens / total invocations)
  - [ ] Model tier distribution — what % of invocations hit Haiku vs Sonnet vs Opus in production
  - [ ] Document each assumption with rationale — evaluators will scrutinize unsupported numbers
- [ ] Task 4: Calculate production projections (AC: #2)
  - [ ] Monthly cost formula: `users × invocations/day × 30 × avg_tokens × cost_per_token`
  - [ ] Calculate for 100 users, 1,000 users, 10,000 users
  - [ ] Present as a table: Scale | Monthly invocations | Monthly tokens | Monthly cost
  - [ ] Include cost per user per month at each scale
  - [ ] Note any economies of scale or volume discounts that might apply
- [ ] Task 5: Write analysis and recommendations (AC: #1, #2)
  - [ ] Cost optimization opportunities: model routing effectiveness (how much did Haiku save vs using Sonnet for everything?)
  - [ ] Token efficiency: average tokens per successful edit vs failed edit (retries are expensive)
  - [ ] Break-even analysis: at what usage level does the agent cost less than a developer?
  - [ ] Recommendations for production cost management
- [ ] Task 6: Assemble the final document (AC: #1, #2)
  - [ ] Output file: `docs/cost-analysis.md`
  - [ ] Ensure all required elements are present: dev spend, invocations, projections for 3 scales, assumptions
  - [ ] This content also feeds into CODEAGENT.md (Story 5.4)

## Dev Notes

- **This is a data-gathering and writing story, not a code story.** The dev agent uses `read_file` to collect data from audit logs and LangSmith, performs calculations, and writes a markdown document.
- **LangSmith is the primary data source.** The project traces every LLM call with model tier metadata (Story 2.1). The LangSmith UI or API can aggregate total tokens by model. If API access isn't available, fall back to parsing audit logs.
- **Model routing is a key insight.** NFR5 specifies Haiku for reads/search, Sonnet for coding/review, Opus for Architect decisions. The cost analysis should show this routing saved money — compare actual spend to a hypothetical "Sonnet for everything" scenario.
- **Be honest about costs.** If the agent is expensive, say so. The evaluator values honest analysis over spin. The Trade-off Analysis in Story 5.1 also touches on cost vs value.
- **Anthropic API pricing** — use current published rates. As of the project date:
  - Haiku 4.5: $0.80/MTok input, $4/MTok output
  - Sonnet 4.6: $3/MTok input, $15/MTok output
  - Opus 4.6: $15/MTok input, $75/MTok output
  - Verify these are current before using — check https://docs.anthropic.com/en/docs/about-claude/pricing
- **Output location:** `docs/cost-analysis.md` — deliverable document. Also embedded in CODEAGENT.md (Story 5.4).

### Dependencies

- **Requires:** Story 2.1 (LangSmith Tracing) — traces provide token usage data
- **Requires:** Story 2.2 (Markdown Audit Logger) — fallback data source for token counts
- **Requires:** All prior epics — need complete development history for actual spend
- **Feeds into:** Story 5.4 (CODEAGENT.md Final Sections) — cost analysis embedded in CODEAGENT.md

### Previous Story Intelligence

- Story 2.1 configured LangSmith tracing with metadata: `agent_role`, `task_id`, `model_tier`, `phase`. The `model_tier` tag enables filtering traces by Haiku/Sonnet/Opus for cost attribution.
- Story 2.2's `AuditLogger` records model used per agent call in session logs. Format: agent role, model used, tool name, file path, SUCCESS/ERROR result. Parse these as a fallback for token attribution.
- The `AGENT_CONFIGS` in `src/multi_agent/roles.py` maps each role to a model tier: Dev→Sonnet, Test→Sonnet, Review→Sonnet, Architect→Opus, Fix Dev→Sonnet. This is the production model routing baseline.

### Project Structure Notes

- Output: `docs/cost-analysis.md`
- Source data: LangSmith project traces, `logs/session-*.md`
- Referenced by CODEAGENT.md in Story 5.4

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 5.2 — acceptance criteria]
- [Source: _bmad-output/planning-artifacts/epics.md#FR11 — AI Cost Analysis requirement]
- [Source: _bmad-output/planning-artifacts/epics.md#NFR5 — Token cost awareness and model routing]
- [Source: _bmad-output/implementation-artifacts/2-1-langsmith-tracing-custom-metadata.md — tracing metadata for cost attribution]
- [Source: _bmad-output/implementation-artifacts/2-2-markdown-audit-logger.md — audit log format with model info]
- [Source: _bmad-output/project-context.md#Model Routing — Haiku/Sonnet/Opus tier assignments]
- [Source: CODEAGENT.md#Cost Analysis — placeholder section to be filled by Story 5.4]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

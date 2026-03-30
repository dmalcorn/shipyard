# Final Demo Script — Project Shipyard

> Covers what's new since the MVP and early-submit demos. ~3–5 minutes total.
>
> **Already demoed (MVP):** Persistent loop, surgical file editing, context injection, LangSmith traces, PRESEARCH.md, clone-and-run.
>
> **Already demoed (early submit):** Multi-agent coordination, per-story TDD pipeline, CODEAGENT.md MVP sections.
>
> **This demo:** Ship rebuild results, rebuilt product, Command Bridge dashboard, CODEAGENT.md final sections, comparative analysis, cost analysis.

---

## Setup (before recording)

Have browser tabs open to:
- Command Bridge dashboard: `https://shipyard-production-29ae.up.railway.app/`
- ShipRebuild deployed app: `https://shiprebuild-production.up.railway.app/`
- `CODEAGENT.md` in the editor (scrolled to Architecture Decisions section)
- `gauntlet_docs/comparative-analysis.md` in the editor

---

## Demo Flow

### 1. Recap & Transition (~15 sec)

**Say:** "In the MVP demo I showed the core agent — surgical edits, context injection, persistent loop, tracing. In the early submit I showed multi-agent coordination and the TDD pipeline architecture. Since then, I've run the full Ship app rebuild and completed all final deliverables. Let me walk through what happened."

---

### 2. Ship App Rebuild — The Run (~60 sec)

**What to show:** The rebuilt application running live and the pipeline stats.

**Open the deployed ShipRebuild app** in browser: `https://shiprebuild-production.up.railway.app/`

**Say:** "This is what Shipyard built — CMOgfa, a full-stack application. 49,500 lines of Go backend across 156 files, 14,700 lines of React frontend across 136 files, PostgreSQL with 18 migrations and 42 seed documents. All produced autonomously by the pipeline."

**Show the app briefly** — navigate a page or two to prove it's functional.

**Say:** "Here are the numbers: 40 stories completed out of 40. 9 epics out of 9. 28 hours 35 minutes of pipeline time, $495 in API cost, 225 agent invocations, nearly 11,000 agent turns. Zero failed invocations. The only human intervention was a credit card running out — not a code failure."

**Say:** "The pipeline ran in Docker using `Dockerfile.rebuild` with the target project mounted in. Ctrl+C triggers a graceful pause — it saves a checkpoint, and you resume with `--resume`. The cost tracker accumulates spend in real-time across all agent invocations."

---

### 3. Command Bridge — Live Monitoring Dashboard (~45 sec)

**What to show:** The public monitoring dashboard that was built beyond PRD requirements.

**Open Command Bridge:** `https://shipyard-production-29ae.up.railway.app/`

**Say:** "This is the Command Bridge — a public dashboard anyone can use to watch Shipyard builds in real-time or replay any previous run. No login required."

**Walk through the UI:**

- **Pipeline flow graph** — "Each node represents a pipeline stage. During the rebuild, nodes light up as the pipeline progresses — idle, active, completed, or failed. The story label shows which story is being processed."

- **Session dropdown** — Select a previous session. "You can pick any past run and replay its complete log output."

- **Stats bar** — "Completed, failed, interventions, and total story counts with a progress bar."

**Say:** "Under the hood, `web_relay.py` pushes log events from the local Docker container to Railway's Postgres via the log relay. The dashboard connects via SSE for real-time streaming. This was built as a beyond-PRD enhancement for observability."

---

### 4. CODEAGENT.md Final Sections (~30 sec)

**What to show:** The four sections completed since early submit.

**Open `CODEAGENT.md` and scroll through each section:**

**Say:** "CODEAGENT.md now has all eight sections complete. The four new ones since early submit:"

- **Architecture Decisions** — "Six decisions with alternatives considered, rationale, and trade-offs — all about Shipyard the factory, not the rebuilt product."
- **Ship Rebuild Log** — "Run timeline, the intervention log — one entry, credit card exhaustion — and post-run observations about what the agent did well and where it struggled."
- **Comparative Analysis** — "Summarized from the full 366-line comparative analysis doc."
- **Cost Analysis** — "Development costs, rebuild costs, and production projections at 100, 1K, and 10K users."

---

### 5. Comparative Analysis Highlights (~30 sec)

**What to show:** Honest, evidence-backed analysis — the most heavily weighted deliverable.

**Open `gauntlet_docs/comparative-analysis.md` and scroll key sections:**

**Say:** "The PRD says this is the most heavily weighted deliverable, and that honest analysis of a flawed agent scores higher than vague praise. So here's what I found:"

- "The agent-built version has five fundamental architectural differences from the original — it favored convention over configuration, generated more boilerplate, and made different trade-offs on abstraction."
- "Shortcomings are documented with specifics — not 'the agent sometimes struggled,' but exactly which patterns caused issues and what the intervention log reveals."
- "The 'If You Built It Again' section covers what I'd change about the pipeline — not just the agent, but the orchestration, the review cycle, and the context strategy."

---

### 6. Cost Analysis (~15 sec)

**Say:** "Development of Shipyard itself cost roughly $131 in Claude Code tooling — the agent's own API cost was zero because it's built on Claude Code, not direct API calls. The rebuild cost $495.36 for 40 stories in 28 hours. At production scale, running Shipyard for 1,000 users at 10 instructions per day would cost about $414K per month unoptimized, or $145K with caching and model tiering."

---

## Wrap-Up (~15 sec)

**Say:** "Since early submit: the rebuild ran to completion — 40 stories, 9 epics, 64,000 lines of code, zero failures. The Command Bridge gives real-time observability into every run. All eight CODEAGENT.md sections are filled in with substantive content. The comparative analysis is honest and specific. Both Shipyard and the rebuilt app are deployed and live."

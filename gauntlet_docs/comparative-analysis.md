# Comparative Analysis: Ship vs. ShipRebuild

## 1. Executive Summary

Shipyard is a software factory that automates the implementation stage of software development, taking well-prepared planning artifacts and autonomously producing working code through a multi-agent pipeline. We used Shipyard to rebuild Ship — a government-grade project management platform — from scratch, simultaneously migrating the backend from Node.js to Go, overhauling the database from a single-table polymorphic model to a hybrid schema with typed property tables, and redesigning the UX from a unified document page to feature-first modules. The factory completed all 40 stories across 9 epics in 28 hours 35 minutes of pipeline time at a total API cost of $495.36, with zero failed agent invocations. The only intervention was a pause-and-restart caused by prepaid credit card exhaustion — not a pipeline or code failure. The rebuild was surprisingly smooth, and the most valuable outcome was the comprehensive observability built into every step: 34,827 log events capturing every agent action, decision, and result, producing a dataset that can be sliced and analyzed to understand exactly what happened and why.

---

## 2. Architectural Comparison

The agent-built ShipRebuild differs from the original Ship in five fundamental ways. Each represents a deliberate architectural decision documented in the planning artifacts before a single line of code was generated.

### Language Migration: Node.js/Express → Go 1.25.5

The original Ship is a TypeScript monorepo — Express.js backend, React 18 frontend, shared type package, and a LangGraph.js AI agent (FleetGraph) — totaling approximately 22,500 lines of application code across 353 source files. The rebuild replaces the entire backend with Go 1.25.5, producing a single compiled binary (~49,500 lines across 156 files) alongside a React 19 frontend (~14,700 lines across 136 files).

The rationale is rooted in government technology policy. The White House ONCD (February 2024) and CISA/NSA (June 2025) explicitly recommend memory-safe languages. Go is on the approved list alongside Rust, C#, and Java. Federal precedent exists: Cloud.gov (GSA/18F, FedRAMP authorized) and UK GDS infrastructure both run on Go. Beyond policy alignment, Go's single-binary deployment eliminates the deep Node.js dependency tree, producing a simpler security surface and cleaner SBOM for auditors.

A human developer would not have attempted this migration on this timeline. The user was learning Go alongside the AI during the rebuild — Shipyard serves as proof that AI collaboration eliminates language expertise as a bottleneck for adopting government-preferred stacks.

### Schema Philosophy: "Everything is a Document" → "Most Things Are a Document"

Ship's defining architectural principle is "everything is a document." All 10 entity types (wikis, issues, programs, projects, sprints, persons, weekly plans, weekly retros, standups, and weekly reviews) live in a single `documents` table with a `document_type` enum discriminator. Type-specific metadata is stored in an unvalidated JSONB `properties` column. Any document can link to any other through a polymorphic `document_associations` junction table.

This design aimed for maximum flexibility. In practice, 70% of the backend code was already type-specific — extracting properties, validating fields, handling state transitions — while the schema pretended to be unified. Queries required 4–5 JOINs through the polymorphic associations table. Adding a new field meant updating 6+ extraction functions. The frontend had 13+ dispatch points switching on document type.

ShipRebuild adopts a hybrid architecture. A shared `documents` table still owns what is genuinely shared: identity, workspace scoping, content (TipTap editor state), audit metadata, hierarchy (`parent_id`), and timestamps. But type-specific data moves to 10 dedicated property tables (`issue_properties`, `program_properties`, `sprint_properties`, etc.) with real columns, foreign keys, NOT NULL constraints, and proper indexes.

A PostgreSQL trigger (`enforce_document_type()`) on each property table prevents inserting property rows for the wrong document type, catching schema mismatches at the database layer. Queries drop from 4–5 JOINs to 1. The schema honestly reflects how the code is organized.

Three architectural paths were evaluated and documented:
- **Path 1 (Keep pattern, fix implementation):** Polishes the same trade-off; the 70% type-specific code problem persists. Acceptable only under extreme time pressure.
- **Path 2 (Hybrid — chosen):** Shared table for genuinely shared concerns + typed property tables. Balances type safety with the real shared DNA across entity types (workspace scoping, content editing, audit trails).
- **Path 3 (Fully normalized):** Over-engineered. The 10 entity types share enough DNA that full separation creates duplication without proportional benefit.

### Real-Time Collaboration: Yjs CRDT → Deferred Block-Locking

Ship's collaborative editing stack is TipTap + Yjs (CRDTs) with WebSocket synchronization, enabling live cursors and character-level concurrent editing. This architecture requires a Node.js WebSocket sidecar (Hocuspocus), which conflicts with the pure-Go single-binary deployment goal.

Seven collaboration options were evaluated. The rebuild chose TipTap without Yjs for v1 (single-user editing with auto-save), with a planned v2 migration to Go-native block-level locking. When a user edits a section, the Go WebSocket server locks that block for other users with presence indicators.

This is simpler to build, audit, and explain than CRDT conflict resolution. It is also appropriate for the actual usage patterns: government PM workflows are predominantly asynchronous — weekly plans, retros, and standups are submitted by one person and reviewed by another. Simultaneous character-level editing is a rare edge case, not a core workflow.

### UX Redesign: Unified Document Page → Feature-First Views

Ship renders all 10 document types through a single `UnifiedDocumentPage` component with a polymorphic sidebar and property panel. This mirrors the "everything is a document" backend philosophy — and inherits its problems. Users must mentally map different entity types through an identical interface.

ShipRebuild adopts feature-first organization with 11 self-contained feature modules, each owning its own components, hooks, API layer, and types. Navigation is restructured around three principles borrowed from best-in-class PM tools (Linear, Asana, Plane):

1. **Command Palette (Cmd+K):** Universal search across all entity types with fuzzy matching, grouped results, and keyboard shortcut hints. Target response time under 150ms via cross-entity `tsvector` search.
2. **"My Work" Home View:** Personal dashboard aggregating assigned issues, pending approvals, and recent activity across all programs. Eliminates tree navigation for 80% of daily tasks.
3. **Contextual Sidebar:** Shows where you are, not everything that exists. Collapsible, program-scoped, with breadcrumb wayfinding on every page.

The UX was designed around three user personas with specific success moments: Jason (new hire, zero-training onboarding), Marcus (manager, at-a-glance accountability), and Priya (tech lead, fast sprint triage via Kanban). Each persona's workflow was documented with pass/fail criteria before implementation.

### Deployment: AWS Multi-Service → Single Binary on Railway

Ship deploys as three independent services on AWS: API on Elastic Beanstalk, frontend on S3/CloudFront, and FleetGraph on a separate container, all managed with Terraform. Estimated cost: ~$80/month for a dev environment.

ShipRebuild compiles to a single Go binary that serves both the API and static frontend assets. It deploys to Railway with managed PostgreSQL. The deployment surface is dramatically simpler — one container, one database, no CDN configuration, no Terraform.

### What a Human Wouldn't Have Done

A human development team would not have attempted a simultaneous language migration, schema redesign, collaboration model change, and UX overhaul on a one-week timeline. Any one of these changes would typically be a quarter-long initiative with dedicated planning, staffing, and risk review. Combining all four would be a 6–12 month program that most executives would decline to approve due to the cost of failure.

The software factory compressed this risk calculus. The cost of the experiment was approximately one week of effort plus API costs — not months of developer salaries. If the rebuild failed, the original Ship still exists unchanged. This asymmetry — high potential upside, bounded downside — is the kind of bet that AI-assisted development makes newly rational.

---

## 3. Performance Benchmarks

### Codebase Scale Comparison

| Metric | Original Ship | ShipRebuild |
|--------|--------------|-------------|
| Backend language | TypeScript (Node.js/Express) | Go 1.25.5 (stdlib net/http) |
| Backend LOC | ~7,000 | ~49,500 |
| Frontend LOC | ~8,000 (React 18, TSX) | ~14,700 (React 19, TSX) |
| Total source files | 353 | 292 |
| Database migrations | 38 | 18 |
| Database schema tables | 1 core table + polymorphic junction | 1 shared table + 10 typed property tables + junction tables |
| E2E tests | 869 (Playwright) | *Not yet benchmarked* |
| Unit tests | 451 (Vitest) | *Not yet benchmarked* |
| Documentation | ~14,800 lines | Embedded in planning artifacts |

The Go backend is substantially larger in raw line count (~49,500 vs. ~7,000), which reflects Go's verbosity compared to TypeScript — explicit error handling, struct definitions, and the convention of co-locating test files with source. The frontend grew from ~8,000 to ~14,700 lines, a consequence of the feature-first module organization where each of 11 features owns its own components, hooks, API layer, and types rather than sharing a single polymorphic page.

The database tells a cleaner story: 18 migrations vs. 38. The hybrid schema design required fewer incremental adjustments because the architecture was designed up front from the planning artifacts rather than evolving organically over weeks of development.

### Original Ship Runtime Benchmarks (Baseline)

These metrics were captured during the ShipShape benchmarking initiative on the original Ship application:

| Metric | Measurement |
|--------|-------------|
| API P50 response — `/api/documents` | 150ms |
| API P97.5 response — `/api/documents` | 374ms |
| API P50 response — `/api/issues` | 117ms |
| API P97.5 response — `/api/issues` | 282ms |
| API payload size — documents | 278 KB |
| API payload size — issues | 327 KB |
| Frontend bundle (gzip, after optimization) | 249 KB |
| Frontend bundle (gzip, before optimization) | 699 KB |
| Queries per main page load | ~15 |
| Accessibility violations (issues page) | 0 |
| Accessibility violations (projects page) | 1 serious (color contrast) |
| Type safety violations | 875 (`: any`, `as any`, `as Type`, `!`) |

ShipRebuild runtime benchmarks (API response times, bundle size, page load times) have not yet been measured. This is an open task. However, several architectural choices in the rebuild are expected to improve on these baselines: the hybrid schema reduces JOIN depth from 4–5 to 1, Go's compiled performance typically outperforms Node.js for I/O-bound workloads, and the feature-first frontend with lazy route splitting should produce smaller initial bundles.

### Software Factory Performance

The most meaningful benchmark for this project is not runtime performance — it is development velocity. The factory rebuilt the entire application autonomously:

| Metric | Value |
|--------|-------|
| Total stories completed | 40 of 40 |
| Total epics | 9 |
| Pipeline wall-clock time | 28 hours 35 minutes |
| Total elapsed time (including downtime) | ~31.5 hours |
| Total API cost | $495.36 |
| Average cost per story | $12.08 |
| Median story duration | 37 minutes 33 seconds |
| Average story duration | 41 minutes 49 seconds |
| Total agent invocations | 225 |
| Total agent turns | 10,793 |
| Total log events recorded | 34,827 |
| Failed agent invocations | 0 |

The pipeline completed 40 stories across 9 epics with zero failed agent invocations. The only interruption was an external billing constraint (prepaid credit card exhaustion), not a pipeline or code failure.

### Factory Cost Breakdown

| Category | Cost | % of Total |
|----------|------|-----------|
| Implementation (dev-story + dev) | $294.01 | 59.4% |
| Test generation (testarch-atdd) | $92.07 | 18.6% |
| Story spec creation | $48.18 | 9.7% |
| Code review & architecture review | $37.53 | 7.6% |
| Fix agents (category A fixes) | $23.55 | 4.8% |
| **Total** | **$495.36** | **100%** |

Implementation dominates at 59.4% of total spend. The pipeline's multi-agent loop (implement → test → review → fix) converges reliably, with most stories passing CI on the first or second attempt.

### Agent Workload Distribution

| Agent | Invocations | Total Cost | Avg Time/Call |
|-------|-------------|-----------|---------------|
| bmad-dev (fix-up & CI repair) | 53 | $142.59 | 9m 13s |
| bmad-dev-story (implementation) | 44 | $151.42 | 13m 24s |
| bmad-testarch-atdd (test generation) | 42 | $92.07 | 8m 18s |
| bmad-create-story (spec writing) | 41 | $48.18 | 4m 58s |
| fix-cat-a (category A fix agent) | 10 | $23.30 | 6m 28s |
| bmad-code-review | 8 | $15.64 | 4m 42s |
| claude-review | 8 | $12.54 | 5m 04s |
| architect (epic review) | 9 | $4.71 | 2m 24s |
| analyze-reviews | 9 | $4.64 | 3m 06s |

The fix-up agent (bmad-dev) was the most frequently called at 53 invocations, reflecting the iterative fix/verify cycle that makes the pipeline self-correcting. The implementation agent (bmad-dev-story) was the most expensive per call at an average of 13 minutes and $3.44 per story.

### Velocity Comparison

The original Ship was built by a human developer over the course of a multi-week program. ShipRebuild — with a language migration, schema overhaul, and UX redesign — was produced by the factory in under 29 hours of pipeline time at a cost of $495. Even accounting for the planning and preparation time that preceded the factory run, the total project timeline from assignment to working results was under one week.

Later epics cost more per story as the codebase grew: Epic 8 (Accountability Cycle) averaged $16.34/story vs. Epic 1 (Foundation) at $6.93/story. This reflects the increasing context that agents need as the integration surface area expands — a natural scaling characteristic of any development process, human or automated.

### Open Benchmarking Tasks

The following runtime benchmarks on ShipRebuild remain to be captured:
- API response times (P50, P97.5) for key endpoints
- Frontend bundle size (gzip)
- Page load time (LCP)
- Database query count per page load
- Accessibility audit (axe-core)
- Test coverage counts (E2E and unit)

---

## 4. Shortcomings

### Interventions During the Rebuild

The factory required exactly one human intervention during the entire 40-story rebuild. That intervention was not caused by the agent producing incorrect code, failing to pass CI, or getting stuck on a story. It was caused by running out of funds on a prepaid credit card, which terminated the Anthropic API connection mid-pipeline.

**The intervention timeline:**

1. **Run 1** completed 12 stories (Epics 1–2) over 6 hours 48 minutes before the prepaid balance was exhausted.
2. **Downtime (~3 hours):** Rather than simply restarting from the last completed story, approximately 2 hours were spent attempting to improve and test the factory's pause-and-resume feature — modifying the code, testing changes, and iterating with Claude on the implementation. This was a conscious choice to improve the factory rather than just work around the problem, but it consumed time without producing a reliable pause/resume mechanism.
3. **Resolution:** The pragmatic fix was to manually set the pipeline's status file to indicate where to resume, then restart. The pipeline picked up at story 2-7 and ran the remaining 29 stories to completion without further intervention.

**What this reveals about the factory's limitations:**
- The pause/resume capability was not production-ready. It had been coded into the pipeline but not thoroughly tested before the first full run. Under pressure, it was faster to manually edit a status file than to debug the feature.
- If the financial setup had been correct from the start (using a funding source without a hard prepaid cap), the run would have completed end-to-end with zero interventions. The pipeline itself never failed.

### Post-Run Output Quality

The factory produced working code for all 40 stories with zero failed agent invocations and all stories passing CI. However, thorough end-to-end testing of the built application has not yet been completed. Early observations:

- **UI look and feel:** The interface is functional but does not fully match the visual specifications from the UX design phase. The layout, components, and interactions are present, but the styling, spacing, and polish do not yet reflect the detailed design tokens and component specifications that were documented in the planning artifacts. This is expected to be correctable by providing the original UX specifications and example HTML mockups to an agent for a styling pass.
- **Undiscovered bugs:** As with any newly built application, bugs are expected to surface during testing. None have been identified as systemic or architectural — the expectation is that they will be individual issues addressable one at a time.

### CI Coverage Gap

The CI scripts used during the factory run were not comprehensive. They verified that the code compiled and that explicit test suites passed, but they did not catch the full range of issues that a thorough CI pipeline should — linting, type checking across the full codebase, and other static analysis steps were either missing or incomplete. This means the factory's "all stories passing CI" metric overstates the actual code quality: stories passed a bar that was set too low.

This has been addressed in the pipeline itself — future factory runs will use a comprehensive CI configuration that covers the full range of checks. However, the existing ShipRebuild codebase was built against the weaker CI, so a full CI rewrite and repo-wide run is needed to identify and fix issues that were never caught during the original build.

### No Migration Verification Step

The pipeline does not include a step to verify that database migrations run successfully against an actual database. Migrations were generated as SQL files and included in the codebase, but the factory never stood up a PostgreSQL instance to apply them and confirm they execute without errors. Issues like syntax problems, ordering dependencies, or constraint conflicts would not have been caught during the build. A migration verification step — spinning up a database, applying all migrations in sequence, and validating the resulting schema — needs to be added to the pipeline and run against the existing ShipRebuild migrations.

### Patterns and Limitations

**What the factory handled well:**
- CRUD operations across all 10 entity types
- Database schema creation with constraints, triggers, and migrations
- Multi-layer architecture (handler → service → repository)
- Frontend feature modules with hooks, API layers, and components
- CI verification and self-correction via the fix-up loop

**Known areas for improvement:**
- **Visual fidelity:** The factory produces functional UI but does not reliably achieve pixel-level design consistency with mockups. A dedicated styling/polish pass appears to be needed as a post-pipeline step.
- **Pause/resume robustness:** The pipeline's ability to stop and restart mid-run needs hardening. This is an engineering improvement to the factory itself, not a limitation of the agent's coding ability.
- **Performance at scale:** Later stories cost more and took longer as the codebase grew (Epic 8 averaged $16.34/story vs. Epic 1 at $6.93). Strategies to manage growing context — such as more targeted context injection or codebase summarization — could improve efficiency for larger projects.

### What Was Not a Shortcoming

It is worth noting what did *not* go wrong. The factory:
- Never produced code that failed to compile or build
- Never required a story to be abandoned or manually rewritten
- Never hallucinated imports, packages, or APIs
- Never broke previously working functionality (no regressions detected during the run)
- Maintained architectural consistency across all 40 stories despite having no memory between story executions

The pipeline's self-correcting loop (implement → test → review → fix) was effective. The fix-up agent was invoked 53 times across the run, but this is by design — it reflects the iterative convergence process, not failure.

---

## 5. Advances

### Every Line Was Faster

There is no individual story, epic, or task in the rebuild where a human developer would have been faster than the factory. Every line of code, every database migration, every React component, every test — all of it was produced at a pace that no manual development process could match. The factory completed 40 stories across 9 epics in 28 hours 35 minutes of pipeline time. A conservative estimate for manual development of equivalent scope — language migration, schema redesign, UX overhaul, full-stack implementation — would be 6–12 months with a team.

### Reliability on Production Infrastructure

The most pleasant surprise of the rebuild was the pipeline's stability when running on production-grade infrastructure. The factory ran inside a Railway container with more memory and CPU than the local development laptop. Previous attempts at automated pipelines running on Docker Desktop locally had experienced repeated freezes where the LLM would halt mid-execution, requiring significant debugging time to diagnose and work around.

On Railway, the pipeline experienced zero freezes, zero hangs, and zero infrastructure-related failures across both runs (31.5 total elapsed hours). This suggests that prior pipeline reliability issues were environmental — constrained local resources — not fundamental to the approach. The lesson: run the factory on infrastructure that matches production workloads, not on a developer laptop.

### Context Without Memory

The factory's zero-memory-between-stories architecture — where each story executes in an isolated agent context with no carry-over from previous stories — turned out to be a non-issue. This was a deliberate design choice, not a limitation.

Each agent in the pipeline operates from targeted documents specified by its workflow: the story spec, the coding standards, the architecture artifacts, the existing codebase. The agents read exactly what they need from files, not from conversation history. This means:

- No context window bloat from accumulated conversation history
- No risk of early-story decisions polluting later-story reasoning
- Each story gets a clean, focused execution environment
- The pipeline can resume at any story without reconstructing prior context

The fact that 40 stories maintained architectural consistency — handler/service/repository layering, consistent API response formats, shared design tokens — without any agent remembering a previous story demonstrates that well-structured planning artifacts and coding standards are a more reliable coordination mechanism than agent memory.

### Self-Correcting Pipeline

The multi-agent loop (implement → test → review → fix) produced zero failed agent invocations across 225 total invocations. The fix-up agent was called 53 times, but this is the pipeline working as designed — catching issues through CI and code review, then converging to passing code. Most stories passed CI on the first or second attempt.

This self-correction capability means the pipeline does not require a human watching it. Once started, Run 2 executed 29 stories over 21 hours 46 minutes with no human involvement whatsoever. The pipeline managed its own quality gates.

### Predictable Cadence

Story completion times were remarkably consistent. The median story duration (37 minutes 33 seconds) was close to the average (41 minutes 49 seconds), indicating a predictable per-story cadence. Most stories fell in the 25–50 minute range. The outliers — stories 3-5 (1h 50m), 8-6 (1h 23m), and 9-2 (1h 13m) — were all dashboard or reporting features with genuinely higher complexity.

This predictability is itself an advance. Human development timelines are notoriously hard to estimate. The factory produces a cadence that is consistent enough to plan around: given N stories, expect approximately N × 42 minutes of pipeline time and N × $12 of API cost.

### Cost as a Feature

The total cost of the rebuild was $495.36. This is not a labor cost estimate or a projection — it is the actual, auditable spend for producing a working full-stack web application with 40 implemented stories. The cost breakdown is transparent down to the per-agent, per-story level because every invocation was logged.

This cost structure fundamentally changes the risk calculus for ambitious technical decisions. Migrating from Node.js to Go, overhauling a database schema, and redesigning the UX would be a high-risk, high-cost initiative for any organization using traditional development. At $495 and one week, it becomes a low-cost experiment. If it fails, the original application still exists unchanged. If it succeeds, the organization has a modernized codebase aligned with government technology policy.

*[Note: This section will be updated with observations from hands-on testing of the generated code later today.]*

---

## 6. Trade-off Analysis

The rebuild involved five major architecture decisions. Each was made deliberately, documented in planning artifacts before implementation, and evaluated through agent-assisted analysis. The common thread: this was an experiment, and experiments are worth running when the cost of trying is low and the information value is high.

### Decision 1: Go Over Node.js

**The call:** Replace the entire Express.js/TypeScript backend with Go 1.25.5.

**Was it right?** Yes. The agent presented a thorough analysis of the trade-offs between the two languages, and the benefits of Go — memory safety alignment with White House/CISA guidance, single-binary deployment, simpler dependency surface for government auditors — were compelling enough to justify the attempt. More importantly, the decision was not just about this one application. It was about understanding what the process looks like to modernize government software from a legacy stack to a policy-aligned one. That process knowledge is valuable regardless of whether the resulting Go code is perfect on the first pass.

**What would change?** The Go backend is significantly more verbose (~49,500 LOC vs. ~7,000 in TypeScript). Some of this is inherent to Go (explicit error handling, struct definitions), and some is co-located test code. Whether the verbosity is a net positive (readability, auditability) or a net negative (more surface area to maintain) will become clearer with hands-on use.

### Decision 2: Hybrid Schema Over Single-Table Model

**The call:** Move from "everything is a document" (single `documents` table with JSONB properties) to "most things are a document" (shared `documents` table + 10 typed property tables with real columns and constraints).

**Was it right?** Yes. The analysis demonstrated that 70% of the original codebase was already type-specific — the schema was pretending to be unified while the code had long since diverged. The hybrid model makes the database honest about this reality. It also provides concrete benefits: queries drop from 4–5 JOINs to 1, type safety is enforced at the database layer with triggers and constraints, and new fields can be added with a simple column rather than updating 6+ extraction functions.

**What would change?** The proof is in production use. The schema design looks sound on paper and was validated against the 547-document seed dataset during planning, but real-world query patterns, data growth, and edge cases will determine whether the hybrid model delivers on its promise. This will become clearer through testing and use in the coming days.

### Decision 3: Dropping Yjs/CRDT for Single-User Editing

**The call:** Remove real-time collaborative editing (TipTap + Yjs + WebSocket) in v1. Plan for Go-native block-level locking in v2.

**Was it right?** Yes. The analysis evaluated seven collaboration options and concluded that Yjs requires a Node.js sidecar, which conflicts with the pure-Go single-binary goal. More fundamentally, the actual usage patterns in government project management are predominantly asynchronous — weekly plans, retros, and standups are submitted by one person and reviewed by another. Character-level real-time collaboration is a rare edge case.

**What would change?** This is the decision with the most visible user-facing trade-off. If users expect Google Docs-style simultaneous editing, v1 will feel like a step backward. The v2 block-locking plan is simpler and more auditable than CRDT, but it has not been built yet. Whether block-locking proves sufficient or whether full CRDT capability is ultimately needed remains an open question.

### Decision 4: Feature-First Frontend Over Unified Document Page

**The call:** Replace the single `UnifiedDocumentPage` (which renders all 10 document types polymorphically) with 11 self-contained feature modules, each owning its own components, hooks, API layer, and types.

**Was it right?** Yes. The original unified approach mirrored the "everything is a document" backend philosophy and inherited its problems — the UI felt disorienting when navigating between fundamentally different entity types rendered through an identical interface. The feature-first approach gives each entity type its own visual identity and interaction patterns.

**What would change?** The generated UI is functional but does not yet match the detailed visual specifications from the UX design phase. Whether this is a limitation of the feature-first architecture or simply a styling pass that needs to happen is not yet clear. Hands-on testing today will inform this.

### Decision 5: Railway Container Over Local Docker

**The call:** Run the factory pipeline on a Railway-hosted container rather than Docker Desktop on the local laptop.

**Was it right?** Unequivocally yes. Previous attempts at running automated pipelines on Docker Desktop locally had experienced repeated LLM freezes requiring significant debugging. The Railway container — with more memory and CPU than the local machine — experienced zero freezes across 31.5 hours of elapsed time. This was not a planned architecture decision so much as a pragmatic discovery: the factory needs production-grade infrastructure to run reliably.

**What would change?** Nothing. This is the clearest right call of the five. The only consideration is cost — Railway charges for container runtime — but the reliability gain is worth it.

### The Meta-Decision: Experimenting at All

The overarching trade-off was whether to attempt this scope of change (language migration + schema overhaul + UX redesign + collaboration model change) in a single automated run. A traditional development organization would have scoped these as four separate initiatives, each with its own planning, staffing, and risk review.

The software factory made this experiment rational. At $495 and one week, the cost of failure was bounded. The original Ship application still exists unchanged as a fallback. And the information gained — about Go adoption, hybrid schemas, factory reliability, and development velocity — has value regardless of whether every line of generated code is production-ready on day one.

*[Note: Trade-off assessments will be refined after hands-on testing of the generated application.]*

---

## 7. If You Built It Again

### The Agent Architecture Was the Right Foundation

Shipyard's agent architecture is built on three pillars: predefined document sources, structured workflows, and expert personas. Each agent in the pipeline calls a skill, and that skill is written such that it pulls in the specific documents it needs, takes on the appropriate persona (senior developer, architect, tester), and follows the workflow steps required for its task type.

This approach — skills as the unit of agent capability — proved superior to building agents from scratch. The skills are composable, customizable, and grounded in specific document context rather than relying on general-purpose prompting. The factory's zero-failure rate across 225 agent invocations validates this architecture. If building it again, this foundation would not change.

### What Would Change: The Pipeline

**Add continuous deployment and verification.** The current pipeline stops at CI — the code builds and tests pass, but it does not deploy and verify the running application. Adding a deployment step (push to Railway or equivalent) and a verification step (hit health checks, run smoke tests against the live service) would close the loop from code generation to production validation. This is achievable and is the next planned improvement.

**Batch stories for throughput.** The current pipeline processes one story at a time through the full multi-agent loop. In practice, agents can handle multiple stories in a single invocation — three to five stories at a time for implementation, or ten stories at a time for review passes. Batching would reduce the overhead of agent startup, context loading, and inter-step handoffs without cutting any quality gates. This is the primary lever for making the factory faster.

### What Would Not Change: The Planning Phase

The planning and preparation phase — product brief, architecture analysis, UX design, epic/story breakdown — is mature and would not change. It is interactive: the agents ask excellent questions, the back-and-forth discussions are productive, and the resulting artifacts (PRD, architecture decisions, coding standards, story specs) provide exactly the context that the implementation agents need. This phase has been refined over multiple projects and is reliable.

The quality of the planning artifacts directly determines the quality of the factory output. Well-structured stories with BDD acceptance criteria, clear technical notes, and self-contained scope produce working code. Vague stories produce vague code. The planning phase is where the real engineering happens; the factory is the execution engine.

### Advice for Others

**Do not reinvent the wheel.** The most important lesson from this project is that agent skills — structured prompts with document sources, personas, and workflows — are available in libraries and communities online. People are polishing these every day. Instead of writing custom prompts from scratch and trying to direct agents manually, use existing skills as your foundation and customize them for your specific context.

The temptation for technically skilled people is to build everything themselves. Resist it. The value is not in crafting the perfect prompt — it is in assembling the right skills, feeding them the right documents, and letting the pipeline execute. The factory pattern works because each agent does one thing well with the right context, not because any single agent is doing something extraordinary.

*[Note: This section will be updated with additional observations after hands-on testing and any subsequent factory improvements.]*

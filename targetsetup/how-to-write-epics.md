# How to Write Epics

A reference for the PM agent, dev agent, operator, or human author drafting a project's `epics.md`. Describes the discipline layered on top of standard BMAD story anatomy — the things that, if missed, will produce stories that look right but won't survive the agent factory.

**13 patterns**, distilled from one full project drafting cycle (PawprintRecipes Phase C, 2026-05-04 to 2026-05-05, Epics 1–17). Examples throughout are drawn from that project; future projects can either swap in their own examples or treat the existing ones as illustrative case studies. The patterns themselves are project-agnostic.

**Source of truth on conflict:** a project's own `epics-rewrite-brief.md` (or equivalent input contract) wins where it conflicts with this document. This is a pattern digest, not a binding spec.

---

## 1. Brief §3.4 — Upstream-first authoring (the biggest one)

When the PM author drafts a story that references a model, column, table, error code, endpoint, permission class, UX-DR pattern, or any other upstream-doc element that does not yet exist in the relevant binding doc, the PM **MUST update the upstream doc first, in the same authoring session, before the story body is committed to `epics.md`** — never punt the upstream update to "same commit during implementation."

**Binding upstream docs** (typical set — adjust per project):

- `_bmad-output/planning-artifacts/prd.md`
- `_bmad-output/planning-artifacts/architecture.md`
- `_bmad-output/planning-artifacts/database-schema.md`
- `_bmad-output/planning-artifacts/ux-design-specification.md`

**Workflow when authoring hits an upstream gap:**

1. Pause story drafting at the point of reference.
2. Open the relevant upstream doc and add the entry, following the doc's existing conventions (column tables, registry rows, etc.).
3. Verify the entry is internally consistent (cascade rules, FK ordering, error envelope shape, etc.).
4. Resume story drafting; cite the now-real upstream entry by its actual section number.
5. Remove the upstream doc from the story's "Files Likely Touched" — UNLESS the story will also modify the upstream entry later (e.g., a follow-up story adds a column to a model an earlier story introduced), in which case keep the cross-cut entry.

**Why this rule exists:** "We'll add the schema entry in the same commit when this story is implemented" is the same class of failure as "We'll fix it in the next epic" — the handoff between author and implementing agent is exactly where silent drift hides. The implementing agent reads the story, sees `accounts.PasswordResetToken`, infers "this must exist somewhere," builds it, but never updates the schema doc; the next story's author opens `database-schema.md`, sees no PasswordResetToken model, and treats it as a missing scaffold to add. Drift compounds across iterations and produces the kind of cumulative misalignment that leads to project restart.

**Operator review pace consequence:** each epic's review now spans both EPICS and the upstream-doc deltas it incurred. The PM calls out the upstream deltas explicitly in the epic-handoff summary (see §3 below).

---

## 2. Strict story anatomy — every story, no exceptions

Every story uses this template — including stories that adapt one already in a prior `epics.md`:

```markdown
### Story X.Y: <Short Descriptive Title>

**Status:** ready-for-dev | review | done
**Epic:** <epic number> — <epic name>
**Story Key:** X-Y-<kebab-case-slug>
**Components:** [backend] [frontend] [integration] [docs] (use applicable tags)

#### Story

**As a** <user role>,
**I want** to <capability>,
**So that** <user value>.

#### Acceptance Criteria

**Given** <precondition>
**When** <action>
**Then** <observable outcome>
**And** <additional outcome>

(Repeat the Given/When/Then block for each scenario, including edge cases and error paths)

#### Files Likely Touched

- `backend/<app>/models.py` — <what changes>
- `backend/<app>/views.py` — <what changes>
- `web/src/app/<route>/page.tsx` — <what changes>
- `tests/factories/<type>.py` — <what changes>

#### Cross-cutting Considerations

(Anything that touches files outside this story's primary scope — even if "None.")

#### References

- PRD §9.1 FR3
- Architecture §A.7
- UX Spec §UX-DR42
- Database schema: `accounts.users`, `accounts.refresh_tokens`
```

`Cross-cutting Considerations` is the single most-often-missed section in prior project iterations. The rewrite makes it mandatory — even if its content is the literal word "None."

**Component tag vocabulary** (typical set — adjust per project):

- `[backend]` — server-side code
- `[frontend]` — web client code
- `[integration]` — cross-component glue, E2E test
- `[docs]` — doc-only (Spike stories, mostly)
- `[infra]` — Docker, CI, deploy
- `[mobile-android]` — Android app (mobile epics only)
- `[mobile-ios]` — iOS app (mobile epics only)

---

## 3. Spike + Polish epic bookends — every epic, no exceptions

**Story X.1 — Spike** (always doc-only, tagged `[docs]`):

- Establishes patterns the rest of the epic builds on
- Output is markdown at `_bmad-output/implementation-artifacts/<epic>-conventions.md` (~2 pages)
- CI Phase 0 short-circuits in <2 seconds (no test suite runs)

_Examples (PawprintRecipes):_

- Story 2.1 — "Auth Patterns Spike" (JWT transport, error envelope, OAuth callback shape)
- Story 12.1 — "Notification Patterns Spike" (taxonomy, frequency caps, quiet-hours rules)
- Story 15.1 — "Staff Panel Patterns Spike" (audit decorator discipline, role/permission matrix, PII redaction)

**Story X.M — Integration Polish** (always last in the epic):

- Ties together loose ends from earlier stories
- Verifies cross-story integration
- Adds/runs the epic-level E2E test
- Names the demo explicitly: `./scripts/demo-epic-N.sh` with numbered demo steps in the epic header

**Epic header summary structure** — every epic in `epics.md` opens with a multi-section header before any story body:

- Epic number + name + goal sentence
- Story list (X.1 Spike → X.M Polish, with count)
- **Cross-cuts encoded as same-commit edits** (named explicitly — see §8)
- **Upstream-doc deltas LANDED at authoring time** (per §3.4 — names every binding-doc change incurred)
- **Demo at end of epic** — numbered list of operator demo steps (Story X.M's ACs replay these)

---

## 4. UX-DR citations are mandatory on every `[frontend]` story

Every story tagged `[frontend]`:

1. Cites at least one `UX-DR<N>` pattern number from `ux-design-specification.md` in its References section.
2. Includes this AC verbatim:

> **And** the implementation matches `ux-design-specification.md` §UX-DR<N>: <title>, verified by Playwright snapshot test or visual regression check.

3. Lists the UX spec section as a "Files Likely Touched" entry IF the implementation reveals a UX-spec gap (so the CHANGE-REQUEST flow fires — see §10).

**Why:** prior project iterations had agents shipping UI that didn't match the design spec because nothing in the story forced the lookup. This rule fixes it at the AC level — implementation cannot be marked "done" without the verification step.

**Prerequisite:** the UX spec must be numbered with stable `UX-DR<N>` IDs. If it isn't, run the procedure in [`how-to-number-ux-spec.md`](how-to-number-ux-spec.md) before drafting `[frontend]` stories.

---

## 5. 5-stage MailPit E2E pattern on every email-touching story

Every story whose ACs mention email send/receive:

1. References `email-testing-guide.md` in its References section.
2. Includes the 5-stage MailPit E2E test in ACs:
   - **Stage 1:** Trigger the email-sending action
   - **Stage 2:** Verify email arrived in MailPit AND verify content (From, Subject, body text)
   - **Stage 3:** Extract the link AND verify URL shape
   - **Stage 4:** Click the link AND verify it resolves correctly
   - **Stage 5:** Verify post-link state (e.g., new password works, account verified, etc.)
3. Sets `EMAIL_HOST=mailpit.<env>.internal` (deployed test env) or `EMAIL_HOST=localhost` (CI) in test setup — never mocks `send_mail()` directly.

**Mock-based "we called sendEmail()" tests are forbidden as the only assertion** for password reset, email verification, transactional notifications, support replies, and any future email feature.

---

## 6. Story tagging convention — factory CI hard-depends on it

Every test includes exactly one of `story_X_Y`, `Story_X_Y`, or `X-Y` in its `describe()` name or filename. Factory CI uses `pytest -k "story_X_Y"` (or `vitest -t`) to filter. Untagged tests cause the filter to silently match zero and fall back to full-suite — wasting 90+ seconds per cycle.

**Recommended:** tag at the `describe()` / class level so all tests inside inherit:

```python
# backend/apps/auth/tests/test_login.py
class TestLoginFlow:
    """Login flow (story_2_4)"""
    def test_valid_credentials_returns_jwt(self): ...
    def test_invalid_password_returns_401(self): ...
```

```typescript
// web/src/app/auth/login/page.test.tsx
describe("Login page (story_2_4)", () => {
  it("submits credentials and redirects", () => { ... });
});
```

---

## 7. Central mock factories — no per-test ad-hoc mocks of shared types

Every shared model has exactly one factory per platform. If a story changes a shared type, it updates the factory (or factories — see §7.4 below) **in the same commit**. The story's Cross-cutting Considerations section MUST list the factory file(s) as touched.

**Why:** this is the rule that prevents the kind of cross-file regression cascade where adding a required column to a shared type without naming all mocks breaks `tsc --noEmit` in 8+ unrelated test files. Central factories make the cascade a single-file change.

### §7.1 Python factories (backend) — the original pattern

Location: `backend/tests/factories/<type>.py`

```python
# backend/tests/factories/pet_profile.py
def make_pet_profile(**overrides):
    defaults = {
        "name": "TestPet",
        "species": "dog",
        "stress_triggers": [],
        # ... all fields from schema, with sensible defaults
    }
    return PetProfile.objects.create(**{**defaults, **overrides})
```

Pattern: `**overrides` defaults-merge. Override only the fields the test cares about.

### §7.2 Kotlin factories (Android) — Option A pattern

Location: `app/src/test/java/<your-package>/factories/<Type>Factory.kt`

```kotlin
// app/src/test/java/<your-package>/factories/PetProfileFactory.kt
fun makePetProfile(
    name: String = "TestPet",
    species: String = "dog",
    stressTriggers: List<String> = emptyList(),
    // ... all fields with defaults
): PetProfile = PetProfile(
    name = name,
    species = species,
    stressTriggers = stressTriggers,
    // ...
)

// usage in test:
val pet = makePetProfile(name = "Wynnie", species = "dog")
```

Pattern: Kotlin default parameters + named-argument overrides. Idiomatic Kotlin, mirrors the Python `**overrides` shape, AI-agent-friendly.

### §7.3 Swift factories (iOS) — Option A pattern

Location: `<YourProjectName>Tests/Factories/<Type>+Factory.swift`

```swift
// <YourProjectName>Tests/Factories/PetProfile+Factory.swift
extension PetProfile {
    static func make(
        name: String = "TestPet",
        species: String = "dog",
        stressTriggers: [String] = []
        // ... all fields with defaults
    ) -> PetProfile {
        PetProfile(
            name: name,
            species: species,
            stressTriggers: stressTriggers
        )
    }
}

// usage in test:
let pet = PetProfile.make(name: "Wynnie")
```

Pattern: static factory method on a Swift extension. Idiomatic Swift, mirrors the Kotlin pattern, AI-agent-friendly.

### §7.4 Phase-aware factory discipline — the cross-cut rule

Mobile factories don't exist until their respective mobile epic creates them. The discipline evolves through three phases:

| Phase                  | Active factories        | Schema-change story must touch                                                      |
| ---------------------- | ----------------------- | ----------------------------------------------------------------------------------- |
| **Web-only phase**     | Python only             | Python factory only                                                                 |
| **After Android epic** | Python + Kotlin         | Both — Kotlin factories created at the Android spike story, kept in sync thereafter |
| **After iOS epic**     | Python + Kotlin + Swift | All three — Swift factories created at the iOS spike story, kept in sync thereafter |

**The post-iOS rule:** once the iOS epic ships, any schema-changing story in any future epic MUST touch all three factory sets in the same commit. The story's Cross-cutting Considerations section names all three files. Skipping a platform's factory = the cascade returns.

**Discipline aid:** add a CI lint that scans for `models.py` or schema YAML changes in a commit and verifies the same commit includes touches in `tests/factories/`, `app/src/test/java/<your-package>/factories/`, AND `<YourProjectName>Tests/Factories/` (whichever platforms exist at that point in the project timeline). Pre-Android the lint only checks Python; mid-Android it adds Kotlin; post-iOS it requires all three. The Android / iOS spike stories are the right place to land each lint expansion.

### §7.5 Why three factory sets and not one shared definition

Shared model definitions (Python Django model, Kotlin data class, Swift struct) are NOT shared across platforms — each platform has its own type system, ORM/persistence layer, and idiomatic constructors. So the factories can't be auto-generated from a single source without significant code-gen tooling that this kind of project typically doesn't have.

The discipline is manual but tractable: schema-changing stories carry the cross-cut explicitly. The cost of three factory updates is paid; the cost of silent drift across platforms (a Kotlin test that passes but compiles against an outdated model shape, masking a backend migration regression) would be much higher.

---

## 8. Cross-cuts are explicit and bidirectional

When Story A consumes, extends, or modifies Story B's work, the dependency is named in **both** the epic header summary AND the story bodies on both sides.

_Examples (PawprintRecipes):_

> "Story 14.5 makes prior epics' rate-limit TODOs real — Stories 2.4, 2.7, 6.3, 10.9, 11.5, 14.3 declared keys; Story 14.5 implements the sliding-window middleware."

> "Story 15.10 (Support resolution) calls `support_service.resolve_ticket` from Story 14.4. Audit-logs via decorator."

> "Story 6.6 modifies Stories 5.2/5.4/5.9 in same commit (algorithm extension + cache-key shape + test expectation flip)."

The reading test: any story that says "uses X from Story Y" should appear in BOTH epics' headers and BOTH story bodies. If you can find a one-sided reference, that's a drift risk — fix it before shipping the epic.

---

## 9. Same-commit-backfill when a later story formalizes inline patterns

When a later story formalizes / centralizes what earlier stories did inline, the formalizing story is responsible for the same-commit refactor of the earlier inline usages.

_Canonical example (PawprintRecipes Epic 11):_

> "Story 11.4 RequireFeature class formalizes what Stories 1.6 / 5.4 / 10.6 / 10.9 used inline — same-commit backfill replaces inline checks where appropriate (5.4 keeps inline soft-gate, 3.3 keeps inline first-pet-free special case, 10.6 adopts class)."

The formalizing story's ACs name **which earlier stories adopt the new pattern in the same commit** AND **which deliberately keep the inline pattern and why**.

_Other examples (PawprintRecipes):_

- Story 12.7 ships canonical notification dispatch pipeline — every notification creator across the app now goes through it
- Story 12.9 backfills unsubscribe link (FR93) into all transactional email templates from prior epics
- Story 14.5 implements rate-limit middleware that Stories 2.4 / 2.7 / 6.3 / 10.9 / 11.5 / 14.3 declared keys for

---

## 10. CHANGE-REQUEST protocol — encoded as a meta-AC

When a dev agent's implementation surfaces a contradiction or augmentation that affects PRD, UX spec, or architecture, the dev agent MUST:

1. **STOP** implementation.
2. Emit a `CHANGE-REQUEST` artefact at `_bmad-output/change-requests/<story-key>-<short-slug>.md` with:
   - What the implementation revealed
   - Which upstream doc needs updating, and where (file + section)
   - Recommended change (delta, not free-form prose)
   - Whether the story can proceed unchanged after the upstream update, or also needs an AC change
3. **Wait** for a PM/architect agent to update the upstream doc(s) AND the story AC together as one change-set.

**This is encoded** in every story's anatomy as an implicit meta-AC: _"And if implementation reveals a contradiction with PRD / UX spec / architecture, dev agent emits a CHANGE-REQUEST and pauses; does not silently edit EPICS."_

**Distinction vs. §3.4 upstream-first authoring:**

- §3.4 = author-time upstream gaps the PM catches while drafting
- §10 / CHANGE-REQUEST = implementation-time contradictions the dev agent catches mid-build

Both rules coexist. Both prevent silent EPICS-only edits.

---

## 11. Source-of-truth resolutions are encoded when older patches conflict

When patches / older docs conflict with current upstream, the resolution is recorded explicitly in the relevant epic header so the dev agent doesn't get confused.

_Examples (PawprintRecipes Epic 2):_

- Account-deletion endpoint: `/users/me/delete/` (arch §B wins over Patch 3's `/auth/delete-account/`)
- User soft-delete column: `deletion_scheduled_at` (schema §6.2 wins over Patch 3's `deleted_at`)
- Email transport: MailPit + Postfix per brief §4 (supersedes Patch 4's Postmark)

**Source-of-truth hierarchy on conflict** (typical — adjust per project):
**PRD > Architecture > UX Spec > EPICS**

The upstream wins. EPICS gets updated to match — never the other way around.

---

## 12. Specialist-subagent handoff for design-judgment upstream additions

§3.4 says upstream-doc gaps must be filled before the story body is committed — but it doesn't say _who_ fills them. For most upstream additions (DB columns, endpoint rows, error codes), the PM agent in John persona can do it directly. The work is mechanical: a column type, a registry row.

**For design-judgment work — particularly net-new UX-DRs — the PM agent should hand the work to the appropriate specialist subagent rather than draft it inline.** UX-DRs involve gesture flows, error states, affordance choices, and voice/depth that match the existing spec's design language. That's the UX designer's domain (Sally), not the PM's.

### When to invoke a specialist vs. draft inline

| Upstream gap type                                   | Who drafts                      | Why                                                          |
| --------------------------------------------------- | ------------------------------- | ------------------------------------------------------------ |
| New DB model / column                               | PM (John) inline                | Mechanical — column type, FK, index                          |
| New endpoint row in arch §B inventory               | PM (John) inline                | Mechanical — URL, verb, request/response shape               |
| New error code in arch §A.9 registry                | PM (John) inline                | Mechanical — code, HTTP status, retry semantics              |
| New permission class in arch §A.8                   | PM (John) inline                | Mechanical — class signature, who-can-call                   |
| New PRD FR                                          | PM (John) inline                | PM owns the PRD                                              |
| **New UX-DR pattern**                               | **Specialist (Sally) subagent** | **Design judgment — gesture flow, affordances, voice match** |
| **Net-new visual / interaction component**          | **Specialist (Sally) subagent** | **Same as above**                                            |
| Net-new architecture decision (e.g., new framework) | Specialist (Winston) subagent   | Architectural judgment                                       |

### How the handoff works

1. PM agent (John) drafts Story X.1 spike — includes a **Gap Audit** as one of the spike's deliverables: lists each net-new UX-DR / architecture decision needed for the epic, with target slot in the spec, voice exemplar to match, and a one-paragraph specification of what the entry should cover.
2. Operator reviews Story X.1 and the Gap Audit.
3. On greenlight, PM spawns the specialist subagent **once per epic, batched** — passes the Gap Audit + relevant context (file paths, voice exemplars, project rules like §3.4, FR references). For UX-DRs, that specialist is Sally via the `bmad-agent-ux-designer` skill invoked inside an `Agent` tool subagent call.
4. Specialist subagent reads the existing spec for voice/format, drafts the entries, writes them at the target slots, returns a summary to the PM.
5. PM reviews the specialist's work briefly, iterates if rough, then resumes drafting story bodies with real references.
6. Operator reviews the new UX-DRs / decisions as part of normal epic operator review — same scrutiny applied to schema and architecture deltas.

### Why batched (one specialist invocation per epic, not per story)

- The specialist context-loads the spec once, not N times
- Net-new entries within an epic share design-system foundation; writing them together produces better internal consistency
- One handoff point in the workflow is cleaner than scattered handoffs

### Why NOT party-mode for this

`bmad-party-mode` is for **roundtable group discussions** (multiple BMAD agents in conversation about a topic). The specialist-handoff pattern is **sequential expert delegation** — PM pauses, specialist writes, PM resumes. Different tool, different shape.

### Caveats

- The specialist subagent doesn't inherit the PM's session memory — the prompt must carry all relevant context (FR numbers, target slots, voice exemplars, project rules). PM writes the prompt carefully; the specialist is only as good as the briefing.
- First invocation in any project should be verified — confirm the specialist correctly loads its skill persona, writes in the expected voice, and produces output the operator would sign off on. Iterate the prompt if the first batch comes back rough.
- The specialist's output goes to the operator as part of normal epic review — same path as PM's own deltas. Specialist is a craftsperson, not a final approver.

### Origin

Introduced 2026-05-05 during the PawprintRecipes Epic 16 (Android) scoping conversation. The four mobile UX-DR gaps (mobile DNA camera capture, first-launch onboarding carousel, mobile permissions flow, mobile alert/notification inbox) were the trigger — design judgment work that warranted Sally's UX expertise rather than John's PM drafting.

---

## 13. End-of-drafting IR pass replaces per-epic Pause-3 walkthroughs at solo-project scale

Multi-stakeholder projects typically do a **Pause-3 walkthrough at the end of every epic** — operator + PM (+ sometimes architect / QA) sit together, walk every story, sign off before greenlighting implementation. The walkthrough distributes review load across multiple humans and surfaces drift early, while the next epic can still incorporate corrections.

At **solo-project scale** — one operator wearing all hats — Pause-3 is over-engineered. The operator already has full context on every drafting decision. A per-epic gate adds session overhead (re-immerse, re-grade, decide, move on) for review surface that's mostly redundant with what the operator just authored.

**Pattern:** skip per-epic Pause-3 walkthroughs at solo-project scale. Run `bmad-check-implementation-readiness` (the IR skill) **once after all epics are drafted** as a single comprehensive cross-document validation pass. IR validates the same surface area Pause-3 would catch — FR coverage, UX-DR completeness, §8 bidirectionality, version drift, story anatomy quality — but does it across the _whole_ epic set in one run.

### Trade-off

| Approach                      | Cost                                                                                             | When it wins                                                                                                                                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Per-epic Pause-3 walkthroughs | N gate-stalls during drafting; review load distributed across stages                             | Multi-stakeholder teams; high cost of late drift discovery (e.g., parallel implementation already started on early epics); review needs distinct human perspectives (security, accessibility, etc.) |
| End-of-drafting IR pass       | Longer single cleanup pass; drift discovered late but contained (no parallel implementation yet) | Solo operator; sequential drafting → IR → implementation flow; project where the operator trusts the IR skill's coverage                                                                            |

### How to apply

1. **At drafting time:** in each epic's drafting plan, note that Pause-3 is **intentionally deferred to IR** — don't have the operator do per-epic walkthroughs. Each epic's drafting completes when the epic body is committed; the next epic begins immediately.
2. **At end of drafting:** open a fresh-context session (don't reuse the drafting session — drafting noise crowds the analysis). The fresh context lets IR read the binding docs cleanly.
3. **Run IR:** dispatch `bmad-check-implementation-readiness`. IR produces a findings report at `_bmad-output/planning-artifacts/implementation-readiness-report-{date}.md` with severity-tagged findings.
4. **Operator review:** the IR findings list IS the operator review surface. Operator decides which to apply, which to defer, which to accept. Apply edits in priority order.
5. **Greenlight:** once Priority-1 findings are addressed (and Priority-2 / 3 / 4 dispositioned per operator preference), record IR-pass + Phase-X greenlight in memory and proceed to implementation.

### When NOT to use

- **Multi-stakeholder teams** — Pause-3 distributes review load across humans (PM reviews story shape, architect reviews endpoints, designer reviews UX-DRs). IR alone can't replace human-perspective diversity.
- **Parallel drafting + implementation** — if implementation has already started on early epics while later epics are still being drafted, late drift discovery breaks shipped code. Pause-3 keeps drift containment per-epic.
- **First-time IR use on a new project** — until the operator has verified IR catches the drift they care about, do at least one per-epic walkthrough alongside IR to compare findings. After IR is trusted, drop the walkthroughs.

### Origin / receipt

PawprintRecipes Phase C drafting (Sessions 1–3, 2026-05-04 / 2026-05-05) — the operator drafted Epics 2–15 in Session 1, Epic 16 in Session 2, Epic 17 in Session 3 with no per-epic Pause-3 walkthroughs. Phase D IR run 2026-05-05 surfaced 11 findings (1 medium, 3 low-medium, 4 low, 2 very low, 1 intentional). All addressable via small targeted edits; no critical defects. Compared against the would-have-found list of per-epic walkthroughs, no findings were uniquely catchable by Pause-3 — IR caught everything Pause-3 would have plus several documentation-completeness items that per-epic review would have missed (FR Coverage Map missing 3 lettered entries; cross-epic §8 bidirectionality between Epic 4 ↔ Epic 16/17 — no per-epic walkthrough sees Epic 4 + Epic 16 simultaneously).

The receipt: at solo scale, IR-once is strictly better than Pause-3-per-epic.

---

## Quick checklist for the PM author drafting a new story

Use this before committing a story body to `epics.md`:

- [ ] Story uses the §2 anatomy completely (no missing sections, including "Cross-cutting Considerations: None" if truly nothing crosses)
- [ ] Status / Epic / Story Key / Components line is filled in correctly
- [ ] All upstream references resolve to **existing** entries in the binding docs (per §1 — if not, pause and add them upstream FIRST)
- [ ] If `[frontend]`: at least one UX-DR cited + the verbatim "matches ux-design-specification.md §UX-DR<N>" AC included
- [ ] If email-touching: 5-stage MailPit pattern in ACs + email-testing-guide referenced
- [ ] All test ACs name a `story_X_Y` tag or describe block
- [ ] If schema-touching: factory file at `tests/factories/<type>.py` listed in Cross-cutting Considerations
- [ ] If formalizing an earlier inline pattern: §9 same-commit backfill list explicit (which stories adopt, which keep inline, why)
- [ ] If consuming Story Y: §8 cross-cut named in BOTH epics' headers and BOTH story bodies
- [ ] Any source-of-truth conflict with older patches resolved explicitly (§11)

## Quick checklist for the operator reviewing an epic

Use this before greenlighting an epic for the next one to be drafted:

- [ ] Epic header lists Cross-cuts encoded as same-commit edits
- [ ] Epic header lists Upstream-doc deltas LANDED at authoring time (per §3.4)
- [ ] Story X.1 is `[docs]` only and produces a `<epic>-conventions.md`
- [ ] Story X.M is Integration Polish with `./scripts/demo-epic-N.sh` and numbered demo steps
- [ ] Spot-check 3 random stories — do they pass the PM author checklist above?
- [ ] Read the demo steps — could you run them yourself end-to-end?
- [ ] Check the upstream-delta list against `git diff` on `prd.md` / `architecture.md` / `database-schema.md` / `ux-design-specification.md` — do they match?

---

## Companion documents in this directory

- [`story-and-epic-writing-guide.md`](story-and-epic-writing-guide.md) — story anatomy spec referenced from §2
- [`how-to-number-ux-spec.md`](how-to-number-ux-spec.md) — UX-DR numbering procedure required by §4
- [`email-testing-guide.md`](email-testing-guide.md) — 5-stage MailPit pattern referenced from §5
- [`test-structure-guide.md`](test-structure-guide.md) — story-tag conventions and factory locations referenced from §6 and §7
- [`ci-script-specification.md`](ci-script-specification.md) — CI script the story tags from §6 hook into

---

_Distilled from PawprintRecipes Phase C drafting (2026-05-04 to 2026-05-05). 13 patterns confirmed across Epics 1–17. If a future project surfaces a 14th pattern worth carrying forward, append it here and update this attribution line._

# How to add `UX-DR<N>` pattern numbering to a UX design specification

This is a procedure for retrofitting stable, citable pattern references onto an existing UX design spec so that downstream artifacts (EPICS, stories, ACs, visual regression tests) can cite specific patterns without depending on heading text that drifts.

_Worked example (PawprintRecipes):_ the project ran this procedure on its `ux-design-specification.md` on 2026-05-04 — see [rewrite-meta-ux-dr-numbering-missing.md](../_bmad-output/change-requests/rewrite-meta-ux-dr-numbering-missing.md) for the originating CHANGE-REQUEST and outcome. References below to "the PawprintRecipes pass" or specific UX-DR numbers are illustrative — substitute your project's equivalents.

---

## Why this exists

A UX spec describes patterns. Stories cite those patterns to verify implementation. The cite has to point at _something_ — the question is what.

Three options, in increasing order of stability:

1. **Section heading text** — `§"Color System"`. Cheap, but breaks the moment a heading is renamed. Visual regression test names that hardcode "Color System" become stale. Search-and-replace risk on every heading edit.
2. **Heading anchor / slug** — `§color-system`. Better, but still text-derived; renames silently break links.
3. **Stable opaque ID** — `§UX-DR1`. The ID is a contract. The title can change freely; the ID is what stories cite. This is the convention this procedure installs.

`UX-DR` stands for "UX Design Reference." The number is sequential and never reused, even if a pattern is later removed.

## When to run this procedure

Signals that you need it:

- An EPICS or story rewrite mandates a UX-spec citation in every `[frontend]` story's References or ACs, but `grep -n UX-DR <ux-spec>` returns zero matches
- Story authors keep citing different titles for the same pattern because they don't know which heading is canonical
- Visual regression / Playwright snapshot test names are inconsistent across stories that target the same UX pattern
- The UX spec has had heading renames in the past, and you want to stop that being a story-rewrite event

If none of those apply yet, don't pre-emptively number. Numbering is a contract — once stories cite `UX-DR17`, you can't reorder.

## Prerequisites

1. **An owner.** A UX designer (or the UX agent — Sally in BMad) executes the pass. The operator (project lead) confirms the section-by-section number-vs-skip selection before editing.
2. **A reason.** The pass is mechanical but not free — it touches every pattern heading in the doc. Run it because a downstream contract (brief / story template / test naming convention) demands it, not pre-emptively.
3. **A brief or CHANGE-REQUEST that references the convention.** Without an upstream document that names `UX-DR<N>`, the numbers are unmoored. The PawprintRecipes pass was driven by [`epics-rewrite-brief.md`](../_bmad-output/planning-artifacts/epics-rewrite-brief.md) §2.5.
4. **Stable scope.** Don't number while the UX spec is mid-rewrite. Number after the spec stabilizes so the numbers don't churn.

## Procedure

### 1. Read the entire spec, end to end

Yes, the whole thing. The number-vs-skip judgment depends on tone and intent, not regex matching. Reading 1,500 lines once is faster than relitigating decisions thirty times.

### 2. List every heading

Use a content-mode grep for the heading lines:

```
Grep: pattern=^#{1,4} , output_mode=content, -n=true, head_limit=0
```

This gives you `(line_number, heading_text)` pairs for every `#`-through-`####` heading in the doc. Working from this list is faster than scrolling.

### 3. Classify each heading: number or skip

Apply the rules in the next section. Record the result as a table — line number, heading text, decision (number / skip), reasoning where non-obvious. The PawprintRecipes pass produced a 42-row "number" table and a list of skipped sections grouped by reason.

### 4. Propose the classification to the operator before editing

This is the step you don't skip. The judgment about "implementable pattern" vs "prose" has interpretation in it — different reviewers will draw the line differently for sections like `### Customization Strategy` or `### Implementation Approach`. Showing the operator the proposed split lets them redirect with a one-line "skip 17" rather than discovering it after a 42-edit pass.

For each ambiguous section, state your reasoning in one line. Surface the borderline cases explicitly — "I'm including X because story authors will likely cite it for Y; flag if you disagree."

### 5. Wait for explicit go

`go` / `proceed` / `ship it`. Don't infer consent from silence on the proposal.

### 6. Insert the index near the top of the doc

Place it after the title block (and after any existing TOC) but before the first content section. Use a `## UX-DR Pattern Index` heading so it's visible in the doc structure.

The index has three parts:

1. **A citation rule.** One paragraph explaining what story authors are supposed to do with these numbers — typically: "every `[frontend]` story must cite at least one `UX-DR<N>` from this index" plus the verbatim AC template. Reference the upstream brief / convention doc.
2. **A note on what's not numbered.** Prose-only sections (vision, philosophy, emotional response, inspiration analysis, etc.) are intentionally not numbered — they aren't implementable patterns to verify. Saying this once in the index avoids the "why isn't section X numbered?" question on every story review.
3. **The table.** Three columns minimum: `#`, `Pattern`, `Domain`. Domain is a one-word grouping (`Mobile Home`, `Web Marketing`, `Visual Design`, etc.) that helps readers locate the pattern in the doc without re-reading the whole TOC.

If two numbered patterns describe overlapping content (the PawprintRecipes pass had two "Guided Cooking Mode" sections — one as an interaction pattern, one as a defining experience), add a one-paragraph **Note on overlapping flows** below the table explaining that they're complementary, not redundant. Don't silently merge — that changes spec content, which is out of scope for a numbering pass.

### 7. Edit each numbered heading

The format is exactly:

```
### UX-DR<N>: <Original Title>
```

Preserve the original heading level (`###` or `####`) and the original title verbatim. The number goes between the level marker and the title, separated by a single space, followed by `: `.

Examples from the PawprintRecipes pass:

| Before                                            | After                                                      |
| ------------------------------------------------- | ---------------------------------------------------------- |
| `### Color System`                                | `### UX-DR30: Color System`                                |
| `### Accessibility Considerations (Home Screen)`  | `### UX-DR12: Accessibility Considerations (Home Screen)`  |
| `#### Recipe Card Skeleton (Home Screen, Browse)` | `#### UX-DR36: Recipe Card Skeleton (Home Screen, Browse)` |

Numbers are sequential through the document in reading order. **Do not group by domain** — domain grouping creates ambiguity when patterns are added later (where does `UX-DR43` go if it's a Mobile Home pattern but the doc already used 1–13 for Mobile Home and is now at 42?). Sequential reading-order numbering is the only convention that survives later additions.

### 8. Verify

Grep the spec to confirm exactly the expected number of headings now have `UX-DR` prefixes:

```
Grep: pattern=^#{3,4} UX-DR, path=<spec>, output_mode=content, -n=true, head_limit=0
```

Check three things:

1. The count matches your proposed number (42 in the PawPrint case)
2. The numbers are contiguous (`UX-DR1` through `UX-DR<N>` with no gaps or duplicates)
3. The index table and the actual headings agree on every pattern's number

If any heading edit silently failed or hit a non-unique-string error, this is where you catch it.

### 9. Bundle in any small consistency fixes you noticed during the read

While walking the spec, you'll spot small parallel-structure gaps where two related sections describe the same rule with different explicitness. Fix these _if and only if_ they're consistency fixes, not semantic changes. Examples:

- **Bundleable:** Segment B says "X is ALWAYS true," Segment C has the same rule encoded in a priority table but doesn't state "ALWAYS." Add the parallel statement to Segment C with a `(per <upstream-doc> §<N>)` cross-reference.
- **Not bundleable:** Two sections give _contradictory_ rules. STOP. This is a CHANGE-REQUEST, not a numbering-pass fix. See the process-discipline rule below.
- **Not bundleable:** A pattern looks underspecified and you have ideas to flesh it out. STOP. Out of scope for a numbering pass.

The rule of thumb: a bundleable fix makes two existing sections agree with each other; a non-bundleable fix changes what one of them says.

### 10. Update the resolution document

If this pass was driven by a CHANGE-REQUEST, update the CHANGE-REQUEST file:

- Mark the resolution actions complete (`☐` → `☑️`) for the items you actually did
- Add a "what landed" subsection summarizing: number of patterns numbered, where the index lives, any bundled consistency fixes, any flags surfaced for future cleanup
- Add a "hand-off" subsection if a downstream agent is the next actor, listing likely citations from the new numbering scheme to save them a discovery round-trip

### 11. Update project memory if relevant

If the pass unblocks a downstream phase or changes the next-action owner, update the relevant project memory entry (status field, next-action line, MEMORY.md index hook). Don't write a fresh memory just for this pass — update the existing handoff entry.

## Decision rules: what to number, what to skip

Number a section if a `[frontend]` story might plausibly cite it to verify implementation. The "verifiability" test is the cleanest:

- Could a Playwright snapshot, visual regression, or integration test point at this pattern and assert "the implementation matches"? → Number.
- Is the section instead framing, rationale, or analysis that informs design without prescribing implementation? → Skip.

### Number these

- **Visual systems** — color, typography, spacing, layout foundations
- **Components** — tiles, cards, modals, navigation structures, headers, footers, form controls (anything story-citable as a unit)
- **Screens / segments / states** — `Segment A: Brand New User`, login screen, empty states for specific surfaces
- **Flows** — guided cooking, batch planning, onboarding, checkout (multi-step interactions with specific transitions)
- **Loading / skeleton patterns** — per surface (recipe card skeleton, detail skeleton, list skeleton)
- **Accessibility rules** — the concrete rule sets, not the philosophy
- **Web marketing sections** — section order, responsive behavior, visual system, copy tone (when copy tone is concrete enough to verify against)
- **Anti-patterns and "do not do" rules** — when stated as concrete rules a test could enforce

### Skip these

- **Vision / philosophy / mission** — `Project Vision`, `Design Direction`, `Defining Experience` (when used as a chapter intro)
- **Persona descriptions** — `Target Users`, `User Mental Model`
- **Design challenges and opportunities** — strategic framing, not implementation rules
- **Emotional design framing** — `Primary Emotional Goals`, `Emotional Journey Mapping`, `Micro-Emotions`, `Emotional Design Principles`
- **Inspiration / competitive analysis** — `Inspiring Products Analysis`, `Transferable UX Patterns`, anything about Mealime/Spotify/competitors
- **Design system meta** — `Design System Choice`, `Rationale for Selection`, `Novel vs. Established Patterns`
- **Rationale prose** — `Philosophy: Why X over Y`, `Why Skeleton Screens (Never Spinners)`
- **Superseded sections** — sections explicitly marked superseded or deprecated should not get numbers (their content is for context only, not for citing)

### Borderline cases

When in doubt, **lean toward numbering**. A number on a borderline section is harmless — story authors who don't need it ignore it. A missing number on a section a story author _did_ need to cite forces them to either invent ad-hoc text references (the problem this whole procedure solves) or block on a re-numbering pass. The cost asymmetry favors over-numbering.

Two patterns the PawprintRecipes pass borderline-included:

- `### Implementation Approach` (Design System) — concrete dev guidance, not pure prose. Numbered.
- `### Customization Strategy` — describes implementable rules about what consumers can override. Numbered.

## Gotchas

### Heading text is a substring of another heading

Common pattern: `### Accessibility` (in one section) and `### Accessibility Considerations` (in another). A naive find-and-replace on `### Accessibility` matches both lines because the substring is shared.

If your editing tool requires unique substrings, disambiguate with a trailing newline:

- `### Accessibility\n` matches only the line where `Accessibility` is the _entire_ title (next char is the newline)
- `### Accessibility Considerations\n` matches only the line where `Considerations` is the last word
- The longer string `### Accessibility Considerations (Home Screen)` is unique on its own

The PawprintRecipes pass used trailing-newline disambiguation for two such cases (`UX-DR19: Accessibility` and `UX-DR33: Accessibility Considerations`).

### Both `###` and `####` headings deserve numbers

If a `####` subsection describes an implementable pattern (the PawprintRecipes pass had `#### Guided Cooking Mode` nested under `### Key Interaction Patterns`), number it too. Story authors will cite the most specific level that matches their story's scope.

When you do this, the parent `###` and the child `####` get separate sequential numbers. The parent isn't a "container only" — it usually still describes a pattern (the umbrella) that some stories will cite as a whole.

### The pass is ordering-sensitive across the doc

If you accidentally edit headings out of order while assigning numbers (e.g., assign `UX-DR15` to a section at line 1100 and `UX-DR16` to a section at line 800), the index becomes confusing. Always assign numbers walking the doc top-to-bottom; never reorder mid-pass.

### Tooling: parallel string-replace edits are fine _if_ every old_string is unique

When using a tool that does literal substring replacement (most editors' find-and-replace, the Claude Code Edit tool, sed in non-`g` mode), you can issue all heading edits in parallel as long as every `old_string` is unique. Verify uniqueness _before_ batching — a non-unique string causes the edit to fail (best case) or replace the wrong instance (worst case).

The fast path: build the edit list, manually scan it for any heading text that's a prefix of another, add trailing-newline disambiguation to those, then issue all edits in one batch.

### Process discipline: contradictions become CHANGE-REQUESTS

If during the read or the edit pass you discover the UX spec contradicts the PRD, the architecture doc, or itself in a way that changes intent, **stop the numbering pass and emit a CHANGE-REQUEST** rather than silently editing. The numbering pass is mechanical; semantic changes require their own approval cycle. Drop the pass back to the operator with the contradiction surfaced and let them decide whether to resolve before resuming.

The PawprintRecipes pass surfaced two flags but neither rose to contradiction:

- Two pairs of sections (`UX-DR23/24` and `UX-DR28/29`) describe the same flows from different angles. Flagged in the index note; left for a future consolidation CR.
- The Anti-Pattern Reference section was already marked superseded; not numbered (correct outcome under the rules above).

## Maintenance after the pass

Once the numbering is in place:

- **Adding a new pattern** — assign the next available `UX-DR<N>` (one higher than the current max), add it to the index in domain-appropriate position with note that it's been added, place it in the doc wherever it fits structurally. Number sequence in the index tolerates non-reading-order entries; the doc itself does too.
- **Removing a pattern** — leave a tombstone in the index: `| UX-DR17 | (removed YYYY-MM-DD: superseded by UX-DR<M>) | — |`. Never reuse the number. Stories that cited the removed pattern need a separate sweep to redirect.
- **Renaming a pattern** — change the title, leave the number. The number is the contract; the title is a label.
- **Splitting one pattern into two** — keep the original number on the most direct successor; assign a new number to the split-off pattern. Note both in the index.
- **Merging two patterns** — pick one number to retain; tombstone the other in the index pointing at the survivor. Sweep stories citing the tombstoned number.

The general principle: titles change freely, numbers never reused, index is the changelog.

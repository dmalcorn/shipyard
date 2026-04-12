"""Tests for src/intake/review_sieve.py.

Fixtures are real review outputs captured from chat2bpmn:

- ``epic-3-review-*.md`` — 2026-04-12 night run, ``### PATCH Findings``
  section headings with ``**[P1]**``-style tagged items.
- ``epic-4-review-*.md`` — 2026-04-12 morning run, the first epic with
  the correct git-history file scope. BMAD emitted a different format:
  ``### CRITICAL / HIGH — Patch Required`` headings with ``**F01**``
  items carrying inline ``` `[patch]` ``` category markers. The
  original sieve parser silently dropped all 20 BMAD findings because
  it didn't recognize either the heading or the item shape. The new
  parser prefers the inline category marker and keeps the heading as
  a safety-net fallback.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.intake.review_sieve import (
    Finding,
    append_deferred_work,
    parse_bmad_review,
    parse_claude_review,
    render_analysis_file,
    render_category_file,
    sieve_reviews,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "review_sieve"
BMAD_FIXTURE = FIXTURES_DIR / "epic-3-review-bmad.md"
CLAUDE_FIXTURE = FIXTURES_DIR / "epic-3-review-claude.md"
BMAD_FIXTURE_E4 = FIXTURES_DIR / "epic-4-review-bmad.md"
CLAUDE_FIXTURE_E4 = FIXTURES_DIR / "epic-4-review-claude.md"
BMAD_FIXTURE_E5 = FIXTURES_DIR / "epic-5-review-bmad.md"
CLAUDE_FIXTURE_E5 = FIXTURES_DIR / "epic-5-review-claude.md"


@pytest.fixture
def bmad_content() -> str:
    return BMAD_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def claude_content() -> str:
    return CLAUDE_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def bmad_content_e4() -> str:
    return BMAD_FIXTURE_E4.read_text(encoding="utf-8")


@pytest.fixture
def claude_content_e4() -> str:
    return CLAUDE_FIXTURE_E4.read_text(encoding="utf-8")


@pytest.fixture
def bmad_content_e5() -> str:
    return BMAD_FIXTURE_E5.read_text(encoding="utf-8")


@pytest.fixture
def claude_content_e5() -> str:
    return CLAUDE_FIXTURE_E5.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# BMAD parser
# ---------------------------------------------------------------------------


class TestParseBmadReview:
    """BMAD skill's section-tagged output should parse cleanly despite duplication."""

    def test_extracts_all_patch_findings(self, bmad_content: str) -> None:
        findings = parse_bmad_review(bmad_content)
        patches = [f for f in findings if f.category == "patch"]
        # Epic 3 summary line: "0 decision-needed, 8 patch, 4 defer, 6 dismissed"
        assert len(patches) == 8
        idents = {f.ident for f in patches}
        assert idents == {"P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"}

    def test_extracts_all_defer_findings(self, bmad_content: str) -> None:
        findings = parse_bmad_review(bmad_content)
        defers = [f for f in findings if f.category == "defer"]
        assert len(defers) == 4
        assert {f.ident for f in defers} == {"D1", "D2", "D3", "D4"}

    def test_dedups_duplicated_output(self, bmad_content: str) -> None:
        # The BMAD skill wrote its final report twice in the same file —
        # the parser must produce each finding exactly once.
        assert bmad_content.count("### PATCH Findings") == 2
        findings = parse_bmad_review(bmad_content)
        idents = [(f.category, f.ident) for f in findings]
        assert len(idents) == len(set(idents))

    def test_source_is_bmad(self, bmad_content: str) -> None:
        findings = parse_bmad_review(bmad_content)
        assert findings, "expected at least one finding"
        assert all(f.source == "bmad" for f in findings)

    def test_extracts_file_paths(self, bmad_content: str) -> None:
        findings = parse_bmad_review(bmad_content)
        p1 = next(f for f in findings if f.ident == "P1")
        assert "interview-list-view.tsx" in p1.file

    def test_empty_input_returns_empty_list(self) -> None:
        assert parse_bmad_review("") == []

    def test_no_tagged_items_returns_empty_list(self) -> None:
        content = "### PATCH Findings\n\nSome free-form prose, no items.\n"
        assert parse_bmad_review(content) == []


# ---------------------------------------------------------------------------
# Claude parser
# ---------------------------------------------------------------------------


class TestParseClaudeReview:
    """Claude's Summary/Findings template should parse into severity-tagged findings."""

    def test_extracts_all_findings(self, claude_content: str) -> None:
        findings = parse_claude_review(claude_content)
        # Epic 3's Claude review has 9 numbered findings (duplicated once).
        assert len(findings) == 9
        assert {f.ident for f in findings} == {str(n) for n in range(1, 10)}

    def test_all_findings_have_severity(self, claude_content: str) -> None:
        findings = parse_claude_review(claude_content)
        for f in findings:
            assert f.category in ("critical", "major", "minor"), (
                f"finding {f.ident} has category={f.category!r}"
            )

    def test_source_is_claude(self, claude_content: str) -> None:
        findings = parse_claude_review(claude_content)
        assert all(f.source == "claude" for f in findings)

    def test_extracts_file_field(self, claude_content: str) -> None:
        findings = parse_claude_review(claude_content)
        first = next(f for f in findings if f.ident == "1")
        assert "route.ts" in first.file

    def test_dedups_duplicated_findings(self, claude_content: str) -> None:
        assert claude_content.count("## Findings") == 2
        findings = parse_claude_review(claude_content)
        assert len(findings) == len({f.ident for f in findings})

    def test_empty_input_returns_empty_list(self) -> None:
        assert parse_claude_review("") == []


# ---------------------------------------------------------------------------
# Sieve routing
# ---------------------------------------------------------------------------


class TestSieveReviews:
    """Routing rules: BMAD patch→A, decision→B, defer→defer, dismiss dropped;
    Claude minor→A, major/critical→B."""

    def test_epic_3_routing_counts(
        self,
        bmad_content: str,
        claude_content: str,
    ) -> None:
        result = sieve_reviews(bmad_content, claude_content)
        # Epic 3: 8 patch + (claude minors) → Cat A
        #         0 decision-needed + (claude major/critical) → Cat B
        #         4 defer → defer
        bmad_patches = 8
        claude_minors = sum(1 for f in result.claude_findings if f.category == "minor")
        claude_biggies = sum(
            1 for f in result.claude_findings if f.category in ("major", "critical")
        )
        assert len(result.cat_a) == bmad_patches + claude_minors
        assert len(result.cat_b) == claude_biggies
        assert len(result.defer) == 4

    def test_dismiss_is_dropped(self, bmad_content: str, claude_content: str) -> None:
        result = sieve_reviews(bmad_content, claude_content)
        for bucket in (result.cat_a, result.cat_b, result.defer):
            assert not any(f.category == "dismiss" for f in bucket)

    def test_has_any_findings_true_on_real_input(
        self,
        bmad_content: str,
        claude_content: str,
    ) -> None:
        assert sieve_reviews(bmad_content, claude_content).has_any_findings is True

    def test_has_any_findings_false_on_empty_input(self) -> None:
        assert sieve_reviews("", "").has_any_findings is False

    def test_synthetic_routing(self) -> None:
        bmad = (
            "### PATCH Findings\n\n"
            "**[P1]** `a.ts` — patch one\nbody one\n\n"
            "### DEFER Findings\n\n"
            "**[D1]** `b.ts` — defer one\nbody\n\n"
            "### Decision-Needed\n\n"
            "**[C1]** `c.ts` — needs call\nbody\n\n"
            "### Dismissed\n\n"
            "**[X1]** `d.ts` — noise\nbody\n"
        )
        claude = (
            "## Findings\n\n"
            "### 1. Crit\n\n"
            "- **File:** `x.ts`\n"
            "- **Severity:** critical\n"
            "- **Action:** do it\n\n"
            "### 2. Minor\n\n"
            "- **File:** `y.ts`\n"
            "- **Severity:** minor\n"
            "- **Action:** tidy\n"
        )
        result = sieve_reviews(bmad, claude)
        cat_a_idents = {f.display_id() for f in result.cat_a}
        cat_b_idents = {f.display_id() for f in result.cat_b}
        defer_idents = {f.display_id() for f in result.defer}
        assert "BP1" in cat_a_idents and "C2" in cat_a_idents
        assert "BC1" in cat_b_idents and "C1" in cat_b_idents
        assert "BD1" in defer_idents
        # Dismissed BMAD items do not appear in any bucket.
        all_emitted = cat_a_idents | cat_b_idents | defer_idents
        assert "BX1" not in all_emitted


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------


class TestRenderCategoryFile:
    def test_empty_category_writes_sentinel(self) -> None:
        body = render_category_file(
            "Category A Fix Plan",
            "3",
            [],
            empty_sentinel="No Category A items found.",
        )
        assert "No Category A items found." in body

    def test_non_empty_category_lists_findings(self) -> None:
        findings = [
            Finding(
                source="bmad",
                ident="P1",
                title="patch one",
                category="patch",
                file="a.ts",
                body="explanation",
            ),
        ]
        body = render_category_file(
            "Category A Fix Plan",
            "3",
            findings,
            empty_sentinel="N/A",
        )
        assert "BP1" in body
        assert "patch one" in body
        assert "a.ts" in body
        assert "explanation" in body


class TestAppendDeferredWork:
    def test_creates_file_when_missing(self, tmp_path: Path) -> None:
        deferred = tmp_path / "sub" / "deferred-work.md"
        findings = [
            Finding(
                source="bmad",
                ident="D1",
                title="N+1 query",
                category="defer",
                file="route.ts",
                body="lots of rows",
            ),
        ]
        append_deferred_work(str(deferred), "3", findings)
        content = deferred.read_text(encoding="utf-8")
        assert "# Deferred Work" in content
        assert "epic-3" in content
        assert "N+1 query" in content

    def test_appends_to_existing_file(self, tmp_path: Path) -> None:
        deferred = tmp_path / "deferred-work.md"
        deferred.write_text("# Deferred Work\n\n## Older\n\n- thing\n", encoding="utf-8")
        findings = [
            Finding(
                source="bmad",
                ident="D1",
                title="new thing",
                category="defer",
                body="body",
            ),
        ]
        append_deferred_work(str(deferred), "3", findings)
        content = deferred.read_text(encoding="utf-8")
        assert content.count("# Deferred Work") == 1
        assert "Older" in content
        assert "new thing" in content

    def test_no_op_on_empty_findings(self, tmp_path: Path) -> None:
        deferred = tmp_path / "deferred-work.md"
        append_deferred_work(str(deferred), "3", [])
        assert not deferred.exists()


class TestRenderAnalysisFile:
    def test_contains_counts_and_routing_lists(
        self,
        bmad_content: str,
        claude_content: str,
    ) -> None:
        result = sieve_reviews(bmad_content, claude_content)
        body = render_analysis_file("3", result, "bmad.md", "claude.md")
        assert "Epic 3" in body
        assert "Category A" in body
        assert "Category B" in body
        assert "Deferred" in body
        assert f"BMAD findings parsed: {len(result.bmad_findings)}" in body


# ---------------------------------------------------------------------------
# Epic 4 format drift — inline category markers take precedence over headings
# ---------------------------------------------------------------------------


class TestParseBmadReviewEpic4Format:
    """Parser must handle the ``**F01** `[patch]``` item shape under a
    ``### CRITICAL / HIGH — Patch Required`` heading."""

    def test_extracts_all_patch_findings(self, bmad_content_e4: str) -> None:
        findings = parse_bmad_review(bmad_content_e4)
        patches = [f for f in findings if f.category == "patch"]
        # Epic 4's BMAD review tagged 17 items as `[patch]` inline.
        assert len(patches) == 17

    def test_extracts_all_defer_findings(self, bmad_content_e4: str) -> None:
        findings = parse_bmad_review(bmad_content_e4)
        defers = [f for f in findings if f.category == "defer"]
        # Epic 4's BMAD review tagged 3 items as `[defer]` inline.
        assert len(defers) == 3

    def test_finds_20_total_items(self, bmad_content_e4: str) -> None:
        findings = parse_bmad_review(bmad_content_e4)
        assert len(findings) == 20

    def test_item_idents_are_F_prefixed(self, bmad_content_e4: str) -> None:
        findings = parse_bmad_review(bmad_content_e4)
        idents = {f.ident for f in findings}
        # Items in Epic 4 are numbered F01 through F20 (with some gaps).
        assert all(i.startswith("F") for i in idents)
        assert len(idents) == 20

    def test_sieve_routes_epic_4_correctly(
        self,
        bmad_content_e4: str,
        claude_content_e4: str,
    ) -> None:
        result = sieve_reviews(bmad_content_e4, claude_content_e4)
        # 17 BMAD patches + 6 Claude minors → Cat A
        # 4 Claude critical + 2 Claude major   → Cat B
        # 3 BMAD defers                        → defer
        claude_minors = sum(1 for f in result.claude_findings if f.category == "minor")
        claude_high = sum(1 for f in result.claude_findings if f.category in ("major", "critical"))
        assert len(result.cat_a) == 17 + claude_minors
        assert len(result.cat_b) == claude_high
        assert len(result.defer) == 3


class TestBmadInlineCategoryPrecedence:
    """Synthetic tests: inline ``[patch]``-style markers outrank the
    section heading, even when the two disagree."""

    def test_inline_marker_overrides_section_heading(self) -> None:
        content = (
            "### DEFER Findings\n\n"
            "**F01** `[patch]` **This should route to patch, not defer**\n"
            "body line\n"
        )
        findings = parse_bmad_review(content)
        assert len(findings) == 1
        assert findings[0].category == "patch"
        assert findings[0].ident == "F01"

    def test_heading_used_when_no_inline_marker(self) -> None:
        content = "### PATCH Findings\n\n**[P1]** description of the thing\nbody\n"
        findings = parse_bmad_review(content)
        assert len(findings) == 1
        assert findings[0].category == "patch"

    def test_heading_keyword_detection_matches_epic4_wording(self) -> None:
        # "### CRITICAL / HIGH — Patch Required" should classify as patch.
        content = (
            "### CRITICAL / HIGH — Patch Required\n\n"
            "**F01** description only, no inline tag\nbody\n"
        )
        findings = parse_bmad_review(content)
        assert len(findings) == 1
        assert findings[0].category == "patch"

    def test_heading_keyword_deferred(self) -> None:
        content = "### DEFERRED\n\n**F01** body only\n"
        findings = parse_bmad_review(content)
        assert len(findings) == 1
        assert findings[0].category == "defer"

    def test_item_without_category_anywhere_is_ignored(self) -> None:
        # No section heading, no inline marker → cannot be categorized.
        content = "**F01** orphaned item, no context\n"
        assert parse_bmad_review(content) == []

    def test_mixed_formats_in_one_file(self) -> None:
        content = (
            "### PATCH Findings\n\n"
            "**[P1]** old-style item\n\n"
            "### DEFERRED\n\n"
            "**F02** `[defer]` new-style item with inline tag\n"
        )
        findings = parse_bmad_review(content)
        cats = {f.ident: f.category for f in findings}
        assert cats == {"P1": "patch", "F02": "defer"}


# ---------------------------------------------------------------------------
# Fallback guard — non-empty file but zero findings must trip the LLM fallback
# ---------------------------------------------------------------------------


class TestSieveFallbackGuard:
    """The analyze_reviews_node wrapper calls back to the LLM agent
    when ``_run_review_sieve`` returns ``None``. This module doesn't
    own that wrapper, but the contract is: if either reviewer's file
    has substantial content and parsed to zero findings, the sieve
    must signal fallback. Tested via the wrapper in epic_graph."""

    def test_sieve_reviews_records_zero_when_format_unknown(self) -> None:
        # Simulate a long BMAD file with an unrecognized format.
        bmad = "## Some Heading\n\n" + ("paragraph of prose. " * 200) + "\n"
        claude = "## Findings\n\n### 1. Title\n\n- **Severity:** minor\n- **Action:** x\n"
        result = sieve_reviews(bmad, claude)
        assert result.bmad_findings == []
        assert len(result.claude_findings) == 1
        # This is the condition the wrapper uses to trigger fallback:
        # "bmad file is substantial but bmad findings are empty".
        assert len(bmad) > 1000
        assert not result.bmad_findings


# ---------------------------------------------------------------------------
# Epic 5 format drift — H2-category sections + whole-title bolds + bullet
# list in deferred/dismissed sections. The first format that actually hit
# the sieve in production; the original parser silently dropped all 27
# BMAD findings and the analyze-reviews LLM fallback fired.
# ---------------------------------------------------------------------------


class TestParseBmadReviewEpic5Format:
    """Parser must handle the Epic 5 BMAD skill output:

    - Triage category comes from H2 headings like ``## Patch Findings (22)``
      / ``## Deferred Findings (2)`` / ``## Dismissed Findings (3)``.
    - Severity-based H3 subheadings (``### Critical``, ``### High``,
      ``### Medium``) sit underneath the H2 but must NOT reset the
      enclosing H2's category.
    - Detail items use whole-title bold: ``**F1 — `getDivergenceForStep`
      uses `Array.includes()` ...**`` (including backticked code inside
      the title, not a file path).
    - Deferred / dismissed items use a bullet-list variant:
      ``- **F19** — title text``.
    - File paths live on the line after the bold title, as a standalone
      backticked token like `` `src/lib/synthesis/mermaid-generator.ts:97` ``.
    """

    def test_all_27_findings_parsed(self, bmad_content_e5: str) -> None:
        findings = parse_bmad_review(bmad_content_e5)
        # Final Report line: "0 decision_needed · 22 patch · 2 defer · 3 dismiss"
        assert len(findings) == 27

    def test_patch_count_matches_report_header(self, bmad_content_e5: str) -> None:
        findings = parse_bmad_review(bmad_content_e5)
        patches = [f for f in findings if f.category == "patch"]
        assert len(patches) == 22

    def test_defer_count_matches_report_header(self, bmad_content_e5: str) -> None:
        findings = parse_bmad_review(bmad_content_e5)
        defers = [f for f in findings if f.category == "defer"]
        assert len(defers) == 2
        assert {f.ident for f in defers} == {"F19", "F27"}

    def test_dismiss_count_matches_report_header(self, bmad_content_e5: str) -> None:
        findings = parse_bmad_review(bmad_content_e5)
        dismissed = [f for f in findings if f.category == "dismiss"]
        assert len(dismissed) == 3
        assert {f.ident for f in dismissed} == {"F9", "F14", "F25"}

    def test_all_idents_are_F_prefixed(self, bmad_content_e5: str) -> None:
        findings = parse_bmad_review(bmad_content_e5)
        for f in findings:
            assert re.fullmatch(r"F\d+", f.ident), f"ident={f.ident!r}"

    def test_dedups_duplicated_body(self, bmad_content_e5: str) -> None:
        # Epic 5 file has the whole report duplicated — dedup by
        # (category, ident) must keep each finding exactly once.
        assert bmad_content_e5.count("## Epic 5 Code Review") == 2
        findings = parse_bmad_review(bmad_content_e5)
        keys = [(f.category, f.ident) for f in findings]
        assert len(keys) == len(set(keys))

    def test_file_paths_prefer_real_paths_over_code_symbols(
        self, bmad_content_e5: str,
    ) -> None:
        # F1's title contains three backticked code symbols
        # (`getDivergenceForStep`, `Array.includes()`, `.find()`),
        # none of which are file paths. The actual path lives on the
        # line below the title as ``src/lib/.../mermaid-generator.ts:97``.
        # The path extractor must skip the code symbols and find the
        # real path in the body.
        findings = parse_bmad_review(bmad_content_e5)
        f1 = next(f for f in findings if f.ident == "F1")
        assert "mermaid-generator.ts" in f1.file
        assert "getDivergenceForStep" not in f1.file

    def test_severity_subheading_does_not_reset_category(
        self, bmad_content_e5: str,
    ) -> None:
        # F2 lives under `## Patch Findings` → `### 🔴 Critical`.
        # If the severity H3 reset current_category to None the way
        # the old parser did for all H2 resets, F2 would parse with
        # empty category and be dropped entirely.
        findings = parse_bmad_review(bmad_content_e5)
        f2 = next(f for f in findings if f.ident == "F2")
        assert f2.category == "patch"

    def test_bullet_list_defer_item_parsed(self, bmad_content_e5: str) -> None:
        findings = parse_bmad_review(bmad_content_e5)
        f19 = next(f for f in findings if f.ident == "F19")
        assert f19.category == "defer"
        assert "getDivergentStepIds" in f19.title

    def test_source_is_bmad(self, bmad_content_e5: str) -> None:
        findings = parse_bmad_review(bmad_content_e5)
        assert all(f.source == "bmad" for f in findings)

    def test_sieve_routes_epic_5_correctly(
        self,
        bmad_content_e5: str,
        claude_content_e5: str,
    ) -> None:
        result = sieve_reviews(bmad_content_e5, claude_content_e5)
        claude_minors = sum(
            1 for f in result.claude_findings if f.category == "minor"
        )
        claude_high = sum(
            1 for f in result.claude_findings if f.category in ("major", "critical")
        )
        # 22 BMAD patches + Claude minors → Cat A
        # Claude major/critical → Cat B
        # 2 BMAD defers → defer (3 dismisses dropped)
        assert len(result.cat_a) == 22 + claude_minors
        assert len(result.cat_b) == claude_high
        assert len(result.defer) == 2
        assert result.has_any_findings

    def test_sieve_does_not_fall_back_on_epic_5(
        self,
        bmad_content_e5: str,
        claude_content_e5: str,
    ) -> None:
        # The format-drift guard in epic_graph._run_review_sieve fires
        # when a >1000-char BMAD file produces zero findings. Parsing
        # 22+ BMAD findings from the Epic 5 fixture means the sieve
        # handles this format natively and the expensive LLM fallback
        # does not run.
        assert len(bmad_content_e5) > 1000
        result = sieve_reviews(bmad_content_e5, claude_content_e5)
        assert len(result.bmad_findings) > 0


class TestEpic5SyntheticEdgeCases:
    """Small targeted tests for the new regexes that don't need fixtures."""

    def test_h2_patch_findings_classifies(self) -> None:
        content = (
            "## Patch Findings (22)\n\n"
            "### Critical\n\n"
            "**F1 — `foo()` is broken in `src/a.ts:10`**\n"
            "`src/a.ts:10`\n"
            "body text\n"
        )
        findings = parse_bmad_review(content)
        assert len(findings) == 1
        assert findings[0].category == "patch"
        assert findings[0].ident == "F1"

    def test_h2_deferred_findings_classifies(self) -> None:
        content = (
            "## Deferred Findings (1)\n\n"
            "- **F9** — deferred thing on `src/b.ts:5`\n"
        )
        findings = parse_bmad_review(content)
        assert len(findings) == 1
        assert findings[0].category == "defer"

    def test_h2_dismissed_findings_classifies(self) -> None:
        content = (
            "## Dismissed Findings (2)\n\n"
            "- **F1** — false positive\n"
            "- **F2** — also false positive\n"
        )
        findings = parse_bmad_review(content)
        # Dismissed items are parsed but the sieve drops them — this
        # tests the parser, not the routing.
        dismissed = [f for f in findings if f.category == "dismiss"]
        assert len(dismissed) == 2

    def test_whole_bold_format_with_backticks_in_title(self) -> None:
        content = (
            "## Patch Findings\n\n"
            "### Critical\n\n"
            "**F1 — `foo` uses `bar()` inside `baz()` — violation**\n"
            "`src/real/path.ts:42`\n"
            "explanation body\n"
        )
        findings = parse_bmad_review(content)
        assert len(findings) == 1
        # Title keeps all the backticked code symbols intact.
        assert "`foo`" in findings[0].title
        assert "`bar()`" in findings[0].title
        # File field prefers the path-like backtick in the body.
        assert findings[0].file == "src/real/path.ts:42"

    def test_severity_subheading_does_not_clobber_h2_category(self) -> None:
        content = (
            "## Patch Findings\n\n"
            "### Medium\n\n"
            "**F42 — something medium in `src/foo.ts`**\n"
            "`src/foo.ts:10`\n"
        )
        findings = parse_bmad_review(content)
        assert len(findings) == 1
        assert findings[0].category == "patch"

    def test_unclassified_h2_still_resets(self) -> None:
        # Without this, `**F1**` under "## Random Section" following
        # "## Patch Findings" would inherit "patch" incorrectly.
        content = (
            "## Patch Findings\n\n"
            "**[F1]** orphan item (no follow-up line)\n\n"
            "## Random Unrelated Section\n\n"
            "**[F2]** should NOT be classified as patch\n"
        )
        findings = parse_bmad_review(content)
        idents = {f.ident: f.category for f in findings}
        assert idents == {"F1": "patch"}  # F2 has no category → dropped

    def test_bullet_list_without_dash_still_parses(self) -> None:
        # Some variants might emit `- **F19** title` without an em-dash.
        content = (
            "## Deferred Findings\n\n"
            "- **F19** a defer item without em-dash\n"
            "- **F20** — another defer item with em-dash\n"
        )
        findings = parse_bmad_review(content)
        idents = {f.ident for f in findings}
        assert idents == {"F19", "F20"}
        assert all(f.category == "defer" for f in findings)

    def test_epic_5_preamble_triage_list_does_not_misclassify(self) -> None:
        # Epic 5 preamble contains lines like "- **F9**: ... **Dismiss**
        # (false positive)" BEFORE any H2 section. Those items should
        # not be emitted as findings (no enclosing category), since
        # the real classification comes later in the `## Dismissed
        # Findings` H2 section.
        content = (
            "**Triage classifications:**\n\n"
            "- **F9**: false positive. **Dismiss** (reason).\n"
            "- **F14**: different reason. **Dismiss**.\n\n"
            "## Dismissed Findings (2)\n\n"
            "- **F9** — real dismiss entry\n"
            "- **F14** — another real dismiss entry\n"
        )
        findings = parse_bmad_review(content)
        # Only the H2-classified entries survive — NOT 4 total.
        assert len(findings) == 2
        assert all(f.category == "dismiss" for f in findings)

    def test_path_extractor_ignores_code_symbols(self) -> None:
        from src.intake.review_sieve import _extract_first_backticked_path
        # Backticked code, no paths → returns empty.
        assert _extract_first_backticked_path(
            "`getDivergenceForStep` uses `Array.includes()`"
        ) == ""
        # Path present → wins over preceding code symbol.
        assert _extract_first_backticked_path(
            "`someFunction()` in `src/foo.ts:42`"
        ) == "src/foo.ts:42"
        # Bare extension at end of token → still recognized.
        assert _extract_first_backticked_path("`package.json`") == "package.json"
        # Path with line range.
        assert _extract_first_backticked_path(
            "`src/a/b/c.tsx:10`"
        ) == "src/a/b/c.tsx:10"

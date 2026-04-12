"""Tests for src/intake/review_sieve.py.

Fixtures are real Epic 3 review outputs captured from chat2bpmn on
2026-04-12 — the first time the factory produced epic-level BMAD
output with read-only tools. They exercise the parsers against content
that is deliberately duplicated (the BMAD skill emits its final report
twice) and contain all four BMAD triage categories.
"""

from __future__ import annotations

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


@pytest.fixture
def bmad_content() -> str:
    return BMAD_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def claude_content() -> str:
    return CLAUDE_FIXTURE.read_text(encoding="utf-8")


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

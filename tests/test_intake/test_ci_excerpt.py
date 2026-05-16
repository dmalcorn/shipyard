"""Tests for src/intake/ci_excerpt.py — CI failure-excerpt extraction."""

from __future__ import annotations

from src.intake.ci_excerpt import extract_ci_failure_excerpt


class TestExtractCiFailureExcerpt:
    """extract_ci_failure_excerpt anchors on test-runner failure summaries.

    Regression coverage for Epic 7 batch 1 (2026-05-14): the prior
    ``output[-2000:]`` slice surfaced late-flushed React act() warnings
    in the operator-facing halt message while the real Playwright
    Phase 4 failure summary sat ~85 KB earlier in the log.
    """

    def test_empty_returns_empty(self) -> None:
        assert extract_ci_failure_excerpt("") == ""

    def test_short_output_returned_verbatim(self) -> None:
        out = "short ci log\nno failures\n"
        assert extract_ci_failure_excerpt(out) == out

    def test_anchors_on_playwright_failed_summary(self) -> None:
        # Playwright-style log: failure summary followed by ~50 KB of
        # late-flushed stderr noise. The naive tail-slice misses the
        # failure; the helper should keep it.
        failure_block = (
            "=== Phase 4: E2E tests (Playwright) ===\n"
            "  1) browse.spec.ts:106 sort dropdown changes URL\n"
            "    Error: expect(page).toHaveURL failed\n"
            "  3 failed\n"
            "    [chromium] browse.spec.ts:103\n"
            "    [chromium] compare.spec.ts:136\n"
            "    [chromium] detail-why-this-recipe-snapshot.spec.ts:11\n"
        )
        noise = "An update to X was not wrapped in act(...).\n" * 2000
        out = failure_block + noise
        excerpt = extract_ci_failure_excerpt(out)
        assert "3 failed" in excerpt
        assert "browse.spec.ts:106" in excerpt

    def test_anchors_on_pytest_failed_summary(self) -> None:
        out = (
            "x" * 5000
            + "\n=========== 2 failed, 102 passed in 12.34s ===========\n"
            + "y" * 5000
        )
        excerpt = extract_ci_failure_excerpt(out)
        assert "2 failed" in excerpt

    def test_zero_failed_is_not_anchored(self) -> None:
        # "0 failed" in a passing summary must not be treated as a
        # failure anchor — the regex requires [1-9]\d*.
        out = (
            "real failure earlier: 5 failed\n"
            + "x" * 5000
            + "\nTests  0 failed | 462 passed\n"
        )
        excerpt = extract_ci_failure_excerpt(out)
        assert "5 failed" in excerpt

    def test_falls_back_to_tail_when_no_anchor(self) -> None:
        # No failure marker → preserve the prior behaviour (tail slice)
        # so unfamiliar test runners still produce a useful excerpt.
        out = "x" * 4000 + "\ndistinctive-tail-marker\n"
        excerpt = extract_ci_failure_excerpt(out)
        assert "distinctive-tail-marker" in excerpt
        assert len(excerpt) <= 2000

    def test_excerpt_capped_at_max_chars(self) -> None:
        # Leading newline before the failure block ensures the regex's
        # ``\b`` matches at "3" — without it, the surrounding ``x``
        # padding is a word char and no boundary exists.
        failure_block = "\n3 failed test_a test_b test_c\n"
        out = "x" * 5000 + failure_block + "y" * 5000
        excerpt = extract_ci_failure_excerpt(out, max_chars=500)
        # Allow the truncation prefix/suffix overhead.
        assert len(excerpt) <= 500 + len("[...truncated]\n[...truncated]") + 2
        assert "3 failed" in excerpt

"""CI failure-excerpt extraction.

Used by the operator-facing halt messages at every level — story
(``orchestrator.error_handler_node``), batch (``epic_graph.batch_ci_node``),
and epic-end (``epic_graph.epic_ci_node``) — to produce a useful slice
of a captured CI run instead of a blind ``output[-2000:]`` tail that
typically catches late-flushed warnings or pip notices.
"""

from __future__ import annotations

import re

# Test-runner failure summary anchors (Playwright "3 failed", pytest
# "1 failed, 102 passed", vitest "Tests  3 failed | ..."). Used to find
# the *actual* failure context in CI logs whose tails are polluted by
# late-flushed React act() warnings, pip upgrade notices, or compose
# teardown output. ``[1-9]\d*`` excludes "0 failed" passing summaries.
_CI_FAILURE_ANCHOR = re.compile(r"\b[1-9]\d*\s+failed\b", re.IGNORECASE)


def extract_ci_failure_excerpt(output: str, max_chars: int = 2000) -> str:
    """Return the most operator-relevant slice of a captured CI run.

    A blind ``output[-max_chars:]`` slice picks whatever stderr drained
    last — often React act() warnings or pip notices that postdate the
    real test-runner failure summary. This helper anchors on the last
    ``\\d+ failed`` marker and returns context centred on it; falls back
    to the tail when no marker is found.
    """
    if not output:
        return ""
    if len(output) <= max_chars:
        return output

    matches = list(_CI_FAILURE_ANCHOR.finditer(output))
    if not matches:
        return output[-max_chars:]

    # Bias toward lead-in: failure details (test names, stack frames)
    # appear before the summary line, not after.
    anchor = matches[-1].start()
    lead = int(max_chars * 0.75)
    start = max(0, anchor - lead)
    end = min(len(output), start + max_chars)
    prefix = "[...truncated]\n" if start > 0 else ""
    suffix = "\n[...truncated]" if end < len(output) else ""
    return f"{prefix}{output[start:end]}{suffix}"

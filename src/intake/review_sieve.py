"""Deterministic sieve for epic-level code review files.

Replaces the LLM-powered analyze-reviews agent with Python parsers that
route findings by the structured labels both reviewers already emit:

- BMAD reviewer runs the ``bmad-code-review`` skill, which triages every
  finding into ``patch`` / ``defer`` / ``dismiss`` / ``decision-needed``.
  Those map directly to Category A / defer / drop / Category B.
- Claude reviewer emits a Summary/Findings template with
  ``**Severity:** critical|major|minor``. ``critical``/``major`` route to
  Category B (architect), ``minor`` routes to Category A.

If either parser returns no findings — or the sieve hits a structural
problem it can't recover from — the caller should fall back to the
legacy LLM agent.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# BMAD triage buckets
BMAD_CATEGORIES = ("patch", "defer", "dismiss", "decision-needed")

# Claude severity buckets (factory-side severity taxonomy)
CLAUDE_SEVERITIES = ("critical", "major", "minor")

# Section heading -> BMAD category
_BMAD_SECTION_MAP = {
    "patch findings": "patch",
    "patch": "patch",
    "defer findings": "defer",
    "defer": "defer",
    "decision-needed": "decision-needed",
    "decision-needed findings": "decision-needed",
    "decision needed": "decision-needed",
    "decision needed findings": "decision-needed",
    "dismissed": "dismiss",
    "dismiss": "dismiss",
}

_BMAD_ITEM_TAG = re.compile(r"^\s*\*\*\[([A-Za-z]\d+)\]\*\*\s*(.*)$")
_BMAD_SECTION_HEADING = re.compile(r"^###\s+(.+?)(?:\s*\(.*?\))?\s*$")

_CLAUDE_FINDING_HEADING = re.compile(r"^###\s+(\d+)\.\s+(.*?)\s*$")
_CLAUDE_FIELD_LINE = re.compile(r"^\s*-\s*\*\*(?P<key>[A-Za-z /]+):\*\*\s*(?P<value>.*)$")


@dataclass
class Finding:
    """A single parsed review finding.

    ``category`` is the raw label from the reviewer. For BMAD it is one
    of :data:`BMAD_CATEGORIES`; for Claude it is one of
    :data:`CLAUDE_SEVERITIES`.
    """

    source: str  # "bmad" | "claude"
    ident: str  # "P1", "D3", "1", "2", ...
    title: str
    category: str
    file: str = ""
    body: str = ""

    def display_id(self) -> str:
        """Human-friendly ID for emitted markdown."""
        prefix = "B" if self.source == "bmad" else "C"
        return f"{prefix}{self.ident}"


@dataclass
class SieveResult:
    """Output of :func:`sieve_reviews`."""

    cat_a: list[Finding] = field(default_factory=list)
    cat_b: list[Finding] = field(default_factory=list)
    defer: list[Finding] = field(default_factory=list)
    bmad_findings: list[Finding] = field(default_factory=list)
    claude_findings: list[Finding] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def has_any_findings(self) -> bool:
        return bool(self.cat_a or self.cat_b or self.defer)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_bmad_review(content: str) -> list[Finding]:
    """Parse a ``bmad-code-review`` skill output into findings.

    Recognises the per-section format: ``### PATCH Findings`` /
    ``### DEFER Findings`` / ``### Dismissed`` / ``### Decision-Needed``
    containing items tagged ``**[P1]**``, ``**[D1]**``, etc. Dismissed
    findings are parsed only when they appear as tagged items — the
    reviewer sometimes collapses them into a single summary paragraph,
    which is fine because the sieve drops dismissed items anyway.

    The BMAD skill's output is sometimes emitted twice in the same file;
    this parser dedups by ``(category, ident)``.
    """
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    lines = content.splitlines()
    current_category: str | None = None
    pending: Finding | None = None

    def flush() -> None:
        nonlocal pending
        if pending is None:
            return
        key = (pending.category, pending.ident)
        if key not in seen:
            seen.add(key)
            pending.body = pending.body.strip()
            pending.file = _extract_first_backticked_path(pending.title) or pending.file
            findings.append(pending)
        pending = None

    for raw in lines:
        # Section boundary: any ### heading — resolve whether it's a BMAD category.
        heading_match = _BMAD_SECTION_HEADING.match(raw)
        if heading_match:
            flush()
            heading_text = heading_match.group(1).strip().lower()
            # Strip trailing count like "Dismissed (6)".
            heading_text = re.sub(r"\s*\(\d+\)\s*$", "", heading_text).strip()
            current_category = _BMAD_SECTION_MAP.get(heading_text)
            continue

        # Hard section reset on ## or --- separators.
        stripped = raw.strip()
        if stripped.startswith("## ") or stripped == "---":
            flush()
            if stripped.startswith("## "):
                current_category = None
            continue

        if current_category is None:
            continue

        tag_match = _BMAD_ITEM_TAG.match(raw)
        if tag_match:
            flush()
            ident, rest = tag_match.group(1), tag_match.group(2).strip()
            pending = Finding(
                source="bmad",
                ident=ident,
                title=rest,
                category=current_category,
            )
            continue

        if pending is not None:
            pending.body += raw + "\n"

    flush()
    return findings


def parse_claude_review(content: str) -> list[Finding]:
    """Parse a Claude-template review into findings.

    Expects the ``## Findings`` section containing numbered subsections
    (``### 1. Title``) with ``- **File:**``, ``- **Severity:**``,
    ``- **Issue:**``, ``- **Action:**`` bullets. Dedups by finding
    number across duplicated content blocks.
    """
    findings: list[Finding] = []
    seen: set[str] = set()

    in_findings_section = False
    pending: Finding | None = None
    body_buffer: list[str] = []

    def flush() -> None:
        nonlocal pending, body_buffer
        if pending is None:
            return
        if pending.ident in seen:
            pending = None
            body_buffer = []
            return
        # Default to "minor" when severity is missing — safer to route
        # to Category A than to escalate to the architect unnecessarily.
        if pending.category not in CLAUDE_SEVERITIES:
            pending.category = "minor"
        pending.body = "\n".join(body_buffer).strip()
        seen.add(pending.ident)
        findings.append(pending)
        pending = None
        body_buffer = []

    for raw in content.splitlines():
        stripped = raw.strip()

        if stripped.startswith("## "):
            flush()
            in_findings_section = stripped.lower().startswith("## findings")
            continue

        if not in_findings_section:
            continue

        heading = _CLAUDE_FINDING_HEADING.match(raw)
        if heading:
            flush()
            pending = Finding(
                source="claude",
                ident=heading.group(1),
                title=heading.group(2).strip(),
                category="",
            )
            continue

        if pending is None:
            continue

        field_match = _CLAUDE_FIELD_LINE.match(raw)
        if field_match:
            key = field_match.group("key").strip().lower()
            value = field_match.group("value").strip()
            if key == "file":
                pending.file = _strip_backticks(value)
            elif key == "severity":
                sev = value.lower().split()[0] if value else ""
                if sev in CLAUDE_SEVERITIES:
                    pending.category = sev
            body_buffer.append(raw)
            continue

        body_buffer.append(raw)

    flush()
    return findings


def _extract_first_backticked_path(text: str) -> str:
    match = re.search(r"`([^`]+)`", text)
    return match.group(1).strip() if match else ""


def _strip_backticks(text: str) -> str:
    return text.strip().strip("`").strip()


# ---------------------------------------------------------------------------
# Sieve + writers
# ---------------------------------------------------------------------------


def sieve_reviews(bmad_content: str, claude_content: str) -> SieveResult:
    """Parse both review files and route findings into pipeline buckets.

    Routing:

    - BMAD ``patch`` → Category A
    - BMAD ``decision-needed`` → Category B
    - BMAD ``defer`` → defer bucket (deferred-work.md, no agent)
    - BMAD ``dismiss`` → dropped
    - Claude ``minor`` → Category A
    - Claude ``major`` / ``critical`` → Category B
    """
    result = SieveResult()

    try:
        result.bmad_findings = parse_bmad_review(bmad_content)
    except Exception as e:  # pragma: no cover — defensive
        logger.exception("BMAD review parse failed")
        result.parse_errors.append(f"bmad: {e}")

    try:
        result.claude_findings = parse_claude_review(claude_content)
    except Exception as e:  # pragma: no cover — defensive
        logger.exception("Claude review parse failed")
        result.parse_errors.append(f"claude: {e}")

    for f in result.bmad_findings:
        if f.category == "patch":
            result.cat_a.append(f)
        elif f.category == "decision-needed":
            result.cat_b.append(f)
        elif f.category == "defer":
            result.defer.append(f)
        # dismiss → dropped intentionally

    for f in result.claude_findings:
        if f.category in ("major", "critical"):
            result.cat_b.append(f)
        elif f.category == "minor":
            result.cat_a.append(f)

    return result


def render_category_file(
    category_label: str,
    epic_num: str,
    findings: list[Finding],
    empty_sentinel: str,
) -> str:
    """Render a Category A or Category B markdown file."""
    if not findings:
        return f"{empty_sentinel}\n"

    lines = [
        f"# {category_label} — Epic {epic_num}",
        "",
        f"{len(findings)} items.",
        "",
        "---",
        "",
    ]
    for f in findings:
        lines.append(f"## {f.display_id()} — {f.title}")
        lines.append("")
        if f.file:
            lines.append(f"- **File:** `{f.file}`")
        lines.append(f"- **Source:** {f.source}")
        if f.source == "claude" and f.category in CLAUDE_SEVERITIES:
            lines.append(f"- **Severity:** {f.category}")
        lines.append("")
        if f.body:
            lines.append(f.body)
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def append_deferred_work(
    deferred_path: str,
    epic_num: str,
    findings: list[Finding],
) -> None:
    """Append defer items to ``deferred-work.md`` using BMAD's convention.

    Creates the file (with parent dirs) if it doesn't exist yet.
    """
    if not findings:
        return

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    header = f"## Deferred from: code review of epic-{epic_num} ({today})"

    body_lines = [header, ""]
    for f in findings:
        title = f.title.strip().rstrip(".")
        first_paragraph = _first_paragraph(f.body)
        if first_paragraph:
            body_lines.append(f"- **{title}**: {first_paragraph}")
        else:
            body_lines.append(f"- **{title}**")
    body_lines.append("")

    os.makedirs(os.path.dirname(deferred_path), exist_ok=True)
    preamble = "# Deferred Work\n\n" if not os.path.exists(deferred_path) else ""

    with open(deferred_path, "a", encoding="utf-8") as fh:
        if preamble:
            fh.write(preamble)
        fh.write("\n".join(body_lines))
        fh.write("\n")


def _first_paragraph(body: str) -> str:
    for chunk in body.strip().split("\n\n"):
        text = chunk.strip()
        if text:
            return " ".join(line.strip() for line in text.splitlines())
    return ""


def render_analysis_file(
    epic_num: str,
    result: SieveResult,
    bmad_path: str,
    claude_path: str,
) -> str:
    """Render a short analysis.md summarising the sieve's routing."""
    lines = [
        f"# Review Analysis — Epic {epic_num}",
        "",
        "Produced by the deterministic review sieve — no LLM analysis.",
        "",
        "## Inputs",
        "",
        f"- BMAD review: `{bmad_path}`",
        f"- Claude review: `{claude_path}`",
        "",
        "## Routing Summary",
        "",
        f"- BMAD findings parsed: {len(result.bmad_findings)}",
        f"- Claude findings parsed: {len(result.claude_findings)}",
        f"- Category A (clear fix): {len(result.cat_a)}",
        f"- Category B (architect review): {len(result.cat_b)}",
        f"- Deferred: {len(result.defer)}",
        "",
    ]

    if result.cat_a:
        lines += ["## Category A", ""]
        for f in result.cat_a:
            lines.append(f"- **{f.display_id()}** ({f.source}/{f.category}) — {f.title}")
        lines.append("")

    if result.cat_b:
        lines += ["## Category B", ""]
        for f in result.cat_b:
            lines.append(f"- **{f.display_id()}** ({f.source}/{f.category}) — {f.title}")
        lines.append("")

    if result.defer:
        lines += ["## Deferred", ""]
        for f in result.defer:
            lines.append(f"- **{f.display_id()}** ({f.source}/{f.category}) — {f.title}")
        lines.append("")

    return "\n".join(lines)

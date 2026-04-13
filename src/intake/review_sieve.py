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

# Ident pattern used across every item-tag regex. Letters + optional
# hyphen + digits matches every form BMAD has emitted so far:
#   P1, F01, D3                    (Epic 3 / Epic 4 / Epic 5)
#   P-01, D-01, M1, S1, L1         (Epic 7 / Epic 8)
_BMAD_IDENT = r"[A-Za-z]+-?\d+"

# Matches an item line in the Epic 3 / Epic 4 BMAD formats:
#   **[P1]** description            (Epic 3 style)
#   **F01** `[patch]` description   (Epic 4 style)
# The optional brackets around the ident are tolerated, and the rest of
# the line (including any inline category marker) is captured as group 2.
_BMAD_ITEM_TAG = re.compile(rf"^\s*\*\*\[?({_BMAD_IDENT})\]?\*\*\s*(.*)$")

# Matches the Epic 5 BMAD detail-section format where the whole
# "ident — title" span is inside a single bold:
#   **F1 — `getDivergenceForStep` uses `Array.includes()` ...**
# The dash separator can be em-dash, en-dash, or hyphen. Greedy match
# on the title keeps any inner backticked code intact.
_BMAD_ITEM_TAG_WHOLE_BOLD = re.compile(
    rf"^\s*\*\*({_BMAD_IDENT})\s*[\u2014\u2013\-]\s*(.+)\*\*\s*$",
)

# Matches the Epic 5 BMAD deferred/dismissed-section format:
#   - **F19** — `getDivergentStepIds` called twice per render ...
#   - **D-01**: `getDivergenceBadgeLabel` cross-module import ...  (Epic 7)
#   - **[D-1]** `usePanZoom` stale closure ...                      (Epic 9)
# The ident is bolded on its own (optionally wrapped in square
# brackets), followed by an em-dash, colon, or space separator, and
# the rest of the line as plain text. Appears as a markdown bullet.
_BMAD_ITEM_TAG_BULLET = re.compile(
    rf"^\s*[-*+]\s+\*\*\[?({_BMAD_IDENT})\]?\*\*\s*[\u2014\u2013\-:]?\s*(.*)$",
)

# Matches the Epic 8 BMAD format where findings are H3 headings with
# a bracketed ident:
#   ### [M1] IDOR: `approve` action approves any synthesis result
#   ### [S1] `handleRouteError` hard-codes error codes
# Required: `### ` + `[ident]` + title text. Must be tried BEFORE
# `_BMAD_SECTION_HEADING` so H3 finding lines are not swallowed as
# section headings.
_BMAD_ITEM_TAG_H3 = re.compile(
    rf"^###\s+\[({_BMAD_IDENT})\]\s+(.+?)\s*$",
)

# Matches the Epic 9 BMAD format where the whole "ident + title" span
# is inside a single bold, with the ident in square brackets:
#   **[P-1] `handleSynthSvgClick` can false-positive on step ID substrings**
#   **[D-2] Pre-existing type duplication**
# Distinct from `_BMAD_ITEM_TAG_WHOLE_BOLD` (Epic 5) which requires a
# dash separator. Distinct from `_BMAD_ITEM_TAG` (Epic 3) which has
# the closing `**` right after the ident, not at end of line.
_BMAD_ITEM_TAG_BRACKET_BOLD = re.compile(
    rf"^\s*\*\*\[({_BMAD_IDENT})\]\s+(.+)\*\*\s*$",
)

# Matches a markdown table row from the Epic 7 format:
#   | 🔴 Critical | P-01 | **Zoom buttons non-functional** — ... | `bpmn-chart.tsx:75-101` |
# The ident column may or may not be bolded. Separator rows
# (``| --- | --- | ... |``) and header rows (no ident cell) are
# rejected by `_parse_bmad_table_row` below.
_MD_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_BMAD_TABLE_IDENT_CELL = re.compile(rf"^\**({_BMAD_IDENT})\**$")

# Matches an inline BMAD category marker like `[patch]`, `[defer]`, etc.
# The BMAD skill's Step 3 triage vocabulary is the authoritative source:
# whatever appears in backticked brackets on a finding line is the
# finding's category, regardless of how the enclosing section is named.
_BMAD_INLINE_CATEGORY = re.compile(
    r"`\[(patch|defer|dismiss|decision[-\s]needed)\]`",
    re.IGNORECASE,
)

# Section heading — matches H2 (##) or H3 (###). Group 1 is the hash
# marks so the caller can distinguish the level; group 2 is the text.
#
# H2 classification matters for the Epic 5 BMAD format, which groups
# findings under `## Patch Findings (22)` / `## Deferred Findings (2)`
# / `## Dismissed Findings (3)` H2 headings, with `### Critical /
# High / Medium` *severity* subheadings underneath. Both levels are
# matched; classification of an H3 that doesn't contain a triage
# keyword leaves the enclosing H2's category in place (rather than
# resetting to None, which would drop every Epic-5-style finding).
_BMAD_SECTION_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$")

_CLAUDE_FINDING_HEADING = re.compile(r"^###\s+(\d+)\.\s+(.*?)\s*$")
_CLAUDE_FIELD_LINE = re.compile(r"^\s*-\s*\*\*(?P<key>[A-Za-z /]+):\*\*\s*(?P<value>.*)$")


def _classify_bmad_heading(heading_text: str) -> str | None:
    """Return the BMAD category a section heading belongs to, or None.

    Keyword-based so we handle format drift across BMAD skill versions:

    - Epic 3: ``### PATCH Findings`` / ``### DEFER Findings``
    - Epic 4: ``### CRITICAL / HIGH — Patch Required`` / ``### DEFERRED``
    - Epic 5: ``## Patch Findings (22)`` / ``## Deferred Findings``
    - Epic 7: ``### Patch Findings by Priority`` / ``### Deferred``
    - Epic 8: ``## MUST FIX — CRITICAL / HIGH`` / ``## SHOULD FIX`` /
      ``## MONITOR (Low Severity)`` — no patch/defer vocabulary at all

    The authoritative triage vocabulary is still ``patch``/``defer``/
    ``dismiss``/``decision-needed``; those are checked first. Drift
    vocabulary observed in the wild is mapped to the closest bucket:

    - ``must fix`` / ``should fix`` → ``patch`` (both are fixable items)
    - ``monitor`` → ``defer`` (low-severity items to track, not drop)

    In practice the inline per-item marker takes precedence over the
    section heading anyway — this is a safety net, not the main path.
    """
    text = heading_text.lower()
    if "patch" in text:
        return "patch"
    if "defer" in text:
        return "defer"
    if "dismiss" in text:
        return "dismiss"
    if "decision" in text and "need" in text:
        return "decision-needed"
    # Drift vocabulary — Epic 8 emitted MUST FIX / SHOULD FIX / MONITOR
    # instead of the canonical triage buckets. Map to the closest bucket.
    if "must fix" in text or "should fix" in text:
        return "patch"
    if "monitor" in text:
        return "defer"
    return None


def _extract_inline_bmad_category(text: str) -> str | None:
    """Return the normalized BMAD category found in a `[tag]`, or None."""
    match = _BMAD_INLINE_CATEGORY.search(text)
    if not match:
        return None
    raw = match.group(1).lower()
    # Normalize "decision needed" and "decision-needed" to the canonical form.
    return "decision-needed" if raw.startswith("decision") else raw


def _parse_bmad_table_row(raw: str) -> tuple[str, str, str] | None:
    """Return ``(ident, title, file)`` if the line is a BMAD-style table row.

    Epic 7 emitted findings as markdown tables with a layout like::

        | Priority    | ID   | Finding                    | File             |
        |-------------|------|----------------------------|------------------|
        | 🔴 Critical | P-01 | **Zoom buttons broken** ...| `bpmn-chart.tsx` |

    The ident column may or may not be bolded. Header rows (no cell
    that looks like an ident) and separator rows (only dashes and
    colons) are rejected — they return ``None``.
    """
    match = _MD_TABLE_ROW.match(raw)
    if not match:
        return None
    cells = [c.strip() for c in match.group(1).split("|")]
    if len(cells) < 3:
        return None
    # Reject separator rows: all cells are dashes / colons / empty.
    if all(not c or re.fullmatch(r":?-+:?", c) for c in cells):
        return None

    ident: str | None = None
    ident_idx: int | None = None
    for i, cell in enumerate(cells):
        ident_match = _BMAD_TABLE_IDENT_CELL.match(cell)
        if ident_match:
            ident = ident_match.group(1)
            ident_idx = i
            break
    if ident is None or ident_idx is None:
        return None

    title_cell = cells[ident_idx + 1] if ident_idx + 1 < len(cells) else ""
    # Strip a leading `**bold**` wrapper from the title if present —
    # the title field in later emitted markdown is rendered naked.
    title_cell = title_cell.strip()

    file_path = ""
    for cell in cells[ident_idx + 2:]:
        candidate = _extract_first_backticked_path(cell)
        if candidate:
            file_path = candidate
            break

    return ident, title_cell, file_path


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

    Handles three known item formats:

    1. **Epic 3 style** — ``**[P1]** ...`` inside a ``### PATCH Findings``
       (or similar) section. Category comes from the section heading.
    2. **Epic 4 style** — ``**F01** `[patch]` ...`` with the category
       tagged inline on the item. Category comes from the inline tag.
    3. **Epic 5 style** — ``**F1 — ...**`` (whole ident + title inside
       one bold), grouped under ``## Patch Findings (22)`` /
       ``## Deferred Findings (2)`` / ``## Dismissed Findings (3)``
       H2 headings, with ``### Critical / High / Medium`` severity
       *subsections* underneath. No inline category tag — the
       category comes from the enclosing H2 heading.

    The inline tag takes precedence over the section heading when both
    are present. Items without either a section heading or an inline
    tag are ignored. The skill's output is sometimes duplicated in the
    same file; dedup is by ``(category, ident)``.
    """
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    lines = content.splitlines()
    current_category: str | None = None
    pending: Finding | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal pending, body_lines
        if pending is None:
            return
        # Late binding: if the item had no inline category and no section
        # category was known at the time it was opened, try once more from
        # anything that appeared in the body (some formats bury the tag
        # on the second line).
        if not pending.category:
            inline = _extract_inline_bmad_category("\n".join(body_lines))
            if inline:
                pending.category = inline
        if pending.category:
            key = (pending.category, pending.ident)
            if key not in seen:
                seen.add(key)
                pending.body = "\n".join(body_lines).strip()
                pending.file = (
                    _extract_first_backticked_path(pending.title)
                    or _extract_first_backticked_path(pending.body)
                    or pending.file
                )
                findings.append(pending)
        pending = None
        body_lines = []

    for raw in lines:
        # Epic 8 format: findings are H3 headings with bracketed idents
        # (``### [M1] title``). Tried BEFORE the generic section-heading
        # match so these lines are treated as items, not headings.
        h3_item_match = _BMAD_ITEM_TAG_H3.match(raw)
        if h3_item_match:
            flush()
            ident, rest = h3_item_match.group(1), h3_item_match.group(2).strip()
            inline_category = _extract_inline_bmad_category(rest)
            category = inline_category or current_category or ""
            pending = Finding(
                source="bmad",
                ident=ident,
                title=rest,
                category=category,
            )
            continue

        heading_match = _BMAD_SECTION_HEADING.match(raw)
        if heading_match:
            flush()
            hashes = heading_match.group(1)
            heading_text = heading_match.group(2).strip()
            # Strip trailing count like "Dismissed (6)" or "Patch Findings (22)".
            heading_text = re.sub(r"\s*\(\d+\)\s*$", "", heading_text).strip()
            classified = _classify_bmad_heading(heading_text)
            if classified:
                current_category = classified
            elif len(hashes) == 2:
                # Unclassified H2 — assume we've moved into a new top-level
                # section ("## Summary", "## Code Review Complete", etc.)
                # and reset so later items don't inherit the old category.
                current_category = None
            # Unclassified H3 (e.g. "### 🔴 Critical" under a classified
            # H2 "## Patch Findings") → keep the H2 category in place.
            continue

        # Hard section reset on --- separators.
        stripped = raw.strip()
        if stripped == "---":
            flush()
            continue

        # Try the Epic 5 detail-section format first (whole-title
        # bold with a required dash separator inside the span — the
        # most specific pattern).
        tag_match = _BMAD_ITEM_TAG_WHOLE_BOLD.match(raw)
        if tag_match:
            flush()
            ident, rest = tag_match.group(1), tag_match.group(2).strip()
            inline_category = _extract_inline_bmad_category(rest)
            category = inline_category or current_category or ""
            pending = Finding(
                source="bmad",
                ident=ident,
                title=rest,
                category=category,
            )
            continue

        # Epic 9 format: whole-line bold with bracketed ident, space
        # separator (no dash required):
        #   **[P-1] `handleSynthSvgClick` can false-positive on substrings**
        tag_match = _BMAD_ITEM_TAG_BRACKET_BOLD.match(raw)
        if tag_match:
            flush()
            ident, rest = tag_match.group(1), tag_match.group(2).strip()
            inline_category = _extract_inline_bmad_category(rest)
            category = inline_category or current_category or ""
            pending = Finding(
                source="bmad",
                ident=ident,
                title=rest,
                category=category,
            )
            continue

        # Epic 5 deferred/dismissed-section bullet format:
        #   - **F19** — title text
        # The ident is its own bold, preceded by a bullet. Tried
        # before the Epic 3 / Epic 4 plain-bold pattern because the
        # latter's leading `\s*` can't eat the bullet character.
        tag_match = _BMAD_ITEM_TAG_BULLET.match(raw)
        if tag_match:
            flush()
            ident, rest = tag_match.group(1), tag_match.group(2).strip()
            inline_category = _extract_inline_bmad_category(rest)
            category = inline_category or current_category or ""
            pending = Finding(
                source="bmad",
                ident=ident,
                title=rest,
                category=category,
            )
            continue

        # Epic 3 / Epic 4 ident-only-bold pattern:
        #   **[P1]** description            (Epic 3)
        #   **F01** `[patch]` description   (Epic 4)
        tag_match = _BMAD_ITEM_TAG.match(raw)
        if tag_match:
            flush()
            ident, rest = tag_match.group(1), tag_match.group(2).strip()
            # Inline marker on the item line always wins.
            inline_category = _extract_inline_bmad_category(rest)
            category = inline_category or current_category or ""
            pending = Finding(
                source="bmad",
                ident=ident,
                title=rest,
                category=category,
            )
            continue

        # Epic 7 markdown-table format:
        #   | 🔴 Critical | P-01 | **Zoom buttons broken** — ... | `file.ts` |
        # Only consumed when inside a classified section — random
        # tables in summary sections won't produce orphan findings.
        if current_category:
            table_item = _parse_bmad_table_row(raw)
            if table_item:
                flush()
                ident, title, file_path = table_item
                inline_category = _extract_inline_bmad_category(title)
                category = inline_category or current_category
                pending = Finding(
                    source="bmad",
                    ident=ident,
                    title=title,
                    category=category,
                    file=file_path,
                )
                continue

        if pending is not None:
            body_lines.append(raw)

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
    """Return the first backticked token that looks like a file path.

    Scans every backticked token in order and returns the first one
    that contains a path separator (``/``) or a short trailing file
    extension (e.g. ``.ts``, ``.tsx``, ``.py``, optionally followed
    by ``:line`` or ``:line-line``). Returns ``""`` if nothing in the
    text looks like a path — the caller then falls through to the next
    source (title → body), rather than recording a code-symbol backtick
    (e.g. ```` `getDivergenceForStep` ````) as the finding's file field.
    """
    for match in re.finditer(r"`([^`]+)`", text):
        candidate = match.group(1).strip()
        if "/" in candidate or re.search(
            r"\.\w{1,4}(?::\d+(?:-\d+)?)?$", candidate,
        ):
            return candidate
    return ""


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

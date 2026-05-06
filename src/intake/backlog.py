"""Backlog parser for intake pipeline output.

Parses the epics source from a target project into a structured list of
epics and stories that the rebuild orchestrator can iterate over.

Two source forms are supported (both BMAD-canonical):

- **Single-file form** — `_bmad-output/planning-artifacts/epics.md` with
  `## Epic N: Title` and `### Story N.M: Title` headings (H2/H3).

- **Sharded form** — `_bmad-output/planning-artifacts/epics/` directory
  containing one `epic-NN-*.md` shard per epic, with `# Epic N: Title`
  and `## Story N.M: Title` headings (H1/H2). The headings shift up one
  level because each shard is a standalone file. Support files like
  `index.md`, `overview.md`, `functional-requirements-inventory.md` etc.
  are ignored — only `epic-[0-9]*.md` shards are parsed. This is what
  BMAD's `bmad-shard-doc` skill produces.

If both forms exist, the single-file form wins (delete `epics.md` if you
want the factory to use the sharded form).

Identification scheme:
  - Epics: numbered "Epic 1", "Epic 2", etc.
  - Stories: dash-separated "1-1", "1-2", "2-1" (epic_num-story_num)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


_SHARD_NAME_RE = re.compile(r"^epic-(\d+)")


def load_backlog(target_dir: str) -> list[dict[str, str | list[str]]]:
    """Parse epics source from the target directory into a structured backlog.

    Accepts either `epics.md` (single-file) or `epics/` (sharded BMAD form);
    see module docstring.

    Args:
        target_dir: Path to the target project directory (i.e., the directory
            containing `_bmad-output/planning-artifacts/`).

    Returns:
        List of dicts with keys: epic_num, epic_name, story_id, story_name,
        description, acceptance_criteria.

    Raises:
        FileNotFoundError: If neither form is present in target_dir.
    """
    content, heading_level = _read_epics_source(target_dir)
    return parse_epics_markdown(content, heading_level=heading_level)


def _read_epics_source(target_dir: str) -> tuple[str, int]:
    """Locate and read the epics source.

    Returns (markdown_content, heading_level) — the heading_level tells
    parse_epics_markdown which heading levels carry the Epic / Story
    structure (2 for mono, 1 for sharded).
    """
    base = Path(target_dir) / "_bmad-output" / "planning-artifacts"
    epics_file = base / "epics.md"
    epics_dir = base / "epics"

    if epics_file.is_file():
        return epics_file.read_text(encoding="utf-8"), 2

    if epics_dir.is_dir():
        shards = sorted(
            epics_dir.glob("epic-[0-9]*.md"),
            key=lambda p: _shard_sort_key(p.name),
        )
        if not shards:
            raise FileNotFoundError(
                f"No epic-NN-*.md shards found in {epics_dir}/"
            )
        joined = "\n\n".join(s.read_text(encoding="utf-8") for s in shards)
        return joined, 1

    raise FileNotFoundError(
        f"Epics source not found: expected {epics_file} or {epics_dir}/"
    )


def _shard_sort_key(filename: str) -> tuple[int, str]:
    """Sort epic shards numerically: epic-2-... before epic-10-... ."""
    m = _SHARD_NAME_RE.match(filename)
    if m:
        return (int(m.group(1)), filename)
    return (0, filename)


def parse_epics_markdown(
    content: str, heading_level: int = 2
) -> list[dict[str, str | list[str]]]:
    """Parse epics markdown content into structured backlog entries.

    Expected format (with default heading_level=2):
        ## Epic N: Title          or  ## Epic N — Title
        ### Story N.M: Title      or  ### Story N.M — Title
        **As a** ..., **I want** ..., **so that** ...
        **Acceptance Criteria:**
        - ...

    For sharded BMAD files, pass heading_level=1; the epic header becomes
    `# Epic N` and stories become `## Story N.M`.

    Args:
        content: Raw markdown string.
        heading_level: Markdown heading level of the Epic header. Story
            headers sit at heading_level + 1.

    Returns:
        List of dicts with keys: epic_num, epic_name, story_id, story_name,
        description, acceptance_criteria.
    """
    epic_prefix = "#" * heading_level
    story_prefix = "#" * (heading_level + 1)
    epic_re = re.compile(
        rf"^{epic_prefix}\s+Epic\s+(\d+)(?::|[\s—]+)\s*(.+)"
    )
    story_re = re.compile(
        rf"^{story_prefix}\s+Story\s+(\d+)[.\-](\d+)(?::|[\s—]+)\s*(.+)"
    )

    backlog: list[dict[str, str | list[str]]] = []
    current_epic_num = ""
    current_epic_name = ""
    current_story_id = ""
    current_story_name = ""
    current_description = ""
    current_criteria: list[str] = []
    in_criteria = False
    story_counter = 0  # counts stories within current epic

    for line in content.split("\n"):
        stripped = line.strip()

        epic_match = epic_re.match(stripped)
        if epic_match:
            # Save previous story if exists
            if current_story_id:
                backlog.append(
                    _make_entry(
                        current_epic_num,
                        current_epic_name,
                        current_story_id,
                        current_story_name,
                        current_description,
                        current_criteria,
                    )
                )
            current_epic_num = epic_match.group(1).strip()
            current_epic_name = epic_match.group(2).strip()
            current_story_id = ""
            current_story_name = ""
            current_description = ""
            current_criteria = []
            in_criteria = False
            story_counter = 0
            continue

        # Match story headers — supports both "1.1" and "1-1" separators
        story_match = story_re.match(stripped)
        if story_match:
            # Save previous story if exists
            if current_story_id:
                backlog.append(
                    _make_entry(
                        current_epic_num,
                        current_epic_name,
                        current_story_id,
                        current_story_name,
                        current_description,
                        current_criteria,
                    )
                )
            epic_num_from_story = story_match.group(1)
            story_num = story_match.group(2)
            current_story_name = story_match.group(3).strip()
            # Use the epic number from the story header (e.g., "1" from "1.2")
            # but fall back to the current epic if not set
            if not current_epic_num:
                current_epic_num = epic_num_from_story
            # Build dash-separated story ID: "1-2", "2-1"
            current_story_id = f"{current_epic_num}-{story_num}"
            story_counter += 1
            current_description = ""
            current_criteria = []
            in_criteria = False
            continue

        # Match user story lines (may span multiple lines)
        if stripped.startswith("**As a**"):
            current_description = stripped
            in_criteria = False
            continue
        if stripped.startswith(("**I want**", "**So that**")):
            current_description += " " + stripped
            continue

        # Match acceptance criteria header
        if stripped.startswith("**Acceptance Criteria:**"):
            in_criteria = True
            continue

        # Match technical notes header (end of criteria)
        if stripped.startswith("**Technical Notes:**"):
            in_criteria = False
            continue

        # Collect criteria lines (only top-level bullets, not indented sub-bullets)
        if in_criteria and line.startswith("- "):
            current_criteria.append(stripped[2:])  # Strip "- " prefix

    # Save last story
    if current_story_id:
        backlog.append(
            _make_entry(
                current_epic_num,
                current_epic_name,
                current_story_id,
                current_story_name,
                current_description,
                current_criteria,
            )
        )

    if not backlog and content.strip():
        logger.warning(
            "parse_epics_markdown returned 0 entries from %d lines of input",
            len(content.split("\n")),
        )

    return backlog


def _make_entry(
    epic_num: str,
    epic_name: str,
    story_id: str,
    story_name: str,
    description: str,
    acceptance_criteria: list[str],
) -> dict[str, str | list[str]]:
    """Create a backlog entry dict."""
    return {
        "epic_num": epic_num,
        "epic_name": epic_name,
        "story_id": story_id,
        "story_name": story_name,
        "description": description,
        "acceptance_criteria": list(acceptance_criteria),
    }

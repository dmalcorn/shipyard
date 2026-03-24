"""Backlog parser for intake pipeline output.

Parses the generated epics.md file into a structured list of
epics and stories that the rebuild orchestrator can iterate over.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def load_backlog(target_dir: str) -> list[dict[str, str | list[str]]]:
    """Parse epics.md from the target directory into a structured backlog.

    Expected markdown format:
        ## Epic N: Title
        ### Story N.M: Title
        **As a** ..., **I want** ..., **so that** ...
        **Acceptance Criteria:**
        - **Given** ... **When** ... **Then** ...
        **Technical Notes:**
        - ...

    Args:
        target_dir: Path to directory containing epics.md.

    Returns:
        List of dicts with keys: epic, story, description, acceptance_criteria.

    Raises:
        FileNotFoundError: If epics.md does not exist in target_dir.
    """
    epics_path = Path(target_dir) / "epics.md"
    if not epics_path.exists():
        raise FileNotFoundError(f"Backlog file not found: {epics_path}")

    content = epics_path.read_text(encoding="utf-8")

    return parse_epics_markdown(content)


def parse_epics_markdown(content: str) -> list[dict[str, str | list[str]]]:
    """Parse epics markdown content into structured backlog entries.

    Args:
        content: Raw markdown string from epics.md.

    Returns:
        List of dicts with keys: epic, story, description, acceptance_criteria.
    """
    backlog: list[dict[str, str | list[str]]] = []
    current_epic = ""
    current_story = ""
    current_description = ""
    current_criteria: list[str] = []
    in_criteria = False

    for line in content.split("\n"):
        stripped = line.strip()

        # Match epic headers: ## Epic N: Title
        epic_match = re.match(r"^##\s+Epic\s+\d+:\s*(.+)", stripped)
        if epic_match:
            # Save previous story if exists
            if current_story:
                backlog.append(
                    _make_entry(
                        current_epic,
                        current_story,
                        current_description,
                        current_criteria,
                    )
                )
            current_epic = epic_match.group(1).strip()
            current_story = ""
            current_description = ""
            current_criteria = []
            in_criteria = False
            continue

        # Match story headers: ### Story N.M: Title
        story_match = re.match(r"^###\s+Story\s+[\d.]+:\s*(.+)", stripped)
        if story_match:
            # Save previous story if exists
            if current_story:
                backlog.append(
                    _make_entry(
                        current_epic,
                        current_story,
                        current_description,
                        current_criteria,
                    )
                )
            current_story = story_match.group(1).strip()
            current_description = ""
            current_criteria = []
            in_criteria = False
            continue

        # Match user story line
        if stripped.startswith("**As a**"):
            current_description = stripped
            in_criteria = False
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
    if current_story:
        backlog.append(
            _make_entry(
                current_epic,
                current_story,
                current_description,
                current_criteria,
            )
        )

    return backlog


def _make_entry(
    epic: str,
    story: str,
    description: str,
    acceptance_criteria: list[str],
) -> dict[str, str | list[str]]:
    """Create a backlog entry dict."""
    return {
        "epic": epic,
        "story": story,
        "description": description,
        "acceptance_criteria": list(acceptance_criteria),
    }

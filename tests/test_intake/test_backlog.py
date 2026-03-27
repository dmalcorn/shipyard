"""Tests for src/intake/backlog.py — epics.md parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.intake.backlog import load_backlog, parse_epics_markdown

SAMPLE_EPICS_MD = """\
## Epic 1: Authentication

### Story 1.1: User Login
**As a** user, **I want** to log in, **so that** I can access my account.

**Acceptance Criteria:**
- **Given** valid credentials **When** I submit the login form **Then** I am authenticated
- **Given** invalid credentials **When** I submit the login form **Then** I see an error

**Technical Notes:**
- Use bcrypt for password hashing

### Story 1.2: User Registration
**As a** user, **I want** to register, **so that** I can create an account.

**Acceptance Criteria:**
- **Given** valid details **When** I submit registration **Then** my account is created

**Technical Notes:**
- Email validation required

## Epic 2: Dashboard

### Story 2.1: View Dashboard
**As a** user, **I want** to see a dashboard, **so that** I can view my data.

**Acceptance Criteria:**
- **Given** I am logged in **When** I navigate to dashboard **Then** I see my data
"""


class TestParseEpicsMarkdown:
    """parse_epics_markdown() parses structured markdown into backlog entries."""

    def test_parses_multiple_epics_and_stories(self) -> None:
        """Parses 2 epics with 3 total stories."""
        result = parse_epics_markdown(SAMPLE_EPICS_MD)
        assert len(result) == 3

    def test_first_story_has_correct_epic(self) -> None:
        """First story belongs to Epic 1."""
        result = parse_epics_markdown(SAMPLE_EPICS_MD)
        assert result[0]["epic_num"] == "1"
        assert result[0]["epic_name"] == "Authentication"

    def test_first_story_has_correct_id(self) -> None:
        """First story has dash-separated ID."""
        result = parse_epics_markdown(SAMPLE_EPICS_MD)
        assert result[0]["story_id"] == "1-1"
        assert result[0]["story_name"] == "User Login"

    def test_first_story_has_description(self) -> None:
        """First story has user story description."""
        result = parse_epics_markdown(SAMPLE_EPICS_MD)
        assert "**As a** user" in result[0]["description"]

    def test_first_story_has_acceptance_criteria(self) -> None:
        """First story has 2 acceptance criteria."""
        result = parse_epics_markdown(SAMPLE_EPICS_MD)
        criteria = result[0]["acceptance_criteria"]
        assert isinstance(criteria, list)
        assert len(criteria) == 2
        assert "valid credentials" in criteria[0]

    def test_second_epic_story(self) -> None:
        """Third story belongs to Epic 2."""
        result = parse_epics_markdown(SAMPLE_EPICS_MD)
        assert result[2]["epic_num"] == "2"
        assert result[2]["story_id"] == "2-1"
        assert result[2]["story_name"] == "View Dashboard"

    def test_empty_content_returns_empty_list(self) -> None:
        """Empty markdown returns empty list."""
        assert parse_epics_markdown("") == []

    def test_no_stories_returns_empty_list(self) -> None:
        """Markdown with no story headers returns empty list."""
        assert parse_epics_markdown("# Just a heading\nSome text") == []

    def test_em_dash_separators(self) -> None:
        """Supports em-dash separators in headers."""
        md = """\
## Epic 1 \u2014 Auth

### Story 1.1 \u2014 Login
**As a** user, **I want** to log in, **so that** I can access my account.

**Acceptance Criteria:**
- Given valid creds When I login Then I am in
"""
        result = parse_epics_markdown(md)
        assert len(result) == 1
        assert result[0]["epic_num"] == "1"
        assert result[0]["story_id"] == "1-1"
        assert result[0]["story_name"] == "Login"


class TestLoadBacklog:
    """load_backlog() reads and parses epics.md from a directory."""

    def test_loads_from_directory(self, tmp_path: Path) -> None:
        """Reads epics.md from target directory."""
        pa = tmp_path / "_bmad-output" / "planning-artifacts"
        pa.mkdir(parents=True)
        (pa / "epics.md").write_text(SAMPLE_EPICS_MD, encoding="utf-8")
        result = load_backlog(str(tmp_path))
        assert len(result) == 3
        assert result[0]["story_id"] == "1-1"

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when epics.md doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Backlog file not found"):
            load_backlog(str(tmp_path))

"""Tests for src/intake/backlog.py — epics source parser."""

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

# Sharded form: each shard has H1 epic + H2 stories (heading_level=1).
SHARD_EPIC_1 = """\
# Epic 1: Authentication

**Goal:** Get auth working.

## Story 1.1: User Login
**As a** user, **I want** to log in, **so that** I can access my account.

**Acceptance Criteria:**
- **Given** valid creds **When** I login **Then** I am in

## Story 1.2: User Registration
**As a** user, **I want** to register, **so that** I can create an account.

**Acceptance Criteria:**
- **Given** valid details **When** I register **Then** account is created
"""

SHARD_EPIC_2 = """\
# Epic 2: Dashboard

## Story 2.1: View Dashboard
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
## Epic 1 — Auth

### Story 1.1 — Login
**As a** user, **I want** to log in, **so that** I can access my account.

**Acceptance Criteria:**
- Given valid creds When I login Then I am in
"""
        result = parse_epics_markdown(md)
        assert len(result) == 1
        assert result[0]["epic_num"] == "1"
        assert result[0]["story_id"] == "1-1"
        assert result[0]["story_name"] == "Login"

    def test_heading_level_1_for_sharded_form(self) -> None:
        """heading_level=1 parses # Epic N / ## Story N.M (sharded form)."""
        result = parse_epics_markdown(SHARD_EPIC_1, heading_level=1)
        assert len(result) == 2
        assert result[0]["epic_num"] == "1"
        assert result[0]["epic_name"] == "Authentication"
        assert result[0]["story_id"] == "1-1"
        assert result[1]["story_id"] == "1-2"

    def test_heading_level_2_does_not_match_h1_headings(self) -> None:
        """Default level=2 must NOT pick up H1 headings from a shard."""
        # If we point the default parser at a shard, it should find zero
        # epics — protects against confusing the two forms.
        result = parse_epics_markdown(SHARD_EPIC_1)  # default heading_level=2
        assert result == []


class TestLoadBacklog:
    """load_backlog() reads either form from a target directory."""

    def test_loads_from_single_file_form(self, tmp_path: Path) -> None:
        """Reads epics.md from target directory."""
        pa = tmp_path / "_bmad-output" / "planning-artifacts"
        pa.mkdir(parents=True)
        (pa / "epics.md").write_text(SAMPLE_EPICS_MD, encoding="utf-8")
        result = load_backlog(str(tmp_path))
        assert len(result) == 3
        assert result[0]["story_id"] == "1-1"

    def test_loads_from_sharded_form(self, tmp_path: Path) -> None:
        """Reads epics/ directory of shards from target directory."""
        epics_dir = tmp_path / "_bmad-output" / "planning-artifacts" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "epic-01-auth.md").write_text(SHARD_EPIC_1, encoding="utf-8")
        (epics_dir / "epic-02-dashboard.md").write_text(SHARD_EPIC_2, encoding="utf-8")
        result = load_backlog(str(tmp_path))
        assert len(result) == 3
        assert result[0]["story_id"] == "1-1"
        assert result[2]["story_id"] == "2-1"
        assert result[2]["epic_name"] == "Dashboard"

    def test_sharded_form_skips_non_epic_shards(self, tmp_path: Path) -> None:
        """Files in epics/ that don't match epic-NN-*.md are ignored."""
        epics_dir = tmp_path / "_bmad-output" / "planning-artifacts" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "epic-01-auth.md").write_text(SHARD_EPIC_1, encoding="utf-8")
        # Support files BMAD shard-doc creates — must be skipped.
        (epics_dir / "index.md").write_text("# TOC\nNot an epic", encoding="utf-8")
        (epics_dir / "overview.md").write_text("# Overview", encoding="utf-8")
        (epics_dir / "epic-structure-overview.md").write_text(
            "# Structure\nNot a shard", encoding="utf-8"
        )
        result = load_backlog(str(tmp_path))
        assert len(result) == 2  # only the 2 stories from epic-01
        assert all(r["epic_num"] == "1" for r in result)

    def test_sharded_form_sorts_numerically(self, tmp_path: Path) -> None:
        """Shards are processed in numeric (not lexical) order: epic-2 before epic-10."""
        epics_dir = tmp_path / "_bmad-output" / "planning-artifacts" / "epics"
        epics_dir.mkdir(parents=True)
        # Without numeric sort, 'epic-10-...' would sort before 'epic-2-...'
        # Use minimal shards so we just check the order.
        (epics_dir / "epic-2-second.md").write_text(
            "# Epic 2: Second\n## Story 2.1: One\n", encoding="utf-8"
        )
        (epics_dir / "epic-10-tenth.md").write_text(
            "# Epic 10: Tenth\n## Story 10.1: One\n", encoding="utf-8"
        )
        result = load_backlog(str(tmp_path))
        assert [r["epic_num"] for r in result] == ["2", "10"]

    def test_single_file_form_wins_when_both_exist(self, tmp_path: Path) -> None:
        """If both epics.md and epics/ exist, the single-file form wins."""
        pa = tmp_path / "_bmad-output" / "planning-artifacts"
        pa.mkdir(parents=True)
        (pa / "epics.md").write_text(SAMPLE_EPICS_MD, encoding="utf-8")
        epics_dir = pa / "epics"
        epics_dir.mkdir()
        (epics_dir / "epic-01-different.md").write_text(
            "# Epic 99: SHOULD NOT BE READ\n## Story 99.1: ignored\n",
            encoding="utf-8",
        )
        result = load_backlog(str(tmp_path))
        # Came from epics.md (3 stories), not the 1-shard fake epics/ dir
        assert len(result) == 3
        assert all(r["epic_num"] in ("1", "2") for r in result)

    def test_raises_when_no_source_present(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when neither form is present."""
        with pytest.raises(FileNotFoundError, match="Epics source not found"):
            load_backlog(str(tmp_path))

    def test_raises_when_sharded_dir_is_empty(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError when epics/ has no epic-*-*.md shards."""
        epics_dir = tmp_path / "_bmad-output" / "planning-artifacts" / "epics"
        epics_dir.mkdir(parents=True)
        (epics_dir / "index.md").write_text("# TOC", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="No epic-NN-.*\\.md shards"):
            load_backlog(str(tmp_path))

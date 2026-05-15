"""Tests for role definitions, tool subsets, and trace metadata in src/multi_agent/roles.py."""

from __future__ import annotations

import pytest

from src.multi_agent.roles import (
    ARCHITECT_ROLE,
    DEV_ROLE,
    FIX_DEV_ROLE,
    REVIEWER_ROLE,
    ROLES,
    TEST_ROLE,
    build_trace_config,
    get_role,
)


class TestBuildTraceConfig:
    """Tests for build_trace_config function."""

    def test_returns_dict_with_configurable_and_metadata(self) -> None:
        """Config dict contains both configurable and metadata keys."""
        result = build_trace_config(
            session_id="sess-1",
            agent_role="dev",
            task_id="story-42",
            model_id="claude-sonnet-4-6",
            phase="implementation",
        )
        assert "configurable" in result
        assert "metadata" in result

    def test_thread_id_matches_session_id(self) -> None:
        """Configurable thread_id is set to the provided session_id."""
        result = build_trace_config(
            session_id="sess-abc",
            agent_role="dev",
            task_id="task-1",
            model_id="claude-haiku-4-5",
            phase="test",
        )
        assert result["configurable"]["thread_id"] == "sess-abc"

    def test_metadata_fields_populated(self) -> None:
        """All required metadata fields are present and correct."""
        result = build_trace_config(
            session_id="sess-1",
            agent_role="reviewer",
            task_id="story-7",
            model_id="claude-opus-4-6",
            phase="review",
        )
        meta = result["metadata"]
        assert meta["agent_role"] == "reviewer"
        assert meta["task_id"] == "story-7"
        assert meta["model_id"] == "claude-opus-4-6"
        assert meta["phase"] == "review"

    def test_parent_session_omitted_by_default(self) -> None:
        """When parent_session is None, it is not in metadata."""
        result = build_trace_config(
            session_id="sess-1",
            agent_role="dev",
            task_id="task-1",
            model_id="claude-sonnet-4-6",
            phase="implementation",
        )
        assert "parent_session" not in result["metadata"]

    def test_parent_session_included_when_provided(self) -> None:
        """When parent_session is given, it appears in metadata."""
        result = build_trace_config(
            session_id="child-sess",
            agent_role="test",
            task_id="task-2",
            model_id="claude-haiku-4-5",
            phase="test",
            parent_session="parent-sess",
        )
        assert result["metadata"]["parent_session"] == "parent-sess"

    def test_invalid_agent_role_raises(self) -> None:
        """Invalid agent_role raises ValueError."""
        with pytest.raises(ValueError, match="agent_role"):
            build_trace_config(
                session_id="s",
                agent_role="invalid",
                task_id="t",
                model_id="claude-sonnet-4-6",
                phase="test",
            )

    def test_invalid_model_id_raises(self) -> None:
        """Invalid model_id raises ValueError."""
        with pytest.raises(ValueError, match="model_id"):
            build_trace_config(
                session_id="s",
                agent_role="dev",
                task_id="t",
                model_id="gpt4",
                phase="test",
            )

    def test_invalid_phase_raises(self) -> None:
        """Invalid phase raises ValueError."""
        with pytest.raises(ValueError, match="phase"):
            build_trace_config(
                session_id="s",
                agent_role="dev",
                task_id="t",
                model_id="claude-sonnet-4-6",
                phase="deploy",
            )

    def test_all_valid_agent_roles(self) -> None:
        """All defined agent roles are accepted."""
        for role in ("dev", "test", "reviewer", "architect", "fix_dev"):
            result = build_trace_config(
                session_id="s",
                agent_role=role,
                task_id="t",
                model_id="claude-sonnet-4-6",
                phase="implementation",
            )
            assert result["metadata"]["agent_role"] == role

    def test_all_valid_model_ids(self) -> None:
        """All defined model IDs are accepted."""
        for model_id in ("claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"):
            result = build_trace_config(
                session_id="s",
                agent_role="dev",
                task_id="t",
                model_id=model_id,
                phase="implementation",
            )
            assert result["metadata"]["model_id"] == model_id

    def test_all_valid_phases(self) -> None:
        """All defined phases are accepted."""
        for phase in (
            "test",
            "implementation",
            "review",
            "fix",
            "ci",
            "architect",
            "post_fix_test",
            "post_fix_ci",
        ):
            result = build_trace_config(
                session_id="s",
                agent_role="dev",
                task_id="t",
                model_id="claude-sonnet-4-6",
                phase=phase,
            )
            assert result["metadata"]["phase"] == phase


class TestAgentRoleDataclass:
    """Tests for AgentRole dataclass and role constants."""

    def test_dev_role_model_id(self) -> None:
        """Dev Agent uses Sonnet."""
        assert DEV_ROLE.model_id == "claude-sonnet-4-6"

    def test_test_role_model_id(self) -> None:
        """Test Agent uses Sonnet."""
        assert TEST_ROLE.model_id == "claude-sonnet-4-6"

    def test_reviewer_role_model_id(self) -> None:
        """Reviewer Agent uses Sonnet."""
        assert REVIEWER_ROLE.model_id == "claude-sonnet-4-6"

    def test_architect_role_model_id(self) -> None:
        """Architect Agent uses Opus."""
        assert ARCHITECT_ROLE.model_id == "claude-opus-4-6"

    def test_fix_dev_role_model_id(self) -> None:
        """Fix Dev Agent uses Sonnet."""
        assert FIX_DEV_ROLE.model_id == "claude-sonnet-4-6"

    def test_dev_role_has_all_tools(self) -> None:
        """Dev Agent has full tool access."""
        expected = {
            "read_file",
            "edit_file",
            "write_file",
            "list_files",
            "search_files",
            "run_command",
        }
        assert set(DEV_ROLE.tools) == expected

    def test_test_role_no_edit_file(self) -> None:
        """Test Agent cannot edit source files (no edit_file)."""
        assert "edit_file" not in TEST_ROLE.tools

    def test_reviewer_role_no_edit_no_bash(self) -> None:
        """Reviewer has no edit_file and no run_command."""
        assert "edit_file" not in REVIEWER_ROLE.tools
        assert "run_command" not in REVIEWER_ROLE.tools

    def test_architect_role_no_edit_no_bash(self) -> None:
        """Architect has no edit_file and no run_command."""
        assert "edit_file" not in ARCHITECT_ROLE.tools
        assert "run_command" not in ARCHITECT_ROLE.tools

    def test_fix_dev_role_matches_dev_tools(self) -> None:
        """Fix Dev has the same tools as Dev."""
        assert set(FIX_DEV_ROLE.tools) == set(DEV_ROLE.tools)

    def test_dev_role_unrestricted_writes(self) -> None:
        """Dev Agent has no write restrictions."""
        assert DEV_ROLE.write_restrictions == ()

    def test_reviewer_role_restricted_to_reviews(self) -> None:
        """Reviewer can only write to reviews/."""
        assert REVIEWER_ROLE.write_restrictions == ("reviews/",)

    def test_architect_role_restricted_to_reviews_and_fix_plan(self) -> None:
        """Architect can write to reviews/ and fix-plan.md."""
        assert ARCHITECT_ROLE.write_restrictions == ("reviews/", "fix-plan.md")

    def test_test_role_restricted_to_tests(self) -> None:
        """Test Agent can only write to tests/."""
        assert TEST_ROLE.write_restrictions == ("tests/",)

    def test_all_roles_registered(self) -> None:
        """All five roles are registered in ROLES dict."""
        assert set(ROLES.keys()) == {"dev", "test", "reviewer", "architect", "fix_dev"}

    def test_role_dataclass_is_frozen(self) -> None:
        """AgentRole instances are immutable."""
        with pytest.raises(AttributeError):
            DEV_ROLE.name = "hacked"  # type: ignore[misc]

    def test_role_model_ids_are_api_aliases(self) -> None:
        """All role model IDs are valid Anthropic API aliases."""
        valid = {"claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"}
        for role in ROLES.values():
            assert role.model_id in valid, f"{role.name} has invalid model_id {role.model_id!r}"


class TestGetRole:
    """Tests for get_role() lookup function."""

    def test_get_role_dev(self) -> None:
        """get_role('dev') returns DEV_ROLE."""
        assert get_role("dev") is DEV_ROLE

    def test_get_role_reviewer(self) -> None:
        """get_role('reviewer') returns REVIEWER_ROLE."""
        assert get_role("reviewer") is REVIEWER_ROLE

    def test_get_role_invalid_raises(self) -> None:
        """Unknown role name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown role"):
            get_role("invalid")

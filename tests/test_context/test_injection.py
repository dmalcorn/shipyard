"""Tests for the context injection system (Story 1.5).

Covers:
- build_system_prompt: Layer 1 context assembly (AC #1, #4)
- inject_task_context: Layer 2 task-specific context (AC #2)
- Role differentiation: different roles produce different prompts (AC #4)
- Layer 3 availability: tools exist for on-demand context (AC #3)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from src.agent.prompts import (
    ARCHITECT_AGENT_PROMPT,
    DEV_AGENT_PROMPT,
    REVIEW_AGENT_PROMPT,
    TEST_AGENT_PROMPT,
    get_prompt,
)
from src.context.injection import build_system_prompt, inject_task_context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_coding_standards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Create a temporary coding-standards.md and point injection at it."""
    import src.context.injection as inj

    standards_file = os.path.join(str(tmp_path), "coding-standards.md")
    with open(standards_file, "w", encoding="utf-8") as f:
        f.write("# Test Standards\n- Use snake_case\n- Type hints required\n")
    monkeypatch.setattr(inj, "CODING_STANDARDS_PATH", standards_file)
    return standards_file


@pytest.fixture()
def tmp_context_file(tmp_path: Path) -> str:
    """Create a temporary context file for Layer 1/2 tests."""
    ctx_file = os.path.join(str(tmp_path), "task-spec.md")
    with open(ctx_file, "w", encoding="utf-8") as f:
        f.write("# Task Spec\nImplement the widget module.\n")
    return ctx_file


# ---------------------------------------------------------------------------
# Task 3 tests: get_prompt / prompt templates
# ---------------------------------------------------------------------------


class TestGetPrompt:
    """Tests for src/agent/prompts.get_prompt."""

    def test_returns_dev_prompt(self) -> None:
        assert get_prompt("dev") == DEV_AGENT_PROMPT

    def test_returns_reviewer_prompt(self) -> None:
        assert get_prompt("reviewer") == REVIEW_AGENT_PROMPT

    def test_returns_test_prompt(self) -> None:
        assert get_prompt("test") == TEST_AGENT_PROMPT

    def test_returns_architect_prompt(self) -> None:
        assert get_prompt("architect") == ARCHITECT_AGENT_PROMPT

    def test_unknown_role_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown agent role"):
            get_prompt("unknown_role")

    def test_dev_prompt_has_required_sections(self) -> None:
        prompt = get_prompt("dev")
        for section in ("## Role", "## Constraints", "## Process", "## Output"):
            assert section in prompt

    def test_reviewer_prompt_forbids_source_edits(self) -> None:
        prompt = get_prompt("reviewer")
        assert "CANNOT edit source files" in prompt

    def test_dev_and_reviewer_prompts_differ(self) -> None:
        """AC #4: different roles produce demonstrably different prompts."""
        assert get_prompt("dev") != get_prompt("reviewer")


# ---------------------------------------------------------------------------
# Task 1 tests: build_system_prompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    """Tests for src/context/injection.build_system_prompt."""

    def test_includes_role_description(self, tmp_coding_standards: str) -> None:
        result = build_system_prompt("dev")
        assert "Dev Agent" in result

    def test_includes_coding_standards(self, tmp_coding_standards: str) -> None:
        """AC #1: coding standards are in the system prompt."""
        result = build_system_prompt("dev")
        assert "## Coding Standards" in result
        assert "snake_case" in result

    def test_includes_additional_context_files(
        self, tmp_coding_standards: str, tmp_context_file: str
    ) -> None:
        result = build_system_prompt("dev", context_files=[tmp_context_file])
        assert "## Context: task-spec.md" in result
        assert "widget module" in result

    def test_reviewer_prompt_differs_from_dev(self, tmp_coding_standards: str) -> None:
        """AC #4: same function, different role → different output."""
        dev_prompt = build_system_prompt("dev")
        review_prompt = build_system_prompt("reviewer")
        assert dev_prompt != review_prompt
        assert "Dev Agent" in dev_prompt
        assert "Review Agent" in review_prompt

    def test_unknown_role_raises(self, tmp_coding_standards: str) -> None:
        with pytest.raises(ValueError, match="Unknown agent role"):
            build_system_prompt("nonexistent")

    def test_missing_coding_standards_still_returns_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gracefully handles missing coding-standards.md."""
        import src.context.injection as inj

        monkeypatch.setattr(inj, "CODING_STANDARDS_PATH", "/nonexistent/path.md")
        result = build_system_prompt("dev")
        assert "Dev Agent" in result
        assert "Coding Standards" not in result

    def test_missing_context_file_shows_not_available(self, tmp_coding_standards: str) -> None:
        result = build_system_prompt("dev", context_files=["/no/such/file.md"])
        assert "Dev Agent" in result
        assert "(file not available)" in result


# ---------------------------------------------------------------------------
# Task 2 tests: inject_task_context
# ---------------------------------------------------------------------------


class TestInjectTaskContext:
    """Tests for src/context/injection.inject_task_context."""

    def test_returns_human_message_list(self) -> None:
        result = inject_task_context("Do the thing")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], HumanMessage)

    def test_instruction_in_message(self) -> None:
        result = inject_task_context("Fix the bug")
        assert "## Instruction" in result[0].content
        assert "Fix the bug" in result[0].content

    def test_context_files_prepended(self, tmp_context_file: str) -> None:
        """AC #2: task-specific files are read and included."""
        result = inject_task_context("Implement feature", context_files=[tmp_context_file])
        content = result[0].content
        assert "## Context: task-spec.md" in content
        assert "widget module" in content
        # Instruction comes after context
        ctx_pos = content.index("## Context:")
        instr_pos = content.index("## Instruction")
        assert ctx_pos < instr_pos

    def test_missing_context_file_shows_not_available(self) -> None:
        result = inject_task_context("Do X", context_files=["/no/such/file.md"])
        assert "(file not available)" in result[0].content

    def test_no_context_files_just_instruction(self) -> None:
        result = inject_task_context("Just do it")
        content = result[0].content
        assert content == "## Instruction\nJust do it"


# ---------------------------------------------------------------------------
# AC #3: Layer 3 — tools exist for on-demand context
# ---------------------------------------------------------------------------


class TestBuildSystemPromptWorkingDir:
    """Tests for build_system_prompt with working_dir parameter (Story 4.5, AC#1)."""

    def test_resolves_context_files_relative_to_working_dir(
        self, tmp_coding_standards: str, tmp_path: Path
    ) -> None:
        """Context files with relative paths are resolved against working_dir."""
        target_dir = tmp_path / "target_project"
        target_dir.mkdir()
        ctx_file = target_dir / "src" / "main.py"
        ctx_file.parent.mkdir(parents=True)
        ctx_file.write_text("print('hello')", encoding="utf-8")

        result = build_system_prompt(
            "dev", context_files=["src/main.py"], working_dir=str(target_dir)
        )
        assert "print('hello')" in result
        assert "## Context: main.py" in result

    def test_without_working_dir_uses_cwd(self, tmp_coding_standards: str) -> None:
        """Without working_dir, relative paths resolve against CWD (existing behavior)."""
        result = build_system_prompt("dev", context_files=["nonexistent_file.py"])
        assert "(file not available)" in result

    def test_absolute_paths_unaffected_by_working_dir(
        self, tmp_coding_standards: str, tmp_context_file: str
    ) -> None:
        """Absolute context file paths are not affected by working_dir."""
        result = build_system_prompt(
            "dev",
            context_files=[tmp_context_file],
            working_dir="/some/other/dir",
        )
        assert "widget module" in result


class TestInjectTaskContextWorkingDir:
    """Tests for inject_task_context with working_dir parameter (Story 4.5, AC#1)."""

    def test_resolves_context_files_relative_to_working_dir(self, tmp_path: Path) -> None:
        """Context files with relative paths are resolved against working_dir."""
        target_dir = tmp_path / "target_project"
        target_dir.mkdir()
        ctx_file = target_dir / "docs" / "spec.md"
        ctx_file.parent.mkdir(parents=True)
        ctx_file.write_text("# Spec\nDo the thing.", encoding="utf-8")

        result = inject_task_context(
            "Implement it",
            context_files=["docs/spec.md"],
            working_dir=str(target_dir),
        )
        content = result[0].content
        assert "Do the thing." in content
        assert "## Context: spec.md" in content

    def test_without_working_dir_relative_paths_fail(self) -> None:
        """Without working_dir, relative paths that don't exist show not available."""
        result = inject_task_context("Do X", context_files=["nonexistent/file.md"])
        assert "(file not available)" in result[0].content


class TestLayer3ToolsAvailable:
    """AC #3: Read, Grep, Glob tools are available for on-demand context."""

    def test_read_file_tool_exists(self) -> None:
        from src.tools.file_ops import read_file

        assert read_file is not None
        assert hasattr(read_file, "invoke")

    def test_search_files_tool_exists(self) -> None:
        from src.tools.search import search_files

        assert search_files is not None
        assert hasattr(search_files, "invoke")

    def test_list_files_tool_exists(self) -> None:
        from src.tools.search import list_files

        assert list_files is not None
        assert hasattr(list_files, "invoke")

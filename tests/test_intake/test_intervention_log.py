"""Tests for the intervention log module."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.intake.intervention_log import (
    InterventionEntry,
    InterventionLogger,
    build_intervention_needed_response,
    cli_intervention_prompt,
    process_api_intervention,
)


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for log files."""
    return tmp_path


@pytest.fixture
def logger(log_dir: Path) -> InterventionLogger:
    """Provide an InterventionLogger writing to a temp directory."""
    return InterventionLogger(log_path=str(log_dir / "intervention-log.md"))


@pytest.fixture
def sample_entry() -> InterventionEntry:
    """Provide a sample InterventionEntry."""
    return InterventionEntry(
        timestamp="2026-03-24T14:30:00Z",
        epic="Epic 1: Project Setup",
        story="Story 1.2: Auth Module",
        pipeline_phase="unit_test",
        failure_report="Test failed: ModuleNotFoundError in test_auth.py",
        what_broke=(
            "Test Agent generated tests that import a module the Dev Agent hadn't created yet."
        ),
        what_developer_did=(
            "Manually created the missing auth/__init__.py with the expected interface."
        ),
        agent_limitation="The agent struggles with cross-module dependencies.",
        retry_counts="edit=2/3, test=5/5, CI=1/3",
        files_involved=["src/auth/__init__.py", "tests/test_auth.py"],
    )


class TestInterventionEntry:
    """Tests for InterventionEntry dataclass."""

    def test_creation_with_all_fields(self, sample_entry: InterventionEntry) -> None:
        """All required fields are set on construction."""
        assert sample_entry.timestamp == "2026-03-24T14:30:00Z"
        assert sample_entry.epic == "Epic 1: Project Setup"
        assert sample_entry.story == "Story 1.2: Auth Module"
        assert sample_entry.pipeline_phase == "unit_test"
        assert sample_entry.failure_report == "Test failed: ModuleNotFoundError in test_auth.py"
        assert sample_entry.what_broke.startswith("Test Agent")
        assert sample_entry.what_developer_did.startswith("Manually")
        assert sample_entry.agent_limitation.startswith("The agent")
        assert sample_entry.retry_counts == "edit=2/3, test=5/5, CI=1/3"
        assert sample_entry.files_involved == ["src/auth/__init__.py", "tests/test_auth.py"]

    def test_files_involved_is_list(self, sample_entry: InterventionEntry) -> None:
        """files_involved must be a list of strings."""
        assert isinstance(sample_entry.files_involved, list)
        assert all(isinstance(f, str) for f in sample_entry.files_involved)


class TestInterventionLogger:
    """Tests for InterventionLogger class."""

    def test_log_intervention_creates_file(
        self, logger: InterventionLogger, sample_entry: InterventionEntry
    ) -> None:
        """log_intervention creates the log file if it doesn't exist."""
        logger.log_intervention(sample_entry)
        assert Path(logger.log_path).exists()

    def test_log_intervention_appends_entry(
        self, logger: InterventionLogger, sample_entry: InterventionEntry
    ) -> None:
        """log_intervention appends a correctly formatted entry."""
        logger.log_intervention(sample_entry)
        content = Path(logger.log_path).read_text(encoding="utf-8")

        assert "## Intervention #1" in content
        assert "**Timestamp:** 2026-03-24T14:30:00Z" in content
        assert "**Epic/Story:** Epic 1: Project Setup / Story 1.2: Auth Module" in content
        assert "**Pipeline Phase:** unit_test" in content
        assert "**Retry Counts:** edit=2/3, test=5/5, CI=1/3" in content
        assert "**What Broke:**" in content
        assert "**What Developer Did:**" in content
        assert "**Agent Limitation:**" in content
        assert "**Files Involved:**" in content
        assert "`src/auth/__init__.py`" in content

    def test_log_intervention_increments_count(
        self, logger: InterventionLogger, sample_entry: InterventionEntry
    ) -> None:
        """Multiple interventions are numbered sequentially."""
        logger.log_intervention(sample_entry)
        logger.log_intervention(sample_entry)
        content = Path(logger.log_path).read_text(encoding="utf-8")

        assert "## Intervention #1" in content
        assert "## Intervention #2" in content

    def test_log_auto_recovery_appends_entry(self, logger: InterventionLogger) -> None:
        """log_auto_recovery appends a correctly formatted auto-recovery entry."""
        logger.log_auto_recovery(
            epic="Epic 1: Project Setup",
            story="Story 1.3: Database Setup",
            phase="ci",
            what_failed="Ruff flagged unused import in generated code",
            how_recovered="Dev Agent removed the unused import on retry (CI cycle 2/3)",
        )
        content = Path(logger.log_path).read_text(encoding="utf-8")

        assert "## Auto-Recovery #1" in content
        assert "**Epic/Story:** Epic 1: Project Setup / Story 1.3: Database Setup" in content
        assert "**Pipeline Phase:** ci" in content
        assert "**What Failed:**" in content
        assert "**How Recovered:**" in content

    def test_log_auto_recovery_increments_count(self, logger: InterventionLogger) -> None:
        """Multiple auto-recoveries are numbered sequentially."""
        logger.log_auto_recovery("E1", "S1", "ci", "fail1", "fix1")
        logger.log_auto_recovery("E2", "S2", "test", "fail2", "fix2")
        content = Path(logger.log_path).read_text(encoding="utf-8")

        assert "## Auto-Recovery #1" in content
        assert "## Auto-Recovery #2" in content

    def test_get_summary_empty(self, logger: InterventionLogger) -> None:
        """get_summary returns zeros when no entries logged."""
        summary = logger.get_summary()
        assert summary["total_interventions"] == 0
        assert summary["total_auto_recoveries"] == 0
        assert summary["interventions_by_phase"] == {}

    def test_get_summary_with_entries(
        self, logger: InterventionLogger, sample_entry: InterventionEntry
    ) -> None:
        """get_summary returns correct counts after logging entries."""
        logger.log_intervention(sample_entry)
        logger.log_auto_recovery("E1", "S1", "ci", "fail", "fix")

        summary = logger.get_summary()
        assert summary["total_interventions"] == 1
        assert summary["total_auto_recoveries"] == 1
        assert summary["interventions_by_phase"] == {"unit_test": 1}

    def test_get_summary_multiple_phases(self, logger: InterventionLogger) -> None:
        """get_summary groups intervention counts by phase."""
        for phase in ["unit_test", "unit_test", "ci", "review"]:
            entry = InterventionEntry(
                timestamp="2026-03-24T14:30:00Z",
                epic="E1",
                story="S1",
                pipeline_phase=phase,
                failure_report="fail",
                what_broke="broke",
                what_developer_did="fixed",
                agent_limitation="limit",
                retry_counts="edit=1/3",
                files_involved=["f.py"],
            )
            logger.log_intervention(entry)

        summary = logger.get_summary()
        assert summary["interventions_by_phase"] == {"unit_test": 2, "ci": 1, "review": 1}

    def test_export_for_analysis_structure(
        self, logger: InterventionLogger, sample_entry: InterventionEntry
    ) -> None:
        """export_for_analysis returns structured summary string."""
        logger.log_intervention(sample_entry)
        logger.log_auto_recovery("E1", "S1", "ci", "fail", "fix")

        export = logger.export_for_analysis()
        assert isinstance(export, str)
        assert "Intervention Frequency by Pipeline Phase" in export
        assert "Agent Limitation Categories" in export
        assert "Auto-Recovery Success Rate" in export

    def test_log_format_matches_markdown_structure(
        self, logger: InterventionLogger, sample_entry: InterventionEntry
    ) -> None:
        """Log file has correct markdown header and structure."""
        logger.log_intervention(sample_entry)
        content = Path(logger.log_path).read_text(encoding="utf-8")

        assert content.startswith("# Ship App Rebuild — Intervention Log\n")
        assert "## Summary" in content
        assert "---" in content

    def test_required_fields_non_empty(self) -> None:
        """InterventionEntry validates that required fields are non-empty."""
        with pytest.raises(ValueError, match="what_broke"):
            InterventionEntry(
                timestamp="2026-03-24T14:30:00Z",
                epic="E1",
                story="S1",
                pipeline_phase="ci",
                failure_report="fail",
                what_broke="",  # empty — should fail
                what_developer_did="fixed",
                agent_limitation="limit",
                retry_counts="edit=1/3",
                files_involved=["f.py"],
            )

    def test_empty_what_developer_did_raises(self) -> None:
        """InterventionEntry rejects empty what_developer_did."""
        with pytest.raises(ValueError, match="what_developer_did"):
            InterventionEntry(
                timestamp="2026-03-24T14:30:00Z",
                epic="E1",
                story="S1",
                pipeline_phase="ci",
                failure_report="fail",
                what_broke="broke",
                what_developer_did="",
                agent_limitation="limit",
                retry_counts="edit=1/3",
            )

    def test_empty_agent_limitation_raises(self) -> None:
        """InterventionEntry rejects empty agent_limitation."""
        with pytest.raises(ValueError, match="agent_limitation"):
            InterventionEntry(
                timestamp="2026-03-24T14:30:00Z",
                epic="E1",
                story="S1",
                pipeline_phase="ci",
                failure_report="fail",
                what_broke="broke",
                what_developer_did="fixed",
                agent_limitation="",
                retry_counts="edit=1/3",
            )

    def test_summary_updates_in_log_file(
        self, logger: InterventionLogger, sample_entry: InterventionEntry
    ) -> None:
        """Summary section in the log file reflects current counts."""
        logger.log_intervention(sample_entry)
        logger.log_auto_recovery("E1", "S1", "ci", "fail", "fix")

        content = Path(logger.log_path).read_text(encoding="utf-8")
        assert "Total interventions: 1" in content
        assert "Auto-recoveries: 1" in content


class TestCliInterventionPrompt:
    """Tests for cli_intervention_prompt function."""

    def test_fix_action_logs_entry(
        self, logger: InterventionLogger, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI prompt with valid input logs an intervention and returns ('fix', instruction)."""
        inputs = iter(["Tests failed on import", "Added missing __init__.py", "Cross-module deps"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        action, fix_instruction = cli_intervention_prompt(
            logger=logger,
            epic="Epic 1",
            story="Story 1.2",
            phase="unit_test",
            failure_report="ModuleNotFoundError",
            retry_counts="edit=2/3, test=5/5",
            files_involved=["src/auth/__init__.py"],
        )
        assert action == "fix"
        assert fix_instruction == "Added missing __init__.py"
        assert logger.get_summary()["total_interventions"] == 1

    def test_skip_on_what_broke(
        self, logger: InterventionLogger, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Typing 'skip' at the first prompt returns ('skip', '')."""
        monkeypatch.setattr("builtins.input", lambda _: "skip")

        action, fix_instruction = cli_intervention_prompt(
            logger=logger,
            epic="E1",
            story="S1",
            phase="ci",
            failure_report="fail",
            retry_counts="edit=1/3",
        )
        assert action == "skip"
        assert fix_instruction == ""
        assert logger.get_summary()["total_interventions"] == 0

    def test_abort_on_what_did(
        self, logger: InterventionLogger, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Typing 'abort' at the second prompt returns ('abort', '')."""
        inputs = iter(["something broke", "abort"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        action, fix_instruction = cli_intervention_prompt(
            logger=logger,
            epic="E1",
            story="S1",
            phase="ci",
            failure_report="fail",
            retry_counts="edit=1/3",
        )
        assert action == "abort"
        assert fix_instruction == ""

    def test_keyboard_interrupt_returns_abort(
        self, logger: InterventionLogger, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KeyboardInterrupt during input returns ('abort', '')."""

        def raise_interrupt(_: str) -> str:
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", raise_interrupt)

        action, fix_instruction = cli_intervention_prompt(
            logger=logger,
            epic="E1",
            story="S1",
            phase="ci",
            failure_report="fail",
            retry_counts="edit=1/3",
        )
        assert action == "abort"
        assert fix_instruction == ""


class TestApiIntervention:
    """Tests for API intervention helpers."""

    def test_build_intervention_needed_response(self) -> None:
        """build_intervention_needed_response returns correct payload."""
        resp = build_intervention_needed_response(
            session_id="sess-123",
            failure_report="Test failed",
            story="Story 1.2",
            phase="unit_test",
            retry_counts="edit=2/3",
        )
        assert resp["status"] == "intervention_needed"
        assert resp["session_id"] == "sess-123"
        assert resp["failure_report"] == "Test failed"
        assert resp["story"] == "Story 1.2"
        assert resp["phase"] == "unit_test"
        assert resp["retry_counts"] == "edit=2/3"

    def test_process_api_intervention_logs_and_returns_action(
        self, logger: InterventionLogger
    ) -> None:
        """process_api_intervention logs the entry and returns the action."""
        action = process_api_intervention(
            logger=logger,
            epic="Epic 1",
            story="Story 1.2",
            phase="unit_test",
            failure_report="Test failed",
            retry_counts="edit=2/3",
            what_broke="Import error",
            what_developer_did="Added missing file",
            agent_limitation="Cross-module deps",
            action="fix",
            files_involved=["src/auth/__init__.py"],
        )
        assert action == "fix"
        assert logger.get_summary()["total_interventions"] == 1

    def test_process_api_intervention_skip_action(self, logger: InterventionLogger) -> None:
        """process_api_intervention with skip action still logs the entry."""
        action = process_api_intervention(
            logger=logger,
            epic="E1",
            story="S1",
            phase="ci",
            failure_report="fail",
            retry_counts="edit=1/3",
            what_broke="broke",
            what_developer_did="skipped",
            agent_limitation="limit",
            action="skip",
        )
        assert action == "skip"
        assert logger.get_summary()["total_interventions"] == 1


class TestExportForAnalysis:
    """Tests for export_for_analysis method."""

    def test_export_empty(self, logger: InterventionLogger) -> None:
        """Export with no data produces valid structure."""
        export = logger.export_for_analysis()
        assert "No interventions recorded" in export
        assert "No failures recorded" in export

    def test_export_with_data(
        self, logger: InterventionLogger, sample_entry: InterventionEntry
    ) -> None:
        """Export includes frequency, categories, and recovery rate."""
        logger.log_intervention(sample_entry)
        logger.log_auto_recovery("E1", "S1", "ci", "fail", "fix")

        export = logger.export_for_analysis()
        assert "unit_test" in export
        assert "Auto-recovery rate:** 50.0%" in export
        assert "Total failures encountered:** 2" in export
        assert "Auto-recovered (no human help):** 1" in export
        assert "Required human intervention:** 1" in export

    def test_export_limitation_categories(
        self, logger: InterventionLogger, sample_entry: InterventionEntry
    ) -> None:
        """Export groups limitations with examples."""
        logger.log_intervention(sample_entry)
        export = logger.export_for_analysis()
        assert "the agent struggles with cross-module dependencies" in export
        assert "Occurrences" in export

    def test_export_multiple_entries(self, logger: InterventionLogger) -> None:
        """Export with multiple entries shows correct categories and counts."""
        for limitation, phase in [
            ("Cross-module deps", "ci"),
            ("Cross-module deps", "unit_test"),
            ("Missing context", "dev"),
        ]:
            entry = InterventionEntry(
                timestamp="2026-03-24T14:30:00Z",
                epic="E1",
                story="S1",
                pipeline_phase=phase,
                failure_report="fail",
                what_broke="broke",
                what_developer_did="fixed",
                agent_limitation=limitation,
                retry_counts="edit=1/3",
            )
            logger.log_intervention(entry)

        export = logger.export_for_analysis()
        assert "cross-module deps" in export
        assert "missing context" in export
        assert "Occurrences:** 2" in export  # cross-module deps
        assert "Occurrences:** 1" in export  # missing context

    def test_case_insensitive_limitation_categories(self, logger: InterventionLogger) -> None:
        """Limitation categories are case-insensitive (normalized to lowercase)."""
        for limitation in ["Cross-module", "cross-module"]:
            entry = InterventionEntry(
                timestamp="2026-03-24T14:30:00Z",
                epic="E1",
                story="S1",
                pipeline_phase="ci",
                failure_report="fail",
                what_broke="broke",
                what_developer_did="fixed",
                agent_limitation=limitation,
                retry_counts="edit=1/3",
            )
            logger.log_intervention(entry)

        export = logger.export_for_analysis()
        # Should be a single category
        assert export.count("cross-module") >= 1
        assert "Occurrences:** 2" in export

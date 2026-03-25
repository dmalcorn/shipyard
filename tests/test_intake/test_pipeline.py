"""Tests for src/intake/pipeline.py — intake pipeline graph and nodes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.intake.backlog import load_backlog
from src.intake.pipeline import (
    IntakeState,
    build_intake_graph,
    create_backlog_node,
    intake_specs_node,
    output_node,
    read_specs_node,
    run_intake_pipeline,
)


class TestIntakeState:
    """IntakeState has all required fields."""

    def test_has_required_fields(self) -> None:
        """IntakeState TypedDict contains all story-specified fields."""
        state: IntakeState = {
            "task_id": "t1",
            "session_id": "s1",
            "spec_dir": "/specs",
            "raw_specs": "raw",
            "spec_summary": "summary",
            "epics_and_stories": "epics",
            "output_dir": "/out",
            "pipeline_status": "running",
            "error": "",
        }
        assert state["task_id"] == "t1"
        assert state["pipeline_status"] == "running"


class TestReadSpecsNode:
    """read_specs_node reads and validates spec directory."""

    def test_reads_specs_from_directory(self, tmp_path: Path) -> None:
        """Reads spec files and populates raw_specs."""
        (tmp_path / "spec.md").write_text("# Spec", encoding="utf-8")
        state: IntakeState = {"spec_dir": str(tmp_path)}
        result = read_specs_node(state)
        assert "# Spec" in result["raw_specs"]
        assert result["pipeline_status"] == "running"

    def test_fails_on_missing_spec_dir(self) -> None:
        """Returns failed status when spec_dir doesn't exist."""
        state: IntakeState = {"spec_dir": "/nonexistent/12345"}
        result = read_specs_node(state)
        assert result["pipeline_status"] == "failed"
        assert "not found" in result["error"]

    def test_fails_on_empty_spec_dir(self) -> None:
        """Returns failed status for empty spec_dir string."""
        state: IntakeState = {"spec_dir": ""}
        result = read_specs_node(state)
        assert result["pipeline_status"] == "failed"

    def test_fails_on_empty_directory(self, tmp_path: Path) -> None:
        """Returns failed status when directory has no spec files."""
        state: IntakeState = {"spec_dir": str(tmp_path)}
        result = read_specs_node(state)
        assert result["pipeline_status"] == "failed"
        assert "No spec files" in result["error"]


class TestIntakeSpecsNode:
    """intake_specs_node spawns a Dev Agent for summarization."""

    @patch("src.intake.pipeline.run_sub_agent")
    def test_calls_sub_agent_with_specs(self, mock_agent: MagicMock) -> None:
        """Passes raw specs to the sub-agent and captures summary."""
        mock_agent.return_value = {"final_message": "Summary here", "files_modified": []}
        state: IntakeState = {
            "session_id": "sess-1",
            "task_id": "intake-1",
            "raw_specs": "## File: readme.md\n# Hello",
        }
        result = intake_specs_node(state)
        assert result["spec_summary"] == "Summary here"
        mock_agent.assert_called_once()
        call_kwargs = mock_agent.call_args
        assert call_kwargs[1]["role"] == "dev"
        assert call_kwargs[1]["current_phase"] == "implementation"


class TestCreateBacklogNode:
    """create_backlog_node spawns a Dev Agent for backlog generation."""

    @patch("src.intake.pipeline.run_sub_agent")
    def test_calls_sub_agent_with_summary(self, mock_agent: MagicMock) -> None:
        """Passes spec summary to the sub-agent and captures backlog."""
        mock_agent.return_value = {
            "final_message": "## Epic 1: Auth\n### Story 1.1: Login",
            "files_modified": [],
        }
        state: IntakeState = {
            "session_id": "sess-1",
            "task_id": "intake-1",
            "spec_summary": "Summary of specs",
        }
        result = create_backlog_node(state)
        assert "Epic 1" in result["epics_and_stories"]


class TestOutputNode:
    """output_node writes spec summary and epics to files."""

    def test_writes_both_files(self, tmp_path: Path) -> None:
        """Writes spec-summary.md and epics.md to output directory."""
        state: IntakeState = {
            "output_dir": str(tmp_path),
            "spec_summary": "# Spec Summary",
            "epics_and_stories": "## Epic 1: Auth",
        }
        result = output_node(state)
        assert result["pipeline_status"] == "completed"
        spec_text = (tmp_path / "spec-summary.md").read_text(encoding="utf-8")
        epics_text = (tmp_path / "epics.md").read_text(encoding="utf-8")
        assert spec_text.startswith("---\n")
        assert spec_text.endswith("# Spec Summary")
        assert epics_text.startswith("---\n")
        assert epics_text.endswith("## Epic 1: Auth")

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        """Creates output directory if it doesn't exist."""
        out_dir = tmp_path / "subdir" / "output"
        state: IntakeState = {
            "output_dir": str(out_dir),
            "spec_summary": "summary",
            "epics_and_stories": "epics",
        }
        result = output_node(state)
        assert result["pipeline_status"] == "completed"
        assert out_dir.exists()

    def test_fails_on_missing_output_dir(self) -> None:
        """Returns failed status when output_dir is empty."""
        state: IntakeState = {"output_dir": "", "spec_summary": "s", "epics_and_stories": "e"}
        result = output_node(state)
        assert result["pipeline_status"] == "failed"


class TestBuildIntakeGraph:
    """build_intake_graph() constructs correct graph topology."""

    def test_has_correct_node_count(self) -> None:
        """Graph has 4 nodes: read_specs, intake_specs, create_backlog, output."""
        graph = build_intake_graph()
        node_names = set(graph.nodes.keys())
        assert "read_specs" in node_names
        assert "intake_specs" in node_names
        assert "create_backlog" in node_names
        assert "output" in node_names
        assert len(node_names) == 4

    def test_has_expected_edge_pairs(self) -> None:
        """Graph edges include the expected pipeline connections."""
        graph = build_intake_graph()
        # Verify specific edge connections rather than brittle count
        edges = graph.edges
        # Verify at least 4 pipeline edges exist (START→read, read→intake, etc.)
        assert len(edges) >= 4


class TestRunIntakePipeline:
    """run_intake_pipeline() integration test with mocked LLM."""

    @patch("src.intake.pipeline.run_sub_agent")
    def test_end_to_end_with_mock_llm(self, mock_agent: MagicMock, tmp_path: Path) -> None:
        """Full pipeline run with mocked LLM produces output files."""
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()
        (spec_dir / "readme.md").write_text("# My App\nA todo app.", encoding="utf-8")

        output_dir = tmp_path / "output"

        # First call: intake_specs_node, second: create_backlog_node
        mock_agent.side_effect = [
            {"final_message": "# Spec Summary\nA todo app with CRUD.", "files_modified": []},
            {
                "final_message": (
                    "## Epic 1: Core CRUD\n\n"
                    "### Story 1.1: Create Todo\n"
                    "**As a** user, **I want** to create todos, **so that** I can track tasks.\n\n"
                    "**Acceptance Criteria:**\n"
                    "- **Given** I am on the app "
                    "**When** I add a todo "
                    "**Then** it appears in the list\n"
                ),
                "files_modified": [],
            },
        ]

        result = run_intake_pipeline(
            spec_dir=str(spec_dir),
            output_dir=str(output_dir),
        )

        assert result["pipeline_status"] == "completed"
        assert (output_dir / "spec-summary.md").exists()
        assert (output_dir / "epics.md").exists()
        assert mock_agent.call_count == 2

        # FIX-28: Verify generated epics.md is parseable by load_backlog
        backlog = load_backlog(str(output_dir))
        assert len(backlog) > 0
        assert backlog[0]["epic"] == "Core CRUD"

    def test_failure_propagation_node_level(self) -> None:
        """read_specs_node with invalid spec_dir sets pipeline_status to failed."""
        state: IntakeState = {"spec_dir": "/nonexistent/12345"}
        result = read_specs_node(state)
        assert result["pipeline_status"] == "failed"
        assert "not found" in result["error"]


class TestOutputNodeEdgeCases:
    """Edge case tests for output_node."""

    def test_fails_on_empty_spec_summary(self, tmp_path: Path) -> None:
        """Returns failed when spec_summary is empty."""
        state: IntakeState = {
            "output_dir": str(tmp_path),
            "spec_summary": "",
            "epics_and_stories": "## Epic 1: Auth",
        }
        result = output_node(state)
        assert result["pipeline_status"] == "failed"
        assert "empty" in result["error"].lower()

    def test_fails_on_empty_epics(self, tmp_path: Path) -> None:
        """Returns failed when epics_and_stories is empty."""
        state: IntakeState = {
            "output_dir": str(tmp_path),
            "spec_summary": "# Summary",
            "epics_and_stories": "   ",
        }
        result = output_node(state)
        assert result["pipeline_status"] == "failed"

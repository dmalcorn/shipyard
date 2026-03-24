"""Intervention log for tracking human interventions during Ship app rebuilds.

Records every human intervention and auto-recovery during the rebuild process,
producing a structured markdown log suitable for comparative analysis.
"""

from __future__ import annotations

import logging as _logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

_EVIDENCE_FIELDS = ("what_broke", "what_developer_did", "agent_limitation")


@dataclass
class InterventionEntry:
    """A single human intervention during the rebuild process.

    Args:
        timestamp: ISO 8601 timestamp of the intervention.
        epic: Epic identifier (e.g. "Epic 1: Project Setup").
        story: Story identifier (e.g. "Story 1.2: Auth Module").
        pipeline_phase: Pipeline phase where failure occurred (e.g. "unit_test", "ci").
        failure_report: The error_handler_node output or pipeline failure description.
        what_broke: Concise description of what went wrong.
        what_developer_did: The human's intervention action.
        agent_limitation: What this reveals about the agent's capabilities.
        retry_counts: Retry count summary (e.g. "edit=2/3, test=5/5, CI=1/3").
        files_involved: List of files related to the intervention.
    """

    timestamp: str
    epic: str
    story: str
    pipeline_phase: str
    failure_report: str
    what_broke: str
    what_developer_did: str
    agent_limitation: str
    retry_counts: str
    files_involved: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate that evidence fields are non-empty."""
        for fname in _EVIDENCE_FIELDS:
            if not getattr(self, fname, "").strip():
                raise ValueError(f"{fname} must not be empty — evidence-based entries required")


@dataclass
class AutoRecoveryEntry:
    """A case where the agent recovered without human help.

    Args:
        timestamp: ISO 8601 timestamp.
        epic: Epic identifier.
        story: Story identifier.
        phase: Pipeline phase.
        what_failed: What initially failed.
        how_recovered: How the agent recovered on retry.
    """

    timestamp: str
    epic: str
    story: str
    phase: str
    what_failed: str
    how_recovered: str


class InterventionLogger:
    """Logs human interventions and auto-recoveries to a markdown file.

    Follows the same class-based pattern as AuditLogger (src/logging/audit.py).
    Produces a structured markdown log at the specified path.

    Args:
        log_path: Path to the intervention log markdown file.
    """

    def __init__(self, log_path: str) -> None:
        self.log_path = Path(log_path)
        self._intervention_count = 0
        self._recovery_count = 0
        self._interventions_by_phase: dict[str, int] = {}
        self._limitation_categories: dict[str, list[str]] = {}
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Create the log file with header if it doesn't exist yet."""
        if self._initialized:
            return
        path = Path(self.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = True
        self._rewrite_file()

    def log_intervention(self, entry: InterventionEntry) -> None:
        """Append an intervention entry to the log file."""
        self._ensure_initialized()
        self._intervention_count += 1
        phase = entry.pipeline_phase
        self._interventions_by_phase[phase] = self._interventions_by_phase.get(phase, 0) + 1

        # Track limitation categories (normalized to lowercase)
        limitation = entry.agent_limitation.strip().lower()
        if limitation not in self._limitation_categories:
            self._limitation_categories[limitation] = []
        example = f"{entry.epic} / {entry.story}: {entry.what_broke}"
        self._limitation_categories[limitation].append(example)

        section = self._format_intervention(self._intervention_count, entry)
        self._append_section(section)
        self._rewrite_summary()

    def log_auto_recovery(
        self,
        epic: str,
        story: str,
        phase: str,
        what_failed: str,
        how_recovered: str,
    ) -> None:
        """Log cases where the agent recovered without human help (for contrast)."""
        self._ensure_initialized()
        self._recovery_count += 1
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")

        recovery = AutoRecoveryEntry(
            timestamp=timestamp,
            epic=epic,
            story=story,
            phase=phase,
            what_failed=what_failed,
            how_recovered=how_recovered,
        )
        section = self._format_auto_recovery(self._recovery_count, recovery)
        self._append_section(section)
        self._rewrite_summary()

    def get_summary(self) -> dict[str, int | dict[str, int]]:
        """Return summary stats: total interventions, by phase, by type."""
        return {
            "total_interventions": self._intervention_count,
            "total_auto_recoveries": self._recovery_count,
            "interventions_by_phase": dict(self._interventions_by_phase),
        }

    def export_for_analysis(self) -> str:
        """Export log in a format ready for Story 5.1 comparative analysis."""
        lines: list[str] = []

        lines.append("# Intervention Log — Export for Comparative Analysis")
        lines.append("")

        # Intervention frequency by phase
        lines.append("## Intervention Frequency by Pipeline Phase")
        lines.append("")
        if self._interventions_by_phase:
            for phase, count in sorted(self._interventions_by_phase.items()):
                lines.append(f"- **{phase}:** {count}")
        else:
            lines.append("- No interventions recorded")
        lines.append("")

        # Agent limitation categories
        lines.append("## Agent Limitation Categories")
        lines.append("")
        if self._limitation_categories:
            for i, (category, examples) in enumerate(self._limitation_categories.items(), 1):
                lines.append(f"### {i}. {category}")
                lines.append(f"- **Occurrences:** {len(examples)}")
                for ex in examples:
                    lines.append(f"  - {ex}")
                lines.append("")
        else:
            lines.append("- No limitations recorded")
            lines.append("")

        # Auto-recovery success rate
        total_failures = self._intervention_count + self._recovery_count
        lines.append("## Auto-Recovery Success Rate")
        lines.append("")
        if total_failures > 0:
            rate = (self._recovery_count / total_failures) * 100
            lines.append(f"- **Total failures encountered:** {total_failures}")
            lines.append(f"- **Auto-recovered (no human help):** {self._recovery_count}")
            lines.append(f"- **Required human intervention:** {self._intervention_count}")
            lines.append(f"- **Auto-recovery rate:** {rate:.1f}%")
        else:
            lines.append("- No failures recorded")
        lines.append("")

        return "\n".join(lines)

    # -- Private helpers --

    def _format_intervention(self, number: int, entry: InterventionEntry) -> str:
        """Format a single intervention entry as markdown."""
        files_list = (
            ", ".join(f"`{f}`" for f in entry.files_involved) if entry.files_involved else "None"
        )
        return (
            f"## Intervention #{number}\n"
            f"- **Timestamp:** {entry.timestamp}\n"
            f"- **Epic/Story:** {entry.epic} / {entry.story}\n"
            f"- **Pipeline Phase:** {entry.pipeline_phase}\n"
            f"- **Retry Counts:** {entry.retry_counts}\n"
            f"- **Failure Report:** {entry.failure_report}\n"
            f"- **What Broke:** {entry.what_broke}\n"
            f"- **What Developer Did:** {entry.what_developer_did}\n"
            f"- **Agent Limitation:** {entry.agent_limitation}\n"
            f"- **Files Involved:** {files_list}\n"
        )

    def _format_auto_recovery(self, number: int, recovery: AutoRecoveryEntry) -> str:
        """Format a single auto-recovery entry as markdown."""
        return (
            f"## Auto-Recovery #{number}\n"
            f"- **Timestamp:** {recovery.timestamp}\n"
            f"- **Epic/Story:** {recovery.epic} / {recovery.story}\n"
            f"- **Pipeline Phase:** {recovery.phase}\n"
            f"- **What Failed:** {recovery.what_failed}\n"
            f"- **How Recovered:** {recovery.how_recovered}\n"
        )

    def _build_header(self) -> str:
        """Build the file header with summary section."""
        phase_parts = []
        for phase in ("test", "dev", "ci", "review"):
            count = self._interventions_by_phase.get(phase, 0)
            if count:
                phase_parts.append(f"{phase}={count}")
        # Include any phases not in the standard list
        for phase, count in self._interventions_by_phase.items():
            if phase not in ("test", "dev", "ci", "review") and count:
                phase_parts.append(f"{phase}={count}")

        phase_str = ", ".join(phase_parts) if phase_parts else "none"

        return (
            "# Ship App Rebuild — Intervention Log\n"
            "\n"
            "## Summary\n"
            f"- Total interventions: {self._intervention_count}\n"
            f"- Auto-recoveries: {self._recovery_count}\n"
            f"- Interventions by phase: {phase_str}\n"
            "\n"
            "---\n"
        )

    def _rewrite_file(self) -> None:
        """Write the full file (header only, used on init)."""
        path = Path(self.log_path)
        path.write_text(self._build_header(), encoding="utf-8")

    def _rewrite_summary(self) -> None:
        """Rewrite just the summary section at the top of the file."""
        path = Path(self.log_path)
        content = path.read_text(encoding="utf-8")

        # Find the end of the summary section (first ---)
        marker = "---\n"
        marker_pos = content.find(marker)
        if marker_pos == -1:
            _logging.getLogger(__name__).warning(
                "Summary marker '---' not found in %s",
                self.log_path,
            )
            return

        rest = content[marker_pos + len(marker) :]
        new_content = self._build_header() + rest
        path.write_text(new_content, encoding="utf-8")

    def _append_section(self, section: str) -> None:
        """Append a markdown section to the log file."""
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write("\n" + section)


# ---------------------------------------------------------------------------
# CLI intervention prompt
# ---------------------------------------------------------------------------


def cli_intervention_prompt(
    logger: InterventionLogger,
    epic: str,
    story: str,
    phase: str,
    failure_report: str,
    retry_counts: str,
    files_involved: list[str] | None = None,
) -> tuple[Literal["fix", "skip", "abort"], str]:
    """Prompt the user for structured intervention data via CLI.

    Prints the failure report and captures what broke, what the developer
    did, and what it reveals about the agent. Logs the intervention entry
    and returns the chosen action with the fix instruction.

    Args:
        logger: The InterventionLogger to record the intervention.
        epic: Current epic identifier.
        story: Current story identifier.
        phase: Pipeline phase where failure occurred.
        failure_report: The error_handler_node output or failure description.
        retry_counts: Summary of retry counts (e.g. "edit=2/3, test=5/5").
        files_involved: Optional list of files related to the failure.

    Returns:
        Tuple of (action, fix_instruction). fix_instruction is the developer's
        description of what they did, or empty string for skip/abort.
    """
    print(f"\n{'=' * 60}")
    print("INTERVENTION NEEDED")
    print(f"{'=' * 60}")
    print(f"Epic: {epic}")
    print(f"Story: {story}")
    print(f"Phase: {phase}")
    print(f"Retry Counts: {retry_counts}")
    print(f"\n{failure_report}\n")
    print(f"{'=' * 60}")

    try:
        what_broke = input("What broke (concise): ").strip()
        if what_broke.lower() == "skip":
            return ("skip", "")
        if what_broke.lower() == "abort":
            return ("abort", "")

        what_did = input("What will you do to fix it: ").strip()
        if what_did.lower() == "skip":
            return ("skip", "")
        if what_did.lower() == "abort":
            return ("abort", "")

        limitation = input("What does this reveal about the agent: ").strip()
        if limitation.lower() == "skip":
            return ("skip", "")
        if limitation.lower() == "abort":
            return ("abort", "")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return ("abort", "")

    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    entry = InterventionEntry(
        timestamp=timestamp,
        epic=epic,
        story=story,
        pipeline_phase=phase,
        failure_report=failure_report,
        what_broke=what_broke or "Not specified",
        what_developer_did=what_did or "Not specified",
        agent_limitation=limitation or "Not specified",
        retry_counts=retry_counts,
        files_involved=files_involved or [],
    )
    logger.log_intervention(entry)
    return ("fix", what_did)


# ---------------------------------------------------------------------------
# API intervention helpers
# ---------------------------------------------------------------------------


def build_intervention_needed_response(
    session_id: str,
    failure_report: str,
    story: str,
    phase: str,
    retry_counts: str,
) -> dict[str, str]:
    """Build the API response payload when intervention is needed.

    Args:
        session_id: Active rebuild session ID.
        failure_report: The error_handler_node output.
        story: Current story identifier.
        phase: Pipeline phase where failure occurred.
        retry_counts: Summary of retry counts.

    Returns:
        Dict with status, session_id, failure_report, story, phase, retry_counts.
    """
    return {
        "status": "intervention_needed",
        "session_id": session_id,
        "failure_report": failure_report,
        "story": story,
        "phase": phase,
        "retry_counts": retry_counts,
    }


def process_api_intervention(
    logger: InterventionLogger,
    epic: str,
    story: str,
    phase: str,
    failure_report: str,
    retry_counts: str,
    what_broke: str,
    what_developer_did: str,
    agent_limitation: str,
    action: Literal["fix", "skip", "abort"],
    files_involved: list[str] | None = None,
) -> Literal["fix", "skip", "abort"]:
    """Process an API intervention submission and log it.

    Args:
        logger: The InterventionLogger to record the intervention.
        epic: Current epic identifier.
        story: Current story identifier.
        phase: Pipeline phase where failure occurred.
        failure_report: The error_handler_node output.
        retry_counts: Summary of retry counts.
        what_broke: What the developer says broke.
        what_developer_did: What fix the developer applied.
        agent_limitation: What this reveals about the agent.
        action: The developer's chosen action (fix, skip, abort).
        files_involved: Optional list of files related to the failure.

    Returns:
        The action to take: "fix", "skip", or "abort".
    """
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    entry = InterventionEntry(
        timestamp=timestamp,
        epic=epic,
        story=story,
        pipeline_phase=phase,
        failure_report=failure_report,
        what_broke=what_broke or "Not specified",
        what_developer_did=what_developer_did or "Not specified",
        agent_limitation=agent_limitation or "Not specified",
        retry_counts=retry_counts,
        files_involved=files_involved or [],
    )
    logger.log_intervention(entry)
    return action

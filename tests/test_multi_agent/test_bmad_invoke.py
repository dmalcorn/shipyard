"""Tests for src/multi_agent/bmad_invoke.py helpers.

Focused on the pure helpers that can be exercised without shelling out
to the real Claude CLI: ``_model_families_match`` and the init-event
branch of ``_print_stream_event``. The streaming loop and subprocess
plumbing are exercised indirectly through end-to-end pipeline runs.
"""

from __future__ import annotations

from src.multi_agent.bmad_invoke import (
    _extract_agent_identification,
    _model_families_match,
    _print_stream_event,
)


class TestModelFamiliesMatch:
    """_model_families_match normalizes requested vs resolved model names."""

    def test_alias_matches_full_id(self) -> None:
        assert _model_families_match("opus", "claude-opus-4-6") is True
        assert _model_families_match("sonnet", "claude-sonnet-4-6") is True
        assert _model_families_match("haiku", "claude-haiku-4-5-20251001") is True

    def test_full_id_matches_itself(self) -> None:
        assert _model_families_match(
            "claude-opus-4-6", "claude-opus-4-6",
        ) is True
        assert _model_families_match(
            "claude-sonnet-4-6-20251201", "claude-sonnet-4-6-20251201",
        ) is True

    def test_different_families_do_not_match(self) -> None:
        assert _model_families_match("opus", "claude-sonnet-4-6") is False
        assert _model_families_match("sonnet", "claude-opus-4-6") is False
        assert _model_families_match("haiku", "claude-opus-4-6") is False

    def test_dated_variants_match_family(self) -> None:
        # The CLI frequently resolves to a dated variant of the family.
        assert _model_families_match(
            "claude-sonnet-4-6", "claude-sonnet-4-6-20251201",
        ) is True
        assert _model_families_match(
            "sonnet", "claude-sonnet-4-5-20251001",
        ) is True

    def test_case_insensitive(self) -> None:
        assert _model_families_match("OPUS", "Claude-Opus-4-6") is True
        assert _model_families_match("Sonnet", "CLAUDE-SONNET-4-6") is True

    def test_unknown_family_compares_literally(self) -> None:
        # When neither name contains a known family keyword, fall back
        # to literal case-insensitive comparison.
        assert _model_families_match("custom-model", "custom-model") is True
        assert _model_families_match("custom-model", "other-model") is False


class TestPrintStreamEventInitBranch:
    """The init-event branch of _print_stream_event prints a session-started
    line, and — when requested_model is provided — warns on mismatch."""

    def _init_event(self, model: str) -> dict[str, object]:
        return {"type": "system", "subtype": "init", "model": model}

    def test_no_request_prints_resolved_only(self, capsys) -> None:
        _print_stream_event(
            self._init_event("claude-sonnet-4-6"), "bmad", 0.0, [],
        )
        out = capsys.readouterr().out
        assert "Session started (model=claude-sonnet-4-6)" in out
        assert "MISMATCH" not in out

    def test_matching_request_prints_both_values(self, capsys) -> None:
        _print_stream_event(
            self._init_event("claude-opus-4-6"), "bmad", 0.0, [],
            requested_model="opus",
        )
        out = capsys.readouterr().out
        assert "requested=opus" in out
        assert "resolved=claude-opus-4-6" in out
        assert "MISMATCH" not in out

    def test_full_id_matches_itself_no_warning(self, capsys) -> None:
        _print_stream_event(
            self._init_event("claude-opus-4-6"), "bmad", 0.0, [],
            requested_model="claude-opus-4-6",
        )
        out = capsys.readouterr().out
        assert "MISMATCH" not in out
        assert "claude-opus-4-6" in out

    def test_family_mismatch_prints_warning(self, capsys) -> None:
        # Asked for opus, CLI resolved to sonnet — this should be loud.
        _print_stream_event(
            self._init_event("claude-sonnet-4-5"), "claude-review", 0.0, [],
            requested_model="opus",
        )
        out = capsys.readouterr().out
        assert "MODEL MISMATCH" in out
        assert "requested=opus" in out
        assert "claude-sonnet-4-5" in out

    def test_full_id_mismatch_prints_warning(self, capsys) -> None:
        _print_stream_event(
            self._init_event("claude-opus-4-6"), "architect", 0.0, [],
            requested_model="claude-sonnet-4-6",
        )
        out = capsys.readouterr().out
        assert "MODEL MISMATCH" in out


class TestExtractAgentIdentification:
    """_extract_agent_identification unchanged by the model-check work —
    included here as a regression anchor while we're touching this file."""

    def test_finds_block(self) -> None:
        output = (
            "some preamble\n"
            "=== AGENT IDENTIFICATION ===\n"
            "Agent: DEV Agent\n"
            "Persona: Amelia\n"
            "Model: claude-sonnet-4-6\n"
            "=== END IDENTIFICATION ===\n"
            "trailing text\n"
        )
        block = _extract_agent_identification(output)
        assert block is not None
        assert "Agent: DEV Agent" in block
        assert "Persona: Amelia" in block

    def test_missing_block_returns_none(self) -> None:
        assert _extract_agent_identification("no block here") is None

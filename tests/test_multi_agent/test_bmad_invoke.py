"""Tests for src/multi_agent/bmad_invoke.py helpers.

Focused on the pure helpers that can be exercised without shelling out
to the real Claude CLI: ``_model_families_match`` and the init-event
branch of ``_print_stream_event``. The streaming loop and subprocess
plumbing are exercised indirectly through end-to-end pipeline runs.
"""

from __future__ import annotations

from src.multi_agent.bmad_invoke import (
    _build_bmad_prompt,
    _extract_agent_identification,
    _model_families_match,
    _print_stream_event,
)


class TestModelFamiliesMatch:
    """_model_families_match: family-first, then version when specified."""

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

    def test_version_mismatch_within_same_family_is_flagged(self) -> None:
        # The scenario that motivated this check: you asked for the
        # newer sonnet, the CLI resolved to an older sonnet. Same
        # family, different version — must NOT silently match.
        assert _model_families_match(
            "claude-sonnet-4-6", "claude-sonnet-4-5",
        ) is False
        assert _model_families_match(
            "claude-sonnet-4-5", "claude-sonnet-4-6",
        ) is False
        assert _model_families_match(
            "claude-opus-4-6", "claude-opus-4-5",
        ) is False

    def test_version_mismatch_with_dated_variant_is_flagged(self) -> None:
        # Asked for 4-6, resolved to a dated variant of 4-5 — still a
        # mismatch even though the date suffix makes the strings look
        # superficially different.
        assert _model_families_match(
            "claude-sonnet-4-6", "claude-sonnet-4-5-20251001",
        ) is False

    def test_dated_variant_of_same_version_matches(self) -> None:
        # Asked for 4-5, resolved to dated 4-5 — this is normal CLI
        # resolution behavior and must not fire a mismatch.
        assert _model_families_match(
            "claude-sonnet-4-5", "claude-sonnet-4-5-20251001",
        ) is True
        assert _model_families_match(
            "claude-opus-4-6", "claude-opus-4-6-20251215",
        ) is True

    def test_bare_alias_tolerates_any_version(self) -> None:
        # "sonnet" with no version specified → any sonnet matches.
        # Callers who want version-level checking must pass a versioned
        # string like "claude-sonnet-4-6".
        assert _model_families_match("sonnet", "claude-sonnet-4-5") is True
        assert _model_families_match("sonnet", "claude-sonnet-4-6") is True
        assert _model_families_match("opus", "claude-opus-4-5") is True
        assert _model_families_match("opus", "claude-opus-4-6") is True


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
    """_extract_agent_identification grabs whatever fields appear
    between the markers — it's format-agnostic so the prompt schema
    can evolve without breaking it."""

    def test_finds_block_with_current_three_field_shape(self) -> None:
        output = (
            "some preamble\n"
            "=== AGENT IDENTIFICATION ===\n"
            "Agent: DEV Agent\n"
            "Persona: Amelia\n"
            "Loaded files:\n"
            "  - .claude/skills/bmad-agent-dev/SKILL.md\n"
            "=== END IDENTIFICATION ===\n"
            "trailing text\n"
        )
        block = _extract_agent_identification(output)
        assert block is not None
        assert "Agent: DEV Agent" in block
        assert "Persona: Amelia" in block
        assert "Loaded files:" in block

    def test_finds_block_with_legacy_model_field(self) -> None:
        # Older runs included a Model: line. The extractor is tolerant
        # so we can still read archived fixtures from before the cleanup.
        output = (
            "=== AGENT IDENTIFICATION ===\n"
            "Agent: DEV Agent\n"
            "Model: claude-sonnet-4-6\n"
            "=== END IDENTIFICATION ===\n"
        )
        block = _extract_agent_identification(output)
        assert block is not None
        assert "Agent: DEV Agent" in block

    def test_missing_block_returns_none(self) -> None:
        assert _extract_agent_identification("no block here") is None


class TestBmadPromptStealth:
    """The BMAD prompt must not ask the agent about its model.

    Stealth requirement: we compare requested vs resolved model using
    the CLI's stream-json init event, which is produced by the CLI
    process itself and invisible to the agent. Asking the agent to
    self-report its model would tell it we care about this data, which
    a sufficiently eager-to-please model might respond to by shading
    its answer. Machine metadata is the authoritative source; the
    agent must never be queried about it.
    """

    def test_prompt_does_not_ask_for_model(self) -> None:
        prompt = _build_bmad_prompt("DS for story 1-1", "bmad-agent-dev")
        lowered = prompt.lower()
        # None of these phrasings should appear — each is a form of
        # asking the agent to self-identify its model.
        assert "what llm are you" not in lowered
        assert "state your underlying model" not in lowered
        assert "state your model" not in lowered
        assert "model:" not in lowered

    def test_prompt_still_asks_for_agent_persona_and_loaded_files(
        self,
    ) -> None:
        # Things only the agent knows about its own activation.
        prompt = _build_bmad_prompt("DS for story 1-1", "bmad-agent-dev")
        assert "Agent:" in prompt
        assert "Persona:" in prompt
        assert "Loaded files:" in prompt
        assert "=== AGENT IDENTIFICATION ===" in prompt
        assert "=== END IDENTIFICATION ===" in prompt

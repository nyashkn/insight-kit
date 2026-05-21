"""T12 — critique severity gate + critiqueRounds counter.

Cites: V16.

V16 — critique severity gates the tier: an `open` critique of `severity >= high`
on a `published`/`audience:board` `claim`/`intervention` = hard gate fail
(block render, force published→draft). `RunState.critiqueRounds` counter;
cap 3 then downgrade — enforced in code, not prose.
"""
from __future__ import annotations

import pytest

from insight_kit.gate.runstate import (
    CritiqueSeverity,
    CritiqueState,
    RunState,
    apply_critique,
    CritiqueGateError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state() -> RunState:
    return RunState()


# ---------------------------------------------------------------------------
# CritiqueSeverity enum
# ---------------------------------------------------------------------------

class TestCritiqueSeverity:
    def test_ordering_low_lt_medium(self):
        assert CritiqueSeverity.low < CritiqueSeverity.medium

    def test_ordering_medium_lt_high(self):
        assert CritiqueSeverity.medium < CritiqueSeverity.high

    def test_ordering_high_lt_critical(self):
        assert CritiqueSeverity.high < CritiqueSeverity.critical

    def test_high_gte_high(self):
        assert CritiqueSeverity.high >= CritiqueSeverity.high

    def test_critical_gte_high(self):
        assert CritiqueSeverity.critical >= CritiqueSeverity.high


# ---------------------------------------------------------------------------
# CritiqueState dataclass
# ---------------------------------------------------------------------------

class TestCritiqueState:
    def test_default_state(self):
        c = CritiqueState.open(severity="medium", reason="test")
        assert c.status == "open"
        assert c.severity == CritiqueSeverity.medium
        assert c.reason == "test"

    def test_resolved_state(self):
        c = CritiqueState.open(severity="low", reason="minor")
        c2 = c.resolve()
        assert c2.status == "resolved"
        assert c2.severity == CritiqueSeverity.low

    def test_severity_accepted_as_string(self):
        c = CritiqueState.open(severity="high", reason="serious issue")
        assert c.severity == CritiqueSeverity.high


# ---------------------------------------------------------------------------
# V16 — severity gate: published + open + severity>=high = hard fail
# ---------------------------------------------------------------------------

class TestSeverityGate:
    def test_open_high_on_published_claim_raises(self, state):
        """Published claim with an open HIGH critique → CritiqueGateError."""
        critique = CritiqueState.open(severity="high", reason="serious flaw")
        with pytest.raises(CritiqueGateError) as exc_info:
            apply_critique(
                run_state=state,
                record_id="abc123",
                record_type="claim",
                tier="published",
                audience=None,
                critique=critique,
            )
        assert "published" in str(exc_info.value).lower() or "high" in str(exc_info.value).lower()

    def test_open_critical_on_published_raises(self, state):
        """Published claim with CRITICAL critique → CritiqueGateError."""
        critique = CritiqueState.open(severity="critical", reason="catastrophic error")
        with pytest.raises(CritiqueGateError):
            apply_critique(
                run_state=state,
                record_id="abc123",
                record_type="claim",
                tier="published",
                audience=None,
                critique=critique,
            )

    def test_open_high_on_board_audience_raises(self, state):
        """Audience=board claim with HIGH critique → CritiqueGateError (V16: published/audience:board)."""
        critique = CritiqueState.open(severity="high", reason="board-level flaw")
        with pytest.raises(CritiqueGateError):
            apply_critique(
                run_state=state,
                record_id="abc123",
                record_type="claim",
                tier="draft",         # tier=draft BUT audience=board
                audience="board",
                critique=critique,
            )

    def test_open_high_on_published_intervention_raises(self, state):
        """Published intervention with HIGH critique → CritiqueGateError."""
        critique = CritiqueState.open(severity="high", reason="intervention flaw")
        with pytest.raises(CritiqueGateError):
            apply_critique(
                run_state=state,
                record_id="xyz456",
                record_type="intervention",
                tier="published",
                audience=None,
                critique=critique,
            )

    def test_open_medium_on_published_does_not_raise(self, state):
        """Medium severity on published = NOT a hard fail (< high threshold)."""
        critique = CritiqueState.open(severity="medium", reason="minor issue")
        # Should not raise
        result = apply_critique(
            run_state=state,
            record_id="abc123",
            record_type="claim",
            tier="published",
            audience=None,
            critique=critique,
        )
        assert result is not None

    def test_open_low_on_published_does_not_raise(self, state):
        """Low severity on published = NOT a hard fail."""
        critique = CritiqueState.open(severity="low", reason="style nit")
        result = apply_critique(
            run_state=state,
            record_id="abc123",
            record_type="claim",
            tier="published",
            audience=None,
            critique=critique,
        )
        assert result is not None

    def test_resolved_high_on_published_does_not_raise(self, state):
        """Resolved HIGH critique on published = NOT a hard fail (resolved, not open)."""
        critique = CritiqueState.open(severity="high", reason="was serious").resolve()
        # Should not raise
        result = apply_critique(
            run_state=state,
            record_id="abc123",
            record_type="claim",
            tier="published",
            audience=None,
            critique=critique,
        )
        assert result is not None

    def test_open_high_on_draft_does_not_raise(self, state):
        """Draft claim with HIGH critique = NOT a gate fail (draft is passive)."""
        critique = CritiqueState.open(severity="high", reason="issue found")
        # draft is permissive
        result = apply_critique(
            run_state=state,
            record_id="abc123",
            record_type="claim",
            tier="draft",
            audience=None,
            critique=critique,
        )
        assert result is not None

    def test_open_critical_on_research_does_not_raise(self, state):
        """Research records are untiered — critique gate does not apply."""
        critique = CritiqueState.open(severity="critical", reason="knowledge issue")
        # research is untiered, gate does not block
        result = apply_critique(
            run_state=state,
            record_id="res001",
            record_type="research",
            tier=None,
            audience=None,
            critique=critique,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# V16 — critiqueRounds counter incremented on gate fail
# ---------------------------------------------------------------------------

class TestCritiqueRoundsCounter:
    def test_critique_rounds_incremented_on_gate_fail(self, state):
        """critiqueRounds increments when apply_critique catches a severity gate hit."""
        critique = CritiqueState.open(severity="high", reason="serious")
        with pytest.raises(CritiqueGateError):
            apply_critique(
                run_state=state,
                record_id="abc123",
                record_type="claim",
                tier="published",
                audience=None,
                critique=critique,
            )
        assert state.critiqueRounds == 1

    def test_critique_rounds_incremented_on_non_blocking_critique(self, state):
        """critiqueRounds also increments on non-blocking critiques (round tracking)."""
        critique = CritiqueState.open(severity="low", reason="style")
        apply_critique(
            run_state=state,
            record_id="abc123",
            record_type="claim",
            tier="published",
            audience=None,
            critique=critique,
        )
        assert state.critiqueRounds == 1

    def test_critique_rounds_accumulate(self, state):
        """Multiple apply_critique calls accumulate rounds."""
        critique = CritiqueState.open(severity="low", reason="nit")
        apply_critique(run_state=state, record_id="a", record_type="claim", tier="draft", audience=None, critique=critique)
        apply_critique(run_state=state, record_id="b", record_type="claim", tier="draft", audience=None, critique=critique)
        apply_critique(run_state=state, record_id="c", record_type="claim", tier="draft", audience=None, critique=critique)
        assert state.critiqueRounds == 3


# ---------------------------------------------------------------------------
# V16 — cap 3 then downgrade
# ---------------------------------------------------------------------------

class TestCritiqueRoundsCap:
    def test_cap_3_triggers_downgrade(self, state):
        """After critiqueRounds reaches 3, apply_critique downgrades instead of raising."""
        # Manually set rounds to 3 to simulate hitting the cap
        state.critiqueRounds = 3
        critique = CritiqueState.open(severity="high", reason="serious flaw")
        # At cap, should NOT raise CritiqueGateError — instead downgrades
        result = apply_critique(
            run_state=state,
            record_id="abc123",
            record_type="claim",
            tier="published",
            audience=None,
            critique=critique,
        )
        # result indicates downgrade
        assert result.get("downgraded") is True
        assert result.get("tier") == "draft"

    def test_cap_3_increments_beyond_three(self, state):
        """Downgrade path still increments critiqueRounds."""
        state.critiqueRounds = 3
        critique = CritiqueState.open(severity="high", reason="serious")
        apply_critique(
            run_state=state,
            record_id="abc123",
            record_type="claim",
            tier="published",
            audience=None,
            critique=critique,
        )
        assert state.critiqueRounds == 4

    def test_below_cap_still_raises(self, state):
        """critiqueRounds = 2 (below cap): still raises CritiqueGateError."""
        state.critiqueRounds = 2
        critique = CritiqueState.open(severity="high", reason="serious flaw")
        with pytest.raises(CritiqueGateError):
            apply_critique(
                run_state=state,
                record_id="abc123",
                record_type="claim",
                tier="published",
                audience=None,
                critique=critique,
            )

    def test_cap_is_exactly_three(self, state):
        """Cap is exactly 3. critiqueRounds=3 → downgrade, not raise."""
        state.critiqueRounds = 3
        critique = CritiqueState.open(severity="high", reason="serious")
        result = apply_critique(
            run_state=state,
            record_id="abc123",
            record_type="claim",
            tier="published",
            audience=None,
            critique=critique,
        )
        assert result.get("downgraded") is True

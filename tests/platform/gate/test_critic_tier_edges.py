"""T29 — Critic tier + supports/refutes edges tests.

Covers:
  - ClaimTier.critic enum value exists and is assignable.
  - ClaimRecord.supports / refutes default to [].
  - supports/refutes fields are NOT accepted on other record types (extra=forbid).
  - check_critic_edges: critic tier requires at least one edge.
  - _check_supporter_refutes_targets: dangling / wrong-type targets rejected (V2).
  - Valid critic claims (supports, refutes, both) emit successfully.
  - Non-critic claims with empty supports/refutes emit successfully.
  - V2 no-partial-write: rejected claim writes nothing to disk.

Cites: T29, C13, V2, V3, T27.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from insight_kit.libs.validation import ValidationError as LayerAValidationError
from insight_kit.libs.validation import check_critic_edges
from insight_kit.platform.gate.emit import ik_claim_emit, ik_research_emit, ik_skill_use_emit
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.schema import (
    ClaimRecord,
    ClaimTier,
    FieldEntry,
    InterventionRecord,
    ResearchRecord,
    SkillUseRecord,
)
from insight_kit.platform.gate.store import record_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emit_claim(
    claim_id: str,
    run_dir: Path,
    state: RunState,
    **kwargs,
):
    """Minimal ik_claim_emit wrapper."""
    return ik_claim_emit(
        claim_id,
        {"value": 1},
        run_state=state,
        run_dir=run_dir,
        **kwargs,
    )


def _emit_research(run_dir: Path, state: RunState, research_id: str = "RSR-R-001"):
    """Emit a minimal research record and return the ref."""
    return ik_research_emit(
        research_id=research_id,
        snapshot_ref="http://example.com",
        query="test query",
        source="test source",
        snapshot={"data": "test"},
        timestamp="2026-01-01T00:00:00+00:00",
        run_state=state,
        run_dir=run_dir,
    )


def _emit_skill_use(run_dir: Path, state: RunState, skill_use_id: str = "SKL-R-001"):
    """Emit a minimal skill_use record and return the ref."""
    return ik_skill_use_emit(
        skill_use_id=skill_use_id,
        snapshot_ref="tool://test",
        tool="test_tool",
        source="test_source",
        snapshot={"result": "test"},
        timestamp="2026-01-01T00:00:00+00:00",
        run_state=state,
        run_dir=run_dir,
    )


# ---------------------------------------------------------------------------
# Schema tests: ClaimTier.critic + ClaimRecord fields
# ---------------------------------------------------------------------------


class TestClaimTierCritic:
    def test_critic_value_exists(self):
        """ClaimTier.critic is defined in the StrEnum."""
        assert ClaimTier.critic == "critic"

    def test_critic_assignable_to_claim_record(self):
        """ClaimRecord accepts tier='critic'."""
        r = ClaimRecord(
            claim_id="TEST-C-001",
            fields={"v": FieldEntry(value=1)},
            tier=ClaimTier.critic,
        )
        assert r.tier == ClaimTier.critic

    def test_claim_tier_values(self):
        """All three tier values are present."""
        values = {t.value for t in ClaimTier}
        assert values == {"draft", "published", "critic"}

    def test_supports_defaults_to_empty_list(self):
        """ClaimRecord.supports defaults to []."""
        r = ClaimRecord(
            claim_id="TEST-C-002",
            fields={"v": FieldEntry(value=1)},
        )
        assert r.supports == []

    def test_refutes_defaults_to_empty_list(self):
        """ClaimRecord.refutes defaults to []."""
        r = ClaimRecord(
            claim_id="TEST-C-003",
            fields={"v": FieldEntry(value=1)},
        )
        assert r.refutes == []

    def test_supports_can_be_populated(self):
        """ClaimRecord.supports accepts a list of strings."""
        r = ClaimRecord(
            claim_id="TEST-C-004",
            fields={"v": FieldEntry(value=1)},
            supports=["TEST-C-001"],
        )
        assert r.supports == ["TEST-C-001"]

    def test_refutes_can_be_populated(self):
        """ClaimRecord.refutes accepts a list of strings."""
        r = ClaimRecord(
            claim_id="TEST-C-005",
            fields={"v": FieldEntry(value=1)},
            refutes=["TEST-C-001"],
        )
        assert r.refutes == ["TEST-C-001"]


class TestOtherRecordTypesRejectCriticFields:
    def test_intervention_rejects_supports(self):
        """InterventionRecord (extra=forbid) rejects a 'supports' field."""
        with pytest.raises(PydanticValidationError):
            InterventionRecord(
                intervention_id="INT-I-001",
                intent={"description": "do something"},
                supports=["TEST-C-001"],  # type: ignore[call-arg]
            )

    def test_intervention_rejects_refutes(self):
        """InterventionRecord (extra=forbid) rejects a 'refutes' field."""
        with pytest.raises(PydanticValidationError):
            InterventionRecord(
                intervention_id="INT-I-002",
                intent={"description": "do something"},
                refutes=["TEST-C-001"],  # type: ignore[call-arg]
            )

    def test_research_rejects_supports(self):
        """ResearchRecord (extra=forbid) rejects a 'supports' field."""
        with pytest.raises(PydanticValidationError):
            ResearchRecord(
                research_id="RSR-R-001",
                snapshot_ref="http://example.com",
                query="q",
                source="s",
                timestamp="2026-01-01T00:00:00+00:00",
                supports=["TEST-C-001"],  # type: ignore[call-arg]
            )

    def test_skill_use_rejects_refutes(self):
        """SkillUseRecord (extra=forbid) rejects a 'refutes' field."""
        with pytest.raises(PydanticValidationError):
            SkillUseRecord(
                skill_use_id="SKL-R-001",
                snapshot_ref="tool://test",
                tool="t",
                source="s",
                timestamp="2026-01-01T00:00:00+00:00",
                refutes=["TEST-C-001"],  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# check_critic_edges (validation lib) unit tests
# ---------------------------------------------------------------------------


class TestCheckCriticEdgesUnit:
    def test_critic_no_edges_raises(self):
        """critic tier with no supports/refutes → critic-requires-edge."""
        with pytest.raises(LayerAValidationError, match="critic-requires-edge"):
            check_critic_edges(tier="critic", supports=None, refutes=None)

    def test_critic_empty_lists_raises(self):
        """critic tier with empty lists → critic-requires-edge."""
        with pytest.raises(LayerAValidationError, match="critic-requires-edge"):
            check_critic_edges(tier="critic", supports=[], refutes=[])

    def test_critic_with_supports_passes(self):
        """critic tier with supports list → no error."""
        check_critic_edges(tier="critic", supports=["CLAIM-C-001"], refutes=None)

    def test_critic_with_refutes_passes(self):
        """critic tier with refutes list → no error."""
        check_critic_edges(tier="critic", supports=None, refutes=["CLAIM-C-001"])

    def test_critic_with_both_passes(self):
        """critic tier with both supports and refutes → no error."""
        check_critic_edges(
            tier="critic",
            supports=["CLAIM-C-001"],
            refutes=["CLAIM-C-002"],
        )

    def test_draft_empty_edges_passes(self):
        """draft tier with empty supports/refutes → no error."""
        check_critic_edges(tier="draft", supports=[], refutes=[])

    def test_published_empty_edges_passes(self):
        """published tier with empty supports/refutes → no error."""
        check_critic_edges(tier="published", supports=None, refutes=None)


# ---------------------------------------------------------------------------
# _check_supporter_refutes_targets (emit wiring): dangling + wrong-type
# ---------------------------------------------------------------------------


class TestSupporterRefutesTargetsWiring:
    """Wire tests for _check_supporter_refutes_targets via full ik_claim_emit path."""

    def test_dangling_supports_rejects(self, tmp_path: Path):
        """supports referencing a nonexistent record → supports-not-found."""
        run_dir = tmp_path / "run"
        state = RunState()

        with pytest.raises(LayerAValidationError, match="supports-not-found"):
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                tier="critic",
                supports=["nonexistent-record-id"],
            )

    def test_dangling_refutes_rejects(self, tmp_path: Path):
        """refutes referencing a nonexistent record → refutes-not-found."""
        run_dir = tmp_path / "run"
        state = RunState()

        with pytest.raises(LayerAValidationError, match="refutes-not-found"):
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                tier="critic",
                refutes=["nonexistent-record-id"],
            )

    def test_supports_wrong_type_research_rejects(self, tmp_path: Path):
        """supports pointing at a research record → supports-wrong-type."""
        run_dir = tmp_path / "run"
        state = RunState()

        # Emit a research record first
        research_ref = _emit_research(run_dir, state)

        with pytest.raises(LayerAValidationError, match="supports-wrong-type"):
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                tier="critic",
                supports=[research_ref.record_id],
            )

    def test_supports_wrong_type_skill_use_rejects(self, tmp_path: Path):
        """supports pointing at a skill_use record → supports-wrong-type."""
        run_dir = tmp_path / "run"
        state = RunState()

        skill_ref = _emit_skill_use(run_dir, state)

        with pytest.raises(LayerAValidationError, match="supports-wrong-type"):
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                tier="critic",
                supports=[skill_ref.record_id],
            )

    def test_refutes_wrong_type_research_rejects(self, tmp_path: Path):
        """refutes pointing at a research record → refutes-wrong-type."""
        run_dir = tmp_path / "run"
        state = RunState()

        research_ref = _emit_research(run_dir, state)

        with pytest.raises(LayerAValidationError, match="refutes-wrong-type"):
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                tier="critic",
                refutes=[research_ref.record_id],
            )

    def test_refutes_wrong_type_skill_use_rejects(self, tmp_path: Path):
        """refutes pointing at a skill_use record → refutes-wrong-type."""
        run_dir = tmp_path / "run"
        state = RunState()

        skill_ref = _emit_skill_use(run_dir, state)

        with pytest.raises(LayerAValidationError, match="refutes-wrong-type"):
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                tier="critic",
                refutes=[skill_ref.record_id],
            )

    def test_valid_critic_with_supports_emits(self, tmp_path: Path):
        """critic claim with supports=[existing_claim_id] emits successfully."""
        run_dir = tmp_path / "run"
        state = RunState()

        # Emit the target claim first
        base_ref = _emit_claim("TEST-C-001", run_dir, state)

        critic_ref = _emit_claim(
            "TEST-C-002",
            run_dir,
            state,
            tier="critic",
            supports=[base_ref.record_id],
        )

        assert critic_ref.record_id is not None
        rec = json.loads(record_path(run_dir, critic_ref.record_id).read_text())
        assert rec["tier"] == "critic"
        assert base_ref.record_id in rec["supports"]

    def test_valid_critic_with_refutes_emits(self, tmp_path: Path):
        """critic claim with refutes=[existing_claim_id] emits successfully."""
        run_dir = tmp_path / "run"
        state = RunState()

        base_ref = _emit_claim("TEST-C-001", run_dir, state)

        critic_ref = _emit_claim(
            "TEST-C-002",
            run_dir,
            state,
            tier="critic",
            refutes=[base_ref.record_id],
        )

        rec = json.loads(record_path(run_dir, critic_ref.record_id).read_text())
        assert rec["tier"] == "critic"
        assert base_ref.record_id in rec["refutes"]

    def test_valid_critic_with_both_emits(self, tmp_path: Path):
        """critic claim with both supports and refutes emits successfully."""
        run_dir = tmp_path / "run"
        state = RunState()

        base1_ref = _emit_claim("TEST-C-001", run_dir, state)
        base2_ref = _emit_claim("TEST-C-002", run_dir, state)

        critic_ref = _emit_claim(
            "TEST-C-003",
            run_dir,
            state,
            tier="critic",
            supports=[base1_ref.record_id],
            refutes=[base2_ref.record_id],
        )

        rec = json.loads(record_path(run_dir, critic_ref.record_id).read_text())
        assert rec["tier"] == "critic"
        assert base1_ref.record_id in rec["supports"]
        assert base2_ref.record_id in rec["refutes"]

    def test_draft_claim_empty_supports_refutes_emits(self, tmp_path: Path):
        """draft/published claim without supports/refutes emits fine (fields optional)."""
        run_dir = tmp_path / "run"
        state = RunState()

        ref = _emit_claim("TEST-C-001", run_dir, state, tier="draft")
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["supports"] == []
        assert rec["refutes"] == []

    def test_critic_no_edges_increments_rejection_count(self, tmp_path: Path):
        """critic tier with no edges increments rejectionCount (critic-requires-edge)."""
        run_dir = tmp_path / "run"
        state = RunState()

        try:
            _emit_claim("TEST-C-001", run_dir, state, tier="critic")
        except LayerAValidationError:
            pass

        assert state.rejectionCount == 1

    def test_dangling_supports_increments_rejection_count(self, tmp_path: Path):
        """Dangling supports target increments rejectionCount (V2)."""
        run_dir = tmp_path / "run"
        state = RunState()

        try:
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                tier="critic",
                supports=["nonexistent"],
            )
        except LayerAValidationError:
            pass

        assert state.rejectionCount == 1

    def test_dangling_supports_zero_partial_write(self, tmp_path: Path):
        """Dangling supports → no record.json written (V2)."""
        run_dir = tmp_path / "run"
        state = RunState()

        try:
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                tier="critic",
                supports=["nonexistent"],
            )
        except LayerAValidationError:
            pass

        assert state.records == [], "no records should be registered in run_state"
        records_dir = run_dir / "records"
        if records_dir.exists():
            written = list(records_dir.glob("*/record.json"))
            assert written == [], f"no record.json should be written, found: {written}"

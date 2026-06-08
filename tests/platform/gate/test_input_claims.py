"""T29 (completion) — input_claims data-lineage field + check_input_claims_exist guard.

Covers:
  - ClaimRecord.input_claims defaults to [].
  - input_claims field is NOT accepted on other record types (extra=forbid).
  - Valid claim with input_claims referencing a real prior claim emits successfully;
    emitted record.json contains input_claims.
  - Dangling input_claims id → rejected (rule_id='input-claims-not-found'), no partial
    write: state.records unchanged, no record.json on disk (V2).
  - input_claims referencing a research/skill_use record → rejected
    (rule_id='input-claims-wrong-type').
  - input_claims default [] → back-compat; existing claims unaffected.
  - supports/refutes and input_claims are independent (a claim can have both).

Cites: T29, V2, C13.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from insight_kit.libs.validation import ValidationError as LayerAValidationError
from insight_kit.platform.gate.emit import (
    check_input_claims_exist,
    ik_claim_emit,
    ik_research_emit,
    ik_skill_use_emit,
)
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.schema import (
    ClaimRecord,
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
# Schema tests: ClaimRecord.input_claims field
# ---------------------------------------------------------------------------


class TestInputClaimsSchema:
    def test_input_claims_defaults_to_empty_list(self):
        """ClaimRecord.input_claims defaults to []."""
        r = ClaimRecord(
            claim_id="TEST-C-001",
            fields={"v": FieldEntry(value=1)},
        )
        assert r.input_claims == []

    def test_input_claims_can_be_populated(self):
        """ClaimRecord.input_claims accepts a list of strings."""
        r = ClaimRecord(
            claim_id="TEST-C-001",
            fields={"v": FieldEntry(value=1)},
            input_claims=["some-record-id"],
        )
        assert r.input_claims == ["some-record-id"]

    def test_intervention_rejects_input_claims(self):
        """InterventionRecord (extra=forbid) rejects an 'input_claims' field."""
        with pytest.raises(PydanticValidationError):
            InterventionRecord(
                intervention_id="INT-I-001",
                intent={"description": "do something"},
                input_claims=["some-record-id"],  # type: ignore[call-arg]
            )

    def test_research_rejects_input_claims(self):
        """ResearchRecord (extra=forbid) rejects an 'input_claims' field."""
        with pytest.raises(PydanticValidationError):
            ResearchRecord(
                research_id="RSR-R-001",
                snapshot_ref="http://example.com",
                query="q",
                source="s",
                timestamp="2026-01-01T00:00:00+00:00",
                input_claims=["some-record-id"],  # type: ignore[call-arg]
            )

    def test_skill_use_rejects_input_claims(self):
        """SkillUseRecord (extra=forbid) rejects an 'input_claims' field."""
        with pytest.raises(PydanticValidationError):
            SkillUseRecord(
                skill_use_id="SKL-R-001",
                snapshot_ref="tool://test",
                tool="t",
                source="s",
                timestamp="2026-01-01T00:00:00+00:00",
                input_claims=["some-record-id"],  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# Emit path: valid input_claims accepted
# ---------------------------------------------------------------------------


class TestInputClaimsValidEmit:
    def test_claim_with_input_claims_emits_and_persists(self, tmp_path: Path):
        """Claim with input_claims referencing a real prior claim emits successfully.

        The emitted record.json must contain input_claims with the prior claim's record_id.
        """
        run_dir = tmp_path / "run"
        state = RunState()

        # Emit the source claim first
        source_ref = _emit_claim("TEST-C-001", run_dir, state)

        # Emit a derived claim referencing the source
        derived_ref = _emit_claim(
            "TEST-C-002",
            run_dir,
            state,
            input_claims=[source_ref.record_id],
        )

        assert derived_ref.record_id is not None
        rec = json.loads(record_path(run_dir, derived_ref.record_id).read_text())
        assert rec["input_claims"] == [source_ref.record_id]

    def test_input_claims_default_empty_existing_claims_unaffected(self, tmp_path: Path):
        """Claims without input_claims emit with input_claims=[] (back-compat)."""
        run_dir = tmp_path / "run"
        state = RunState()

        ref = _emit_claim("TEST-C-001", run_dir, state)
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["input_claims"] == []

    def test_claim_with_supports_refutes_and_input_claims(self, tmp_path: Path):
        """supports/refutes and input_claims are independent — a claim can have both."""
        run_dir = tmp_path / "run"
        state = RunState()

        # base claim to be supported/refuted and used as input
        base_ref = _emit_claim("TEST-C-001", run_dir, state)
        # another claim as input source
        source_ref = _emit_claim("TEST-C-002", run_dir, state)

        critic_ref = _emit_claim(
            "TEST-C-003",
            run_dir,
            state,
            tier="critic",
            supports=[base_ref.record_id],
            input_claims=[source_ref.record_id],
        )

        rec = json.loads(record_path(run_dir, critic_ref.record_id).read_text())
        assert rec["tier"] == "critic"
        assert base_ref.record_id in rec["supports"]
        assert source_ref.record_id in rec["input_claims"]


# ---------------------------------------------------------------------------
# Emit path: dangling input_claims → rejected, V2 no-partial-write
# ---------------------------------------------------------------------------


class TestInputClaimsDanglingRejection:
    def test_dangling_input_claims_raises_not_found(self, tmp_path: Path):
        """input_claims referencing a nonexistent record → input-claims-not-found."""
        run_dir = tmp_path / "run"
        state = RunState()

        with pytest.raises(LayerAValidationError, match="input-claims-not-found"):
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                input_claims=["nonexistent-record-id"],
            )

    def test_dangling_input_claims_no_partial_write(self, tmp_path: Path):
        """Dangling input_claims → state.records unchanged, no record.json on disk (V2)."""
        run_dir = tmp_path / "run"
        state = RunState()

        try:
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                input_claims=["nonexistent-record-id"],
            )
        except LayerAValidationError:
            pass

        # V2: state must be clean — no RecordRef appended
        assert state.records == [], "no records should be registered in run_state"
        # V2: no record.json must be written to disk
        records_dir = run_dir / "records"
        if records_dir.exists():
            written = list(records_dir.glob("*/record.json"))
            assert written == [], f"no record.json should be written, found: {written}"

    def test_dangling_input_claims_increments_rejection_count(self, tmp_path: Path):
        """Dangling input_claims increments rejectionCount."""
        run_dir = tmp_path / "run"
        state = RunState()

        try:
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                input_claims=["nonexistent-record-id"],
            )
        except LayerAValidationError:
            pass

        assert state.rejectionCount == 1


# ---------------------------------------------------------------------------
# Emit path: input_claims wrong-type (research / skill_use)
# ---------------------------------------------------------------------------


class TestInputClaimsWrongTypeRejection:
    def test_input_claims_research_wrong_type(self, tmp_path: Path):
        """input_claims pointing at a research record → input-claims-wrong-type."""
        run_dir = tmp_path / "run"
        state = RunState()

        research_ref = _emit_research(run_dir, state)

        with pytest.raises(LayerAValidationError, match="input-claims-wrong-type"):
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                input_claims=[research_ref.record_id],
            )

    def test_input_claims_skill_use_wrong_type(self, tmp_path: Path):
        """input_claims pointing at a skill_use record → input-claims-wrong-type."""
        run_dir = tmp_path / "run"
        state = RunState()

        skill_ref = _emit_skill_use(run_dir, state)

        with pytest.raises(LayerAValidationError, match="input-claims-wrong-type"):
            _emit_claim(
                "TEST-C-001",
                run_dir,
                state,
                input_claims=[skill_ref.record_id],
            )

    def test_input_claims_wrong_type_no_partial_write(self, tmp_path: Path):
        """Wrong-type input_claims → no record.json written (V2)."""
        run_dir = tmp_path / "run"
        state = RunState()

        research_ref = _emit_research(run_dir, state)
        # Reset state to track only the claim attempt
        claim_state = RunState()

        try:
            _emit_claim(
                "TEST-C-001",
                run_dir,
                claim_state,
                input_claims=[research_ref.record_id],
            )
        except LayerAValidationError:
            pass

        assert claim_state.records == [], "no claim should be registered in run_state"

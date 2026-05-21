"""Tests for gate/emit.py — T2.

Covers:
  V1  — only emit writes records.jsonl / record.json.
  V2  — bad payload → raise + no partial write + rejectionCount incremented.
  V4  — both fingerprints present on every emitted record.
  Determinism — emit same input twice into fresh dirs → identical record_fingerprint.
  Typed wrappers — ik_claim_emit, ik_intervention_emit, ik_research_emit, ik_skill_use_emit.
  Layer-A guards — claim_id format + duplicate-in-run.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.gate.emit import (
    _record_emit,
    ik_claim_emit,
    ik_intervention_emit,
    ik_research_emit,
    ik_skill_use_emit,
)
from insight_kit.gate.runstate import RunState
from insight_kit.gate.store import index_path, record_path
from insight_kit.validation import ValidationError as LayerAValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


def _valid_claim_payload() -> dict:
    return {
        "record_type": "claim",
        "claim_id": "TEST-D-001",
        "fields": {"revenue": {"value": 123456, "fmt_hint": "$,.0f"}},
        "tier": "draft",
    }


# ---------------------------------------------------------------------------
# V1 — only emit writes records.jsonl / record.json
# ---------------------------------------------------------------------------

class TestV1_OnlyEmitWrites:
    def test_emit_creates_record_json(self, run_dir, state):
        ref = _record_emit(_valid_claim_payload(), run_state=state, run_dir=run_dir)
        assert record_path(run_dir, ref.record_id).exists()

    def test_emit_appends_records_jsonl(self, run_dir, state):
        _record_emit(_valid_claim_payload(), run_state=state, run_dir=run_dir)
        assert index_path(run_dir).exists()
        rows = [ln for ln in index_path(run_dir).read_text().splitlines() if ln.strip()]
        assert len(rows) == 1

    def test_two_emits_two_rows(self, run_dir, state):
        p1 = _valid_claim_payload()
        p2 = _valid_claim_payload()
        p2["claim_id"] = "TEST-D-002"
        _record_emit(p1, run_state=state, run_dir=run_dir)
        _record_emit(p2, run_state=state, run_dir=run_dir)
        rows = [ln for ln in index_path(run_dir).read_text().splitlines() if ln.strip()]
        assert len(rows) == 2

    def test_records_jsonl_carries_record_type(self, run_dir, state):
        _record_emit(_valid_claim_payload(), run_state=state, run_dir=run_dir)
        row = json.loads(index_path(run_dir).read_text().strip())
        assert row["record_type"] == "claim"


# ---------------------------------------------------------------------------
# V2 — bad payload → raise + no partial write + rejectionCount incremented
# ---------------------------------------------------------------------------

class TestV2_BadPayloadReject:
    def test_schema_invalid_raises(self, run_dir, state):
        """Missing required field → pydantic error → wrapped ValidationError."""
        with pytest.raises(LayerAValidationError, match="schema-validation"):
            _record_emit(
                {"record_type": "claim"},  # missing claim_id and fields
                run_state=state,
                run_dir=run_dir,
            )

    def test_schema_invalid_increments_rejection_count(self, run_dir, state):
        try:
            _record_emit({"record_type": "claim"}, run_state=state, run_dir=run_dir)
        except LayerAValidationError:
            pass
        assert state.rejectionCount == 1

    def test_schema_invalid_no_partial_write(self, run_dir, state):
        """V2 — no record.json written on rejection."""
        try:
            _record_emit({"record_type": "claim"}, run_state=state, run_dir=run_dir)
        except LayerAValidationError:
            pass
        assert not index_path(run_dir).exists()

    def test_unknown_record_type_raises(self, run_dir, state):
        with pytest.raises(LayerAValidationError, match="schema-validation"):
            _record_emit(
                {"record_type": "hallucinated", "claim_id": "TEST-D-001"},
                run_state=state,
                run_dir=run_dir,
            )

    def test_unknown_record_type_increments_rejection(self, run_dir, state):
        try:
            _record_emit(
                {"record_type": "hallucinated"},
                run_state=state,
                run_dir=run_dir,
            )
        except LayerAValidationError:
            pass
        assert state.rejectionCount == 1

    def test_layer_a_claim_id_format_raises(self, run_dir, state):
        payload = _valid_claim_payload()
        payload["claim_id"] = "bad_format"  # does not match regex
        with pytest.raises(LayerAValidationError, match="claim-id-format"):
            _record_emit(payload, run_state=state, run_dir=run_dir)

    def test_layer_a_claim_id_format_increments_rejection(self, run_dir, state):
        payload = _valid_claim_payload()
        payload["claim_id"] = "bad_format"
        try:
            _record_emit(payload, run_state=state, run_dir=run_dir)
        except LayerAValidationError:
            pass
        assert state.rejectionCount == 1

    def test_layer_a_claim_id_format_no_partial_write(self, run_dir, state):
        payload = _valid_claim_payload()
        payload["claim_id"] = "bad_format"
        try:
            _record_emit(payload, run_state=state, run_dir=run_dir)
        except LayerAValidationError:
            pass
        assert not index_path(run_dir).exists()

    def test_layer_a_duplicate_in_run_raises(self, run_dir, state):
        p1 = _valid_claim_payload()
        _record_emit(p1, run_state=state, run_dir=run_dir)
        with pytest.raises(LayerAValidationError, match="claim-id-duplicate-in-run"):
            _record_emit(p1, run_state=state, run_dir=run_dir)

    def test_layer_a_duplicate_in_run_increments_rejection(self, run_dir, state):
        p1 = _valid_claim_payload()
        _record_emit(p1, run_state=state, run_dir=run_dir)
        assert state.rejectionCount == 0  # first emit succeeded
        try:
            _record_emit(p1, run_state=state, run_dir=run_dir)
        except LayerAValidationError:
            pass
        assert state.rejectionCount == 1

    def test_multiple_rejections_counted(self, run_dir, state):
        for _ in range(3):
            try:
                _record_emit({"record_type": "claim"}, run_state=state, run_dir=run_dir)
            except LayerAValidationError:
                pass
        assert state.rejectionCount == 3


# ---------------------------------------------------------------------------
# V4 — both fingerprints present on every record
# ---------------------------------------------------------------------------

class TestV4_Fingerprints:
    def test_record_fingerprint_present(self, run_dir, state):
        ref = _record_emit(_valid_claim_payload(), run_state=state, run_dir=run_dir)
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert "record_fingerprint" in rec
        assert len(rec["record_fingerprint"]) == 64

    def test_data_fingerprint_present(self, run_dir, state):
        ref = _record_emit(_valid_claim_payload(), run_state=state, run_dir=run_dir)
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert "data_fingerprint" in rec
        assert len(rec["data_fingerprint"]) == 64

    def test_both_fingerprints_in_index_row(self, run_dir, state):
        _record_emit(_valid_claim_payload(), run_state=state, run_dir=run_dir)
        row = json.loads(index_path(run_dir).read_text().strip())
        assert "record_fingerprint" in row
        assert "data_fingerprint" in row

    def test_research_record_has_fingerprints(self, run_dir, state):
        ref = ik_research_emit(
            "RES-001", "s/r.json", "query", "source",
            timestamp="2026-05-21T10:00:00+00:00",
            run_state=state, run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert "record_fingerprint" in rec
        assert "data_fingerprint" in rec


# ---------------------------------------------------------------------------
# Determinism — same input → same record_fingerprint (C2)
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_claim_same_fp_in_fresh_dirs(self, tmp_path):
        """Emit same payload into two fresh dirs → identical record_fingerprint."""
        payload = {
            "record_type": "claim",
            "claim_id": "TEST-D-001",
            "fields": {"revenue": {"value": 123456, "fmt_hint": "$,.0f"}},
            "tier": "draft",
        }
        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"

        state_a = RunState()
        state_b = RunState()

        ref_a = _record_emit(payload, run_state=state_a, run_dir=dir_a)
        ref_b = _record_emit(dict(payload), run_state=state_b, run_dir=dir_b)

        assert ref_a.record_fingerprint == ref_b.record_fingerprint

    def test_different_payloads_different_fps(self, tmp_path):
        dir_a = tmp_path / "run_a"
        dir_b = tmp_path / "run_b"
        p1 = _valid_claim_payload()
        p2 = _valid_claim_payload()
        p2["claim_id"] = "TEST-D-002"

        ref_a = _record_emit(p1, run_state=RunState(), run_dir=dir_a)
        ref_b = _record_emit(p2, run_state=RunState(), run_dir=dir_b)

        assert ref_a.record_fingerprint != ref_b.record_fingerprint


# ---------------------------------------------------------------------------
# Typed wrappers
# ---------------------------------------------------------------------------

class TestIkClaimEmit:
    def test_basic_emit_returns_ref(self, run_dir, state):
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 123456},
            run_state=state, run_dir=run_dir,
        )
        assert ref.record_type == "claim"
        assert ref.record_id

    def test_fields_value_only_form(self, run_dir, state):
        ref = ik_claim_emit(
            "TEST-D-001",
            {"count": 42},
            run_state=state, run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["fields"]["count"]["value"] == 42
        assert rec["fields"]["count"]["fmt_hint"] is None

    def test_fields_tuple_form(self, run_dir, state):
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": (123456, "$,.0f")},
            run_state=state, run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["fields"]["revenue"]["value"] == 123456
        assert rec["fields"]["revenue"]["fmt_hint"] == "$,.0f"

    def test_fields_dict_form(self, run_dir, state):
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": {"value": 99, "fmt_hint": "%.2f"}},
            run_state=state, run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["fields"]["revenue"]["value"] == 99

    def test_tier_published(self, run_dir, state):
        ref = ik_claim_emit(
            "TEST-D-001",
            {"x": 1},
            tier="published",
            run_state=state, run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "published"

    def test_invalid_claim_id_raises(self, run_dir, state):
        with pytest.raises(LayerAValidationError):
            ik_claim_emit("bad-id", {"x": 1}, run_state=state, run_dir=run_dir)

    def test_adds_to_runstate(self, run_dir, state):
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        assert len(state.records) == 1
        assert state.records[0].record_type == "claim"


class TestIkInterventionEmit:
    def test_basic_emit(self, run_dir, state):
        ref = ik_intervention_emit(
            "INT-001",
            {"description": "send email"},
            run_state=state, run_dir=run_dir,
        )
        assert ref.record_type == "intervention"

    def test_with_realized(self, run_dir, state):
        ref = ik_intervention_emit(
            "INT-001",
            {"description": "send email"},
            realized={"status": "applied"},
            run_state=state, run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["realized"]["status"] == "applied"

    def test_invalid_realized_status_raises(self, run_dir, state):
        with pytest.raises(LayerAValidationError, match="schema-validation"):
            ik_intervention_emit(
                "INT-001",
                {"description": "x"},
                realized={"status": "bad_status"},
                run_state=state, run_dir=run_dir,
            )


class TestIkResearchEmit:
    def test_basic_emit(self, run_dir, state):
        ref = ik_research_emit(
            "RES-001", "s/r.json", "what is X", "web",
            timestamp="2026-05-21T10:00:00+00:00",
            run_state=state, run_dir=run_dir,
        )
        assert ref.record_type == "research"

    def test_timestamp_auto_set(self, run_dir, state):
        ref = ik_research_emit(
            "RES-001", "s/r.json", "query", "source",
            run_state=state, run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["timestamp"]  # auto-set


class TestIkSkillUseEmit:
    def test_basic_emit(self, run_dir, state):
        ref = ik_skill_use_emit(
            "SKU-001", "s/k.json", "tavily", "tavily-api",
            timestamp="2026-05-21T10:00:00+00:00",
            run_state=state, run_dir=run_dir,
        )
        assert ref.record_type == "skill_use"

    def test_timestamp_auto_set(self, run_dir, state):
        ref = ik_skill_use_emit(
            "SKU-001", "s/k.json", "tavily", "tavily-api",
            run_state=state, run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["timestamp"]

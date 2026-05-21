"""T7 — Tier gate tests (V6, V22, C7).

published-tier claim/intervention requires:
  - Full fingerprint set in run.json: data_fingerprint + code_fingerprint +
    agent_version + env_fingerprint
  - data_fingerprint_source == registered_input

Missing any required key OR source == payload → DOWNGRADE to draft (not reject).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.gate.emit import ik_claim_emit, ik_intervention_emit
from insight_kit.gate.runstate import RunState
from insight_kit.gate.store import record_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


FULL_FP_SET = {
    "data_fingerprint": "abc123",
    "code_fingerprint": "def456",
    "agent_version": "1.0.0",
    "env_fingerprint": "ghi789",
}


def _write_run_json(run_dir: Path, extra: dict | None = None) -> Path:
    """Write a run.json to run_dir with optional fingerprint fields."""
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = extra or {}
    run_json = run_dir / "run.json"
    run_json.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    return run_json


# ---------------------------------------------------------------------------
# T7 — V6, V22: tier gate downgrades
# ---------------------------------------------------------------------------


class TestTierGateDowngrade:
    def test_published_payload_source_downgraded_to_draft(self, run_dir, state):
        """payload source + published → emitted as draft (V22, C7)."""
        _write_run_json(run_dir, FULL_FP_SET)
        # No input_data → data_fingerprint_source == payload
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="published",
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "draft", "published+payload source must downgrade to draft"

    def test_published_payload_source_downgrade_reason_recorded(self, run_dir, state):
        """Downgrade reason is stored in the emitted record."""
        _write_run_json(run_dir, FULL_FP_SET)
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="published",
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert "tier_downgrade_reason" in rec, "downgrade reason must be recorded"
        assert rec["tier_downgrade_reason"]  # non-empty

    def test_published_missing_code_fingerprint_downgraded(self, run_dir, state):
        """Full fp set missing code_fingerprint → downgrade to draft (V6)."""
        incomplete = {
            "data_fingerprint": "abc123",
            "agent_version": "1.0.0",
            "env_fingerprint": "ghi789",
            # code_fingerprint missing
        }
        _write_run_json(run_dir, incomplete)
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="published",
            run_state=state,
            run_dir=run_dir,
            input_data=b"real-input-data",
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "draft"

    def test_published_missing_agent_version_downgraded(self, run_dir, state):
        """Full fp set missing agent_version → downgrade to draft (V6)."""
        incomplete = {
            "data_fingerprint": "abc123",
            "code_fingerprint": "def456",
            "env_fingerprint": "ghi789",
            # agent_version missing
        }
        _write_run_json(run_dir, incomplete)
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="published",
            run_state=state,
            run_dir=run_dir,
            input_data=b"real-input-data",
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "draft"

    def test_published_missing_env_fingerprint_downgraded(self, run_dir, state):
        """Full fp set missing env_fingerprint → downgrade to draft (V6)."""
        incomplete = {
            "data_fingerprint": "abc123",
            "code_fingerprint": "def456",
            "agent_version": "1.0.0",
            # env_fingerprint missing
        }
        _write_run_json(run_dir, incomplete)
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="published",
            run_state=state,
            run_dir=run_dir,
            input_data=b"real-input-data",
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "draft"

    def test_published_no_run_json_downgraded(self, run_dir, state):
        """No run.json at all → downgrade to draft (V6)."""
        # Don't write run.json
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="published",
            run_state=state,
            run_dir=run_dir,
            input_data=b"real-input-data",
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "draft"

    def test_published_full_set_registered_stays_published(self, run_dir, state):
        """Full fp set + registered_input source → stays published (V6, V22)."""
        _write_run_json(run_dir, FULL_FP_SET)
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="published",
            run_state=state,
            run_dir=run_dir,
            input_data=b"real-input-data",  # → data_fingerprint_source = registered_input
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "published"
        assert rec["data_fingerprint_source"] == "registered_input"
        assert "tier_downgrade_reason" not in rec

    def test_draft_not_affected_by_tier_gate(self, run_dir, state):
        """draft-tier records are not subject to the tier gate (C7 applies to published only)."""
        # No run.json, payload source — draft must always succeed
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="draft",
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "draft"
        assert "tier_downgrade_reason" not in rec

    def test_intervention_published_payload_source_downgraded(self, run_dir, state):
        """Intervention records also subject to tier gate (C7)."""
        _write_run_json(run_dir, FULL_FP_SET)
        ref = ik_intervention_emit(
            "INT-001",
            {"description": "send email"},
            tier="published",
            run_state=state,
            run_dir=run_dir,
            # No input_data → payload source
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "draft"

    def test_intervention_published_full_set_registered_stays(self, run_dir, state):
        """Intervention with full fp set + registered_input stays published."""
        _write_run_json(run_dir, FULL_FP_SET)
        ref = ik_intervention_emit(
            "INT-001",
            {"description": "send email"},
            tier="published",
            run_state=state,
            run_dir=run_dir,
            input_data=b"real-input-data",
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "published"

    def test_downgrade_does_not_increment_rejection_count(self, run_dir, state):
        """Downgrade is NOT a rejection — record still emits (C7)."""
        _write_run_json(run_dir, FULL_FP_SET)
        ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="published",
            run_state=state,
            run_dir=run_dir,
            # no input_data → payload → downgrade
        )
        assert state.rejectionCount == 0, "downgrade must not increment rejectionCount"
        assert len(state.records) == 1, "record must still be emitted"

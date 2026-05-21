"""Tests for gate/runstate.py — T5.

Covers:
  V10  — finalizeRun idempotent (completedAt guard, second call is no-op).
  V17  — manifest_complete detects count mismatch.
  Plus: RunState accumulation, RecordRef to_dict, write_run_json.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.gate.emit import ik_claim_emit, ik_research_emit
from insight_kit.gate.runstate import (
    ManifestError,
    RecordRef,
    RunState,
    finalizeRun,
    write_run_json,
)
from insight_kit.gate.store import index_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


# ---------------------------------------------------------------------------
# RunState accumulation
# ---------------------------------------------------------------------------

class TestRunStateAccumulation:
    def test_initial_state(self, state):
        assert state.records == []
        assert state.rejectionCount == 0
        assert state.critiqueRounds == 0
        assert state.completedAt is None

    def test_emit_adds_to_records(self, run_dir, state):
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        assert len(state.records) == 1

    def test_two_emits_two_records(self, run_dir, state):
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        ik_claim_emit("TEST-D-002", {"x": 2}, run_state=state, run_dir=run_dir)
        assert len(state.records) == 2

    def test_record_ids_list(self, run_dir, state):
        r1 = ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        r2 = ik_claim_emit("TEST-D-002", {"x": 2}, run_state=state, run_dir=run_dir)
        ids = state.record_ids()
        assert r1.record_id in ids
        assert r2.record_id in ids

    def test_rejection_count_incremented(self, run_dir, state):
        from insight_kit.validation import ValidationError as LayerAValidationError
        try:
            ik_claim_emit("bad-id", {"x": 1}, run_state=state, run_dir=run_dir)
        except LayerAValidationError:
            pass
        assert state.rejectionCount == 1

    def test_critique_rounds_manual_increment(self, state):
        state.critiqueRounds += 1
        assert state.critiqueRounds == 1


# ---------------------------------------------------------------------------
# RecordRef
# ---------------------------------------------------------------------------

class TestRecordRef:
    def test_to_dict_structure(self, run_dir):
        ref = RecordRef(
            record_id="abc123",
            record_type="claim",
            record_fingerprint="f" * 64,
            run_dir=run_dir,
        )
        d = ref.to_dict()
        assert d["record_id"] == "abc123"
        assert d["record_type"] == "claim"
        assert d["record_fingerprint"] == "f" * 64
        assert "run_dir" in d


# ---------------------------------------------------------------------------
# V10 — finalizeRun idempotent
# ---------------------------------------------------------------------------

class TestFinalizeRunIdempotent:
    def test_sets_completed_at(self, state):
        finalizeRun(state, assert_manifest=False)
        assert state.completedAt is not None

    def test_second_call_is_no_op(self, state):
        finalizeRun(state, assert_manifest=False)
        first_ts = state.completedAt
        finalizeRun(state, assert_manifest=False)
        assert state.completedAt == first_ts  # unchanged — idempotent

    def test_third_call_still_no_op(self, state):
        finalizeRun(state, assert_manifest=False)
        finalizeRun(state, assert_manifest=False)
        finalizeRun(state, assert_manifest=False)
        assert state.completedAt is not None

    def test_returns_run_state(self, state):
        result = finalizeRun(state, assert_manifest=False)
        assert result is state

    def test_completed_at_is_iso8601(self, state):
        finalizeRun(state, assert_manifest=False)
        from datetime import datetime
        # Should parse without error
        dt = datetime.fromisoformat(state.completedAt)
        assert dt is not None

    def test_double_finalize_agent_end_session_shutdown_safe(self, state):
        """Simulates agent_end + session_shutdown both calling finalizeRun (V10)."""
        finalizeRun(state, assert_manifest=False)  # agent_end
        ts = state.completedAt
        finalizeRun(state, assert_manifest=False)  # session_shutdown
        assert state.completedAt == ts  # same timestamp, no error


# ---------------------------------------------------------------------------
# V17 — manifest_complete detects count mismatch
# ---------------------------------------------------------------------------

class TestManifestComplete:
    def test_matching_counts_passes(self, run_dir, state):
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        # records.jsonl has 1 row, RunState.records has 1 entry
        state.manifest_complete()  # should not raise

    def test_mismatch_raises_manifest_error(self, run_dir, state):
        """V17 — inject a phantom record into RunState without writing to disk."""
        state.run_dir = run_dir
        # Emit one real record
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        # Manually add a phantom ref that has no corresponding disk row
        phantom = RecordRef(
            record_id="phantom000000000",
            record_type="claim",
            record_fingerprint="0" * 64,
            run_dir=run_dir,
        )
        state.records.append(phantom)
        # Now RunState has 2 entries but records.jsonl has 1 row
        with pytest.raises(ManifestError):
            state.manifest_complete()

    def test_extra_row_in_jsonl_raises_manifest_error(self, run_dir, state):
        """V17 — extra row in records.jsonl vs RunState."""
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        # Manually append a phantom row to records.jsonl
        idx = index_path(run_dir)
        with idx.open("a") as f:
            f.write('{"record_id":"phantom","record_type":"claim"}\n')
        # Now records.jsonl has 2 rows but RunState.records has 1 entry
        with pytest.raises(ManifestError):
            state.manifest_complete()

    def test_no_run_dir_is_permissive(self, state):
        """manifest_complete is a no-op when run_dir is None (unit test mode)."""
        assert state.run_dir is None
        state.manifest_complete()  # should not raise

    def test_finalizeRun_with_manifest_passes_on_clean_state(self, run_dir, state):
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        finalizeRun(state, assert_manifest=True)  # should not raise
        assert state.completedAt is not None

    def test_finalizeRun_with_manifest_raises_on_mismatch(self, run_dir, state):
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        # Add phantom
        state.records.append(
            RecordRef("phantom", "claim", "0" * 64, run_dir)
        )
        with pytest.raises(ManifestError):
            finalizeRun(state, assert_manifest=True)

    def test_empty_run_passes_manifest(self, run_dir, state):
        state.run_dir = run_dir
        state.manifest_complete()  # 0 == 0, should pass

    def test_multiple_record_types_manifest(self, run_dir, state):
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        ik_research_emit(
            "RES-001", "s/r.json", "query", "source",
            timestamp="2026-05-21T10:00:00+00:00",
            run_state=state, run_dir=run_dir,
        )
        state.manifest_complete()  # 2 == 2, should pass


# ---------------------------------------------------------------------------
# write_run_json (I.run)
# ---------------------------------------------------------------------------

class TestWriteRunJson:
    def test_writes_run_json(self, run_dir, state):
        finalizeRun(state, assert_manifest=False)
        path = write_run_json(run_dir, state)
        assert path.exists()
        data = json.loads(path.read_text())
        assert "completedAt" in data
        assert "rejectionCount" in data
        assert "record_count" in data

    def test_extra_metadata_merged(self, run_dir, state):
        finalizeRun(state, assert_manifest=False)
        path = write_run_json(run_dir, state, extra={"agent_version": "v1.2.3"})
        data = json.loads(path.read_text())
        assert data["agent_version"] == "v1.2.3"

    def test_record_ids_in_run_json(self, run_dir, state):
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        finalizeRun(state, assert_manifest=False)
        path = write_run_json(run_dir, state)
        data = json.loads(path.read_text())
        assert len(data["record_ids"]) == 1
        assert data["record_count"] == 1

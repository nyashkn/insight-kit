"""T6 — Supersession tests (V3).

A correcting record carries a `supersedes` edge naming the record_id it supersedes.
Validates that the superseded record exists in the run dir at emit time.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.gate.emit import ik_claim_emit, ik_intervention_emit, ik_research_emit
from insight_kit.gate.runstate import RunState
from insight_kit.gate.store import record_path
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


# ---------------------------------------------------------------------------
# T6 — V3: supersedes edge validation
# ---------------------------------------------------------------------------


class TestSupersession:
    def test_supersedes_existing_record_accepted(self, run_dir, state):
        """A new record superseding an existing record_id succeeds."""
        ref1 = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            run_state=state,
            run_dir=run_dir,
        )
        # Emit correction with different claim_id that supersedes ref1.record_id
        ref2 = ik_claim_emit(
            "TEST-D-002",
            {"revenue": 200},
            supersedes=ref1.record_id,
            run_state=state,
            run_dir=run_dir,
        )
        rec2 = json.loads(record_path(run_dir, ref2.record_id).read_text())
        assert rec2["supersedes"] == ref1.record_id

    def test_supersedes_nonexistent_record_raises(self, run_dir, state):
        """Superseding a record_id that does not exist in run dir → reject (V3)."""
        with pytest.raises(LayerAValidationError, match="supersedes-not-found"):
            ik_claim_emit(
                "TEST-D-001",
                {"revenue": 100},
                supersedes="deadbeefdeadbeef",  # non-existent record_id
                run_state=state,
                run_dir=run_dir,
            )

    def test_supersedes_nonexistent_increments_rejection(self, run_dir, state):
        """Rejected supersession increments rejectionCount (V2)."""
        try:
            ik_claim_emit(
                "TEST-D-001",
                {"revenue": 100},
                supersedes="deadbeefdeadbeef",
                run_state=state,
                run_dir=run_dir,
            )
        except LayerAValidationError:
            pass
        assert state.rejectionCount == 1

    def test_supersedes_nonexistent_no_partial_write(self, run_dir, state):
        """No partial write on supersession rejection (V2)."""
        from insight_kit.gate.store import index_path

        try:
            ik_claim_emit(
                "TEST-D-001",
                {"revenue": 100},
                supersedes="deadbeefdeadbeef",
                run_state=state,
                run_dir=run_dir,
            )
        except LayerAValidationError:
            pass
        # No records.jsonl should exist since nothing was written
        assert not index_path(run_dir).exists()

    def test_supersedes_chain_three_records(self, run_dir, state):
        """Three-hop supersession chain is valid."""
        ref1 = ik_claim_emit("TEST-D-001", {"v": 1}, run_state=state, run_dir=run_dir)
        ref2 = ik_claim_emit(
            "TEST-D-002",
            {"v": 2},
            supersedes=ref1.record_id,
            run_state=state,
            run_dir=run_dir,
        )
        ref3 = ik_claim_emit(
            "TEST-D-003",
            {"v": 3},
            supersedes=ref2.record_id,
            run_state=state,
            run_dir=run_dir,
        )
        rec3 = json.loads(record_path(run_dir, ref3.record_id).read_text())
        assert rec3["supersedes"] == ref2.record_id

    def test_supersedes_none_is_valid(self, run_dir, state):
        """A record without supersedes is perfectly valid (no regression)."""
        ref = ik_claim_emit("TEST-D-001", {"v": 1}, run_state=state, run_dir=run_dir)
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["supersedes"] is None

    def test_supersedes_intervention_record(self, run_dir, state):
        """Supersession works for intervention records too."""
        ref1 = ik_intervention_emit(
            "INT-001",
            {"description": "send email"},
            run_state=state,
            run_dir=run_dir,
        )
        ref2 = ik_intervention_emit(
            "INT-002",
            {"description": "send corrected email"},
            supersedes=ref1.record_id,
            run_state=state,
            run_dir=run_dir,
        )
        rec2 = json.loads(record_path(run_dir, ref2.record_id).read_text())
        assert rec2["supersedes"] == ref1.record_id

    def test_supersedes_research_record(self, run_dir, state):
        """Supersession works for research records too."""
        ref1 = ik_research_emit(
            "RES-001",
            "s/r1.json",
            "query v1",
            "source",
            timestamp="2026-05-21T10:00:00+00:00",
            run_state=state,
            run_dir=run_dir,
        )
        ref2 = ik_research_emit(
            "RES-002",
            "s/r2.json",
            "query v2 corrected",
            "source",
            timestamp="2026-05-21T11:00:00+00:00",
            supersedes=ref1.record_id,
            run_state=state,
            run_dir=run_dir,
        )
        rec2 = json.loads(record_path(run_dir, ref2.record_id).read_text())
        assert rec2["supersedes"] == ref1.record_id

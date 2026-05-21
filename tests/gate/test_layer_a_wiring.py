"""T8 (Layer-A part) — Layer-A validation guards wired into _record_emit (V2, C13).

Tests that the existing insight_kit.validation/ guard functions are invoked
at schema-stage emit time (not post-hoc). All failures must:
  - raise LayerAValidationError
  - increment RunState.rejectionCount
  - produce ZERO partial write (V2)

Layer-B/C runner (ik_run_check) is a SEPARATE module built by a sibling agent.
This file covers ONLY the gate-level (Layer-A) wiring.

Cites: V2, C13.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.gate.emit import _record_emit, ik_claim_emit
from insight_kit.gate.runstate import RunState
from insight_kit.gate.store import index_path
from insight_kit.validation import ValidationError as LayerAValidationError
from insight_kit.validation import (
    check_claim_id_format,
    check_claim_id_unique_in_run,
)


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
# T8 / V2 / C13 — Layer-A guards from validation/ module fire at emit time
# ---------------------------------------------------------------------------


class TestLayerAWiringClaimIdFormat:
    """check_claim_id_format is wired into _record_emit for claim records."""

    def test_invalid_format_raises_layer_a_error(self, run_dir, state):
        """claim_id not matching regex → ValidationError(rule_id='claim-id-format')."""
        with pytest.raises(LayerAValidationError, match="claim-id-format"):
            ik_claim_emit(
                "bad-format-id",
                {"x": 1},
                run_state=state,
                run_dir=run_dir,
            )

    def test_invalid_format_increments_rejection_count(self, run_dir, state):
        try:
            ik_claim_emit("bad-format-id", {"x": 1}, run_state=state, run_dir=run_dir)
        except LayerAValidationError:
            pass
        assert state.rejectionCount == 1

    def test_invalid_format_zero_partial_write(self, run_dir, state):
        try:
            ik_claim_emit("bad-format-id", {"x": 1}, run_state=state, run_dir=run_dir)
        except LayerAValidationError:
            pass
        assert not index_path(run_dir).exists()

    def test_valid_format_passes(self, run_dir, state):
        """Valid claim_id passes the format guard without error."""
        ref = ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        assert ref.record_type == "claim"

    def test_etl_format_passes(self, run_dir, state):
        ref = ik_claim_emit("AB-ETL_R-001", {"x": 1}, run_state=state, run_dir=run_dir)
        assert ref.record_type == "claim"


class TestLayerAWiringClaimIdUniqueInRun:
    """check_claim_id_unique_in_run is wired into _record_emit for claim records."""

    def test_duplicate_claim_id_raises(self, run_dir, state):
        """Same claim_id twice in one run → ValidationError(rule_id='claim-id-duplicate-in-run')."""
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        with pytest.raises(LayerAValidationError, match="claim-id-duplicate-in-run"):
            ik_claim_emit("TEST-D-001", {"x": 2}, run_state=state, run_dir=run_dir)

    def test_duplicate_increments_rejection(self, run_dir, state):
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        try:
            ik_claim_emit("TEST-D-001", {"x": 2}, run_state=state, run_dir=run_dir)
        except LayerAValidationError:
            pass
        assert state.rejectionCount == 1

    def test_different_ids_both_accepted(self, run_dir, state):
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        ik_claim_emit("TEST-D-002", {"x": 2}, run_state=state, run_dir=run_dir)
        assert len(state.records) == 2


class TestLayerAWiringNonClaimRecords:
    """Non-claim records (intervention, research, skill_use) skip claim-specific guards."""

    def test_intervention_skips_claim_id_format_guard(self, run_dir, state):
        """intervention records don't carry claim_id — format guard must not fire."""
        from insight_kit.gate.emit import ik_intervention_emit

        ref = ik_intervention_emit(
            "INT-001",
            {"description": "test action"},
            run_state=state,
            run_dir=run_dir,
        )
        assert ref.record_type == "intervention"

    def test_research_skips_claim_id_guards(self, run_dir, state):
        from insight_kit.gate.emit import ik_research_emit

        ref = ik_research_emit(
            "RES-001",
            "s/r.json",
            "query",
            "source",
            timestamp="2026-05-22T00:00:00+00:00",
            run_state=state,
            run_dir=run_dir,
        )
        assert ref.record_type == "research"


class TestLayerAGuardFnDirectly:
    """Sanity-check that the guard functions in validation/ work as standalone fns.

    Ensures C13 reuse contract: gate does NOT reimplement the logic.
    """

    def test_check_claim_id_format_raises_on_bad(self):
        with pytest.raises(LayerAValidationError, match="claim-id-format"):
            check_claim_id_format("bad_format")

    def test_check_claim_id_format_passes_on_good(self):
        check_claim_id_format("TEST-D-001")  # no exception

    def test_check_claim_id_unique_raises_on_dup(self):
        with pytest.raises(LayerAValidationError, match="claim-id-duplicate-in-run"):
            check_claim_id_unique_in_run("TEST-D-001", {"TEST-D-001"})

    def test_check_claim_id_unique_passes_on_new(self):
        check_claim_id_unique_in_run("TEST-D-002", {"TEST-D-001"})  # no exception

"""T21 — intervention reconciliation gate tests (V19).

A published-tier intervention is rejected at emit unless it carries a `realized`
result whose status ∈ {applied, partial, failed}. A draft intervention may emit
with realized=None (the external action is still pending).

The reconciliation gate runs on the caller's DECLARED tier, BEFORE the T7 tier
gate — the reject is on the intent to publish. intent≠realized (partial/failed)
is recorded, never rejected: the invariant is *reconciliation captured*, not
*action succeeded*.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.gate.emit import ik_intervention_emit
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


FULL_FP_SET = {
    "data_fingerprint": "abc123",
    "code_fingerprint": "def456",
    "agent_version": "1.0.0",
    "env_fingerprint": "ghi789",
}

INTENT = {
    "description": "raise meta adset budget",
    "params": {"adset": "A1", "delta_pct": 20},
}
REALIZED_APPLIED = {"status": "applied", "details": "budget set to 120"}


def _write_run_json(run_dir: Path, extra: dict | None = None) -> None:
    """Write a run.json so a published record survives the T7 tier gate."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(extra or {}, sort_keys=True), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Draft interventions — realized optional (action may be pending)
# ---------------------------------------------------------------------------


class TestDraftInterventionAllowsPendingAction:
    def test_draft_no_realized_emits(self, run_dir, state):
        """draft intervention, action pending (realized=None) → emits (V19)."""
        ref = ik_intervention_emit("INT-001", INTENT, run_state=state, run_dir=run_dir)
        assert state.rejectionCount == 0
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "draft"
        assert rec["realized"] is None

    def test_draft_with_realized_emits(self, run_dir, state):
        """draft intervention may also carry a realized result."""
        ref = ik_intervention_emit(
            "INT-001", INTENT, realized=REALIZED_APPLIED, run_state=state, run_dir=run_dir
        )
        assert state.rejectionCount == 0
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["realized"]["status"] == "applied"


# ---------------------------------------------------------------------------
# Published interventions — realized result required
# ---------------------------------------------------------------------------


class TestPublishedInterventionRequiresReconciliation:
    def test_published_no_realized_rejected(self, run_dir, state):
        """published intervention with no realized result → reject (V19)."""
        with pytest.raises(LayerAValidationError) as exc:
            ik_intervention_emit(
                "INT-001", INTENT, tier="published", run_state=state, run_dir=run_dir
            )
        assert exc.value.rule_id == "intervention-unreconciled"

    def test_reject_is_zero_partial_write(self, run_dir, state):
        """V2 — reject increments rejectionCount, writes nothing, registers nothing."""
        with pytest.raises(LayerAValidationError):
            ik_intervention_emit(
                "INT-001", INTENT, tier="published", run_state=state, run_dir=run_dir
            )
        assert state.rejectionCount == 1
        assert len(state.records) == 0
        records_dir = run_dir / "records"
        assert not records_dir.exists() or not any(records_dir.iterdir())

    def test_published_with_applied_emits_and_stays_published(self, run_dir, state):
        """published + realized.status=applied + full fingerprint set → stays published."""
        _write_run_json(run_dir, FULL_FP_SET)
        ref = ik_intervention_emit(
            "INT-001",
            INTENT,
            realized=REALIZED_APPLIED,
            tier="published",
            run_state=state,
            run_dir=run_dir,
            input_data=b"real-upstream-input",  # → data_fingerprint_source=registered_input
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "published"
        assert rec["realized"]["status"] == "applied"
        assert state.rejectionCount == 0

    def test_published_with_partial_not_a_reject(self, run_dir, state):
        """realized.status=partial passes — intent≠realized is recorded, not rejected."""
        ref = ik_intervention_emit(
            "INT-001",
            INTENT,
            realized={"status": "partial", "details": "1 of 2 adsets updated"},
            tier="published",
            run_state=state,
            run_dir=run_dir,
        )
        assert state.rejectionCount == 0
        assert record_path(run_dir, ref.record_id).exists()

    def test_published_with_failed_not_a_reject(self, run_dir, state):
        """realized.status=failed passes — the invariant is reconciliation captured."""
        ref = ik_intervention_emit(
            "INT-001",
            INTENT,
            realized={"status": "failed", "details": "Meta API returned 500"},
            tier="published",
            run_state=state,
            run_dir=run_dir,
        )
        assert state.rejectionCount == 0
        assert record_path(run_dir, ref.record_id).exists()

    def test_intent_and_realized_round_trip(self, run_dir, state):
        """intent + realized payloads persist verbatim into record.json."""
        ref = ik_intervention_emit(
            "INT-001",
            INTENT,
            realized=REALIZED_APPLIED,
            tier="published",
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["intent"]["description"] == "raise meta adset budget"
        assert rec["intent"]["params"]["delta_pct"] == 20
        assert rec["realized"]["details"] == "budget set to 120"


# ---------------------------------------------------------------------------
# Ordering — reconciliation gate (5a) runs before the T7 tier gate (5b)
# ---------------------------------------------------------------------------


class TestReconciliationGateOrdering:
    def test_reconciliation_rejects_before_tier_downgrade(self, run_dir, state):
        """published intervention, no realized AND no run.json: the T7 tier gate
        would downgrade published->draft (which would then be legal), but the
        reconciliation gate runs FIRST and rejects on the declared published
        tier. Proves step 5a precedes step 5b."""
        # no run.json written → T7 alone would have downgraded, not rejected.
        with pytest.raises(LayerAValidationError) as exc:
            ik_intervention_emit(
                "INT-001", INTENT, tier="published", run_state=state, run_dir=run_dir
            )
        assert exc.value.rule_id == "intervention-unreconciled"


# ---------------------------------------------------------------------------
# Promotion lock — draft→published needs realized populated
# ---------------------------------------------------------------------------


class TestPromotionLock:
    def test_promotion_requires_realized(self, run_dir, state):
        """Promote a pending draft intervention to published: the new emit is
        locked out until realized is populated, then succeeds (V19)."""
        _write_run_json(run_dir, FULL_FP_SET)
        # 1. emit the pending draft (realized=None) — allowed
        draft = ik_intervention_emit("INT-001", INTENT, run_state=state, run_dir=run_dir)
        # 2. attempt promotion to published WITHOUT realized → locked out
        with pytest.raises(LayerAValidationError) as exc:
            ik_intervention_emit(
                "INT-001",
                INTENT,
                tier="published",
                supersedes=draft.record_id,
                run_state=state,
                run_dir=run_dir,
            )
        assert exc.value.rule_id == "intervention-unreconciled"
        # 3. promotion WITH realized → succeeds, stays published
        promoted = ik_intervention_emit(
            "INT-001",
            INTENT,
            realized=REALIZED_APPLIED,
            tier="published",
            supersedes=draft.record_id,
            run_state=state,
            run_dir=run_dir,
            input_data=b"real-upstream-input",
        )
        rec = json.loads(record_path(run_dir, promoted.record_id).read_text())
        assert rec["tier"] == "published"
        assert rec["supersedes"] == draft.record_id

"""Reconciliation critic (item 3b) — generalized identity check + critic emission.

check_ratio_identity generalizes check_annual_equals_monthly_sum from the additive
identity to the ratio identity (CAC == spend/new_customers, MER == revenue/ad_spend).
emit_reconciliation_critique turns the verdict into a critic-tier claim: a refutes
edge on failure (the drift class), a supports edge on success.

Cites: T11/V15 (identity), T29 (critic edges); brief §04 (deductive check that can refute).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.platform.gate import (
    RunState,
    check_ratio_identity,
    emit_reconciliation_critique,
    ik_claim_emit,
)
from insight_kit.platform.gate.store import read_record


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "run"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# pure identity check
# ---------------------------------------------------------------------------


def test_ratio_identity_holds() -> None:
    """CAC == spend / new_customers within tolerance passes."""
    r = check_ratio_identity(1000.0, 3000.0, 3.0, label="cac")
    assert r.passed
    assert r.expected == pytest.approx(1000.0)


def test_ratio_identity_drift_fails() -> None:
    """The CAC-1059-vs-1770 drift: headline disagrees with components → fails."""
    r = check_ratio_identity(1059.0, 3000.0, 3.0, label="cac")  # true = 1000
    assert not r.passed
    assert r.rel_diff > 0.01
    assert "disagrees" in r.message


def test_ratio_identity_zero_denominator_fails() -> None:
    """Undefined ratio (denominator 0, numerator != 0) always fails."""
    r = check_ratio_identity(5.0, 100.0, 0.0)
    assert not r.passed
    assert r.rel_diff == float("inf")


def test_ratio_identity_within_tolerance() -> None:
    """Small structural slack under tolerance passes (refunds/FX/timing headroom)."""
    r = check_ratio_identity(1005.0, 3000.0, 3.0, tolerance=0.01)  # 0.5% off
    assert r.passed


# ---------------------------------------------------------------------------
# critic emission
# ---------------------------------------------------------------------------


def test_failed_reconciliation_emits_refuting_critic(run_dir: Path) -> None:
    """A failed reconciliation emits a critic claim that refutes the target claim."""
    rs = RunState(run_dir=run_dir)
    target = ik_claim_emit("DEMO-D-001", {"cac_kes": (1059,)}, run_state=rs, run_dir=run_dir)

    result = check_ratio_identity(1059.0, 3000.0, 3.0, label="cac")
    critic_ref = emit_reconciliation_critique(
        result, target.record_id, "DEMO-C-001", run_state=rs, run_dir=run_dir
    )

    rec = read_record(run_dir, critic_ref.record_id)
    assert rec["tier"] == "critic"
    assert target.record_id in rec["refutes"]
    assert target.record_id not in rec.get("supports", [])
    assert rec["fields"]["passed"]["value"] is False


def test_passed_reconciliation_emits_supporting_critic(run_dir: Path) -> None:
    """A passed reconciliation emits a critic claim that supports the target claim."""
    rs = RunState(run_dir=run_dir)
    target = ik_claim_emit("DEMO-D-002", {"cac_kes": (1000,)}, run_state=rs, run_dir=run_dir)

    result = check_ratio_identity(1000.0, 3000.0, 3.0, label="cac")
    critic_ref = emit_reconciliation_critique(
        result, target.record_id, "DEMO-C-002", run_state=rs, run_dir=run_dir
    )

    rec = read_record(run_dir, critic_ref.record_id)
    assert rec["tier"] == "critic"
    assert target.record_id in rec["supports"]
    assert rec["fields"]["passed"]["value"] is True

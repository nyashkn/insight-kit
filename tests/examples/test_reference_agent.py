"""The growth-demo reference agent: the read-history -> diff -> report loop.

Pins the behavior the cross-run substrate exists to enable — a memoryless
agent reconstructing context from sealed runs: drift read back from history,
and the persistent guard catching a refuted claim republished a run later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

HAS_HAMILTON = False
try:
    from hamilton import driver  # noqa: F401

    HAS_HAMILTON = True
except ImportError:
    pass

requires_hamilton = pytest.mark.skipif(not HAS_HAMILTON, reason="Hamilton not installed")


@requires_hamilton
def test_reference_loop_reports_drift_and_catches_republish(tmp_path: Path) -> None:
    from insight_kit.examples.growth_demo import datagen
    from insight_kit.examples.growth_demo.reference_agent import (
        _NAIVE_CAC,
        _TRUE_CAC,
        run_reference_loop,
    )

    report = run_reference_loop(tmp_path)

    # Two pulse days sealed, in order.
    assert [r.run_id for r in report.runs] == ["pulse-2026-01-30", "pulse-2026-02-14"]
    day1, day2 = report.runs
    assert (day1.days, day2.days) == (30, 45)

    # Each day's blended CAC equals that window's by-construction ground truth.
    assert day1.blended_cac == pytest.approx(
        datagen.generate(seed=42, days=30).ground_truth["cac_kes"]
    )
    assert day2.blended_cac == pytest.approx(
        datagen.generate(seed=42, days=45).ground_truth["cac_kes"]
    )

    # Drift is read back from sealed history and is non-trivial (window advanced).
    assert report.blended_cac_drift == pytest.approx(day2.blended_cac - day1.blended_cac)
    assert report.blended_cac_drift != pytest.approx(0.0)

    # The P5-trap naive CAC is refuted on BOTH days by the reconciliation critic.
    assert day1.naive_refuted and day2.naive_refuted

    # Day 1 has no prior sealed run, so the guard finds nothing; day 2's guard
    # catches the naive claim republished after its day-1 refutation.
    assert day1.guard_findings == []
    assert report.republished_refuted == [_NAIVE_CAC]
    finding = next(f for f in day2.guard_findings if f.claim_id == _NAIVE_CAC)
    assert finding.prior_run_id == "pulse-2026-01-30"
    assert finding.critic_record_id is not None

    # The true CAC (DEMO-D-010) shares all upstream sources with the naive one
    # yet is NOT flagged — the guard is precise, not a blanket block.
    assert _TRUE_CAC not in report.republished_refuted


@requires_hamilton
def test_reference_loop_is_reproducible_with_fixed_timestamp(tmp_path: Path) -> None:
    from insight_kit.examples.growth_demo.reference_agent import run_reference_loop

    ts = "2026-03-31T00:00:00+00:00"
    a = run_reference_loop(tmp_path / "a", emit_timestamp=ts)
    b = run_reference_loop(tmp_path / "b", emit_timestamp=ts)

    assert [r.blended_cac for r in a.runs] == [r.blended_cac for r in b.runs]
    assert a.blended_cac_drift == b.blended_cac_drift
    assert a.republished_refuted == b.republished_refuted

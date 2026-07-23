"""Layered metrics: a Layer-2 claim derived from upstream claims (issue #6 nugget).

The growth-demo DAG's base metrics (blended_cac, arpu, ...) are a flat layer
computed from data rows. ``cac_payback_ratio`` sits a layer above: its inputs
are the *values* of two upstream claim nodes, not raw rows. This pins the edge
that a flat DAG cannot express —

  * a derived metric has no live input rows, so it lands as payload provenance
    (it can't earn a row fingerprint), yet
  * it is not orphaned: the adapter records the two upstream claims it was
    computed from as ``input_claims`` (claim->claim data lineage), so the number
    still traces back to what produced it.

Contrast is the point: the Layer-1 claim it cites (arpu) carries registered_input
provenance from its own rows; the Layer-2 claim carries claim->claim edges.

Cites: T29 (input_claims data lineage), item 7 (lineage), issue #6.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.platform.gate import RunState
from insight_kit.platform.gate.store import read_record

HAS_HAMILTON = False
try:
    from hamilton import driver  # noqa: F401

    HAS_HAMILTON = True
except ImportError:
    pass

requires_hamilton = pytest.mark.skipif(not HAS_HAMILTON, reason="Hamilton not installed")

_ARPU = "DEMO-D-013"
_BLENDED_CAC = "DEMO-D-010"
_PAYBACK = "DEMO-D-020"


def _run(run_dir: Path, final_vars: list[str]):
    """Execute the growth-demo DAG through the gate-backed driver."""
    from insight_kit.examples.growth_demo import dag, datagen
    from insight_kit.integrations.hamilton import build_driver

    demo = datagen.generate(seed=42, days=45)
    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [dag])
    out = dr.execute(
        final_vars,
        inputs={
            "meta_ads_raw": demo.meta_ads,
            "google_ads_raw": demo.google_ads,
            "orders_raw": demo.orders,
        },
    )
    return demo, rs, out


def _claim_by_id(rs: RunState, run_dir: Path, claim_id: str) -> tuple[str, dict]:
    """(record_id, record dict) for the claim with the given gate claim_id."""
    for ref in rs.records:
        if ref.record_type != "claim":
            continue
        rec = read_record(run_dir, ref.record_id)
        if rec.get("claim_id") == claim_id:
            return ref.record_id, rec
    raise AssertionError(f"no claim {claim_id} in run state")


@requires_hamilton
def test_layer2_metric_records_upstream_claims_as_input_claims(tmp_path: Path) -> None:
    """The derived metric cites the two claims it was computed from, via input_claims."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # Ask for the Layer-2 metric only; Hamilton pulls arpu + blended_cac transitively,
    # and the hook emits a claim for each as they execute.
    demo, rs, out = _run(run_dir, ["cac_payback_ratio"])

    arpu_rid, _ = _claim_by_id(rs, run_dir, _ARPU)
    cac_rid, _ = _claim_by_id(rs, run_dir, _BLENDED_CAC)
    _, payback = _claim_by_id(rs, run_dir, _PAYBACK)

    # 1. claim->claim data lineage: the derived metric points at BOTH upstream
    #    claims' record_ids — and the edge lives on input_claims, not cites
    #    (cites is knowledge-provenance only; the gate rejects a claim in cites).
    assert set(payback["input_claims"]) == {arpu_rid, cac_rid}
    assert payback["cites"] == []  # no research/skill_use knowledge chain

    # 2. it earned NO row fingerprint — a derived metric has no live input rows,
    #    so payload provenance is correct here (its backing is the input_claims).
    assert payback["data_fingerprint_source"] == "payload"

    # 3. by contrast, the Layer-1 claim it derives from DID fingerprint its rows.
    _, arpu_rec = _claim_by_id(rs, run_dir, _ARPU)
    assert arpu_rec["data_fingerprint_source"] == "registered_input"
    assert arpu_rec["input_claims"] == []  # a base metric derives from data, not claims

    # 4. the number itself is the by-construction ground-truth identity:
    #    payback = ARPU / CAC = (revenue / new_customers) / cac.
    gt = demo.ground_truth
    expected_arpu = gt["revenue_kes"] / gt["new_customers"]
    assert out["cac_payback_ratio"] == pytest.approx(expected_arpu / gt["cac_kes"])


@requires_hamilton
def test_layer1_siblings_have_no_input_claims(tmp_path: Path) -> None:
    """A flat metric derives from data, so it declares no claim->claim edges.

    Guards against the adapter over-attaching input_claims: blended_cac's kwargs
    are transform tables (ad_spend_unified, new_customer_orders), not claims, so
    nothing should be recorded as an upstream claim.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _, rs, _ = _run(run_dir, ["blended_cac"])
    _, rec = _claim_by_id(rs, run_dir, _BLENDED_CAC)
    assert rec["input_claims"] == []
    assert rec["data_fingerprint_source"] == "registered_input"

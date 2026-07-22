"""Item 7 — deterministic DAG lineage, groundtruthed on the growth-funnel fixture.

Covers the full loop the enhancement is for:
  * the compiled graph's upstream closure is stamped onto every metric claim;
  * lineage_of / trace_to_rows answer "where did this number come from" from
    the sealed run bundle alone (no hamilton import, no re-execution);
  * the DAG's metrics match the fixture's ground truth EXACTLY (the fixture
    computes truth from the rows it generated — groundtruthing, not eyeballing);
  * the planted P5 trap (naive_cac counting returning customers) drifts from
    truth and is refuted by the reconciliation critic — fixture, lineage, and
    critic exercised together.

Cites: item 7 (brief §07), V15/V22/T7, T29 (critic edges).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.platform.gate import (
    LineageNotRecordedError,
    RunState,
    check_ratio_identity,
    emit_reconciliation_critique,
    ik_claim_emit,
    lineage_of,
    trace_to_rows,
)
from insight_kit.platform.gate.store import read_record

HAS_HAMILTON = False
try:
    from hamilton import driver  # noqa: F401

    HAS_HAMILTON = True
except ImportError:
    pass

requires_hamilton = pytest.mark.skipif(not HAS_HAMILTON, reason="Hamilton not installed")


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "run"
    d.mkdir()
    return d


def _run_demo(run_dir: Path, final_vars: list[str]):
    """Execute the growth-funnel DAG through the gate-backed driver."""
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


# ---------------------------------------------------------------------------
# lineage stamped on the claim
# ---------------------------------------------------------------------------


@requires_hamilton
def test_metric_claim_carries_upstream_closure(run_dir: Path) -> None:
    """The claim's lineage field holds the node's full transitive closure."""
    _, rs, _ = _run_demo(run_dir, ["blended_cac"])
    _, rec = _claim_by_id(rs, run_dir, "DEMO-D-010")

    lineage = rec["fields"]["lineage"]["value"]
    assert lineage["node"] == "blended_cac"
    assert sorted(lineage["direct_upstream"]) == ["ad_spend_unified", "new_customer_orders"]
    # closure reaches through the intermediates back to the raw sources
    assert set(lineage["upstream_closure"]) == {
        "ad_spend_unified",
        "new_customer_orders",
        "orders_clean",
        "meta_ads_raw",
        "google_ads_raw",
        "orders_raw",
    }
    assert sorted(lineage["external_inputs"]) == ["google_ads_raw", "meta_ads_raw", "orders_raw"]


@requires_hamilton
def test_lineage_of_traces_claim_to_rows(run_dir: Path) -> None:
    """lineage_of reads the sealed bundle: graph position + the exact input rows."""
    demo, rs, _ = _run_demo(run_dir, ["blended_cac"])
    record_id, rec = _claim_by_id(rs, run_dir, "DEMO-D-010")

    trace = lineage_of(run_dir, record_id)
    assert trace.claim_id == "DEMO-D-010"
    assert trace.node == "blended_cac"
    assert trace.depends_on("meta_ads_raw") and trace.depends_on("orders_raw")
    assert not trace.depends_on("blended_cac")  # a node is not its own upstream
    assert trace.data_fingerprint_source == "registered_input"
    assert trace.extraction_record_id in rec["cites"]

    # the captured rows ARE the metric node's direct inputs — count-exact
    assert trace.input_rows is not None
    new_customer_rows = trace.input_rows["new_customer_orders"]
    assert len(new_customer_rows["order_id"]) == int(demo.ground_truth["new_customers"])
    assert trace_to_rows(run_dir, record_id) == trace.input_rows


def test_lineage_of_refuses_to_guess(run_dir: Path) -> None:
    """A claim emitted outside a driver run has no lineage — that's an error, not a reconstruction."""
    rs = RunState(run_dir=run_dir)
    ref = ik_claim_emit("DEMO-D-900", {"x": (1,)}, run_state=rs, run_dir=run_dir)
    with pytest.raises(LineageNotRecordedError):
        lineage_of(run_dir, ref.record_id)


# ---------------------------------------------------------------------------
# groundtruthing: DAG output vs the fixture's known answers
# ---------------------------------------------------------------------------


@requires_hamilton
def test_dag_matches_ground_truth_exactly(run_dir: Path) -> None:
    """Metrics computed through the gate equal the generator's by-construction truth."""
    demo, _, out = _run_demo(run_dir, ["blended_cac", "demo_mer", "naive_cac"])
    gt = demo.ground_truth
    assert out["blended_cac"] == pytest.approx(gt["cac_kes"])
    assert out["demo_mer"] == pytest.approx(gt["mer"])
    assert out["naive_cac"] == pytest.approx(gt["naive_cac_kes"])


@requires_hamilton
def test_naive_cac_trap_is_refuted_by_reconciliation_critic(run_dir: Path) -> None:
    """The planted P5 trap end to end: naive claim emitted, identity fails, critic refutes.

    The true claim (blended_cac) passes the same identity and gets a supports
    edge — the critic separates the two claims, it doesn't blanket-block.
    """
    demo, rs, out = _run_demo(run_dir, ["blended_cac", "naive_cac"])
    gt = demo.ground_truth

    naive_id, _ = _claim_by_id(rs, run_dir, "DEMO-D-012")
    true_id, _ = _claim_by_id(rs, run_dir, "DEMO-D-010")

    # identity: CAC == spend / new customers (component truth from the fixture)
    naive_check = check_ratio_identity(
        out["naive_cac"], gt["total_spend_kes"], gt["new_customers"], label="cac"
    )
    true_check = check_ratio_identity(
        out["blended_cac"], gt["total_spend_kes"], gt["new_customers"], label="cac"
    )
    assert not naive_check.passed and true_check.passed

    naive_critic = emit_reconciliation_critique(
        naive_check, naive_id, "DEMO-C-012", run_state=rs, run_dir=run_dir
    )
    true_critic = emit_reconciliation_critique(
        true_check, true_id, "DEMO-C-010", run_state=rs, run_dir=run_dir
    )

    assert naive_id in read_record(run_dir, naive_critic.record_id)["refutes"]
    assert true_id in read_record(run_dir, true_critic.record_id)["supports"]

    # and lineage tells us WHERE the trap is: both claims share the same
    # upstream sources — the drift is in the node's own selection, not the data.
    naive_trace = lineage_of(run_dir, naive_id)
    true_trace = lineage_of(run_dir, true_id)
    assert set(naive_trace.external_inputs) == set(true_trace.external_inputs)
    assert "new_customer_orders" in true_trace.upstream_closure
    assert "new_customer_orders" not in naive_trace.upstream_closure  # skipped the filter


# ---------------------------------------------------------------------------
# lineage snapshot rides the extraction record too
# ---------------------------------------------------------------------------


@requires_hamilton
def test_extraction_snapshot_pairs_rows_with_lineage(run_dir: Path) -> None:
    import json

    from insight_kit.platform.gate.store import snapshot_path

    _, rs, _ = _run_demo(run_dir, ["blended_cac"])
    record_id, _ = _claim_by_id(rs, run_dir, "DEMO-D-010")
    trace = lineage_of(run_dir, record_id)

    snap = json.loads(snapshot_path(run_dir, trace.extraction_record_id).read_text())
    assert set(snap["input_rows"]) == {"ad_spend_unified", "new_customer_orders"}
    assert snap["lineage"]["node"] == "blended_cac"


# ---------------------------------------------------------------------------
# review-confirmed defects (workflow wf_c45dc178): regression coverage
# ---------------------------------------------------------------------------


@requires_hamilton
def test_override_truncates_lineage_and_is_declared(run_dir: Path) -> None:
    """HIGH: an execute-time override must truncate the closure and be declared.

    Before the fix, a claim computed from a forged override table still stamped
    the full static closure back to the real raw sources — provenance pointing
    at data that was never read.
    """
    import pyarrow as pa

    from insight_kit.examples.growth_demo import dag, datagen
    from insight_kit.integrations.hamilton import build_driver

    demo = datagen.generate(seed=42, days=45)
    forged_spend = pa.table(
        {"day": ["2026-01-01"], "channel": ["meta"], "campaign": ["x"], "spend_kes": [999999.0]}
    )
    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [dag])
    dr.execute(
        ["blended_cac"],
        inputs={"orders_raw": demo.orders},
        overrides={"ad_spend_unified": forged_spend},
    )

    record_id, _ = _claim_by_id(rs, run_dir, "DEMO-D-010")
    trace = lineage_of(run_dir, record_id)

    # override is declared, and the bypassed sources are NOT asserted
    assert trace.overridden == ["ad_spend_unified"]
    assert trace.is_overridden
    assert not trace.depends_on("meta_ads_raw")
    assert not trace.depends_on("google_ads_raw")
    assert "meta_ads_raw" not in trace.external_inputs
    # the orders path was genuinely computed, so it IS still asserted
    assert trace.depends_on("orders_raw")


@requires_hamilton
def test_scalar_only_metric_cannot_register_input(run_dir: Path) -> None:
    """HIGH: a metric node fed bare literals must land as payload and be downgraded.

    Before the fix, scalar kwargs alone produced a registered_input claim — a
    hardcoded number laundered into publishable provenance (P1 bypass).
    """
    import sys
    import types

    from hamilton.function_modifiers import tag

    from insight_kit.integrations.hamilton import build_driver

    @tag(ik_emit="metric", ik_tier="published", ik_claim_id="DEMO-D-500", ik_metric="scalar_cac")
    def scalar_cac(spend: float, customers: float) -> float:
        return spend / customers

    mod = types.ModuleType("scalar_metric_mod")
    scalar_cac.__module__ = mod.__name__
    mod.scalar_cac = scalar_cac
    sys.modules[mod.__name__] = mod  # hamilton resolves node functions via sys.modules
    try:
        rs = RunState(run_dir=run_dir)
        dr = build_driver(rs, run_dir, [mod])
        dr.execute(["scalar_cac"], inputs={"spend": 3000.0, "customers": 3.0})
    finally:
        del sys.modules[mod.__name__]

    _record_id, rec = _claim_by_id(rs, run_dir, "DEMO-D-500")
    assert rec["data_fingerprint_source"] == "payload"
    assert rec["tier"] == "draft"  # tier gate downgraded the published ask
    # no provenance chain was faked for it either
    assert not [r for r in rs.records if r.record_type == "skill_use"]


@requires_hamilton
def test_statement_tag_lands_on_claim(run_dir: Path) -> None:
    """MEDIUM: ik_statement must reach the sealed bundle, not be silently dropped."""
    _, rs, _ = _run_demo(run_dir, ["naive_cac"])
    _, rec = _claim_by_id(rs, run_dir, "DEMO-D-012")
    assert "P5 trap" in rec["fields"]["statement"]["value"]


@requires_hamilton
def test_second_execute_skips_cleanly_no_orphans(run_dir: Path) -> None:
    """MEDIUM: re-executing one driver/RunState must not orphan provenance records.

    Before the fix, the second execute emitted a fresh skill_use record and then
    had its claim rejected as a duplicate — a half-written bundle, silently.
    """
    from insight_kit.examples.growth_demo import dag, datagen
    from insight_kit.integrations.hamilton import build_driver

    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [dag])
    for seed in (42, 43):  # different data second time — still must be skipped
        demo = datagen.generate(seed=seed, days=20)
        dr.execute(
            ["blended_cac"],
            inputs={
                "meta_ads_raw": demo.meta_ads,
                "google_ads_raw": demo.google_ads,
                "orders_raw": demo.orders,
            },
        )

    kinds = sorted(r.record_type for r in rs.records)
    assert kinds == ["claim", "skill_use"]  # exactly one chain, no orphans


@requires_hamilton
def test_emit_timestamp_makes_record_ids_reproducible(tmp_path: Path) -> None:
    """MEDIUM (pre-existing): fixed emit_timestamp -> identical record ids across runs."""
    from insight_kit.examples.growth_demo import dag, datagen
    from insight_kit.integrations.hamilton import build_driver

    ts = "2026-03-31T00:00:00+00:00"
    ids: list[set[str]] = []
    for name in ("a", "b"):
        run_dir = tmp_path / name
        run_dir.mkdir()
        demo = datagen.generate(seed=42, days=20)
        rs = RunState(run_dir=run_dir)
        dr = build_driver(rs, run_dir, [dag], emit_timestamp=ts)
        dr.execute(
            ["blended_cac"],
            inputs={
                "meta_ads_raw": demo.meta_ads,
                "google_ads_raw": demo.google_ads,
                "orders_raw": demo.orders,
            },
        )
        ids.append({r.record_id for r in rs.records})

    assert ids[0] == ids[1]  # content-addressing now holds across runs

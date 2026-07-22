"""Reference-metric (CAC) + grind-replay tests for the hardened Hamilton path.

These exercise the ``ik_emit="metric"`` path on ``InsightKitHook`` end to end and
replay documented failures from the PPC-attribution grind against the gate:

  * P1 "verdict-from-proxy" — a CAC that was not computed from live rows (a
    hardcoded literal / a value read off transform code) has no registered input,
    lands as data_fingerprint_source=payload, and is downgraded from published to
    draft. A CAC computed from live rows is registered_input.
  * Selection trap — the "new customer" filter (customer_order_index==1) that
    drove the documented CAC drift is recorded as an explicit gate selection (V15),
    never left implicit.
  * Defect guard — the generated claim_id satisfies the gate id grammar (the
    legacy _gen_claim_id produced ids the gate rejects).

Cites: V15, V22, T7; brief §08.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa  # core dependency — always available
import pytest

from insight_kit.libs.validation import CLAIM_ID_REGEX
from insight_kit.platform.gate import RunState, ik_claim_emit
from insight_kit.platform.gate.store import read_record

# Hamilton is an optional extra; the driver/adapter tests skip without it, but the
# pure-gate grind-replay below needs only the gate + pyarrow, so it runs in CI.
HAS_HAMILTON = False
try:
    from hamilton import driver  # noqa: F401
    from hamilton.function_modifiers import tag  # noqa: F401

    HAS_HAMILTON = True
except ImportError:
    pass

requires_hamilton = pytest.mark.skipif(not HAS_HAMILTON, reason="Hamilton not installed")


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "run"
    d.mkdir()
    return d


def _orders() -> pa.Table:
    # c1,c2,c3 are new (first order, index==1); c1's 2nd order and c4 are returning.
    return pa.table(
        {
            "customer_id": ["c1", "c2", "c3", "c1", "c4"],
            "customer_order_index": [1, 1, 1, 2, 2],
            "order_date": ["2026-03-02", "2026-03-08", "2026-03-19", "2026-03-25", "2026-03-27"],
        }
    )


def _spend() -> pa.Table:
    # total 3000 KES over the window
    return pa.table({"day": ["2026-03-05", "2026-03-15", "2026-03-25"], "spend_kes": [1000, 1500, 500]})


# ---------------------------------------------------------------------------
# claim-id grammar (defect guard)
# ---------------------------------------------------------------------------


@requires_hamilton
def test_generated_metric_claim_id_matches_gate_grammar() -> None:
    """A generated metric claim_id satisfies CLAIM_ID_REGEX (the legacy path did not)."""
    from insight_kit.integrations.hamilton.adapter import InsightKitHook

    cid = InsightKitHook._gen_metric_claim_id("DEMO", "D", "cac_march")
    assert CLAIM_ID_REGEX.match(cid), cid
    # namespace shorter than 2 letters falls back to IK; ETL tier token is valid.
    assert CLAIM_ID_REGEX.match(InsightKitHook._gen_metric_claim_id("", "ETL_M", "spend_curated"))
    # explicit id passes through unchanged.
    assert InsightKitHook._gen_metric_claim_id("DEMO", "D", "n", explicit="DEMO-D-001") == "DEMO-D-001"


# ---------------------------------------------------------------------------
# CAC end to end through the gate
# ---------------------------------------------------------------------------


def _find_claim(rs: RunState):
    """Return (claim_ref, [skill_use_refs]) from a RunState after a metric emit."""
    claim = next(r for r in rs.records if r.record_type == "claim")
    skill_uses = [r for r in rs.records if r.record_type == "skill_use"]
    return claim, skill_uses


@requires_hamilton
def test_cac_metric_emits_registered_input_claim(run_dir: Path) -> None:
    """E2E: cac_march computes CAC and the hook emits a registered_input claim."""
    from insight_kit.examples import cac_metric
    from insight_kit.integrations.hamilton import build_driver

    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [cac_metric])
    out = dr.execute(["cac_march"], inputs={"orders_rows": _orders(), "spend_rows": _spend()})

    assert out["cac_march"] == pytest.approx(1000.0)  # 3000 KES / 3 new customers

    claim_ref, _ = _find_claim(rs)
    rec = read_record(run_dir, claim_ref.record_id)

    # valid id, asserted value carried as a field, and provenance is over live rows
    assert rec["claim_id"] == "DEMO-D-001"
    assert CLAIM_ID_REGEX.match(rec["claim_id"])
    assert rec["fields"]["cac_kes"]["value"] == pytest.approx(1000.0)
    assert rec["fields"]["cac_kes"]["fmt_hint"] == ",.0f"
    assert rec["data_fingerprint_source"] == "registered_input"


@requires_hamilton
def test_cac_metric_emits_skill_use_chain(run_dir: Path) -> None:
    """Item 1: the claim cites a real skill_use record capturing the input rows."""
    from insight_kit.examples import cac_metric
    from insight_kit.integrations.hamilton import build_driver

    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [cac_metric])
    dr.execute(["cac_march"], inputs={"orders_rows": _orders(), "spend_rows": _spend()})

    claim_ref, skill_uses = _find_claim(rs)
    assert len(skill_uses) == 1  # the extraction record
    su = read_record(run_dir, skill_uses[0].record_id)
    assert su["tool"] == "hamilton"
    assert "spend_rows" in su["source"]  # the upstream inputs are named as the source

    claim = read_record(run_dir, claim_ref.record_id)
    # the claim cites the skill_use record — provenance is a chain, not just a fingerprint
    assert skill_uses[0].record_id in claim["cites"]


@requires_hamilton
def test_cac_selection_filter_recorded(run_dir: Path) -> None:
    """The 'new customer' filter (P3 trap) is an explicit gate selection, not implicit prose."""
    from insight_kit.examples import cac_metric
    from insight_kit.integrations.hamilton import build_driver

    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [cac_metric])
    dr.execute(["cac_march"], inputs={"orders_rows": _orders(), "spend_rows": _spend()})

    claim_ref, _ = _find_claim(rs)
    rec = read_record(run_dir, claim_ref.record_id)
    sel = rec["selection"]
    assert sel["grain"] == "month"
    assert sel["date_window"] == "2026-03-01/2026-03-31"
    assert sel["filters"] == {"customer_order_index": "1"}


@requires_hamilton
def test_metric_path_is_generic_mer(run_dir: Path) -> None:
    """Genericity proof: a different metric (MER, a ratio) uses the SAME adapter.

    MER omits ik_claim_id, so the adapter's id generator runs end to end. No engine
    change distinguishes MER from CAC — only the tags and the formula differ.
    """
    from insight_kit.examples import mer_metric
    from insight_kit.integrations.hamilton import build_driver

    revenue = pa.table({"day": ["2026-03-10", "2026-03-20"], "revenue_kes": [8000, 4000]})
    spend = pa.table({"day": ["2026-03-10", "2026-03-20"], "spend_kes": [2000, 2000]})

    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [mer_metric])
    out = dr.execute(["mer_march"], inputs={"revenue_rows": revenue, "spend_rows": spend})

    assert out["mer_march"] == pytest.approx(3.0)  # 12000 / 4000

    claim_ref, skill_uses = _find_claim(rs)
    rec = read_record(run_dir, claim_ref.record_id)
    assert CLAIM_ID_REGEX.match(rec["claim_id"])  # generated id is gate-valid
    assert rec["fields"]["mer"]["value"] == pytest.approx(3.0)
    assert rec["fields"]["mer"]["fmt_hint"] == ".2f"
    assert rec["data_fingerprint_source"] == "registered_input"
    assert len(skill_uses) == 1 and skill_uses[0].record_id in rec["cites"]


# ---------------------------------------------------------------------------
# Grind replay — P1 verdict-from-proxy
# ---------------------------------------------------------------------------


def test_hardcoded_cac_cannot_publish(run_dir: Path) -> None:
    """P1 replay: a CAC with no live-row provenance is downgraded from published to draft.

    This is the automated form of the CAC-1059-vs-1770 drift: a number issued
    from a proxy (a hardcoded literal, a value read off transform code) carries
    no registered input. The gate downgrades the published claim to draft and
    records the reason. The same number computed from live rows is registered.
    """
    rs = RunState(run_dir=run_dir)

    # proxy: no input_data → payload provenance → cannot hold 'published'
    ik_claim_emit(
        "DEMO-D-001",
        {"cac_kes": (1059, ",.0f")},
        tier="published",
        run_state=rs,
        run_dir=run_dir,
    )
    proxy = read_record(run_dir, rs.records[0].record_id)
    assert proxy["data_fingerprint_source"] == "payload"
    assert proxy["tier"] == "draft"  # downgraded, not published
    assert "payload" in proxy.get("tier_downgrade_reason", "")

    # live rows: registered_input provenance (the fix)
    rs2 = RunState(run_dir=run_dir)
    ik_claim_emit(
        "DEMO-D-002",
        {"cac_kes": (1770, ",.0f")},
        tier="published",
        run_state=rs2,
        run_dir=run_dir,
        input_data={"orders": _orders().to_pydict(), "spend": _spend().to_pydict()},
    )
    live = read_record(run_dir, rs2.records[0].record_id)
    assert live["data_fingerprint_source"] == "registered_input"

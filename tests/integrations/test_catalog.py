"""Measure catalog: the discoverable semantic layer an agent reads before composing.

Built statically from @tag metadata + the compiled graph (no execution, no data).
Pins that it distinguishes base from derived measures, advertises the exact
claim_id the adapter will emit, and surfaces the claim->claim edges (derives_from)
a derived measure will carry as input_claims.

Cites: T29 (input_claims), item 7 (lineage), issue #6.
"""

from __future__ import annotations

import pytest

HAS_HAMILTON = False
try:
    from hamilton import driver  # noqa: F401

    HAS_HAMILTON = True
except ImportError:
    pass

requires_hamilton = pytest.mark.skipif(not HAS_HAMILTON, reason="Hamilton not installed")


@requires_hamilton
def test_catalog_lists_all_measures_with_ids_and_grain() -> None:
    from insight_kit.examples.growth_demo import dag
    from insight_kit.integrations.hamilton import catalog

    cat = catalog([dag])

    assert cat.names() == ("arpu", "blended_cac", "cac_payback_ratio", "demo_mer", "naive_cac")

    cac = cat.by_name("blended_cac")
    assert cac is not None
    assert cac.claim_id == "DEMO-D-010"
    assert cac.metric_field == "blended_cac_kes"
    assert cac.grain == "window"
    assert cac.statement and "Blended CAC" in cac.statement

    # raw datasets are surfaced separately from measures
    assert cat.inputs == ("google_ads_raw", "meta_ads_raw", "orders_raw")


@requires_hamilton
def test_catalog_flags_derived_measure_and_its_claim_edges() -> None:
    from insight_kit.examples.growth_demo import dag
    from insight_kit.integrations.hamilton import catalog

    cat = catalog([dag])

    # The Layer-2 measure is flagged derived, and its derives_from names exactly
    # the upstream measures it will cite as input_claims at emit.
    payback = cat.by_name("cac_payback_ratio")
    assert payback is not None
    assert payback.kind == "derived"
    assert payback.derives_from == ("arpu", "blended_cac")

    # Flat base measures derive from data, so they name no upstream measures.
    for name in ("arpu", "blended_cac", "demo_mer", "naive_cac"):
        m = cat.by_name(name)
        assert m is not None and m.kind == "base" and m.derives_from == ()

    assert {m.measure for m in cat.base()} == {"arpu", "blended_cac", "demo_mer", "naive_cac"}
    assert {m.measure for m in cat.derived()} == {"cac_payback_ratio"}


@requires_hamilton
def test_catalog_claim_ids_match_what_the_adapter_emits(tmp_path) -> None:
    """The id the catalog advertises is the id a run actually emits — no drift."""
    from insight_kit.examples.growth_demo import dag, datagen
    from insight_kit.integrations.hamilton import build_driver, catalog
    from insight_kit.platform.gate import RunState
    from insight_kit.platform.gate.store import read_record

    cat = catalog([dag])
    catalog_ids = {m.measure: m.claim_id for m in cat.measures}

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    demo = datagen.generate(seed=42, days=30)
    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [dag])
    dr.execute(
        ["cac_payback_ratio"],
        inputs={
            "meta_ads_raw": demo.meta_ads,
            "google_ads_raw": demo.google_ads,
            "orders_raw": demo.orders,
        },
    )

    emitted = {
        read_record(run_dir, ref.record_id)["fields"]["node_id"]["value"]: read_record(
            run_dir, ref.record_id
        )["claim_id"]
        for ref in rs.records
        if ref.record_type == "claim"
    }
    for measure, claim_id in emitted.items():
        assert catalog_ids[measure] == claim_id


@requires_hamilton
def test_format_catalog_is_readable() -> None:
    from insight_kit.examples.growth_demo import dag
    from insight_kit.integrations.hamilton import catalog, format_catalog

    text = format_catalog(catalog([dag]))
    assert "cac_payback_ratio" in text
    assert "DEMO-D-010" in text
    assert "derived <- arpu, blended_cac" in text

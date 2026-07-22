"""Second reference metric: MER — proof that the metric-emit path is generic.

This module exists to demonstrate — with a passing test rather than an assertion
— that the ``ik_emit="metric"`` path in ``InsightKitHook`` is not CAC-specific.
It computes a structurally different metric (a ratio, MER = revenue / ad spend)
and deliberately omits ``ik_claim_id`` so the adapter's id generator runs end to
end. The adapter is used unchanged: no engine edit distinguishes MER from CAC.

    MER (Marketing Efficiency Ratio) = revenue / ad spend

Like ``cac_metric``, the two leaf tables are ``inputs=`` here for a hermetic test;
in production they are ``@load_from`` nodes over the DuckDB catalog.

Cites: genericity proof for the metric-emit path (brief §01, "one definition surface").
"""
from __future__ import annotations

import pyarrow as pa
from hamilton.function_modifiers import tag


@tag(
    ik_emit="metric",
    ik_namespace="DEMO",
    ik_id_tier="D",
    # NOTE: no ik_claim_id — the adapter generates a gate-valid id from the
    # namespace + tier + node name, proving that path works end to end too.
    ik_metric="mer",
    ik_fmt=".2f",
    ik_grain="month",
    ik_date_window="2026-03-01/2026-03-31",
    ik_statement="March 2026 marketing efficiency ratio = revenue / ad spend",
)
def mer_march(revenue_rows: pa.Table, spend_rows: pa.Table) -> float:
    """MER for the March window: total revenue ÷ total ad spend.

    Derived directly from the two row tables, so the gate fingerprints those
    rows as the claim's registered input — identical provenance mechanics to
    CAC, a different formula.
    """
    spend = float(sum(spend_rows.column("spend_kes").to_pylist()))
    if spend == 0:
        raise ValueError("ad spend is zero — MER denominator is zero")
    revenue = float(sum(revenue_rows.column("revenue_kes").to_pylist()))
    return revenue / spend

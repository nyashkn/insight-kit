"""growth demo DAG — multi-layer Hamilton module over the seeded testbed.

Layered so lineage (item 7) is non-trivial: raw inputs -> unified/cleaned
intermediates -> metric nodes. The metric nodes' direct kwargs are the
intermediate Arrow tables, so every claim gets registered-input provenance
over the exact rows the number was computed from, and its stamped lineage
closure reaches back to the raw sources.

    meta_ads_raw ─┐
                  ├─ ad_spend_unified ─┬─ blended_cac   (true CAC, DEMO-D-010)
    google_ads_raw┘                    ├─ demo_mer      (MER,      DEMO-D-011)
                                       └─ naive_cac     (P5 trap,  DEMO-D-012)
    orders_raw ── orders_clean ─┬─ new_customer_orders ─ blended_cac
                                ├─ demo_mer
                                └─ naive_cac

``naive_cac`` is a deliberate replay of the documented CAC drift: it divides
spend by DISTINCT customers seen in the window (returning customers included)
instead of first orders. It is kept in the DAG on purpose — the fixture's
ground truth knows both answers, so the reconciliation critic can refute it.

The metrics above are a flat layer computed from data. ``cac_payback_ratio``
adds a second layer — a metric whose inputs are the *values of two upstream
claims* (``arpu`` and ``blended_cac``), not raw rows::

    arpu         (DEMO-D-013) ─┐
                               ├─ cac_payback_ratio  (Layer 2, DEMO-D-020)
    blended_cac  (DEMO-D-010) ─┘

A Layer-2 metric has no live input rows of its own, so the adapter backs it
with claim->claim data lineage (``input_claims``) instead of a row fingerprint —
the provenance a derived number carries in place of extracted rows.
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc
from hamilton.function_modifiers import tag


def ad_spend_unified(meta_ads_raw: pa.Table, google_ads_raw: pa.Table) -> pa.Table:
    """Union Meta + Google spend into one (day, channel, campaign, spend_kes) table."""
    parts = []
    for channel, table in (("meta", meta_ads_raw), ("google", google_ads_raw)):
        parts.append(
            pa.table(
                {
                    "day": table.column("day"),
                    "channel": pa.array([channel] * len(table)),
                    "campaign": table.column("campaign"),
                    "spend_kes": table.column("spend_kes"),
                }
            )
        )
    return pa.concat_tables(parts)


def orders_clean(orders_raw: pa.Table) -> pa.Table:
    """Curated orders: sorted by order date (stand-in for the real clean layer)."""
    return orders_raw.sort_by([("order_date", "ascending"), ("order_id", "ascending")])


def new_customer_orders(orders_clean: pa.Table) -> pa.Table:
    """First orders only (customer_order_index == 1) — the true 'new customer' set."""
    return orders_clean.filter(pc.equal(orders_clean.column("customer_order_index"), 1))


@tag(
    ik_emit="metric",
    ik_namespace="DEMO",
    ik_id_tier="D",
    ik_claim_id="DEMO-D-010",
    ik_metric="blended_cac_kes",
    ik_fmt=",.0f",
    ik_grain="window",
    ik_filters="customer_order_index=1",
    ik_statement="Blended CAC = (Meta + Google spend) / new customers in window",
)
def blended_cac(ad_spend_unified: pa.Table, new_customer_orders: pa.Table) -> float:
    """True blended CAC: total spend divided by first orders in the window."""
    spend = float(sum(ad_spend_unified.column("spend_kes").to_pylist()))
    new_customers = len(new_customer_orders)
    if new_customers == 0:
        raise ValueError("no new customers in window — CAC denominator is zero")
    return spend / new_customers


@tag(
    ik_emit="metric",
    ik_namespace="DEMO",
    ik_id_tier="D",
    ik_claim_id="DEMO-D-011",
    ik_metric="mer",
    ik_fmt=".2f",
    ik_grain="window",
    ik_statement="MER = order revenue / blended ad spend over the window",
)
def demo_mer(ad_spend_unified: pa.Table, orders_clean: pa.Table) -> float:
    """MER: total order revenue divided by total blended ad spend."""
    spend = float(sum(ad_spend_unified.column("spend_kes").to_pylist()))
    if spend == 0:
        raise ValueError("ad spend is zero — MER denominator is zero")
    revenue = float(sum(orders_clean.column("revenue_kes").to_pylist()))
    return revenue / spend


@tag(
    ik_emit="metric",
    ik_namespace="DEMO",
    ik_id_tier="D",
    ik_claim_id="DEMO-D-012",
    ik_metric="naive_cac_kes",
    ik_fmt=",.0f",
    ik_grain="window",
    ik_statement=(
        "NAIVE CAC (deliberate P5 trap): spend / distinct customers in window — "
        "counts returning customers as acquisitions"
    ),
)
def naive_cac(ad_spend_unified: pa.Table, orders_clean: pa.Table) -> float:
    """The documented CAC drift, replayed: divides by distinct customers.

    Returning customers (first order before the window, index >= 2 inside it)
    inflate the denominator, so this lands below the true CAC. Kept so the
    reconciliation critic has a live target to refute.
    """
    spend = float(sum(ad_spend_unified.column("spend_kes").to_pylist()))
    distinct_customers = len(set(orders_clean.column("customer_id").to_pylist()))
    return spend / distinct_customers


@tag(
    ik_emit="metric",
    ik_namespace="DEMO",
    ik_id_tier="D",
    ik_claim_id="DEMO-D-013",
    ik_metric="arpu_kes",
    ik_fmt=",.0f",
    ik_grain="window",
    ik_filters="customer_order_index=1",
    ik_statement="ARPU = window order revenue / new customers in window",
)
def arpu(orders_clean: pa.Table, new_customer_orders: pa.Table) -> float:
    """Average revenue per newly-acquired customer in the window."""
    revenue = float(sum(orders_clean.column("revenue_kes").to_pylist()))
    new_customers = len(new_customer_orders)
    if new_customers == 0:
        raise ValueError("no new customers in window — ARPU denominator is zero")
    return revenue / new_customers


@tag(
    ik_emit="metric",
    ik_namespace="DEMO",
    ik_id_tier="D",
    ik_claim_id="DEMO-D-020",
    ik_metric="cac_payback_ratio",
    ik_fmt=".2f",
    ik_grain="window",
    ik_statement=(
        "CAC payback ratio = ARPU / blended CAC — a Layer-2 metric derived from "
        "two upstream claims, not from raw rows; >1 means the first order already "
        "clears acquisition cost"
    ),
)
def cac_payback_ratio(arpu: float, blended_cac: float) -> float:
    """Layer-2 metric derived purely from two upstream claim values.

    Its kwargs are the *values* of the ``arpu`` (DEMO-D-013) and ``blended_cac``
    (DEMO-D-010) claim nodes, so it carries no live input rows of its own. The
    adapter records those two claims as ``input_claims`` (claim->claim data
    lineage) — the provenance a derived metric has in place of a row fingerprint.
    """
    if blended_cac == 0:
        raise ValueError("blended CAC is zero — payback denominator is zero")
    return arpu / blended_cac

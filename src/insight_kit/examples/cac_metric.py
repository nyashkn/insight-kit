"""Reference metric: CAC as a Hamilton @feature module wired to the L1 gate.

This is the "one real metric, end to end" reference for the Hamilton-as-substrate
+ insight-kit-as-gate stack. It computes blended Customer Acquisition Cost the way
the nairomarket / Dock Blocks growth work does:

    CAC = (Meta ad spend in the window) / (new customers acquired in the window)

where a *new customer* is a customer whose first order falls in the window
(``customer_order_index == 1``). That "new customer" filter is exactly the
selection trap the PPC grind hit (a value that silently changes when the filter
drifts), so it is declared explicitly as a gate ``selection`` — never left
implicit in prose (V15).

In production the two leaf tables (`orders_rows`, `spend_rows`) are Hamilton
``@load_from`` nodes over the DuckDB catalog. Here they are plain ``inputs=`` so
the module is hermetic and fast to test; the metric logic is identical either way.

The metric node carries ``ik_*`` tags read by ``InsightKitHook``: on success the
hook fingerprints the node's *input rows* (registered_input provenance, V22) and
emits a typed ``claim`` through the frozen gate. A CAC number that was NOT
computed from live rows (a hardcoded literal, a value read off transform code)
has no registered input and therefore cannot publish — which is precisely the
P1 "verdict-from-proxy" failure the gate makes unrepresentable.

Run under the gate:

    from insight_kit.platform.gate import RunState
    from insight_kit.integrations.hamilton import build_driver
    from insight_kit.examples import cac_metric

    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [cac_metric])
    dr.execute(["cac_march"], inputs={"orders_rows": orders, "spend_rows": spend})

Cites: V15, V22, T7 (gate); §08 grind-replay (validation).
"""
from __future__ import annotations

import pyarrow as pa
from hamilton.function_modifiers import tag

# ---------------------------------------------------------------------------
# Curated feature nodes
# ---------------------------------------------------------------------------


def new_customer_orders(orders_rows: pa.Table) -> pa.Table:
    """Orders that represent a customer's first purchase (the 'new customer' set).

    The 'new customer' definition is ``customer_order_index == 1``. This is the
    single filter that determines the CAC denominator; getting it wrong is the
    documented CAC drift (a headline CAC of 1,059 vs the true 1,770). It lives
    in one node so there is one definition, and it is surfaced to the gate as an
    explicit selection filter (see the ``ik_filters`` tag on ``cac_march``).
    """
    idx = orders_rows.column("customer_order_index").to_pylist()
    mask = [i == 1 for i in idx]
    return orders_rows.filter(pa.array(mask))


@tag(
    ik_emit="metric",
    ik_namespace="DOCK",
    ik_id_tier="D",
    ik_claim_id="DOCK-D-001",
    ik_metric="cac_kes",
    ik_fmt=",.0f",
    ik_grain="month",
    ik_date_window="2026-03-01/2026-03-31",
    ik_filters="customer_order_index=1",
    ik_statement="March 2026 blended CAC = Meta spend / new customers",
)
def cac_march(new_customer_orders: pa.Table, spend_rows: pa.Table) -> float:
    """Blended CAC for the March window (Meta spend ÷ distinct new customers).

    Derives the value directly from the two row tables it is given, so the gate
    fingerprints *those rows* as the claim's registered input. `new_customers`
    counts distinct customer_id in the first-order set; `spend` sums Meta spend.
    """
    new_customers = len(set(new_customer_orders.column("customer_id").to_pylist()))
    if new_customers == 0:
        raise ValueError("no new customers in window — CAC denominator is zero")
    spend = float(sum(spend_rows.column("spend_kes").to_pylist()))
    return spend / new_customers

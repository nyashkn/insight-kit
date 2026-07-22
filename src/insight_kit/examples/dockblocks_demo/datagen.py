"""Seeded dockblocks data generator — ground truth by construction.

Every table is produced from a single ``random.Random(seed)`` stream, so the
same seed yields byte-identical tables on every machine (no wall clock, no
global RNG). The ground-truth metrics are computed from the generated rows
themselves before they are handed out — so a DAG (or an agent) computing the
same metric can be graded exactly, not approximately.

Planted trap (P5, the documented CAC drift): the order stream includes a pool
of customers whose FIRST order predates the analysis window. Inside the
window they appear with ``customer_order_index >= 2``. A naive CAC that
divides spend by *distinct customers seen in the window* silently includes
them and lands too low — the 1059-vs-1770 failure. The true CAC divides by
first orders only (``customer_order_index == 1``). Both numbers are in
``ground_truth`` so the drift delta itself is an assertable fact.

Scale: default (days=90) is a few thousand rows — fast for CI. For large
agent-session fixtures raise ``days`` and ``scale`` and call
``write_parquet``; determinism is preserved at any size.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa

_START = dt.date(2026, 1, 1)  # fixed epoch — never derived from the wall clock

_META_CAMPAIGNS = ("meta_prospecting", "meta_retargeting", "meta_advantage")
_GOOGLE_CAMPAIGNS = ("google_search_brand", "google_pmax")
_EMAIL_EVENTS = ("sent", "open", "click")
_DEAL_STAGES = ("mql", "sql", "proposal", "closed_won", "closed_lost")


@dataclass(frozen=True)
class DemoData:
    """The generated tables plus their metrics' ground truth.

    ground_truth keys:
      total_spend_kes, revenue_kes, new_customers, distinct_customers,
      cac_kes (spend / new customers — the true definition),
      naive_cac_kes (spend / distinct customers — the planted P5 trap),
      mer (revenue / spend).
    """

    meta_ads: pa.Table
    google_ads: pa.Table
    orders: pa.Table
    crm_contacts: pa.Table
    crm_deals: pa.Table
    email_events: pa.Table
    ground_truth: dict[str, float]

    def tables(self) -> dict[str, pa.Table]:
        """All tables keyed by their canonical source name."""
        return {
            "meta_ads": self.meta_ads,
            "google_ads": self.google_ads,
            "orders": self.orders,
            "crm_contacts": self.crm_contacts,
            "crm_deals": self.crm_deals,
            "email_events": self.email_events,
        }

    def write_parquet(self, target_dir: Path | str) -> dict[str, Path]:
        """Materialize every table as parquet under target_dir; returns the paths."""
        import pyarrow.parquet as pq

        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        for name, table in self.tables().items():
            path = target / f"{name}.parquet"
            pq.write_table(table, path)
            paths[name] = path
        return paths


def _iso(day_index: int) -> str:
    return (_START + dt.timedelta(days=day_index)).isoformat()


def generate(seed: int = 42, days: int = 90, scale: float = 1.0) -> DemoData:
    """Generate the dockblocks testbed for `days` days starting 2026-01-01.

    Args:
        seed:  RNG seed — same seed, same bytes, always.
        days:  length of the analysis window in days.
        scale: multiplies daily volumes (orders, contacts, events) for large
               fixtures; 1.0 keeps CI-sized tables.
    """
    rng = random.Random(seed)

    # ---- ad spend: Meta + Google, per day per campaign -------------------
    meta_rows: dict[str, list[Any]] = {"day": [], "campaign": [], "spend_kes": [], "impressions": [], "clicks": []}
    google_rows: dict[str, list[Any]] = {"day": [], "campaign": [], "spend_kes": [], "impressions": [], "clicks": []}
    for d in range(days):
        day = _iso(d)
        for campaign in _META_CAMPAIGNS:
            spend = round(rng.uniform(800, 2500) * scale, 2)
            impressions = int(spend * rng.uniform(28, 45))
            meta_rows["day"].append(day)
            meta_rows["campaign"].append(campaign)
            meta_rows["spend_kes"].append(spend)
            meta_rows["impressions"].append(impressions)
            meta_rows["clicks"].append(max(1, int(impressions * rng.uniform(0.008, 0.03))))
        for campaign in _GOOGLE_CAMPAIGNS:
            spend = round(rng.uniform(500, 1800) * scale, 2)
            impressions = int(spend * rng.uniform(20, 38))
            google_rows["day"].append(day)
            google_rows["campaign"].append(campaign)
            google_rows["spend_kes"].append(spend)
            google_rows["impressions"].append(impressions)
            google_rows["clicks"].append(max(1, int(impressions * rng.uniform(0.01, 0.04))))

    # ---- customers & orders ----------------------------------------------
    # Pre-window pool: customers whose FIRST order predates the window. Their
    # in-window orders carry customer_order_index >= 2 — the P5 trap material.
    pool_size = max(1, int(days * 2 * scale))
    prior_orders: dict[str, int] = {
        f"cust_{i:05d}": rng.randint(1, 5) for i in range(pool_size)
    }
    next_customer = pool_size

    order_rows: dict[str, list[Any]] = {
        "order_id": [], "customer_id": [], "order_date": [], "revenue_kes": [], "customer_order_index": [],
    }
    order_seq = 0

    def _add_order(customer_id: str, day: str, index: int) -> None:
        nonlocal order_seq
        order_seq += 1
        order_rows["order_id"].append(f"ord_{order_seq:06d}")
        order_rows["customer_id"].append(customer_id)
        order_rows["order_date"].append(day)
        order_rows["revenue_kes"].append(round(rng.uniform(1500, 9500) * scale, 2))
        order_rows["customer_order_index"].append(index)

    for d in range(days):
        day = _iso(d)
        # new customers: first order inside the window (index == 1)
        for _ in range(rng.randint(3, max(4, int(8 * scale)))):
            customer_id = f"cust_{next_customer:05d}"
            next_customer += 1
            prior_orders[customer_id] = 1
            _add_order(customer_id, day, 1)
        # returning orders: drawn from everyone who has ordered before
        existing = sorted(prior_orders)
        for _ in range(rng.randint(1, max(2, int(5 * scale)))):
            customer_id = existing[rng.randrange(len(existing))]
            prior_orders[customer_id] += 1
            _add_order(customer_id, day, prior_orders[customer_id])

    # ---- CRM: one contact per customer, deals for a subset ----------------
    contact_rows: dict[str, list[Any]] = {"contact_id": [], "email": [], "created_at": [], "source": []}
    customer_ids = sorted({c for c in order_rows["customer_id"]})
    for customer_id in customer_ids:
        contact_rows["contact_id"].append(customer_id.replace("cust_", "cont_"))
        contact_rows["email"].append(f"{customer_id}@example.co.ke")
        contact_rows["created_at"].append(_iso(rng.randrange(days)))
        contact_rows["source"].append(rng.choice(["meta", "google", "referral", "organic"]))

    deal_rows: dict[str, list[Any]] = {"deal_id": [], "contact_id": [], "stage": [], "amount_kes": [], "closed_at": []}
    for i, contact_id in enumerate(contact_rows["contact_id"]):
        if rng.random() < 0.25:
            stage = rng.choice(_DEAL_STAGES)
            deal_rows["deal_id"].append(f"deal_{i:05d}")
            deal_rows["contact_id"].append(contact_id)
            deal_rows["stage"].append(stage)
            deal_rows["amount_kes"].append(round(rng.uniform(5000, 80000) * scale, 2))
            deal_rows["closed_at"].append(_iso(rng.randrange(days)) if stage.startswith("closed") else None)

    # ---- email lifecycle events -------------------------------------------
    event_rows: dict[str, list[Any]] = {"event_id": [], "contact_id": [], "event_type": [], "event_date": []}
    event_seq = 0
    for contact_id in contact_rows["contact_id"]:
        for _ in range(rng.randint(0, max(1, int(4 * scale)))):
            event_seq += 1
            event_rows["event_id"].append(f"evt_{event_seq:07d}")
            event_rows["contact_id"].append(contact_id)
            event_rows["event_type"].append(rng.choice(_EMAIL_EVENTS))
            event_rows["event_date"].append(_iso(rng.randrange(days)))

    # ---- ground truth, computed from the rows just generated ---------------
    total_spend = sum(meta_rows["spend_kes"]) + sum(google_rows["spend_kes"])
    revenue = sum(order_rows["revenue_kes"])
    new_customers = sum(1 for i in order_rows["customer_order_index"] if i == 1)
    distinct_customers = len(set(order_rows["customer_id"]))
    ground_truth: dict[str, float] = {
        "total_spend_kes": total_spend,
        "revenue_kes": revenue,
        "new_customers": float(new_customers),
        "distinct_customers": float(distinct_customers),
        "cac_kes": total_spend / new_customers,
        "naive_cac_kes": total_spend / distinct_customers,  # the P5 trap answer
        "mer": revenue / total_spend,
    }

    return DemoData(
        meta_ads=pa.table(meta_rows),
        google_ads=pa.table(google_rows),
        orders=pa.table(order_rows),
        crm_contacts=pa.table(contact_rows),
        crm_deals=pa.table(deal_rows),
        email_events=pa.table(event_rows),
        ground_truth=ground_truth,
    )

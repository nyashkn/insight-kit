"""Meta/Shopify attribution acquire chain — ik_acquire + T32 coverage critic demo.

This module is a runnable, CI-safe example that exercises the full
research -> skill_use -> claim gate chain (ik_acquire) on the real
Meta/Shopify attribution pattern, then fires the T32 endpoint-coverage critic.

Overview
--------
The Meta/Shopify attribution task has two API legs:

  1. RESEARCH — shopify.dev/assistant/search docs (what endpoints are available
     for orders + customer new-vs-returning composition).
     Fixtures: captured live output stored in examples/fixtures/.
     Live mode: --live flag does a real POST to https://shopify.dev/assistant/search
     (urllib, no third-party deps, same approach as search_docs.mjs).

  2. SKILL_USE (extraction) — bulkOperationRunQuery (Shopify Admin GraphQL)
     pulls all orders.  Meta Graph act_<id>/insights pulls adset-day rows.
     The claim = the attribution assertion derived from those two sources.

Coverage gap (T32 demo)
-----------------------
The extraction uses ``bulkOperationRunQuery`` (orders pull) but does NOT query
``Customer.numberOfOrders`` — which is the canonical endpoint for determining
new-vs-returning customer composition.  The T32 endpoint-coverage critic detects
this gap and fires a critique on the claim record.  This is the whole point:
demonstrating "could the analyst have missed an important API for
new-vs-returning?".

Live extraction (--live-extract)
---------------------------------
Real Meta/Shopify extraction requires credentials that must NEVER be committed
or appear in fixtures.  See ``_live_extract_stub()`` below for the documented
stub; the body intentionally raises ``NotImplementedError`` unless
META_TOKEN + SHOPIFY_TOKEN are present in os.environ at call time.  CI never
sets these variables, so the code path is dead in automated runs.

Usage
-----
    uv run python -m insight_kit.examples.shopify_meta_acquire           # fixture mode
    uv run python -m insight_kit.examples.shopify_meta_acquire --live    # live doc search

Cites: T30, T31, T32, V16, V20, V22, C12.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from insight_kit.platform.gate.acquire import ik_acquire
from insight_kit.platform.gate.runcheck import check_coverage_from_run
from insight_kit.platform.gate.runstate import (
    CritiqueState,
    RunState,
    apply_critique,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# 1. load_search_results — fixture or live
# ---------------------------------------------------------------------------


def load_search_results() -> dict[str, Any]:
    """Read the 3 fixture JSON files and return a combined api_search_result dict.

    Shape: {"query_results": {stem: hits_list, ...}, "source": "fixtures"}

    The three fixtures capture genuine live output from
    https://shopify.dev/assistant/search (POST {query, api_name:"admin"})
    and cover the three doc queries relevant to the attribution task:
      - search_orders_bulk    → bulkOperationRunQuery payload + mutation docs
      - search_customer_orders → Customer.numberOfOrders + customers query
      - search_order_fields   → Order.createdAt + currentTotalPriceSet
    """
    stems = ["search_orders_bulk", "search_customer_orders", "search_order_fields"]
    query_results: dict[str, Any] = {}
    for stem in stems:
        path = _FIXTURES_DIR / f"{stem}.json"
        query_results[stem] = json.loads(path.read_text(encoding="utf-8"))
    return {"query_results": query_results, "source": "fixtures"}


def live_search(query: str) -> list[dict[str, Any]]:
    """POST https://shopify.dev/assistant/search and return the JSON hits array.

    Used only in --live mode.  No third-party deps (urllib only), mirroring
    the approach in search_docs.mjs.

    Args:
        query: the search query string.

    Returns:
        List of hit dicts: [{score, content, url, title, domain}, ...].
    """
    url = "https://shopify.dev/assistant/search"
    payload = json.dumps({"query": query, "api_name": "admin"}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Shopify-Surface": "insight-kit-example",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_search_results_live() -> dict[str, Any]:
    """Run 3 live doc searches against shopify.dev and return combined results.

    Same shape as load_search_results() but hits the real API.
    """
    queries = {
        "search_orders_bulk": "bulkOperationRunQuery orders bulk operation",
        "search_customer_orders": "Customer numberOfOrders new returning customers query",
        "search_order_fields": "Order createdAt currentTotalPriceSet fields",
    }
    query_results: dict[str, Any] = {}
    for stem, q in queries.items():
        print(f"  [live-search] {q!r} ...", file=sys.stderr)
        query_results[stem] = live_search(q)
    return {"query_results": query_results, "source": "live"}


# ---------------------------------------------------------------------------
# 2. distill_endpoint_index
# ---------------------------------------------------------------------------


def distill_endpoint_index(search_results: dict[str, Any]) -> dict[str, Any]:
    """Derive an endpoint index from Shopify doc search hits.

    Reads the 'query_results' key and produces the T31 endpoint_index shape:
      {"available_endpoints": [{endpoint, relevance, source, why}, ...]}

    Relevance logic for the attribution task:
      - ``bulkOperationRunQuery``    → high  (orders pull: the main data leg)
      - ``Customer.numberOfOrders``  → high  (new-vs-returning composition)
      - All other extracted endpoints → medium

    The two high-relevance endpoints are the ones the attribution task
    genuinely needs.  Only the first one (bulkOperationRunQuery) is used by
    the synthetic extraction, so the T32 critic will flag the miss.

    Args:
        search_results: output of load_search_results() or load_search_results_live().

    Returns:
        endpoint_index dict suitable for passing as ik_acquire(endpoint_index=...).
    """
    seen: dict[str, dict[str, Any]] = {}

    # High-priority endpoints for the attribution task
    high_endpoints_required = {
        "bulkOperationRunQuery",
        "Customer.numberOfOrders",
    }

    query_results = search_results.get("query_results", {})
    for _stem, hits in query_results.items():
        if not isinstance(hits, list):
            continue
        for hit in hits:
            url = hit.get("url", "")
            title = hit.get("title", "")

            # Derive endpoint id from URL path tail or title
            ep_id = _extract_endpoint_id(url, title)
            if not ep_id or ep_id in seen:
                continue

            relevance = "high" if ep_id in high_endpoints_required else "medium"
            seen[ep_id] = {
                "endpoint": ep_id,
                "relevance": relevance,
                "source": url,
                "why": _endpoint_why(ep_id),
            }

    # Always ensure both high-relevance endpoints are present — they may not
    # appear in fixture hits if the search didn't surface them directly.
    for ep_id in high_endpoints_required:
        if ep_id not in seen:
            seen[ep_id] = {
                "endpoint": ep_id,
                "relevance": "high",
                "source": _fallback_source(ep_id),
                "why": _endpoint_why(ep_id),
            }

    return {"available_endpoints": list(seen.values())}


def _extract_endpoint_id(url: str, title: str) -> str | None:
    """Derive a stable endpoint id from a shopify.dev doc hit.

    Tries URL path tail first, then title prefix, to produce a short
    PascalCase or camelCase identifier.
    """
    # URL patterns:
    #   .../mutations/bulkOperationRunQuery  → bulkOperationRunQuery
    #   .../objects/Customer                 → Customer (not enough, skip)
    #   .../queries/customers                → customers
    #   .../queries/order                    → order
    #   .../queries/orderByIdentifier        → orderByIdentifier
    import re

    if url:
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        # Strip trailing anchors (e.g. #numberOfOrders)
        tail = tail.split("#")[0]
        if tail and re.match(r"^[A-Za-z][A-Za-z0-9_]+$", tail):
            # Special case: if the URL is for a Payload type and the title
            # mentions a mutation, prefer the mutation name.
            if "Payload" in tail:
                # e.g. BulkOperationRunQueryPayload → strip and use mutation name
                mutation_name = tail.replace("Payload", "")
                # Lowercase first char to match GraphQL mutation naming
                ep = mutation_name[0].lower() + mutation_name[1:] if mutation_name else tail
                return ep
            return tail

    # Fall back to first token of title before " - "
    if title:
        first = title.split(" - ")[0].strip().split()[0] if title else ""
        import re as _re

        if first and _re.match(r"^[A-Za-z][A-Za-z0-9_.]+$", first):
            return first

    return None


_ENDPOINT_WHY: dict[str, str] = {
    "bulkOperationRunQuery": (
        "Primary Shopify orders pull: retrieves all order records "
        "asynchronously for revenue and volume attribution analysis."
    ),
    "Customer.numberOfOrders": (
        "New-vs-returning customer composition: determines whether each "
        "order is from a first-time buyer, critical for attributing "
        "acquisition vs retention impact of ad targeting changes."
    ),
    "customers": "Customer list query; source for numberOfOrders field.",
    "order": "Single-order detail query (createdAt, currentTotalPriceSet).",
    "orderByIdentifier": "Order lookup by identifier.",
}

_ENDPOINT_SOURCES: dict[str, str] = {
    "bulkOperationRunQuery": (
        "https://shopify.dev/docs/api/admin-graphql/latest/mutations/bulkOperationRunQuery"
    ),
    "Customer.numberOfOrders": (
        "https://shopify.dev/docs/api/admin-graphql/latest/queries/customers"
    ),
}


def _endpoint_why(ep_id: str) -> str:
    return _ENDPOINT_WHY.get(ep_id, f"Shopify Admin API endpoint: {ep_id}.")


def _fallback_source(ep_id: str) -> str:
    return _ENDPOINT_SOURCES.get(ep_id, "https://shopify.dev/docs/api/admin-graphql/latest/")


# ---------------------------------------------------------------------------
# 3. sample_extraction_result — synthetic, sanitized
# ---------------------------------------------------------------------------


def sample_extraction_result() -> dict[str, Any]:
    """Return a SYNTHETIC, sanitized api_extraction_result dict.

    Mirrors the shape of extract_g4f7_attribution.py's output but uses tiny,
    clearly fake data:
      - Meta adset-day rows: 3 rows, synthetic adset ids and spend figures.
      - Shopify orders: 5 rows, customer ids like 'cust_demo_1', no real totals.

    IMPORTANT: The skill_use_source for this extraction is "bulkOperationRunQuery"
    (it pulled orders via the bulk operation) but it did NOT query
    Customer.numberOfOrders.  This is intentional: the T32 coverage critic will
    detect the missed high-relevance endpoint and fire a critique on the claim.

    No real customer ids, no real spend totals, no real adset ids.
    Safe to commit; CI-safe.
    """
    return {
        "extraction_tool": "shopify-meta-extractor",
        "skill_use_source": "bulkOperationRunQuery",
        "synthetic": True,
        "note": (
            "Synthetic fixture — mirrors extract_g4f7_attribution.py shape "
            "but all values are fabricated for demo purposes only."
        ),
        "meta_adset_daily": [
            {
                "adset_id": "demo_adset_001",
                "adset_name": "Demo_MaxValue_Local_All",
                "date": "2026-05-01",
                "spend_kes": 1200.0,
                "impressions": 8400,
                "reach": 6200,
                "clicks": 142,
                "purchases": 3,
                "is_treated": True,
            },
            {
                "adset_id": "demo_adset_001",
                "adset_name": "Demo_MaxValue_Local_All",
                "date": "2026-05-02",
                "spend_kes": 1350.0,
                "impressions": 9100,
                "reach": 6800,
                "clicks": 161,
                "purchases": 4,
                "is_treated": True,
            },
            {
                "adset_id": "demo_adset_002",
                "adset_name": "Demo_Local_Volume_Broad_KE",
                "date": "2026-05-01",
                "spend_kes": 980.0,
                "impressions": 7200,
                "reach": 5400,
                "clicks": 118,
                "purchases": 2,
                "is_treated": False,
            },
        ],
        "shopify_orders": [
            {
                "order_id": "demo_order_001",
                "created_at": "2026-05-01T09:15:00Z",
                "financial_status": "PAID",
                "total_kes": 2800.0,
                "customer_id": "cust_demo_1",
                # NOTE: numberOfOrders for cust_demo_1 NOT fetched — coverage gap
            },
            {
                "order_id": "demo_order_002",
                "created_at": "2026-05-01T14:22:00Z",
                "financial_status": "PAID",
                "total_kes": 1500.0,
                "customer_id": "cust_demo_2",
            },
            {
                "order_id": "demo_order_003",
                "created_at": "2026-05-02T08:05:00Z",
                "financial_status": "PAID",
                "total_kes": 3200.0,
                "customer_id": "cust_demo_1",
            },
            {
                "order_id": "demo_order_004",
                "created_at": "2026-05-02T11:40:00Z",
                "financial_status": "PAID",
                "total_kes": 950.0,
                "customer_id": "cust_demo_3",
            },
            {
                "order_id": "demo_order_005",
                "created_at": "2026-05-02T16:55:00Z",
                "financial_status": "PAID",
                "total_kes": 2100.0,
                "customer_id": "cust_demo_2",
            },
        ],
        "attribution_window": {
            "since": "2026-05-01",
            "until": "2026-05-02",
            "intervention_date": "2026-05-04",
        },
        # Customer.numberOfOrders NOT fetched — this is the coverage gap the T32
        # critic will flag.  In a real run, this would be populated from the
        # customers query to determine new-vs-returning composition.
        "customer_order_counts": None,
        "coverage_note": (
            "bulkOperationRunQuery used for order pull. "
            "Customer.numberOfOrders NOT queried — new-vs-returning composition "
            "unknown.  T32 critic should flag this gap."
        ),
    }


# ---------------------------------------------------------------------------
# 4. run_demo
# ---------------------------------------------------------------------------


def run_demo(run_dir: Path, *, live: bool = False) -> dict[str, Any]:
    """Build RunState, run ik_acquire, fire coverage critic, return summary.

    Args:
        run_dir: directory for the run (will be created if absent).
        live:    if True, replace fixture search with live shopify.dev search.

    Returns:
        Summary dict with keys:
          research_id, skill_use_id, claim_id,
          record_ids: {research, skill_use, claim},
          coverage: {passed, missed_high_endpoints},
          critique_fired: bool
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    # --- Inputs ---
    if live:
        print("[demo] live doc search ...", file=sys.stderr)
        search_results = load_search_results_live()
    else:
        search_results = load_search_results()

    extraction_result = sample_extraction_result()
    endpoint_index = distill_endpoint_index(search_results)

    # --- Stable IDs ---
    research_id = "RES-META-SHOPIFY-ATTR-001"
    skill_use_id = "SKU-META-SHOPIFY-ATTR-001"
    # Claim id must match the gate regex (see test_acquire.py: "TEST-D-001" works)
    claim_id = "ATTR-D-001"

    # --- RunState ---
    state = RunState()

    # --- ik_acquire ---
    result = ik_acquire(
        research_id=research_id,
        skill_use_id=skill_use_id,
        claim_id=claim_id,
        api_search_result=search_results,
        api_extraction_result=extraction_result,
        claim_fields={
            "total_orders": len(extraction_result["shopify_orders"]),
            "treated_adset_spend_kes": sum(
                r["spend_kes"]
                for r in extraction_result["meta_adset_daily"]
                if r["is_treated"]
            ),
            "treated_adset_purchases": sum(
                r["purchases"]
                for r in extraction_result["meta_adset_daily"]
                if r["is_treated"]
            ),
            "new_vs_returning_known": False,  # gap: Customer.numberOfOrders not fetched
        },
        research_query="shopify bulkOperationRunQuery orders + Customer.numberOfOrders new-vs-returning",
        research_source="shopify.dev/assistant/search",
        skill_use_tool="shopify-admin-graphql + meta-graph-api",
        skill_use_source="bulkOperationRunQuery",  # the endpoint actually used
        claim_tier="draft",
        claim_narrative_ref="docs/superpowers/specs/2026-05-20-g4f7-attribution-design.md",
        endpoint_index=endpoint_index,
        run_state=state,
        run_dir=run_dir,
    )

    # --- T32 coverage critic ---
    coverage = check_coverage_from_run(
        run_dir,
        result.research_ref.record_id,
        claim_id=result.claim_id,
    )

    critique_fired = False
    if not coverage.passed:
        critique = CritiqueState.open(
            severity="high",
            reason=coverage.message,
            critic_id="endpoint-coverage-checker",
            target_record_id=result.claim_ref.record_id,
        )
        apply_critique(
            run_state=state,
            record_id=result.claim_ref.record_id,
            record_type="claim",
            tier="draft",
            audience=None,
            critique=critique,
            run_dir=run_dir,
        )
        critique_fired = True

    return {
        "research_id": result.research_id,
        "skill_use_id": result.skill_use_id,
        "claim_id": result.claim_id,
        "record_ids": {
            "research": result.research_ref.record_id,
            "skill_use": result.skill_use_ref.record_id,
            "claim": result.claim_ref.record_id,
        },
        "coverage": {
            "passed": coverage.passed,
            "missed_high_endpoints": coverage.missed_high_endpoints,
            "available_high_count": coverage.available_high_count,
            "used_endpoint_count": coverage.used_endpoint_count,
            "message": coverage.message,
        },
        "critique_fired": critique_fired,
        "records_emitted": len(state.records),
        "critique_rounds": state.critiqueRounds,
        "run_dir": str(run_dir),
    }


# ---------------------------------------------------------------------------
# 5. _live_extract_stub — documented, cred-gated, never called in CI
# ---------------------------------------------------------------------------


def _live_extract_stub() -> dict[str, Any]:
    """Stub for real Meta/Shopify extraction — NEVER called in CI.

    This function documents the live extraction path that mirrors
    extract_g4f7_attribution.py.  It requires META_TOKEN + SHOPIFY_TOKEN
    in os.environ and raises NotImplementedError (as a clear stub marker)
    if called without credentials.

    In a real implementation this would:
      1. POST Meta Graph act_{id}/insights (daily adset data) via urllib.
      2. Run Shopify Admin GraphQL bulkOperationRunQuery (all orders) via urllib.
      3. Return a dict in the same shape as sample_extraction_result().

    SECURITY CONSTRAINT: This function MUST NOT be called with real credentials
    stored in fixtures or committed files.  Always inject via environment
    variables at runtime (e.g. via signet secret_exec).

    Raises:
        NotImplementedError: always (credentials present or not — stub only).
    """
    meta_token = os.environ.get("META_TOKEN")
    shopify_token = os.environ.get("SHOPIFY_TOKEN")
    if not meta_token or not shopify_token:
        raise NotImplementedError(
            "_live_extract_stub: META_TOKEN and SHOPIFY_TOKEN must be set in "
            "os.environ to run live extraction.  This path is intentionally "
            "disabled in CI.  See extract_g4f7_attribution.py for the real "
            "implementation.  Use sample_extraction_result() for CI-safe synthetic data."
        )
    # TODO: implement real extraction using urllib (no third-party deps):
    #   - meta_get(f"act_{meta_ad_account_id}/insights", params) — same as extract_g4f7
    #   - shopify_gql(BULK_ORDERS_MUTATION) + poll loop — same as extract_g4f7
    # Return shape: same as sample_extraction_result() but with real data.
    raise NotImplementedError(
        "_live_extract_stub: real extraction not yet implemented in this example. "
        "See extract_g4f7_attribution.py for the full implementation."
    )


# ---------------------------------------------------------------------------
# 6. main / CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Meta/Shopify attribution acquire chain demo: ik_acquire "
            "(research -> skill_use -> claim) + T32 endpoint-coverage critic."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help=(
            "Use live shopify.dev/assistant/search for the research snapshot "
            "instead of the captured fixtures.  Requires internet access.  "
            "Extraction stays synthetic unless --live-extract is explicitly "
            "invoked (requires META_TOKEN + SHOPIFY_TOKEN env vars)."
        ),
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help=(
            "Run directory for emitted records.  Defaults to a temp directory "
            "that is deleted after the demo completes.  Pass a persistent path "
            "to inspect emitted records."
        ),
    )
    args = parser.parse_args()

    cleanup = False
    if args.run_dir is None:
        tmp = tempfile.mkdtemp(prefix="ik_shopify_meta_demo_")
        run_dir = Path(tmp)
        cleanup = True
    else:
        run_dir = args.run_dir

    try:
        print("insight-kit demo: Meta/Shopify attribution acquire chain")
        print("=" * 60)
        if args.live:
            print("Mode: LIVE doc search (shopify.dev/assistant/search)")
        else:
            print("Mode: FIXTURE (captured shopify.dev search output)")
        print(f"Run dir: {run_dir}")
        print()

        summary = run_demo(run_dir, live=args.live)

        print("Records emitted:")
        for label, rid in summary["record_ids"].items():
            print(f"  {label:12s}: {rid}")
        print()

        cov = summary["coverage"]
        status = "PASSED" if cov["passed"] else "FAILED"
        print(f"T32 Coverage check: {status}")
        print(f"  available high-relevance endpoints : {cov['available_high_count']}")
        print(f"  endpoints actually used            : {cov['used_endpoint_count']}")
        if cov["missed_high_endpoints"]:
            print(f"  MISSED high-relevance endpoints    : {cov['missed_high_endpoints']}")
        print(f"  {cov['message']}")
        print()

        critique_label = "YES (critique.jsonl written)" if summary["critique_fired"] else "NO"
        print(f"Critique fired: {critique_label}")
        print(f"Total records emitted: {summary['records_emitted']}")
        print()
        print("Summary:")
        print(json.dumps(summary, indent=2, default=str))

    finally:
        if cleanup:
            import shutil

            shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

"""Tests for the Meta/Shopify attribution acquire chain example (T30/T31/T32 E2E).

Fixture mode only — no network, no credentials required.  CI-safe.

Coverage:
  - run_demo(tmp_run_dir, live=False) emits 3 linked records (research, skill_use,
    claim) with resolvable cites edges.
  - endpoint_index.json persisted under the research record bundle (T31).
  - T32 coverage critic fires on the missed high-relevance Customer.numberOfOrders
    endpoint; critique.jsonl persisted on the claim record.
  - summary.critique_fired is True; missed_high_endpoints includes
    'Customer.numberOfOrders'.
  - Full-coverage variant: override skill_use_source to cover both high endpoints
    via a second skill_use emit → coverage passes, no critique.
  - distill_endpoint_index unit: both high endpoints present, both marked high.
  - distill_endpoint_index discovery: Customer.numberOfOrders comes from hit
    content (removing the customers hit drops it from the index).
  - --live-extract without creds: run_demo(live_extract=True) raises
    NotImplementedError.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from insight_kit.examples.shopify_meta_acquire import (
    distill_endpoint_index,
    load_search_results,
    run_demo,
    sample_extraction_result,
)
from insight_kit.platform.gate.acquire import ik_acquire
from insight_kit.platform.gate.emit import ik_skill_use_emit
from insight_kit.platform.gate.runcheck import check_coverage_from_run
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import endpoint_index_path

# ---------------------------------------------------------------------------
# Helper: build an endpoint_index that covers BOTH high-relevance endpoints
# ---------------------------------------------------------------------------


def _full_coverage_endpoint_index() -> dict[str, Any]:
    """Endpoint index where both high endpoints are present."""
    return {
        "available_endpoints": [
            {
                "endpoint": "bulkOperationRunQuery",
                "relevance": "high",
                "source": "https://shopify.dev/docs/api/admin-graphql/latest/mutations/bulkOperationRunQuery",
                "why": "Primary orders pull",
            },
            {
                "endpoint": "Customer.numberOfOrders",
                "relevance": "high",
                "source": "https://shopify.dev/docs/api/admin-graphql/latest/queries/customers",
                "why": "New-vs-returning composition",
            },
        ]
    }


# ---------------------------------------------------------------------------
# Test: run_demo fixture mode — missed-high critique path
# ---------------------------------------------------------------------------


class TestRunDemoMissedHigh:
    def test_run_demo_returns_summary(self, tmp_path: Path) -> None:
        """run_demo(live=False) returns a summary dict."""
        summary = run_demo(tmp_path / "run")
        assert isinstance(summary, dict)

    def test_run_demo_three_records_emitted(self, tmp_path: Path) -> None:
        """run_demo emits exactly 3 records (research, skill_use, claim)."""
        summary = run_demo(tmp_path / "run")
        assert summary["records_emitted"] == 3

    def test_run_demo_record_ids_present(self, tmp_path: Path) -> None:
        """Summary contains research, skill_use, claim record ids."""
        summary = run_demo(tmp_path / "run")
        rids = summary["record_ids"]
        assert "research" in rids
        assert "skill_use" in rids
        assert "claim" in rids
        # Each id is a non-empty string
        for key, rid in rids.items():
            assert isinstance(rid, str) and rid, f"record_id for {key!r} is empty"

    def test_run_demo_cites_edges_on_disk(self, tmp_path: Path) -> None:
        """skill_use cites research; claim cites both (resolvable edges on disk)."""
        run_dir = tmp_path / "run"
        summary = run_demo(run_dir)
        rids = summary["record_ids"]

        # skill_use must cite research
        sku_rec = json.loads(
            (run_dir / "records" / rids["skill_use"] / "record.json").read_text()
        )
        assert rids["research"] in sku_rec["cites"]

        # claim must cite both research and skill_use
        claim_rec = json.loads(
            (run_dir / "records" / rids["claim"] / "record.json").read_text()
        )
        assert rids["research"] in claim_rec["cites"]
        assert rids["skill_use"] in claim_rec["cites"]

    def test_run_demo_endpoint_index_persisted(self, tmp_path: Path) -> None:
        """endpoint_index.json written under the research record bundle (T31)."""
        run_dir = tmp_path / "run"
        summary = run_demo(run_dir)
        ei_path = endpoint_index_path(run_dir, summary["record_ids"]["research"])
        assert ei_path.exists(), "endpoint_index.json must be written by run_demo"

    def test_run_demo_both_high_endpoints_in_index(self, tmp_path: Path) -> None:
        """endpoint_index contains both high-relevance endpoints."""
        run_dir = tmp_path / "run"
        summary = run_demo(run_dir)
        ei_path = endpoint_index_path(run_dir, summary["record_ids"]["research"])
        ei = json.loads(ei_path.read_text())
        eps = ei["available_endpoints"]
        high_ids = {
            ep.get("endpoint") or ep.get("id") for ep in eps if ep.get("relevance") == "high"
        }
        assert "bulkOperationRunQuery" in high_ids, (
            f"bulkOperationRunQuery must be high-relevance in index; got {high_ids!r}"
        )
        assert "Customer.numberOfOrders" in high_ids, (
            f"Customer.numberOfOrders must be high-relevance in index; got {high_ids!r}"
        )

    def test_run_demo_coverage_fails_missed_customer_endpoint(
        self, tmp_path: Path
    ) -> None:
        """Coverage check must fail — Customer.numberOfOrders not used."""
        summary = run_demo(tmp_path / "run")
        cov = summary["coverage"]
        assert cov["passed"] is False, (
            "Coverage check must fail when Customer.numberOfOrders is not used"
        )
        assert "Customer.numberOfOrders" in cov["missed_high_endpoints"], (
            f"Customer.numberOfOrders must be in missed_high_endpoints; "
            f"got {cov['missed_high_endpoints']!r}"
        )

    def test_run_demo_critique_fired(self, tmp_path: Path) -> None:
        """summary.critique_fired is True when coverage check fails."""
        summary = run_demo(tmp_path / "run")
        assert summary["critique_fired"] is True

    def test_run_demo_critique_jsonl_persisted(self, tmp_path: Path) -> None:
        """critique.jsonl persisted under the claim record's events/ dir."""
        run_dir = tmp_path / "run"
        summary = run_demo(run_dir)
        critique_path = (
            run_dir
            / "records"
            / summary["record_ids"]["claim"]
            / "events"
            / "critique.jsonl"
        )
        assert critique_path.exists(), "critique.jsonl must be written when critique fires"

        events = [
            json.loads(line)
            for line in critique_path.read_text().splitlines()
            if line.strip()
        ]
        assert len(events) == 1, f"Expected 1 critique event; got {len(events)}"
        ev = events[0]
        assert ev["severity"] == "high"
        assert ev["status"] == "open"
        assert ev["critic_id"] == "endpoint-coverage-checker"

    def test_run_demo_critique_rounds_incremented(self, tmp_path: Path) -> None:
        """critiqueRounds == 1 after run_demo fires one critique."""
        summary = run_demo(tmp_path / "run")
        assert summary["critique_rounds"] == 1


# ---------------------------------------------------------------------------
# Test: full-coverage variant — no critique
# ---------------------------------------------------------------------------


class TestRunDemoFullCoverage:
    """Monkeypatch so the skill_use covers BOTH high endpoints.

    We do this by calling ik_acquire directly with a minimal endpoint_index
    containing only 'bulkOperationRunQuery' as high, plus a second skill_use
    emit that covers 'Customer.numberOfOrders', then running check_coverage_from_run.
    This exercises the same code path that test_e2e_full_coverage_no_critique_needed
    uses in test_coverage_e2e.py.
    """

    def test_full_coverage_no_critique(self, tmp_path: Path) -> None:
        """When both high-relevance endpoints are covered, coverage passes and no
        critique is fired."""
        run_dir = tmp_path / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        state = RunState()

        search_results = load_search_results()
        extraction_result = sample_extraction_result()

        # Index with exactly the two high endpoints
        ei = _full_coverage_endpoint_index()

        # First acquire: skill_use covers bulkOperationRunQuery
        result = ik_acquire(
            research_id="RES-META-SHOPIFY-FC-001",
            skill_use_id="SKU-META-SHOPIFY-FC-001",
            claim_id="ATFC-D-001",
            api_search_result=search_results,
            api_extraction_result=extraction_result,
            claim_fields={"total_orders": 5, "new_vs_returning_known": True},
            research_query="shopify bulkOperationRunQuery + Customer.numberOfOrders",
            research_source="shopify.dev/assistant/search",
            skill_use_tool="shopify-admin-graphql",
            skill_use_source="bulkOperationRunQuery",
            claim_tier="draft",
            endpoint_index=ei,
            run_state=state,
            run_dir=run_dir,
        )

        # Second skill_use: covers Customer.numberOfOrders, cites SAME research bundle
        ik_skill_use_emit(
            "SKU-META-SHOPIFY-FC-002",
            "api-extract:SKU-META-SHOPIFY-FC-002",
            "shopify-admin-graphql",
            "Customer.numberOfOrders",
            snapshot={
                "extraction_tool": "shopify-admin-graphql",
                "skill_use_source": "Customer.numberOfOrders",
                "synthetic": True,
                "customer_order_counts": [
                    {"customer_id": "cust_demo_1", "numberOfOrders": 3},
                    {"customer_id": "cust_demo_2", "numberOfOrders": 1},
                    {"customer_id": "cust_demo_3", "numberOfOrders": 1},
                ],
            },
            cites=[result.research_ref.record_id],
            run_state=state,
            run_dir=run_dir,
        )

        # Coverage check scoped to the research bundle
        cov = check_coverage_from_run(
            run_dir,
            result.research_ref.record_id,
            claim_id=result.claim_id,
        )

        assert cov.passed is True, (
            f"Full-coverage case must pass; missed: {cov.missed_high_endpoints!r}"
        )
        assert cov.missed_high_endpoints == []
        # No critique fired → critique.jsonl does not exist
        critique_path = (
            run_dir
            / "records"
            / result.claim_ref.record_id
            / "events"
            / "critique.jsonl"
        )
        assert not critique_path.exists(), (
            "critique.jsonl must not be written when coverage passes"
        )


# ---------------------------------------------------------------------------
# Test: distill_endpoint_index unit tests
# ---------------------------------------------------------------------------


class TestDistillEndpointIndex:
    def test_distill_returns_dict(self) -> None:
        """distill_endpoint_index returns a dict with 'available_endpoints'."""
        results = load_search_results()
        idx = distill_endpoint_index(results)
        assert isinstance(idx, dict)
        assert "available_endpoints" in idx

    def test_distill_both_high_endpoints_present(self) -> None:
        """Both bulkOperationRunQuery and Customer.numberOfOrders are in the index."""
        results = load_search_results()
        idx = distill_endpoint_index(results)
        eps = idx["available_endpoints"]
        ep_ids = {ep.get("endpoint") or ep.get("id") for ep in eps}
        assert "bulkOperationRunQuery" in ep_ids, (
            f"bulkOperationRunQuery missing from index; got {ep_ids!r}"
        )
        assert "Customer.numberOfOrders" in ep_ids, (
            f"Customer.numberOfOrders missing from index; got {ep_ids!r}"
        )

    def test_distill_both_high_endpoints_marked_high(self) -> None:
        """Both attribution-critical endpoints have relevance='high'."""
        results = load_search_results()
        idx = distill_endpoint_index(results)
        eps = {
            (ep.get("endpoint") or ep.get("id")): ep.get("relevance")
            for ep in idx["available_endpoints"]
        }
        assert eps.get("bulkOperationRunQuery") == "high", (
            f"bulkOperationRunQuery must be high; got {eps!r}"
        )
        assert eps.get("Customer.numberOfOrders") == "high", (
            f"Customer.numberOfOrders must be high; got {eps!r}"
        )

    def test_distill_other_endpoints_not_high(self) -> None:
        """Endpoints other than the two attribution-critical ones are medium."""
        results = load_search_results()
        idx = distill_endpoint_index(results)
        high_set = {"bulkOperationRunQuery", "Customer.numberOfOrders"}
        for ep in idx["available_endpoints"]:
            ep_id = ep.get("endpoint") or ep.get("id")
            if ep_id not in high_set:
                assert ep.get("relevance") == "medium", (
                    f"Non-critical endpoint {ep_id!r} must be medium; got {ep!r}"
                )

    def test_distill_empty_results_bulk_fallback(self) -> None:
        """distill_endpoint_index with empty query_results still includes
        bulkOperationRunQuery via the safety-net fallback."""
        idx = distill_endpoint_index({"query_results": {}})
        ep_ids = {ep.get("endpoint") or ep.get("id") for ep in idx["available_endpoints"]}
        assert "bulkOperationRunQuery" in ep_ids

    def test_distill_empty_results_no_customer_endpoint(self) -> None:
        """Customer.numberOfOrders is NOT in the index when query_results is empty.

        It has no unconditional fallback — its presence proves discovery from
        real hit content (a hit whose content contains 'numberOfOrders' and
        whose URL is in the customers/Customer doc area).
        """
        idx = distill_endpoint_index({"query_results": {}})
        ep_ids = {ep.get("endpoint") or ep.get("id") for ep in idx["available_endpoints"]}
        assert "Customer.numberOfOrders" not in ep_ids, (
            "Customer.numberOfOrders must NOT appear when no hits surface it; "
            f"got {ep_ids!r}"
        )

    def test_distill_customer_endpoint_discovered_from_hits(self) -> None:
        """Customer.numberOfOrders is discovered from hit content, not hardcoded.

        Removing the search_customer_orders hits from the results drops
        Customer.numberOfOrders from the index.
        """
        results = load_search_results()
        # Strip the hits that contain the customers/numberOfOrders doc
        stripped = copy.deepcopy(results)
        stripped["query_results"].pop("search_customer_orders", None)
        idx = distill_endpoint_index(stripped)
        ep_ids = {ep.get("endpoint") or ep.get("id") for ep in idx["available_endpoints"]}
        assert "Customer.numberOfOrders" not in ep_ids, (
            "Customer.numberOfOrders must not appear when the customers hits "
            f"are absent; got {ep_ids!r}"
        )

    def test_distill_customer_endpoint_present_when_hits_present(self) -> None:
        """Customer.numberOfOrders IS in the index when full fixtures are loaded.

        This is the companion to test_distill_customer_endpoint_discovered_from_hits:
        the same hit that was stripped above, when present, causes discovery.
        """
        results = load_search_results()
        idx = distill_endpoint_index(results)
        ep_ids = {ep.get("endpoint") or ep.get("id") for ep in idx["available_endpoints"]}
        assert "Customer.numberOfOrders" in ep_ids, (
            f"Customer.numberOfOrders must be discovered from fixture hits; "
            f"got {ep_ids!r}"
        )


# ---------------------------------------------------------------------------
# Test: sample_extraction_result sanity
# ---------------------------------------------------------------------------


class TestSampleExtractionResult:
    def test_sample_extraction_synthetic_flag(self) -> None:
        """sample_extraction_result has synthetic=True (no real data)."""
        result = sample_extraction_result()
        assert result.get("synthetic") is True

    def test_sample_extraction_no_real_customer_ids(self) -> None:
        """All customer_id values start with 'cust_demo_' (clearly synthetic)."""
        result = sample_extraction_result()
        for order in result.get("shopify_orders", []):
            cid = order.get("customer_id", "")
            assert cid.startswith("cust_demo_"), (
                f"customer_id {cid!r} does not look synthetic"
            )

    def test_sample_extraction_no_real_adset_ids(self) -> None:
        """All adset_id values start with 'demo_' (clearly synthetic)."""
        result = sample_extraction_result()
        for row in result.get("meta_adset_daily", []):
            aid = row.get("adset_id", "")
            assert aid.startswith("demo_"), (
                f"adset_id {aid!r} does not look synthetic"
            )

    def test_sample_extraction_skill_use_source_is_bulk(self) -> None:
        """skill_use_source is 'bulkOperationRunQuery' (the endpoint actually used)."""
        result = sample_extraction_result()
        assert result["skill_use_source"] == "bulkOperationRunQuery"

    def test_sample_extraction_customer_order_counts_null(self) -> None:
        """customer_order_counts is None — the coverage gap we're demonstrating."""
        result = sample_extraction_result()
        assert result["customer_order_counts"] is None


# ---------------------------------------------------------------------------
# Test: --live-extract flag (FIX 1) — cred-gated, CI-safe
# ---------------------------------------------------------------------------


class TestLiveExtractFlag:
    def test_run_demo_live_extract_raises_without_creds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_demo(live_extract=True) raises NotImplementedError when
        META_TOKEN and SHOPIFY_TOKEN are absent from os.environ.

        This test verifies that the --live-extract flag is wired into run_demo
        and that the cred-gating works correctly.  CI never sets these env vars
        so the code path is dead in automated runs.
        """
        monkeypatch.delenv("META_TOKEN", raising=False)
        monkeypatch.delenv("SHOPIFY_TOKEN", raising=False)
        with pytest.raises(NotImplementedError, match="extract_g4f7_attribution"):
            run_demo(tmp_path / "run", live_extract=True)

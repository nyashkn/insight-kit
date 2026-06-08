"""T31/T32 end-to-end: endpoint_index wired into acquire + derive_used_endpoints.

Tests cover:
  - ik_acquire with endpoint_index param persists endpoint_index.json under the
    research record bundle (T31 production path).
  - derive_used_endpoints scans emitted skill_use records and returns their
    .source values as a set.
  - check_coverage_from_run (convenience) wires the two helpers into
    check_endpoint_coverage_gap for a fully end-to-end critic run.
  - Missed high-relevance endpoint detected → critique persisted (T32 E2E).
  - Full-coverage case → no critique, passed=True.
  - Backward compatibility: ik_acquire without endpoint_index param works as
    before (no endpoint_index.json written, existing tests unaffected).

Cites: T31, T32, V16, T27, V20, I.cites.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.platform.gate.acquire import AcquireResult, ik_acquire
from insight_kit.platform.gate.runcheck import (
    check_coverage_from_run,
    derive_used_endpoints,
)
from insight_kit.platform.gate.runstate import (
    CritiqueState,
    RunState,
    apply_critique,
)
from insight_kit.platform.gate.store import (
    endpoint_index_path,
    read_endpoint_index,
)

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

TS = "2026-06-09T10:00:00+00:00"

SEARCH_RESULT = {
    "query": "shopify orders api endpoints",
    "results": [{"url": "https://shopify.dev/docs/api/admin-rest/orders", "snippet": "..."}],
    "timestamp": TS,
}

EXTRACTION_RESULT_ORDERS_LIST = {
    "tool": "shopify-rest-extractor",
    "endpoint": "orders.listOrders",
    "fields_extracted": {"order_count": 42},
    "timestamp": TS,
}

EXTRACTION_RESULT_ORDERS_GET = {
    "tool": "shopify-rest-extractor",
    "endpoint": "orders.getOrder",
    "fields_extracted": {"order_id": "gid://shopify/Order/123"},
    "timestamp": TS,
}

EXTRACTION_RESULT_PRODUCTS_ONLY = {
    "tool": "shopify-rest-extractor",
    "endpoint": "products.list",
    "fields_extracted": {"product_count": 10},
    "timestamp": TS,
}

CLAIM_FIELDS = {"order_count": 42}

# Endpoint index: two high-relevance + one medium
ENDPOINT_INDEX = {
    "available_endpoints": [
        {"id": "orders.listOrders", "relevance": "high", "why": "primary revenue source"},
        {"id": "orders.getOrder", "relevance": "high", "why": "detail view"},
        {"id": "products.list", "relevance": "medium", "why": "catalogue"},
    ]
}


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


def _acquire(run_dir: Path, state: RunState, **overrides) -> AcquireResult:
    """Call ik_acquire with sensible defaults; overrides forwarded."""
    kwargs: dict = dict(
        research_id="RES-E2E-001",
        skill_use_id="SKU-E2E-001",
        claim_id="TEST-D-001",
        api_search_result=SEARCH_RESULT,
        api_extraction_result=EXTRACTION_RESULT_ORDERS_LIST,
        claim_fields=CLAIM_FIELDS,
        research_query="shopify orders api endpoints",
        research_source="shopify-dev-docs",
        research_timestamp=TS,
        skill_use_tool="shopify-rest-extractor",
        skill_use_source="orders.listOrders",
        skill_use_timestamp=TS,
        run_state=state,
        run_dir=run_dir,
    )
    kwargs.update(overrides)
    return ik_acquire(**kwargs)


# ---------------------------------------------------------------------------
# GAP-1 (T31): endpoint_index wired into ik_acquire
# ---------------------------------------------------------------------------


class TestAcquireWithEndpointIndex:
    def test_acquire_writes_endpoint_index_json(self, run_dir, state):
        """ik_acquire with endpoint_index persists endpoint_index.json in the research bundle."""
        result = _acquire(run_dir, state, endpoint_index=ENDPOINT_INDEX)
        ei_path = endpoint_index_path(run_dir, result.research_ref.record_id)
        assert ei_path.exists(), "endpoint_index.json must be written alongside research snapshot"

    def test_acquire_endpoint_index_content_round_trips(self, run_dir, state):
        """Written endpoint_index.json deserializes back to the original dict."""
        result = _acquire(run_dir, state, endpoint_index=ENDPOINT_INDEX)
        ei = read_endpoint_index(run_dir, result.research_ref.record_id)
        assert ei == ENDPOINT_INDEX

    def test_acquire_without_endpoint_index_writes_nothing(self, run_dir, state):
        """ik_acquire without endpoint_index param does NOT write endpoint_index.json (backward compat)."""
        result = _acquire(run_dir, state)  # no endpoint_index kwarg
        ei_path = endpoint_index_path(run_dir, result.research_ref.record_id)
        assert not ei_path.exists(), "No endpoint_index.json should be written when param is None"

    def test_acquire_endpoint_index_none_writes_nothing(self, run_dir, state):
        """Explicit endpoint_index=None has same effect as omitting the param."""
        result = _acquire(run_dir, state, endpoint_index=None)
        ei_path = endpoint_index_path(run_dir, result.research_ref.record_id)
        assert not ei_path.exists()

    def test_acquire_endpoint_index_does_not_affect_claim_cites(self, run_dir, state):
        """Providing endpoint_index does not change cites edges or record structure."""
        result = _acquire(run_dir, state, endpoint_index=ENDPOINT_INDEX)
        claim_rec = json.loads(
            (run_dir / "records" / result.claim_ref.record_id / "record.json").read_text()
        )
        assert claim_rec["cites"] == [
            result.research_ref.record_id,
            result.skill_use_ref.record_id,
        ]

    def test_acquire_endpoint_index_three_records_emitted(self, run_dir, state):
        """endpoint_index param does not emit extra records — still 3."""
        _acquire(run_dir, state, endpoint_index=ENDPOINT_INDEX)
        assert len(state.records) == 3

    def test_acquire_endpoint_index_immutable_on_second_acquire(self, run_dir, state):
        """Second ik_acquire call with same research content raises record-duplicate,
        endpoint_index.json is not double-written (V3 / immutability guard)."""
        from insight_kit.libs.validation import ValidationError as LayerAValidationError

        _acquire(run_dir, state, endpoint_index=ENDPOINT_INDEX)
        # Second call with same content → record-duplicate error from research emit
        with pytest.raises(LayerAValidationError) as exc:
            _acquire(
                run_dir,
                state,
                claim_id="TEST-D-002",
                endpoint_index=ENDPOINT_INDEX,
            )
        assert exc.value.rule_id == "record-duplicate"


# ---------------------------------------------------------------------------
# GAP-2 (T32): derive_used_endpoints scans real skill_use records
# ---------------------------------------------------------------------------


class TestDeriveUsedEndpoints:
    def test_derive_used_endpoints_returns_set(self, run_dir, state):
        """derive_used_endpoints returns a set."""
        _acquire(run_dir, state, skill_use_source="orders.listOrders")
        result = derive_used_endpoints(run_dir)
        assert isinstance(result, set)

    def test_derive_used_endpoints_finds_skill_use_source(self, run_dir, state):
        """derive_used_endpoints picks up skill_use_source from the emitted record."""
        _acquire(run_dir, state, skill_use_source="orders.listOrders")
        result = derive_used_endpoints(run_dir)
        assert "orders.listOrders" in result

    def test_derive_used_endpoints_multiple_skill_uses(self, run_dir, state):
        """Multiple skill_use records → all their sources in the returned set."""
        _acquire(
            run_dir,
            state,
            research_id="RES-E2E-MUL-001",
            skill_use_id="SKU-E2E-MUL-001",
            claim_id="TEST-D-001",
            api_search_result={**SEARCH_RESULT, "tag": "mul-1"},
            api_extraction_result={**EXTRACTION_RESULT_ORDERS_LIST, "tag": "mul-1"},
            skill_use_source="orders.listOrders",
        )
        _acquire(
            run_dir,
            state,
            research_id="RES-E2E-MUL-002",
            skill_use_id="SKU-E2E-MUL-002",
            claim_id="TEST-D-002",
            api_search_result={**SEARCH_RESULT, "tag": "mul-2"},
            api_extraction_result={**EXTRACTION_RESULT_ORDERS_GET, "tag": "mul-2"},
            skill_use_source="orders.getOrder",
        )
        result = derive_used_endpoints(run_dir)
        assert "orders.listOrders" in result
        assert "orders.getOrder" in result

    def test_derive_used_endpoints_excludes_non_skill_use_records(self, run_dir, state):
        """Research and claim records do not contribute to the used-set."""
        result_a = _acquire(run_dir, state, skill_use_source="orders.listOrders")
        used = derive_used_endpoints(run_dir)
        # research and claim have no 'source' field → should not add noise
        # only 1 distinct source
        assert used == {"orders.listOrders"}
        _ = result_a

    def test_derive_used_endpoints_empty_run_dir(self, run_dir):
        """Empty run_dir (no records/) → empty set, no error."""
        result = derive_used_endpoints(run_dir)
        assert result == set()

    def test_derive_used_endpoints_no_skill_use_records(self, run_dir, state):
        """Run with only research+claim (no skill_use) → empty set."""
        from insight_kit.platform.gate.emit import ik_claim_emit, ik_research_emit

        ik_research_emit(
            "RES-NOSUB-001",
            "https://api.example.com/docs",
            "test query",
            "perplexity",
            snapshot={"docs": ["x"]},
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
        )
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        result = derive_used_endpoints(run_dir)
        assert result == set()


# ---------------------------------------------------------------------------
# E2E: missed high-relevance endpoint → critique persisted (T32 full path)
# ---------------------------------------------------------------------------


class TestCoverageE2EMissedHigh:
    def test_e2e_missed_high_critique_fired_and_persisted(self, run_dir, state):
        """Full E2E: acquire with endpoint_index, skill_use only uses medium endpoint,
        derive_used_endpoints sees only 'products.list', coverage check detects miss,
        critique is fired and persisted to critique.jsonl."""
        # Step 1: acquire — research with endpoint_index, skill_use on medium endpoint only
        result = _acquire(
            run_dir,
            state,
            endpoint_index=ENDPOINT_INDEX,
            skill_use_source="products.list",
            api_extraction_result={**EXTRACTION_RESULT_PRODUCTS_ONLY},
        )

        # Step 2: derive used set from emitted skill_use records
        used = derive_used_endpoints(run_dir)
        assert used == {"products.list"}

        # Step 3: run coverage check
        from insight_kit.platform.gate.store import read_endpoint_index
        from insight_kit.platform.gate.runcheck import check_endpoint_coverage_gap

        ei = read_endpoint_index(run_dir, result.research_ref.record_id)
        cov_result = check_endpoint_coverage_gap(
            ei, list(used), claim_id=result.claim_ref.record_id
        )
        assert cov_result.passed is False
        assert "orders.listOrders" in cov_result.missed_high_endpoints
        assert "orders.getOrder" in cov_result.missed_high_endpoints

        # Step 4: fire critique on the claim record
        critique = CritiqueState.open(
            severity="high",
            reason=cov_result.message,
            critic_id="endpoint-coverage-checker",
            target_record_id=result.claim_ref.record_id,
        )
        gate_result = apply_critique(
            run_state=state,
            record_id=result.claim_ref.record_id,
            record_type="claim",
            tier="draft",
            audience=None,
            critique=critique,
            run_dir=run_dir,
        )
        assert gate_result["downgraded"] is False
        assert gate_result["tier"] == "draft"

        # Step 5: assert critique persisted on disk
        critique_path = (
            run_dir / "records" / result.claim_ref.record_id / "events" / "critique.jsonl"
        )
        assert critique_path.exists(), "critique.jsonl must be written"
        events = [
            json.loads(line)
            for line in critique_path.read_text().splitlines()
            if line.strip()
        ]
        assert len(events) == 1
        ev = events[0]
        assert ev["severity"] == "high"
        assert ev["status"] == "open"
        assert ev["critic_id"] == "endpoint-coverage-checker"

    def test_e2e_missed_high_via_check_coverage_from_run(self, run_dir, state):
        """check_coverage_from_run convenience method produces the same result
        as the three-step manual version."""
        result = _acquire(
            run_dir,
            state,
            endpoint_index=ENDPOINT_INDEX,
            skill_use_source="products.list",
            api_extraction_result={**EXTRACTION_RESULT_PRODUCTS_ONLY},
        )

        cov = check_coverage_from_run(
            run_dir,
            result.research_ref.record_id,
            claim_id=result.claim_ref.record_id,
        )
        assert cov.passed is False
        assert set(cov.missed_high_endpoints) == {"orders.listOrders", "orders.getOrder"}


# ---------------------------------------------------------------------------
# E2E: full-coverage case → no critique
# ---------------------------------------------------------------------------


class TestCoverageE2EFullCoverage:
    def test_e2e_full_coverage_no_critique_needed(self, run_dir, state):
        """Full E2E: acquire with endpoint_index, two skill_use records covering all
        high-relevance endpoints → check passes, no critique fired."""
        # Acquire chain 1: skill_use for orders.listOrders
        result = _acquire(
            run_dir,
            state,
            research_id="RES-E2E-FC-001",
            skill_use_id="SKU-E2E-FC-001",
            claim_id="TEST-D-001",
            api_search_result={**SEARCH_RESULT, "chain": "FC-1"},
            api_extraction_result={**EXTRACTION_RESULT_ORDERS_LIST, "chain": "FC-1"},
            skill_use_source="orders.listOrders",
            endpoint_index=ENDPOINT_INDEX,
        )

        # Acquire chain 2: skill_use for orders.getOrder (second high-relevance)
        _acquire(
            run_dir,
            state,
            research_id="RES-E2E-FC-002",
            skill_use_id="SKU-E2E-FC-002",
            claim_id="TEST-D-002",
            api_search_result={**SEARCH_RESULT, "chain": "FC-2"},
            api_extraction_result={**EXTRACTION_RESULT_ORDERS_GET, "chain": "FC-2"},
            skill_use_source="orders.getOrder",
        )

        # Both high-relevance endpoints are now in the used set
        used = derive_used_endpoints(run_dir)
        assert "orders.listOrders" in used
        assert "orders.getOrder" in used

        # Coverage check uses the first chain's endpoint_index
        cov = check_coverage_from_run(
            run_dir,
            result.research_ref.record_id,
            claim_id=result.claim_ref.record_id,
        )
        assert cov.passed is True
        assert cov.missed_high_endpoints == []

        # No critique rounds incremented
        assert state.critiqueRounds == 0

    def test_e2e_full_coverage_no_critique_jsonl(self, run_dir, state):
        """Full coverage → critique.jsonl not written (no apply_critique called)."""
        result = _acquire(
            run_dir,
            state,
            research_id="RES-E2E-NoCrit-001",
            skill_use_id="SKU-E2E-NoCrit-001",
            claim_id="TEST-D-001",
            api_search_result={**SEARCH_RESULT, "chain": "NC-1"},
            api_extraction_result={**EXTRACTION_RESULT_ORDERS_LIST, "chain": "NC-1"},
            skill_use_source="orders.listOrders",
            endpoint_index={
                "available_endpoints": [
                    {"id": "orders.listOrders", "relevance": "high", "why": "primary"},
                ]
            },
        )

        cov = check_coverage_from_run(
            run_dir,
            result.research_ref.record_id,
            claim_id=result.claim_ref.record_id,
        )
        assert cov.passed is True

        critique_path = (
            run_dir / "records" / result.claim_ref.record_id / "events" / "critique.jsonl"
        )
        # No critique fired → file should not exist
        assert not critique_path.exists()

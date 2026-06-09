"""T32 — check_endpoint_coverage_gap: Layer-B/C critic coverage check (V16).

Verifies:
  - Pure-fn: full coverage → passed=True, missed_high_endpoints=[].
  - Pure-fn: missed high-relevance endpoints → passed=False, correct missed list.
  - None endpoint_index → passed=True (no denominator, no gate).
  - Missing 'available_endpoints' key → passed=True (treated as empty).
  - No high-relevance endpoints in index → passed=True (nothing to miss).
  - used_endpoints=[] with high-relevance available → passed=False.
  - used_endpoints is a superset (extra endpoints beyond index) → passed=True
    when all high-relevance are covered.
  - Integration: emit research+endpoint_index, emit skill_use, extract data,
    call check_endpoint_coverage_gap → result matches expected coverage state.
  - Missed high-relevance endpoints → caller can fire CritiqueState.open
    via apply_critique (V16, T27).
  - Public __init__ exports are present and callable.

Cites: T32, V16, T27, V20, I.runcheck, I.cites.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.platform.gate import (
    CheckEndpointCoverageResult,
    check_endpoint_coverage_gap,
)
from insight_kit.platform.gate.emit import ik_research_emit, ik_skill_use_emit
from insight_kit.platform.gate.runstate import (
    CritiqueGateError,
    CritiqueState,
    RunState,
    apply_critique,
)
from insight_kit.platform.gate.store import (
    read_endpoint_index,
    write_endpoint_index,
)

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

TS = "2026-06-09T12:00:00+00:00"

# Endpoint index with two high-relevance + one medium + one low
ENDPOINT_INDEX_MIXED = {
    "available_endpoints": [
        {"id": "orders.listOrders", "relevance": "high", "why": "primary revenue source"},
        {"id": "orders.getOrder", "relevance": "high", "why": "detail view"},
        {"id": "products.list", "relevance": "medium", "why": "catalogue"},
        {"id": "inventory.levels", "relevance": "low", "why": "rarely needed"},
    ]
}

# Endpoint index with only medium/low relevance
ENDPOINT_INDEX_NO_HIGH = {
    "available_endpoints": [
        {"id": "health.check", "relevance": "medium", "why": "status"},
        {"id": "debug.info", "relevance": "low", "why": "diagnostics"},
    ]
}

SNAPSHOT = {"docs": ["orders-api"], "n": 1}


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


# ---------------------------------------------------------------------------
# Pure-fn: full coverage
# ---------------------------------------------------------------------------


class TestCheckEndpointCoverageGapPureFn:
    def test_full_coverage_passes(self):
        """All high-relevance endpoints covered → passed=True, no missed."""
        result = check_endpoint_coverage_gap(
            ENDPOINT_INDEX_MIXED,
            ["orders.listOrders", "orders.getOrder"],
            claim_id="CLM-001",
        )
        assert result.passed is True
        assert result.missed_high_endpoints == []
        assert result.available_high_count == 2
        assert result.used_endpoint_count == 2

    def test_full_coverage_includes_extra_endpoints(self):
        """used_endpoints has endpoints beyond the index — extra ignored, still passes."""
        result = check_endpoint_coverage_gap(
            ENDPOINT_INDEX_MIXED,
            ["orders.listOrders", "orders.getOrder", "some.other.endpoint"],
            claim_id="CLM-002",
        )
        assert result.passed is True
        assert result.missed_high_endpoints == []
        assert result.available_high_count == 2
        # used_endpoint_count counts uniques in used_endpoints
        assert result.used_endpoint_count == 3

    def test_missed_high_endpoints_fails(self):
        """Missed high-relevance endpoints → passed=False, correct missed list."""
        result = check_endpoint_coverage_gap(
            ENDPOINT_INDEX_MIXED,
            ["products.list"],  # only medium, no high-relevance used
            claim_id="CLM-003",
        )
        assert result.passed is False
        assert set(result.missed_high_endpoints) == {"orders.listOrders", "orders.getOrder"}
        assert result.available_high_count == 2
        assert result.used_endpoint_count == 1

    def test_partial_missed_high(self):
        """Only one of two high-relevance endpoints used → one missed."""
        result = check_endpoint_coverage_gap(
            ENDPOINT_INDEX_MIXED,
            ["orders.listOrders"],
            claim_id="CLM-004",
        )
        assert result.passed is False
        assert result.missed_high_endpoints == ["orders.getOrder"]
        assert result.available_high_count == 2

    def test_used_endpoints_empty_with_high_available_fails(self):
        """used_endpoints=[] with high-relevance available → passed=False, all high missed."""
        result = check_endpoint_coverage_gap(
            ENDPOINT_INDEX_MIXED,
            [],
            claim_id="CLM-005",
        )
        assert result.passed is False
        assert set(result.missed_high_endpoints) == {"orders.listOrders", "orders.getOrder"}
        assert result.used_endpoint_count == 0

    def test_medium_low_not_flagged(self):
        """Medium and low relevance endpoints not in missed list when uncovered."""
        result = check_endpoint_coverage_gap(
            ENDPOINT_INDEX_MIXED,
            ["orders.listOrders", "orders.getOrder"],  # only high-relevance covered
            claim_id="CLM-006",
        )
        # products.list (medium) and inventory.levels (low) are not in missed
        assert result.passed is True
        assert "products.list" not in result.missed_high_endpoints
        assert "inventory.levels" not in result.missed_high_endpoints

    def test_no_high_relevance_in_index_passes(self):
        """Index has no high-relevance entries → passed=True (nothing to miss)."""
        result = check_endpoint_coverage_gap(
            ENDPOINT_INDEX_NO_HIGH,
            [],
            claim_id="CLM-007",
        )
        assert result.passed is True
        assert result.missed_high_endpoints == []
        assert result.available_high_count == 0

    def test_none_endpoint_index_passes(self):
        """None endpoint_index → passed=True (no denominator, no gate)."""
        result = check_endpoint_coverage_gap(
            None,
            ["orders.listOrders"],
            claim_id="CLM-008",
        )
        assert result.passed is True
        assert result.missed_high_endpoints == []
        assert result.available_high_count == 0

    def test_missing_available_endpoints_key_passes(self):
        """endpoint_index without 'available_endpoints' key → passed=True."""
        result = check_endpoint_coverage_gap(
            {"metadata": "some info"},  # no 'available_endpoints'
            ["orders.listOrders"],
            claim_id="CLM-009",
        )
        assert result.passed is True
        assert result.missed_high_endpoints == []

    def test_empty_available_endpoints_list_passes(self):
        """endpoint_index with empty available_endpoints list → passed=True."""
        result = check_endpoint_coverage_gap(
            {"available_endpoints": []},
            ["orders.listOrders"],
            claim_id="CLM-010",
        )
        assert result.passed is True

    def test_returns_check_endpoint_coverage_result_instance(self):
        """Return type is CheckEndpointCoverageResult."""
        result = check_endpoint_coverage_gap(None, [])
        assert isinstance(result, CheckEndpointCoverageResult)

    def test_message_contains_missed_endpoint_ids(self):
        """Message string describes missed endpoints."""
        result = check_endpoint_coverage_gap(
            ENDPOINT_INDEX_MIXED,
            [],
            claim_id="CLM-MSG-001",
        )
        assert result.passed is False
        assert "orders.listOrders" in result.message or "orders.getOrder" in result.message

    def test_message_passed_contains_covered_count(self):
        """Passing result message notes coverage."""
        result = check_endpoint_coverage_gap(
            ENDPOINT_INDEX_MIXED,
            ["orders.listOrders", "orders.getOrder"],
            claim_id="CLM-MSG-002",
        )
        assert result.passed is True
        assert "2" in result.message  # 2 high-relevance covered

    def test_claim_id_optional(self):
        """claim_id is optional — function works without it."""
        result = check_endpoint_coverage_gap(ENDPOINT_INDEX_MIXED, [])
        assert result.passed is False  # missed high endpoints

    def test_endpoint_fallback_to_endpoint_key(self):
        """Endpoint id falls back to 'endpoint' key when 'id' key missing."""
        index = {
            "available_endpoints": [
                {"endpoint": "/v1/orders", "relevance": "high"},
            ]
        }
        result = check_endpoint_coverage_gap(index, ["/v1/orders"])
        assert result.passed is True
        assert result.missed_high_endpoints == []

    def test_endpoint_fallback_to_name_key(self):
        """Endpoint id falls back to 'name' key when 'id' and 'endpoint' missing."""
        index = {
            "available_endpoints": [
                {"name": "listOrders", "relevance": "high"},
            ]
        }
        result = check_endpoint_coverage_gap(index, ["listOrders"])
        assert result.passed is True


# ---------------------------------------------------------------------------
# Integration: emit research + endpoint_index, emit skill_use, check coverage
# ---------------------------------------------------------------------------


class TestCheckEndpointCoverageGapIntegration:
    def test_integration_full_coverage(self, run_dir, state):
        """Emit research+endpoint_index, emit skill_use covering all high-relevance → passed."""
        # Emit research record
        res_ref = ik_research_emit(
            "RES-T32-001",
            "https://api.example.com/docs",
            "what order endpoints are available",
            "perplexity",
            snapshot=SNAPSHOT,
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
        )
        # Write endpoint_index alongside the research record
        write_endpoint_index(run_dir, res_ref.record_id, ENDPOINT_INDEX_MIXED)

        # Emit skill_use records for both high-relevance endpoints
        # ik_skill_use_emit(skill_use_id, snapshot_ref, tool, source, *, snapshot, ...)
        ik_skill_use_emit(
            "SKU-T32-001",
            "orders-api",
            "orders-client",
            "orders.listOrders",
            snapshot={"result": []},
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
            cites=[res_ref.record_id],
        )
        ik_skill_use_emit(
            "SKU-T32-002",
            "orders-api",
            "orders-client",
            "orders.getOrder",
            snapshot={"result": {}},
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
            cites=[res_ref.record_id],
        )

        # Retrieve endpoint_index and call check
        ei = read_endpoint_index(run_dir, res_ref.record_id)
        result = check_endpoint_coverage_gap(
            ei,
            ["orders.listOrders", "orders.getOrder"],
            claim_id="CLM-T32-001",
        )
        assert result.passed is True
        assert result.missed_high_endpoints == []
        assert result.available_high_count == 2

    def test_integration_missed_high(self, run_dir, state):
        """Emit research+endpoint_index, skill_use only uses medium endpoint → missed high."""
        res_ref = ik_research_emit(
            "RES-T32-002",
            "https://api.example.com/docs",
            "what endpoints are available",
            "perplexity",
            snapshot=SNAPSHOT,
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
        )
        write_endpoint_index(run_dir, res_ref.record_id, ENDPOINT_INDEX_MIXED)

        # Only use a medium-relevance endpoint
        # ik_skill_use_emit(skill_use_id, snapshot_ref, tool, source, *, snapshot, ...)
        ik_skill_use_emit(
            "SKU-T32-003",
            "products-api",
            "product-lister",
            "products.list",
            snapshot={"result": []},
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
            cites=[res_ref.record_id],
        )

        ei = read_endpoint_index(run_dir, res_ref.record_id)
        result = check_endpoint_coverage_gap(
            ei,
            ["products.list"],
            claim_id="CLM-T32-002",
        )
        assert result.passed is False
        assert set(result.missed_high_endpoints) == {"orders.listOrders", "orders.getOrder"}

    def test_integration_no_endpoint_index_written_returns_none(self, run_dir, state):
        """Research record without endpoint_index → read_endpoint_index returns None → passed=True."""
        res_ref = ik_research_emit(
            "RES-T32-003",
            "https://api.example.com/docs",
            "some query",
            "perplexity",
            snapshot=SNAPSHOT,
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
        )

        ei = read_endpoint_index(run_dir, res_ref.record_id)
        assert ei is None

        result = check_endpoint_coverage_gap(ei, [], claim_id="CLM-T32-003")
        assert result.passed is True


# ---------------------------------------------------------------------------
# V16 critique integration: missed high → apply_critique ready
# ---------------------------------------------------------------------------


class TestCheckEndpointCoverageGapCritiqueIntegration:
    def test_missed_high_triggers_critique_persisted(self, run_dir, state):
        """Missed high-relevance endpoints → caller fires apply_critique → event persisted (V16, T27)."""
        # Emit a research record and a claim record to critique
        from insight_kit.platform.gate.emit import ik_claim_emit

        res_ref = ik_research_emit(
            "RES-T32-C01",
            "https://api.example.com/docs",
            "endpoint coverage test",
            "perplexity",
            snapshot=SNAPSHOT,
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
        )
        write_endpoint_index(run_dir, res_ref.record_id, ENDPOINT_INDEX_MIXED)

        claim_ref = ik_claim_emit(
            "TEST-D-001",
            {"value": (100, "d")},
            run_state=state,
            run_dir=run_dir,
            cites=[res_ref.record_id],
        )

        # Derive used endpoints from skill_use.source (simulated here as a list)
        used = ["products.list"]  # only medium used — missed 2 high
        ei = read_endpoint_index(run_dir, res_ref.record_id)

        cov_result = check_endpoint_coverage_gap(
            ei, used, claim_id=claim_ref.record_id
        )
        assert cov_result.passed is False

        # Caller fires a critique (V16 gate — draft claim, so no CritiqueGateError)
        critique = CritiqueState.open(
            severity="high",
            reason=cov_result.message,
            critic_id="endpoint-coverage-checker",
            target_record_id=claim_ref.record_id,
        )
        gate_result = apply_critique(
            run_state=state,
            record_id=claim_ref.record_id,
            record_type="claim",
            tier="draft",  # draft — no gate fire
            audience=None,
            critique=critique,
            run_dir=run_dir,
        )
        assert gate_result["downgraded"] is False
        assert gate_result["tier"] == "draft"

        # Verify event was persisted on disk (T27)
        events_path = run_dir / "records" / claim_ref.record_id / "events" / "critique.jsonl"
        assert events_path.exists()
        import json
        events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
        assert len(events) == 1
        ev = events[0]
        assert ev["severity"] == "high"
        assert ev["status"] == "open"
        assert ev["critic_id"] == "endpoint-coverage-checker"

    def test_missed_high_critique_gate_fires_on_published(self, run_dir, state):
        """Published claim with missed high-relevance critique → CritiqueGateError raised (V16)."""
        from insight_kit.platform.gate.emit import ik_claim_emit

        res_ref = ik_research_emit(
            "RES-T32-C02",
            "https://api.example.com/docs",
            "endpoint coverage gate test",
            "perplexity",
            snapshot=SNAPSHOT,
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
        )
        write_endpoint_index(run_dir, res_ref.record_id, ENDPOINT_INDEX_MIXED)

        claim_ref = ik_claim_emit(
            "TEST-D-002",
            {"value": (200, "d")},
            tier="published",
            run_state=state,
            run_dir=run_dir,
            cites=[res_ref.record_id],
        )

        ei = read_endpoint_index(run_dir, res_ref.record_id)
        cov_result = check_endpoint_coverage_gap(ei, [], claim_id=claim_ref.record_id)
        assert cov_result.passed is False

        critique = CritiqueState.open(
            severity="high",
            reason=cov_result.message,
            critic_id="endpoint-coverage-checker",
        )
        with pytest.raises(CritiqueGateError):
            apply_critique(
                run_state=state,
                record_id=claim_ref.record_id,
                record_type="claim",
                tier="published",
                audience=None,
                critique=critique,
                run_dir=run_dir,
            )

    def test_full_coverage_no_critique_needed(self, run_dir, state):
        """Full coverage → check passes → no critique fired."""
        res_ref = ik_research_emit(
            "RES-T32-C03",
            "https://api.example.com/docs",
            "full coverage test",
            "perplexity",
            snapshot=SNAPSHOT,
            timestamp=TS,
            run_state=state,
            run_dir=run_dir,
        )
        write_endpoint_index(run_dir, res_ref.record_id, ENDPOINT_INDEX_MIXED)

        ei = read_endpoint_index(run_dir, res_ref.record_id)
        result = check_endpoint_coverage_gap(
            ei,
            ["orders.listOrders", "orders.getOrder"],
            claim_id="CLM-T32-C03",
        )
        assert result.passed is True
        # No critique fired — critiqueRounds unchanged
        assert state.critiqueRounds == 0


# ---------------------------------------------------------------------------
# Public __init__ exports
# ---------------------------------------------------------------------------


class TestPublicExports:
    def test_check_endpoint_coverage_gap_importable_from_gate(self):
        """check_endpoint_coverage_gap importable from the gate package root."""
        from insight_kit.platform.gate import check_endpoint_coverage_gap as fn

        assert callable(fn)

    def test_check_endpoint_coverage_result_importable_from_gate(self):
        """CheckEndpointCoverageResult importable from the gate package root."""
        from insight_kit.platform.gate import CheckEndpointCoverageResult

        assert CheckEndpointCoverageResult is CheckEndpointCoverageResult

    def test_check_endpoint_coverage_gap_in_all(self):
        """check_endpoint_coverage_gap present in gate __all__."""
        import insight_kit.platform.gate as gate_pkg

        assert "check_endpoint_coverage_gap" in gate_pkg.__all__

    def test_check_endpoint_coverage_result_in_all(self):
        """CheckEndpointCoverageResult present in gate __all__."""
        import insight_kit.platform.gate as gate_pkg

        assert "CheckEndpointCoverageResult" in gate_pkg.__all__

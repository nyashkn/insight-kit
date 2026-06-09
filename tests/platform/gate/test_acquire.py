"""T30 — ik_acquire: research->skill_use->claim API-ingestion chain.

Tests cover:
  - Chain produces 3 linked records (AcquireResult with 3 RecordRef objects).
  - cites edges: skill_use cites research, claim cites both.
  - knowledge-record snapshots persisted (V20).
  - Claim data_fingerprint_source == 'registered_input' (V22, C12).
  - Content-addressed record ids (deterministic for same inputs, V22).
  - V2 no-partial-write: if skill_use emit fails (dangling research), nothing
    from that step forward is written; if claim emit fails, research+skill_use
    are already on disk (sequential semantics, not two-phase).
  - Composability: multiple claims over the same research+skill_use pair.
  - rejectionCount incremented on emit failure.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.libs.validation import ValidationError as LayerAValidationError
from insight_kit.platform.gate.acquire import AcquireResult, ik_acquire
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import record_path, snapshot_path

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

TS = "2026-06-09T10:00:00+00:00"

SEARCH_RESULT = {
    "query": "shopify storefront graphql api schema",
    "results": [
        {"url": "https://shopify.dev/docs/api/storefront", "snippet": "GraphQL API..."},
    ],
    "timestamp": TS,
}

EXTRACTION_RESULT = {
    "tool": "shopify-graphql-extractor",
    "endpoint": "https://mystore.myshopify.com/api/2024-01/graphql.json",
    "fields_extracted": {"total_orders": 1234, "revenue_usd": 98765.43},
    "timestamp": TS,
}

CLAIM_FIELDS = {"total_orders": 1234, "revenue_usd": (98765.43, "$,.2f")}


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


def _acquire(run_dir: Path, state: RunState, **overrides) -> AcquireResult:
    """Helper that calls ik_acquire with sensible defaults."""
    kwargs: dict = dict(
        research_id="RES-SHOP-001",
        skill_use_id="SKU-SHOP-001",
        claim_id="TEST-D-001",
        api_search_result=SEARCH_RESULT,
        api_extraction_result=EXTRACTION_RESULT,
        claim_fields=CLAIM_FIELDS,
        research_query="shopify graphql api schema",
        research_source="shopify-dev-docs",
        research_timestamp=TS,
        skill_use_tool="shopify-graphql-extractor",
        skill_use_source="mystore.myshopify.com",
        skill_use_timestamp=TS,
        run_state=state,
        run_dir=run_dir,
    )
    kwargs.update(overrides)
    return ik_acquire(**kwargs)


# ---------------------------------------------------------------------------
# T30 — basic chain structure
# ---------------------------------------------------------------------------


class TestAcquireChain:
    def test_acquire_returns_acquire_result(self, run_dir, state):
        """ik_acquire returns an AcquireResult instance."""
        result = _acquire(run_dir, state)
        assert isinstance(result, AcquireResult)

    def test_acquire_chain_three_records(self, run_dir, state):
        """acquire() returns AcquireResult with 3 RecordRef objects, all in state.records."""
        result = _acquire(run_dir, state)
        assert result.research_ref is not None
        assert result.skill_use_ref is not None
        assert result.claim_ref is not None
        assert len(state.records) == 3

    def test_acquire_result_record_types(self, run_dir, state):
        """RecordRef objects carry correct record_type values."""
        result = _acquire(run_dir, state)
        assert result.research_ref.record_type == "research"
        assert result.skill_use_ref.record_type == "skill_use"
        assert result.claim_ref.record_type == "claim"

    def test_acquire_stable_ids_on_result(self, run_dir, state):
        """AcquireResult carries back the caller-assigned stable ids."""
        result = _acquire(run_dir, state)
        assert result.research_id == "RES-SHOP-001"
        assert result.skill_use_id == "SKU-SHOP-001"
        assert result.claim_id == "TEST-D-001"

    def test_acquire_records_in_state(self, run_dir, state):
        """All three record_ids appear in state.records."""
        result = _acquire(run_dir, state)
        state_ids = {r.record_id for r in state.records}
        assert result.research_ref.record_id in state_ids
        assert result.skill_use_ref.record_id in state_ids
        assert result.claim_ref.record_id in state_ids


# ---------------------------------------------------------------------------
# T30 — cites-edge integrity
# ---------------------------------------------------------------------------


class TestAcquireCitesEdges:
    def test_acquire_skill_use_cites_research(self, run_dir, state):
        """skill_use record cites=[research.record_id], forming the knowledge chain."""
        result = _acquire(run_dir, state)
        sku_rec = json.loads(record_path(run_dir, result.skill_use_ref.record_id).read_text())
        assert sku_rec["cites"] == [result.research_ref.record_id]

    def test_acquire_claim_cites_both(self, run_dir, state):
        """Claim cites list equals [research_id, skill_use_id], edges in record.json."""
        result = _acquire(run_dir, state)
        claim_rec = json.loads(record_path(run_dir, result.claim_ref.record_id).read_text())
        assert claim_rec["cites"] == [
            result.research_ref.record_id,
            result.skill_use_ref.record_id,
        ]

    def test_acquire_research_has_no_cites(self, run_dir, state):
        """Research record has no cites (it is the root of the chain)."""
        result = _acquire(run_dir, state)
        res_rec = json.loads(record_path(run_dir, result.research_ref.record_id).read_text())
        assert res_rec.get("cites", []) == []


# ---------------------------------------------------------------------------
# T30 — snapshot persistence (V20)
# ---------------------------------------------------------------------------


class TestAcquireSnapshotPersistence:
    def test_acquire_research_snapshot_persisted(self, run_dir, state):
        """Research snapshot.json persisted with the api_search_result content."""
        result = _acquire(run_dir, state)
        snap_file = snapshot_path(run_dir, result.research_ref.record_id)
        assert snap_file.exists()
        assert json.loads(snap_file.read_text()) == SEARCH_RESULT

    def test_acquire_skill_use_snapshot_persisted(self, run_dir, state):
        """skill_use snapshot.json persisted with the api_extraction_result content."""
        result = _acquire(run_dir, state)
        snap_file = snapshot_path(run_dir, result.skill_use_ref.record_id)
        assert snap_file.exists()
        assert json.loads(snap_file.read_text()) == EXTRACTION_RESULT

    def test_acquire_research_snapshot_fingerprint_in_record(self, run_dir, state):
        """Research record.json carries a non-None snapshot_fingerprint (64-hex sha256)."""
        result = _acquire(run_dir, state)
        rec = json.loads(record_path(run_dir, result.research_ref.record_id).read_text())
        assert rec["snapshot_fingerprint"] is not None
        assert len(rec["snapshot_fingerprint"]) == 64

    def test_acquire_skill_use_snapshot_fingerprint_in_record(self, run_dir, state):
        """skill_use record.json carries a non-None snapshot_fingerprint."""
        result = _acquire(run_dir, state)
        rec = json.loads(record_path(run_dir, result.skill_use_ref.record_id).read_text())
        assert rec["snapshot_fingerprint"] is not None
        assert len(rec["snapshot_fingerprint"]) == 64


# ---------------------------------------------------------------------------
# T30 — V22 input data fingerprint (registered_input)
# ---------------------------------------------------------------------------


class TestAcquireInputDataFingerprint:
    def test_acquire_claim_input_data_fingerprint_source(self, run_dir, state):
        """Claim has data_fingerprint_source='registered_input' (V22)."""
        result = _acquire(run_dir, state)
        claim_rec = json.loads(record_path(run_dir, result.claim_ref.record_id).read_text())
        assert claim_rec["data_fingerprint_source"] == "registered_input"

    def test_acquire_research_data_fingerprint_source_payload(self, run_dir, state):
        """Research record uses payload fingerprint (no input_data supplied)."""
        result = _acquire(run_dir, state)
        res_rec = json.loads(record_path(run_dir, result.research_ref.record_id).read_text())
        assert res_rec["data_fingerprint_source"] == "payload"

    def test_acquire_skill_use_data_fingerprint_source_payload(self, run_dir, state):
        """skill_use record uses payload fingerprint (no input_data supplied)."""
        result = _acquire(run_dir, state)
        sku_rec = json.loads(record_path(run_dir, result.skill_use_ref.record_id).read_text())
        assert sku_rec["data_fingerprint_source"] == "payload"


# ---------------------------------------------------------------------------
# T30 — claim tier/audience propagation
# ---------------------------------------------------------------------------


class TestAcquireClaimParams:
    def test_acquire_claim_tier_default_draft(self, run_dir, state):
        """Default claim_tier is 'draft'."""
        result = _acquire(run_dir, state)
        claim_rec = json.loads(record_path(run_dir, result.claim_ref.record_id).read_text())
        assert claim_rec["tier"] == "draft"

    def test_acquire_claim_tier_propagated(self, run_dir, state):
        """claim_tier param propagates to claim.json."""
        result = _acquire(run_dir, state, claim_tier="draft")
        claim_rec = json.loads(record_path(run_dir, result.claim_ref.record_id).read_text())
        assert claim_rec["tier"] == "draft"

    def test_acquire_claim_audience_propagated(self, run_dir, state):
        """claim_audience param propagates to claim.json when set."""
        result = _acquire(run_dir, state, claim_audience="ops")
        claim_rec = json.loads(record_path(run_dir, result.claim_ref.record_id).read_text())
        assert claim_rec["audience"] == "ops"

    def test_acquire_claim_fields_scalar_normalised(self, run_dir, state):
        """Plain-scalar claim_fields are normalised to FieldEntry (value+fmt_hint)."""
        result = _acquire(run_dir, state, claim_fields={"total_orders": 42})
        claim_rec = json.loads(record_path(run_dir, result.claim_ref.record_id).read_text())
        assert claim_rec["fields"]["total_orders"]["value"] == 42
        assert claim_rec["fields"]["total_orders"]["fmt_hint"] is None

    def test_acquire_claim_fields_tuple_form_normalised(self, run_dir, state):
        """Tuple (value, fmt_hint) form normalised to FieldEntry."""
        result = _acquire(run_dir, state, claim_fields={"revenue": (9999.0, "$,.0f")})
        claim_rec = json.loads(record_path(run_dir, result.claim_ref.record_id).read_text())
        assert claim_rec["fields"]["revenue"]["value"] == 9999.0
        assert claim_rec["fields"]["revenue"]["fmt_hint"] == "$,.0f"


# ---------------------------------------------------------------------------
# T30 — deterministic / content-addressed (V22)
# ---------------------------------------------------------------------------


class TestAcquireDeterministicFingerprints:
    def test_acquire_deterministic_fingerprints(self, run_dir, state):
        """Two acquire() calls with identical inputs → same record_ids (content-addressable).

        Because the second call hits the same content-addressed record ids as the
        first, _record_emit raises record-duplicate (FileExistsError path) for the
        research step. This is the expected behaviour for idempotent content-addressing.
        """
        _acquire(run_dir, state)
        # Identical payload → same fingerprints → duplicate record on disk → reject
        with pytest.raises(LayerAValidationError) as exc:
            _acquire(run_dir, state, claim_id="TEST-D-002")  # different claim_id but same research/sku
        assert exc.value.rule_id == "record-duplicate"

    def test_acquire_different_snapshots_produce_different_ids(self, run_dir, state):
        """Different api_search_result payloads → different research record_id."""
        result_a = _acquire(
            run_dir,
            state,
            api_search_result={"results": "A", "timestamp": TS},
            claim_id="TEST-D-001",
        )
        result_b = _acquire(
            run_dir,
            state,
            api_search_result={"results": "B", "timestamp": TS},
            research_id="RES-SHOP-002",
            skill_use_id="SKU-SHOP-002",
            claim_id="TEST-D-002",
        )
        assert result_a.research_ref.record_id != result_b.research_ref.record_id


# ---------------------------------------------------------------------------
# T30 — V2 no-partial-write and rejection counting
# ---------------------------------------------------------------------------


class TestAcquirePartialWriteAndRejection:
    def test_acquire_dangling_skill_use_cites_rejected(self, run_dir, state):
        """If research is not emitted yet and skill_use cites it, ik_skill_use_emit raises.

        We simulate this by calling ik_skill_use_emit directly with a bogus research id
        before calling ik_acquire — demonstrating that the underlying gate rejects it.
        The acquire wrapper itself won't call skill_use with a dangling cite; this test
        confirms the gate invariant holds for the underlying emit path.
        """
        from insight_kit.platform.gate.emit import ik_skill_use_emit

        with pytest.raises(LayerAValidationError) as exc:
            ik_skill_use_emit(
                "SKU-SHOP-001",
                "ref",
                "tool",
                "src",
                snapshot=EXTRACTION_RESULT,
                cites=["nonexistent-record-id"],
                timestamp=TS,
                run_state=state,
                run_dir=run_dir,
            )
        assert exc.value.rule_id == "cites-not-found"
        assert state.rejectionCount == 1

    def test_acquire_zero_partial_write_on_claim_reject(self, run_dir, state):
        """If claim emit fails, research+skill_use are already on disk (sequential).

        The claim fails because we pass an illegal claim_id (format check).
        research and skill_use should have already landed (2 records in state).
        """
        with pytest.raises(LayerAValidationError):
            _acquire(run_dir, state, claim_id="bad-id-format")  # illegal format
        # research + skill_use succeeded (2 records in state)
        assert len(state.records) == 2
        # rejection count == 1 (claim format check)
        assert state.rejectionCount == 1

    def test_acquire_runstate_rejection_count(self, run_dir, state):
        """rejectionCount incremented on emit failure in the chain."""
        assert state.rejectionCount == 0
        with pytest.raises(LayerAValidationError):
            _acquire(run_dir, state, claim_id="bad-id")
        assert state.rejectionCount == 1


# ---------------------------------------------------------------------------
# T30 — composability (meta-api / shopify-graphql use case)
# ---------------------------------------------------------------------------


class TestAcquireComposability:
    def test_acquire_composability_meta_api(self, run_dir, state):
        """ik_acquire can be called in a loop with different claim_ids over the same
        research/skill_use snapshot content.

        Because snapshots differ only in timestamp-irrelevant fields in this test
        we supply different claim ids and different research/skill_use ids each time
        to avoid content-address collisions.
        """
        results = []
        for i in range(3):
            r = _acquire(
                run_dir,
                state,
                research_id=f"RES-META-{i:03d}",
                skill_use_id=f"SKU-META-{i:03d}",
                claim_id=f"TEST-D-{i + 10:03d}",
                api_search_result={**SEARCH_RESULT, "iteration": i},
                api_extraction_result={**EXTRACTION_RESULT, "iteration": i},
            )
            results.append(r)

        # Each iteration emits 3 records → 9 total
        assert len(state.records) == 9
        # All claim record_ids distinct
        claim_ids = [r.claim_ref.record_id for r in results]
        assert len(set(claim_ids)) == 3

    def test_acquire_multiple_claims_share_no_records(self, run_dir, state):
        """Two separate acquire() chains with different snapshots each produce
        independent records — no cross-contamination in cites edges."""
        r1 = _acquire(
            run_dir,
            state,
            research_id="RES-A-001",
            skill_use_id="SKU-A-001",
            claim_id="TEST-D-001",
            api_search_result={"q": "api-A", "ts": TS},
            api_extraction_result={"data": "A", "ts": TS},
        )
        r2 = _acquire(
            run_dir,
            state,
            research_id="RES-B-001",
            skill_use_id="SKU-B-001",
            claim_id="TEST-D-002",
            api_search_result={"q": "api-B", "ts": TS},
            api_extraction_result={"data": "B", "ts": TS},
        )
        # Chain 1 claim cites only chain-1 knowledge records
        claim1 = json.loads(record_path(run_dir, r1.claim_ref.record_id).read_text())
        assert claim1["cites"] == [r1.research_ref.record_id, r1.skill_use_ref.record_id]

        # Chain 2 claim cites only chain-2 knowledge records
        claim2 = json.loads(record_path(run_dir, r2.claim_ref.record_id).read_text())
        assert claim2["cites"] == [r2.research_ref.record_id, r2.skill_use_ref.record_id]

    def test_acquire_public_export_via_init(self):
        """ik_acquire and AcquireResult are importable from the gate package root."""
        from insight_kit.platform.gate import AcquireResult as AcquireResultPkg
        from insight_kit.platform.gate import ik_acquire as ik_acquire_pkg

        assert ik_acquire_pkg is ik_acquire
        assert AcquireResultPkg is AcquireResult

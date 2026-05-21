"""Tests for gate/schema.py — T1.

Covers:
  - Discriminated union correctly routes each record_type.
  - Invalid record_type or missing required fields raises pydantic ValidationError.
  - FieldEntry value + fmt_hint round-trips.
  - ClaimTier enum values.
  - Extra fields rejected (model_config extra=forbid).
"""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError as PydanticValidationError

from insight_kit.gate.schema import (
    ClaimRecord,
    ClaimTier,
    FieldEntry,
    IntentPayload,
    InterventionRecord,
    RealizedPayload,
    RecordSchema,
    ResearchRecord,
    SkillUseRecord,
)

_TA = TypeAdapter(RecordSchema)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_claim_payload() -> dict:
    return {
        "record_type": "claim",
        "claim_id": "TEST-D-001",
        "fields": {"revenue": {"value": 123456, "fmt_hint": "$,.0f"}},
        "tier": "draft",
    }


def _valid_intervention_payload() -> dict:
    return {
        "record_type": "intervention",
        "intervention_id": "INT-001",
        "intent": {"description": "send email"},
        "tier": "draft",
    }


def _valid_research_payload() -> dict:
    return {
        "record_type": "research",
        "research_id": "RES-001",
        "snapshot_ref": "snapshots/res-001.json",
        "query": "market size",
        "source": "perplexity",
        "timestamp": "2026-05-21T10:00:00+00:00",
    }


def _valid_skill_use_payload() -> dict:
    return {
        "record_type": "skill_use",
        "skill_use_id": "SKU-001",
        "snapshot_ref": "snapshots/sku-001.json",
        "tool": "tavily-search",
        "source": "tavily",
        "timestamp": "2026-05-21T10:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Discriminated union routing
# ---------------------------------------------------------------------------

class TestDiscriminatedUnion:
    def test_claim_routes_to_claim_record(self):
        rec = _TA.validate_python(_valid_claim_payload())
        assert isinstance(rec, ClaimRecord)
        assert rec.record_type == "claim"

    def test_intervention_routes_to_intervention_record(self):
        rec = _TA.validate_python(_valid_intervention_payload())
        assert isinstance(rec, InterventionRecord)
        assert rec.record_type == "intervention"

    def test_research_routes_to_research_record(self):
        rec = _TA.validate_python(_valid_research_payload())
        assert isinstance(rec, ResearchRecord)
        assert rec.record_type == "research"

    def test_skill_use_routes_to_skill_use_record(self):
        rec = _TA.validate_python(_valid_skill_use_payload())
        assert isinstance(rec, SkillUseRecord)
        assert rec.record_type == "skill_use"

    def test_invalid_record_type_raises(self):
        payload = _valid_claim_payload()
        payload["record_type"] = "hallucinated"
        with pytest.raises(PydanticValidationError):
            _TA.validate_python(payload)

    def test_missing_record_type_raises(self):
        payload = _valid_claim_payload()
        del payload["record_type"]
        with pytest.raises(PydanticValidationError):
            _TA.validate_python(payload)


# ---------------------------------------------------------------------------
# ClaimRecord specifics
# ---------------------------------------------------------------------------

class TestClaimRecord:
    def test_fields_round_trip(self):
        rec = ClaimRecord(
            claim_id="TEST-D-001",
            fields={"revenue": FieldEntry(value=123456, fmt_hint="$,.0f")},
        )
        assert rec.fields["revenue"].value == 123456
        assert rec.fields["revenue"].fmt_hint == "$,.0f"

    def test_fields_no_fmt_hint(self):
        rec = ClaimRecord(
            claim_id="TEST-D-001",
            fields={"count": FieldEntry(value=42)},
        )
        assert rec.fields["count"].fmt_hint is None

    def test_tier_defaults_to_draft(self):
        rec = ClaimRecord(claim_id="TEST-D-001", fields={})
        assert rec.tier == ClaimTier.draft

    def test_tier_published(self):
        rec = ClaimRecord(claim_id="TEST-D-001", fields={}, tier=ClaimTier.published)
        assert rec.tier == ClaimTier.published

    def test_audience_optional(self):
        rec = ClaimRecord(claim_id="TEST-D-001", fields={}, audience="board")
        assert rec.audience == "board"

    def test_narrative_ref_optional(self):
        rec = ClaimRecord(
            claim_id="TEST-D-001",
            fields={},
            narrative_ref="narrative/TEST-D-001.md",
        )
        assert rec.narrative_ref == "narrative/TEST-D-001.md"

    def test_extra_field_rejected(self):
        with pytest.raises(PydanticValidationError):
            ClaimRecord(
                claim_id="TEST-D-001",
                fields={},
                _unknown_extra_field="oops",  # type: ignore[call-arg]
            )

    def test_cites_defaults_empty(self):
        rec = ClaimRecord(claim_id="TEST-D-001", fields={})
        assert rec.cites == []

    def test_cites_populated(self):
        rec = ClaimRecord(
            claim_id="TEST-D-001",
            fields={},
            cites=["RES-001", "SKU-001"],
        )
        assert rec.cites == ["RES-001", "SKU-001"]


# ---------------------------------------------------------------------------
# InterventionRecord specifics
# ---------------------------------------------------------------------------

class TestInterventionRecord:
    def test_realized_null_on_draft(self):
        rec = InterventionRecord(
            intervention_id="INT-001",
            intent=IntentPayload(description="do thing"),
        )
        assert rec.realized is None

    def test_realized_applied(self):
        rec = InterventionRecord(
            intervention_id="INT-001",
            intent=IntentPayload(description="do thing"),
            realized=RealizedPayload(status="applied"),
        )
        assert rec.realized.status == "applied"

    def test_realized_partial(self):
        rec = InterventionRecord(
            intervention_id="INT-001",
            intent=IntentPayload(description="do thing"),
            realized=RealizedPayload(status="partial", details="only half worked"),
        )
        assert rec.realized.status == "partial"

    def test_realized_invalid_status_raises(self):
        with pytest.raises(PydanticValidationError):
            InterventionRecord(
                intervention_id="INT-001",
                intent=IntentPayload(description="do thing"),
                realized=RealizedPayload(status="unknown_status"),  # type: ignore[arg-type]
            )

    def test_extra_field_rejected(self):
        with pytest.raises(PydanticValidationError):
            InterventionRecord(
                intervention_id="INT-001",
                intent=IntentPayload(description="do thing"),
                bad_extra=True,  # type: ignore[call-arg]
            )


# ---------------------------------------------------------------------------
# ResearchRecord specifics
# ---------------------------------------------------------------------------

class TestResearchRecord:
    def test_required_fields_present(self):
        rec = ResearchRecord(
            research_id="RES-001",
            snapshot_ref="s/r.json",
            query="what is X",
            source="web",
            timestamp="2026-05-21T10:00:00+00:00",
        )
        assert rec.research_id == "RES-001"
        assert rec.source == "web"

    def test_missing_snapshot_ref_raises(self):
        with pytest.raises(PydanticValidationError):
            ResearchRecord(  # type: ignore[call-arg]
                research_id="RES-001",
                query="q",
                source="s",
                timestamp="2026-05-21T10:00:00+00:00",
            )


# ---------------------------------------------------------------------------
# SkillUseRecord specifics
# ---------------------------------------------------------------------------

class TestSkillUseRecord:
    def test_required_fields_present(self):
        rec = SkillUseRecord(
            skill_use_id="SKU-001",
            snapshot_ref="s/k.json",
            tool="tavily",
            source="tavily",
            timestamp="2026-05-21T10:00:00+00:00",
        )
        assert rec.skill_use_id == "SKU-001"
        assert rec.tool == "tavily"

    def test_missing_tool_raises(self):
        with pytest.raises(PydanticValidationError):
            SkillUseRecord(  # type: ignore[call-arg]
                skill_use_id="SKU-001",
                snapshot_ref="s/k.json",
                source="tavily",
                timestamp="2026-05-21T10:00:00+00:00",
            )


# ---------------------------------------------------------------------------
# model_dump round-trip
# ---------------------------------------------------------------------------

class TestModelDump:
    def test_claim_dump_contains_record_type(self):
        rec = ClaimRecord(claim_id="TEST-D-001", fields={})
        d = rec.model_dump(mode="json")
        assert d["record_type"] == "claim"

    def test_intervention_dump_contains_record_type(self):
        rec = InterventionRecord(
            intervention_id="INT-001",
            intent=IntentPayload(description="x"),
        )
        d = rec.model_dump(mode="json")
        assert d["record_type"] == "intervention"

"""Unit tests for Claim + ClaimValue dataclass serialization."""
from __future__ import annotations
import pytest
from insight_kit.provenance.claim import Claim, ClaimValue


# U-01
def test_claim_roundtrip():
    """Claim.to_json() preserves all non-None top-level fields."""
    c = Claim(
        claim_id="T-001",
        statement="x is 5",
        tier="derived",
        value=ClaimValue(n=5, unit="count"),
        confidence="high",
        agent_id="analyst",
        supports=["T-000"],
    )
    d = c.to_json()
    assert d["claim_id"] == "T-001"
    assert d["statement"] == "x is 5"
    assert d["tier"] == "derived"
    assert d["value"] == {"n": 5, "unit": "count"}
    assert d["confidence"] == "high"
    assert d["agent_id"] == "analyst"
    assert d["supports"] == ["T-000"]


# U-02
def test_claimvalue_none_pruning():
    assert ClaimValue(n=5, unit=None).to_json() == {"n": 5}
    assert ClaimValue().to_json() == {}


# U-03
def test_claimvalue_all_fields():
    v = ClaimValue(n=5, unit="KES", ci_low=4.0, ci_high=6.0, ci_method="bootstrap")
    d = v.to_json()
    assert set(d.keys()) == {"n", "unit", "ci_low", "ci_high", "ci_method"}


# U-05
def test_claim_status_default():
    c = Claim(claim_id="T-002", statement="s")
    assert c.status == "proposed"


# U-06
def test_claim_confidence_default():
    c = Claim(claim_id="T-003", statement="s")
    assert c.confidence == "medium"


# U-07
def test_claim_to_json_drops_none_top_level():
    c = Claim(claim_id="T-004", statement="s")
    d = c.to_json()
    assert "model" not in d
    assert "metric_id" not in d
    assert "run_id" not in d
    assert all(v is not None for v in d.values())


# U-08
def test_claim_to_json_keeps_empty_input_claims():
    c = Claim(claim_id="T-005", statement="s")
    d = c.to_json()
    assert d["input_claims"] == []


# U-09
def test_claim_to_json_keeps_empty_supports():
    c = Claim(claim_id="T-006", statement="s")
    d = c.to_json()
    assert d["supports"] == []


# U-04 (gap doc — runtime accepts bogus tier; pydantic migration tracked separately)
def test_claim_tier_is_dataclass_unconstrained():
    """Claim.tier is a Literal at type-time but unchecked at runtime (dataclass)."""
    c = Claim(claim_id="T-007", statement="s", tier="bogus_tier")  # type: ignore[arg-type]
    assert c.tier == "bogus_tier"

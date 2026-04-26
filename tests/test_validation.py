"""Tests for Layer-A real-time validation guards.

~20 tests covering:
- claim-id-format       (5 tests)
- claim-id-namespace    (4 tests)
- critic-requires-edge  (4 tests)
- external-requires-caveats (4 tests)
- integration via Run   (3 tests)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit import Run
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config
from insight_kit.validation import (
    ValidationError,
    check_claim_id_format,
    check_claim_id_namespace,
    check_critic_edges,
    check_external_caveats,
)

# ---------- fixtures ----------


@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    return tmp_path


# ---------- claim-id-format (5 tests) ----------


def test_format_valid_simple():
    """TEST-D-001 is valid."""
    check_claim_id_format("TEST-D-001")  # must not raise


def test_format_valid_etl_metric():
    """TEST-ETL_M-001 is valid (ETL_M tier)."""
    check_claim_id_format("TEST-ETL_M-001")


def test_format_invalid_lowercase_namespace():
    """lowercase namespace fails regex."""
    with pytest.raises(ValidationError) as exc_info:
        check_claim_id_format("test-D-001")
    assert exc_info.value.rule_id == "claim-id-format"
    assert "suggestion" in str(exc_info.value).lower() or exc_info.value.suggestion is not None


def test_format_invalid_missing_tier():
    """Missing tier segment fails."""
    with pytest.raises(ValidationError) as exc_info:
        check_claim_id_format("TEST-001")
    assert exc_info.value.rule_id == "claim-id-format"


def test_format_invalid_too_few_digits():
    """Sequence with fewer than 3 digits fails (seq must be 3+ digits)."""
    with pytest.raises(ValidationError) as exc_info:
        check_claim_id_format("TEST-D-01")
    assert exc_info.value.rule_id == "claim-id-format"


def test_format_invalid_empty():
    """Empty string fails."""
    with pytest.raises(ValidationError):
        check_claim_id_format("")


def test_format_invalid_namespace_too_long():
    """Namespace longer than 5 chars fails."""
    with pytest.raises(ValidationError):
        check_claim_id_format("TOOLONG-D-001")


# ---------- claim-id-namespace (4 tests) ----------


def test_namespace_valid_match():
    """claim_id starting with namespace passes."""
    check_claim_id_namespace("TEST-D-001", "TEST")  # must not raise


def test_namespace_valid_different_ns():
    """claim_id with a two-char namespace passes against that namespace."""
    check_claim_id_namespace("NM-D-001", "NM")  # must not raise


def test_namespace_invalid_wrong_prefix():
    """claim_id with wrong namespace prefix raises."""
    with pytest.raises(ValidationError) as exc_info:
        check_claim_id_namespace("OTHER-D-001", "TEST")
    assert exc_info.value.rule_id == "claim-id-namespace"
    assert "TEST" in (exc_info.value.suggestion or "")


def test_namespace_case_sensitive():
    """Namespace check is case-sensitive: 'test' != 'TEST'."""
    with pytest.raises(ValidationError) as exc_info:
        check_claim_id_namespace("test-D-001", "TEST")
    assert exc_info.value.rule_id == "claim-id-namespace"


# ---------- critic-requires-edge (4 tests) ----------


def test_critic_valid_with_supports():
    """critic tier with supports edge passes."""
    check_critic_edges("critic", ["OTHER-D-001"], None)  # must not raise


def test_critic_valid_with_refutes():
    """critic tier with refutes edge passes."""
    check_critic_edges("critic", None, ["OTHER-D-001"])  # must not raise


def test_critic_invalid_no_edges():
    """critic tier with neither supports nor refutes raises."""
    with pytest.raises(ValidationError) as exc_info:
        check_critic_edges("critic", [], [])
    assert exc_info.value.rule_id == "critic-requires-edge"
    assert "supports" in (exc_info.value.suggestion or "")


def test_derived_tier_no_edges_ok():
    """Non-critic tier with no edges is fine."""
    check_critic_edges("derived", [], [])  # must not raise
    check_critic_edges("raw", None, None)  # must not raise


# ---------- external-requires-caveats (4 tests) ----------


def test_external_caveats_explicit_list():
    """Explicit non-empty caveats passes."""
    check_external_caveats(["my_caveat"])  # must not raise


def test_external_caveats_none_defaults():
    """None (unspecified) passes — defaults applied upstream."""
    check_external_caveats(None)  # must not raise


def test_external_caveats_explicit_empty_raises():
    """Explicitly passing [] raises — caller must not opt out of caveats."""
    with pytest.raises(ValidationError) as exc_info:
        check_external_caveats([])
    assert exc_info.value.rule_id == "external-requires-caveats"
    assert "external_source" in (exc_info.value.suggestion or "")


def test_external_caveats_multiple_values():
    """Multiple explicit caveats pass."""
    check_external_caveats(["external_source", "non_audited", "stale_data"])  # must not raise


# ---------- integration: Run-level (3 tests) ----------


def test_run_claim_raises_on_bad_format(kit: Path):
    """Run.claim raises ValidationError when claim_id doesn't match regex."""
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.claim(claim_id="bad_id", statement="should fail")
    assert exc_info.value.rule_id == "claim-id-format"


def test_run_ingest_external_raises_on_empty_caveats(kit: Path):
    """Run.ingest_external raises ValidationError when caveats=[] is passed."""
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.ingest_external(
                kind="search",
                source_id="test-query",
                content="some content",
                caveats=[],  # explicitly empty — must raise
            )
    assert exc_info.value.rule_id == "external-requires-caveats"


def test_validation_error_attrs_accessible(kit: Path):
    """ValidationError exposes rule_id and suggestion as attributes."""
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.claim(claim_id="OTHER-D-001", statement="wrong namespace")
    err = exc_info.value
    assert isinstance(err, ValidationError)
    assert isinstance(err, ValueError)
    assert err.rule_id == "claim-id-namespace"
    assert err.suggestion is not None
    assert "TEST" in err.suggestion


def test_run_ingest_external_default_caveats(kit: Path):
    """Run.ingest_external with no caveats arg defaults to ['external_source', 'non_audited']."""
    with Run(topic="t", agent="a") as r:
        rec = r.ingest_external(
            kind="search",
            source_id="test-query",
            content="some content",
        )
    assert rec.default_caveats == ["external_source", "non_audited"]


def test_run_claim_critic_no_edges_raises(kit: Path):
    """Run.claim raises ValidationError for critic tier with no edges."""
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.claim(
                claim_id="TEST-C-001",
                statement="this critic has no edges",
                tier="critic",
            )
    assert exc_info.value.rule_id == "critic-requires-edge"


def test_run_claim_critic_with_refutes_ok(kit: Path):
    """Run.claim with critic tier and refutes passes validation."""
    with Run(topic="t", agent="a") as r:
        c = r.claim(
            claim_id="TEST-C-001",
            statement="this critic refutes something",
            tier="critic",
            refutes=["TEST-D-001"],
        )
    assert c.claim_id == "TEST-C-001"

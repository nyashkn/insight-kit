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
    check_citation_referential_integrity,
    check_claim_id_format,
    check_claim_id_namespace,
    check_claim_id_unique,
    check_claim_id_unique_in_run,
    check_critic_edges,
    check_external_caveats,
    check_input_claims_exist,
    check_metric_id_allowed,
    check_supersedes_chain_integrity,
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


# ---------- Fix #8: input-claims referential integrity ----------


def test_input_claims_no_refs_passes():
    """Empty input_claims always passes."""
    check_input_claims_exist("TEST-D-002", [], set(), Path("/nonexistent"))


def test_input_claims_ref_in_current_run_passes(kit: Path):
    """input_claims ref to claim in current run's already-emitted claims passes."""
    with Run(topic="t", agent="a") as r:
        r.claim(claim_id="TEST-D-001", statement="base claim")
        # TEST-D-002 references TEST-D-001 which is already in current run
        c = r.claim(
            claim_id="TEST-D-002",
            statement="derived from 001",
            input_claims=["TEST-D-001"],
        )
    assert c.claim_id == "TEST-D-002"


def test_input_claims_dangling_ref_raises(kit: Path):
    """input_claims referencing a non-existent claim_id raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.claim(
                claim_id="TEST-D-001",
                statement="references a ghost",
                input_claims=["TEST-D-GHOST-999"],
            )
    assert exc_info.value.rule_id == "input-claims-referential-integrity"
    assert "TEST-D-GHOST-999" in str(exc_info.value)


def test_input_claims_ref_in_prior_run_passes(kit: Path):
    """input_claims ref to claim_id written in a prior run's claims.jsonl passes."""
    import json as _json

    # Manually create a prior run dir with a claims.jsonl containing TEST-D-001
    prior_run_dir = kit / ".insight-kit" / "runs" / "2024-01-01_0000_prior_agent_t"
    prior_run_dir.mkdir(parents=True, exist_ok=True)
    (prior_run_dir / "claims.jsonl").write_text(
        _json.dumps({"claim_id": "TEST-D-001", "statement": "prior claim"}) + "\n"
    )

    # Now a new run references TEST-D-001 as an input_claim — should pass
    with Run(topic="t", agent="a") as r:
        c = r.claim(
            claim_id="TEST-D-002",
            statement="references prior run claim",
            input_claims=["TEST-D-001"],
        )
    assert c.claim_id == "TEST-D-002"


# ---------- Fix #10: claim-id globally unique ----------


def test_claim_id_unique_no_runs(kit: Path):
    """No runs → no errors."""
    errors = check_claim_id_unique(kit)
    assert errors == []


def test_claim_id_unique_single_run_no_errors(kit: Path):
    """Single run with a claim → no errors."""
    with Run(topic="t", agent="a") as r:
        r.claim(claim_id="TEST-D-001", statement="unique")
    errors = check_claim_id_unique(kit)
    assert errors == []


def test_claim_id_unique_duplicate_across_runs_raises(kit: Path):
    """Same claim_id in two runs without supersedes → ValidationError."""
    import json as _json
    import time

    # First run
    run1_dir = kit / ".insight-kit" / "runs" / "2024-01-01_0000_a_t"
    run1_dir.mkdir(parents=True, exist_ok=True)
    (run1_dir / "claims.jsonl").write_text(
        _json.dumps({"claim_id": "TEST-D-001", "statement": "first"}) + "\n"
    )

    # Second run with same claim_id, no supersedes
    run2_dir = kit / ".insight-kit" / "runs" / "2024-01-02_0000_a_t"
    run2_dir.mkdir(parents=True, exist_ok=True)
    (run2_dir / "claims.jsonl").write_text(
        _json.dumps({"claim_id": "TEST-D-001", "statement": "duplicate"}) + "\n"
    )

    errors = check_claim_id_unique(kit)
    assert len(errors) == 1
    assert errors[0].rule_id == "claim-id-globally-unique"
    assert "TEST-D-001" in str(errors[0])


def test_claim_id_unique_supersedes_chain_ok(kit: Path):
    """Same claim_id in two runs where one has supersedes → no error."""
    import json as _json

    run1_dir = kit / ".insight-kit" / "runs" / "2024-01-01_0000_a_t"
    run1_dir.mkdir(parents=True, exist_ok=True)
    (run1_dir / "claims.jsonl").write_text(
        _json.dumps({"claim_id": "TEST-D-001", "statement": "first"}) + "\n"
    )

    run2_dir = kit / ".insight-kit" / "runs" / "2024-01-02_0000_a_t"
    run2_dir.mkdir(parents=True, exist_ok=True)
    (run2_dir / "claims.jsonl").write_text(
        _json.dumps(
            {"claim_id": "TEST-D-001", "statement": "replacement", "supersedes": "TEST-D-001"}
        )
        + "\n"
    )

    errors = check_claim_id_unique(kit)
    assert errors == []


def test_run_exit_raises_on_duplicate_claim_id(kit: Path):
    """Run.__exit__ (Layer B) raises if a claim_id was already used in a prior run."""
    import json as _json

    # Inject a prior run with TEST-D-001
    prior_dir = kit / ".insight-kit" / "runs" / "2024-01-01_0000_prior_a_t"
    prior_dir.mkdir(parents=True, exist_ok=True)
    (prior_dir / "claims.jsonl").write_text(
        _json.dumps({"claim_id": "TEST-D-001", "statement": "prior"}) + "\n"
    )

    # New run uses the same claim_id without supersedes → should raise on __exit__
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.claim(claim_id="TEST-D-001", statement="duplicate no supersedes")
    assert exc_info.value.rule_id == "claim-id-globally-unique"


# ---------- M5: supersedes-already-deprecated ----------


def test_supersedes_chain_no_supersedes_passes(kit: Path):
    """No supersedes → no error."""
    check_supersedes_chain_integrity("TEST-D-002", None, kit, set())  # must not raise


def test_supersedes_chain_fresh_target_passes(kit: Path):
    """supersedes=X where X has no existing successor → passes."""
    import json as _json

    prior_dir = kit / ".insight-kit" / "runs" / "2024-01-01_0000_prior_a_t"
    prior_dir.mkdir(parents=True, exist_ok=True)
    (prior_dir / "claims.jsonl").write_text(
        _json.dumps({"claim_id": "TEST-D-001", "statement": "original"}) + "\n"
    )
    # Should not raise — nothing supersedes TEST-D-001 yet
    check_supersedes_chain_integrity("TEST-D-002", "TEST-D-001", kit, set())


def test_supersedes_chain_already_superseded_raises(kit: Path):
    """supersedes=X where X was already superseded by a prior claim → raises."""
    import json as _json

    # Y supersedes X already
    prior_dir = kit / ".insight-kit" / "runs" / "2024-01-02_0000_prior_a_t"
    prior_dir.mkdir(parents=True, exist_ok=True)
    (prior_dir / "claims.jsonl").write_text(
        _json.dumps({"claim_id": "TEST-D-002", "statement": "Y supersedes X", "supersedes": "TEST-D-001"}) + "\n"
    )
    # Now Z also tries to supersede X → must raise
    with pytest.raises(ValidationError) as exc_info:
        check_supersedes_chain_integrity("TEST-D-003", "TEST-D-001", kit, set())
    assert exc_info.value.rule_id == "supersedes-already-deprecated"
    assert "TEST-D-001" in str(exc_info.value)


def test_run_supersedes_already_deprecated_raises(kit: Path):
    """Run.claim() raises supersedes-already-deprecated if target already has a successor."""
    import json as _json

    prior_dir = kit / ".insight-kit" / "runs" / "2024-01-02_0000_prior_a_t"
    prior_dir.mkdir(parents=True, exist_ok=True)
    (prior_dir / "claims.jsonl").write_text(
        _json.dumps({"claim_id": "TEST-D-002", "statement": "replacement", "supersedes": "TEST-D-001"}) + "\n"
    )
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.claim(claim_id="TEST-D-003", statement="also replaces 001", supersedes="TEST-D-001")
    assert exc_info.value.rule_id == "supersedes-already-deprecated"


# ---------- M6: citation-referential-integrity ----------


def test_citation_no_cites_passes():
    """Statement with no [[CITE:]] patterns passes."""
    check_citation_referential_integrity("plain statement", None, set(), Path("/nonexistent"))


def test_citation_known_id_passes(kit: Path):
    """[[CITE: TEST-D-001]] passes when TEST-D-001 is in current_run_claim_ids."""
    check_citation_referential_integrity(
        "See [[CITE: TEST-D-001]] for details.",
        None,
        {"TEST-D-001"},
        kit,
    )


def test_citation_unknown_id_raises(kit: Path):
    """[[CITE: DOCK-D-999]] raises when 999 doesn't exist."""
    with pytest.raises(ValidationError) as exc_info:
        check_citation_referential_integrity(
            "Based on [[CITE: DOCK-D-999]] analysis.",
            None,
            set(),
            kit,
        )
    assert exc_info.value.rule_id == "citation-referential-integrity"
    assert "DOCK-D-999" in str(exc_info.value)


def test_run_citation_unknown_raises(kit: Path):
    """Run.claim raises citation-referential-integrity for [[CITE: ID]] when ID not found."""
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.claim(
                claim_id="TEST-D-001",
                statement="Based on [[CITE: TEST-D-999]] which is unknown.",
            )
    assert exc_info.value.rule_id == "citation-referential-integrity"


# ---------- M7: claim-id-duplicate-in-run ----------


def test_duplicate_in_run_first_emit_passes():
    """First emit of a claim_id in empty set passes."""
    check_claim_id_unique_in_run("TEST-D-001", set())  # must not raise


def test_duplicate_in_run_second_emit_raises():
    """Second emit of same claim_id in run raises immediately."""
    with pytest.raises(ValidationError) as exc_info:
        check_claim_id_unique_in_run("TEST-D-001", {"TEST-D-001"})
    assert exc_info.value.rule_id == "claim-id-duplicate-in-run"
    assert "TEST-D-001" in str(exc_info.value)


def test_run_claim_duplicate_in_run_raises_immediately(kit: Path):
    """Run.claim raises claim-id-duplicate-in-run on 2nd emit of same ID in same run."""
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.claim(claim_id="TEST-D-001", statement="first")
            r.claim(claim_id="TEST-D-001", statement="second — must raise immediately")
    assert exc_info.value.rule_id == "claim-id-duplicate-in-run"


# ---------- M8: metric-id-off-glossary ----------


@pytest.fixture
def kit_with_glossary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Kit fixture with a project glossary.yaml defining topics=["funnel", "zoho"]."""
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    glossary_dir = tmp_path / ".insight-kit" / "templates"
    glossary_dir.mkdir(parents=True, exist_ok=True)
    (glossary_dir / "glossary.yaml").write_text("topics:\n  - funnel\n  - zoho\n")
    return tmp_path


def test_metric_id_allowed_known_prefix_passes(kit_with_glossary: Path):
    """metric name starting with a glossary prefix passes."""
    check_metric_id_allowed("funnel_volume_b1", kit_with_glossary)  # must not raise
    check_metric_id_allowed("zoho_pipeline_value", kit_with_glossary)  # must not raise


def test_metric_id_allowed_unknown_prefix_raises(kit_with_glossary: Path):
    """metric name with no glossary prefix raises."""
    with pytest.raises(ValidationError) as exc_info:
        check_metric_id_allowed("weather_pressure", kit_with_glossary)
    assert exc_info.value.rule_id == "metric-id-off-glossary"
    assert "weather_pressure" in str(exc_info.value)


def test_metric_id_no_glossary_is_permissive(kit: Path):
    """Without a project glossary.yaml, any metric name is accepted."""
    check_metric_id_allowed("weather_pressure", kit)  # must not raise — no glossary


def test_run_emit_metric_off_glossary_raises(kit_with_glossary: Path):
    """Run.emit_metric raises metric-id-off-glossary for unknown metric name prefix."""
    import polars as pl

    df = pl.DataFrame({"a": [1, 2, 3]})
    with pytest.raises(ValidationError) as exc_info:
        with Run(topic="t", agent="a") as r:
            r.emit_metric(df, name="weather_pressure_kpa")
    assert exc_info.value.rule_id == "metric-id-off-glossary"


def test_run_emit_metric_known_prefix_passes(kit_with_glossary: Path):
    """Run.emit_metric passes when name matches a glossary topic prefix."""
    import polars as pl

    df = pl.DataFrame({"a": [1, 2, 3]})
    with Run(topic="t", agent="a") as r:
        path = r.emit_metric(df, name="funnel_volume_b1")
    assert path.exists()

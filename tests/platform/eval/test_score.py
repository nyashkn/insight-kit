"""Tests for insight_kit.platform.eval.score — checks 7-9 (semantic) + integration.

Covers:
  - Check 7: claim_id regex validation (numeric + T-suffix critic threading)
  - Check 8: citation cross-check (claim.query_path resolves on disk;
             multi-source, .py extractors, missing field all covered)
  - Check 9: length prior on findings_*.md
  - Integration: full 9-check score pass/fail scenarios
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.platform.eval.score import (
    CLAIM_ID_RE,
    FINDINGS_MAX_BYTES,
    FINDINGS_MIN_BYTES,
    score as run_score,
)

FINDINGS_MIN = FINDINGS_MIN_BYTES
FINDINGS_MAX = FINDINGS_MAX_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run_dir(
    tmp_path: Path,
    *,
    claim_ids: list[str] | None = None,
    analyst_bytes: int = 5000,
    critic_bytes: int = 5000,
    include_queries_for: list[str] | None = None,
    stub_analyst: bool = False,
    query_paths: dict[str, str] | None = None,
) -> Path:
    """Build a minimal run dir fixture.

    query_paths: per-claim override of the query_path field. Keyed by claim_id.
                 When omitted, MD-D-* claims default to `queries/<id>.sql` and
                 MD-C-* claims default to empty string (critic claims usually
                 don't cite a single backing query).
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # Default: 2 analyst + 1 critic, matching real format
    if claim_ids is None:
        claim_ids = ["MD-D-G6-001", "MD-D-G6-002", "MD-C-G6-001"]

    query_paths = query_paths or {}

    # claims.jsonl
    lines = ["# header comment\n"]
    for cid in claim_ids:
        tier = "critic" if cid.startswith("MD-C-") else "derived"
        obj: dict = {"claim_id": cid, "tier": tier, "statement": "test claim"}
        if cid in query_paths:
            obj["query_path"] = query_paths[cid]
        elif cid.startswith("MD-D-"):
            obj["query_path"] = f"queries/{cid}.sql"
        lines.append(json.dumps(obj) + "\n")
    (run_dir / "claims.jsonl").write_text("".join(lines))

    # findings_analyst.md
    analyst_text = "x" * analyst_bytes
    if stub_analyst:
        analyst_text = "replace this stub"
    (run_dir / "findings_analyst.md").write_text(analyst_text)

    # findings_critic.md
    (run_dir / "findings_critic.md").write_text("x" * critic_bytes)

    # queries/ dir
    qdir = run_dir / "queries"
    qdir.mkdir()

    # default: create query files for all MD-D-* claim_ids present
    md_d_ids = [c for c in claim_ids if c.startswith("MD-D-")]
    if include_queries_for is None:
        include_queries_for = md_d_ids
    for cid in include_queries_for:
        (qdir / f"{cid}.sql").write_text(f"-- {cid}\nSELECT 1;\n")

    return run_dir


# ---------------------------------------------------------------------------
# Check 7: claim_id regex
# ---------------------------------------------------------------------------

def test_claim_id_regex_pass(tmp_path: Path) -> None:
    """All valid IDs — regex check must pass."""
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-D-G6-010", "MD-C-G6-001", "MD-C-G6-009"],
    )
    result = run_score(run_dir)
    assert result == pytest.approx(9 / 9)


def test_claim_id_regex_fail(tmp_path: Path) -> None:
    """Malformed IDs — regex check must fail, lowering score."""
    bad_ids = ["MD-D-G6-001", "INVALID-001", "MD-X-G6-001", "md-d-g6-001"]
    run_dir = _make_run_dir(tmp_path, claim_ids=bad_ids)
    result = run_score(run_dir)
    assert result < 9 / 9


def test_claim_id_regex_valid_patterns() -> None:
    """Spot-check the regex directly against known good/bad examples."""
    valid = [
        "MD-D-G6-001", "MD-D-G6-010", "MD-D-G12-099",
        "MD-C-G6-001", "MD-C-G6-009",
        "MD-C-G6-T01", "MD-C-G6F7-T08",  # omp critic threading variant
    ]
    invalid = [
        "MD-E-G6-001",   # wrong middle char
        "md-d-g6-001",   # lowercase
        "MD-D-G6-1",     # too few digits
        "MD-D-G6-0001",  # too many digits
        "MD-D-6-001",    # missing G prefix
        "MD-C-G6-T1",    # T-variant too few digits
        "MD-C-G6-T001",  # T-variant too many digits
        "MD-C-G6-t01",   # lowercase T
        "INVALID",
        "",
    ]
    for v in valid:
        assert CLAIM_ID_RE.match(v), f"Expected valid: {v}"
    for inv in invalid:
        assert not CLAIM_ID_RE.match(inv), f"Expected invalid: {inv}"


# ---------------------------------------------------------------------------
# Check 8: citation cross-check
# ---------------------------------------------------------------------------

def test_citation_cross_check_pass(tmp_path: Path) -> None:
    """Every MD-D-* claim has its .sql file — check 8 must pass."""
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-D-G6-002", "MD-C-G6-001"],
        include_queries_for=["MD-D-G6-001", "MD-D-G6-002"],
    )
    result = run_score(run_dir)
    assert result == pytest.approx(9 / 9)


def test_citation_cross_check_fail_missing_query(tmp_path: Path) -> None:
    """MD-D-* claim with no matching .sql — check 8 must fail."""
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-D-G6-002", "MD-C-G6-001"],
        include_queries_for=["MD-D-G6-001"],  # MD-D-G6-002 missing
    )
    result = run_score(run_dir)
    assert result < 9 / 9


def test_citation_cross_check_critic_no_query_required(tmp_path: Path) -> None:
    """MD-C-* claims are NOT required to have query files — check 8 still passes."""
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-C-G6-001"],
        include_queries_for=["MD-D-G6-001"],
    )
    result = run_score(run_dir)
    assert result == pytest.approx(9 / 9)


def test_citation_cross_check_empty_query_path_fails(tmp_path: Path) -> None:
    """MD-D-* claim with empty query_path — check 8 must fail."""
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-C-G6-001"],
        query_paths={"MD-D-G6-001": ""},
    )
    result = run_score(run_dir)
    assert result < 9 / 9


def test_citation_cross_check_multi_source_pass(tmp_path: Path) -> None:
    """Whitespace-separated multi-source query_path — all paths must exist."""
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-D-G6-002", "MD-C-G6-001"],
        query_paths={
            "MD-D-G6-001": "queries/MD-D-G6-001.sql queries/MD-D-G6-002.sql",
        },
    )
    result = run_score(run_dir)
    assert result == pytest.approx(9 / 9)


def test_citation_cross_check_multi_source_partial_missing(tmp_path: Path) -> None:
    """Multi-source with one missing path — check 8 must fail (real omp G6-005 bug)."""
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-D-G6-002", "MD-C-G6-001"],
        query_paths={
            # Second token missing .sql — won't resolve. Mirrors real omp drift.
            "MD-D-G6-001": "queries/MD-D-G6-001.sql MD-D-G6-002",
        },
    )
    result = run_score(run_dir)
    assert result < 9 / 9


def test_citation_cross_check_py_extractor_pass(tmp_path: Path) -> None:
    """Claim backed by .py extractor (not .sql) — check 8 must pass.

    Co-include a SQL-backed sibling claim so check 6 (queries/*.sql archived)
    still passes — the .py extractor case is about check 8 only.
    """
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-D-G6-002", "MD-C-G6-001"],
        query_paths={"MD-D-G6-001": "scripts/extract_meta_changelog.py"},
        include_queries_for=["MD-D-G6-002"],
    )
    scripts_dir = run_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "extract_meta_changelog.py").write_text("# extractor\n")
    result = run_score(run_dir)
    assert result == pytest.approx(9 / 9)


def test_citation_cross_check_bare_token_normalises_to_queries_dir(tmp_path: Path) -> None:
    """Bare filename token (no /) is resolved against queries/ subdir."""
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-C-G6-001"],
        query_paths={"MD-D-G6-001": "MD-D-G6-001.sql"},
    )
    result = run_score(run_dir)
    assert result == pytest.approx(9 / 9)


# ---------------------------------------------------------------------------
# Check 9: length prior
# ---------------------------------------------------------------------------

def test_length_prior_pass(tmp_path: Path) -> None:
    """Both findings files at 5000 bytes — within [2000, 50000]."""
    run_dir = _make_run_dir(tmp_path, analyst_bytes=5000, critic_bytes=5000)
    result = run_score(run_dir)
    assert result == pytest.approx(9 / 9)


def test_length_prior_fail_too_short(tmp_path: Path) -> None:
    """50-byte findings_analyst — stub-like, below 2000 lower bound."""
    run_dir = _make_run_dir(tmp_path, analyst_bytes=50, critic_bytes=5000)
    result = run_score(run_dir)
    assert result < 9 / 9


def test_length_prior_fail_too_long(tmp_path: Path) -> None:
    """200 KB findings_analyst — noise/blob, above 50000 upper bound."""
    run_dir = _make_run_dir(tmp_path, analyst_bytes=200_000, critic_bytes=5000)
    result = run_score(run_dir)
    assert result < 9 / 9


def test_length_prior_critic_too_short(tmp_path: Path) -> None:
    """50-byte findings_critic — stub-like, check 9 fails."""
    run_dir = _make_run_dir(tmp_path, analyst_bytes=5000, critic_bytes=50)
    result = run_score(run_dir)
    assert result < 9 / 9


def test_length_prior_boundary_min(tmp_path: Path) -> None:
    """Exactly FINDINGS_MIN_BYTES — should pass."""
    run_dir = _make_run_dir(
        tmp_path, analyst_bytes=FINDINGS_MIN, critic_bytes=FINDINGS_MIN
    )
    result = run_score(run_dir)
    assert result == pytest.approx(9 / 9)


def test_length_prior_boundary_max(tmp_path: Path) -> None:
    """Exactly FINDINGS_MAX_BYTES — should pass."""
    run_dir = _make_run_dir(
        tmp_path, analyst_bytes=FINDINGS_MAX, critic_bytes=FINDINGS_MAX
    )
    result = run_score(run_dir)
    assert result == pytest.approx(9 / 9)


# ---------------------------------------------------------------------------
# Integration: full 9-check score
# ---------------------------------------------------------------------------

def test_full_score_all_pass(tmp_path: Path) -> None:
    """Full fixture with all 9 checks passing — score == 1.0."""
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=["MD-D-G6-001", "MD-D-G6-002", "MD-C-G6-001"],
        analyst_bytes=7500,
        critic_bytes=8700,
    )
    result = run_score(run_dir)
    assert result == pytest.approx(1.0)


def test_full_score_with_failures(tmp_path: Path) -> None:
    """Two failures (malformed claim_id + missing query) → score 7/9."""
    claim_ids = ["MD-D-G6-001", "MD-D-G6-002", "INVALID-001", "MD-C-G6-001"]
    run_dir = _make_run_dir(
        tmp_path,
        claim_ids=claim_ids,
        analyst_bytes=5000,
        critic_bytes=5000,
        include_queries_for=["MD-D-G6-001"],
    )
    result = run_score(run_dir)
    assert result == pytest.approx(7 / 9)


def test_score_returns_float_between_zero_and_one(tmp_path: Path) -> None:
    """Score is always in [0.0, 1.0]."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    result = run_score(empty_dir)
    assert 0.0 <= result <= 1.0

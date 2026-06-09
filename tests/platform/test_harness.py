"""T17 — eval harness tests (V11, C10, C11).

Synthetic golden + negative (buggy-run) fixtures. No real business data, no
credentials — the real-data containerization is LOCAL-only (see eval/README.md).
"""
from __future__ import annotations

import json
from pathlib import Path

from insight_kit.platform.harness import (
    DiffClass,
    charts_byte_identical,
    check_replay_determinism,
    classify_field,
    diff_run_against_golden,
    load_golden,
    run_harness,
)

# ---------------------------------------------------------------------------
# Helpers — synthetic claim records + golden
# ---------------------------------------------------------------------------


def _claim(claim_id: str, fields: dict, **kw) -> dict:
    """Build a minimal claim record dict."""
    return {
        "record_type": "claim",
        "claim_id": claim_id,
        "fields": {k: {"value": v, "fmt_hint": None} for k, v in fields.items()},
        **kw,
    }


GOLDEN = {"ABC-D-001": {"gmv": 1200.0}, "ABC-D-002": {"orders": 50}}


# ---------------------------------------------------------------------------
# classify_field — the four classes
# ---------------------------------------------------------------------------


class TestClassifyField:
    def test_exact_match(self):
        claim = _claim("ABC-D-001", {"gmv": 1200.0})
        d = classify_field("ABC-D-001", "gmv", 1200.0, claim)
        assert d.classification == DiffClass.match

    def test_within_tolerance_is_match(self):
        claim = _claim("ABC-D-001", {"gmv": 1200.0000001})
        d = classify_field("ABC-D-001", "gmv", 1200.0, claim)
        assert d.classification == DiffClass.match

    def test_unexplained_difference_is_regression(self):
        claim = _claim("ABC-D-001", {"gmv": 9999.0})
        d = classify_field("ABC-D-001", "gmv", 1200.0, claim)
        assert d.classification == DiffClass.regression

    def test_difference_with_supersedes_is_legitimate(self):
        claim = _claim("ABC-D-001", {"gmv": 1350.0}, supersedes="oldrecordid")
        d = classify_field("ABC-D-001", "gmv", 1200.0, claim)
        assert d.classification == DiffClass.legitimate

    def test_difference_with_partial_period_is_coverage_drop(self):
        claim = _claim("ABC-D-001", {"gmv": 400.0}, coverage={"partial_period": True})
        d = classify_field("ABC-D-001", "gmv", 1200.0, claim)
        assert d.classification == DiffClass.coverage_drop

    def test_difference_with_low_n_is_coverage_drop(self):
        claim = _claim("ABC-D-001", {"gmv": 800.0}, coverage={"n": 12})
        d = classify_field("ABC-D-001", "gmv", 1200.0, claim)
        assert d.classification == DiffClass.coverage_drop

    def test_missing_claim_is_regression(self):
        d = classify_field("ABC-D-001", "gmv", 1200.0, None)
        assert d.classification == DiffClass.regression
        assert d.run_value is None

    def test_missing_field_is_regression(self):
        claim = _claim("ABC-D-001", {"other": 1})
        d = classify_field("ABC-D-001", "gmv", 1200.0, claim)
        assert d.classification == DiffClass.regression


# ---------------------------------------------------------------------------
# diff_run_against_golden + run_harness
# ---------------------------------------------------------------------------


class TestRunHarness:
    def test_clean_run_passes(self):
        run = [_claim("ABC-D-001", {"gmv": 1200.0}), _claim("ABC-D-002", {"orders": 50})]
        report = run_harness(run, GOLDEN)
        assert report.passed
        assert all(d.classification == DiffClass.match for d in report.diffs)

    def test_regression_fails_the_harness(self):
        run = [_claim("ABC-D-001", {"gmv": 9999.0}), _claim("ABC-D-002", {"orders": 50})]
        report = run_harness(run, GOLDEN)
        assert not report.passed
        assert len(report.regressions) == 1

    def test_coverage_drop_does_not_fail_harness(self):
        run = [
            _claim("ABC-D-001", {"gmv": 400.0}, coverage={"partial_period": True}),
            _claim("ABC-D-002", {"orders": 50}),
        ]
        report = run_harness(run, GOLDEN)
        assert report.passed
        assert len(report.by_class(DiffClass.coverage_drop)) == 1

    def test_legitimate_change_does_not_fail_harness(self):
        run = [
            _claim("ABC-D-001", {"gmv": 1350.0}, supersedes="rid"),
            _claim("ABC-D-002", {"orders": 50}),
        ]
        report = run_harness(run, GOLDEN)
        assert report.passed
        assert len(report.by_class(DiffClass.legitimate)) == 1

    def test_diff_covers_every_golden_field(self):
        diffs = diff_run_against_golden([], GOLDEN)
        assert {(d.claim_id, d.field) for d in diffs} == {
            ("ABC-D-001", "gmv"),
            ("ABC-D-002", "orders"),
        }


# ---------------------------------------------------------------------------
# Negative fixtures — buggy historical runs (C11 / RT6)
# ---------------------------------------------------------------------------


class TestNegativeFixtures:
    def test_buggy_run_is_flagged_as_regression(self):
        """RT6 — a buggy historical run must be caught, never certified.

        This is the negative fixture: a run with a known-wrong value and no
        supersedes / coverage reason. The harness MUST fail it.
        """
        buggy_run = [
            _claim("ABC-D-001", {"gmv": 12000.0}),  # 10x bug — misplaced decimal
            _claim("ABC-D-002", {"orders": 50}),
        ]
        report = run_harness(buggy_run, GOLDEN)
        assert not report.passed
        assert report.regressions[0].claim_id == "ABC-D-001"

    def test_buggy_run_not_excused_by_unrelated_supersedes(self):
        """A supersedes edge on a DIFFERENT claim does not excuse the bug."""
        buggy_run = [
            _claim("ABC-D-001", {"gmv": 12000.0}),
            _claim("ABC-D-002", {"orders": 999}, supersedes="rid"),
        ]
        report = run_harness(buggy_run, GOLDEN)
        assert not report.passed
        assert any(r.claim_id == "ABC-D-001" for r in report.regressions)


# ---------------------------------------------------------------------------
# V11 — replay determinism
# ---------------------------------------------------------------------------


class TestReplayDeterminism:
    def test_identical_runs_are_deterministic(self):
        run = [_claim("ABC-D-001", {"gmv": 1200.0})]
        result = check_replay_determinism(run, [_claim("ABC-D-001", {"gmv": 1200.0})])
        assert result.deterministic

    def test_value_drift_is_non_deterministic(self):
        run_a = [_claim("ABC-D-001", {"gmv": 1200.0})]
        run_b = [_claim("ABC-D-001", {"gmv": 1201.0})]
        result = check_replay_determinism(run_a, run_b)
        assert not result.deterministic
        assert len(result.mismatches) == 1

    def test_within_tolerance_is_deterministic(self):
        run_a = [_claim("ABC-D-001", {"gmv": 1200.0})]
        run_b = [_claim("ABC-D-001", {"gmv": 1200.0000001})]
        assert check_replay_determinism(run_a, run_b).deterministic

    def test_chart_byte_identical(self):
        assert charts_byte_identical('{"a":1}', '{"a":1}')
        assert not charts_byte_identical('{"a":1}', '{"a":2}')


# ---------------------------------------------------------------------------
# load_golden
# ---------------------------------------------------------------------------


def test_load_golden_from_json(tmp_path: Path):
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(GOLDEN), encoding="utf-8")
    assert load_golden(path) == GOLDEN

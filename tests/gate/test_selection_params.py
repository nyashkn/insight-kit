"""T11 — Selection params + Layer-C cross-check tests (V15).

Two halves:
  - SelectionParams: date-window / baseline / grain / filters emitted as
    explicit, structured claim fields (never implicit in prompt text).
  - check_annual_equals_monthly_sum: a standalone Layer-C invariant catching
    the partial-month / wrong-grain class (annual must equal sum of months).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from insight_kit.gate.emit import ik_claim_emit
from insight_kit.gate.runcheck import CrossCheckResult, check_annual_equals_monthly_sum
from insight_kit.gate.runstate import RunState
from insight_kit.gate.schema import ClaimRecord, SelectionParams
from insight_kit.gate.store import record_path


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


# ---------------------------------------------------------------------------
# SelectionParams schema
# ---------------------------------------------------------------------------


class TestSelectionParamsSchema:
    def test_round_trip(self):
        sel = SelectionParams(
            date_window="2026-03-01/2026-03-31",
            baseline="2026-02",
            grain="month",
            filters={"channel": "meta"},
        )
        assert sel.date_window == "2026-03-01/2026-03-31"
        assert sel.baseline == "2026-02"
        assert sel.grain == "month"
        assert sel.filters == {"channel": "meta"}

    def test_all_fields_optional(self):
        sel = SelectionParams()
        assert sel.date_window is None
        assert sel.baseline is None
        assert sel.grain is None
        assert sel.filters == {}

    def test_extra_field_rejected(self):
        with pytest.raises(PydanticValidationError):
            SelectionParams(window="oops")  # type: ignore[call-arg]

    def test_claim_record_carries_selection(self):
        rec = ClaimRecord(
            claim_id="TEST-D-001",
            fields={},
            selection=SelectionParams(date_window="2026-Q1", grain="quarter"),
        )
        assert rec.selection is not None
        assert rec.selection.grain == "quarter"

    def test_claim_record_selection_defaults_none(self):
        rec = ClaimRecord(claim_id="TEST-D-001", fields={})
        assert rec.selection is None


# ---------------------------------------------------------------------------
# ik_claim_emit — selection round-trip to record.json
# ---------------------------------------------------------------------------


class TestSelectionEmit:
    def test_selection_persisted_to_record(self, run_dir, state):
        ref = ik_claim_emit(
            "TEST-D-001",
            {"gmv": 1000},
            selection={"date_window": "2026-03-01/2026-03-31", "grain": "month"},
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["selection"]["date_window"] == "2026-03-01/2026-03-31"
        assert rec["selection"]["grain"] == "month"

    def test_no_selection_emits_null(self, run_dir, state):
        ref = ik_claim_emit("TEST-D-001", {"gmv": 1000}, run_state=state, run_dir=run_dir)
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["selection"] is None


# ---------------------------------------------------------------------------
# check_annual_equals_monthly_sum — Layer-C cross-check
# ---------------------------------------------------------------------------


class TestAnnualEqualsMonthlySum:
    def test_exact_match_passes(self):
        months = [100.0] * 12
        res = check_annual_equals_monthly_sum(1200.0, months)
        assert isinstance(res, CrossCheckResult)
        assert res.passed
        assert res.expected == 1200.0
        assert res.actual == 1200.0
        assert res.rel_diff == 0.0
        assert res.message

    def test_within_tolerance_passes(self):
        # 0.5% off, default tolerance 1%
        res = check_annual_equals_monthly_sum(1206.0, [100.0] * 12)
        assert res.passed

    def test_beyond_tolerance_fails(self):
        # annual claims 1500 but months sum to 1200 — 25% off
        res = check_annual_equals_monthly_sum(1500.0, [100.0] * 12)
        assert not res.passed
        assert res.expected == 1200.0
        assert res.rel_diff > 0.01
        assert "wrong-grain" in res.message or "partial-month" in res.message

    def test_tolerance_override(self):
        # 25% off but tolerance widened to 30% → passes
        res = check_annual_equals_monthly_sum(1500.0, [100.0] * 12, tolerance=0.30)
        assert res.passed

    def test_zero_expected_zero_actual_passes(self):
        res = check_annual_equals_monthly_sum(0.0, [0.0] * 12)
        assert res.passed
        assert res.rel_diff == 0.0

    def test_zero_expected_nonzero_actual_fails(self):
        res = check_annual_equals_monthly_sum(500.0, [0.0] * 12)
        assert not res.passed
        assert res.rel_diff == float("inf")

    def test_empty_monthly_list(self):
        res = check_annual_equals_monthly_sum(0.0, [])
        assert res.expected == 0.0
        assert res.passed

    def test_partial_month_scenario(self):
        """The real bug class: 11 full months + 1 partial month under-sums."""
        months = [100.0] * 11 + [40.0]  # December only month-to-date
        # analyst claims a full 1200 annual
        res = check_annual_equals_monthly_sum(1200.0, months)
        assert not res.passed  # 1140 actual sum vs 1200 claimed
        assert res.expected == 1140.0

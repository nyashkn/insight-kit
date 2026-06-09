"""T10 — Coverage-warning gate tests (V14).

A published-tier claim whose declared CoverageInfo is "thin" — partial_period
True, or sample size n < 30 — and which lacks a non-empty coverage_warning is
REJECTED at emit (hard reject, not a downgrade).

Ordering: the coverage gate runs AFTER the T7 tier gate, so a claim already
downgraded published->draft is no longer subject to this check.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.libs.validation import ValidationError as LayerAValidationError
from insight_kit.platform.gate.emit import ik_claim_emit
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import record_path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


FULL_FP_SET = {
    "data_fingerprint": "abc123",
    "code_fingerprint": "def456",
    "agent_version": "1.0.0",
    "env_fingerprint": "ghi789",
}


def _write_run_json(run_dir: Path, extra: dict | None = None) -> None:
    """Write a run.json so a published claim survives the T7 tier gate."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(extra or {}, sort_keys=True), encoding="utf-8"
    )


def _emit_published(run_dir: Path, state: RunState, **kw):
    """Emit a published claim that survives the tier gate (full fp set + registered input)."""
    _write_run_json(run_dir, FULL_FP_SET)
    return ik_claim_emit(
        "TEST-D-001",
        {"revenue": 100},
        tier="published",
        run_state=state,
        run_dir=run_dir,
        input_data=b"real-input-data",  # → data_fingerprint_source == registered_input
        **kw,
    )


# ---------------------------------------------------------------------------
# Reject — thin coverage, no warning
# ---------------------------------------------------------------------------


class TestCoverageRejects:
    def test_low_n_no_warning_rejected(self, run_dir, state):
        """published + coverage n<30 + no warning → reject (V14)."""
        with pytest.raises(LayerAValidationError) as exc:
            _emit_published(run_dir, state, coverage={"n": 10})
        assert exc.value.rule_id == "coverage-warning-missing"

    def test_partial_period_no_warning_rejected(self, run_dir, state):
        """published + partial_period + no warning → reject (V14)."""
        with pytest.raises(LayerAValidationError) as exc:
            _emit_published(run_dir, state, coverage={"partial_period": True})
        assert exc.value.rule_id == "coverage-warning-missing"

    def test_n_29_is_thin(self, run_dir, state):
        """n=29 is below the 30 threshold → thin → reject."""
        with pytest.raises(LayerAValidationError):
            _emit_published(run_dir, state, coverage={"n": 29})

    def test_empty_warning_string_treated_as_missing(self, run_dir, state):
        """coverage_warning='' (or whitespace) does not satisfy V14."""
        with pytest.raises(LayerAValidationError) as exc:
            _emit_published(
                run_dir, state, coverage={"n": 5}, coverage_warning="   "
            )
        assert exc.value.rule_id == "coverage-warning-missing"

    def test_reject_is_zero_partial_write(self, run_dir, state):
        """V2 — reject increments rejectionCount, writes nothing, registers nothing."""
        with pytest.raises(LayerAValidationError):
            _emit_published(run_dir, state, coverage={"n": 10})
        assert state.rejectionCount == 1
        assert len(state.records) == 0
        records_dir = run_dir / "records"
        assert not records_dir.exists() or not any(records_dir.iterdir())


# ---------------------------------------------------------------------------
# Accept — warning present, coverage adequate, or not published
# ---------------------------------------------------------------------------


class TestCoverageAccepts:
    def test_thin_coverage_with_warning_emits(self, run_dir, state):
        """published + thin coverage + coverage_warning → emits, stays published."""
        ref = _emit_published(
            run_dir,
            state,
            coverage={"n": 10},
            coverage_warning="sample of 10 orders only — directional",
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "published"
        assert state.rejectionCount == 0

    def test_adequate_n_no_warning_emits(self, run_dir, state):
        """n>=30 is adequate → no warning needed."""
        ref = _emit_published(run_dir, state, coverage={"n": 100})
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "published"

    def test_n_exactly_30_is_adequate(self, run_dir, state):
        """n=30 is the boundary — not thin (rule is n<30)."""
        ref = _emit_published(run_dir, state, coverage={"n": 30})
        assert state.rejectionCount == 0
        assert json.loads(record_path(run_dir, ref.record_id).read_text())["tier"] == "published"

    def test_coverage_present_but_not_thin_emits(self, run_dir, state):
        """coverage declared, partial_period False, n unknown → not thin → emits."""
        ref = _emit_published(run_dir, state, coverage={"partial_period": False})
        assert state.rejectionCount == 0
        assert record_path(run_dir, ref.record_id).exists()

    def test_no_coverage_declared_emits(self, run_dir, state):
        """No CoverageInfo → gate cannot assess → claim emits (V14 note)."""
        ref = _emit_published(run_dir, state)
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "published"

    def test_draft_thin_coverage_not_enforced(self, run_dir, state):
        """draft-tier claim with thin coverage + no warning → emits (V14 = published only)."""
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="draft",
            coverage={"n": 3},
            run_state=state,
            run_dir=run_dir,
        )
        assert state.rejectionCount == 0
        assert record_path(run_dir, ref.record_id).exists()


# ---------------------------------------------------------------------------
# Ordering — tier gate runs first
# ---------------------------------------------------------------------------


class TestCoverageGateOrdering:
    def test_downgraded_claim_skips_coverage_gate(self, run_dir, state):
        """A published claim downgraded to draft by the T7 tier gate (payload
        source) is no longer 'published' when the coverage gate runs — so thin
        coverage with no warning does NOT reject; it emits as draft."""
        # No input_data → payload source → T7 downgrades published->draft.
        _write_run_json(run_dir, FULL_FP_SET)
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            tier="published",
            coverage={"n": 5},  # thin, no warning
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["tier"] == "draft"
        assert state.rejectionCount == 0
        assert len(state.records) == 1

"""T23 — post-hoc utility verdict tests (V21, I.events).

The useful/not_useful verdict on a research/skill_use record is event-only: it
lands in records/{id}/events/utility_verdict.jsonl, append-only, and never
touches the immutable record.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.platform.gate.emit import (
    ik_claim_emit,
    ik_intervention_emit,
    ik_research_emit,
    ik_skill_use_emit,
)
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import events_dir, record_path
from insight_kit.platform.gate.verdict import (
    UTILITY_VERDICT_EVENT,
    UtilityVerdict,
    ik_utility_verdict,
)
from insight_kit.validation import ValidationError as LayerAValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


SNAPSHOT = {"results": "captured"}
TS = "2026-05-22T10:00:00+00:00"


def _research(run_dir, state, rid="RES-001"):
    return ik_research_emit(
        rid, "origin", "query", "source",
        snapshot=SNAPSHOT, timestamp=TS, run_state=state, run_dir=run_dir,
    )


def _skill_use(run_dir, state, sid="SKU-001"):
    return ik_skill_use_emit(
        sid, "origin", "tavily", "tavily-api",
        snapshot=SNAPSHOT, timestamp=TS, run_state=state, run_dir=run_dir,
    )


def _verdict_lines(run_dir: Path, record_id: str) -> list[dict]:
    log = events_dir(run_dir, record_id) / f"{UTILITY_VERDICT_EVENT}.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines() if line]


# ---------------------------------------------------------------------------
# Verdict appended as an event
# ---------------------------------------------------------------------------


class TestVerdictAppended:
    def test_useful_verdict_appended(self, run_dir, state):
        res = _research(run_dir, state)
        ik_utility_verdict(res.record_id, "useful", run_dir=run_dir)
        lines = _verdict_lines(run_dir, res.record_id)
        assert len(lines) == 1
        assert lines[0]["verdict"] == "useful"

    def test_not_useful_verdict_appended(self, run_dir, state):
        res = _research(run_dir, state)
        ik_utility_verdict(res.record_id, "not_useful", run_dir=run_dir)
        assert _verdict_lines(run_dir, res.record_id)[0]["verdict"] == "not_useful"

    def test_skill_use_verdict_ok(self, run_dir, state):
        sku = _skill_use(run_dir, state)
        ik_utility_verdict(sku.record_id, "useful", run_dir=run_dir)
        assert _verdict_lines(run_dir, sku.record_id)[0]["verdict"] == "useful"

    def test_verdict_lands_in_events_log(self, run_dir, state):
        """Returned path is records/{id}/events/utility_verdict.jsonl (I.events)."""
        res = _research(run_dir, state)
        path = ik_utility_verdict(res.record_id, "useful", run_dir=run_dir)
        assert path == events_dir(run_dir, res.record_id) / f"{UTILITY_VERDICT_EVENT}.jsonl"
        assert path.exists()

    def test_rationale_persisted(self, run_dir, state):
        res = _research(run_dir, state)
        ik_utility_verdict(
            res.record_id, "not_useful", run_dir=run_dir,
            rationale="superseded by a fresher source",
        )
        assert _verdict_lines(run_dir, res.record_id)[0]["rationale"] == (
            "superseded by a fresher source"
        )

    def test_default_timestamp_set(self, run_dir, state):
        res = _research(run_dir, state)
        ik_utility_verdict(res.record_id, "useful", run_dir=run_dir)
        assert _verdict_lines(run_dir, res.record_id)[0]["timestamp"]

    def test_utility_verdict_enum_values(self):
        assert {m.value for m in UtilityVerdict} == {"useful", "not_useful"}


# ---------------------------------------------------------------------------
# V21 — record.json stays immutable; verdict is append-only
# ---------------------------------------------------------------------------


class TestVerdictImmutabilityAndAppendOnly:
    def test_record_json_untouched_by_verdict(self, run_dir, state):
        """V21 — the verdict never edits record.json."""
        res = _research(run_dir, state)
        before = record_path(run_dir, res.record_id).read_bytes()
        ik_utility_verdict(res.record_id, "not_useful", run_dir=run_dir)
        after = record_path(run_dir, res.record_id).read_bytes()
        assert before == after

    def test_verdict_is_append_only(self, run_dir, state):
        """A revised verdict appends a new line — the log keeps both, latest wins."""
        res = _research(run_dir, state)
        ik_utility_verdict(res.record_id, "useful", run_dir=run_dir)
        ik_utility_verdict(
            res.record_id, "not_useful", run_dir=run_dir, rationale="reassessed",
        )
        lines = _verdict_lines(run_dir, res.record_id)
        assert len(lines) == 2
        assert lines[0]["verdict"] == "useful"
        assert lines[-1]["verdict"] == "not_useful"  # current verdict = last line


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


class TestVerdictRejections:
    def test_invalid_verdict_value_rejected(self, run_dir, state):
        res = _research(run_dir, state)
        with pytest.raises(LayerAValidationError) as exc:
            ik_utility_verdict(res.record_id, "maybe", run_dir=run_dir)
        assert exc.value.rule_id == "utility-verdict-invalid"

    def test_missing_target_rejected(self, run_dir):
        with pytest.raises(LayerAValidationError) as exc:
            ik_utility_verdict("deadbeefdeadbeef", "useful", run_dir=run_dir)
        assert exc.value.rule_id == "utility-verdict-target-missing"

    def test_verdict_on_claim_rejected(self, run_dir, state):
        """V21 — verdict applies only to knowledge records, not claims."""
        ref = ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        with pytest.raises(LayerAValidationError) as exc:
            ik_utility_verdict(ref.record_id, "useful", run_dir=run_dir)
        assert exc.value.rule_id == "utility-verdict-wrong-type"

    def test_verdict_on_intervention_rejected(self, run_dir, state):
        ref = ik_intervention_emit(
            "INT-001", {"description": "do thing"}, run_state=state, run_dir=run_dir
        )
        with pytest.raises(LayerAValidationError) as exc:
            ik_utility_verdict(ref.record_id, "useful", run_dir=run_dir)
        assert exc.value.rule_id == "utility-verdict-wrong-type"

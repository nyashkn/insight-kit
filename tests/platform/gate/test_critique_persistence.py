"""T27 — critique persistence tests.

Verifies that apply_critique, when called with run_dir, writes a
critique event to records/{id}/events/critique.jsonl (append-only,
never touches record.json). Mirrors the T23 utility-verdict pattern.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.platform.gate.emit import ik_claim_emit
from insight_kit.platform.gate.runstate import (
    CritiqueGateError,
    CritiqueState,
    RunState,
    apply_critique,
)
from insight_kit.platform.gate.store import events_dir, record_path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CLAIM_ID = "DEMO-D-128"
FIELDS = {"value": 42}


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


def _emit_claim(run_dir: Path, state: RunState, claim_id: str = CLAIM_ID) -> str:
    """Emit a real claim record and return its content-addressed record_id."""
    ref = ik_claim_emit(
        claim_id,
        FIELDS,
        tier="draft",
        run_state=state,
        run_dir=run_dir,
    )
    return ref.record_id


def _critique_lines(run_dir: Path, record_id: str) -> list[dict]:
    log = events_dir(run_dir, record_id) / "critique.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines() if line]


# ---------------------------------------------------------------------------
# T27 — tests
# ---------------------------------------------------------------------------


def test_critique_persisted_to_events(run_dir: Path, state: RunState) -> None:
    """apply_critique with run_dir writes records/{id}/events/critique.jsonl."""
    record_id = _emit_claim(run_dir, state)
    critique = CritiqueState.open(severity="medium", reason="check window")

    apply_critique(
        run_state=state,
        record_id=record_id,
        record_type="claim",
        tier="published",
        audience=None,
        critique=critique,
        run_dir=run_dir,
    )

    ev_path = events_dir(run_dir, record_id) / "critique.jsonl"
    assert ev_path.exists(), "critique.jsonl must be created after apply_critique"
    lines = _critique_lines(run_dir, record_id)
    assert len(lines) == 1


def test_critique_event_fields(run_dir: Path, state: RunState) -> None:
    """The persisted critique line carries the required fields with correct types."""
    record_id = _emit_claim(run_dir, state)
    critique = CritiqueState.open(severity="medium", reason="check window")
    # Optionally set critic_id / target_record_id / timestamp if the dataclass supports them
    try:
        critique = CritiqueState(
            status="open",
            severity=critique.severity,
            reason="check window",
            critic_id="reviewer-1",
            target_record_id=record_id,
            timestamp="2026-06-08T12:00:00+00:00",
        )
        has_provenance_fields = True
    except TypeError:
        # Fields not yet added — test the base fields only
        has_provenance_fields = False

    apply_critique(
        run_state=state,
        record_id=record_id,
        record_type="claim",
        tier="published",
        audience=None,
        critique=critique,
        run_dir=run_dir,
    )

    line = _critique_lines(run_dir, record_id)[0]

    assert line["status"] == "open"
    assert line["severity"] == "medium", "severity must be the .name string, not an int"
    assert line["reason"] == "check window"
    assert line["target_record_id"] == record_id
    assert line["timestamp"], "timestamp must be non-empty"

    if has_provenance_fields:
        assert line["critic_id"] == "reviewer-1"


def test_record_json_unchanged_after_critique(run_dir: Path, state: RunState) -> None:
    """V3 — apply_critique must never touch record.json (byte-identical before/after)."""
    record_id = _emit_claim(run_dir, state)
    before = record_path(run_dir, record_id).read_bytes()

    critique = CritiqueState.open(severity="medium", reason="immutability check")
    apply_critique(
        run_state=state,
        record_id=record_id,
        record_type="claim",
        tier="published",
        audience=None,
        critique=critique,
        run_dir=run_dir,
    )

    after = record_path(run_dir, record_id).read_bytes()
    assert before == after, "record.json must be byte-identical after apply_critique"


def test_multiple_critiques_append(run_dir: Path, state: RunState) -> None:
    """Two apply_critique calls on the same record append two lines (never overwrite)."""
    record_id = _emit_claim(run_dir, state)

    for reason in ("first critique", "second critique"):
        apply_critique(
            run_state=state,
            record_id=record_id,
            record_type="claim",
            tier="published",
            audience=None,
            critique=CritiqueState.open(severity="low", reason=reason),
            run_dir=run_dir,
        )

    lines = _critique_lines(run_dir, record_id)
    assert len(lines) == 2, "critique.jsonl must have 2 lines after 2 calls (append-only)"
    assert lines[0]["reason"] == "first critique"
    assert lines[1]["reason"] == "second critique"


def test_run_dir_none_writes_nothing_and_same_return(run_dir: Path, state: RunState) -> None:
    """Back-compat: apply_critique without run_dir returns the gate dict and writes nothing."""
    record_id = _emit_claim(run_dir, state)
    critique = CritiqueState.open(severity="low", reason="back-compat check")

    result = apply_critique(
        run_state=state,
        record_id=record_id,
        record_type="claim",
        tier="published",
        audience=None,
        critique=critique,
        # run_dir intentionally omitted
    )

    assert result == {"downgraded": False, "tier": "published"}, (
        "return dict must be unchanged when run_dir is not passed"
    )
    ev_dir = events_dir(run_dir, record_id)
    assert not ev_dir.exists(), "events/ dir must not be created when run_dir=None"


def test_raise_path_still_persists(run_dir: Path, state: RunState) -> None:
    """CritiqueGateError path: the critique event is written BEFORE the raise."""
    record_id = _emit_claim(run_dir, state)
    # Fresh RunState: critiqueRounds=0, below cap → will raise
    fresh_state = RunState()
    critique = CritiqueState.open(severity="high", reason="hard gate")

    with pytest.raises(CritiqueGateError):
        apply_critique(
            run_state=fresh_state,
            record_id=record_id,
            record_type="claim",
            tier="published",
            audience=None,
            critique=critique,
            run_dir=run_dir,
        )

    ev_path = events_dir(run_dir, record_id) / "critique.jsonl"
    assert ev_path.exists(), "critique.jsonl must exist even when CritiqueGateError is raised"
    lines = _critique_lines(run_dir, record_id)
    assert len(lines) == 1, "exactly 1 critique line must be written before the raise"
    assert lines[0]["severity"] == "high"

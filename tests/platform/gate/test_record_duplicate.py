"""V2 — content-address collision must raise structured ValidationError + rejectionCount++.

When an identical research record is re-emitted (research has no per-run claim_id
duplicate guard), write_record raises FileExistsError.  emit.py must translate that
into a LayerAValidationError(rule_id="record-duplicate") and increment rejectionCount,
while leaving RunState.records at its pre-collision length.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.libs.validation import ValidationError as LayerAValidationError
from insight_kit.platform.gate.emit import ik_research_emit
from insight_kit.platform.gate.runstate import RunState


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


def test_duplicate_research_raises_structured_error(run_dir, state):
    """Re-emitting an identical research record raises ValidationError(rule_id='record-duplicate')."""
    kwargs = dict(
        research_id="RES-001",
        snapshot_ref="s/r.json",
        query="what is X",
        source="web",
        timestamp="2026-05-22T10:00:00+00:00",
        snapshot={"results": "found X"},
        run_state=state,
        run_dir=run_dir,
    )
    # First emit succeeds
    ik_research_emit(**kwargs)
    assert state.rejectionCount == 0

    # Second identical emit must raise a structured ValidationError
    with pytest.raises(LayerAValidationError) as exc_info:
        ik_research_emit(**kwargs)

    assert exc_info.value.rule_id == "record-duplicate"


def test_duplicate_research_increments_rejection_count(run_dir, state):
    """rejectionCount must be 1 after the duplicate is rejected."""
    kwargs = dict(
        research_id="RES-001",
        snapshot_ref="s/r.json",
        query="what is X",
        source="web",
        timestamp="2026-05-22T10:00:00+00:00",
        snapshot={"results": "found X"},
        run_state=state,
        run_dir=run_dir,
    )
    ik_research_emit(**kwargs)
    try:
        ik_research_emit(**kwargs)
    except LayerAValidationError:
        pass

    assert state.rejectionCount == 1


def test_duplicate_research_records_length_unchanged(run_dir, state):
    """RunState.records must not grow on a rejected duplicate."""
    kwargs = dict(
        research_id="RES-001",
        snapshot_ref="s/r.json",
        query="what is X",
        source="web",
        timestamp="2026-05-22T10:00:00+00:00",
        snapshot={"results": "found X"},
        run_state=state,
        run_dir=run_dir,
    )
    ik_research_emit(**kwargs)
    length_after_first = len(state.records)

    try:
        ik_research_emit(**kwargs)
    except LayerAValidationError:
        pass

    assert len(state.records) == length_after_first

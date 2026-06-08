"""T26 — Supersedes chain integrity wiring tests.

Validates that the emit gate rejects superseding an already-superseded claim
(closes V3 hole) via the check_supersedes_chain_integrity guard wired into
_run_layer_a_guards (emit.py:103-114).

The guard fires only when a kit_root is resolvable from run_dir AND a prior
run's claims.jsonl already records the target's record_id in a `supersedes`
field.  The `supersedes` field on emit stores a record_id (hex hash), not a
claim_id — so fixtures must write prior claims.jsonl rows that reference the
correct record_id.

Strategy: emit the target claim in a simulated "run1" (which naturally writes
claims.jsonl), then write an additional claims.jsonl row in run1 that records
"somebody supersedes that record_id" — simulating a prior supersession.  Then
in a current "run2", attempt to supersede the same record_id again.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.libs.provenance.root import find_kit_root, kit_config
from insight_kit.libs.validation import ValidationError as LayerAValidationError
from insight_kit.platform.gate.emit import ik_claim_emit
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import record_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kit_root(tmp_path: Path) -> Path:
    """Scaffold a minimal .insight-kit/runs/ tree at tmp_path.

    Returns tmp_path (the kit root).  Does NOT call init_kit — we only need
    .insight-kit/runs/ for the guard to scan.
    """
    (tmp_path / ".insight-kit" / "runs").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _emit_claim(claim_id: str, run_dir: Path, state: RunState, **kwargs):
    """Convenience wrapper around ik_claim_emit with minimal required fields."""
    return ik_claim_emit(
        claim_id,
        {"value": 1},
        run_state=state,
        run_dir=run_dir,
        **kwargs,
    )


def _append_supersedes_row(claims_jsonl: Path, successor_claim_id: str, supersedes_record_id: str) -> None:
    """Append a claims.jsonl row that records a supersession from a prior run.

    The guard reads rec.get("supersedes") from claims.jsonl lines.  We append
    a row whose "supersedes" value is the record_id (hex hash) of the target —
    simulating a prior run where someone already superseded that record.
    """
    row = {
        "record_type": "claim",
        "claim_id": successor_claim_id,
        "supersedes": supersedes_record_id,
    }
    with claims_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_lru_cache():
    """Clear find_kit_root and kit_config LRU caches before and after each test.

    find_kit_root uses @lru_cache(maxsize=1) — a cached root from a prior test
    would bypass the FileNotFoundError that the no-kit-root test relies on.
    """
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    yield
    find_kit_root.cache_clear()
    kit_config.cache_clear()


@pytest.fixture
def kit_root(tmp_path: Path) -> Path:
    """Minimal kit root with .insight-kit/runs/ at tmp_path."""
    return _make_kit_root(tmp_path)


# ---------------------------------------------------------------------------
# Scenario builder — shared across the first three tests
# ---------------------------------------------------------------------------


def _build_already_superseded_scenario(kit_root: Path):
    """Emit AAA-D-001 in run1, mark it as already-superseded, return (run2, state, record_id).

    1. Emit AAA-D-001 into run1 — this writes run1/claims.jsonl.
    2. Append a row to run1/claims.jsonl recording that AAA-D-999 supersedes
       AAA-D-001's record_id — simulating a prior supersession in that run.
    3. Return run2 path + a fresh RunState ready for the current-run tests.
    """
    run1 = kit_root / ".insight-kit" / "runs" / "run1"
    state1 = RunState()
    ref1 = _emit_claim("AAA-D-001", run1, state1)
    target_record_id = ref1.record_id  # hex hash, e.g. "5cea9f067b0eec9d"

    # Mark target_record_id as already superseded in run1
    claims_jsonl = run1 / "claims.jsonl"
    _append_supersedes_row(claims_jsonl, "AAA-D-999", target_record_id)

    run2 = kit_root / ".insight-kit" / "runs" / "run2"
    state2 = RunState()
    return run2, state2, target_record_id


# ---------------------------------------------------------------------------
# T26 — V3 chain integrity: reject superseding an already-superseded claim
# ---------------------------------------------------------------------------


class TestSupersedesChainWiring:
    def test_supersede_already_superseded_raises(self, kit_root: Path):
        """Superseding a record that already has a successor in a prior run → reject."""
        run2, state, target_record_id = _build_already_superseded_scenario(kit_root)

        # Emit AAA-D-001 into run2 so _check_supersedes_exists passes
        _emit_claim("AAA-D-001", run2, state)
        emitted_record_id = state.records[0].record_id
        # emitted_record_id == target_record_id (same payload → same fingerprint)
        assert emitted_record_id == target_record_id

        # Now attempt to supersede AAA-D-001 — already superseded in run1
        with pytest.raises(LayerAValidationError, match="supersedes-already-deprecated"):
            _emit_claim("AAA-D-002", run2, state, supersedes=target_record_id)

    def test_chain_rejection_increments_rejection_count(self, kit_root: Path):
        """Rejected chain supersession increments RunState.rejectionCount."""
        run2, state, target_record_id = _build_already_superseded_scenario(kit_root)

        _emit_claim("AAA-D-001", run2, state)

        try:
            _emit_claim("AAA-D-002", run2, state, supersedes=target_record_id)
        except LayerAValidationError:
            pass

        assert state.rejectionCount == 1

    def test_chain_no_partial_write(self, kit_root: Path):
        """No record.json is written for the rejected superseding claim."""
        run2, state, target_record_id = _build_already_superseded_scenario(kit_root)

        _emit_claim("AAA-D-001", run2, state)

        try:
            _emit_claim("AAA-D-002", run2, state, supersedes=target_record_id)
        except LayerAValidationError:
            pass

        # Only AAA-D-001 should have been written; the rejected AAA-D-002 must not exist.
        assert len(state.records) == 1, "only the first claim should be registered in run_state"
        records_dir = run2 / "records"
        written_ids = [p.parent.name for p in records_dir.glob("*/record.json")]
        assert len(written_ids) == 1, f"expected 1 written record, found: {written_ids}"

    def test_fresh_supersede_still_passes(self, kit_root: Path):
        """Superseding a claim with no prior successor succeeds (no false positive).

        run1 has AAA-D-000 with no supersedes entry pointing at our target —
        so AAA-D-001's record_id is free to be superseded.
        """
        # Write a run1 claims.jsonl that does NOT reference AAA-D-001 as superseded
        run1 = kit_root / ".insight-kit" / "runs" / "run1"
        run1.mkdir(parents=True, exist_ok=True)
        # Write an unrelated row (supersedes a different claim)
        (run1 / "claims.jsonl").write_text(
            json.dumps({"record_type": "claim", "claim_id": "AAA-D-000", "supersedes": None}) + "\n",
            encoding="utf-8",
        )

        run2 = kit_root / ".insight-kit" / "runs" / "run2"
        state = RunState()

        ref1 = _emit_claim("AAA-D-001", run2, state)
        ref2 = _emit_claim("AAA-D-002", run2, state, supersedes=ref1.record_id)

        rec2 = json.loads(record_path(run2, ref2.record_id).read_text())
        assert rec2["supersedes"] == ref1.record_id

    def test_no_kit_root_skips_chain_guard(self, tmp_path: Path):
        """When run_dir has no .insight-kit/ ancestor, chain guard is skipped.

        find_kit_root raises FileNotFoundError → guard is bypassed → emit succeeds.
        This is the back-compat path that keeps test_supersession.py green.
        """
        # Isolated run_dir with NO .insight-kit/ in any ancestor
        run_dir = tmp_path / "run"
        state = RunState()

        ref1 = _emit_claim("AAA-D-001", run_dir, state)
        ref2 = _emit_claim("AAA-D-002", run_dir, state, supersedes=ref1.record_id)

        rec2 = json.loads(record_path(run_dir, ref2.record_id).read_text())
        assert rec2["supersedes"] == ref1.record_id
        assert state.rejectionCount == 0

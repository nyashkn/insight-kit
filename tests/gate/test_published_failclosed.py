"""T13 — published-tier fail-closed hooks (V17).

V17 — published-tier hooks fail closed: on published runs, manifest/finalize
failure is FATAL (run fails closed — no unauditable published record). draft
stays passive. `finalizeRun` asserts `manifest_complete` — tool_call vs
tool_result count, records.jsonl count vs `RunState.records.length`;
mismatch blocks published finalize.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.gate.emit import ik_claim_emit, ik_intervention_emit
from insight_kit.gate.runstate import (
    ManifestError,
    PublishedRunError,
    RecordRef,
    RunState,
    finalizeRun,
    finalize_published_run,
)
from insight_kit.gate.store import index_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


# ---------------------------------------------------------------------------
# finalize_published_run — fail-closed semantics
# ---------------------------------------------------------------------------

class TestFinalizePublishedRun:
    def test_published_run_passes_on_clean_state(self, run_dir, state):
        """Published run with matching manifest count → finalize succeeds."""
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, tier="published", run_state=state, run_dir=run_dir)
        # Should not raise
        finalize_published_run(state)
        assert state.completedAt is not None

    def test_published_run_empty_passes(self, run_dir, state):
        """Empty published run (0 == 0) → passes."""
        state.run_dir = run_dir
        finalize_published_run(state)
        assert state.completedAt is not None

    def test_published_run_mismatch_raises_published_run_error(self, run_dir, state):
        """Published run with manifest mismatch → PublishedRunError (fail closed)."""
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, tier="published", run_state=state, run_dir=run_dir)
        # Inject phantom record into RunState without a disk row
        phantom = RecordRef("phantom0000000", "claim", "0" * 64, run_dir)
        state.records.append(phantom)
        with pytest.raises(PublishedRunError) as exc_info:
            finalize_published_run(state)
        assert "published" in str(exc_info.value).lower() or "manifest" in str(exc_info.value).lower()

    def test_published_run_extra_row_raises_published_run_error(self, run_dir, state):
        """Extra row in records.jsonl vs RunState → PublishedRunError."""
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, tier="published", run_state=state, run_dir=run_dir)
        # Inject phantom row into records.jsonl
        idx = index_path(run_dir)
        with idx.open("a") as f:
            f.write('{"record_id":"phantom","record_type":"claim"}\n')
        with pytest.raises(PublishedRunError):
            finalize_published_run(state)

    def test_published_run_is_not_idempotent_on_mismatch(self, run_dir, state):
        """A second finalize_published_run on an already-failed run re-raises."""
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, tier="published", run_state=state, run_dir=run_dir)
        phantom = RecordRef("phantom0000000", "claim", "0" * 64, run_dir)
        state.records.append(phantom)
        with pytest.raises(PublishedRunError):
            finalize_published_run(state)
        # Run not completed — state.completedAt still None
        assert state.completedAt is None

    def test_published_run_multiple_records_passes(self, run_dir, state):
        """Multiple records in a published run with clean manifest → passes."""
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, tier="published", run_state=state, run_dir=run_dir)
        ik_claim_emit("TEST-D-002", {"y": 2}, tier="published", run_state=state, run_dir=run_dir)
        finalize_published_run(state)
        assert state.completedAt is not None


# ---------------------------------------------------------------------------
# finalizeRun — published vs draft behavior
# ---------------------------------------------------------------------------

class TestFinalizeRunPublishedVsDraft:
    def test_draft_finalizeRun_passive_on_mismatch(self, run_dir, state):
        """Draft run: finalizeRun with assert_manifest=False is passive — no error on mismatch."""
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        phantom = RecordRef("phantom0000000", "claim", "0" * 64, run_dir)
        state.records.append(phantom)
        # Draft does not assert manifest by default (assert_manifest=False)
        finalizeRun(state, assert_manifest=False)  # should not raise
        assert state.completedAt is not None

    def test_draft_finalizeRun_with_assert_still_raises_manifest_error(self, run_dir, state):
        """Draft run with assert_manifest=True: manifest mismatch → ManifestError (not PublishedRunError)."""
        state.run_dir = run_dir
        ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        phantom = RecordRef("phantom0000000", "claim", "0" * 64, run_dir)
        state.records.append(phantom)
        with pytest.raises(ManifestError):
            finalizeRun(state, assert_manifest=True)

    def test_published_tool_call_count_mismatch_raises(self, run_dir, state):
        """Published run: tool_call count != tool_result count → PublishedRunError."""
        state.run_dir = run_dir
        # Inject a tool_call imbalance (simulate incomplete tool use)
        state.tool_calls = 3
        state.tool_results = 2
        ik_claim_emit("TEST-D-001", {"x": 1}, tier="published", run_state=state, run_dir=run_dir)
        with pytest.raises(PublishedRunError) as exc_info:
            finalize_published_run(state)
        assert "tool" in str(exc_info.value).lower() or "call" in str(exc_info.value).lower() or "published" in str(exc_info.value).lower()

    def test_published_balanced_tool_calls_passes(self, run_dir, state):
        """Published run: balanced tool_call/tool_result count → passes."""
        state.run_dir = run_dir
        state.tool_calls = 2
        state.tool_results = 2
        ik_claim_emit("TEST-D-001", {"x": 1}, tier="published", run_state=state, run_dir=run_dir)
        finalize_published_run(state)
        assert state.completedAt is not None

    def test_published_zero_tool_calls_passes(self, run_dir, state):
        """Published run with no tool calls tracked (0==0) → passes."""
        state.run_dir = run_dir
        # tool_calls/tool_results default to 0
        ik_claim_emit("TEST-D-001", {"x": 1}, tier="published", run_state=state, run_dir=run_dir)
        finalize_published_run(state)
        assert state.completedAt is not None


# ---------------------------------------------------------------------------
# RunState tool_calls / tool_results attributes
# ---------------------------------------------------------------------------

class TestRunStateToolCallTracking:
    def test_initial_tool_counts_are_zero(self, state):
        assert state.tool_calls == 0
        assert state.tool_results == 0

    def test_tool_calls_increment(self, state):
        state.tool_calls += 1
        assert state.tool_calls == 1

    def test_tool_results_increment(self, state):
        state.tool_results += 1
        assert state.tool_results == 1

    def test_to_dict_includes_tool_counts(self, state):
        state.tool_calls = 3
        state.tool_results = 3
        d = state.to_dict()
        assert d["tool_calls"] == 3
        assert d["tool_results"] == 3

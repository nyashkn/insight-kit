"""T22 — research/skill_use knowledge records (V20, I.cites).

Two halves:
  - Snapshot persistence: a research/skill_use emit must carry a non-empty
    captured-results snapshot. emit persists it as records/{id}/snapshot.json
    and folds its sha256 (snapshot_fingerprint) into record_fingerprint, so the
    snapshot is content-addressed and tamper-evident.
  - cites-edge integrity: every id in a record's `cites` list must resolve to an
    existing research/skill_use record. The cites edge is the knowledge-
    provenance chain — it never points at a claim/intervention (use `supersedes`
    to correct those).
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
from insight_kit.platform.gate.fingerprint import data_fingerprint
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import record_path, snapshot_path
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


SNAPSHOT = {"results": ["row-a", "row-b"], "n": 2}
TS = "2026-05-22T10:00:00+00:00"


def _emit_research(run_dir, state, *, research_id="RES-001", snapshot=None, **kw):
    return ik_research_emit(
        research_id,
        "https://example.com/source",
        "what is the market size",
        "perplexity",
        snapshot=snapshot if snapshot is not None else SNAPSHOT,
        timestamp=TS,
        run_state=state,
        run_dir=run_dir,
        **kw,
    )


def _emit_skill_use(run_dir, state, *, skill_use_id="SKU-001", snapshot=None, **kw):
    return ik_skill_use_emit(
        skill_use_id,
        "tavily-cache-key",
        "tavily-search",
        "tavily",
        snapshot=snapshot if snapshot is not None else SNAPSHOT,
        timestamp=TS,
        run_state=state,
        run_dir=run_dir,
        **kw,
    )


# ---------------------------------------------------------------------------
# Snapshot persistence + hashing (V20)
# ---------------------------------------------------------------------------


class TestSnapshotPersistence:
    def test_research_snapshot_persisted_to_bundle(self, run_dir, state):
        """research emit writes records/{id}/snapshot.json with the payload."""
        ref = _emit_research(run_dir, state)
        snap_file = snapshot_path(run_dir, ref.record_id)
        assert snap_file.exists()
        assert json.loads(snap_file.read_text()) == SNAPSHOT

    def test_skill_use_snapshot_persisted_to_bundle(self, run_dir, state):
        ref = _emit_skill_use(run_dir, state)
        snap_file = snapshot_path(run_dir, ref.record_id)
        assert snap_file.exists()
        assert json.loads(snap_file.read_text()) == SNAPSHOT

    def test_snapshot_fingerprint_in_record(self, run_dir, state):
        """record.json carries snapshot_fingerprint — 64-hex sha256."""
        ref = _emit_research(run_dir, state)
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["snapshot_fingerprint"] is not None
        assert len(rec["snapshot_fingerprint"]) == 64

    def test_snapshot_fingerprint_is_sha256_of_payload(self, run_dir, state):
        """snapshot_fingerprint == data_fingerprint(snapshot) — exact formula."""
        ref = _emit_research(run_dir, state)
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["snapshot_fingerprint"] == data_fingerprint(SNAPSHOT)

    def test_snapshot_content_addressed(self, run_dir, state):
        """Two research records identical except for snapshot → different
        record_id: the snapshot is folded into the content address."""
        ref_a = _emit_research(run_dir, state, snapshot={"results": "A"})
        ref_b = _emit_research(run_dir, state, snapshot={"results": "B"})
        assert ref_a.record_id != ref_b.record_id

    def test_claim_records_have_no_snapshot_file(self, run_dir, state):
        """Snapshot persistence is knowledge-record only — claims get none."""
        ref = ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        assert not snapshot_path(run_dir, ref.record_id).exists()


# ---------------------------------------------------------------------------
# Snapshot required — missing/empty snapshot rejects
# ---------------------------------------------------------------------------


class TestSnapshotRequired:
    def test_empty_research_snapshot_rejected(self, run_dir, state):
        """research emit with snapshot={} → reject (V20)."""
        with pytest.raises(LayerAValidationError) as exc:
            _emit_research(run_dir, state, snapshot={})
        assert exc.value.rule_id == "knowledge-snapshot-missing"

    def test_empty_skill_use_snapshot_rejected(self, run_dir, state):
        with pytest.raises(LayerAValidationError) as exc:
            _emit_skill_use(run_dir, state, snapshot={})
        assert exc.value.rule_id == "knowledge-snapshot-missing"

    def test_empty_snapshot_is_zero_partial_write(self, run_dir, state):
        """V2 — reject increments rejectionCount, writes nothing."""
        with pytest.raises(LayerAValidationError):
            _emit_research(run_dir, state, snapshot={})
        assert state.rejectionCount == 1
        assert len(state.records) == 0
        records_dir = run_dir / "records"
        assert not records_dir.exists() or not any(records_dir.iterdir())


# ---------------------------------------------------------------------------
# cites-edge integrity (I.cites, V20)
# ---------------------------------------------------------------------------


class TestCitesEdgeIntegrity:
    def test_claim_cites_research_ok(self, run_dir, state):
        """A claim citing an existing research record emits, edge persisted."""
        res = _emit_research(run_dir, state)
        ref = ik_claim_emit(
            "TEST-D-001", {"x": 1}, cites=[res.record_id], run_state=state, run_dir=run_dir
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["cites"] == [res.record_id]

    def test_claim_cites_skill_use_ok(self, run_dir, state):
        sku = _emit_skill_use(run_dir, state)
        ref = ik_claim_emit(
            "TEST-D-001", {"x": 1}, cites=[sku.record_id], run_state=state, run_dir=run_dir
        )
        assert json.loads(record_path(run_dir, ref.record_id).read_text())["cites"] == [
            sku.record_id
        ]

    def test_intervention_cites_research_ok(self, run_dir, state):
        res = _emit_research(run_dir, state)
        ref = ik_intervention_emit(
            "INT-001",
            {"description": "act on the research"},
            cites=[res.record_id],
            run_state=state,
            run_dir=run_dir,
        )
        assert json.loads(record_path(run_dir, ref.record_id).read_text())["cites"] == [
            res.record_id
        ]

    def test_research_can_cite_skill_use(self, run_dir, state):
        """A knowledge chain — research citing the skill_use that fed it — is
        allowed: the cites target is still a knowledge record."""
        sku = _emit_skill_use(run_dir, state)
        ref = _emit_research(run_dir, state, cites=[sku.record_id])
        assert json.loads(record_path(run_dir, ref.record_id).read_text())["cites"] == [
            sku.record_id
        ]

    def test_dangling_cite_rejected(self, run_dir, state):
        """cites pointing to a nonexistent record → reject (I.cites)."""
        with pytest.raises(LayerAValidationError) as exc:
            ik_claim_emit(
                "TEST-D-001",
                {"x": 1},
                cites=["deadbeefdeadbeef"],
                run_state=state,
                run_dir=run_dir,
            )
        assert exc.value.rule_id == "cites-not-found"

    def test_cite_to_claim_rejected(self, run_dir, state):
        """cites must point at a knowledge record — citing a claim → reject.
        (Claim→claim corrections use `supersedes`, not `cites`.)"""
        first = ik_claim_emit("TEST-D-001", {"x": 1}, run_state=state, run_dir=run_dir)
        with pytest.raises(LayerAValidationError) as exc:
            ik_claim_emit(
                "TEST-D-002",
                {"y": 2},
                cites=[first.record_id],
                run_state=state,
                run_dir=run_dir,
            )
        assert exc.value.rule_id == "cites-wrong-type"

    def test_cite_to_intervention_rejected(self, run_dir, state):
        intv = ik_intervention_emit(
            "INT-001", {"description": "do thing"}, run_state=state, run_dir=run_dir
        )
        with pytest.raises(LayerAValidationError) as exc:
            ik_claim_emit(
                "TEST-D-001",
                {"x": 1},
                cites=[intv.record_id],
                run_state=state,
                run_dir=run_dir,
            )
        assert exc.value.rule_id == "cites-wrong-type"

    def test_bad_cite_is_zero_partial_write(self, run_dir, state):
        """V2 — a rejected cite writes nothing, increments rejectionCount."""
        res = _emit_research(run_dir, state)
        with pytest.raises(LayerAValidationError):
            ik_claim_emit(
                "TEST-D-001",
                {"x": 1},
                cites=[res.record_id, "missing-id"],
                run_state=state,
                run_dir=run_dir,
            )
        assert state.rejectionCount == 1
        # only the research record landed
        assert len(state.records) == 1

"""Cross-run workspace substrate (I.workspace) — dated run dirs, runs.jsonl
manifest, claim history queries, persistent refuted-claim republish guard.

The guard closes the confirmed review hole: the duplicate/refutation guard is
in-memory per-run only, so a critic-refuted claim could be silently re-emitted
in a fresh run.  standing_refutations makes verdicts persistent (latest
VERDICTED sighting wins; an unverdicted re-emission does not clear).

Cites: V3 (never adopt a bundle), V7 (regenerable manifest), V10 (idempotent
seal), V16 (record-then-enforce critique).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.libs.validation import CLAIM_ID_REGEX
from insight_kit.platform.gate import (
    CrossCheckResult,
    RunEntry,
    RunState,
    claim_by_id,
    claim_history,
    emit_reconciliation_critique,
    guard_republished_claims,
    ik_claim_emit,
    list_runs,
    new_run_dir,
    reindex_runs,
    seal_run,
    standing_refutations,
)
from insight_kit.platform.gate.store import read_record

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL_FP_SET = {
    "data_fingerprint": "abc123",
    "code_fingerprint": "def456",
    "agent_version": "1.0.0",
    "env_fingerprint": "ghi789",
}


def _sealed_run(
    ws: Path,
    run_id: str,
    claim_id: str,
    *,
    verdict: str | None = None,
) -> RunEntry:
    """Seal a run holding one claim, optionally verdicted by a real critic."""
    run_dir = new_run_dir(ws, run_id=run_id)
    rs = RunState(run_dir=run_dir)
    ref = ik_claim_emit(claim_id, {"metric": 42}, run_state=rs, run_dir=run_dir)
    if verdict == "refuted":
        result = CrossCheckResult(
            passed=False,
            expected=100.0,
            actual=250.0,
            rel_diff=1.5,
            message="headline disagrees with components",
        )
        emit_reconciliation_critique(
            result, ref.record_id, "DEMO-X-900", run_state=rs, run_dir=run_dir
        )
    elif verdict == "supported":
        result = CrossCheckResult(
            passed=True,
            expected=100.0,
            actual=100.0,
            rel_diff=0.0,
            message="identity holds",
        )
        emit_reconciliation_critique(
            result, ref.record_id, "DEMO-X-900", run_state=rs, run_dir=run_dir
        )
    return seal_run(ws, run_dir, rs)


def _manifest_lines(ws: Path) -> list[str]:
    text = (ws / "runs.jsonl").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1. new_run_dir
# ---------------------------------------------------------------------------


class TestNewRunDir:
    def test_default_dated_id_from_started_at(self, tmp_path: Path) -> None:
        run_dir = new_run_dir(tmp_path, started_at="2026-07-01T12:34:56+00:00")
        assert run_dir.name == "20260701T123456Z"
        assert run_dir.parent == tmp_path / "runs"
        assert run_dir.is_dir()

    def test_default_dated_id_from_now(self, tmp_path: Path) -> None:
        run_dir = new_run_dir(tmp_path)
        assert len(run_dir.name) == 16  # YYYYMMDDTHHMMSSZ
        assert run_dir.name.endswith("Z")

    def test_collision_appends_deterministic_suffix(self, tmp_path: Path) -> None:
        started = "2026-07-01T00:00:00+00:00"
        first = new_run_dir(tmp_path, started_at=started)
        second = new_run_dir(tmp_path, started_at=started)
        third = new_run_dir(tmp_path, started_at=started)
        assert first.name == "20260701T000000Z"
        assert second.name == "20260701T000000Z-2"
        assert third.name == "20260701T000000Z-3"

    def test_explicit_run_id_wins(self, tmp_path: Path) -> None:
        run_dir = new_run_dir(tmp_path, run_id="pulse-001", started_at="2026-07-01T00:00:00Z")
        assert run_dir.name == "pulse-001"

    def test_explicit_id_adopts_existing_empty_dir(self, tmp_path: Path) -> None:
        (tmp_path / "runs" / "pulse-001").mkdir(parents=True)
        run_dir = new_run_dir(tmp_path, run_id="pulse-001")
        assert run_dir == tmp_path / "runs" / "pulse-001"

    @pytest.mark.parametrize("bad_id", ["bad/id", "a b", "", "../up", "run:1"])
    def test_invalid_run_id_rejected(self, tmp_path: Path, bad_id: str) -> None:
        with pytest.raises(ValueError, match="filesystem-safe"):
            new_run_dir(tmp_path, run_id=bad_id)

    def test_existing_bundle_with_records_refused(self, tmp_path: Path) -> None:
        (tmp_path / "runs" / "r1" / "records").mkdir(parents=True)
        with pytest.raises(FileExistsError, match="bundle"):
            new_run_dir(tmp_path, run_id="r1")

    def test_existing_bundle_with_run_json_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "runs" / "r1"
        target.mkdir(parents=True)
        (target / "run.json").write_text("{}", encoding="utf-8")
        with pytest.raises(FileExistsError, match="bundle"):
            new_run_dir(tmp_path, run_id="r1")


# ---------------------------------------------------------------------------
# 2. seal_run
# ---------------------------------------------------------------------------


class TestSealRun:
    def test_seal_writes_run_json_and_one_manifest_row(self, tmp_path: Path) -> None:
        entry = _sealed_run(tmp_path, "r1", "DEMO-D-101")
        assert (tmp_path / "runs" / "r1" / "run.json").exists()
        assert len(_manifest_lines(tmp_path)) == 1
        assert entry.run_id == "r1"
        assert entry.record_count == 1
        assert entry.completed_at
        assert [s.claim_id for s in entry.claims] == ["DEMO-D-101"]
        assert entry.claims[0].tier == "draft"
        assert entry.claims[0].completed_at == entry.completed_at

    def test_seal_second_call_idempotent(self, tmp_path: Path) -> None:
        run_dir = new_run_dir(tmp_path, run_id="r1")
        rs = RunState(run_dir=run_dir)
        ik_claim_emit("DEMO-D-102", {"metric": 1}, run_state=rs, run_dir=run_dir)
        first = seal_run(tmp_path, run_dir, rs)
        second = seal_run(tmp_path, run_dir, rs)
        assert len(_manifest_lines(tmp_path)) == 1
        assert second == first

    def test_seal_outside_workspace_runs_rejected(self, tmp_path: Path) -> None:
        stray = tmp_path / "elsewhere" / "r1"
        stray.mkdir(parents=True)
        with pytest.raises(ValueError, match="not under"):
            seal_run(tmp_path, stray, RunState(run_dir=stray))

    def test_critic_sightings_carry_verdict_edges(self, tmp_path: Path) -> None:
        entry = _sealed_run(tmp_path, "r1", "DEMO-D-103", verdict="refuted")
        target, critic = entry.claims
        assert target.claim_id == "DEMO-D-103"
        assert target.refuted_by == [critic.record_id]
        assert target.supported_by == []
        assert target.is_refuted
        assert critic.tier == "critic"
        assert not critic.is_refuted


# ---------------------------------------------------------------------------
# 3. list_runs
# ---------------------------------------------------------------------------


class TestListRuns:
    def test_order_matches_seal_order(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r-b", "DEMO-D-201")
        _sealed_run(tmp_path, "r-a", "DEMO-D-202")
        assert [e.run_id for e in list_runs(tmp_path)] == ["r-b", "r-a"]

    def test_empty_workspace_returns_empty(self, tmp_path: Path) -> None:
        assert list_runs(tmp_path) == []


# ---------------------------------------------------------------------------
# 4. reindex_runs
# ---------------------------------------------------------------------------


class TestReindexRuns:
    def test_rebuild_is_byte_identical(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-301", verdict="refuted")
        _sealed_run(tmp_path, "r2", "DEMO-D-302")
        manifest = tmp_path / "runs.jsonl"
        original = manifest.read_text(encoding="utf-8")
        manifest.unlink()
        count, skipped = reindex_runs(tmp_path)
        assert count == 2
        assert skipped == []
        assert manifest.read_text(encoding="utf-8") == original

    def test_unsealed_run_reported_skipped_not_indexed(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-303")
        new_run_dir(tmp_path, run_id="never-sealed")
        count, skipped = reindex_runs(tmp_path)
        assert count == 1
        assert skipped == ["never-sealed"]
        assert [e.run_id for e in list_runs(tmp_path)] == ["r1"]


# ---------------------------------------------------------------------------
# 5. claim_history / claim_by_id
# ---------------------------------------------------------------------------


class TestClaimHistory:
    def test_history_across_three_runs_in_order(self, tmp_path: Path) -> None:
        for run_id in ("r1", "r2", "r3"):
            _sealed_run(tmp_path, run_id, "DEMO-D-401")
        history = claim_history(tmp_path, "DEMO-D-401")
        assert [s.run_id for s in history] == ["r1", "r2", "r3"]
        assert all(s.claim_id == "DEMO-D-401" for s in history)

    def test_claim_by_id_returns_latest(self, tmp_path: Path) -> None:
        for run_id in ("r1", "r2", "r3"):
            _sealed_run(tmp_path, run_id, "DEMO-D-402")
        sighting = claim_by_id(tmp_path, "DEMO-D-402")
        assert sighting is not None
        assert sighting.run_id == "r3"

    def test_unknown_claim_id(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-403")
        assert claim_history(tmp_path, "DEMO-D-999") == []
        assert claim_by_id(tmp_path, "DEMO-D-999") is None


# ---------------------------------------------------------------------------
# 6. ClaimSighting.load
# ---------------------------------------------------------------------------


def test_sighting_load_returns_full_record(tmp_path: Path) -> None:
    _sealed_run(tmp_path, "r1", "DEMO-D-501")
    sighting = claim_by_id(tmp_path, "DEMO-D-501")
    assert sighting is not None
    rec = sighting.load(tmp_path)
    assert rec["claim_id"] == "DEMO-D-501"
    assert rec["tier"] == "draft"
    assert rec["record_type"] == "claim"
    assert rec["fields"]["metric"]["value"] == 42


# ---------------------------------------------------------------------------
# 7. standing_refutations
# ---------------------------------------------------------------------------


class TestStandingRefutations:
    def test_refuted_claim_is_standing(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-601", verdict="refuted")
        standing = standing_refutations(tmp_path)
        assert set(standing) == {"DEMO-D-601"}
        assert standing["DEMO-D-601"].run_id == "r1"
        assert standing["DEMO-D-601"].refuted_by

    def test_later_supported_sighting_clears(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-602", verdict="refuted")
        _sealed_run(tmp_path, "r2", "DEMO-D-602", verdict="supported")
        assert standing_refutations(tmp_path) == {}

    def test_unverdicted_reemission_does_not_clear(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-603", verdict="refuted")
        _sealed_run(tmp_path, "r2", "DEMO-D-603")  # no verdict — the republish hole
        standing = standing_refutations(tmp_path)
        assert set(standing) == {"DEMO-D-603"}
        # The latest VERDICTED sighting wins — still the r1 refutation.
        assert standing["DEMO-D-603"].run_id == "r1"

    def test_only_unverdicted_sightings_never_standing(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-604")
        assert standing_refutations(tmp_path) == {}


# ---------------------------------------------------------------------------
# 8. guard_republished_claims
# ---------------------------------------------------------------------------


def _current_run(
    ws: Path, run_id: str = "current", *, publishable: bool = False
) -> tuple[Path, RunState]:
    run_dir = new_run_dir(ws, run_id=run_id)
    if publishable:
        # Full fingerprint set so a published-tier emit survives the T7 tier gate.
        (run_dir / "run.json").write_text(json.dumps(FULL_FP_SET, sort_keys=True), encoding="utf-8")
    return run_dir, RunState(run_dir=run_dir)


class TestGuardRepublishedClaims:
    def test_published_republish_flagged_and_downgrade_required(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-701", verdict="refuted")
        run_dir, rs = _current_run(tmp_path, publishable=True)
        ref = ik_claim_emit(
            "DEMO-D-701",
            {"metric": 43},
            tier="published",
            run_state=rs,
            run_dir=run_dir,
            input_data=b"real-input-rows",
        )
        assert read_record(run_dir, ref.record_id)["tier"] == "published"

        findings = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.claim_id == "DEMO-D-701"
        assert finding.record_id == ref.record_id
        assert finding.tier == "published"
        assert finding.prior_run_id == "r1"
        assert finding.downgrade_required is True
        assert finding.critic_record_id is not None

        prior = claim_by_id(tmp_path, "DEMO-D-701")
        assert prior is not None  # latest sealed sighting is r1's
        assert finding.prior_record_id == prior.record_id
        assert finding.prior_refuting_record_ids == prior.refuted_by

        critic = read_record(run_dir, finding.critic_record_id)
        assert critic["tier"] == "critic"
        assert critic["refutes"] == [ref.record_id]
        assert critic["fields"]["checked"]["value"] == "DEMO-D-701"
        assert critic["fields"]["prior_run_id"]["value"] == "r1"
        assert critic["fields"]["prior_record_id"]["value"] == prior.record_id
        assert critic["fields"]["prior_refuting_record_ids"]["value"] == prior.refuted_by
        assert critic["fields"]["passed"]["value"] is False
        assert "refuted in run r1" in critic["fields"]["reason"]["value"]

        # V16 record-then-enforce: the critique event landed on the new record.
        event_log = run_dir / "records" / ref.record_id / "events" / "critique.jsonl"
        assert event_log.exists()

    def test_draft_republish_flagged_without_downgrade(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-702", verdict="refuted")
        run_dir, rs = _current_run(tmp_path)
        ref = ik_claim_emit("DEMO-D-702", {"metric": 43}, run_state=rs, run_dir=run_dir)

        findings = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

        assert len(findings) == 1
        assert findings[0].tier == "draft"
        assert findings[0].downgrade_required is False
        critic = read_record(run_dir, findings[0].critic_record_id)
        assert critic["tier"] == "critic"
        assert critic["refutes"] == [ref.record_id]
        event_log = run_dir / "records" / ref.record_id / "events" / "critique.jsonl"
        assert event_log.exists()

    def test_no_prior_refutation_no_findings_no_critic(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-703")  # never refuted
        run_dir, rs = _current_run(tmp_path)
        ik_claim_emit("DEMO-D-703", {"metric": 43}, run_state=rs, run_dir=run_dir)
        before = len(rs.records)

        findings = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

        assert findings == []
        assert len(rs.records) == before  # no critic emitted

    def test_critic_tier_claims_never_guarded(self, tmp_path: Path) -> None:
        # DEMO-X-704 has a standing refutation, but in the current run it is
        # the claim_id of a CRITIC-tier claim — the guard must skip it.
        _sealed_run(tmp_path, "r1", "DEMO-X-704", verdict="refuted")
        run_dir, rs = _current_run(tmp_path)
        target = ik_claim_emit("DEMO-D-705", {"metric": 1}, run_state=rs, run_dir=run_dir)
        ik_claim_emit(
            "DEMO-X-704",
            {"passed": False},
            tier="critic",
            refutes=[target.record_id],
            run_state=rs,
            run_dir=run_dir,
        )
        before = len(rs.records)

        findings = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

        assert findings == []
        assert len(rs.records) == before

    def test_supported_then_republished_not_flagged(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-706", verdict="refuted")
        _sealed_run(tmp_path, "r2", "DEMO-D-706", verdict="supported")
        run_dir, rs = _current_run(tmp_path)
        ik_claim_emit("DEMO-D-706", {"metric": 43}, run_state=rs, run_dir=run_dir)

        findings = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

        assert findings == []


# ---------------------------------------------------------------------------
# 9. Determinism of the guard's critic claim_id
# ---------------------------------------------------------------------------


def _guard_identical_workspace(ws: Path) -> str:
    """Build a fixed workspace, run the guard, return the critic's claim_id."""
    _sealed_run(ws, "r1", "DEMO-D-801", verdict="refuted")
    run_dir, rs = _current_run(ws)
    ik_claim_emit("DEMO-D-801", {"metric": 43}, run_state=rs, run_dir=run_dir)
    findings = guard_republished_claims(ws, run_state=rs, run_dir=run_dir)
    assert len(findings) == 1
    assert findings[0].critic_record_id is not None
    return read_record(run_dir, findings[0].critic_record_id)["claim_id"]


def test_guard_critic_claim_id_deterministic_and_gate_valid(tmp_path: Path) -> None:
    ws_one = tmp_path / "ws1"
    ws_two = tmp_path / "ws2"
    id_one = _guard_identical_workspace(ws_one)
    id_two = _guard_identical_workspace(ws_two)
    assert id_one == id_two
    assert id_one.startswith("DEMO-X-")
    assert CLAIM_ID_REGEX.match(id_one)

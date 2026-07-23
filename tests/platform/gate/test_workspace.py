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
    WorkspaceNotFoundError,
    claim_by_id,
    claim_history,
    emit_reconciliation_critique,
    guard_refuted_inputs,
    guard_republished_claims,
    ik_claim_emit,
    list_runs,
    new_run_dir,
    reindex_runs,
    seal_run,
    standing_refutations,
)
from insight_kit.platform.gate.runstate import (
    CritiqueGateError,
    CritiqueState,
    apply_critique,
    finalizeRun,
    write_run_json,
)
from insight_kit.platform.gate.store import read_record
from insight_kit.platform.gate.workspace import _guard_critic_claim_id

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


def test_guard_critic_claim_id_fixed_nine_digit_space(tmp_path: Path) -> None:
    # Emitted through the workspace: 9-digit number segment, gate-valid.
    critic_id = _guard_identical_workspace(tmp_path / "ws1")
    number = critic_id.rsplit("-", 1)[-1]
    assert len(number) == 9
    assert number.isdigit()
    assert CLAIM_ID_REGEX.match(critic_id)

    # Unit level: same target record → same id; different targets → different
    # ids (the record-id salt widens the collision space).
    same = _guard_critic_claim_id("DEMO-D-801", "r1", "rec-aaa")
    again = _guard_critic_claim_id("DEMO-D-801", "r1", "rec-aaa")
    other = _guard_critic_claim_id("DEMO-D-801", "r1", "rec-bbb")
    assert same == again
    assert same != other
    assert 100_000_000 <= int(same.rsplit("-", 1)[-1]) <= 999_999_999


# ---------------------------------------------------------------------------
# 10. Guard idempotency + multi-finding behavior
# ---------------------------------------------------------------------------


class TestGuardIdempotency:
    def test_guard_twice_equal_findings_single_critic_no_rejections(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-740", verdict="refuted")
        run_dir, rs = _current_run(tmp_path)
        ik_claim_emit("DEMO-D-740", {"metric": 43}, run_state=rs, run_dir=run_dir)

        first = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)
        records_after_first = len(rs.records)
        second = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

        assert second == first
        assert len(rs.records) == records_after_first  # no duplicate critic
        assert rs.rejectionCount == 0
        critics = [
            r
            for r in rs.records
            if r.record_type == "claim" and read_record(run_dir, r.record_id)["tier"] == "critic"
        ]
        assert len(critics) == 1
        assert first[0].critic_record_id == critics[0].record_id

    def test_two_refuted_claim_ids_two_findings_distinct_critics(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-751", verdict="refuted")
        _sealed_run(tmp_path, "r2", "DEMO-D-752", verdict="refuted")
        run_dir, rs = _current_run(tmp_path)
        ref_one = ik_claim_emit("DEMO-D-751", {"metric": 1}, run_state=rs, run_dir=run_dir)
        ref_two = ik_claim_emit("DEMO-D-752", {"metric": 2}, run_state=rs, run_dir=run_dir)

        findings = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

        assert len(findings) == 2
        by_claim = {f.claim_id: f for f in findings}
        assert set(by_claim) == {"DEMO-D-751", "DEMO-D-752"}
        critic_one = read_record(run_dir, by_claim["DEMO-D-751"].critic_record_id)
        critic_two = read_record(run_dir, by_claim["DEMO-D-752"].critic_record_id)
        assert critic_one["claim_id"] != critic_two["claim_id"]
        assert critic_one["refutes"] == [ref_one.record_id]
        assert critic_two["refutes"] == [ref_two.record_id]

    def test_guard_then_seal_critic_becomes_standing_refutation(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "run1", "DEMO-D-760", verdict="refuted")

        # run2 republishes; the guard critiques; the run is sealed.
        run2_dir, rs2 = _current_run(tmp_path, "run2")
        ref2 = ik_claim_emit("DEMO-D-760", {"metric": 43}, run_state=rs2, run_dir=run2_dir)
        findings2 = guard_republished_claims(tmp_path, run_state=rs2, run_dir=run2_dir)
        assert len(findings2) == 1
        entry2 = seal_run(tmp_path, run2_dir, rs2)

        # run2's manifest row shows the re-emitted record refuted by the guard critic.
        sighting = next(s for s in entry2.claims if s.record_id == ref2.record_id)
        assert sighting.refuted_by == [findings2[0].critic_record_id]

        # run3 republishes again — the guard's critic in run2 is now the
        # standing refutation.
        run3_dir, rs3 = _current_run(tmp_path, "run3")
        ik_claim_emit("DEMO-D-760", {"metric": 44}, run_state=rs3, run_dir=run3_dir)
        findings3 = guard_republished_claims(tmp_path, run_state=rs3, run_dir=run3_dir)
        assert len(findings3) == 1
        assert findings3[0].prior_run_id == "run2"
        assert findings3[0].prior_record_id == ref2.record_id
        assert findings3[0].prior_refuting_record_ids == [findings2[0].critic_record_id]


# ---------------------------------------------------------------------------
# 11. Guard must not spend the V16 critiqueRounds budget
# ---------------------------------------------------------------------------


class TestGuardCritiqueRoundsBudget:
    def test_guard_preserves_rounds_and_first_real_critique_still_raises(
        self, tmp_path: Path
    ) -> None:
        for i, cid in enumerate(["DEMO-D-711", "DEMO-D-712", "DEMO-D-713"]):
            _sealed_run(tmp_path, f"r{i}", cid, verdict="refuted")
        run_dir, rs = _current_run(tmp_path, publishable=True)
        for cid in ["DEMO-D-711", "DEMO-D-712", "DEMO-D-713"]:
            ik_claim_emit(cid, {"metric": 43}, run_state=rs, run_dir=run_dir)

        findings = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

        assert len(findings) == 3
        assert rs.critiqueRounds == 0  # guard spent nothing

        # A genuine FIRST-round high critique on a fresh published record
        # must still RAISE (not silently take the at-cap downgrade path).
        pub = ik_claim_emit(
            "DEMO-D-999",
            {"metric": 7},
            tier="published",
            run_state=rs,
            run_dir=run_dir,
            input_data=b"real-input-rows",
        )
        assert read_record(run_dir, pub.record_id)["tier"] == "published"
        with pytest.raises(CritiqueGateError):
            apply_critique(
                run_state=rs,
                record_id=pub.record_id,
                record_type="claim",
                tier="published",
                audience=None,
                critique=CritiqueState.open(
                    severity="high",
                    reason="genuine identity violation",
                    critic_id="rc-1",
                    target_record_id=pub.record_id,
                ),
                run_dir=run_dir,
            )

    def test_at_cap_published_republish_downgrades_and_rounds_untouched(
        self, tmp_path: Path
    ) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-730", verdict="refuted")
        run_dir, rs = _current_run(tmp_path, publishable=True)
        ik_claim_emit(
            "DEMO-D-730",
            {"metric": 43},
            tier="published",
            run_state=rs,
            run_dir=run_dir,
            input_data=b"real-input-rows",
        )
        rs.critiqueRounds = 3  # at cap — gate returns downgraded instead of raising

        findings = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

        assert len(findings) == 1
        assert findings[0].downgrade_required is True
        assert rs.critiqueRounds == 3


# ---------------------------------------------------------------------------
# 12. Board-audience drafts hit the gate too
# ---------------------------------------------------------------------------


def test_board_audience_draft_republish_requires_downgrade(tmp_path: Path) -> None:
    _sealed_run(tmp_path, "r1", "DEMO-D-720", verdict="refuted")
    run_dir, rs = _current_run(tmp_path)
    ik_claim_emit("DEMO-D-720", {"metric": 43}, audience="board", run_state=rs, run_dir=run_dir)

    findings = guard_republished_claims(tmp_path, run_state=rs, run_dir=run_dir)

    assert len(findings) == 1
    assert findings[0].tier == "draft"
    assert findings[0].downgrade_required is True
    assert rs.critiqueRounds == 0


# ---------------------------------------------------------------------------
# 13. Dot-only run_ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dotty", ["..", ".", "..."])
def test_dot_only_run_ids_rejected(tmp_path: Path, dotty: str) -> None:
    with pytest.raises(ValueError, match="filesystem-safe"):
        new_run_dir(tmp_path, run_id=dotty)
    assert not (tmp_path / "runs").exists()  # nothing escaped runs/


# ---------------------------------------------------------------------------
# 14. Symlinked runs/ dir
# ---------------------------------------------------------------------------


def test_seal_run_through_symlinked_runs_dir(tmp_path: Path) -> None:
    real_runs = tmp_path / "real-runs"
    real_runs.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").symlink_to(real_runs)

    run_dir = new_run_dir(ws, run_id="r1")
    rs = RunState(run_dir=run_dir)
    ik_claim_emit("DEMO-D-770", {"metric": 1}, run_state=rs, run_dir=run_dir)
    entry = seal_run(ws, run_dir, rs)

    assert entry.run_id == "r1"
    assert len(_manifest_lines(ws)) == 1
    assert [e.run_id for e in list_runs(ws)] == ["r1"]


# ---------------------------------------------------------------------------
# 15. Canonical order independent of file order / reindex
# ---------------------------------------------------------------------------


def _seal_after(ws: Path, previous_completed_at: str, run_id: str, claim_id: str, **kw) -> RunEntry:
    """Seal a run whose completedAt is strictly after previous_completed_at."""
    from datetime import UTC, datetime

    # Spin until the clock moves past the previous completedAt so the two
    # runs get deterministically distinct, ordered timestamps.
    while datetime.now(UTC).isoformat() <= previous_completed_at:
        pass
    return _sealed_run(ws, run_id, claim_id, **kw)


def test_canonical_order_survives_reindex_lexical_vs_chronological(
    tmp_path: Path,
) -> None:
    # run_ids lexically OPPOSITE to chronology: "z-first" seals before "a-second".
    first = _sealed_run(tmp_path, "z-first", "DEMO-D-780", verdict="refuted")
    _seal_after(tmp_path, first.completed_at, "a-second", "DEMO-D-780", verdict="supported")

    canonical = ["z-first", "a-second"]
    assert [e.run_id for e in list_runs(tmp_path)] == canonical
    standing_before = standing_refutations(tmp_path)
    assert standing_before == {}  # latest verdicted sighting (a-second) supports

    count, skipped = reindex_runs(tmp_path)
    assert (count, skipped) == (2, [])
    first_rebuild = (tmp_path / "runs.jsonl").read_text(encoding="utf-8")

    assert [e.run_id for e in list_runs(tmp_path)] == canonical
    assert standing_refutations(tmp_path) == standing_before

    reindex_runs(tmp_path)
    second_rebuild = (tmp_path / "runs.jsonl").read_text(encoding="utf-8")
    assert second_rebuild == first_rebuild  # idempotent, byte-identical


# ---------------------------------------------------------------------------
# 16. Interrupted seal recovery
# ---------------------------------------------------------------------------


def test_interrupted_seal_recovers_to_exactly_one_manifest_row(tmp_path: Path) -> None:
    run_dir = new_run_dir(tmp_path, run_id="r1")
    rs = RunState(run_dir=run_dir)
    ik_claim_emit("DEMO-D-790", {"metric": 1}, run_state=rs, run_dir=run_dir)

    # Simulate a seal interrupted after write_run_json but before the
    # manifest append.
    finalizeRun(rs)
    write_run_json(run_dir, rs)
    assert not (tmp_path / "runs.jsonl").exists()

    entry = seal_run(tmp_path, run_dir, rs)
    assert entry.run_id == "r1"
    assert len(_manifest_lines(tmp_path)) == 1
    # And a repeat seal stays idempotent.
    seal_run(tmp_path, run_dir, rs)
    assert len(_manifest_lines(tmp_path)) == 1


# ---------------------------------------------------------------------------
# 17. Deleted manifest — reads fall back to a bundle scan, never write
# ---------------------------------------------------------------------------


def test_deleted_manifest_reads_still_answer_without_recreating(tmp_path: Path) -> None:
    _sealed_run(tmp_path, "r1", "DEMO-D-795", verdict="refuted")
    _sealed_run(tmp_path, "r2", "DEMO-D-796")
    manifest = tmp_path / "runs.jsonl"
    manifest.unlink()

    history = claim_history(tmp_path, "DEMO-D-795")
    assert [s.run_id for s in history] == ["r1"]
    standing = standing_refutations(tmp_path)
    assert set(standing) == {"DEMO-D-795"}
    assert standing["DEMO-D-795"].run_id == "r1"
    assert claim_by_id(tmp_path, "DEMO-D-796") is not None
    assert not manifest.exists()  # reads must not write


# ---------------------------------------------------------------------------
# 18. Nonexistent workspace — typed error, never a silent empty answer
# ---------------------------------------------------------------------------


def test_nonexistent_workspace_raises_typed_error(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-workspace"
    with pytest.raises(WorkspaceNotFoundError):
        claim_history(missing, "DEMO-D-101")
    with pytest.raises(WorkspaceNotFoundError):
        claim_by_id(missing, "DEMO-D-101")
    with pytest.raises(WorkspaceNotFoundError):
        standing_refutations(missing)

    run_dir = new_run_dir(tmp_path, run_id="current")
    rs = RunState(run_dir=run_dir)
    with pytest.raises(WorkspaceNotFoundError):
        guard_republished_claims(missing, run_state=rs, run_dir=run_dir)


# ---------------------------------------------------------------------------
# 19. guard_refuted_inputs — refutation contagion along input_claims
# ---------------------------------------------------------------------------


class TestGuardRefutedInputs:
    def test_derived_from_standing_refutation_is_flagged(self, tmp_path: Path) -> None:
        # r1 refuted DEMO-D-010 (a base measure). The current run republishes it
        # AND stands a derived metric on it.
        _sealed_run(tmp_path, "r1", "DEMO-D-010", verdict="refuted")
        run_dir, rs = _current_run(tmp_path)
        base = ik_claim_emit("DEMO-D-010", {"metric": 5}, run_state=rs, run_dir=run_dir)
        derived = ik_claim_emit(
            "DEMO-D-020",
            {"metric": 2},
            input_claims=[base.record_id],
            run_state=rs,
            run_dir=run_dir,
        )

        findings = guard_refuted_inputs(tmp_path, run_state=rs, run_dir=run_dir)

        # Only the DERIVED claim is a contagion finding: the republished base is
        # the republish guard's job, and here acts only as a taint source.
        assert len(findings) == 1
        f = findings[0]
        assert f.claim_id == "DEMO-D-020"
        assert f.record_id == derived.record_id
        assert f.refuted_ancestor_claim_id == "DEMO-D-010"
        assert f.refuted_ancestor_record_id == base.record_id
        assert f.source == "standing"
        assert f.path == [derived.record_id, base.record_id]
        assert f.tier == "draft"
        assert f.downgrade_required is False
        assert f.critic_record_id is not None

        critic = read_record(run_dir, f.critic_record_id)
        assert critic["tier"] == "critic"
        assert critic["refutes"] == [derived.record_id]
        assert critic["fields"]["guard"]["value"] == "refuted_inputs"
        assert critic["fields"]["checked"]["value"] == "DEMO-D-020"
        assert critic["fields"]["refuted_ancestor_claim_id"]["value"] == "DEMO-D-010"
        assert critic["fields"]["source"]["value"] == "standing"
        assert critic["fields"]["path"]["value"] == [derived.record_id, base.record_id]
        assert critic["fields"]["passed"]["value"] is False

        # V16 record-then-enforce: the critique landed on the derived record.
        event_log = run_dir / "records" / derived.record_id / "events" / "critique.jsonl"
        assert event_log.exists()

    def test_in_run_refutation_propagates_transitively(self, tmp_path: Path) -> None:
        # No standing refutation; a genuine critic refutes the base THIS run.
        # The taint must reach both the direct and the transitive derivative.
        run_dir, rs = _current_run(tmp_path)
        base = ik_claim_emit("DEMO-D-010", {"metric": 5}, run_state=rs, run_dir=run_dir)
        mid = ik_claim_emit(
            "DEMO-D-020", {"metric": 2}, input_claims=[base.record_id], run_state=rs, run_dir=run_dir
        )
        top = ik_claim_emit(
            "DEMO-D-030", {"metric": 1}, input_claims=[mid.record_id], run_state=rs, run_dir=run_dir
        )
        ik_claim_emit(
            "DEMO-X-900",
            {"passed": False},
            tier="critic",
            refutes=[base.record_id],
            run_state=rs,
            run_dir=run_dir,
        )

        findings = guard_refuted_inputs(tmp_path, run_state=rs, run_dir=run_dir)
        flagged = {f.claim_id: f for f in findings}

        # base is directly refuted -> NOT a contagion finding; mid + top inherit.
        assert set(flagged) == {"DEMO-D-020", "DEMO-D-030"}
        assert flagged["DEMO-D-020"].source == "in_run"
        assert flagged["DEMO-D-020"].path == [mid.record_id, base.record_id]
        assert flagged["DEMO-D-030"].path == [top.record_id, mid.record_id, base.record_id]
        assert flagged["DEMO-D-030"].refuted_ancestor_record_id == base.record_id

    def test_clean_chain_no_findings_no_critic(self, tmp_path: Path) -> None:
        run_dir, rs = _current_run(tmp_path)
        base = ik_claim_emit("DEMO-D-010", {"metric": 5}, run_state=rs, run_dir=run_dir)
        ik_claim_emit(
            "DEMO-D-020", {"metric": 2}, input_claims=[base.record_id], run_state=rs, run_dir=run_dir
        )
        before = len(rs.records)

        findings = guard_refuted_inputs(tmp_path, run_state=rs, run_dir=run_dir)

        assert findings == []
        assert len(rs.records) == before  # no critic emitted

    def test_idempotent_reinvocation(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-010", verdict="refuted")
        run_dir, rs = _current_run(tmp_path)
        base = ik_claim_emit("DEMO-D-010", {"metric": 5}, run_state=rs, run_dir=run_dir)
        ik_claim_emit(
            "DEMO-D-020", {"metric": 2}, input_claims=[base.record_id], run_state=rs, run_dir=run_dir
        )

        first = guard_refuted_inputs(tmp_path, run_state=rs, run_dir=run_dir)
        records_after_first = len(rs.records)
        rounds_after_first = rs.critiqueRounds
        second = guard_refuted_inputs(tmp_path, run_state=rs, run_dir=run_dir)

        assert [f.record_id for f in first] == [f.record_id for f in second]
        assert [f.critic_record_id for f in first] == [f.critic_record_id for f in second]
        assert len(rs.records) == records_after_first  # no second critic emission
        assert rs.critiqueRounds == rounds_after_first  # no fix-round budget spent

    def test_published_derivative_requires_downgrade(self, tmp_path: Path) -> None:
        _sealed_run(tmp_path, "r1", "DEMO-D-010", verdict="refuted")
        run_dir, rs = _current_run(tmp_path, publishable=True)
        base = ik_claim_emit(
            "DEMO-D-010", {"metric": 5}, run_state=rs, run_dir=run_dir, input_data=b"rows"
        )
        ik_claim_emit(
            "DEMO-D-020",
            {"metric": 2},
            tier="published",
            input_claims=[base.record_id],
            run_state=rs,
            run_dir=run_dir,
            input_data=b"rows2",
        )

        findings = guard_refuted_inputs(tmp_path, run_state=rs, run_dir=run_dir)
        f = next(f for f in findings if f.claim_id == "DEMO-D-020")

        assert f.tier == "published"
        assert f.downgrade_required is True

    def test_supported_ancestor_is_not_contagious(self, tmp_path: Path) -> None:
        # r1 refuted, r2 supported -> the ancestor's refutation is cleared, so a
        # derivative in the current run must NOT be flagged.
        _sealed_run(tmp_path, "r1", "DEMO-D-010", verdict="refuted")
        _sealed_run(tmp_path, "r2", "DEMO-D-010", verdict="supported")
        run_dir, rs = _current_run(tmp_path)
        base = ik_claim_emit("DEMO-D-010", {"metric": 5}, run_state=rs, run_dir=run_dir)
        ik_claim_emit(
            "DEMO-D-020", {"metric": 2}, input_claims=[base.record_id], run_state=rs, run_dir=run_dir
        )

        assert guard_refuted_inputs(tmp_path, run_state=rs, run_dir=run_dir) == []

    def test_guard_critic_does_not_reseed_itself(self, tmp_path: Path) -> None:
        # Regression for the self-reseed idempotency hole: the contagion critic
        # refutes the derived claim, but must be excluded from the in_run seed so
        # a re-invocation does not reclassify the derived claim as a source and
        # shrink the findings list.
        run_dir, rs = _current_run(tmp_path)
        base = ik_claim_emit("DEMO-D-010", {"metric": 5}, run_state=rs, run_dir=run_dir)
        ik_claim_emit(
            "DEMO-D-020", {"metric": 2}, input_claims=[base.record_id], run_state=rs, run_dir=run_dir
        )
        ik_claim_emit(
            "DEMO-X-900",
            {"passed": False},
            tier="critic",
            refutes=[base.record_id],
            run_state=rs,
            run_dir=run_dir,
        )

        first = guard_refuted_inputs(tmp_path, run_state=rs, run_dir=run_dir)
        second = guard_refuted_inputs(tmp_path, run_state=rs, run_dir=run_dir)

        assert {f.claim_id for f in first} == {"DEMO-D-020"}
        assert {f.claim_id for f in second} == {"DEMO-D-020"}  # unchanged: no shrink
        assert [f.critic_record_id for f in first] == [f.critic_record_id for f in second]

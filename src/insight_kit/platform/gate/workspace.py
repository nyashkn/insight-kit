"""Cross-run workspace substrate (I.workspace): dated run dirs + runs.jsonl manifest.

A workspace holds many sealed run bundles side by side and answers the
questions a single run_dir cannot: "when did this claim_id last appear",
"what happened yesterday", and — the confirmed republish hole — "was this
claim_id refuted in a PRIOR run".  Layout:

  workspace_dir/
    runs/<run_id>/    # each an ordinary run_dir (store.py layout)
    runs.jsonl        # append-only manifest, one row per SEALED run; regenerable

Invariants carried over from the single-run gate:
  * V3 spirit — new_run_dir never adopts an existing bundle silently
    (a dir with records/ or run.json raises FileExistsError).
  * V7 analog — runs.jsonl is regenerable from runs/*/run.json bundles via
    reindex_runs; rebuilt rows are byte-identical to seal-written rows.
  * V10 mirror — seal_run is idempotent: a run_id already in the manifest
    returns its existing entry, never a duplicate row.
  * V16 — guard_republished_claims records the critique event, then enforces
    (record-then-enforce); the guard SURFACES findings, it never blocks —
    only deductive identities may block.

Verdicts are per-sighting: the latest VERDICTED sighting of a claim_id wins.
An unverdicted re-emission does NOT clear a standing refutation — that is
exactly the republish hole this module closes.

Cites: V3, V7, V10, V16, I.store, I.run, I.workspace.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from insight_kit.platform.gate.emit import ik_claim_emit
from insight_kit.platform.gate.runstate import (
    CritiqueGateError,
    CritiqueState,
    RunState,
    apply_critique,
    finalizeRun,
    write_run_json,
)
from insight_kit.platform.gate.store import index_path, read_record

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_NAMESPACE_RE = re.compile(r"^[A-Z]{2,5}")

# Tiers the republish guard watches. Critic-tier claims are never guarded —
# a critic re-stating a refutation is the mechanism, not the hole.
_GUARDED_TIERS = frozenset({"draft", "published"})


class RunNotSealedError(LookupError):
    """Raised when an operation needs a sealed run that has no run.json / completedAt."""


# ---------------------------------------------------------------------------
# Manifest row types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimSighting:
    """One claim occurrence in one sealed run.

    refuted_by / supported_by hold record ids of critic claims in the SAME
    run whose refutes/supports lists point at this record.  A sighting with
    neither is unverdicted — it carries no stance and cannot clear a
    standing refutation (see standing_refutations).
    """

    run_id: str
    record_id: str
    claim_id: str
    tier: str
    completed_at: str
    refuted_by: list[str] = field(default_factory=list)
    supported_by: list[str] = field(default_factory=list)

    @property
    def is_refuted(self) -> bool:
        """True when at least one critic claim in the run refutes this record."""
        return bool(self.refuted_by)

    def load(self, workspace_dir: Path | str) -> dict[str, Any]:
        """Read the full record dict back from the sealed run bundle."""
        return read_record(Path(workspace_dir) / "runs" / self.run_id, self.record_id)


@dataclass(frozen=True)
class RunEntry:
    """One runs.jsonl manifest row: a sealed run and its claim sightings.

    claims holds sightings of ALL tiers (including critic) in records.jsonl
    order — seal order within the run is emission order.
    """

    run_id: str
    completed_at: str
    record_count: int
    claims: list[ClaimSighting] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Row (de)serialization — store.py json.dumps style
# ---------------------------------------------------------------------------


def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sighting_to_dict(sighting: ClaimSighting) -> dict[str, Any]:
    return {
        "run_id": sighting.run_id,
        "record_id": sighting.record_id,
        "claim_id": sighting.claim_id,
        "tier": sighting.tier,
        "completed_at": sighting.completed_at,
        "refuted_by": sighting.refuted_by,
        "supported_by": sighting.supported_by,
    }


def _sighting_from_dict(row: dict[str, Any]) -> ClaimSighting:
    return ClaimSighting(
        run_id=row["run_id"],
        record_id=row["record_id"],
        claim_id=row["claim_id"],
        tier=row["tier"],
        completed_at=row["completed_at"],
        refuted_by=list(row.get("refuted_by") or []),
        supported_by=list(row.get("supported_by") or []),
    )


def _entry_to_dict(entry: RunEntry) -> dict[str, Any]:
    return {
        "run_id": entry.run_id,
        "completed_at": entry.completed_at,
        "record_count": entry.record_count,
        "claims": [_sighting_to_dict(s) for s in entry.claims],
    }


def _entry_from_dict(row: dict[str, Any]) -> RunEntry:
    return RunEntry(
        run_id=row["run_id"],
        completed_at=row["completed_at"],
        record_count=int(row["record_count"]),
        claims=[_sighting_from_dict(s) for s in row.get("claims") or []],
    )


def _manifest_path(workspace_dir: Path) -> Path:
    """Path to runs.jsonl."""
    return workspace_dir / "runs.jsonl"


# ---------------------------------------------------------------------------
# new_run_dir — dated run isolation
# ---------------------------------------------------------------------------


def new_run_dir(
    workspace_dir: Path | str,
    *,
    run_id: str | None = None,
    started_at: str | None = None,
) -> Path:
    """Create workspace_dir/runs/<run_id>/ and return it.

    An explicit run_id wins and must be filesystem-safe
    (``^[A-Za-z0-9._-]+$`` — ValueError otherwise).  The default run_id is
    derived from ``started_at`` (ISO-8601 string) or, if None, the current
    UTC time, in compact form ``YYYYMMDDTHHMMSSZ``; on collision with an
    existing dir the suffix ``-2``, ``-3``, ... is appended (deterministic,
    no randomness).

    If the target dir already exists AND contains records/ or run.json the
    call raises FileExistsError (V3 spirit — never adopt an existing bundle
    silently).  An existing *empty* dir with an explicit run_id is fine to
    adopt.
    """
    runs_root = Path(workspace_dir) / "runs"

    if run_id is not None:
        if not _RUN_ID_RE.match(run_id):
            raise ValueError(
                f"run_id {run_id!r} is not filesystem-safe: it must match ^[A-Za-z0-9._-]+$."
            )
    else:
        if started_at is not None:
            dt = datetime.fromisoformat(started_at)
        else:
            dt = datetime.now(UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        base = dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = base
        n = 2
        while (runs_root / run_id).exists():
            run_id = f"{base}-{n}"
            n += 1

    run_dir = runs_root / run_id
    if run_dir.exists() and ((run_dir / "records").exists() or (run_dir / "run.json").exists()):
        raise FileExistsError(
            f"run dir {run_dir} already contains a bundle (records/ or run.json). "
            "Never adopt an existing bundle silently (V3) — pick a fresh run_id."
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


# ---------------------------------------------------------------------------
# Entry building — shared by seal_run and reindex_runs (V7 analog)
# ---------------------------------------------------------------------------


def _build_entry(workspace_dir: Path, run_id: str) -> RunEntry:
    """Build a manifest row from a sealed run bundle on disk.

    Reads run.json for completedAt/record_count, records.jsonl for the claim
    rows (order = emission order), and each critic claim's record.json for its
    refutes/supports edges.  Raises RunNotSealedError when the run has no
    run.json or no completedAt (never guess — an unsealed run is a fact).
    """
    run_dir = workspace_dir / "runs" / run_id
    run_json = run_dir / "run.json"
    if not run_json.exists():
        raise RunNotSealedError(
            f"run {run_id!r} has no run.json under {run_dir} — it was never sealed."
        )
    meta = json.loads(run_json.read_text(encoding="utf-8"))
    completed_at = meta.get("completedAt")
    if not completed_at:
        raise RunNotSealedError(
            f"run {run_id!r} has run.json but no completedAt — it was never finalized."
        )

    claim_rows: list[dict[str, Any]] = []
    idx = index_path(run_dir)
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record_type") == "claim":
                claim_rows.append(row)

    # Resolve verdict edges: critic claims' refutes/supports record-id lists
    # within the same run point at the records they verdict.
    refuted_by: dict[str, list[str]] = {}
    supported_by: dict[str, list[str]] = {}
    for row in claim_rows:
        if row.get("tier") != "critic":
            continue
        critic = read_record(run_dir, row["record_id"])
        for target_id in critic.get("refutes") or []:
            refuted_by.setdefault(target_id, []).append(row["record_id"])
        for target_id in critic.get("supports") or []:
            supported_by.setdefault(target_id, []).append(row["record_id"])

    sightings = [
        ClaimSighting(
            run_id=run_id,
            record_id=row["record_id"],
            claim_id=str(row.get("claim_id")),
            tier=str(row.get("tier")),
            completed_at=completed_at,
            refuted_by=refuted_by.get(row["record_id"], []),
            supported_by=supported_by.get(row["record_id"], []),
        )
        for row in claim_rows
    ]
    return RunEntry(
        run_id=run_id,
        completed_at=completed_at,
        record_count=int(meta.get("record_count", 0)),
        claims=sightings,
    )


# ---------------------------------------------------------------------------
# seal_run / list_runs / reindex_runs — the manifest
# ---------------------------------------------------------------------------


def seal_run(
    workspace_dir: Path | str,
    run_dir: Path | str,
    run_state: RunState,
    *,
    extra: dict[str, Any] | None = None,
) -> RunEntry:
    """Finalize a run, write run.json, and append its manifest row.

    run_dir MUST be a direct child of workspace_dir/runs/ (ValueError
    otherwise).  Idempotent (V10 mirror): if the run_id already has a
    manifest row the existing entry is returned and no duplicate is
    appended.  Otherwise finalizeRun (itself idempotent) + write_run_json
    run first, then the row is built by scanning the sealed bundle — the
    same scan reindex_runs uses, so rebuilt rows equal seal-written rows.
    """
    workspace_dir = Path(workspace_dir).resolve()
    run_dir = Path(run_dir).resolve()
    runs_root = workspace_dir / "runs"
    if run_dir.parent != runs_root:
        raise ValueError(
            f"run_dir {run_dir} is not under {runs_root} — seal_run only seals "
            "runs that live inside the workspace."
        )
    run_id = run_dir.name

    for existing in list_runs(workspace_dir):
        if existing.run_id == run_id:
            return existing

    finalizeRun(run_state)
    write_run_json(run_dir, run_state, extra)

    entry = _build_entry(workspace_dir, run_id)
    manifest = _manifest_path(workspace_dir)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as f:
        f.write(_dumps(_entry_to_dict(entry)))
        f.write("\n")
    return entry


def list_runs(workspace_dir: Path | str) -> list[RunEntry]:
    """Parse runs.jsonl in file order (seal order = chronology).

    Missing manifest → empty list. Blank lines are skipped.
    """
    manifest = _manifest_path(Path(workspace_dir))
    if not manifest.exists():
        return []
    entries: list[RunEntry] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entries.append(_entry_from_dict(json.loads(line)))
    return entries


def reindex_runs(workspace_dir: Path | str) -> tuple[int, list[str]]:
    """Rebuild runs.jsonl from runs/*/run.json bundles (V7 analog).

    Sealed runs are sorted by completedAt (tie-break run_id); dirs without a
    usable run.json are skipped and returned in the second element.
    Overwrites runs.jsonl.  Rebuilt rows equal seal-written rows for the
    same runs — both come from the same bundle scan.
    """
    workspace_dir = Path(workspace_dir).resolve()
    runs_root = workspace_dir / "runs"

    entries: list[RunEntry] = []
    skipped: list[str] = []
    if runs_root.exists():
        for run_path in sorted(p for p in runs_root.iterdir() if p.is_dir()):
            try:
                entries.append(_build_entry(workspace_dir, run_path.name))
            except RunNotSealedError:
                skipped.append(run_path.name)
    entries.sort(key=lambda e: (e.completed_at, e.run_id))

    manifest = _manifest_path(workspace_dir)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(_dumps(_entry_to_dict(entry)))
            f.write("\n")
    return len(entries), skipped


# ---------------------------------------------------------------------------
# Claim history queries
# ---------------------------------------------------------------------------


def claim_history(workspace_dir: Path | str, claim_id: str) -> list[ClaimSighting]:
    """Every sighting of claim_id across sealed runs, in manifest order."""
    return [
        sighting
        for entry in list_runs(workspace_dir)
        for sighting in entry.claims
        if sighting.claim_id == claim_id
    ]


def claim_by_id(workspace_dir: Path | str, claim_id: str) -> ClaimSighting | None:
    """The LATEST sighting of claim_id, or None if it was never sealed."""
    history = claim_history(workspace_dir, claim_id)
    return history[-1] if history else None


def standing_refutations(workspace_dir: Path | str) -> dict[str, ClaimSighting]:
    """claim_id -> latest verdicted sighting, filtered to standing refutations.

    Verdicts are per-sighting and the most recent VERDICTED sighting wins: a
    later supported sighting clears a refutation; an unverdicted re-emission
    does NOT (that is exactly the republish hole).  A claim_id with only
    unverdicted sightings is never standing.
    """
    latest_verdicted: dict[str, ClaimSighting] = {}
    for entry in list_runs(workspace_dir):
        for sighting in entry.claims:
            if sighting.refuted_by or sighting.supported_by:
                latest_verdicted[sighting.claim_id] = sighting
    return {
        claim_id: sighting for claim_id, sighting in latest_verdicted.items() if sighting.is_refuted
    }


# ---------------------------------------------------------------------------
# guard_republished_claims — the persistent refuted-claim republish guard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepublishFinding:
    """One republished-after-refutation hit surfaced by the guard.

    record_id is the NEW record in the current run; prior_* fields carry the
    provenance of the standing refutation; critic_record_id is the guard's
    freshly emitted critic claim.  downgrade_required is True when the V16
    gate fired on the new record (published tier) — the caller must
    downgrade before rendering.
    """

    claim_id: str
    record_id: str
    tier: str
    prior_run_id: str
    prior_record_id: str
    prior_refuting_record_ids: list[str]
    critic_record_id: str | None
    downgrade_required: bool


def _guard_critic_claim_id(claim_id: str, prior_run_id: str) -> str:
    """Deterministic gate-valid claim_id for the guard's critic claim.

    Namespace is the target claim_id's leading ``[A-Z]{2,5}`` segment; the
    number derives from sha256 of "claim_id|prior_run_id" (hamilton adapter
    hash-to-number scheme) so identical workspaces yield identical ids.
    """
    match = _NAMESPACE_RE.match(claim_id)
    namespace = match.group(0) if match else "IK"
    digest = hashlib.sha256(f"{claim_id}|{prior_run_id}".encode()).hexdigest()
    return f"{namespace}-X-{int(digest[:6], 16) % 900 + 100}"


def guard_republished_claims(
    workspace_dir: Path | str,
    *,
    run_state: RunState,
    run_dir: Path | str,
) -> list[RepublishFinding]:
    """Flag current-run claims whose claim_id carries a standing refutation.

    Run against a CURRENT (typically unsealed) run before sealing.  For each
    draft/published claim record in run_state.records (never critic-tier
    claims) with a standing refutation from SEALED runs, the guard:

      1. emits a critic-tier claim refuting the new record, carrying the
         prior run/record provenance in its fields, and
      2. applies a severity=high critique to the new record via
         apply_critique — the critique event lands on the record's events
         log on every path (V16 record-then-enforce); a CritiqueGateError
         (published tier) is caught and surfaced as downgrade_required=True.

    SURFACE, NEVER BLOCK: the guard raises nothing for guard hits; it
    returns findings.  (Doctrine: only deductive identities may block.)
    """
    run_dir = Path(run_dir)
    standing = standing_refutations(workspace_dir)
    findings: list[RepublishFinding] = []

    # Snapshot — emitting guard critics appends to run_state.records.
    for ref in list(run_state.records):
        if ref.record_type != "claim":
            continue
        record = read_record(run_dir, ref.record_id)
        tier = str(record.get("tier"))
        if tier not in _GUARDED_TIERS:
            continue
        claim_id = str(record.get("claim_id"))
        prior = standing.get(claim_id)
        if prior is None:
            continue

        reason = (
            f"claim_id {claim_id} was refuted in run {prior.run_id} and "
            "republished without a superseding verdict"
        )
        critic_ref = ik_claim_emit(
            _guard_critic_claim_id(claim_id, prior.run_id),
            {
                "checked": claim_id,
                "prior_run_id": prior.run_id,
                "prior_record_id": prior.record_id,
                "prior_refuting_record_ids": list(prior.refuted_by),
                "reason": reason,
                "passed": False,
            },
            tier="critic",
            refutes=[ref.record_id],
            run_state=run_state,
            run_dir=run_dir,
        )

        downgrade_required = False
        try:
            gate_result = apply_critique(
                run_state=run_state,
                record_id=ref.record_id,
                record_type="claim",
                tier=tier,
                audience=None,
                critique=CritiqueState.open(
                    severity="high",
                    reason=reason,
                    critic_id=critic_ref.record_id,
                    target_record_id=ref.record_id,
                ),
                run_dir=run_dir,
            )
            downgrade_required = bool(gate_result.get("downgraded"))
        except CritiqueGateError:
            downgrade_required = True

        findings.append(
            RepublishFinding(
                claim_id=claim_id,
                record_id=ref.record_id,
                tier=tier,
                prior_run_id=prior.run_id,
                prior_record_id=prior.record_id,
                prior_refuting_record_ids=list(prior.refuted_by),
                critic_record_id=critic_ref.record_id,
                downgrade_required=downgrade_required,
            )
        )

    return findings

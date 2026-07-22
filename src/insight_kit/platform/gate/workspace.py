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
    reindex_runs; row CONTENT is identical per run, file order is
    canonicalized to (completedAt, run_id), and a second reindex is
    byte-identical to the first.  File order in runs.jsonl (append = seal
    order) is a storage detail — the canonical order every query sees is
    (completedAt, run_id).
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
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from insight_kit.libs.validation import ValidationError as LayerAValidationError
from insight_kit.platform.gate.emit import ik_claim_emit
from insight_kit.platform.gate.runstate import (
    CritiqueGateError,
    CritiqueState,
    RecordRef,
    RunState,
    apply_critique,
    finalizeRun,
    write_run_json,
)
from insight_kit.platform.gate.store import index_path, read_record, reindex

# Filesystem-safe run ids; the lookahead rejects dot-only names ("."/".."/…)
# that would escape or alias the runs/ directory.
_RUN_ID_RE = re.compile(r"^(?!\.+$)[A-Za-z0-9._-]+$")
_NAMESPACE_RE = re.compile(r"^[A-Z]{2,5}")

# Tiers the republish guard watches. Critic-tier claims are never guarded —
# a critic re-stating a refutation is the mechanism, not the hole.
_GUARDED_TIERS = frozenset({"draft", "published"})


class RunNotSealedError(LookupError):
    """Raised when an operation needs a sealed run that has no run.json / completedAt."""


class WorkspaceNotFoundError(LookupError):
    """Raised when a workspace_dir passed to a workspace query does not exist.

    A typo'd or deleted workspace path must never silently answer "no runs /
    no refutations" — that would blind every query and the republish guard.
    """


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
    order: emission order on a freshly-sealed bundle. (If the index had to be
    regenerated from record.json — a corrupt/missing index — store.reindex
    orders by record_id instead; verdict resolution is order-independent, so
    only within-run presentation order is affected.)
    """

    run_id: str
    completed_at: str
    record_count: int
    claims: list[ClaimSighting] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Row (de)serialization — store.py json.dumps style
# ---------------------------------------------------------------------------


# The canonical order every query sees, regardless of runs.jsonl file order
# (append = seal order). Defined once so a new read path can't drift from it.
def _canonical_key(entry: RunEntry) -> tuple[str, str]:
    return (entry.completed_at, entry.run_id)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# The serialize side is a pure 1:1 field mirror (asdict recurses into the
# nested claims), so dataclasses.asdict IS the row dict — sort_keys makes key
# order irrelevant on disk. The deserialize side stays explicit: it coerces
# record_count and normalizes the edge lists / missing keys (schema stability).
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


def _write_manifest_rows(manifest: Path, entries: Iterable[RunEntry], *, mode: str) -> None:
    """Write manifest rows in one canonical format (append or overwrite).

    Single row spelling for both the seal-append (mode="a") and reindex
    overwrite (mode="w") sites, so the V7 invariant "seal-written row ==
    reindex-written row" cannot drift between them.
    """
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open(mode, encoding="utf-8") as f:
        for entry in entries:
            f.write(_dumps(asdict(entry)))
            f.write("\n")


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
    (``^[A-Za-z0-9._-]+$`` and not only dots — ValueError otherwise; a
    dot-only id like ``..`` would write the bundle outside runs/).  The
    default run_id is
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
                f"run_id {run_id!r} is not filesystem-safe: it must match "
                "^[A-Za-z0-9._-]+$ and must not be only dots."
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
    rows (records.jsonl order — emission order on a freshly-sealed bundle;
    record_id order if the index had to be regenerated, see below), and each
    critic claim's record.json for its refutes/supports edges.  Raises
    RunNotSealedError when the run has no
    run.json or no completedAt (never guess — an unsealed run is a fact).

    A missing or stale records.jsonl (row count disagreeing with run.json's
    record_ids/record_count) is never trusted: it is regenerated from the
    record.json set via store.reindex (the V7 mechanism — deterministic, not
    guessing) and re-read.  If it STILL disagrees the bundle is corrupt and
    RunNotSealedError is raised — never emit a silently contradictory
    manifest row.
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

    record_ids = meta.get("record_ids")
    expected_rows = len(record_ids) if record_ids is not None else int(meta.get("record_count", 0))

    def _read_index_rows() -> list[dict[str, Any]] | None:
        idx = index_path(run_dir)
        if not idx.exists():
            return None
        return [
            json.loads(line)
            for line in idx.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    rows = _read_index_rows()
    if rows is None or len(rows) != expected_rows:
        # Never trust a missing/stale index — regenerate it from the
        # record.json set (V7) and re-read.
        reindex(run_dir)
        rows = _read_index_rows() or []
        if len(rows) != expected_rows:
            raise RunNotSealedError(
                f"run {run_id!r} bundle is corrupt: records.jsonl has {len(rows)} rows "
                f"after reindex but run.json expects {expected_rows} records — refusing "
                "to emit a silently contradictory manifest row."
            )

    claim_rows = [row for row in rows if row.get("record_type") == "claim"]

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


def _read_manifest_rows(workspace_dir: Path) -> list[RunEntry]:
    """Parse runs.jsonl rows in FILE order (append = seal order).

    File order is a storage detail — callers wanting the canonical
    (completed_at, run_id) order must sort (list_runs does).
    """
    manifest = _manifest_path(workspace_dir)
    entries: list[RunEntry] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entries.append(_entry_from_dict(json.loads(line)))
    return entries


def _scan_bundles(workspace_dir: Path) -> tuple[list[RunEntry], list[str]]:
    """Build entries for every sealed bundle under runs/*/ (canonical order).

    Dirs without a usable run.json are skipped and returned second.
    """
    runs_root = workspace_dir / "runs"
    entries: list[RunEntry] = []
    skipped: list[str] = []
    if runs_root.exists():
        for run_path in sorted(p for p in runs_root.iterdir() if p.is_dir()):
            try:
                entries.append(_build_entry(workspace_dir, run_path.name))
            except RunNotSealedError:
                skipped.append(run_path.name)
    entries.sort(key=_canonical_key)
    return entries, skipped


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
    manifest ROW the existing entry is returned and no duplicate is
    appended — the check reads the manifest file itself, so a sealed bundle
    whose row went missing (interrupted seal, deleted manifest) is re-rowed
    rather than silently skipped.  Otherwise finalizeRun (itself idempotent)
    + write_run_json run first, then the row is built by scanning the sealed
    bundle — the same scan reindex_runs uses, so rebuilt rows equal
    seal-written rows.
    """
    workspace_dir = Path(workspace_dir).resolve()
    run_dir = Path(run_dir).resolve()
    # Resolve the final runs component too: a symlinked runs/ dir must
    # canonicalize to the same real path run_dir.resolve() reaches.
    runs_root = (workspace_dir / "runs").resolve()
    if run_dir.parent != runs_root:
        raise ValueError(
            f"run_dir {run_dir} is not under {runs_root} — seal_run only seals "
            "runs that live inside the workspace."
        )
    run_id = run_dir.name

    # Idempotency (V10): if this run_id already has a manifest ROW, return it.
    # Scan run_id off the raw lines — no need to deserialize every prior run's
    # full claim list just to compare one string.
    manifest = _manifest_path(workspace_dir)
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("run_id") == run_id:
                return _entry_from_dict(row)

    finalizeRun(run_state)
    write_run_json(run_dir, run_state, extra)

    entry = _build_entry(workspace_dir, run_id)
    _write_manifest_rows(manifest, [entry], mode="a")
    return entry


def list_runs(workspace_dir: Path | str) -> list[RunEntry]:
    """Sealed-run entries in CANONICAL order: (completed_at, run_id).

    runs.jsonl file order (append = seal order) is a storage detail; entries
    are sorted by the canonical key regardless of file order, so
    claim_history / claim_by_id / standing_refutations see the same order
    before and after reindex_runs.

    A nonexistent workspace_dir raises WorkspaceNotFoundError — a typo'd
    path must never silently answer "no runs".  When the workspace exists
    but runs.jsonl is missing, sealed bundles under runs/*/ are scanned
    in memory instead; the manifest is NOT recreated (reads must not
    write).  An existing-but-empty workspace still yields [].  Blank
    manifest lines are skipped.
    """
    workspace_dir = Path(workspace_dir)
    if not workspace_dir.exists():
        raise WorkspaceNotFoundError(
            f"workspace {workspace_dir} does not exist — refusing to answer "
            "workspace queries for a path that was never a workspace."
        )
    if _manifest_path(workspace_dir).exists():
        entries = _read_manifest_rows(workspace_dir)
        entries.sort(key=_canonical_key)
        return entries
    entries, _skipped = _scan_bundles(workspace_dir)
    return entries


def reindex_runs(workspace_dir: Path | str) -> tuple[int, list[str]]:
    """Rebuild runs.jsonl from runs/*/run.json bundles (V7 analog).

    Sealed runs are written in canonical (completedAt, run_id) order; dirs
    without a usable run.json are skipped and returned in the second
    element.  Overwrites runs.jsonl.  Row CONTENT is identical per run to
    the seal-written row (same bundle scan); file order is canonicalized,
    so a second reindex is byte-identical to the first (idempotent).
    """
    workspace_dir = Path(workspace_dir).resolve()
    entries, skipped = _scan_bundles(workspace_dir)
    _write_manifest_rows(_manifest_path(workspace_dir), entries, mode="w")
    return len(entries), skipped


# ---------------------------------------------------------------------------
# Claim history queries
# ---------------------------------------------------------------------------


def claim_history(workspace_dir: Path | str, claim_id: str) -> list[ClaimSighting]:
    """Every sighting of claim_id across sealed runs, in canonical run order."""
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
    critic claim (freshly emitted, or reused on re-invocation; None when the
    emit was rejected — the critique still applied).  downgrade_required is
    True when the V16 gate fired on the new record (published tier or board
    audience) — the caller must downgrade before rendering.
    """

    claim_id: str
    record_id: str
    tier: str
    prior_run_id: str
    prior_record_id: str
    prior_refuting_record_ids: list[str]
    critic_record_id: str | None
    downgrade_required: bool


def _guard_critic_claim_id(claim_id: str, prior_run_id: str, new_record_id: str) -> str:
    """Deterministic gate-valid claim_id for the guard's critic claim.

    Namespace is the target claim_id's leading ``[A-Z]{2,5}`` segment; the
    number derives from sha256 of "claim_id|prior_run_id|new_record_id"
    (hamilton adapter hash-to-number scheme) so identical workspaces yield
    identical ids.  Salting with the target record id makes the id stable
    across re-invocations for the SAME target record (guard idempotency)
    while distinct targets get distinct ids.  The 9-digit number space
    (100_000_000..999_999_999 — CLAIM_ID_REGEX allows ``\\d{3,}``) makes
    collisions between distinct targets, or with human-authored 3-digit
    ``<NS>-X-NNN`` ids, unrealistic.
    """
    match = _NAMESPACE_RE.match(claim_id)
    namespace = match.group(0) if match else "IK"
    digest = hashlib.sha256(f"{claim_id}|{prior_run_id}|{new_record_id}".encode()).hexdigest()
    return f"{namespace}-X-{100_000_000 + int(digest[:12], 16) % 900_000_000}"


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
         (published tier / board audience) is caught and surfaced as
         downgrade_required=True.

    Idempotent (V10 mirror): the guard's critic claim_id is deterministic
    per target record, so a re-invocation on the same run finds the critic
    already in the run, reuses it, and returns an equal findings list — no
    duplicate emission, no duplicate critique event, rejectionCount stays 0.

    Guard critiques are cross-run surfacings, not critique-fix rounds of
    THIS run — run_state.critiqueRounds (the V16 fix-round budget) is
    preserved across every guard apply_critique call.

    SURFACE, NEVER BLOCK: the guard raises nothing for guard hits; it
    returns findings.  (Doctrine: only deductive identities may block.)
    Even a rejected critic emit (LayerAValidationError) only nulls
    critic_record_id on the finding — the critique still applies.
    """
    run_dir = Path(run_dir)
    standing = standing_refutations(workspace_dir)
    findings: list[RepublishFinding] = []

    # Snapshot — emitting guard critics appends to run_state.records.
    snapshot = list(run_state.records)

    # Build the idempotency lookup ONCE from the entry snapshot: stored
    # claim_id -> record_id for every claim record already in the run.  A
    # critic emitted by a prior guard invocation is found here by its
    # deterministic claim_id.
    claim_records: list[tuple[RecordRef, dict[str, Any]]] = []
    record_id_by_claim_id: dict[str, str] = {}
    for ref in snapshot:
        if ref.record_type != "claim":
            continue
        record = read_record(run_dir, ref.record_id)
        claim_records.append((ref, record))
        record_id_by_claim_id[str(record.get("claim_id"))] = ref.record_id

    for ref, record in claim_records:
        tier = str(record.get("tier"))
        if tier not in _GUARDED_TIERS:
            continue
        claim_id = str(record.get("claim_id"))
        prior = standing.get(claim_id)
        if prior is None:
            continue
        audience = record.get("audience")

        critic_claim_id = _guard_critic_claim_id(claim_id, prior.run_id, ref.record_id)
        existing_critic_id = record_id_by_claim_id.get(critic_claim_id)
        critic_record_id: str | None
        if existing_critic_id is not None:
            # Re-invocation: this target's critic was already emitted and its
            # critique already applied.  Reuse the record and recompute the
            # gate exposure from the record itself — no second emission, no
            # double critique event, no rounds spend.
            critic_record_id = existing_critic_id
            downgrade_required = tier == "published" or audience == "board"
        else:
            reason = (
                f"claim_id {claim_id} was refuted in run {prior.run_id} and "
                "republished without a superseding verdict"
            )
            try:
                critic_ref = ik_claim_emit(
                    critic_claim_id,
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
                critic_record_id = critic_ref.record_id
            except LayerAValidationError:
                # Belt-and-braces: surface, never block — a rejected critic
                # emit must not abort the guard; the critique below still applies.
                critic_record_id = None

            downgrade_required = False
            # Guard critiques are cross-run surfacings, not critique-fix rounds
            # of THIS run — the guard must not spend the run's V16 fix-round
            # budget, so critiqueRounds is restored on every path (return,
            # CritiqueGateError, unexpected error).
            saved_rounds = run_state.critiqueRounds
            try:
                gate_result = apply_critique(
                    run_state=run_state,
                    record_id=ref.record_id,
                    record_type="claim",
                    tier=tier,
                    audience=audience,
                    critique=CritiqueState.open(
                        severity="high",
                        reason=reason,
                        critic_id=critic_record_id,
                        target_record_id=ref.record_id,
                    ),
                    run_dir=run_dir,
                )
                downgrade_required = bool(gate_result.get("downgraded"))
            except CritiqueGateError:
                downgrade_required = True
            finally:
                run_state.critiqueRounds = saved_rounds

        findings.append(
            RepublishFinding(
                claim_id=claim_id,
                record_id=ref.record_id,
                tier=tier,
                prior_run_id=prior.run_id,
                prior_record_id=prior.record_id,
                prior_refuting_record_ids=list(prior.refuted_by),
                critic_record_id=critic_record_id,
                downgrade_required=downgrade_required,
            )
        )

    return findings

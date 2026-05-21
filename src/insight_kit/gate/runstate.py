"""T5 — RunState accumulator + idempotent finalizeRun + manifest_complete assert.
T12 — critique severity gate + critiqueRounds counter (V16).
T13 — published-tier fail-closed hooks (V17).

RunState tracks all records emitted within a run session, rejection count,
and critique rounds. finalizeRun is idempotent — completedAt guard ensures
double-calls (agent_end + session_shutdown) are safe.

Cites: V10, V16, V17, I.run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# RecordRef — lightweight reference returned by emit
# ---------------------------------------------------------------------------


@dataclass
class RecordRef:
    """Lightweight reference to an emitted record.

    record_id:          content-addressed id (fingerprint prefix).
    record_type:        one of claim|intervention|research|skill_use.
    record_fingerprint: full sha256 hex of the canonical record.json.
    run_dir:            absolute path to the run directory.
    """

    record_id: str
    record_type: str
    record_fingerprint: str
    run_dir: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "record_type": self.record_type,
            "record_fingerprint": self.record_fingerprint,
            "run_dir": str(self.run_dir),
        }


# ---------------------------------------------------------------------------
# ManifestError — raised when manifest_complete assertion fails
# ---------------------------------------------------------------------------


class ManifestError(Exception):
    """Raised when records.jsonl row count != RunState.records length (V17)."""


# ---------------------------------------------------------------------------
# T13 — PublishedRunError: raised when published-tier finalize fails closed
# ---------------------------------------------------------------------------


class PublishedRunError(Exception):
    """Raised when a published run fails finalization (V17 — fail closed)."""


# ---------------------------------------------------------------------------
# T12 — Critique severity gate (V16)
# ---------------------------------------------------------------------------

_CRITIQUE_ROUNDS_CAP = 3
"""Cap on critiqueRounds before downgrade path activates (V16)."""

# Tiered record types that are subject to the critique gate
_GATED_RECORD_TYPES = frozenset({"claim", "intervention"})

# Audience tags that trigger the gate (V16: published/audience:board)
_GATED_AUDIENCES = frozenset({"board"})


class CritiqueSeverity(IntEnum):
    """Ordered severity levels for critique records.

    Integer ordering allows `>= high` comparisons (V16).
    """

    low = 1
    medium = 2
    high = 3
    critical = 4


@dataclass
class CritiqueState:
    """Immutable snapshot of a single critique.

    status:   'open' | 'resolved'.
    severity: CritiqueSeverity.
    reason:   free-text explanation.
    """

    status: str
    severity: CritiqueSeverity
    reason: str

    @classmethod
    def open(cls, *, severity: str | CritiqueSeverity, reason: str) -> CritiqueState:
        """Factory for an open critique."""
        if isinstance(severity, str):
            severity = CritiqueSeverity[severity]
        return cls(status="open", severity=severity, reason=reason)

    def resolve(self) -> CritiqueState:
        """Return a new CritiqueState with status='resolved'."""
        return CritiqueState(status="resolved", severity=self.severity, reason=self.reason)


class CritiqueGateError(Exception):
    """Raised when an open critique of severity >= high blocks a published/board record.

    Callers MUST catch this and force the record tier to 'draft' (V16).
    """


def _is_gated_tier(tier: str | None, audience: str | None) -> bool:
    """Return True if this tier/audience combination is subject to the critique gate.

    The gate applies to:
      - tier == 'published'  (explicit published tier)
      - audience == 'board'  (regardless of tier — V16: published/audience:board)
    """
    if tier == "published":
        return True
    if audience in _GATED_AUDIENCES:
        return True
    return False


def apply_critique(
    *,
    run_state: RunState,
    record_id: str,
    record_type: str,
    tier: str | None,
    audience: str | None,
    critique: CritiqueState,
) -> dict[str, Any]:
    """Apply a critique to a record and enforce the severity gate (V16).

    Increments `run_state.critiqueRounds` on every call.

    Gate logic:
      - If critique.status != 'open' → no gate check needed. Return passthrough.
      - If record_type not in {claim, intervention} → no gate (untiered records).
      - If not a gated tier/audience → no gate.
      - If severity < high → no gate.
      - If critiqueRounds >= cap (3) → downgrade path: return {"downgraded": True, "tier": "draft"}.
      - Otherwise → raise CritiqueGateError (caller MUST downgrade tier).

    Returns a dict:
      - Normal pass: {"downgraded": False, "tier": tier}
      - Downgrade at cap: {"downgraded": True, "tier": "draft"}

    Raises CritiqueGateError when severity gate fires (below cap).
    """
    run_state.critiqueRounds += 1

    # Gate only applies to tiered record types
    if record_type not in _GATED_RECORD_TYPES:
        return {"downgraded": False, "tier": tier}

    # Gate only fires on open critiques
    if critique.status != "open":
        return {"downgraded": False, "tier": tier}

    # Gate only fires on gated tiers/audiences
    if not _is_gated_tier(tier, audience):
        return {"downgraded": False, "tier": tier}

    # Gate only fires on severity >= high
    if critique.severity < CritiqueSeverity.high:
        return {"downgraded": False, "tier": tier}

    # Cap check: if rounds already at cap, downgrade instead of raising
    # Note: critiqueRounds was already incremented above, so cap check
    # uses the pre-increment count, meaning: if we were AT cap before this
    # call, we downgrade. Cap is the threshold for switching from raise to downgrade.
    # V16: "cap 3 then downgrade" — after 3 failed rounds, switch to downgrade mode.
    pre_increment_rounds = run_state.critiqueRounds - 1
    if pre_increment_rounds >= _CRITIQUE_ROUNDS_CAP:
        return {"downgraded": True, "tier": "draft"}

    raise CritiqueGateError(
        f"Open critique of severity={critique.severity.name!r} on record "
        f"{record_id!r} (type={record_type!r}, tier={tier!r}, audience={audience!r}) "
        f"blocks published/board render. Force tier to 'draft' before emitting. (V16)"
    )


# ---------------------------------------------------------------------------
# RunState accumulator
# ---------------------------------------------------------------------------


@dataclass
class RunState:
    """Per-run accumulator tracking emitted records and quality counters.

    records:        list of RecordRef for every successfully emitted record.
    rejectionCount: incremented each time _record_emit rejects a payload (V2).
    critiqueRounds: incremented by the critique severity gate (T12 seam).
    completedAt:    set by finalizeRun; None until finalized.
    run_dir:        run directory path (required for manifest_complete assertion).
    tool_calls:     count of tool_call messages seen in this run (T13 — V17).
    tool_results:   count of tool_result messages seen in this run (T13 — V17).
    """

    records: list[RecordRef] = field(default_factory=list)
    rejectionCount: int = 0  # noqa: N815  camelCase = cross-language on-disk contract — do not snake_case
    critiqueRounds: int = 0  # noqa: N815  camelCase = cross-language on-disk contract — do not snake_case
    completedAt: str | None = None  # noqa: N815  camelCase = cross-language on-disk contract — do not snake_case
    run_dir: Path | None = None
    tool_calls: int = 0
    tool_results: int = 0

    def record_ids(self) -> list[str]:
        """Return list of record_ids in emission order."""
        return [r.record_id for r in self.records]

    def manifest_complete(self) -> None:
        """Assert records.jsonl row count == len(self.records).

        Raises ManifestError on mismatch (V17).
        No-op if run_dir is not set (permissive for unit tests without storage).
        """
        if self.run_dir is None:
            return

        from insight_kit.gate.store import index_path

        idx = index_path(self.run_dir)
        if not idx.exists():
            row_count = 0
        else:
            rows = [
                line
                for line in idx.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            row_count = len(rows)

        expected = len(self.records)
        if row_count != expected:
            raise ManifestError(
                f"manifest_complete failed: records.jsonl has {row_count} rows "
                f"but RunState.records has {expected} entries. "
                "This indicates a partial write or corrupted index (V17)."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "rejectionCount": self.rejectionCount,
            "critiqueRounds": self.critiqueRounds,
            "completedAt": self.completedAt,
            "run_dir": str(self.run_dir) if self.run_dir else None,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
        }


# ---------------------------------------------------------------------------
# finalizeRun — idempotent (V10)
# ---------------------------------------------------------------------------


def finalizeRun(  # noqa: N802  camelCase = cross-language on-disk contract — do not snake_case
    run_state: RunState,
    *,
    assert_manifest: bool = True,
) -> RunState:
    """Idempotent run finalization.

    Sets completedAt on the RunState. Second call is a no-op (completedAt guard).
    Optionally asserts manifest_complete (V17) — skipped on second call.

    Args:
        run_state:        the RunState to finalize.
        assert_manifest:  if True, call manifest_complete() before finalizing.
                         Pass False for draft/test runs where no storage is wired.

    Returns the mutated RunState (for chaining convenience).
    """
    if run_state.completedAt is not None:
        # Already finalized — idempotent no-op (V10)
        return run_state

    if assert_manifest:
        run_state.manifest_complete()

    run_state.completedAt = datetime.now(UTC).isoformat()
    return run_state


# ---------------------------------------------------------------------------
# T13 — finalize_published_run: published-tier fail-closed (V17)
# ---------------------------------------------------------------------------


def finalize_published_run(run_state: RunState) -> RunState:
    """Fail-closed finalization for published runs (V17).

    Unlike finalizeRun which is permissive on draft, this function is FATAL
    on any mismatch — no unauditable published record can escape.

    Checks (all raise PublishedRunError on failure):
      1. records.jsonl row count == len(RunState.records)
         (the core manifest_complete assertion, V17).
      2. tool_calls == tool_results
         (every tool_call must have a paired tool_result — no hanging calls).

    On success: sets completedAt and returns the mutated RunState.
    On failure: leaves completedAt as None (run is aborted, not finalized).

    Note: this function is NOT idempotent — it re-checks on every call.
    This is intentional: a second call after a manifest fix should succeed.
    """
    # Check 1: tool_call / tool_result balance
    if run_state.tool_calls != run_state.tool_results:
        raise PublishedRunError(
            f"Published run finalization failed (V17): "
            f"tool_calls={run_state.tool_calls} != tool_results={run_state.tool_results}. "
            "Every tool_call must have a paired tool_result. "
            "Run fails closed — no unauditable published record."
        )

    # Check 2: manifest completeness (records.jsonl == RunState.records length)
    try:
        run_state.manifest_complete()
    except ManifestError as exc:
        raise PublishedRunError(
            f"Published run finalization failed (V17): manifest mismatch — {exc}"
        ) from exc

    run_state.completedAt = datetime.now(UTC).isoformat()
    return run_state


# ---------------------------------------------------------------------------
# run.json writer (I.run)
# ---------------------------------------------------------------------------


def write_run_json(run_dir: Path, run_state: RunState, extra: dict[str, Any] | None = None) -> Path:
    """Write run.json to run_dir from a finalized RunState.

    Merges optional extra metadata (e.g. agent_version, env info for T20).
    Overwrites if already present — run.json is mutable metadata, unlike record.json.
    """
    run_json_path = run_dir / "run.json"
    run_json_path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "completedAt": run_state.completedAt,
        "rejectionCount": run_state.rejectionCount,
        "critiqueRounds": run_state.critiqueRounds,
        "record_ids": run_state.record_ids(),
        "record_count": len(run_state.records),
    }
    if extra:
        payload.update(extra)

    run_json_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return run_json_path

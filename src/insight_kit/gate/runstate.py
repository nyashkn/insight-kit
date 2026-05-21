"""T5 — RunState accumulator + idempotent finalizeRun + manifest_complete assert.

RunState tracks all records emitted within a run session, rejection count,
and critique rounds. finalizeRun is idempotent — completedAt guard ensures
double-calls (agent_end + session_shutdown) are safe.

Cites: V10, V17, I.run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    """

    records: list[RecordRef] = field(default_factory=list)
    rejectionCount: int = 0  # noqa: N815  camelCase = cross-language on-disk contract — do not snake_case
    critiqueRounds: int = 0  # noqa: N815  camelCase = cross-language on-disk contract — do not snake_case
    completedAt: str | None = None  # noqa: N815  camelCase = cross-language on-disk contract — do not snake_case
    run_dir: Path | None = None

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

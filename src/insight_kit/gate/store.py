"""T4 — Storage layer for the L1 typed-record gate.

On-disk layout under run_dir:
  records/{id}/record.json          canonical, immutable (C3 — refuse overwrite)
  records.jsonl                     derived projection index, one row per record
  claims.jsonl                      regenerable claim-projection view (Evidence back-compat, I.store)
  records/{id}/events/              append-only event log (I.events)

Invariants:
  V1  — only emit writes records.jsonl / record.json.
  V3  — record.json immutable post-emit. Overwrite refused (FileExistsError).
  V7  — records.jsonl regenerable from record.json set via reindex(run_dir).

Cites: V3, V7, I.store, I.events.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Run-dir resolution
# ---------------------------------------------------------------------------


def resolve_run_dir(run_dir: Path | None = None) -> Path:
    """Resolve the run directory.

    Priority:
      1. Explicit `run_dir` argument.
      2. INSIGHT_KIT_RUN_DIR environment variable.
      3. find_kit_root() / .insight-kit/runs/<current-run> — but this requires
         a live run context we don't have here. Callers that use the gate stand-
         alone MUST pass run_dir or set INSIGHT_KIT_RUN_DIR.

    Raises ValueError if neither is available.
    """
    if run_dir is not None:
        return Path(run_dir).resolve()

    env_dir = os.environ.get("INSIGHT_KIT_RUN_DIR")
    if env_dir:
        return Path(env_dir).resolve()

    raise ValueError(
        "run_dir is required: pass it explicitly or set INSIGHT_KIT_RUN_DIR env var."
    )


# ---------------------------------------------------------------------------
# record.json — canonical, immutable
# ---------------------------------------------------------------------------


def record_path(run_dir: Path, record_id: str) -> Path:
    """Path to records/{id}/record.json."""
    return run_dir / "records" / record_id / "record.json"


def write_record(
    run_dir: Path,
    record_id: str,
    record_dict: dict[str, Any],
) -> Path:
    """Write records/{id}/record.json.

    Raises FileExistsError (V3) if record.json already exists — immutable post-emit.
    Creates parent directories as needed.
    Returns the path to the written file.
    """
    path = record_path(run_dir, record_id)
    if path.exists():
        raise FileExistsError(
            f"record.json already exists at {path}. "
            "Records are immutable post-emit (V3). "
            "Create a new record with a 'supersedes' edge instead."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def read_record(run_dir: Path, record_id: str) -> dict[str, Any]:
    """Read and return the parsed contents of records/{id}/record.json."""
    path = record_path(run_dir, record_id)
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# records.jsonl — derived projection index
# ---------------------------------------------------------------------------


def index_path(run_dir: Path) -> Path:
    """Path to records.jsonl."""
    return run_dir / "records.jsonl"


def _projection_row(record_dict: dict[str, Any], record_id: str) -> dict[str, Any]:
    """Build the projection row for records.jsonl.

    Must carry record_type discriminant (V7).
    Includes the stable record_id and record-type-specific primary key.
    """
    record_type = record_dict["record_type"]
    row: dict[str, Any] = {
        "record_id": record_id,
        "record_type": record_type,
    }
    # Include primary key field for each type (convenience for index consumers)
    if record_type == "claim":
        row["claim_id"] = record_dict.get("claim_id")
        row["tier"] = record_dict.get("tier")
    elif record_type == "intervention":
        row["intervention_id"] = record_dict.get("intervention_id")
        row["tier"] = record_dict.get("tier")
    elif record_type == "research":
        row["research_id"] = record_dict.get("research_id")
    elif record_type == "skill_use":
        row["skill_use_id"] = record_dict.get("skill_use_id")

    # Always include fingerprints if present
    for key in ("record_fingerprint", "data_fingerprint"):
        if key in record_dict:
            row[key] = record_dict[key]

    return row


def append_index_row(run_dir: Path, record_dict: dict[str, Any], record_id: str) -> None:
    """Append one projection row to records.jsonl."""
    row = _projection_row(record_dict, record_id)
    idx = index_path(run_dir)
    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        f.write("\n")


# ---------------------------------------------------------------------------
# claims.jsonl — regenerable claim-projection view (Evidence back-compat, I.store)
# ---------------------------------------------------------------------------


def claims_index_path(run_dir: Path) -> Path:
    """Path to claims.jsonl."""
    return run_dir / "claims.jsonl"


def _claims_row(record_dict: dict[str, Any], record_id: str) -> dict[str, Any]:
    """Build a claim-projection row for claims.jsonl back-compat view."""
    return {
        "record_id": record_id,
        "record_type": "claim",
        "claim_id": record_dict.get("claim_id"),
        "tier": record_dict.get("tier"),
        "fields": record_dict.get("fields"),
        "audience": record_dict.get("audience"),
        "narrative_ref": record_dict.get("narrative_ref"),
        "record_fingerprint": record_dict.get("record_fingerprint"),
        "data_fingerprint": record_dict.get("data_fingerprint"),
    }


def append_claims_row(run_dir: Path, record_dict: dict[str, Any], record_id: str) -> None:
    """Append one row to claims.jsonl (claim records only)."""
    if record_dict.get("record_type") != "claim":
        return
    row = _claims_row(record_dict, record_id)
    idx = claims_index_path(run_dir)
    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        f.write("\n")


# ---------------------------------------------------------------------------
# events/*.jsonl — append-only event log
# ---------------------------------------------------------------------------


def events_dir(run_dir: Path, record_id: str) -> Path:
    """Path to records/{id}/events/."""
    return run_dir / "records" / record_id / "events"


def append_event(
    run_dir: Path,
    record_id: str,
    event_name: str,
    event_data: dict[str, Any],
) -> Path:
    """Append one event to records/{id}/events/{event_name}.jsonl.

    Creates the events/ directory if needed.
    Returns the path to the event log file.
    """
    evdir = events_dir(run_dir, record_id)
    evdir.mkdir(parents=True, exist_ok=True)
    ev_path = evdir / f"{event_name}.jsonl"
    with ev_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        f.write("\n")
    return ev_path


# ---------------------------------------------------------------------------
# reindex — regenerate records.jsonl from record.json set (V7)
# ---------------------------------------------------------------------------


def reindex(run_dir: Path) -> int:
    """Rebuild records.jsonl (and claims.jsonl) from the record.json set.

    Scans records/*/record.json, sorts by record_id for deterministic output.
    Overwrites the existing index files.
    Returns the number of records indexed.

    Invariant V7: records.jsonl must be regenerable from record.json set.
    """
    run_dir = Path(run_dir).resolve()
    records_root = run_dir / "records"

    rows: list[dict[str, Any]] = []
    claim_rows: list[dict[str, Any]] = []

    if records_root.exists():
        record_ids = sorted(
            p.parent.name
            for p in records_root.glob("*/record.json")
        )
        for rid in record_ids:
            try:
                rec = read_record(run_dir, rid)
                rows.append(_projection_row(rec, rid))
                if rec.get("record_type") == "claim":
                    claim_rows.append(_claims_row(rec, rid))
            except Exception:
                continue  # corrupt record — skip, don't crash reindex

    # Overwrite records.jsonl
    idx = index_path(run_dir)
    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            f.write("\n")

    # Overwrite claims.jsonl
    cidx = claims_index_path(run_dir)
    with cidx.open("w", encoding="utf-8") as f:
        for row in claim_rows:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
            f.write("\n")

    return len(rows)

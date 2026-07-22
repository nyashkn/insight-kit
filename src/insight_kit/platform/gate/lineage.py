"""Deterministic DAG lineage surfaced on gate records (item 7, I.lineage).

The Hamilton adapter stamps every metric claim with its node's transitive
upstream closure (a ``lineage`` claim field) and pairs the extraction
skill_use snapshot with the same trace next to the captured rows. This module
is the read side: given a claim record id, walk claim -> cites -> skill_use ->
snapshot and answer "where did this number come from" without re-running the
DAG.

Two invariants:
  * No hamilton import (C1/V5) — lineage is read back as plain record data, so
    the ProvenanceRail and critics work from the sealed run bundle alone.
  * Lineage is never guessed. A claim without a stamped lineage field raises
    ``LineageNotRecordedError`` rather than returning a reconstruction — an absent
    trace is a fact about the claim, not a gap to paper over.

Cites: item 7 (brief §07); V20/T22 (snapshot), V22 (registered input), C1/V5.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from insight_kit.platform.gate.store import read_record, snapshot_path


class LineageNotRecordedError(LookupError):
    """Raised when a claim carries no stamped lineage field."""


@dataclass(frozen=True)
class LineageTrace:
    """A claim's answer to "where did this number come from".

    node / direct_upstream / upstream_closure / external_inputs come from the
    compiled Hamilton graph (code-derived, deterministic). extraction_record_id
    and input_rows come from the cited skill_use record — the exact rows the
    value was computed from, when the claim has registered-input provenance.
    """

    claim_record_id: str
    claim_id: str
    node: str
    direct_upstream: list[str] = field(default_factory=list)
    upstream_closure: list[str] = field(default_factory=list)
    external_inputs: list[str] = field(default_factory=list)
    overridden: list[str] = field(default_factory=list)
    data_fingerprint_source: str | None = None
    extraction_record_id: str | None = None
    input_rows: dict[str, Any] | None = None

    def depends_on(self, node_name: str) -> bool:
        """True when `node_name` is anywhere upstream of the claim's node."""
        return node_name in self.upstream_closure

    @property
    def is_overridden(self) -> bool:
        """True when any upstream value was replaced at execute time.

        An overridden claim's value did not flow from the registered sources —
        the closure is truncated at the override points, and consumers (rails,
        critics, promotion policies) should treat the trace as caller-supplied
        beyond them.
        """
        return bool(self.overridden)


def lineage_of(run_dir: Path | str, claim_record_id: str) -> LineageTrace:
    """Read a claim's full lineage trace back from the run bundle.

    Walks the sealed records only: the claim's stamped ``lineage`` field gives
    the graph position; the cited hamilton skill_use record (when present)
    gives the extraction and its captured ``input_rows`` snapshot.

    Raises:
        LineageNotRecordedError: the record is a claim but carries no lineage field
            (emitted outside a driver run, or by a non-metric path).
        ValueError: the record is not a claim record.
    """
    run_dir = Path(run_dir)
    rec = read_record(run_dir, claim_record_id)
    if rec.get("record_type") != "claim":
        raise ValueError(
            f"lineage_of expects a claim record; {claim_record_id} is "
            f"{rec.get('record_type')!r}"
        )

    lineage_field = (rec.get("fields") or {}).get("lineage")
    lineage = lineage_field.get("value") if isinstance(lineage_field, dict) else None
    if not isinstance(lineage, dict):
        raise LineageNotRecordedError(
            f"claim {claim_record_id} ({rec.get('claim_id')}) carries no lineage "
            "field — it was not emitted through a lineage-capturing driver run"
        )

    extraction_record_id: str | None = None
    input_rows: dict[str, Any] | None = None
    for cited_id in rec.get("cites") or []:
        try:
            cited = read_record(run_dir, cited_id)
        except Exception:
            continue
        if cited.get("record_type") == "skill_use" and cited.get("tool") == "hamilton":
            extraction_record_id = cited_id
            snap_file = snapshot_path(run_dir, cited_id)
            if snap_file.exists():
                snap = json.loads(snap_file.read_text())
                if isinstance(snap, dict):
                    rows = snap.get("input_rows")
                    input_rows = rows if isinstance(rows, dict) else None
            break

    return LineageTrace(
        claim_record_id=claim_record_id,
        claim_id=str(rec.get("claim_id", "")),
        node=str(lineage.get("node", "")),
        direct_upstream=list(lineage.get("direct_upstream", [])),
        upstream_closure=list(lineage.get("upstream_closure", [])),
        external_inputs=list(lineage.get("external_inputs", [])),
        overridden=list(lineage.get("overridden", [])),
        data_fingerprint_source=rec.get("data_fingerprint_source"),
        extraction_record_id=extraction_record_id,
        input_rows=input_rows,
    )


def trace_to_rows(run_dir: Path | str, claim_record_id: str) -> dict[str, Any] | None:
    """The exact input rows a claim's value was computed from, or None.

    Convenience over :func:`lineage_of`: returns the captured ``input_rows``
    snapshot (per upstream input name, column dict) from the claim's cited
    extraction record. None means the claim has no captured rows — which
    coincides with payload provenance, the P1 signature.
    """
    return lineage_of(run_dir, claim_record_id).input_rows

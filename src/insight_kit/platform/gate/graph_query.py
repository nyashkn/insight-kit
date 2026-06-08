"""T28 — Read-only cites/supersedes graph query over the record.json set.

Derives a full forward/reverse adjacency view of cites and supersedes edges
by scanning the record.json set, following the same pattern as store.py:258
reindex().  The graph is regenerated on each call — no projection is persisted
(V7 compliant, pure read-only).

Public API:
    query_cites(run_dir) -> GraphAdjacency

Invariants respected:
    V3  — record.json files are never modified.
    V7  — scan pattern mirrors reindex; regenerable from record.json set.

Cites: V3, V7, I.store, T28.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from insight_kit.platform.gate.store import resolve_run_dir

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AdjacencyNode:
    """Edges for a single record in the knowledge graph.

    record_id: unique stable id of this record.
    record_type: 'claim' | 'intervention' | 'research' | 'skill_use'.
    cites: list of record_ids this record directly cites (outgoing refs).
    cited_by: list of record_ids that cite this one (reverse edges, derived).
    supersedes: single record_id this record supersedes (or None).
    superseded_by: list of record_ids that supersede this one (derived).
    """

    record_id: str
    record_type: str
    cites: list[str] = field(default_factory=list)
    cited_by: list[str] = field(default_factory=list)
    supersedes: str | None = None
    superseded_by: list[str] = field(default_factory=list)


@dataclass
class GraphAdjacency:
    """Adjacency view of cites/supersedes edges for all records in a run.

    graph: dict[str, AdjacencyNode] keyed by record_id.
    record_count: total records successfully scanned.
    """

    graph: dict[str, AdjacencyNode] = field(default_factory=dict)
    record_count: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_edges(rec: dict[str, Any]) -> tuple[str | None, list[str], str | None]:
    """Extract (record_id, cites, supersedes) from a raw record dict.

    Returns (record_id, cites_list, supersedes_or_None).
    Returns (None, [], None) if the dict is missing a stable id field.
    """
    record_type = rec.get("record_type", "")

    # Determine the canonical id field per discriminated-union kind.
    id_field_map = {
        "claim": "claim_id",
        "intervention": "intervention_id",
        "research": "research_id",
        "skill_use": "skill_use_id",
    }
    id_field = id_field_map.get(record_type)
    record_id: str | None = rec.get(id_field) if id_field else None
    if not record_id:
        # Fall back to the directory name the caller may have injected.
        record_id = rec.get("_record_id")
    if not record_id:
        return None, [], None

    cites: list[str] = rec.get("cites") or []
    supersedes: str | None = rec.get("supersedes") or None
    return record_id, cites, supersedes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def query_cites(run_dir: Path | None = None) -> GraphAdjacency:
    """Build adjacency view of cites/supersedes edges from the record.json set.

    Scans records/*/record.json following the store.py:258 reindex pattern,
    builds an in-memory adjacency dict on each call.  Corrupt or unreadable
    record.json files are skipped (logged at WARNING), matching reindex
    behaviour.

    Args:
        run_dir: Path to run directory.  Resolved via store.resolve_run_dir()
                 (explicit arg → INSIGHT_KIT_RUN_DIR env → ValueError).

    Returns:
        GraphAdjacency with forward (cites, supersedes) and derived reverse
        (cited_by, superseded_by) edges for every successfully scanned record.
        Returns GraphAdjacency(graph={}, record_count=0) for an empty run_dir.

    Raises:
        ValueError: if run_dir cannot be resolved.
    """
    run_dir = resolve_run_dir(run_dir)
    records_root = run_dir / "records"

    # Pass 1 — forward edges (scan record.json set, mirror reindex pattern).
    nodes: dict[str, AdjacencyNode] = {}
    skipped: list[str] = []

    if records_root.exists():
        record_ids = sorted(
            p.parent.name
            for p in records_root.glob("*/record.json")
        )
        for dir_id in record_ids:
            rec_path = records_root / dir_id / "record.json"
            try:
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
            except Exception:
                skipped.append(dir_id)
                log.warning(
                    "graph_query: skipping corrupt record",
                    extra={"record_id": dir_id, "run_dir": str(run_dir)},
                )
                continue

            record_id, cites, supersedes = _extract_edges(rec)
            if record_id is None:
                # Use directory name as fallback stable id.
                record_id = dir_id

            record_type = rec.get("record_type", "unknown")

            # Ensure this record exists in the graph.
            if record_id not in nodes:
                nodes[record_id] = AdjacencyNode(
                    record_id=record_id,
                    record_type=record_type,
                )
            else:
                # Node was pre-created as a target of a reverse edge; fill it in.
                nodes[record_id].record_type = record_type

            node = nodes[record_id]
            node.cites = list(cites)
            node.supersedes = supersedes

            # Ensure cited targets exist in graph (as stubs for reverse wiring).
            for cited_id in cites:
                if cited_id not in nodes:
                    nodes[cited_id] = AdjacencyNode(
                        record_id=cited_id,
                        record_type="unknown",
                    )

            if supersedes and supersedes not in nodes:
                nodes[supersedes] = AdjacencyNode(
                    record_id=supersedes,
                    record_type="unknown",
                )

    # Pass 2 — derive reverse edges (cited_by, superseded_by).
    for node in list(nodes.values()):
        for cited_id in node.cites:
            if cited_id in nodes:
                if node.record_id not in nodes[cited_id].cited_by:
                    nodes[cited_id].cited_by.append(node.record_id)

        if node.supersedes and node.supersedes in nodes:
            target = nodes[node.supersedes]
            if node.record_id not in target.superseded_by:
                target.superseded_by.append(node.record_id)

    record_count = len(record_ids) - len(skipped) if records_root.exists() else 0  # type: ignore[possibly-undefined]

    return GraphAdjacency(graph=nodes, record_count=record_count)

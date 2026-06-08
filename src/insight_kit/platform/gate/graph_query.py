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

Node identity:
    Every node is keyed by ``dir_id`` — the directory name under records/,
    which equals the content-addressed record_id produced by
    record_id_from_fingerprint() in emit.py.  The ``cites`` and ``supersedes``
    values stored in record.json are also content-addressed record_ids, so edge
    targets match real nodes without phantom stubs.  The discriminated-union
    business id (claim_id / research_id / …) is stored as the optional
    ``business_id`` attribute on AdjacencyNode and is NOT used as the node key.

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

    record_id: content-addressed id (= directory name under records/).
    record_type: 'claim' | 'intervention' | 'research' | 'skill_use'.
    business_id: discriminated-union business id from the record payload
                 (claim_id / research_id / skill_use_id / intervention_id),
                 or None if the record has an unknown type.  Informational
                 only — node identity and all edge matching use record_id.
    cites: list of record_ids this record directly cites (outgoing refs).
    cited_by: list of record_ids that cite this one (reverse edges, derived).
    supersedes: single record_id this record supersedes (or None).
    superseded_by: list of record_ids that supersede this one (derived).
    """

    record_id: str
    record_type: str
    business_id: str | None = None
    cites: list[str] = field(default_factory=list)
    cited_by: list[str] = field(default_factory=list)
    supersedes: str | None = None
    superseded_by: list[str] = field(default_factory=list)


@dataclass
class GraphAdjacency:
    """Adjacency view of cites/supersedes edges for all records in a run.

    graph: dict[str, AdjacencyNode] keyed by content-addressed record_id
           (= directory name under records/).
    record_count: total records successfully scanned.
    """

    graph: dict[str, AdjacencyNode] = field(default_factory=dict)
    record_count: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Maps record_type discriminant to its business-id field name.
_BUSINESS_ID_FIELD: dict[str, str] = {
    "claim": "claim_id",
    "intervention": "intervention_id",
    "research": "research_id",
    "skill_use": "skill_use_id",
}


def _extract_record_meta(
    rec: dict[str, Any],
) -> tuple[str | None, list[str], str | None]:
    """Extract (business_id, cites, supersedes) from a raw record dict.

    business_id is the discriminated-union id (claim_id / research_id / …),
    or None for unknown record types.  It is NOT used as the graph node key —
    node identity is always the content-addressed dir_id.

    Returns (business_id_or_None, cites_list, supersedes_or_None).
    """
    record_type = rec.get("record_type", "")
    id_field = _BUSINESS_ID_FIELD.get(record_type)
    business_id: str | None = rec.get(id_field) if id_field else None

    cites: list[str] = rec.get("cites") or []
    supersedes: str | None = rec.get("supersedes") or None
    return business_id, cites, supersedes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def query_cites(run_dir: Path | None = None) -> GraphAdjacency:
    """Build adjacency view of cites/supersedes edges from the record.json set.

    Scans records/*/record.json following the store.py:258 reindex pattern,
    builds an in-memory adjacency dict on each call.  Corrupt or unreadable
    record.json files are skipped (logged at WARNING), matching reindex
    behaviour.

    Graph nodes are keyed by the content-addressed record_id (= directory name
    under records/).  The ``cites`` and ``supersedes`` values in record.json
    are also content-addressed ids, so edge targets match real nodes without
    phantom stubs.

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
    # Nodes are ALWAYS keyed by dir_id (content-addressed record_id).
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

            record_type = rec.get("record_type", "unknown")
            business_id, cites, supersedes = _extract_record_meta(rec)

            # Node key is always dir_id (content-addressed), never business_id.
            if dir_id not in nodes:
                nodes[dir_id] = AdjacencyNode(
                    record_id=dir_id,
                    record_type=record_type,
                    business_id=business_id,
                )
            else:
                # Node was pre-created as a stub target of an earlier cite edge;
                # fill in the real record_type and business_id now.
                nodes[dir_id].record_type = record_type
                nodes[dir_id].business_id = business_id

            node = nodes[dir_id]
            node.cites = list(cites)
            node.supersedes = supersedes

            # Ensure cited targets exist in graph (as stubs for reverse wiring).
            # cites values are content-addressed ids — they match dir_id keys.
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

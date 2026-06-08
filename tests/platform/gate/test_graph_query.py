"""Tests for gate/graph_query.py — T28.

Covers:
  - Forward cites edges (outgoing refs).
  - Reverse cited_by edges (derived).
  - supersedes / superseded_by chain.
  - Missing / corrupt record.json skipped gracefully (mirrors reindex).
  - Dangling cite edge: node stub created, graph still builds.
  - Empty run_dir returns empty GraphAdjacency.
  - record_type preserved for all discriminated union kinds.
  - record_count reflects successfully scanned records.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.platform.gate.graph_query import (
    AdjacencyNode,
    GraphAdjacency,
    query_cites,
)
from insight_kit.platform.gate.store import write_record

# ---------------------------------------------------------------------------
# Helpers — minimal valid record dicts per discriminated-union kind
# ---------------------------------------------------------------------------


def _research_record(record_id: str, cites: list[str] | None = None) -> dict:
    return {
        "record_type": "research",
        "research_id": record_id,
        "snapshot_ref": "s/r.json",
        "query": "q",
        "source": "s",
        "timestamp": "2026-05-21T10:00:00+00:00",
        "record_fingerprint": "c" * 64,
        "data_fingerprint": "d" * 64,
        **({"cites": cites} if cites is not None else {}),
    }


def _skill_use_record(record_id: str, cites: list[str] | None = None) -> dict:
    return {
        "record_type": "skill_use",
        "skill_use_id": record_id,
        "skill_name": "test_skill",
        "inputs": {},
        "outputs": {},
        "record_fingerprint": "e" * 64,
        "data_fingerprint": "f" * 64,
        **({"cites": cites} if cites is not None else {}),
    }


def _claim_record(
    record_id: str,
    cites: list[str] | None = None,
    supersedes: str | None = None,
) -> dict:
    d: dict = {
        "record_type": "claim",
        "claim_id": record_id,
        "fields": {"revenue": {"value": 1000, "fmt_hint": "$,.0f"}},
        "tier": "draft",
        "record_fingerprint": "a" * 64,
        "data_fingerprint": "b" * 64,
    }
    if cites is not None:
        d["cites"] = cites
    if supersedes is not None:
        d["supersedes"] = supersedes
    return d


def _intervention_record(record_id: str) -> dict:
    return {
        "record_type": "intervention",
        "intervention_id": record_id,
        "label": "test intervention",
        "record_fingerprint": "g" * 64,
        "data_fingerprint": "h" * 64,
    }


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


# ---------------------------------------------------------------------------
# Basic forward edge — cites
# ---------------------------------------------------------------------------


class TestCitesForwardEdge:
    def test_cites_populated_on_citing_record(self, run_dir):
        """CLAIM-1 cites RES-001 and SKU-001 → forward edges recorded."""
        res_id = "RES-001"
        sku_id = "SKU-001"
        claim_id = "CLAIM-1"

        write_record(run_dir, res_id, _research_record(res_id))
        write_record(run_dir, sku_id, _skill_use_record(sku_id))
        write_record(run_dir, claim_id, _claim_record(claim_id, cites=[res_id, sku_id]))

        g = query_cites(run_dir)
        assert set(g.graph[claim_id].cites) == {res_id, sku_id}

    def test_cited_records_have_empty_cites(self, run_dir):
        """Knowledge records that don't cite anything have cites=[]."""
        res_id = "RES-001"
        claim_id = "CLAIM-1"

        write_record(run_dir, res_id, _research_record(res_id))
        write_record(run_dir, claim_id, _claim_record(claim_id, cites=[res_id]))

        g = query_cites(run_dir)
        assert g.graph[res_id].cites == []


# ---------------------------------------------------------------------------
# Reverse edge — cited_by
# ---------------------------------------------------------------------------


class TestCitedByReverseEdge:
    def test_cited_by_populated_on_target(self, run_dir):
        """RES-001 cited by CLAIM-1 → cited_by == [CLAIM-1]."""
        res_id = "RES-001"
        claim_id = "CLAIM-1"

        write_record(run_dir, res_id, _research_record(res_id))
        write_record(run_dir, claim_id, _claim_record(claim_id, cites=[res_id]))

        g = query_cites(run_dir)
        assert g.graph[res_id].cited_by == [claim_id]

    def test_both_knowledge_records_cited_by_claim(self, run_dir):
        """RES-001 and SKU-001 both cited_by CLAIM-1."""
        res_id = "RES-001"
        sku_id = "SKU-001"
        claim_id = "CLAIM-1"

        write_record(run_dir, res_id, _research_record(res_id))
        write_record(run_dir, sku_id, _skill_use_record(sku_id))
        write_record(run_dir, claim_id, _claim_record(claim_id, cites=[res_id, sku_id]))

        g = query_cites(run_dir)
        assert g.graph[res_id].cited_by == [claim_id]
        assert g.graph[sku_id].cited_by == [claim_id]

    def test_no_self_citation(self, run_dir):
        """Isolated record has cited_by == []."""
        res_id = "RES-001"
        write_record(run_dir, res_id, _research_record(res_id))

        g = query_cites(run_dir)
        assert g.graph[res_id].cited_by == []


# ---------------------------------------------------------------------------
# supersedes / superseded_by chain
# ---------------------------------------------------------------------------


class TestSupersessionChain:
    def test_three_link_chain(self, run_dir):
        """CLAIM-1a → CLAIM-1b → CLAIM-1c."""
        a_id = "CLAIM-1a"
        b_id = "CLAIM-1b"
        c_id = "CLAIM-1c"

        write_record(run_dir, a_id, _claim_record(a_id))
        write_record(run_dir, b_id, _claim_record(b_id, supersedes=a_id))
        write_record(run_dir, c_id, _claim_record(c_id, supersedes=b_id))

        g = query_cites(run_dir)

        # b supersedes a
        assert g.graph[b_id].supersedes == a_id
        # c supersedes b
        assert g.graph[c_id].supersedes == b_id

        # a is superseded by b only
        assert g.graph[a_id].superseded_by == [b_id]
        # b is superseded by c only
        assert g.graph[b_id].superseded_by == [c_id]
        # c is not superseded by anything
        assert g.graph[c_id].superseded_by == []

        # a has no supersedes
        assert g.graph[a_id].supersedes is None

    def test_no_supersession(self, run_dir):
        """Record without supersedes has supersedes=None and superseded_by=[]."""
        claim_id = "CLAIM-1"
        write_record(run_dir, claim_id, _claim_record(claim_id))

        g = query_cites(run_dir)
        assert g.graph[claim_id].supersedes is None
        assert g.graph[claim_id].superseded_by == []


# ---------------------------------------------------------------------------
# record_count
# ---------------------------------------------------------------------------


class TestRecordCount:
    def test_record_count_matches_scanned(self, run_dir):
        write_record(run_dir, "RES-001", _research_record("RES-001"))
        write_record(run_dir, "SKU-001", _skill_use_record("SKU-001"))
        write_record(run_dir, "CLAIM-1", _claim_record("CLAIM-1", cites=["RES-001", "SKU-001"]))

        g = query_cites(run_dir)
        assert g.record_count == 3

    def test_empty_run_dir_returns_zero(self, run_dir):
        g = query_cites(run_dir)
        assert g.record_count == 0
        assert g.graph == {}


# ---------------------------------------------------------------------------
# Corrupt / missing record.json — graceful skip
# ---------------------------------------------------------------------------


class TestCorruptRecord:
    def test_corrupt_record_skipped(self, run_dir):
        """Emit 3 records, corrupt one — graph still builds for the other 2."""
        write_record(run_dir, "RES-001", _research_record("RES-001"))
        write_record(run_dir, "SKU-001", _skill_use_record("SKU-001"))
        write_record(run_dir, "CLAIM-1", _claim_record("CLAIM-1", cites=["RES-001"]))

        # Corrupt CLAIM-1's record.json
        corrupt_path = run_dir / "records" / "CLAIM-1" / "record.json"
        corrupt_path.write_text("not valid json", encoding="utf-8")

        g = query_cites(run_dir)
        assert g.record_count == 2  # only RES-001 and SKU-001 counted
        assert "RES-001" in g.graph
        assert "SKU-001" in g.graph
        # CLAIM-1 might appear as a stub if referenced, but not as a full node
        # since it was skipped — either way no error raised
        assert g.graph.get("CLAIM-1") is None or g.graph["CLAIM-1"].record_type == "unknown"

    def test_deleted_record_json_skipped(self, run_dir):
        """Manually deleted record.json — scan skips it cleanly."""
        write_record(run_dir, "RES-001", _research_record("RES-001"))
        write_record(run_dir, "SKU-001", _skill_use_record("SKU-001"))

        # Delete SKU-001 after write
        (run_dir / "records" / "SKU-001" / "record.json").unlink()

        g = query_cites(run_dir)
        # Deleted file: glob won't return it, so both count and graph reflect only RES-001
        assert "RES-001" in g.graph
        assert g.record_count == 1


# ---------------------------------------------------------------------------
# Dangling cite — non-existent target referenced
# ---------------------------------------------------------------------------


class TestDanglingCite:
    def test_dangling_cite_builds_stub(self, run_dir):
        """CLAIM-1 cites a non-existent record → stub node created, no error."""
        claim_id = "CLAIM-1"
        dangling_id = "NONEXISTENT-999"

        write_record(run_dir, claim_id, _claim_record(claim_id, cites=[dangling_id]))

        g = query_cites(run_dir)
        # Graph still builds
        assert claim_id in g.graph
        assert g.graph[claim_id].cites == [dangling_id]
        # Stub node created for dangling target
        assert dangling_id in g.graph
        assert g.graph[dangling_id].record_type == "unknown"
        # Reverse edge wired
        assert claim_id in g.graph[dangling_id].cited_by

    def test_manually_added_dangling_cite_via_raw_edit(self, run_dir, tmp_path):
        """Edit record.json directly to add a non-existent cite — graph still builds."""
        res_id = "RES-001"
        claim_id = "CLAIM-1"
        ghost_id = "GHOST-001"

        write_record(run_dir, res_id, _research_record(res_id))
        write_record(run_dir, claim_id, _claim_record(claim_id, cites=[res_id]))

        # Bypass immutability: overwrite with raw JSON adding a ghost cite
        rec_path = run_dir / "records" / claim_id / "record.json"
        raw = json.loads(rec_path.read_text(encoding="utf-8"))
        raw["cites"] = [res_id, ghost_id]
        rec_path.write_text(json.dumps(raw), encoding="utf-8")

        g = query_cites(run_dir)
        assert set(g.graph[claim_id].cites) == {res_id, ghost_id}
        assert ghost_id in g.graph
        assert claim_id in g.graph[ghost_id].cited_by


# ---------------------------------------------------------------------------
# Record type preservation
# ---------------------------------------------------------------------------


class TestRecordTypePreserved:
    def test_all_four_record_types(self, run_dir):
        """All four discriminated union kinds appear with correct record_type."""
        write_record(run_dir, "CLAIM-1", _claim_record("CLAIM-1"))
        write_record(run_dir, "INT-001", _intervention_record("INT-001"))
        write_record(run_dir, "RES-001", _research_record("RES-001"))
        write_record(run_dir, "SKU-001", _skill_use_record("SKU-001"))

        g = query_cites(run_dir)
        assert g.graph["CLAIM-1"].record_type == "claim"
        assert g.graph["INT-001"].record_type == "intervention"
        assert g.graph["RES-001"].record_type == "research"
        assert g.graph["SKU-001"].record_type == "skill_use"

    def test_record_count_all_four_kinds(self, run_dir):
        write_record(run_dir, "CLAIM-1", _claim_record("CLAIM-1"))
        write_record(run_dir, "INT-001", _intervention_record("INT-001"))
        write_record(run_dir, "RES-001", _research_record("RES-001"))
        write_record(run_dir, "SKU-001", _skill_use_record("SKU-001"))

        g = query_cites(run_dir)
        assert g.record_count == 4


# ---------------------------------------------------------------------------
# Public API export from __init__
# ---------------------------------------------------------------------------


class TestPublicExport:
    def test_query_cites_importable_from_gate(self):
        from insight_kit.platform.gate import query_cites as qc  # noqa: F401
        assert callable(qc)

    def test_graph_adjacency_importable_from_gate(self):
        from insight_kit.platform.gate import GraphAdjacency as GA  # noqa: F401
        assert GA is not None

    def test_adjacency_node_importable_from_gate(self):
        from insight_kit.platform.gate import AdjacencyNode as AN  # noqa: F401
        assert AN is not None

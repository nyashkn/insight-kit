"""T31 — Available-endpoints index (endpoint_index.json) persisted in research record bundle.

Verifies:
  - endpoint_index_path returns correct sibling path.
  - write_endpoint_index persists endpoint_index.json; raises FileExistsError on second write (V3).
  - read_endpoint_index round-trips the written dict; returns None when absent.
  - Relevance ranking order (insertion order) is preserved across write/read.
  - endpoint_index is optional: research records without it return None gracefully.
  - Empty dict is accepted (index is optional metadata, not a required payload).
  - read_endpoint_index returns None for a record_id with no endpoint_index.json
    (e.g. a claim record directory, or a directory that never received the file).
  - reindex does not corrupt or remove endpoint_index.json sibling files.
  - A claim that cites a research record can retrieve the research endpoint_index.
  - Public __init__ exports are present and callable.

Cites: T31, V3, V7, V20, I.cites.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.platform.gate.emit import ik_claim_emit, ik_research_emit
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import (
    endpoint_index_path,
    read_endpoint_index,
    reindex,
    write_endpoint_index,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


TS = "2026-06-09T10:00:00+00:00"
SNAPSHOT = {"docs": ["endpoint-A", "endpoint-B"], "n": 2}

ENDPOINT_INDEX = {
    "available_endpoints": [
        {"endpoint": "/v1/completions", "relevance": "high", "source": "openai-docs"},
        {"endpoint": "/v1/chat/completions", "relevance": "high", "source": "openai-docs"},
        {"endpoint": "/v1/models", "relevance": "medium", "source": "openai-docs"},
        {"endpoint": "/v1/embeddings", "relevance": "low", "source": "openai-docs"},
    ]
}


def _emit_research(run_dir, state, *, research_id="RES-T31-001", snapshot=None, **kw):
    return ik_research_emit(
        research_id,
        "https://api.example.com/docs",
        "what endpoints are available",
        "perplexity",
        snapshot=snapshot if snapshot is not None else SNAPSHOT,
        timestamp=TS,
        run_state=state,
        run_dir=run_dir,
        **kw,
    )


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------


class TestEndpointIndexPath:
    def test_path_is_sibling_to_record_json(self, run_dir):
        path = endpoint_index_path(run_dir, "rec-abc123")
        assert path == run_dir / "records" / "rec-abc123" / "endpoint_index.json"

    def test_path_is_sibling_to_snapshot_json(self, run_dir):
        from insight_kit.platform.gate.store import snapshot_path

        snap = snapshot_path(run_dir, "rec-xyz")
        idx = endpoint_index_path(run_dir, "rec-xyz")
        assert snap.parent == idx.parent


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestEndpointIndexPersistence:
    def test_write_creates_file(self, run_dir):
        run_dir.mkdir(parents=True, exist_ok=True)
        record_dir = run_dir / "records" / "rec-001"
        record_dir.mkdir(parents=True)
        path = write_endpoint_index(run_dir, "rec-001", ENDPOINT_INDEX)
        assert path.exists()
        assert path == endpoint_index_path(run_dir, "rec-001")

    def test_write_content_is_valid_json(self, run_dir):
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "records" / "rec-002").mkdir(parents=True)
        path = write_endpoint_index(run_dir, "rec-002", ENDPOINT_INDEX)
        parsed = json.loads(path.read_text(encoding="utf-8"))
        assert parsed == ENDPOINT_INDEX

    def test_write_creates_parent_dirs(self, run_dir):
        # Parent directory does not pre-exist
        path = write_endpoint_index(run_dir, "rec-003", ENDPOINT_INDEX)
        assert path.exists()

    def test_write_immutability_raises_file_exists_error(self, run_dir):
        """V3 — second write to same record_id raises FileExistsError."""
        write_endpoint_index(run_dir, "rec-004", ENDPOINT_INDEX)
        with pytest.raises(FileExistsError):
            write_endpoint_index(run_dir, "rec-004", {"available_endpoints": []})

    def test_write_returns_path(self, run_dir):
        returned = write_endpoint_index(run_dir, "rec-005", ENDPOINT_INDEX)
        assert isinstance(returned, Path)
        assert returned == endpoint_index_path(run_dir, "rec-005")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestEndpointIndexRoundTrip:
    def test_read_returns_written_dict(self, run_dir):
        write_endpoint_index(run_dir, "rt-001", ENDPOINT_INDEX)
        result = read_endpoint_index(run_dir, "rt-001")
        assert result == ENDPOINT_INDEX

    def test_read_preserves_all_fields(self, run_dir):
        write_endpoint_index(run_dir, "rt-002", ENDPOINT_INDEX)
        result = read_endpoint_index(run_dir, "rt-002")
        assert "available_endpoints" in result
        first = result["available_endpoints"][0]
        assert first["endpoint"] == "/v1/completions"
        assert first["relevance"] == "high"
        assert first["source"] == "openai-docs"

    def test_read_returns_none_when_absent(self, run_dir):
        result = read_endpoint_index(run_dir, "nonexistent-record")
        assert result is None

    def test_read_empty_dict_round_trips(self, run_dir):
        """Empty dict is valid (optional metadata); round-trips correctly."""
        write_endpoint_index(run_dir, "rt-003", {})
        result = read_endpoint_index(run_dir, "rt-003")
        assert result == {}

    def test_read_arbitrary_extra_fields_preserved(self, run_dir):
        """Extra fields outside available_endpoints are preserved (forward-compat)."""
        index_with_meta = {
            "available_endpoints": [
                {"endpoint": "/v1/chat", "relevance": "high", "source": "docs"},
            ],
            "distilled_at": "2026-06-09T10:00:00Z",
            "distilled_by": "researcher-agent",
        }
        write_endpoint_index(run_dir, "rt-004", index_with_meta)
        result = read_endpoint_index(run_dir, "rt-004")
        assert result["distilled_at"] == "2026-06-09T10:00:00Z"
        assert result["distilled_by"] == "researcher-agent"


# ---------------------------------------------------------------------------
# Relevance ranking preservation
# ---------------------------------------------------------------------------


class TestEndpointIndexRelevanceRanking:
    def test_high_medium_low_order_preserved(self, run_dir):
        """Read order matches write order — insertion-order dict preservation."""
        write_endpoint_index(run_dir, "rank-001", ENDPOINT_INDEX)
        result = read_endpoint_index(run_dir, "rank-001")
        endpoints = result["available_endpoints"]
        assert endpoints[0]["relevance"] == "high"
        assert endpoints[1]["relevance"] == "high"
        assert endpoints[2]["relevance"] == "medium"
        assert endpoints[3]["relevance"] == "low"

    def test_custom_order_preserved(self, run_dir):
        """Caller-defined order (e.g. low first) is not sorted by the layer."""
        index = {
            "available_endpoints": [
                {"endpoint": "/v1/z", "relevance": "low", "source": "docs"},
                {"endpoint": "/v1/a", "relevance": "high", "source": "docs"},
            ]
        }
        write_endpoint_index(run_dir, "rank-002", index)
        result = read_endpoint_index(run_dir, "rank-002")
        assert result["available_endpoints"][0]["endpoint"] == "/v1/z"
        assert result["available_endpoints"][1]["endpoint"] == "/v1/a"

    def test_endpoint_names_preserved_exactly(self, run_dir):
        write_endpoint_index(run_dir, "rank-003", ENDPOINT_INDEX)
        result = read_endpoint_index(run_dir, "rank-003")
        names = [e["endpoint"] for e in result["available_endpoints"]]
        assert names == [
            "/v1/completions",
            "/v1/chat/completions",
            "/v1/models",
            "/v1/embeddings",
        ]


# ---------------------------------------------------------------------------
# Integration with emit
# ---------------------------------------------------------------------------


class TestEndpointIndexIntegration:
    def test_write_after_research_emit(self, run_dir, state):
        """endpoint_index written alongside snapshot.json after emit."""
        ref = _emit_research(run_dir, state)
        write_endpoint_index(run_dir, ref.record_id, ENDPOINT_INDEX)
        result = read_endpoint_index(run_dir, ref.record_id)
        assert result == ENDPOINT_INDEX

    def test_snapshot_and_endpoint_index_coexist(self, run_dir, state):
        """snapshot.json and endpoint_index.json are independent sibling files."""
        from insight_kit.platform.gate.store import snapshot_path

        ref = _emit_research(run_dir, state)
        write_endpoint_index(run_dir, ref.record_id, ENDPOINT_INDEX)
        assert snapshot_path(run_dir, ref.record_id).exists()
        assert endpoint_index_path(run_dir, ref.record_id).exists()

    def test_claim_citing_research_can_read_endpoint_index(self, run_dir, state):
        """A claim can call read_endpoint_index on its cited research record."""
        res_ref = _emit_research(run_dir, state)
        write_endpoint_index(run_dir, res_ref.record_id, ENDPOINT_INDEX)

        claim_ref = ik_claim_emit(
            "TEST-D-001",
            {"x": 1},
            cites=[res_ref.record_id],
            run_state=state,
            run_dir=run_dir,
        )

        # Claim consumer resolves knowledge via cites -> read_endpoint_index
        result = read_endpoint_index(run_dir, res_ref.record_id)
        assert result is not None
        assert len(result["available_endpoints"]) > 0
        _ = claim_ref  # used

    def test_read_on_claim_record_returns_none(self, run_dir, state):
        """A claim record directory never has endpoint_index.json — returns None."""
        claim_ref = ik_claim_emit(
            "TEST-D-002", {"y": 2}, run_state=state, run_dir=run_dir
        )
        result = read_endpoint_index(run_dir, claim_ref.record_id)
        assert result is None

    def test_reindex_does_not_corrupt_endpoint_index(self, run_dir, state):
        """reindex (V7) scans record.json files; endpoint_index.json is unaffected."""
        ref1 = _emit_research(run_dir, state, research_id="RES-T31-A")
        ref2 = _emit_research(run_dir, state, research_id="RES-T31-B", snapshot={"docs": ["C"]})

        write_endpoint_index(run_dir, ref1.record_id, ENDPOINT_INDEX)
        # ref2 intentionally has no endpoint_index

        count, skipped = reindex(run_dir)
        assert count >= 2
        assert not skipped

        # endpoint_index for ref1 must survive intact
        result = read_endpoint_index(run_dir, ref1.record_id)
        assert result == ENDPOINT_INDEX

        # endpoint_index absent for ref2 still returns None
        assert read_endpoint_index(run_dir, ref2.record_id) is None

    def test_multiple_research_records_independent_indices(self, run_dir, state):
        """Each research record carries its own endpoint_index."""
        ref1 = _emit_research(run_dir, state, research_id="RES-T31-C")
        ref2 = _emit_research(run_dir, state, research_id="RES-T31-D", snapshot={"docs": ["D"]})

        index1 = {"available_endpoints": [{"endpoint": "/a", "relevance": "high", "source": "s1"}]}
        index2 = {"available_endpoints": [{"endpoint": "/b", "relevance": "low", "source": "s2"}]}

        write_endpoint_index(run_dir, ref1.record_id, index1)
        write_endpoint_index(run_dir, ref2.record_id, index2)

        assert read_endpoint_index(run_dir, ref1.record_id) == index1
        assert read_endpoint_index(run_dir, ref2.record_id) == index2


# ---------------------------------------------------------------------------
# Public API exports
# ---------------------------------------------------------------------------


class TestPublicAPIExports:
    def test_endpoint_index_path_exported(self):
        from insight_kit.platform.gate import endpoint_index_path as _ep
        assert callable(_ep)

    def test_write_endpoint_index_exported(self):
        from insight_kit.platform.gate import write_endpoint_index as _w
        assert callable(_w)

    def test_read_endpoint_index_exported(self):
        from insight_kit.platform.gate import read_endpoint_index as _r
        assert callable(_r)

    def test_all_list_contains_exports(self):
        import insight_kit.platform.gate as gate
        assert "endpoint_index_path" in gate.__all__
        assert "write_endpoint_index" in gate.__all__
        assert "read_endpoint_index" in gate.__all__

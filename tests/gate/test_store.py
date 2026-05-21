"""Tests for gate/store.py — T4.

Covers:
  V1  — only emit writes records.jsonl / record.json (tested structurally here).
  V3  — overwrite of record.json refused (FileExistsError).
  V7  — records.jsonl regenerable via reindex().
  Plus: claims.jsonl written for claim records only,
        events append, resolve_run_dir fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from insight_kit.gate.store import (
    append_claims_row,
    append_event,
    append_index_row,
    claims_index_path,
    index_path,
    read_record,
    reindex,
    resolve_run_dir,
    write_record,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


def _claim_dict(claim_id: str = "TEST-D-001", tier: str = "draft") -> dict:
    return {
        "record_type": "claim",
        "claim_id": claim_id,
        "fields": {"revenue": {"value": 1000, "fmt_hint": "$,.0f"}},
        "tier": tier,
        "record_fingerprint": "a" * 64,
        "data_fingerprint": "b" * 64,
    }


def _research_dict(research_id: str = "RES-001") -> dict:
    return {
        "record_type": "research",
        "research_id": research_id,
        "snapshot_ref": "s/r.json",
        "query": "q",
        "source": "s",
        "timestamp": "2026-05-21T10:00:00+00:00",
        "record_fingerprint": "c" * 64,
        "data_fingerprint": "d" * 64,
    }


# ---------------------------------------------------------------------------
# write_record / read_record
# ---------------------------------------------------------------------------

class TestWriteRecord:
    def test_writes_record_json(self, run_dir):
        rd = _claim_dict()
        path = write_record(run_dir, "rec001", rd)
        assert path.exists()
        assert path.name == "record.json"

    def test_written_content_parseable(self, run_dir):
        rd = _claim_dict()
        write_record(run_dir, "rec001", rd)
        loaded = read_record(run_dir, "rec001")
        assert loaded["claim_id"] == "TEST-D-001"

    def test_overwrite_refused(self, run_dir):
        """V3 — record.json immutable post-emit."""
        rd = _claim_dict()
        write_record(run_dir, "rec001", rd)
        with pytest.raises(FileExistsError):
            write_record(run_dir, "rec001", rd)

    def test_overwrite_refused_with_modified_content(self, run_dir):
        """V3 — even if content differs, overwrite is refused."""
        rd1 = _claim_dict("TEST-D-001")
        rd2 = _claim_dict("TEST-D-002")
        write_record(run_dir, "rec001", rd1)
        with pytest.raises(FileExistsError):
            write_record(run_dir, "rec001", rd2)

    def test_creates_parent_dirs(self, tmp_path):
        rd = _claim_dict()
        nested = tmp_path / "deep" / "nested" / "run"
        write_record(nested, "rec001", rd)
        assert (nested / "records" / "rec001" / "record.json").exists()

    def test_different_ids_coexist(self, run_dir):
        write_record(run_dir, "rec001", _claim_dict("TEST-D-001"))
        write_record(run_dir, "rec002", _claim_dict("TEST-D-002"))
        assert (run_dir / "records" / "rec001" / "record.json").exists()
        assert (run_dir / "records" / "rec002" / "record.json").exists()


# ---------------------------------------------------------------------------
# append_index_row / records.jsonl
# ---------------------------------------------------------------------------

class TestAppendIndexRow:
    def test_appends_row_with_record_type(self, run_dir):
        rd = _claim_dict()
        append_index_row(run_dir, rd, "rec001")
        idx = index_path(run_dir)
        row = json.loads(idx.read_text().strip())
        assert row["record_type"] == "claim"
        assert row["record_id"] == "rec001"

    def test_multiple_rows_appended(self, run_dir):
        append_index_row(run_dir, _claim_dict("TEST-D-001"), "rec001")
        append_index_row(run_dir, _research_dict("RES-001"), "rec002")
        rows = [json.loads(l) for l in index_path(run_dir).read_text().splitlines() if l.strip()]
        assert len(rows) == 2
        assert {r["record_type"] for r in rows} == {"claim", "research"}

    def test_row_carries_fingerprints(self, run_dir):
        rd = _claim_dict()
        append_index_row(run_dir, rd, "rec001")
        row = json.loads(index_path(run_dir).read_text().strip())
        assert row["record_fingerprint"] == "a" * 64
        assert row["data_fingerprint"] == "b" * 64


# ---------------------------------------------------------------------------
# claims.jsonl — claim-only projection view
# ---------------------------------------------------------------------------

class TestAppendClaimsRow:
    def test_claim_appends_to_claims_jsonl(self, run_dir):
        rd = _claim_dict()
        append_claims_row(run_dir, rd, "rec001")
        cidx = claims_index_path(run_dir)
        assert cidx.exists()
        row = json.loads(cidx.read_text().strip())
        assert row["record_type"] == "claim"
        assert row["claim_id"] == "TEST-D-001"

    def test_non_claim_does_not_append(self, run_dir):
        rd = _research_dict()
        append_claims_row(run_dir, rd, "rec001")
        cidx = claims_index_path(run_dir)
        assert not cidx.exists()


# ---------------------------------------------------------------------------
# events/*.jsonl
# ---------------------------------------------------------------------------

class TestAppendEvent:
    def test_appends_event(self, run_dir):
        # write record first (event dir needs record to exist — though store doesn't enforce)
        write_record(run_dir, "rec001", _claim_dict())
        ev_path = append_event(run_dir, "rec001", "critique", {"severity": "high"})
        assert ev_path.exists()
        content = json.loads(ev_path.read_text().strip())
        assert content["severity"] == "high"

    def test_multiple_events_in_same_file(self, run_dir):
        write_record(run_dir, "rec001", _claim_dict())
        append_event(run_dir, "rec001", "critique", {"round": 1})
        append_event(run_dir, "rec001", "critique", {"round": 2})
        ev_path = run_dir / "records" / "rec001" / "events" / "critique.jsonl"
        rows = [json.loads(l) for l in ev_path.read_text().splitlines() if l.strip()]
        assert len(rows) == 2
        assert rows[0]["round"] == 1
        assert rows[1]["round"] == 2

    def test_different_event_names_separate_files(self, run_dir):
        write_record(run_dir, "rec001", _claim_dict())
        append_event(run_dir, "rec001", "critique", {"x": 1})
        append_event(run_dir, "rec001", "staleness", {"stale": True})
        ev_dir = run_dir / "records" / "rec001" / "events"
        files = {p.name for p in ev_dir.iterdir()}
        assert "critique.jsonl" in files
        assert "staleness.jsonl" in files


# ---------------------------------------------------------------------------
# reindex — V7
# ---------------------------------------------------------------------------

class TestReindex:
    def test_reindex_rebuilds_from_records(self, run_dir):
        write_record(run_dir, "rec001", _claim_dict("TEST-D-001"))
        write_record(run_dir, "rec002", _research_dict("RES-001"))

        # Delete index files
        index_path(run_dir).unlink(missing_ok=True)
        claims_index_path(run_dir).unlink(missing_ok=True)

        count = reindex(run_dir)
        assert count == 2

        rows = [json.loads(l) for l in index_path(run_dir).read_text().splitlines() if l.strip()]
        assert len(rows) == 2
        assert {r["record_type"] for r in rows} == {"claim", "research"}

    def test_reindex_claims_jsonl_only_has_claims(self, run_dir):
        write_record(run_dir, "rec001", _claim_dict("TEST-D-001"))
        write_record(run_dir, "rec002", _research_dict("RES-001"))
        reindex(run_dir)
        claim_rows = [
            json.loads(l)
            for l in claims_index_path(run_dir).read_text().splitlines()
            if l.strip()
        ]
        assert len(claim_rows) == 1
        assert claim_rows[0]["claim_id"] == "TEST-D-001"

    def test_reindex_sorted_deterministic(self, run_dir):
        write_record(run_dir, "zzz", _claim_dict("TEST-D-003"))
        write_record(run_dir, "aaa", _claim_dict("TEST-D-001"))
        write_record(run_dir, "mmm", _claim_dict("TEST-D-002"))
        reindex(run_dir)
        rows = [json.loads(l) for l in index_path(run_dir).read_text().splitlines() if l.strip()]
        ids = [r["record_id"] for r in rows]
        assert ids == sorted(ids)

    def test_reindex_empty_run_dir(self, tmp_path):
        empty = tmp_path / "empty_run"
        count = reindex(empty)
        assert count == 0
        assert index_path(empty).exists()

    def test_reindex_overwrites_stale_index(self, run_dir):
        write_record(run_dir, "rec001", _claim_dict())
        append_index_row(run_dir, _claim_dict(), "rec001")
        append_index_row(run_dir, _claim_dict(), "rec001")  # stale duplicate
        rows_before = [l for l in index_path(run_dir).read_text().splitlines() if l.strip()]
        assert len(rows_before) == 2  # stale

        reindex(run_dir)
        rows_after = [l for l in index_path(run_dir).read_text().splitlines() if l.strip()]
        assert len(rows_after) == 1  # clean

    def test_reindex_returns_count(self, run_dir):
        for i in range(3):
            write_record(run_dir, f"rec00{i}", _claim_dict(f"TEST-D-00{i}"))
        count = reindex(run_dir)
        assert count == 3


# ---------------------------------------------------------------------------
# resolve_run_dir
# ---------------------------------------------------------------------------

class TestResolveRunDir:
    def test_explicit_run_dir(self, tmp_path):
        resolved = resolve_run_dir(tmp_path)
        assert resolved == tmp_path.resolve()

    def test_env_var_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INSIGHT_KIT_RUN_DIR", str(tmp_path))
        resolved = resolve_run_dir()
        assert resolved == tmp_path.resolve()

    def test_no_run_dir_no_env_raises(self, monkeypatch):
        monkeypatch.delenv("INSIGHT_KIT_RUN_DIR", raising=False)
        with pytest.raises(ValueError, match="run_dir is required"):
            resolve_run_dir()

    def test_explicit_overrides_env(self, tmp_path, monkeypatch):
        env_path = tmp_path / "env_dir"
        explicit_path = tmp_path / "explicit_dir"
        monkeypatch.setenv("INSIGHT_KIT_RUN_DIR", str(env_path))
        resolved = resolve_run_dir(explicit_path)
        assert resolved == explicit_path.resolve()

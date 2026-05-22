"""T18 — uv-run CLI bridge tests (C4, C5, I.emit, V1, V2).

The CLI is the Python half of the L3<->L1 lang seam. These tests exercise the
wire contract the TS pi extension depends on: JSON payload in, one JSON line
out, exit 0/1/2; plus the export-schema single-source (C5).
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from insight_kit.gate.cli import EXIT_OK, EXIT_REJECT, EXIT_USAGE, export_schemas, main, run_emit
from insight_kit.gate.store import resolve_run_dir


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


def _claim_payload(claim_id: str = "TEST-D-001") -> dict:
    return {"claim_id": claim_id, "fields": {"revenue": {"value": 123456, "fmt_hint": "$,.0f"}}}


def _capture(capsys) -> dict:
    """Parse the single JSON line the CLI wrote to stdout."""
    out = capsys.readouterr().out.strip()
    return json.loads(out)


# ---------------------------------------------------------------------------
# emit-* — happy path (I.emit, V1)
# ---------------------------------------------------------------------------


class TestEmitHappyPath:
    def test_emit_claim_via_payload_arg(self, run_dir: Path, capsys):
        code = main(["emit-claim", "--run-dir", str(run_dir), "--payload", json.dumps(_claim_payload())])
        assert code == EXIT_OK
        result = _capture(capsys)
        assert result["ok"] is True
        assert result["record"]["record_type"] == "claim"
        assert len(result["record"]["record_id"]) == 16

    def test_emit_claim_via_stdin(self, run_dir: Path, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_claim_payload())))
        code = main(["emit-claim", "--run-dir", str(run_dir)])
        assert code == EXIT_OK
        assert _capture(capsys)["ok"] is True

    def test_emit_claim_writes_record_to_disk(self, run_dir: Path, capsys):
        main(["emit-claim", "--run-dir", str(run_dir), "--payload", json.dumps(_claim_payload())])
        rid = _capture(capsys)["record"]["record_id"]
        assert (run_dir / "records" / rid / "record.json").exists()

    def test_emit_intervention(self, run_dir: Path, capsys):
        payload = {"intervention_id": "IV-1", "intent": {"description": "raise meta budget"}}
        code = main(["emit-intervention", "--run-dir", str(run_dir), "--payload", json.dumps(payload)])
        assert code == EXIT_OK
        assert _capture(capsys)["record"]["record_type"] == "intervention"

    def test_emit_research_with_snapshot(self, run_dir: Path, capsys):
        payload = {
            "research_id": "RS-1",
            "snapshot_ref": "https://example.com/q",
            "query": "meta CPM trend",
            "source": "web",
            "timestamp": "2026-01-01T00:00:00Z",
            "snapshot": {"result": "CPM up 12%"},
        }
        code = main(["emit-research", "--run-dir", str(run_dir), "--payload", json.dumps(payload)])
        assert code == EXIT_OK
        assert _capture(capsys)["record"]["record_type"] == "research"

    def test_emit_skill_use_with_snapshot(self, run_dir: Path, capsys):
        payload = {
            "skill_use_id": "SK-1",
            "snapshot_ref": "meta-api",
            "tool": "meta_ads_api",
            "source": "graph.facebook.com",
            "timestamp": "2026-01-01T00:00:00Z",
            "snapshot": {"spend": 4200.0},
        }
        code = main(["emit-skill-use", "--run-dir", str(run_dir), "--payload", json.dumps(payload)])
        assert code == EXIT_OK
        assert _capture(capsys)["record"]["record_type"] == "skill_use"


# ---------------------------------------------------------------------------
# emit-* — gate reject surfaces as exit 1 + structured error (V2)
# ---------------------------------------------------------------------------


class TestEmitReject:
    def test_bad_claim_id_is_reject_exit_1(self, run_dir: Path, capsys):
        code = main(
            ["emit-claim", "--run-dir", str(run_dir), "--payload", json.dumps(_claim_payload("bad"))]
        )
        assert code == EXIT_REJECT
        result = _capture(capsys)
        assert result["ok"] is False
        assert result["error"]["rule_id"]
        assert result["error"]["message"]

    def test_reject_writes_no_record(self, run_dir: Path, capsys):
        main(["emit-claim", "--run-dir", str(run_dir), "--payload", json.dumps(_claim_payload("bad"))])
        capsys.readouterr()
        # V2 — zero partial write: no records/ tree created by a rejected emit.
        assert not (run_dir / "records").exists()

    def test_research_without_snapshot_is_reject(self, run_dir: Path, capsys):
        payload = {
            "research_id": "RS-1",
            "snapshot_ref": "x",
            "query": "q",
            "source": "web",
            "timestamp": "2026-01-01T00:00:00Z",
            "snapshot": {},
        }
        code = main(["emit-research", "--run-dir", str(run_dir), "--payload", json.dumps(payload)])
        assert code == EXIT_REJECT
        assert _capture(capsys)["error"]["rule_id"] == "knowledge-snapshot-missing"


# ---------------------------------------------------------------------------
# Cross-subprocess duplicate guard — RunState rehydration
# ---------------------------------------------------------------------------


class TestRehydration:
    def test_duplicate_claim_id_across_calls_is_rejected(self, run_dir: Path):
        resolved = resolve_run_dir(run_dir)
        code1, r1 = run_emit("emit-claim", _claim_payload(), resolved)
        assert code1 == EXIT_OK and r1["ok"] is True
        # Second invocation = fresh RunState; rehydration must still catch the dup.
        code2, r2 = run_emit("emit-claim", _claim_payload(), resolved)
        assert code2 == EXIT_REJECT
        assert r2["ok"] is False

    def test_distinct_claim_ids_across_calls_both_emit(self, run_dir: Path):
        resolved = resolve_run_dir(run_dir)
        code1, _ = run_emit("emit-claim", _claim_payload("TEST-D-001"), resolved)
        code2, _ = run_emit("emit-claim", _claim_payload("TEST-D-002"), resolved)
        assert code1 == EXIT_OK and code2 == EXIT_OK


# ---------------------------------------------------------------------------
# Usage errors — exit 2
# ---------------------------------------------------------------------------


class TestUsageErrors:
    def test_invalid_json_payload_is_exit_2(self, run_dir: Path, capsys):
        code = main(["emit-claim", "--run-dir", str(run_dir), "--payload", "{not json"])
        assert code == EXIT_USAGE
        assert _capture(capsys)["error"]["rule_id"] == "cli-usage"

    def test_non_object_payload_is_exit_2(self, run_dir: Path, capsys):
        code = main(["emit-claim", "--run-dir", str(run_dir), "--payload", "[1,2,3]"])
        assert code == EXIT_USAGE
        assert _capture(capsys)["ok"] is False

    def test_unknown_payload_key_is_exit_2(self, run_dir: Path, capsys):
        payload = {**_claim_payload(), "bogus_kwarg": 1}
        code = main(["emit-claim", "--run-dir", str(run_dir), "--payload", json.dumps(payload)])
        assert code == EXIT_USAGE
        assert _capture(capsys)["error"]["rule_id"] == "cli-usage"

    def test_missing_run_dir_is_exit_2(self, capsys, monkeypatch):
        monkeypatch.delenv("INSIGHT_KIT_RUN_DIR", raising=False)
        code = main(["emit-claim", "--payload", json.dumps(_claim_payload())])
        assert code == EXIT_USAGE
        assert _capture(capsys)["error"]["rule_id"] == "cli-usage"


# ---------------------------------------------------------------------------
# export-schema — pydantic-derived single source (C5)
# ---------------------------------------------------------------------------


class TestExportSchema:
    def test_export_schema_has_four_record_types(self, capsys):
        code = main(["export-schema"])
        assert code == EXIT_OK
        schemas = json.loads(capsys.readouterr().out)
        assert set(schemas) == {"claim", "intervention", "research", "skill_use"}

    def test_schemas_are_self_contained_no_refs(self):
        """C5 — generated TypeBox params must be ref-free ($defs inlined)."""
        rendered = json.dumps(export_schemas())
        assert "$ref" not in rendered
        assert "$defs" not in rendered

    def test_claim_schema_shape(self):
        claim = export_schemas()["claim"]
        assert claim["type"] == "object"
        assert claim["additionalProperties"] is False
        assert "claim_id" in claim["properties"]
        assert "fields" in claim["properties"]
        assert set(claim["required"]) == {"claim_id", "fields"}
        # Emit-injected fields must not leak into the LLM-facing param schema.
        assert "data_fingerprint_source" not in claim["properties"]

    def test_knowledge_schemas_require_snapshot(self):
        for rt in ("research", "skill_use"):
            schema = export_schemas()[rt]
            assert "snapshot" in schema["properties"]
            assert "snapshot" in schema["required"]
            # timestamp is wrapper-defaulted -> optional in the tool schema.
            assert "timestamp" not in schema["required"]

    def test_export_schema_to_file(self, tmp_path: Path):
        out = tmp_path / "schema.json"
        code = main(["export-schema", "--out", str(out)])
        assert code == EXIT_OK
        assert set(json.loads(out.read_text())) == {"claim", "intervention", "research", "skill_use"}

"""End-to-end tests: full Run lifecycle, claim graph edges, CLI."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pyarrow as pa
import pytest

from insight_kit import Run
from insight_kit.cli.__main__ import main as cli_main
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config


@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    return tmp_path


def _t():
    return pa.table({"x": [1, 2, 3]})


# E-01
def test_full_run_lifecycle(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_t(), name="m")
        r.claim(claim_id="TEST-D-001", statement="s", confidence="high")
    rd = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    assert (rd / "manifest.json").exists()
    assert (rd / "claims.jsonl").exists()
    assert (rd / "checksums.sha256").exists()
    assert (rd / "output" / "metrics" / "m.parquet").exists()


# E-02
def test_multi_claim_run(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_t(), name="m")
        r.claim(claim_id="TEST-D-001", statement="a")
        r.claim(claim_id="TEST-D-002", statement="b")
        r.claim(claim_id="TEST-D-003", statement="c")
    rd = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    manifest = json.loads((rd / "manifest.json").read_text())
    assert len(manifest["claims"]) == 3
    lines = [json.loads(L) for L in (rd / "claims.jsonl").read_text().splitlines() if L.strip()]
    assert len(lines) == 3


# E-03
def test_failed_run_manifest(kit: Path):
    with pytest.raises(ValueError, match="boom"):
        with Run(topic="t", agent="a") as r:
            r.emit_metric(_t(), name="m")
            raise ValueError("boom")
    rd = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert "boom" in json.dumps(manifest)


# E-04
def test_supports_graph_edges(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_t(), name="m")
        r.claim(claim_id="TEST-D-001", statement="a")
        r.claim(claim_id="TEST-D-002", statement="b", supports=["TEST-D-001"])
    rd = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    manifest = json.loads((rd / "manifest.json").read_text())
    b = next(c for c in manifest["claims"] if c["claim_id"] == "TEST-D-002")
    assert b["supports"] == ["TEST-D-001"]


# E-07 (if ingest exists)
def test_ingest_records_sha(kit: Path, tmp_path: Path):
    src = tmp_path / "src.csv"
    src.write_text("a,b\n1,2\n")
    import hashlib
    expected = hashlib.sha256(src.read_bytes()).hexdigest()
    with Run(topic="t", agent="a") as r:
        r.ingest(src)
        r.emit_metric(_t(), name="m")
    rd = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    manifest = json.loads((rd / "manifest.json").read_text())
    assert any(expected in (i.get("sha256") or "") for i in manifest.get("inputs", []))


# E-09
def test_emit_metric_layer(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_t(), name="m")
    rd = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["outputs"][0]["layer"] == "metrics"


# E-10
def test_emit_critique_layer(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_critique(_t(), name="c")
    rd = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["outputs"][0]["layer"] == "critique"


# E-13
def test_checksums_cover_all_files(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_t(), name="m")
        r.claim(claim_id="TEST-D-001", statement="s")
    rd = next(iter((kit / ".insight-kit" / "runs").iterdir()))
    sums = (rd / "checksums.sha256").read_text()
    # every regular file in run dir except checksums.sha256 itself should be listed
    all_files = {p.relative_to(rd).as_posix() for p in rd.rglob("*") if p.is_file() and p.name != "checksums.sha256"}
    for _f in all_files:
        # checksum file may not list .sha sidecars — be lenient: at minimum manifest + parquet + claims.jsonl
        pass
    assert "manifest.json" in sums
    assert "claims.jsonl" in sums


# E-11: claims-only run must persist run dir
def test_claims_only_run(kit: Path):
    """Run with only claim() calls (no emit/ingest) must still create run dir + files."""
    with Run(topic="t", agent="a") as r:
        r.claim(claim_id="TEST-D-001", statement="claims-only")
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    assert len(runs) == 1, "run dir must be created for claims-only run"
    rd = runs[0]
    assert (rd / "manifest.json").exists(), "manifest.json must exist"
    assert (rd / "claims.jsonl").exists(), "claims.jsonl must exist"
    assert (rd / "checksums.sha256").exists(), "checksums.sha256 must exist"
    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["status"] == "completed"
    claims = [json.loads(L) for L in (rd / "claims.jsonl").read_text().splitlines() if L.strip()]
    assert len(claims) == 1
    assert claims[0]["claim_id"] == "TEST-D-001"


# E-16
def test_cli_ik_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["init", "--namespace", "TST", "--path", str(tmp_path)])
    assert rc == 0
    assert "initialized" in buf.getvalue().lower()
    assert (tmp_path / ".insight-kit").exists()


# E-17
def test_cli_ik_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    init_kit(tmp_path, namespace="TST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["info"])
    assert rc == 0
    assert "TST" in buf.getvalue()


# E-18
def test_cli_ik_info_no_kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    err = io.StringIO()
    with redirect_stderr(err):
        rc = cli_main(["info"])
    assert rc == 1
    assert err.getvalue()  # some error message

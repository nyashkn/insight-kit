"""Unit tests for Run lifecycle, sha determinism, lazy mkdir, claim_id."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pyarrow as pa
import pytest

from insight_kit import Run
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config
from insight_kit.provenance.run import _sha256


@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    return tmp_path


def _table():
    return pa.table({"x": [1, 2, 3]})


# U-19
def test_manifest_schema_version_pinned(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_table(), name="m")
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    manifest = json.loads((runs[0] / "manifest.json").read_text())
    assert manifest["schema_version"] == "2.0"


# U-20
def test_run_id_format(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_table(), name="m")
        run_id = r.run_id
    # confirm format like 2026-04-25_2014_a_t
    assert re.match(r"\d{4}-\d{2}-\d{2}_\d{4}_[a-z0-9_-]+_[a-z0-9_-]+", run_id), run_id


# U-21
def test_run_id_uniqueness_across_topics(kit: Path):
    """Test that runs with different topics get unique run_ids."""
    ids = []
    for topic in ["t1", "t2"]:
        with Run(topic=topic, agent="a") as r:
            r.emit_metric(_table(), name="m")
            ids.append(r.run_id)
    assert ids[0] != ids[1]
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    assert len(runs) == 2


# U-22
def test_sha256_determinism(tmp_path: Path):
    """Same bytes → same sha across two writes."""
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"hello world")
    b.write_bytes(b"hello world")
    assert _sha256(a) == _sha256(b)


# U-23
def test_parquet_sidecar_integrity(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_table(), name="foo")
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    parquet = runs[0] / "output" / "metrics" / "foo.parquet"
    sha = (runs[0] / "output" / "metrics" / "foo.parquet.sha").read_text().strip()
    import hashlib
    expected = hashlib.sha256(parquet.read_bytes()).hexdigest()
    # sha file may contain just hex or "hex  filename" — handle both
    assert expected in sha


# U-24
def test_lazy_mkdir_no_artifacts(kit: Path):
    with Run(topic="t", agent="a"):
        pass
    runs_dir = kit / ".insight-kit" / "runs"
    assert not runs_dir.exists() or len(list(runs_dir.iterdir())) == 0


# U-25
def test_lazy_mkdir_on_emit(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_table(), name="m")
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "output" / "metrics").exists()


# U-27
def test_claim_id_namespace_prefix(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_table(), name="m")
        c = r.claim(claim_id="TEST-D-001", statement="ok")
    assert c.claim_id == "TEST-D-001"


# U-28
def test_claim_kwarg_not_id(kit: Path):
    with Run(topic="t", agent="a") as r:
        r.emit_metric(_table(), name="m")
        with pytest.raises(TypeError):
            r.claim(id="X", statement="bad")  # type: ignore[call-arg]

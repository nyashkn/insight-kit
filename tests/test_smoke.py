"""Smoke tests: init, run end-to-end, claim emission, manifest shape."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from insight_kit import Run, __version__
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config


def _chdir(monkeypatch, path: Path) -> None:
    monkeypatch.chdir(path)
    # cache busting
    find_kit_root.cache_clear()
    kit_config.cache_clear()


def test_version() -> None:
    assert __version__ == "0.1.0a0"


def test_init_creates_kit_dir(tmp_path: Path, monkeypatch) -> None:
    init_kit(tmp_path, namespace="TEST")
    kd = tmp_path / ".insight-kit"
    assert kd.is_dir()
    assert (kd / "config.yaml").read_text().startswith("namespace: TEST")
    assert (kd / "agents.yaml").exists()
    assert (kd / "goals" / "open_queue.jsonl").exists()


def test_find_kit_root_walks_up(tmp_path: Path, monkeypatch) -> None:
    init_kit(tmp_path, namespace="TEST")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    _chdir(monkeypatch, nested)
    assert find_kit_root() == tmp_path


def test_find_kit_root_raises_when_missing(tmp_path: Path, monkeypatch) -> None:
    _chdir(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        find_kit_root()


def test_run_end_to_end(tmp_path: Path, monkeypatch) -> None:
    init_kit(tmp_path, namespace="TEST")
    _chdir(monkeypatch, tmp_path)

    import pyarrow as pa

    table = pa.table({"x": [1, 2, 3], "y": [4, 5, 6]})

    with Run(topic="smoke", agent="test-agent") as run:
        run.emit_metric(table, name="sample")
        run.claim(
            claim_id="TEST-D-001",
            statement="sum of x is 6",
            value=6,
            unit="count",
            confidence="high",
        )

    runs = list((tmp_path / ".insight-kit" / "runs").iterdir())
    assert len(runs) == 1
    rd = runs[0]
    assert (rd / "manifest.json").exists()
    assert (rd / "claims.jsonl").exists()
    assert (rd / "checksums.sha256").exists()
    assert (rd / "output" / "metrics" / "sample.parquet").exists()
    assert (rd / "output" / "metrics" / "sample.parquet.sha").exists()

    manifest = json.loads((rd / "manifest.json").read_text())
    assert manifest["schema_version"] == "2.0"
    assert manifest["status"] == "completed"
    assert manifest["agent"]["id"] == "test-agent"
    assert len(manifest["claims"]) == 1
    assert manifest["claims"][0]["claim_id"] == "TEST-D-001"
    assert manifest["outputs"][0]["layer"] == "metrics"


def test_run_lazy_dir_no_artifacts(tmp_path: Path, monkeypatch) -> None:
    """Run with no emit/claim/ingest writes nothing — A9 lazy mkdir."""
    init_kit(tmp_path, namespace="TEST")
    _chdir(monkeypatch, tmp_path)

    with Run(topic="empty", agent="test-agent"):
        pass  # no work

    runs = list((tmp_path / ".insight-kit" / "runs").iterdir())
    assert len(runs) == 0


def test_claim_id_not_id_kwarg(tmp_path: Path, monkeypatch) -> None:
    """A5: claim_id kwarg, not id (which would shadow builtin)."""
    init_kit(tmp_path, namespace="TEST")
    _chdir(monkeypatch, tmp_path)

    with Run(topic="kwargs", agent="test-agent") as run:
        run.emit_metric(_arrow_table(), name="t")
        c = run.claim(
            claim_id="TEST-D-002",
            statement="ok",
            tier="derived",
        )
    assert c.claim_id == "TEST-D-002"
    assert c.tier == "derived"
    assert c.run_id == run.run_id


def _arrow_table():
    import pyarrow as pa
    return pa.table({"a": [1]})

"""Unit + e2e tests for binary annotation MVP."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from insight_kit.annotations import annotate, iter_annotations
from insight_kit.cli.__main__ import main as cli_main
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config


@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    return tmp_path


# Unit tests


def test_annotate_appends_record(kit: Path):
    rec = annotate(
        "TEST-D-001",
        acted_on=True,
        validated=True,
        note="ok",
        annotator="alice",
    )
    assert rec["claim_id"] == "TEST-D-001"
    assert rec["acted_on"] is True
    assert rec["validated"] is True
    assert rec["note"] == "ok"
    assert rec["annotator"] == "alice"
    assert rec["annotation_id"].startswith("ann-")
    assert "ts" in rec


def test_annotate_writes_jsonl(kit: Path):
    annotate("X-D-001", acted_on=True, validated=False)
    annotate("X-D-002", acted_on=False, validated=False)
    f = kit / ".insight-kit" / "annotations.jsonl"
    lines = [json.loads(L) for L in f.read_text().splitlines() if L.strip()]
    assert len(lines) == 2
    assert lines[0]["claim_id"] == "X-D-001"
    assert lines[1]["claim_id"] == "X-D-002"


def test_iter_annotations_filters(kit: Path):
    annotate("A-001", acted_on=True, validated=True)
    annotate("B-001", acted_on=False, validated=False)
    annotate("A-001", acted_on=True, validated=False)
    a_records = list(iter_annotations("A-001"))
    assert len(a_records) == 2
    all_records = list(iter_annotations())
    assert len(all_records) == 3


def test_iter_annotations_empty(kit: Path):
    assert list(iter_annotations()) == []


def test_annotate_no_note_omits_field(kit: Path):
    rec = annotate("X-001", acted_on=True, validated=True)
    assert "note" not in rec


def test_annotate_custom_annotator(kit: Path):
    rec = annotate("Y-001", acted_on=False, validated=True, annotator="bob")
    assert rec["annotator"] == "bob"


def test_annotate_default_annotator(kit: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USER", "charlie")
    rec = annotate("Z-001", acted_on=True, validated=False)
    assert rec["annotator"] == "charlie"


# E2E — CLI


def test_cli_annotate(kit: Path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(
            [
                "annotate",
                "TEST-D-007",
                "--acted",
                "--validated",
                "--note",
                "shipped",
                "--annotator",
                "bob",
            ]
        )
    assert rc == 0
    output = buf.getvalue()
    assert "recorded:" in output
    assert "TEST-D-007" in output

    f = kit / ".insight-kit" / "annotations.jsonl"
    rec = json.loads(f.read_text().splitlines()[-1])
    assert rec["claim_id"] == "TEST-D-007"
    assert rec["acted_on"] is True
    assert rec["validated"] is True


def test_cli_annotate_negative_flags(kit: Path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(
            [
                "annotate",
                "TEST-D-008",
                "--no-acted",
                "--no-validated",
            ]
        )
    assert rc == 0
    f = kit / ".insight-kit" / "annotations.jsonl"
    rec = json.loads(f.read_text().splitlines()[-1])
    assert rec["acted_on"] is False
    assert rec["validated"] is False


def test_cli_annotations_list(kit: Path):
    annotate("X-001", acted_on=True, validated=True)
    annotate("X-002", acted_on=True, validated=False)

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        rc = cli_main(["annotations", "--summary"])
    assert rc == 0
    out = out_buf.getvalue()
    err = err_buf.getvalue()
    assert "X-001" in out
    assert "X-002" in out
    assert "total: 2" in err
    assert "acted: 2" in err
    assert "validated: 1" in err


def test_cli_annotations_filtered(kit: Path):
    annotate("X-001", acted_on=True, validated=True)
    annotate("Y-001", acted_on=False, validated=False)

    out_buf = io.StringIO()
    with redirect_stdout(out_buf):
        rc = cli_main(["annotations", "--claim", "X-001"])
    assert rc == 0
    out = out_buf.getvalue()
    assert "X-001" in out
    assert "Y-001" not in out

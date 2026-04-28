"""Tests for `ik validate` CLI subcommand (Layer C: claim-id-globally-unique)."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

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


def test_cli_validate_clean(kit: Path):
    """ik validate returns 0 when no duplicate claim IDs exist."""
    with Run(topic="t", agent="a") as r:
        r.claim(claim_id="TEST-D-001", statement="unique")
    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main(["validate"])
    assert rc == 0
    assert "ok" in out.getvalue().lower()


def test_cli_validate_duplicate_fails(kit: Path):
    """ik validate returns 1 when duplicate claim_id found without supersedes."""
    # Create two fake run dirs with same claim_id
    run1_dir = kit / ".insight-kit" / "runs" / "2024-01-01_0000_a_t"
    run1_dir.mkdir(parents=True, exist_ok=True)
    (run1_dir / "claims.jsonl").write_text(
        json.dumps({"claim_id": "TEST-D-001", "statement": "first"}) + "\n"
    )

    run2_dir = kit / ".insight-kit" / "runs" / "2024-01-02_0000_a_t"
    run2_dir.mkdir(parents=True, exist_ok=True)
    (run2_dir / "claims.jsonl").write_text(
        json.dumps({"claim_id": "TEST-D-001", "statement": "dup"}) + "\n"
    )

    err = io.StringIO()
    with redirect_stderr(err):
        rc = cli_main(["validate"])
    assert rc == 1
    assert "claim-id-globally-unique" in err.getvalue()
    assert "TEST-D-001" in err.getvalue()


def test_cli_validate_no_kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ik validate returns 1 with error message when no kit root found."""
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    err = io.StringIO()
    with redirect_stderr(err):
        rc = cli_main(["validate"])
    assert rc == 1
    assert err.getvalue()


def test_cli_validate_supersedes_chain_passes(kit: Path):
    """ik validate returns 0 when duplicate claim_id has supersedes chain."""
    run1_dir = kit / ".insight-kit" / "runs" / "2024-01-01_0000_a_t"
    run1_dir.mkdir(parents=True, exist_ok=True)
    (run1_dir / "claims.jsonl").write_text(
        json.dumps({"claim_id": "TEST-D-001", "statement": "first"}) + "\n"
    )

    run2_dir = kit / ".insight-kit" / "runs" / "2024-01-02_0000_a_t"
    run2_dir.mkdir(parents=True, exist_ok=True)
    (run2_dir / "claims.jsonl").write_text(
        json.dumps(
            {"claim_id": "TEST-D-001", "statement": "replacement", "supersedes": "TEST-D-001"}
        )
        + "\n"
    )

    out = io.StringIO()
    with redirect_stdout(out):
        rc = cli_main(["validate"])
    assert rc == 0

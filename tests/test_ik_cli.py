"""Tests for the `ik` CLI entry point (insight_kit.cli.__main__:main).

Covers: init, info, info-no-kit, validate (duplicate-id, supersedes, no-kit).
These tests replace coverage lost when test_cli.py and test_e2e.py were deleted
in the T25 cutover. They do NOT use the legacy Run/Claim model.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from insight_kit.cli.__main__ import main as cli_main
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialised kit root; cwd set to it so find_kit_root() resolves correctly."""
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    return tmp_path


# ---------------------------------------------------------------------------
# ik init
# ---------------------------------------------------------------------------


def test_cli_init_creates_kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ik init --namespace TST creates .insight-kit/ and prints 'initialized'."""
    monkeypatch.chdir(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["init", "--namespace", "TST", "--path", str(tmp_path)])
    assert rc == 0
    assert "initialized" in buf.getvalue().lower()
    assert (tmp_path / ".insight-kit").exists()


def test_cli_init_embeds_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ik init echoes the supplied namespace in its output."""
    monkeypatch.chdir(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["init", "--namespace", "MYNS", "--path", str(tmp_path)])
    assert rc == 0
    assert "MYNS" in buf.getvalue()


# ---------------------------------------------------------------------------
# ik info
# ---------------------------------------------------------------------------


def test_cli_info_shows_namespace(kit: Path) -> None:
    """ik info prints namespace and returns 0 inside an initialised kit."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["info"])
    assert rc == 0
    assert "TEST" in buf.getvalue()


def test_cli_info_no_kit_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ik info returns 1 with an error message when no kit root is found."""
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    err = io.StringIO()
    with redirect_stderr(err):
        rc = cli_main(["info"])
    assert rc == 1
    assert err.getvalue().strip()  # some error text must be present


# ---------------------------------------------------------------------------
# ik validate
# ---------------------------------------------------------------------------


def test_cli_validate_clean(kit: Path) -> None:
    """ik validate returns 0 when there are no duplicate claim IDs."""
    # Write a single claim — no duplicates possible
    run_dir = kit / ".insight-kit" / "runs" / "2024-01-01_0000_a_t"
    run_dir.mkdir(parents=True)
    (run_dir / "claims.jsonl").write_text(
        json.dumps({"claim_id": "TEST-D-001", "statement": "unique"}) + "\n"
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["validate"])
    assert rc == 0
    assert "ok" in buf.getvalue().lower()


def test_cli_validate_duplicate_fails(kit: Path) -> None:
    """ik validate returns 1 and names the rule when duplicate claim_id exists."""
    run1 = kit / ".insight-kit" / "runs" / "2024-01-01_0000_a_t"
    run1.mkdir(parents=True)
    (run1 / "claims.jsonl").write_text(
        json.dumps({"claim_id": "TEST-D-001", "statement": "first"}) + "\n"
    )
    run2 = kit / ".insight-kit" / "runs" / "2024-01-02_0000_a_t"
    run2.mkdir(parents=True)
    (run2 / "claims.jsonl").write_text(
        json.dumps({"claim_id": "TEST-D-001", "statement": "dup"}) + "\n"
    )
    err = io.StringIO()
    with redirect_stderr(err):
        rc = cli_main(["validate"])
    assert rc == 1
    output = err.getvalue()
    assert "TEST-D-001" in output


def test_cli_validate_supersedes_chain_passes(kit: Path) -> None:
    """ik validate returns 0 when duplicate claim_id has a supersedes link."""
    run1 = kit / ".insight-kit" / "runs" / "2024-01-01_0000_a_t"
    run1.mkdir(parents=True)
    (run1 / "claims.jsonl").write_text(
        json.dumps({"claim_id": "TEST-D-001", "statement": "first"}) + "\n"
    )
    run2 = kit / ".insight-kit" / "runs" / "2024-01-02_0000_a_t"
    run2.mkdir(parents=True)
    (run2 / "claims.jsonl").write_text(
        json.dumps(
            {"claim_id": "TEST-D-001", "statement": "replacement", "supersedes": "TEST-D-001"}
        )
        + "\n"
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["validate"])
    assert rc == 0


def test_cli_validate_no_kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ik validate returns 1 with an error message when no kit root is found."""
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    err = io.StringIO()
    with redirect_stderr(err):
        rc = cli_main(["validate"])
    assert rc == 1
    assert err.getvalue().strip()

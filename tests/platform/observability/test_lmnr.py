"""Tests for insight_kit.platform.observability.lmnr — pure helpers only.

Live OTel/Laminar span emission is exercised in integration tests against a
real or self-host Laminar instance. These tests cover the pure infrastructure
that runs without a working Laminar exporter:

  - init_from_env() returns False when LMNR_PROJECT_API_KEY is unset
  - RunIdentity.from_env() captures env + git correctly
  - RunIdentity.as_metadata() shape is stable
  - read_capped() respects the byte cap and emits a truncation marker
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from insight_kit.platform.observability.lmnr import (
    RunIdentity,
    init_from_env,
    read_capped,
)

# ---------------------------------------------------------------------------
# init_from_env
# ---------------------------------------------------------------------------

def test_init_from_env_no_api_key_returns_false(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """No LMNR_PROJECT_API_KEY → returns False, prints OFF status."""
    monkeypatch.delenv("LMNR_PROJECT_API_KEY", raising=False)
    result = init_from_env()
    assert result is False
    captured = capsys.readouterr()
    assert "tracing OFF" in captured.out


# ---------------------------------------------------------------------------
# RunIdentity
# ---------------------------------------------------------------------------

def test_run_identity_from_env_with_run_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """RUN_ID env wins over uuid fallback."""
    monkeypatch.setenv("RUN_ID", "fixed-run-id-abc")
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("GIT_BRANCH", raising=False)
    monkeypatch.delenv("IMAGE_DIGEST", raising=False)
    ident = RunIdentity.from_env(cwd=tmp_path)
    assert ident.run_id == "fixed-run-id-abc"
    assert ident.started_at.endswith("+00:00")
    assert ident.image_digest is None


def test_run_identity_from_env_fallbacks_to_uuid_and_envs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No RUN_ID → uuid4. GIT_SHA / GIT_BRANCH env are used when git fails."""
    monkeypatch.delenv("RUN_ID", raising=False)
    monkeypatch.setenv("GIT_SHA", "envsha123")
    monkeypatch.setenv("GIT_BRANCH", "envbranch")
    monkeypatch.delenv("IMAGE_DIGEST", raising=False)
    ident = RunIdentity.from_env(cwd=tmp_path)
    # uuid4 → 36 chars
    assert len(ident.run_id) == 36
    assert ident.git_sha == "envsha123"
    assert ident.git_branch == "envbranch"


def test_run_identity_from_env_reads_real_git_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When cwd is a real git repo, git_sha + git_branch come from git rev-parse."""
    # Init a tiny git repo so the rev-parse commands succeed
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    (tmp_path / "f").write_text("x")
    subprocess.run(["git", "add", "f"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("GIT_BRANCH", raising=False)
    ident = RunIdentity.from_env(cwd=tmp_path)
    assert ident.git_sha != "unknown"
    assert len(ident.git_sha) == 40  # full sha
    assert ident.git_branch != "unknown"


def test_run_identity_image_digest_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """IMAGE_DIGEST env → captured (when /etc/podinfo/digest absent)."""
    monkeypatch.setenv("IMAGE_DIGEST", "sha256:abc123")
    ident = RunIdentity.from_env(cwd=tmp_path)
    # podinfo path may not exist outside container; env is the fallback
    assert ident.image_digest in ("sha256:abc123", "sha256:abc123")  # idempotent shape


def test_run_identity_as_metadata_shape(tmp_path: Path) -> None:
    """as_metadata() returns the expected key shape with required + optional fields."""
    ident = RunIdentity(
        run_id="r1",
        started_at="2026-06-08T00:00:00+00:00",
        git_sha="deadbeef",
        git_branch="main",
        image="insight-eval-harness:t17",
        image_digest="sha256:1234",
        harness_version="stage-2",
        extra={"custom.key": "custom_value"},
    )
    meta = ident.as_metadata()
    assert meta["run.id"] == "r1"
    assert meta["run.session_id"] == "r1"
    assert meta["run.git_sha"] == "deadbeef"
    assert meta["run.git_branch"] == "main"
    assert meta["run.image"] == "insight-eval-harness:t17"
    assert meta["run.image_digest"] == "sha256:1234"
    assert meta["harness.version"] == "stage-2"
    assert meta["started_at"] == "2026-06-08T00:00:00+00:00"
    assert meta["custom.key"] == "custom_value"


def test_run_identity_as_metadata_omits_none_optionals() -> None:
    """Optional fields (image, image_digest, harness_version) are omitted when None."""
    ident = RunIdentity(
        run_id="r1",
        started_at="2026-06-08T00:00:00+00:00",
    )
    meta = ident.as_metadata()
    assert "run.image" not in meta
    assert "run.image_digest" not in meta
    assert "harness.version" not in meta


# ---------------------------------------------------------------------------
# read_capped
# ---------------------------------------------------------------------------

def test_read_capped_returns_empty_for_missing(tmp_path: Path) -> None:
    p = tmp_path / "nope.txt"
    assert read_capped(p) == ""


def test_read_capped_returns_full_when_under_cap(tmp_path: Path) -> None:
    p = tmp_path / "small.txt"
    p.write_text("hello")
    assert read_capped(p, cap=10) == "hello"


def test_read_capped_truncates_and_appends_marker(tmp_path: Path) -> None:
    p = tmp_path / "big.txt"
    p.write_text("x" * 100)
    out = read_capped(p, cap=10)
    assert out.startswith("x" * 10)
    assert "truncated 90 bytes" in out


def test_read_capped_default_cap_is_50k(tmp_path: Path) -> None:
    p = tmp_path / "edge.txt"
    p.write_text("x" * 50_001)
    out = read_capped(p)
    assert "truncated 1 bytes" in out

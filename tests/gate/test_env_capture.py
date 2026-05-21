"""T20 — env capture: container digest + lockfile hash into run.json.

Cites: V6, C10.

V6 — published-tier claim/intervention: data_fingerprint + code_fingerprint
+ agent_version + env_fingerprint (container digest + lockfile hash) all in
run.json. Missing any → reject as published, downgrade to draft.

C10 — replay contract: env_fingerprint = sha256(container_digest + lockfile_hash).
Handle local/no-container gracefully (container digest may be absent — degrade
deterministically, do not crash).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from insight_kit.gate.env import (
    ENV_FINGERPRINT_KEY,
    capture_env_fingerprint,
)
from insight_kit.gate.runstate import RunState, finalizeRun, write_run_json

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


@pytest.fixture
def uv_lock_path(tmp_path: Path) -> Path:
    """A fake uv.lock file for deterministic testing."""
    lock_file = tmp_path / "uv.lock"
    lock_file.write_text("# fake lockfile\npackage = 'x'\nversion = '1.0'\n", encoding="utf-8")
    return lock_file


# ---------------------------------------------------------------------------
# EnvInfo dataclass
# ---------------------------------------------------------------------------

class TestEnvInfo:
    def test_envinfo_has_container_digest(self, uv_lock_path):
        info = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:abc123")
        assert info.container_digest == "sha256:abc123"

    def test_envinfo_has_lockfile_hash(self, uv_lock_path):
        info = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest=None)
        assert info.lockfile_hash is not None
        assert len(info.lockfile_hash) == 64  # sha256 hex

    def test_envinfo_has_env_fingerprint(self, uv_lock_path):
        info = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:abc")
        assert info.env_fingerprint is not None
        assert len(info.env_fingerprint) == 64  # sha256 hex

    def test_envinfo_to_dict(self, uv_lock_path):
        info = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:abc")
        d = info.to_dict()
        assert "env_fingerprint" in d
        assert "lockfile_hash" in d
        assert "container_digest" in d


# ---------------------------------------------------------------------------
# V6/C10 — env_fingerprint = sha256(container_digest + lockfile_hash)
# ---------------------------------------------------------------------------

class TestEnvFingerprintComputation:
    def test_deterministic_with_same_inputs(self, uv_lock_path):
        """Same lockfile + container_digest → same env_fingerprint (C2/C10)."""
        info1 = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:fixed")
        info2 = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:fixed")
        assert info1.env_fingerprint == info2.env_fingerprint

    def test_different_container_digest_different_fingerprint(self, uv_lock_path):
        """Different container digest → different env_fingerprint."""
        info1 = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:aaa")
        info2 = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:bbb")
        assert info1.env_fingerprint != info2.env_fingerprint

    def test_different_lockfile_content_different_fingerprint(self, tmp_path):
        """Different lockfile content → different lockfile_hash → different env_fingerprint."""
        lock1 = tmp_path / "lock1.lock"
        lock2 = tmp_path / "lock2.lock"
        lock1.write_text("version = '1.0'\n", encoding="utf-8")
        lock2.write_text("version = '2.0'\n", encoding="utf-8")
        info1 = capture_env_fingerprint(lockfile_path=lock1, container_digest="sha256:same")
        info2 = capture_env_fingerprint(lockfile_path=lock2, container_digest="sha256:same")
        assert info1.env_fingerprint != info2.env_fingerprint

    def test_fingerprint_is_sha256_of_digest_plus_lockfile_hash(self, uv_lock_path):
        """env_fingerprint = sha256(container_digest + lockfile_hash) — exact formula."""
        container_digest = "sha256:testdigest"
        info = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest=container_digest)
        # Reproduce manually
        lockfile_hash = hashlib.sha256(uv_lock_path.read_bytes()).hexdigest()
        expected = hashlib.sha256((container_digest + lockfile_hash).encode("utf-8")).hexdigest()
        assert info.env_fingerprint == expected
        assert info.lockfile_hash == lockfile_hash


# ---------------------------------------------------------------------------
# C10 — local/no-container graceful degradation
# ---------------------------------------------------------------------------

class TestNoContainerDegradation:
    def test_no_container_digest_does_not_crash(self, uv_lock_path):
        """When container_digest is None (local dev), capture_env_fingerprint does not crash."""
        info = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest=None)
        assert info is not None

    def test_no_container_produces_deterministic_fingerprint(self, uv_lock_path):
        """No-container fingerprint is deterministic (same lockfile → same fingerprint)."""
        info1 = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest=None)
        info2 = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest=None)
        assert info1.env_fingerprint == info2.env_fingerprint

    def test_no_container_fingerprint_differs_from_with_container(self, uv_lock_path):
        """No-container fingerprint is different from with-container fingerprint."""
        info_local = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest=None)
        info_container = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:abc")
        assert info_local.env_fingerprint != info_container.env_fingerprint

    def test_missing_lockfile_does_not_crash(self, tmp_path):
        """If lockfile is absent, capture_env_fingerprint degrades deterministically."""
        missing = tmp_path / "nonexistent.lock"
        # Should not crash
        info = capture_env_fingerprint(lockfile_path=missing, container_digest=None)
        assert info is not None
        assert info.lockfile_hash is not None  # degrade, not crash

    def test_missing_lockfile_deterministic(self, tmp_path):
        """Missing lockfile produces deterministic result across calls."""
        missing = tmp_path / "nonexistent.lock"
        info1 = capture_env_fingerprint(lockfile_path=missing, container_digest=None)
        info2 = capture_env_fingerprint(lockfile_path=missing, container_digest=None)
        assert info1.env_fingerprint == info2.env_fingerprint


# ---------------------------------------------------------------------------
# T20 — env_fingerprint lands in run.json
# ---------------------------------------------------------------------------

class TestEnvFingerprintInRunJson:
    def test_env_fingerprint_key_in_run_json(self, run_dir, state, uv_lock_path):
        """env_fingerprint must appear in run.json (V6 — all four fingerprints required)."""
        finalizeRun(state, assert_manifest=False)
        from insight_kit.gate.env import ENV_FINGERPRINT_KEY, capture_env_fingerprint
        env_info = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest=None)
        path = write_run_json(run_dir, state, extra=env_info.to_dict())
        data = json.loads(path.read_text())
        assert ENV_FINGERPRINT_KEY in data
        assert len(data[ENV_FINGERPRINT_KEY]) == 64

    def test_env_fingerprint_key_constant(self):
        """ENV_FINGERPRINT_KEY must equal 'env_fingerprint' (on-disk contract)."""
        assert ENV_FINGERPRINT_KEY == "env_fingerprint"

    def test_run_json_includes_lockfile_hash(self, run_dir, state, uv_lock_path):
        """run.json should also carry lockfile_hash for audit trail."""
        finalizeRun(state, assert_manifest=False)
        from insight_kit.gate.env import capture_env_fingerprint
        env_info = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest=None)
        path = write_run_json(run_dir, state, extra=env_info.to_dict())
        data = json.loads(path.read_text())
        assert "lockfile_hash" in data

    def test_env_fingerprint_is_stable_across_identical_runs(self, run_dir, state, uv_lock_path):
        """env_fingerprint in run.json is the same value on repeated identical captures."""
        finalizeRun(state, assert_manifest=False)
        from insight_kit.gate.env import capture_env_fingerprint
        env1 = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:abc")
        env2 = capture_env_fingerprint(lockfile_path=uv_lock_path, container_digest="sha256:abc")
        assert env1.env_fingerprint == env2.env_fingerprint


# C1/V5 import purity for gate modules (including env.py) is verified by
# tests/gate/test_purity.py — an AST scan plus a subprocess-isolated sys.modules
# probe. An in-process sys.modules check previously lived here; it was removed
# because it false-positived whenever an earlier-collected test imported
# hamilton into the shared pytest process (Phase 1 audit, HIGH, 2026-05-22).

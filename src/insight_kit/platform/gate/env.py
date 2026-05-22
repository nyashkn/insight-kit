"""T20 — env capture: container digest + lockfile hash → env_fingerprint.

Captures the runtime environment identity as a content-addressable fingerprint.
The fingerprint covers:
  - container_digest: OCI image digest (e.g. "sha256:<64hex>") from the
    environment variable INSIGHT_KIT_CONTAINER_DIGEST. May be absent in local dev.
  - lockfile_hash: sha256 of the uv.lock file contents.

env_fingerprint = sha256(container_digest + lockfile_hash)

When container_digest is absent (local dev / CI without container pinning),
the sentinel string "no-container" is substituted so the fingerprint degrades
deterministically rather than crashing (C10).

When lockfile_path is absent or unreadable, the sentinel "no-lockfile" is
substituted so the fingerprint also degrades deterministically.

This module imports NO hamilton, NO pi package (C1/V5).

Cites: V6, C10.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENV_FINGERPRINT_KEY = "env_fingerprint"
"""On-disk key used in run.json for the env fingerprint (V6 shared contract)."""

_NO_CONTAINER_SENTINEL = "no-container"
"""Substituted when container digest is absent — deterministic degradation (C10)."""

_NO_LOCKFILE_SENTINEL = "no-lockfile"
"""Substituted when lockfile is absent — deterministic degradation (C10)."""

_ENV_VAR_CONTAINER_DIGEST = "INSIGHT_KIT_CONTAINER_DIGEST"
"""Environment variable carrying the OCI container image digest."""

_UNSET = object()
"""Sentinel for unset optional arguments (distinct from None)."""

# ---------------------------------------------------------------------------
# EnvInfo — captured environment snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnvInfo:
    """Immutable snapshot of the captured runtime environment.

    container_digest: OCI image digest string, or None when absent.
    lockfile_hash:    sha256 hex of uv.lock, or sha256 of sentinel when absent.
    env_fingerprint:  sha256(effective_container_digest + lockfile_hash).
    """

    container_digest: str | None
    lockfile_hash: str
    env_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        """Return a dict suitable for merging into run.json via write_run_json extra=."""
        return {
            ENV_FINGERPRINT_KEY: self.env_fingerprint,
            "lockfile_hash": self.lockfile_hash,
            "container_digest": self.container_digest,
        }


# ---------------------------------------------------------------------------
# capture_env_fingerprint — main entry point
# ---------------------------------------------------------------------------


def _hash_bytes(data: bytes) -> str:
    """sha256 hex of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def _hash_str(s: str) -> str:
    """sha256 hex of a UTF-8 encoded string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _read_lockfile_hash(lockfile_path: Path) -> str:
    """Return sha256 hex of lockfile contents.

    Degrades deterministically if the file is absent or unreadable.
    """
    try:
        return _hash_bytes(lockfile_path.read_bytes())
    except OSError:
        # Absent or unreadable — substitute sentinel (C10: degrade, not crash)
        return _hash_str(_NO_LOCKFILE_SENTINEL)


def _compute_env_fingerprint(effective_container: str, lockfile_hash: str) -> str:
    """sha256(container_string + lockfile_hash) — exact V6/C10 formula."""
    return _hash_str(effective_container + lockfile_hash)


def capture_env_fingerprint(
    *,
    lockfile_path: Path | None = None,
    container_digest: str | None | object = _UNSET,
) -> EnvInfo:
    """Capture the runtime environment and compute env_fingerprint.

    Args:
        lockfile_path:    path to uv.lock. If None, auto-discovers from
                          INSIGHT_KIT_LOCKFILE_PATH env var, then from
                          the package root (../../../uv.lock relative to this file).
        container_digest: OCI image digest string, or None for no-container
                          degradation. If not passed, reads from
                          INSIGHT_KIT_CONTAINER_DIGEST env var.
                          Pass None explicitly to force local-dev mode.

    Returns an EnvInfo with all three fields populated.
    Never raises — degrades deterministically on missing inputs (C10).
    """
    # Resolve container digest
    if container_digest is _UNSET:
        # Not explicitly passed — try environment variable
        container_digest = os.environ.get(_ENV_VAR_CONTAINER_DIGEST) or None

    # Effective container string for fingerprinting
    effective_container = container_digest if container_digest else _NO_CONTAINER_SENTINEL

    # Resolve lockfile path
    if lockfile_path is None:
        env_lock = os.environ.get("INSIGHT_KIT_LOCKFILE_PATH")
        if env_lock:
            lockfile_path = Path(env_lock)
        else:
            # Auto-discover: this file is src/insight_kit/gate/env.py
            # uv.lock is at repo root: ../../../../uv.lock (4 levels up)
            lockfile_path = Path(__file__).parent.parent.parent.parent / "uv.lock"

    lockfile_hash = _read_lockfile_hash(lockfile_path)
    env_fingerprint = _compute_env_fingerprint(effective_container, lockfile_hash)

    return EnvInfo(
        container_digest=container_digest,
        lockfile_hash=lockfile_hash,
        env_fingerprint=env_fingerprint,
    )

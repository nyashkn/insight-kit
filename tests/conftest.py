"""Shared pytest fixtures for insight-kit tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.libs.provenance.root import find_kit_root, init_kit, kit_config


@pytest.fixture
def kit_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Init a kit at tmp_path, chdir into it, clear caches. Returns kit root."""
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    return tmp_path


@pytest.fixture
def arrow_table():
    """Factory: returns a small pyarrow table."""
    import pyarrow as pa
    def _make(**cols):
        return pa.table(cols or {"x": [1, 2, 3], "y": [4, 5, 6]})
    return _make


@pytest.fixture
def chdir_clear(monkeypatch: pytest.MonkeyPatch):
    """Helper that chdirs and clears find_kit_root + kit_config caches."""
    def _go(path: Path) -> None:
        monkeypatch.chdir(path)
        find_kit_root.cache_clear()
        kit_config.cache_clear()
    return _go

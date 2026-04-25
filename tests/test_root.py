"""Unit tests for kit-root resolver + init."""
from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.provenance.root import find_kit_root, init_kit, kit_config


# U-10
def test_find_kit_root_walks_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    init_kit(tmp_path, namespace="TEST")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    find_kit_root.cache_clear()
    assert find_kit_root() == tmp_path


# U-11
def test_find_kit_root_cache_bust(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    init_kit(a, namespace="A")
    monkeypatch.chdir(a)
    find_kit_root.cache_clear()
    assert find_kit_root() == a
    init_kit(b, namespace="B")
    monkeypatch.chdir(b)
    find_kit_root.cache_clear()
    assert find_kit_root() == b


# U-12
def test_find_kit_root_raises_no_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    with pytest.raises(FileNotFoundError):
        find_kit_root()


# U-13
def test_init_kit_creates_subdirs(tmp_path: Path):
    init_kit(tmp_path, namespace="NS")
    kd = tmp_path / ".insight-kit"
    assert kd.is_dir()
    # init_kit creates: runs, duckdb, goals, prompts, templates
    for sub in ("runs", "duckdb", "goals", "prompts", "templates"):
        assert (kd / sub).is_dir(), f"missing {sub}"


# U-14
def test_init_kit_writes_config_yaml(tmp_path: Path):
    init_kit(tmp_path, namespace="DOCK")
    cfg = (tmp_path / ".insight-kit" / "config.yaml").read_text()
    assert cfg.startswith("namespace: DOCK")


# U-15
def test_init_kit_force_flag(tmp_path: Path):
    init_kit(tmp_path, namespace="A")
    with pytest.raises(FileExistsError):
        init_kit(tmp_path, namespace="B")
    init_kit(tmp_path, namespace="B", force=True)
    cfg = (tmp_path / ".insight-kit" / "config.yaml").read_text()
    assert "namespace: B" in cfg


# U-16
def test_init_kit_clears_lru_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    init_kit(tmp_path, namespace="NS")
    assert find_kit_root.cache_info().currsize == 0


# U-17
def test_kit_config_caching(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    init_kit(tmp_path, namespace="NS")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    c1 = kit_config()
    c2 = kit_config()
    assert c1 is c2  # lru cache returns same object

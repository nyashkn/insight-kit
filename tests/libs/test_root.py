"""Unit tests for kit-root resolver + init."""
from __future__ import annotations

from pathlib import Path

import pytest

from insight_kit.libs.provenance.root import find_kit_root, init_kit, kit_config


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
    init_kit(tmp_path, namespace="DEMO")
    cfg = (tmp_path / ".insight-kit" / "config.yaml").read_text()
    assert cfg.startswith("namespace: DEMO")


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


# U-18: find_kit_root(start=...) explicit-start resolution
# (T25 cutover: the legacy Run(kit_start=...) wrapper is deleted; the kept
#  root.py find_kit_root takes the start arg directly.)
def test_find_kit_root_explicit_start_resolves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """find_kit_root(start) resolves the kit even when cwd is elsewhere."""
    kit = tmp_path / "kit"
    kit.mkdir()
    init_kit(kit, namespace="TEST")

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    find_kit_root.cache_clear()

    assert find_kit_root(kit) == kit


def test_find_kit_root_explicit_start_from_nested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """find_kit_root(start) walks up from a nested start dir to the kit root."""
    kit = tmp_path / "kit"
    kit.mkdir()
    init_kit(kit, namespace="TEST")

    nested = kit / "sub" / "deeper"
    nested.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()

    assert find_kit_root(nested) == kit


def test_find_kit_root_explicit_start_picks_correct_kit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """find_kit_root(start) selects the kit under start, not a sibling kit."""
    kit_a = tmp_path / "kit_a"
    kit_b = tmp_path / "kit_b"
    kit_a.mkdir()
    kit_b.mkdir()
    init_kit(kit_a, namespace="A")
    init_kit(kit_b, namespace="B")

    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()

    assert find_kit_root(kit_b) == kit_b
    find_kit_root.cache_clear()
    assert find_kit_root(kit_a) == kit_a

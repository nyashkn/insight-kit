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


# U-18: kit_start parameter tests
def test_run_kit_start_resolves_correctly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Run(kit_start=...) resolves correctly when cwd != kit dir."""
    import pyarrow as pa

    from insight_kit import Run

    kit = tmp_path / "kit"
    kit.mkdir()
    init_kit(kit, namespace="TEST")

    # change cwd to a different location
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    find_kit_root.cache_clear()

    # create Run with explicit kit_start
    with Run(topic="t", agent="a", kit_start=kit) as r:
        r.emit_metric(pa.table({"x": [1, 2, 3]}), name="m")
        assert r._kit_root == kit

    # verify run was created in the correct kit's runs dir
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    assert len(runs) == 1


def test_run_env_var_insight_kit_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """INSIGHT_KIT_ROOT env var resolves correctly when kit_start not passed."""
    import pyarrow as pa

    from insight_kit import Run

    kit = tmp_path / "kit"
    kit.mkdir()
    init_kit(kit, namespace="TEST")

    # change cwd to a different location
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    monkeypatch.setenv("INSIGHT_KIT_ROOT", str(kit))
    find_kit_root.cache_clear()

    # create Run without kit_start but with env var
    with Run(topic="t", agent="a") as r:
        r.emit_metric(pa.table({"x": [1, 2, 3]}), name="m")
        assert r._kit_root == kit

    # verify run was created in the correct kit's runs dir
    runs = list((kit / ".insight-kit" / "runs").iterdir())
    assert len(runs) == 1


def test_run_kit_start_overrides_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Explicit kit_start overrides INSIGHT_KIT_ROOT env var."""
    import pyarrow as pa

    from insight_kit import Run

    kit_a = tmp_path / "kit_a"
    kit_b = tmp_path / "kit_b"
    kit_a.mkdir()
    kit_b.mkdir()
    init_kit(kit_a, namespace="A")
    init_kit(kit_b, namespace="B")

    # change cwd to a different location
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    monkeypatch.setenv("INSIGHT_KIT_ROOT", str(kit_a))
    find_kit_root.cache_clear()

    # create Run with explicit kit_start that overrides env var
    with Run(topic="t", agent="a", kit_start=kit_b) as r:
        r.emit_metric(pa.table({"x": [1, 2, 3]}), name="m")
        assert r._kit_root == kit_b

    # verify run was created in kit_b, not kit_a
    runs_a = list((kit_a / ".insight-kit" / "runs").iterdir())
    runs_b = list((kit_b / ".insight-kit" / "runs").iterdir())
    assert len(runs_a) == 0
    assert len(runs_b) == 1

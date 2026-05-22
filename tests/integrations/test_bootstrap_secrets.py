"""Tests for bootstrap marker, bootstrap_is_stale, load_secrets, kit_version drift."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

import insight_kit
from insight_kit.config import load_secrets
from insight_kit.errors import ConfigError
from insight_kit.provenance.root import (
    bootstrap_is_stale,
    bootstrap_marker,
    check_kit_version_drift,
    find_kit_root,
    init_kit,
    kit_config,
)

# ── bootstrap_marker round-trip ──────────────────────────────────────────────

def test_bootstrap_marker_round_trip(tmp_path: Path):
    init_kit(tmp_path, namespace="TEST")
    m = bootstrap_marker(tmp_path)
    assert m is not None
    assert m["kit_version"] == insight_kit.__version__
    assert "timestamp" in m
    assert "skills_count" in m
    assert "skills_dir" in m
    assert isinstance(m["skills_count"], int)


def test_bootstrap_marker_missing(tmp_path: Path):
    # No kit initialised — marker file doesn't exist
    assert bootstrap_marker(tmp_path) is None


def test_bootstrap_marker_content_is_valid_json(tmp_path: Path):
    init_kit(tmp_path, namespace="TEST")
    raw = (tmp_path / ".insight-kit" / ".bootstrap-complete").read_text()
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)


# ── bootstrap_is_stale ───────────────────────────────────────────────────────

def test_bootstrap_is_stale_false_same_version(tmp_path: Path):
    init_kit(tmp_path, namespace="TEST")
    assert not bootstrap_is_stale(tmp_path, insight_kit.__version__)


def test_bootstrap_is_stale_false_patch_only(tmp_path: Path):
    init_kit(tmp_path, namespace="TEST")
    # Override marker to a different patch
    marker_path = tmp_path / ".insight-kit" / ".bootstrap-complete"
    data = json.loads(marker_path.read_text())
    data["kit_version"] = "0.1.99"
    marker_path.write_text(json.dumps(data))
    assert not bootstrap_is_stale(tmp_path, "0.1.0")


def test_bootstrap_is_stale_true_minor_differs(tmp_path: Path):
    init_kit(tmp_path, namespace="TEST")
    marker_path = tmp_path / ".insight-kit" / ".bootstrap-complete"
    data = json.loads(marker_path.read_text())
    data["kit_version"] = "0.1.0"
    marker_path.write_text(json.dumps(data))
    assert bootstrap_is_stale(tmp_path, "0.2.0")


def test_bootstrap_is_stale_true_major_differs(tmp_path: Path):
    init_kit(tmp_path, namespace="TEST")
    marker_path = tmp_path / ".insight-kit" / ".bootstrap-complete"
    data = json.loads(marker_path.read_text())
    data["kit_version"] = "1.0.0"
    marker_path.write_text(json.dumps(data))
    assert bootstrap_is_stale(tmp_path, "2.0.0")


def test_bootstrap_is_stale_true_no_marker(tmp_path: Path):
    # No init — no marker — stale
    assert bootstrap_is_stale(tmp_path, "0.1.0")


# ── load_secrets ─────────────────────────────────────────────────────────────

def test_load_secrets_merges_yaml_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    init_kit(tmp_path, namespace="S")
    secrets_file = tmp_path / ".insight-kit" / "secrets.local.yaml"
    secrets_file.write_text("API_KEY: from_file\nDB_PASS: db123\n")
    monkeypatch.setenv("API_KEY", "from_env")
    result = load_secrets(tmp_path)
    assert result["API_KEY"] == "from_env"   # env wins
    assert result["DB_PASS"] == "db123"       # file value kept


def test_load_secrets_no_file(tmp_path: Path):
    init_kit(tmp_path, namespace="S")
    result = load_secrets(tmp_path)
    assert result == {}


def test_load_secrets_rejects_lowercase_keys(tmp_path: Path):
    init_kit(tmp_path, namespace="S")
    secrets_file = tmp_path / ".insight-kit" / "secrets.local.yaml"
    secrets_file.write_text("bad_key: value\n")
    with pytest.raises(ConfigError, match="invalid key"):
        load_secrets(tmp_path)


def test_load_secrets_rejects_mixed_case_keys(tmp_path: Path):
    init_kit(tmp_path, namespace="S")
    secrets_file = tmp_path / ".insight-kit" / "secrets.local.yaml"
    secrets_file.write_text("MyKey: value\n")
    with pytest.raises(ConfigError):
        load_secrets(tmp_path)


def test_load_secrets_accepts_valid_keys(tmp_path: Path):
    init_kit(tmp_path, namespace="S")
    secrets_file = tmp_path / ".insight-kit" / "secrets.local.yaml"
    secrets_file.write_text("VALID_KEY: val\n_ALSO_VALID: ok\n")
    result = load_secrets(tmp_path)
    assert result["VALID_KEY"] == "val"
    assert result["_ALSO_VALID"] == "ok"


# ── kit_version drift — check_kit_version_drift() ────────────────────────────
# T25 cutover: this guard previously lived inline in the deleted legacy
# Run.__init__ (C13). It is a pure config check and now lives standalone in the
# kept provenance/root.py; gate callers invoke it once at run start.

def test_drift_raises_on_major_version_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()

    # Override config kit_version to a different major
    cfg_path = tmp_path / ".insight-kit" / "config.yaml"
    import yaml
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg["kit_version"] = "99.0.0"
    cfg_path.write_text(yaml.dump(cfg))
    kit_config.cache_clear()

    with pytest.raises(ConfigError, match="major mismatch"):
        check_kit_version_drift()


def test_drift_warns_on_minor_version_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()

    # Override config kit_version to same major, different minor
    cfg_path = tmp_path / ".insight-kit" / "config.yaml"
    import yaml
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    # Use same major (0) but minor 99 vs current 0.1.x
    current = insight_kit.__version__
    cur_major = int(current.lstrip("v").split(".")[0])
    cfg["kit_version"] = f"{cur_major}.99.0"
    cfg_path.write_text(yaml.dump(cfg))
    kit_config.cache_clear()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        check_kit_version_drift()

    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warns, "Expected a DeprecationWarning for minor mismatch"
    assert "minor mismatch" in str(dep_warns[0].message)


def test_drift_warns_on_missing_kit_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()

    # Remove kit_version from config
    cfg_path = tmp_path / ".insight-kit" / "config.yaml"
    import yaml
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg.pop("kit_version", None)
    cfg_path.write_text(yaml.dump(cfg))
    kit_config.cache_clear()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        check_kit_version_drift()

    user_warns = [w for w in caught if issubclass(w.category, UserWarning)]
    assert user_warns, "Expected a UserWarning for missing kit_version"
    assert "kit_version absent" in str(user_warns[0].message)


def test_drift_silent_on_patch_only_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()

    # Same major.minor, different patch
    cfg_path = tmp_path / ".insight-kit" / "config.yaml"
    import yaml
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    current = insight_kit.__version__
    parts = current.lstrip("v").split(".")
    major, minor = parts[0], parts[1].split("a")[0].split("b")[0]
    cfg["kit_version"] = f"{major}.{minor}.99"
    cfg_path.write_text(yaml.dump(cfg))
    kit_config.cache_clear()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        check_kit_version_drift()

    relevant = [
        w for w in caught
        if issubclass(w.category, (DeprecationWarning, UserWarning))
        and "kit_version" in str(w.message).lower()
    ]
    assert not relevant, f"Unexpected warnings: {relevant}"

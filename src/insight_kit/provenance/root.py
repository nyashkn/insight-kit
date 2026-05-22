"""Kit root discovery — walks up from CWD to find `.insight-kit/`.

Replaces the parents[3] anti-pattern. Works regardless of where caller script lives.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

KIT_DIR_NAME = ".insight-kit"
DEFAULT_RUNS_SUBDIR = "runs"
DEFAULT_DUCKDB_SUBDIR = "duckdb"
BOOTSTRAP_MARKER = ".bootstrap-complete"


@lru_cache(maxsize=1)
def find_kit_root(start: Path | None = None) -> Path:
    """Walk up from `start` (or CWD) to find directory containing `.insight-kit/`.

    Raises FileNotFoundError if not found. Caller should `init` before first Run.
    """
    p = (start or Path.cwd()).resolve()
    for candidate in (p, *p.parents):
        if (candidate / KIT_DIR_NAME).is_dir():
            return candidate
    raise FileNotFoundError(
        f"No {KIT_DIR_NAME}/ found above {p}. Run `ik init` to scaffold a project."
    )


def kit_dir(start: Path | None = None) -> Path:
    """Return the `.insight-kit/` dir itself."""
    return find_kit_root(start) / KIT_DIR_NAME


def runs_dir(start: Path | None = None) -> Path:
    """Resolve runs dir from config.yaml or default to `.insight-kit/runs/`."""
    cfg = kit_config(start)
    custom = cfg.get("runs_dir")
    if custom:
        return Path(custom).expanduser().resolve()
    d = kit_dir(start) / DEFAULT_RUNS_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def duckdb_path(start: Path | None = None) -> Path:
    """Project-local duckdb file."""
    cfg = kit_config(start)
    custom = cfg.get("duckdb_path")
    if custom:
        return Path(custom).expanduser().resolve()
    d = kit_dir(start) / DEFAULT_DUCKDB_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d / "insights.duckdb"


@lru_cache(maxsize=1)
def kit_config(start: Path | None = None) -> dict[str, Any]:
    """Load `.insight-kit/config.yaml`. Empty dict if missing.

    Lazily merges secrets from secrets.local.yaml under the ``"secrets"`` key.
    """
    cfg_path = kit_dir(start) / "config.yaml"
    cfg: dict[str, Any] = {}
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text()) or {}

    # Lazy secrets merge — import here to avoid circular imports at module load
    try:
        from insight_kit.config import load_secrets
        root = find_kit_root(start)
        cfg["secrets"] = load_secrets(root)
    except Exception:
        cfg.setdefault("secrets", {})

    return cfg


def init_kit(root: Path, namespace: str, force: bool = False) -> Path:
    """Scaffold a `.insight-kit/` directory in `root`.

    Returns path to the created directory.
    """
    from insight_kit import __version__

    root = root.resolve()
    target = root / KIT_DIR_NAME
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists. Pass force=True to overwrite.")

    for sub in ("runs", "duckdb", "goals", "prompts", "templates"):
        (target / sub).mkdir(parents=True, exist_ok=True)

    # Load existing config to preserve extra keys when force=True
    cfg_path = target / "config.yaml"
    existing_cfg: dict[str, Any] = {}
    if cfg_path.exists():
        existing_cfg = yaml.safe_load(cfg_path.read_text()) or {}

    existing_cfg["namespace"] = namespace
    existing_cfg["kit_version"] = __version__

    # Write config preserving extra keys; ensure runs_dir comment on fresh init
    cfg_lines = yaml.dump(existing_cfg, default_flow_style=False, sort_keys=False)
    if "runs_dir" not in existing_cfg:
        cfg_lines += "# runs_dir: /custom/path  # uncomment to override\n"
    cfg_path.write_text(cfg_lines)

    (target / "agents.yaml").write_text(
        "version: 1\n"
        "defaults:\n"
        "  role: agent\n"
        "agents: {}\n"
    )
    (target / "claims_registry.yaml").write_text(
        f"namespace: {namespace}\n"
        f"# prefix claim_ids with: {namespace.upper()}-<TIER>-<NUM>\n"
    )
    (target / "goals" / "open_queue.jsonl").touch()
    (target / "goals" / "closed.jsonl").touch()

    # Write bootstrap marker
    skills_dir_env = os.environ.get("CLAUDE_SKILLS_DIR")
    skills_dir = skills_dir_env or str(Path("~/.claude/skills").expanduser())
    agents_skills = root.parent / ".agents" / "skills"
    skills_count = len(list(agents_skills.iterdir())) if agents_skills.is_dir() else 0

    marker_data = {
        "timestamp": datetime.now(UTC).isoformat(),
        "kit_version": __version__,
        "skills_count": skills_count,
        "skills_dir": skills_dir,
    }
    (target / BOOTSTRAP_MARKER).write_text(json.dumps(marker_data, indent=2))

    # Cache invalidation — root/config may have changed
    find_kit_root.cache_clear()
    kit_config.cache_clear()

    return target


def bootstrap_marker(kit_root: Path) -> dict | None:
    """Read and return the .bootstrap-complete marker as a dict, or None if missing."""
    marker_path = kit_root / KIT_DIR_NAME / BOOTSTRAP_MARKER
    if not marker_path.exists():
        return None
    try:
        return json.loads(marker_path.read_text())
    except Exception:
        return None


def bootstrap_is_stale(kit_root: Path, current_version: str) -> bool:
    """Return True if the marker's kit_version differs in major/minor from current_version."""
    marker = bootstrap_marker(kit_root)
    if marker is None:
        return True
    marker_ver = marker.get("kit_version", "")

    def _maj_min(v: str) -> tuple[int, int]:
        parts = v.lstrip("v").split(".")
        try:
            return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            return (-1, -1)

    return _maj_min(marker_ver) != _maj_min(current_version)


def check_kit_version_drift(start: Path | None = None) -> None:
    """Compare config.yaml kit_version against the installed insight_kit.__version__.

    Raises ConfigError on a major-version mismatch (migration required).
    Emits a DeprecationWarning on a minor mismatch, a UserWarning when kit_version
    is absent, and is silent on a patch-only difference.

    Cutover note (T25): this kit-config guard previously lived inline in the
    legacy ``Run.__init__``. The legacy ``Run`` is deleted (C13); the guard is a
    pure config check and belongs with kit-root discovery, so it moved here.
    Gate callers wiring up a RunState should invoke this once at run start.
    """
    import warnings

    from insight_kit import __version__ as current
    from insight_kit.errors import ConfigError

    cfg = kit_config(start)
    cfg_ver: str | None = cfg.get("kit_version")

    if not cfg_ver:
        warnings.warn(
            "kit_version absent from config.yaml; pre-0.1.0 kit. "
            "Re-run init_kit to stamp.",
            UserWarning,
            stacklevel=2,
        )
        return

    def _parts(v: str) -> tuple[int, int]:
        """Return (major, minor) parsed from a semver-ish string."""
        clean = v.lstrip("v")
        pieces = clean.split(".", 2)
        try:
            major = int(pieces[0]) if len(pieces) > 0 else 0
            minor = (
                int(pieces[1].split("a")[0].split("b")[0].split("rc")[0])
                if len(pieces) > 1
                else 0
            )
        except ValueError:
            major, minor = 0, 0
        return major, minor

    cfg_maj, cfg_min = _parts(cfg_ver)
    cur_maj, cur_min = _parts(current)

    if cfg_maj != cur_maj:
        raise ConfigError(
            f"kit_version major mismatch: kit was init'd with {cfg_ver}, "
            f"current insight_kit is {current}. Migration required."
        )
    if cfg_min != cur_min:
        warnings.warn(
            f"kit_version minor mismatch: config has {cfg_ver}, "
            f"current insight_kit is {current}. Consider re-running init_kit.",
            DeprecationWarning,
            stacklevel=2,
        )
    # patch-only difference: silent

"""Kit root discovery — walks up from CWD to find `.insight-kit/`.

Replaces the parents[3] anti-pattern. Works regardless of where caller script lives.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

KIT_DIR_NAME = ".insight-kit"
DEFAULT_RUNS_SUBDIR = "runs"
DEFAULT_DUCKDB_SUBDIR = "duckdb"


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
    """Load `.insight-kit/config.yaml`. Empty dict if missing."""
    cfg_path = kit_dir(start) / "config.yaml"
    if not cfg_path.exists():
        return {}
    return yaml.safe_load(cfg_path.read_text()) or {}


def init_kit(root: Path, namespace: str, force: bool = False) -> Path:
    """Scaffold a `.insight-kit/` directory in `root`.

    Returns path to the created directory.
    """
    root = root.resolve()
    target = root / KIT_DIR_NAME
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists. Pass force=True to overwrite.")

    for sub in ("runs", "duckdb", "goals", "prompts", "templates"):
        (target / sub).mkdir(parents=True, exist_ok=True)

    (target / "config.yaml").write_text(
        f"namespace: {namespace}\n"
        f"kit_version: 0.1.0a0\n"
        f"# runs_dir: /custom/path  # uncomment to override\n"
    )
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

    # Cache invalidation — root/config may have changed
    find_kit_root.cache_clear()
    kit_config.cache_clear()

    return target

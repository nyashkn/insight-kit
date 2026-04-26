"""insight-kit bundled static assets.

Provides helpers to locate shipped assets (Evidence Svelte components, etc.)
so downstream projects can copy or symlink them without knowing the install path.
"""
from __future__ import annotations

from pathlib import Path

_ASSETS_DIR = Path(__file__).parent


def components_dir() -> Path:
    """Return the absolute path to the bundled Evidence Svelte components directory.

    Downstream projects can copy or symlink this directory into their Evidence
    ``reports/components/`` folder to get ClaimBlock, ClaimInline, ClaimDelta,
    and claimsManifest.

    Example::

        from insight_kit.assets import components_dir
        import shutil, pathlib

        dest = pathlib.Path("reports/components")
        shutil.copytree(components_dir(), dest, dirs_exist_ok=True)
    """
    return _ASSETS_DIR / "components"

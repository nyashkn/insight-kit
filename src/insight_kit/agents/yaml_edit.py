"""Round-trip YAML editing for config.yaml.

Uses ruamel.yaml if available (preserves comments/order), falls back to pyyaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Try ruamel.yaml first for comment-preserving round-trip
try:
    from ruamel.yaml import YAML as _RuamelYAML  # noqa: N811  # optional dep, alias for None-fallback

    _HAS_RUAMEL = True
except ImportError:
    _RuamelYAML = None  # type: ignore[assignment,misc]
    _HAS_RUAMEL = False


def load_yaml_roundtrip(path: Path) -> tuple[Any, Any]:
    """Load YAML preserving comments if ruamel is available.

    Returns:
        (data, loader) — loader is the YAML instance (ruamel) or None (pyyaml).
    """
    if _HAS_RUAMEL:
        ry = _RuamelYAML()
        ry.preserve_quotes = True
        with open(path) as f:
            data = ry.load(f)
        return data, ry
    else:
        import yaml

        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return data, None


def save_yaml_roundtrip(path: Path, data: Any, loader: Any) -> None:
    """Write YAML back to file.

    Args:
        path: Destination file.
        data: Data as returned from load_yaml_roundtrip.
        loader: The loader returned from load_yaml_roundtrip.
    """
    if loader is not None:
        # ruamel.yaml instance
        with open(path, "w") as f:
            loader.dump(data, f)
    else:
        import yaml

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

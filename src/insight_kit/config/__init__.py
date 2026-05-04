"""insight-kit config helpers — secrets loader."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from insight_kit.errors import ConfigError

_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def load_secrets(kit_root: Path) -> dict[str, str]:
    """Merge .insight-kit/secrets.local.yaml + os.environ. Env wins.

    Only keys present in the YAML are eligible for env overlay. Validates
    that all YAML keys match ``^[A-Z_][A-Z0-9_]*$``.

    Returns a plain ``dict[str, str]``.
    """
    secrets_path = kit_root / ".insight-kit" / "secrets.local.yaml"
    base: dict[str, str] = {}

    if secrets_path.exists():
        raw = yaml.safe_load(secrets_path.read_text()) or {}
        bad = [k for k in raw if not _KEY_RE.match(str(k))]
        if bad:
            raise ConfigError(
                f"secrets.local.yaml has invalid key(s): {bad!r}. "
                "Keys must match ^[A-Z_][A-Z0-9_]*$"
            )
        base = {k: str(v) for k, v in raw.items()}

    # Overlay env vars for keys declared in YAML
    merged = dict(base)
    for k in base:
        if k in os.environ:
            merged[k] = os.environ[k]

    return merged

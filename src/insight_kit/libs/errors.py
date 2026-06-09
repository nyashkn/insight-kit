"""insight-kit domain exceptions."""

from __future__ import annotations


class ConfigError(Exception):
    """Raised for configuration problems (version mismatch, bad secrets keys, etc.)."""

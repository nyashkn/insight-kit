"""Agents configuration loader and validator."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml


class ConfigError(Exception):
    """Raised when config validation fails."""

    pass


@dataclass
class SkillsConfig:
    """Skills configuration section."""

    local: list[str]
    global_: list[str]
    domain_bundles: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillsConfig":
        """Create from dictionary."""
        return cls(
            local=data.get("local", []),
            global_=data.get("global", []),
            domain_bundles=data.get("domain_bundles", []),
        )


@dataclass
class CouncilConfig:
    """Council configuration section."""

    required: int
    source: str
    members: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CouncilConfig":
        """Create from dictionary."""
        return cls(
            required=data.get("required", 0),
            source=data.get("source", ""),
            members=data.get("members", []),
        )


@dataclass
class BootstrapConfig:
    """Bootstrap configuration section."""

    on_init: bool
    symlink_to_user: bool
    pull_missing_council: bool
    fail_on_missing_global: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BootstrapConfig":
        """Create from dictionary."""
        return cls(
            on_init=data.get("on_init", True),
            symlink_to_user=data.get("symlink_to_user", True),
            pull_missing_council=data.get("pull_missing_council", True),
            fail_on_missing_global=data.get("fail_on_missing_global", False),
        )


@dataclass
class AgentsConfig:
    """Top-level agents configuration."""

    version: int
    project: str
    roles: list[str]
    personas: list[str]
    skills: SkillsConfig
    council: CouncilConfig
    bootstrap: BootstrapConfig

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentsConfig":
        """Create from dictionary."""
        return cls(
            version=data.get("version", 1),
            project=data.get("project", ""),
            roles=data.get("roles", []),
            personas=data.get("personas", []),
            skills=SkillsConfig.from_dict(data.get("skills", {})),
            council=CouncilConfig.from_dict(data.get("council", {})),
            bootstrap=BootstrapConfig.from_dict(data.get("bootstrap", {})),
        )


def validate_config(data: dict[str, Any], schema_path: Path) -> None:
    """Validate config dict against JSON Schema.

    Args:
        data: Configuration dictionary.
        schema_path: Path to JSON Schema file.

    Raises:
        ConfigError: If validation fails.
    """
    try:
        with open(schema_path) as f:
            schema = yaml.safe_load(f) or {}

        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        path_str = " -> ".join(str(p) for p in e.absolute_path) or "root"
        raise ConfigError(
            f"Config validation failed at '{path_str}': {e.message}"
        ) from e
    except Exception as e:
        raise ConfigError(f"Config validation error: {e}") from e


def load_config(
    path: Path = Path(".agents/config.yaml"),
) -> AgentsConfig:
    """Load and validate agents configuration.

    Args:
        path: Path to config.yaml (default: .agents/config.yaml).

    Returns:
        Parsed and validated AgentsConfig instance.

    Raises:
        ConfigError: If config is missing, unparseable, or invalid.
    """
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    try:
        with open(path) as f:
            raw_data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse YAML: {e}") from e

    # Validate against schema
    schema_path = path.parent / "config.schema.json"
    validate_config(raw_data, schema_path)

    # Convert to typed dataclass
    return AgentsConfig.from_dict(raw_data)

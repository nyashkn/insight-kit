"""Tests for agents config loader and validator."""

import json
from pathlib import Path

import pytest

from insight_kit.agents.config import AgentsConfig, ConfigError, load_config


@pytest.fixture
def config_dir(tmp_path):
    """Create temporary .agents directory with schema."""
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()

    # Copy schema
    schema_path = agents_dir / "config.schema.json"
    project_schema = (
        Path(__file__).parent.parent / ".agents" / "config.schema.json"
    )
    if project_schema.exists():
        schema_path.write_text(project_schema.read_text())

    return agents_dir


@pytest.fixture
def canonical_config_path():
    """Path to the canonical config in the project."""
    return Path(__file__).parent.parent / ".agents" / "config.yaml"


class TestLoadCanonical:
    """Test loading the canonical config."""

    def test_loads_canonical(self, canonical_config_path):
        """The canonical config.yaml parses and validates."""
        if not canonical_config_path.exists():
            pytest.skip("Canonical config not found")

        config = load_config(canonical_config_path)
        assert isinstance(config, AgentsConfig)
        assert config.version == 1
        assert config.project == "insight-kit"
        assert "data-engineer" in config.roles
        assert "operator" in config.roles


class TestProjectField:
    """Test project field validation."""

    def test_rejects_missing_project(self, config_dir):
        """Config without 'project' field raises ConfigError."""
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            """
version: 1
roles: [data-engineer]
personas: []
skills:
  local: []
  global: []
  domain_bundles: []
council:
  required: 18
  source: https://example.com
  members: []
bootstrap:
  on_init: true
  symlink_to_user: true
  pull_missing_council: true
  fail_on_missing_global: false
"""
        )

        with pytest.raises(ConfigError):
            load_config(config_file)


class TestRoleValidation:
    """Test role validation."""

    def test_rejects_unknown_role(self, config_dir):
        """Config with invalid role raises ConfigError."""
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            """
version: 1
project: test-project
roles: [invalid-role]
personas: []
skills:
  local: []
  global: []
  domain_bundles: []
council:
  required: 18
  source: https://example.com
  members: []
bootstrap:
  on_init: true
  symlink_to_user: true
  pull_missing_council: true
  fail_on_missing_global: false
"""
        )

        with pytest.raises(ConfigError):
            load_config(config_file)


class TestCouncilValidation:
    """Test council member validation."""

    def test_council_member_count(self, config_dir):
        """Council with 18 members and required=18 validates OK."""
        members = [
            "ada",
            "aristotle",
            "aurelius",
            "feynman",
            "kahneman",
            "karpathy",
            "lao-tzu",
            "machiavelli",
            "meadows",
            "munger",
            "musashi",
            "rams",
            "socrates",
            "sun-tzu",
            "sutskever",
            "taleb",
            "torvalds",
            "watts",
        ]

        config_file = config_dir / "config.yaml"
        config_file.write_text(
            f"""
version: 1
project: test-project
roles: [data-engineer]
personas: []
skills:
  local: []
  global: []
  domain_bundles: []
council:
  required: 18
  source: https://example.com
  members: {json.dumps(members)}
bootstrap:
  on_init: true
  symlink_to_user: true
  pull_missing_council: true
  fail_on_missing_global: false
"""
        )

        config = load_config(config_file)
        assert config.council.required == 18
        assert len(config.council.members) == 18

    def test_council_count_mismatch_allowed(self, config_dir):
        """Council with 5 members and required=18 still validates (no count enforcement)."""
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            """
version: 1
project: test-project
roles: [data-engineer]
personas: []
skills:
  local: []
  global: []
  domain_bundles: []
council:
  required: 18
  source: https://example.com
  members: [alice, bob, charlie, dana, eve]
bootstrap:
  on_init: true
  symlink_to_user: true
  pull_missing_council: true
  fail_on_missing_global: false
"""
        )

        # Should not raise
        config = load_config(config_file)
        assert config.council.required == 18
        assert len(config.council.members) == 5


class TestSkillsValidation:
    """Test skills configuration."""

    def test_accepts_local_and_global_skills(self, config_dir):
        """Skills with local and global arrays validate."""
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            """
version: 1
project: test-project
roles: [data-engineer]
personas: []
skills:
  local: [skill-a, skill-b]
  global: [skill-x, skill-y]
  domain_bundles: []
council:
  required: 0
  source: https://example.com
  members: []
bootstrap:
  on_init: true
  symlink_to_user: true
  pull_missing_council: true
  fail_on_missing_global: false
"""
        )

        config = load_config(config_file)
        assert config.skills.local == ["skill-a", "skill-b"]
        assert config.skills.global_ == ["skill-x", "skill-y"]


class TestBootstrapValidation:
    """Test bootstrap configuration."""

    def test_bootstrap_flags(self, config_dir):
        """Bootstrap flags are correctly parsed."""
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            """
version: 1
project: test-project
roles: [data-engineer]
personas: []
skills:
  local: []
  global: []
  domain_bundles: []
council:
  required: 0
  source: https://example.com
  members: []
bootstrap:
  on_init: false
  symlink_to_user: false
  pull_missing_council: false
  fail_on_missing_global: true
"""
        )

        config = load_config(config_file)
        assert config.bootstrap.on_init is False
        assert config.bootstrap.symlink_to_user is False
        assert config.bootstrap.pull_missing_council is False
        assert config.bootstrap.fail_on_missing_global is True

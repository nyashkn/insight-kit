"""Tests for agents config loader and validator."""

import json
from pathlib import Path

import pytest

from insight_kit.integrations.agents.config import AgentsConfig, ConfigError, load_config


@pytest.fixture
def config_dir(tmp_path):
    """Create temporary .agents directory with schema."""
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()

    # Copy schema
    schema_path = agents_dir / "config.schema.json"
    project_schema = (
        Path(__file__).parent.parent.parent / ".agents" / "config.schema.json"
    )
    if project_schema.exists():
        schema_path.write_text(project_schema.read_text())

    return agents_dir


@pytest.fixture
def canonical_config_path():
    """Path to the canonical config in the project."""
    return Path(__file__).parent.parent.parent / ".agents" / "config.yaml"


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


class TestDefaultRoleFor:
    """Test default_role_for routing block."""

    _base_yaml = """
version: 1
project: test-project
roles: [data-engineer, analyst, researcher, critic, renderer, evaluator, operator]
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
  on_init: true
  symlink_to_user: true
  pull_missing_council: true
  fail_on_missing_global: false
"""

    def test_parses_correctly_when_present(self, config_dir):
        """default_role_for is parsed and returned when present."""
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            self._base_yaml
            + """
default_role_for:
  ingest: data-engineer
  analysis: analyst
  visualization: renderer
  validation: critic
  evaluation: evaluator
  orchestration: operator
  hypothesis: researcher
"""
        )

        config = load_config(config_file)
        assert config.default_role_for is not None
        assert config.default_role_for["ingest"] == "data-engineer"
        assert config.default_role_for["analysis"] == "analyst"
        assert config.default_role_for["visualization"] == "renderer"
        assert config.default_role_for["validation"] == "critic"
        assert config.default_role_for["evaluation"] == "evaluator"
        assert config.default_role_for["orchestration"] == "operator"
        assert config.default_role_for["hypothesis"] == "researcher"

    def test_accepts_none_when_absent(self, config_dir):
        """default_role_for is None when not present in config."""
        config_file = config_dir / "config.yaml"
        config_file.write_text(self._base_yaml)

        config = load_config(config_file)
        assert config.default_role_for is None

    def test_raises_when_value_not_in_configured_roles(self, config_dir):
        """Raises ConfigError when a role value is not in the project roles list."""
        config_file = config_dir / "config.yaml"
        # Only data-engineer is in roles, but we try to map to analyst
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
  on_init: true
  symlink_to_user: true
  pull_missing_council: true
  fail_on_missing_global: false
default_role_for:
  analysis: analyst
"""
        )

        with pytest.raises(ConfigError, match="default_role_for"):
            load_config(config_file)

    def test_raises_when_value_is_not_a_valid_role_enum(self, config_dir):
        """Raises ConfigError when value is not one of the 7 canonical role names."""
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            self._base_yaml
            + """
default_role_for:
  ingest: not-a-real-role
"""
        )

        with pytest.raises(ConfigError):
            load_config(config_file)

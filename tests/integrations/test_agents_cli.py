"""Tests for `ik agents` CLI subcommands."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CANONICAL_CONFIG = Path(__file__).parent.parent.parent / ".agents" / "config.yaml"
CANONICAL_SCHEMA = Path(__file__).parent.parent.parent / ".agents" / "config.schema.json"
CANONICAL_TEMPLATE = (
    Path(__file__).parent.parent.parent / ".agents" / "personas" / "_template" / "persona.md"
)

COUNCIL_MEMBERS = [
    "ada", "aristotle", "aurelius", "feynman", "kahneman", "karpathy",
    "lao-tzu", "machiavelli", "meadows", "munger", "musashi", "rams",
    "socrates", "sun-tzu", "sutskever", "taleb", "torvalds", "watts",
]

MINIMAL_CONFIG_TEMPLATE = """\
version: 1
project: test-project
roles:
  - data-engineer
  - operator
personas: []
skills:
  local: []
  global: []
  domain_bundles: []
council:
  required: 0
  source: https://example.com/council
  members: []
bootstrap:
  on_init: true
  symlink_to_user: false
  pull_missing_council: false
  fail_on_missing_global: false
"""


def make_agents_dir(tmp_path: Path, extra_yaml: str = "") -> tuple[Path, Path]:
    """Create a .agents/ directory with config + schema in tmp_path.

    Returns (agents_dir, config_path).
    """
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    schema_dst = agents_dir / "config.schema.json"
    if CANONICAL_SCHEMA.exists():
        schema_dst.write_text(CANONICAL_SCHEMA.read_text())

    config_content = MINIMAL_CONFIG_TEMPLATE + extra_yaml
    config_path = agents_dir / "config.yaml"
    config_path.write_text(config_content)
    return agents_dir, config_path


def _monkeypatch_claude_dirs(monkeypatch, tmp_path: Path):
    """Redirect ~/.claude/ to a tmp location so tests don't touch the real one."""
    fake_claude = tmp_path / "fake_claude"
    (fake_claude / "agents").mkdir(parents=True)
    (fake_claude / "skills").mkdir(parents=True)

    from insight_kit.integrations.agents import bootstrap as bs

    monkeypatch.setattr(bs, "CLAUDE_DIR", fake_claude)
    return fake_claude


# ---------------------------------------------------------------------------
# test_check_passes_canonical
# ---------------------------------------------------------------------------


def test_check_passes_canonical(monkeypatch, tmp_path):
    """Running `ik agents check --dry-run` on canonical config exits 0.

    The canonical config has pull_missing_council=true but `check` never clones.
    We redirect ~/.claude/ and pre-seed enough state to satisfy required=18.
    """
    if not CANONICAL_CONFIG.exists():
        pytest.skip("canonical config not found")

    fake_claude = _monkeypatch_claude_dirs(monkeypatch, tmp_path)

    # Pre-create all 18 council member files so check passes the council gate
    agents_dir = fake_claude / "agents"
    for member in COUNCIL_MEMBERS:
        (agents_dir / f"council-{member}.md").write_text(f"# {member}\n")

    # Pre-create global skills referenced in canonical config
    skills_dir = fake_claude / "skills"
    canonical_globals = ["evidence-dev", "evidence-dashboards", "agent-browser", "council", "create-skill"]
    for skill in canonical_globals:
        (skills_dir / skill).mkdir(parents=True, exist_ok=True)

    # Symlink targets: pre-create all local skill + agent dirs
    # The check cmd compares .agents/skills/* → ~/.claude/skills/*
    # We pre-seed the symlinks/dirs so check sees them as present
    repo_root = CANONICAL_CONFIG.parent.parent
    skills_src = repo_root / ".agents" / "skills"
    if skills_src.exists():
        for sd in skills_src.iterdir():
            if sd.is_dir():
                link = skills_dir / sd.name
                if not link.exists():
                    link.mkdir(parents=True, exist_ok=True)

    agents_src = repo_root / ".agents" / "agents"
    if agents_src.exists():
        for ad in agents_src.iterdir():
            if ad.is_dir():
                link = agents_dir / ad.name
                if not link.exists():
                    link.mkdir(parents=True, exist_ok=True)

    from insight_kit.surfaces.cli.__main__ import main

    rc = main(["agents", "check", "--config", str(CANONICAL_CONFIG)])
    assert rc == 0


# ---------------------------------------------------------------------------
# test_add_role_appends
# ---------------------------------------------------------------------------


def test_add_role_appends(monkeypatch, tmp_path):
    """`ik agents add analyst` mutates config + creates dir; re-run errors."""
    _agents_dir, config_path = make_agents_dir(tmp_path)
    _monkeypatch_claude_dirs(monkeypatch, tmp_path)

    from insight_kit.surfaces.cli.__main__ import main

    rc = main(["agents", "add", "analyst", "--config", str(config_path)])
    assert rc == 0

    # Config should now list analyst
    data = yaml.safe_load(config_path.read_text())
    assert "analyst" in data["roles"]

    # AGENT.md should exist
    agent_md = tmp_path / ".agents" / "agents" / "analyst" / "AGENT.md"
    assert agent_md.exists()
    content = agent_md.read_text()
    assert "analyst" in content
    assert "## Mandate" in content

    # Second run should error (already present)
    rc2 = main(["agents", "add", "analyst", "--config", str(config_path)])
    assert rc2 != 0


# ---------------------------------------------------------------------------
# test_add_persona_scaffold
# ---------------------------------------------------------------------------


def test_add_persona_scaffold(monkeypatch, tmp_path):
    """`ik agents add-persona growth` copies template + updates frontmatter name."""
    if not CANONICAL_TEMPLATE.exists():
        pytest.skip("persona template not found")

    agents_dir, config_path = make_agents_dir(tmp_path)
    _monkeypatch_claude_dirs(monkeypatch, tmp_path)

    # Copy template into place
    template_dir = agents_dir / "personas" / "_template"
    template_dir.mkdir(parents=True)
    shutil.copy2(CANONICAL_TEMPLATE, template_dir / "persona.md")

    from insight_kit.surfaces.cli.__main__ import main

    rc = main(["agents", "add-persona", "growth", "--config", str(config_path)])
    assert rc == 0

    # Config should now list growth
    data = yaml.safe_load(config_path.read_text())
    assert "growth" in data["personas"]

    # persona.md should exist with updated name
    persona_md = agents_dir / "personas" / "growth" / "persona.md"
    assert persona_md.exists()
    content = persona_md.read_text()
    assert "name: growth" in content


# ---------------------------------------------------------------------------
# test_invalid_role_rejected
# ---------------------------------------------------------------------------


def test_invalid_role_rejected(monkeypatch, tmp_path):
    """`ik agents add foo` errors with non-zero exit."""
    _agents_dir, config_path = make_agents_dir(tmp_path)
    _monkeypatch_claude_dirs(monkeypatch, tmp_path)

    from insight_kit.surfaces.cli.__main__ import main

    rc = main(["agents", "add", "foo", "--config", str(config_path)])
    assert rc != 0


# ---------------------------------------------------------------------------
# test_bootstrap_dry_run
# ---------------------------------------------------------------------------


def test_bootstrap_dry_run(monkeypatch, tmp_path):
    """`ik agents bootstrap --dry-run` exits 0 and writes nothing."""
    _agents_dir, config_path = make_agents_dir(tmp_path)
    fake_claude = _monkeypatch_claude_dirs(monkeypatch, tmp_path)

    # No-op clone stub
    def _stub_clone(**kwargs):
        return 0

    from insight_kit.surfaces.cli.__main__ import main

    rc = main([
        "agents", "bootstrap", "--dry-run", "--config", str(config_path)
    ])
    assert rc == 0
    # No files should appear under fake_claude (dry-run)
    created = list(fake_claude.rglob("council-*.md"))
    assert created == []


# ---------------------------------------------------------------------------
# test_check_exits_1_on_missing_council
# ---------------------------------------------------------------------------


def test_check_exits_1_on_missing_council(monkeypatch, tmp_path):
    """check exits 1 when council count < required."""
    _agents_dir, config_path = make_agents_dir(tmp_path)
    # Override required to 1 so at least something is missing
    data = yaml.safe_load(config_path.read_text())
    data["council"]["required"] = 1
    config_path.write_text(yaml.dump(data, sort_keys=False))

    _monkeypatch_claude_dirs(monkeypatch, tmp_path)
    # Don't seed any council files → check should fail

    from insight_kit.surfaces.cli.__main__ import main

    rc = main(["agents", "check", "--config", str(config_path)])
    assert rc == 1


# ---------------------------------------------------------------------------
# test_pull_council_network (network — skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.network
def test_pull_council_network(monkeypatch, tmp_path):
    """pull-council actually clones from real source (slow / network)."""
    if not CANONICAL_CONFIG.exists():
        pytest.skip("canonical config not found")

    _monkeypatch_claude_dirs(monkeypatch, tmp_path)

    from insight_kit.surfaces.cli.__main__ import main

    rc = main(["agents", "pull-council", "--config", str(CANONICAL_CONFIG)])
    assert rc == 0

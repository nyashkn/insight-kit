"""CLI subcommands for `ik agents {bootstrap,check,add,add-persona,pull-council}`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bootstrap import (
    CANONICAL_ROLES,
    _clone_council,
    run_bootstrap,
    run_check,
)
from .config import ConfigError, load_config
from .yaml_edit import load_yaml_roundtrip, save_yaml_roundtrip

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGENT_STUB_TEMPLATE = """\
---
name: {role}
role: {role}
description: <one-line description of what this role does>
phase: <phase>
tier_produces: []
modes: []
metadata:
  last_verified: {today}
---

# {role}

## Mandate

<!-- What this role is responsible for. Be specific. -->

## Inputs

<!-- What data, artifacts, or signals this role consumes. -->

## Outputs

<!-- What this role produces. Format, tier, destination. -->

## Required skills

<!-- Skills that must be available for this role to function. -->

## Anti-Patterns

<!-- Common failure modes specific to this role. -->
"""


def _today_str() -> str:
    from datetime import date

    return date.today().isoformat()


def _find_repo_root(config_path: Path) -> Path:
    """Walk up from config_path to find the repo root (contains .agents/)."""
    return config_path.parent.parent.resolve()


def _resolve_config(path_str: str) -> Path:
    return Path(path_str).resolve()


# ---------------------------------------------------------------------------
# cmd_bootstrap
# ---------------------------------------------------------------------------


def cmd_agents_bootstrap(args: argparse.Namespace) -> int:
    """Bootstrap council + skills + symlinks per config."""
    config_path = _resolve_config(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    repo_root = _find_repo_root(config_path)
    dry_run: bool = args.dry_run

    if dry_run:
        print("[dry-run] no files will be written")

    clone_fn = getattr(args, "_clone_fn", None)  # injectable for tests
    kwargs = {}
    if clone_fn is not None:
        kwargs["_clone_fn"] = clone_fn

    try:
        run_bootstrap(
            config=config,
            repo_root=repo_root,
            dry_run=dry_run,
            force=getattr(args, "force", False),
            log=print,
            **kwargs,
        )
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    return 0


# ---------------------------------------------------------------------------
# cmd_check
# ---------------------------------------------------------------------------


def cmd_agents_check(args: argparse.Namespace) -> int:
    """Check environment against config; exit 1 if any required missing."""
    config_path = _resolve_config(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    repo_root = _find_repo_root(config_path)
    all_ok, deltas = run_check(config=config, repo_root=repo_root, log=print)

    if not all_ok:
        print(
            f"check failed: {len(deltas)} delta(s) found — run `ik agents bootstrap` to fix",
            file=sys.stderr,
        )
        return 1

    return 0


# ---------------------------------------------------------------------------
# cmd_add
# ---------------------------------------------------------------------------


def cmd_agents_add(args: argparse.Namespace) -> int:
    """Append role to config + scaffold .agents/agents/<role>/AGENT.md."""
    role: str = args.role.strip()

    if role not in CANONICAL_ROLES:
        print(
            f"error: '{role}' is not a canonical role.\n"
            f"  Valid roles: {', '.join(sorted(CANONICAL_ROLES))}",
            file=sys.stderr,
        )
        return 1

    config_path = _resolve_config(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if role in config.roles:
        print(f"error: role '{role}' already present in {config_path}", file=sys.stderr)
        return 1

    # Edit config.yaml
    data, loader = load_yaml_roundtrip(config_path)
    if "roles" not in data or data["roles"] is None:
        data["roles"] = []
    data["roles"].append(role)
    save_yaml_roundtrip(config_path, data, loader)
    print(f"[updated] {config_path}: added role '{role}'")

    # Re-validate
    try:
        load_config(config_path)
    except ConfigError as e:
        print(f"error: config re-validation failed after edit: {e}", file=sys.stderr)
        return 1

    # Scaffold .agents/agents/<role>/AGENT.md
    repo_root = _find_repo_root(config_path)
    agent_dir = repo_root / ".agents" / "agents" / role
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_md = agent_dir / "AGENT.md"
    if agent_md.exists():
        print(f"[skip] {agent_md} already exists")
    else:
        agent_md.write_text(
            _AGENT_STUB_TEMPLATE.format(role=role, today=_today_str())
        )
        print(f"[created] {agent_md}")

    return 0


# ---------------------------------------------------------------------------
# cmd_add_persona
# ---------------------------------------------------------------------------


def cmd_agents_add_persona(args: argparse.Namespace) -> int:
    """Append persona to config + scaffold .agents/personas/<name>/persona.md."""
    name: str = args.name.strip()

    config_path = _resolve_config(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if name in (config.personas or []):
        print(
            f"error: persona '{name}' already present in {config_path}",
            file=sys.stderr,
        )
        return 1

    repo_root = _find_repo_root(config_path)
    template_path = repo_root / ".agents" / "personas" / "_template" / "persona.md"
    if not template_path.exists():
        print(
            f"error: persona template not found: {template_path}\n"
            "  Create .agents/personas/_template/persona.md first.",
            file=sys.stderr,
        )
        return 1

    # Edit config.yaml
    data, loader = load_yaml_roundtrip(config_path)
    if "personas" not in data or data["personas"] is None:
        data["personas"] = []
    # Handle pyyaml rendering of `personas: []` as a Python list
    data["personas"].append(name)
    save_yaml_roundtrip(config_path, data, loader)
    print(f"[updated] {config_path}: added persona '{name}'")

    # Re-validate
    try:
        load_config(config_path)
    except ConfigError as e:
        print(f"error: config re-validation failed after edit: {e}", file=sys.stderr)
        return 1

    # Scaffold persona file
    persona_dir = repo_root / ".agents" / "personas" / name
    persona_dir.mkdir(parents=True, exist_ok=True)
    persona_md = persona_dir / "persona.md"
    if persona_md.exists():
        print(f"[skip] {persona_md} already exists")
    else:
        content = template_path.read_text()
        # Update frontmatter name: field
        content = content.replace("name: <name>", f"name: {name}", 1)
        persona_md.write_text(content)
        print(f"[created] {persona_md}")

    return 0


# ---------------------------------------------------------------------------
# cmd_pull_council
# ---------------------------------------------------------------------------


def cmd_agents_pull_council(args: argparse.Namespace) -> int:
    """Explicitly clone/refresh council member files."""
    config_path = _resolve_config(args.config)
    try:
        config = load_config(config_path)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    force: bool = args.force
    clone_fn = getattr(args, "_clone_fn", None) or _clone_council

    print(f"Pulling council from: {config.council.source}")
    try:
        copied = clone_fn(
            source=config.council.source,
            members=config.council.members,
            dry_run=False,
            log=print,
            force=force,
        )
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"Done: {copied} file(s) copied to ~/.claude/agents/")
    return 0


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def add_agents_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the `agents` top-level subcommand with its own subparsers."""
    p_agents = sub.add_parser("agents", help="manage agents system (bootstrap, check, add…)")
    agents_subs = p_agents.add_subparsers(dest="agents_cmd", required=True)

    # Shared --config argument
    def _add_config(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--config",
            default=".agents/config.yaml",
            metavar="PATH",
            help="path to agents config.yaml (default: .agents/config.yaml)",
        )

    # bootstrap
    p_bootstrap = agents_subs.add_parser(
        "bootstrap", help="ensure council + skills + symlinks per config"
    )
    _add_config(p_bootstrap)
    p_bootstrap.add_argument(
        "--dry-run",
        action="store_true",
        help="preview changes without writing anything",
    )
    p_bootstrap.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing council files",
    )
    p_bootstrap.set_defaults(func=cmd_agents_bootstrap)

    # check
    p_check = agents_subs.add_parser(
        "check",
        help="check environment against config; exit 1 if required items missing",
    )
    _add_config(p_check)
    p_check.set_defaults(func=cmd_agents_check)

    # add
    p_add = agents_subs.add_parser(
        "add", help="add a canonical role to config + scaffold AGENT.md"
    )
    _add_config(p_add)
    p_add.add_argument(
        "role",
        help=f"role to add ({', '.join(sorted(CANONICAL_ROLES))})",
    )
    p_add.set_defaults(func=cmd_agents_add)

    # add-persona
    p_add_persona = agents_subs.add_parser(
        "add-persona", help="add a persona to config + scaffold persona.md from template"
    )
    _add_config(p_add_persona)
    p_add_persona.add_argument("name", help="persona name (slug, e.g. retention)")
    p_add_persona.set_defaults(func=cmd_agents_add_persona)

    # pull-council
    p_pull = agents_subs.add_parser(
        "pull-council", help="clone/refresh council member files into ~/.claude/agents/"
    )
    _add_config(p_pull)
    p_pull.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing council files",
    )
    p_pull.set_defaults(func=cmd_agents_pull_council)

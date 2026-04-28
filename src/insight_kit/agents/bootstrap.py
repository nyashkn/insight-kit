"""Bootstrap logic for the agents system: council clone, skill checks, symlinks."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from .config import AgentsConfig, ConfigError

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

CANONICAL_ROLES = {
    "data-engineer",
    "analyst",
    "researcher",
    "critic",
    "renderer",
    "evaluator",
    "operator",
}

CLAUDE_DIR = Path.home() / ".claude"


def _claude_agents_dir() -> Path:
    return CLAUDE_DIR / "agents"


def _claude_skills_dir() -> Path:
    return CLAUDE_DIR / "skills"


def _count_council(members: list[str]) -> tuple[int, list[str]]:
    """Count how many council-<member>.md files exist in ~/.claude/agents/."""
    agents_dir = _claude_agents_dir()
    present = []
    for m in members:
        if (agents_dir / f"council-{m}.md").exists():
            present.append(m)
    return len(present), present


def _clone_council(
    source: str,
    members: list[str],
    dry_run: bool = False,
    log: Callable[[str], None] = print,
    force: bool = False,
) -> int:
    """Clone council repo and copy member files.

    Returns count of files copied.
    """
    agents_dir = _claude_agents_dir()
    copied = 0

    with tempfile.TemporaryDirectory(prefix="ik-council-") as tmpdir:
        log(f"  cloning council repo: {source}")
        if not dry_run:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", source, tmpdir],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise ConfigError(
                    f"Failed to clone council repo '{source}':\n{result.stderr}"
                )

        for member in members:
            src = Path(tmpdir) / f"{member}.md"
            dst = agents_dir / f"council-{member}.md"

            if dst.exists() and not force:
                log(f"  [skip] council-{member}.md already exists")
                continue

            if not dry_run and not src.exists():
                log(f"  [warn] {member}.md not found in repo — skipping")
                continue

            if dry_run:
                log(f"  [dry-run] would copy {member}.md → {dst}")
            else:
                agents_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                log(f"  [copied] council-{member}.md → {dst}")
            copied += 1

    return copied


def _check_global_skills(
    skills: list[str],
    fail_on_missing: bool,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Check that global skills exist in ~/.claude/skills/.

    Returns list of missing skill names.
    """
    skills_dir = _claude_skills_dir()
    missing = []
    for name in skills:
        skill_dir = skills_dir / name
        if not skill_dir.exists():
            missing.append(name)
            if fail_on_missing:
                raise ConfigError(
                    f"Required global skill missing: {skill_dir}\n"
                    f"  Fix: ensure ~/.claude/skills/{name}/ exists."
                )
            else:
                log(f"  [warn] global skill not found: ~/.claude/skills/{name}/")
    return missing


def _symlink_local_skills(
    repo_root: Path,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> int:
    """Symlink .agents/skills/<name>/ → ~/.claude/skills/<name>.

    Returns count of symlinks created.
    """
    skills_src = repo_root / ".agents" / "skills"
    if not skills_src.exists():
        return 0

    target_base = _claude_skills_dir()
    created = 0
    for skill_dir in sorted(skills_src.iterdir()):
        if not skill_dir.is_dir():
            continue
        link = target_base / skill_dir.name
        if link.exists() or link.is_symlink():
            log(f"  [skip] ~/.claude/skills/{skill_dir.name} already exists")
            continue
        if dry_run:
            log(f"  [dry-run] would symlink {link} → {skill_dir}")
        else:
            target_base.mkdir(parents=True, exist_ok=True)
            link.symlink_to(skill_dir.resolve())
            log(f"  [symlink] ~/.claude/skills/{skill_dir.name} → {skill_dir}")
        created += 1
    return created


def _symlink_local_agents(
    repo_root: Path,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> int:
    """Symlink .agents/agents/<name>/ → ~/.claude/agents/<name>.

    Returns count of symlinks created.
    """
    agents_src = repo_root / ".agents" / "agents"
    if not agents_src.exists():
        return 0

    target_base = _claude_agents_dir()
    created = 0
    for agent_dir in sorted(agents_src.iterdir()):
        if not agent_dir.is_dir():
            continue
        link = target_base / agent_dir.name
        if link.exists() or link.is_symlink():
            log(f"  [skip] ~/.claude/agents/{agent_dir.name} already exists")
            continue
        if dry_run:
            log(f"  [dry-run] would symlink {link} → {agent_dir}")
        else:
            target_base.mkdir(parents=True, exist_ok=True)
            link.symlink_to(agent_dir.resolve())
            log(f"  [symlink] ~/.claude/agents/{agent_dir.name} → {agent_dir}")
        created += 1
    return created


def run_bootstrap(
    config: AgentsConfig,
    repo_root: Path,
    dry_run: bool = False,
    force: bool = False,
    log: Callable[[str], None] = print,
    _clone_fn: Callable | None = None,
) -> dict:
    """Execute bootstrap steps.

    Args:
        config: Loaded AgentsConfig.
        repo_root: Repo root directory.
        dry_run: If True, preview only, no mutations.
        force: If True, overwrite existing council files.
        log: Callable for progress output.
        _clone_fn: Optional override for the clone function (used in tests).

    Returns:
        Summary dict with counts.
    """
    clone_fn = _clone_fn if _clone_fn is not None else _clone_council
    summary = {
        "council_present": 0,
        "council_copied": 0,
        "global_skills_missing": [],
        "skill_symlinks": 0,
        "agent_symlinks": 0,
    }

    # --- Council ---
    log("==> Council")
    present_count, present_members = _count_council(config.council.members)
    summary["council_present"] = present_count
    log(f"  present: {present_count}/{config.council.required} required")

    if present_count < config.council.required and config.bootstrap.pull_missing_council:
        missing_members = [m for m in config.council.members if m not in present_members]
        log(f"  pulling {len(missing_members)} missing member(s)...")
        try:
            copied = clone_fn(
                source=config.council.source,
                members=missing_members,
                dry_run=dry_run,
                log=log,
                force=force,
            )
            summary["council_copied"] = copied
        except ConfigError:
            raise
    elif present_count < config.council.required:
        log(
            f"  [warn] {config.council.required - present_count} council member(s) missing; "
            "pull_missing_council=false"
        )

    # --- Global skills ---
    log("==> Global skills")
    missing = _check_global_skills(
        config.skills.global_,
        fail_on_missing=config.bootstrap.fail_on_missing_global,
        dry_run=dry_run,
        log=log,
    )
    summary["global_skills_missing"] = missing
    if not missing:
        log(f"  ok: all {len(config.skills.global_)} global skill(s) present")

    # --- Symlinks ---
    if config.bootstrap.symlink_to_user:
        log("==> Local skill symlinks")
        summary["skill_symlinks"] = _symlink_local_skills(
            repo_root, dry_run=dry_run, log=log
        )

        log("==> Local agent symlinks")
        summary["agent_symlinks"] = _symlink_local_agents(
            repo_root, dry_run=dry_run, log=log
        )
    else:
        log("==> Symlinks skipped (symlink_to_user=false)")

    # --- Summary ---
    log("==> Done")
    mode = "[DRY-RUN] " if dry_run else ""
    log(
        f"  {mode}council: {summary['council_present']} present, "
        f"{summary['council_copied']} copied | "
        f"global missing: {len(summary['global_skills_missing'])} | "
        f"symlinks: {summary['skill_symlinks']} skills, {summary['agent_symlinks']} agents"
    )

    return summary


def run_check(
    config: AgentsConfig,
    repo_root: Path,
    log: Callable[[str], None] = print,
) -> tuple[bool, list[str]]:
    """Check environment against config without making mutations.

    Returns:
        (all_ok, list_of_delta_messages)
    """
    deltas: list[str] = []

    # Council
    present_count, _ = _count_council(config.council.members)
    if present_count < config.council.required:
        deltas.append(
            f"council: {present_count}/{config.council.required} present "
            f"— missing {config.council.required - present_count}"
        )

    # Global skills
    skills_dir = _claude_skills_dir()
    for name in config.skills.global_:
        if not (skills_dir / name).exists():
            deltas.append(f"global skill missing: ~/.claude/skills/{name}/")

    # Local skill symlinks
    skills_src = repo_root / ".agents" / "skills"
    if skills_src.exists():
        for skill_dir in sorted(skills_src.iterdir()):
            if skill_dir.is_dir():
                link = _claude_skills_dir() / skill_dir.name
                if not link.exists() and not link.is_symlink():
                    deltas.append(
                        f"skill symlink missing: ~/.claude/skills/{skill_dir.name}"
                    )

    # Local agent symlinks
    agents_src = repo_root / ".agents" / "agents"
    if agents_src.exists():
        for agent_dir in sorted(agents_src.iterdir()):
            if agent_dir.is_dir():
                link = _claude_agents_dir() / agent_dir.name
                if not link.exists() and not link.is_symlink():
                    deltas.append(
                        f"agent symlink missing: ~/.claude/agents/{agent_dir.name}"
                    )

    all_ok = len(deltas) == 0
    if all_ok:
        log("ok: environment matches config")
    else:
        for d in deltas:
            log(f"  [delta] {d}")

    return all_ok, deltas

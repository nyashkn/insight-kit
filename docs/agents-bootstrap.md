# Agents Bootstrap

**Operational runbook** (previously a SKILL). Follow this procedure to bootstrap the insight-kit agent council from scratch on a new machine or CI runner.

## Purpose

A fresh machine or CI runner has no skills symlinked and no council config. This runbook covers the full cold-start sequence: cloning the council repo, checking that the required global skills are discoverable, symlinking the project-local skills from `.agents/skills/`, and confirming that `config.yaml` resolves correctly so the first `Run` does not fail with `FileNotFoundError: No .insight-kit/ found`.

## When to invoke

- First setup on a new developer machine.
- CI runner bootstrap (before any `uv run pytest` or `bun run` command).
- After cloning the insight-kit repo on a machine that has never run it.
- When `/find-skills` returns missing skills that should be present.
- When `Run(topic=...)` fails with `FileNotFoundError: No .insight-kit/ found above ...`.

## Prerequisites

- Git is installed and `git clone` works.
- Python >= 3.11 is available (check: `python3 --version`).
- `uv` is installed (check: `uv --version`; install via `curl -LsSf https://astral.sh/uv/install.sh | sh`).
- Bun is installed (check: `bun --version`; install via `curl -fsSL https://bun.sh/install | bash`).
- `~/.claude/skills/` directory exists (Claude Code creates it on first run).

## Procedure

### Step 1: Clone the council repo

```bash
COUNCIL_DIR="$HOME/.claude/council-of-high-intelligence"
if [ ! -d "$COUNCIL_DIR" ]; then
  git clone https://github.com/0xNyk/council-of-high-intelligence.git "$COUNCIL_DIR"
  echo "Council cloned to $COUNCIL_DIR"
else
  echo "Council already present at $COUNCIL_DIR — pulling latest"
  git -C "$COUNCIL_DIR" pull --ff-only
fi
```

### Step 2: Check global skills directory

```bash
SKILLS_DIR="$HOME/.claude/skills"
mkdir -p "$SKILLS_DIR"
ls "$SKILLS_DIR"
```

If the council ships global skills, symlink them:

```bash
for d in "$COUNCIL_DIR"/skills/*/; do
  skill_name="$(basename "$d")"
  TARGET="$SKILLS_DIR/$skill_name"
  if [ ! -e "$TARGET" ]; then
    ln -s "$(realpath "$d")" "$TARGET"
    echo "Linked global skill: $skill_name"
  else
    echo "Skill already present: $skill_name"
  fi
done
```

### Step 3: Symlink project-local skills

```bash
REPO_DIR="/path/to/insight-kit"   # adjust to actual repo path
cd "$REPO_DIR"

for d in .agents/skills/*/; do
  skill_name="$(basename "$d")"
  TARGET="$SKILLS_DIR/$skill_name"
  SOURCE="$(realpath "$d")"
  if [ -e "$TARGET" ] && [ "$(readlink "$TARGET")" = "$SOURCE" ]; then
    echo "Already linked: $skill_name"
  elif [ -e "$TARGET" ]; then
    echo "WARNING: $skill_name already exists at $TARGET — skipping (resolve conflict manually)"
  else
    ln -s "$SOURCE" "$TARGET"
    echo "Linked project skill: $skill_name"
  fi
done
```

This is the same loop documented in `.agents/SETUP.md`. It is safe to run multiple times.

### Step 4: Verify skills are discoverable

```bash
ls ~/.claude/skills/ | sort
# Expected: agents-bootstrap, agent-browser-verify, bun-monorepo-setup,
#           citation-hygiene, claim-authoring, eval-protocol, evidence-page-creation,
#           glossary-management, goal-management, ingest-flow, layer-a-validation,
#           preflight, schema-drift, viz-evidence-authoring
```

In Claude Code, run `/find-skills` to refresh the skills cache and confirm the list.

### Step 5: Initialize the kit root in the project

If `.insight-kit/` does not exist:

```bash
cd "$REPO_DIR"
uv run python -c "
from insight_kit.provenance.root import init_kit, find_kit_root
from pathlib import Path
init_kit(Path('.'), namespace='NMK')
print('Kit initialized:', find_kit_root())
"
```

If it already exists:
```bash
cat .insight-kit/config.yaml
# Must show: namespace: NMK (or project namespace)
```

### Step 6: Resolve config.yaml — algorithm

`find_kit_root` walks up from the given `start` path (or CWD) looking for a directory containing `.insight-kit/`. The resolution order is:

1. `kit_start` argument passed to `Run(kit_start=...)` — explicit, highest priority.
2. `INSIGHT_KIT_ROOT` environment variable — useful for CI runners.
3. Walk up from `Path.cwd()` — works for interactive scripts run from within the repo.

```python
# Priority resolution pseudocode (from root.py):
# 1. kit_start argument → Path(kit_start)
# 2. os.environ["INSIGHT_KIT_ROOT"] → Path(env_start)
# 3. Path.cwd(), then Path.cwd().parents[0], parents[1], ... until .insight-kit/ found
```

For CI runners, set the env var:

```bash
export INSIGHT_KIT_ROOT="$REPO_DIR"
```

### Step 7: Confirm the first Run resolves correctly

```python
from insight_kit import Run
from pathlib import Path

with Run(topic="bootstrap-smoke", agent="operator", kit_start=Path(".")) as r:
    r.note("Bootstrap smoke test — kit root resolves correctly.")

print("Run dir:", r.run_dir)
# Expect: .insight-kit/runs/<timestamp>_operator_bootstrap-smoke/
```

```bash
ls .insight-kit/runs/ | tail -1
# Should show the new run dir
```

### Step 8: Verify Python and Bun tool chains

```bash
cd "$REPO_DIR"

# Python tests
uv run pytest tests/ -q
# Expected: all tests pass (ignore `slow` and `eval` marks)

# Bun typecheck
bun run --filter '*' typecheck
# Expected: exit 0

# Bun lint
bun run lint
# Expected: exit 0 (biome check)
```

## Acceptance criteria

- `ls ~/.claude/skills/` lists all 14 skills (12 written here + preflight + viz-evidence-authoring).
- `/find-skills` in Claude Code returns all 14 skills without errors.
- `.insight-kit/config.yaml` exists and has a `namespace:` field.
- `uv run pytest tests/ -q` exits 0.
- `bun run --filter '*' typecheck` exits 0.
- `Run(topic="smoke", kit_start=Path("."))` context exits with `status: completed` and a run dir under `.insight-kit/runs/`.

## Common pitfalls

**`FileNotFoundError: No .insight-kit/ found`:** `find_kit_root` could not locate `.insight-kit/` above the CWD. Either `init_kit` was not run, or the script is being invoked from outside the repo. Fix: pass `kit_start=Path("/absolute/path/to/repo")` or set `INSIGHT_KIT_ROOT`.

**Symlink conflict (step 3 WARNING):** If a different project already symlinked a skill with the same name, the bootstrap prints a warning and skips. Resolve by checking which project's skill should take precedence — rename the conflicting project's skill dir before relinking.

**`bun.lock` mismatch in CI:** CI runners may cache a stale `bun.lock`. Run `bun install --frozen-lockfile` to validate, or `bun install` to regenerate. Never ignore a lockfile mismatch.

**`uv` not on PATH:** `uv` installs to `~/.cargo/bin/` or `~/.local/bin/`. If `uv` is not found, add `~/.local/bin` to PATH or re-run the installer.

**council clone fails (private repo):** If `0xNyk/council-of-high-intelligence` is private, configure SSH keys or a personal access token before cloning. The bootstrap script will fail silently if `git clone` exits non-zero — always check the exit code.

**`find_kit_root` LRU cache stale:** After `init_kit` creates `.insight-kit/`, the first `Run` in the same Python process will find it. But if `find_kit_root` was called before `init_kit`, it cached a `FileNotFoundError`. Call `find_kit_root.cache_clear()` after init.

## Examples

### Full cold-start one-liner (paste into terminal)

```bash
REPO="/path/to/insight-kit"
SKILLS="$HOME/.claude/skills"
mkdir -p "$SKILLS"
for d in "$REPO"/.agents/skills/*/; do
  skill="$(basename "$d")"
  [ ! -e "$SKILLS/$skill" ] && ln -s "$(realpath "$d")" "$SKILLS/$skill" && echo "Linked: $skill"
done
cd "$REPO"
uv run python -c "
from insight_kit.provenance.root import init_kit, find_kit_root
from pathlib import Path
try:
    find_kit_root(Path('.'))
    print('Kit root already exists')
except FileNotFoundError:
    init_kit(Path('.'), namespace='NMK')
    print('Kit initialized')
"
uv run pytest tests/ -q
bun run --filter '*' typecheck
```

### CI environment variable setup

```yaml
# .github/workflows/ci.yml (excerpt)
- name: Set INSIGHT_KIT_ROOT
  run: echo "INSIGHT_KIT_ROOT=$GITHUB_WORKSPACE" >> "$GITHUB_ENV"

- name: Bootstrap kit
  run: |
    uv run python -c "
    from insight_kit.provenance.root import init_kit, find_kit_root
    from pathlib import Path
    try:
        find_kit_root()
    except FileNotFoundError:
        init_kit(Path('.'), namespace='NMK')
    "
```

## Related skills

- `preflight` — run after bootstrap to validate the Evidence layer.
- `bun-monorepo-setup` — add new viz packages after bootstrap.
- `goal-management` — open the first project goal after kit initialization.

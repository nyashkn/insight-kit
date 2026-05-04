---
description: Cold-start the insight-kit agent council on a new machine or CI runner
allowed-tools: Bash, Read, Edit, Write, Glob
argument-hint: [--namespace=XXX]
---

Bootstrap the insight-kit agent council following the procedure in `docs/agents-bootstrap.md`.

Steps to execute:

1. **Parse arguments**: If `--namespace=XXX` is provided in `$ARGUMENTS`, use that value as the namespace. Otherwise default to `NMK`.

2. **Skills symlink loop** (Step 3 of docs/agents-bootstrap.md):
   ```bash
   SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
   mkdir -p "$SKILLS_DIR"
   REPO_DIR="$(git rev-parse --show-toplevel)"
   for d in "$REPO_DIR"/.agents/skills/*/; do
     skill_name="$(basename "$d")"
     TARGET="$SKILLS_DIR/$skill_name"
     SOURCE="$(realpath "$d")"
     if [ -e "$TARGET" ] && [ "$(readlink "$TARGET")" = "$SOURCE" ]; then
       echo "Already linked: $skill_name"
     elif [ -e "$TARGET" ]; then
       echo "WARNING: $skill_name exists at $TARGET — skipping (resolve conflict manually)"
     else
       ln -s "$SOURCE" "$TARGET"
       echo "Linked project skill: $skill_name"
     fi
   done
   ```

3. **Init kit root** (Step 5): Run the following Python snippet from the repo root. If `.insight-kit/` already exists, skip init and just print the config.
   ```bash
   uv run python -c "
   from insight_kit.provenance.root import init_kit, find_kit_root
   from pathlib import Path
   try:
       root = find_kit_root(Path('.'))
       print('Kit root already exists:', root)
   except FileNotFoundError:
       init_kit(Path('.'), namespace='NAMESPACE_PLACEHOLDER')
       print('Kit initialized:', find_kit_root(Path('.')))
   "
   ```
   Replace `NAMESPACE_PLACEHOLDER` with the namespace from step 1.

4. **Verify** (Step 4 acceptance criteria):
   - List `$SKILLS_DIR` — confirm all 12 skills are present: `agent-browser-verify`, `bun-monorepo-setup`, `citation-hygiene`, `claim-authoring`, `eval-protocol`, `evidence-page-creation`, `glossary-management`, `ingest-flow`, `layer-a-validation`, `preflight`, `schema-drift`, `viz-evidence-authoring`.
   - Confirm `.insight-kit/config.yaml` exists and has a `namespace:` field.
   - Run `/find-skills` to refresh the skills cache.

5. **Report**: Print a summary table of what was linked vs already present, the resolved kit root path, and the namespace in use.

Invoke `insight-kit:preflight` after bootstrap completes to validate the Evidence layer.

# Skills setup

Symlink the skills in `.agents/skills/` into your Claude Code (or compatible) skills dir.

For the full bootstrap procedure (council clone, kit init, verification), see [docs/agents-bootstrap.md](../docs/agents-bootstrap.md).

## Quick install (macOS / Linux)

```bash
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mkdir -p "$SKILLS_DIR"
cd /path/to/insight-kit
for d in .agents/skills/*/; do
  ln -sf "$(realpath "$d")" "$SKILLS_DIR/$(basename "$d")"
done
```

After symlinking, restart Claude Code or run `/find-skills` to refresh.

For Cursor / other harnesses, set `CLAUDE_SKILLS_DIR` to the harness's skills dir before running the loop.

## Windows

Symlinks aren't reliable on Windows. Copy directories instead:

```powershell
Copy-Item -Path .agents\\skills\\* -Destination $env:USERPROFILE\\.claude\\skills\\ -Recurse -Force
```

## CI

CI runners need directories copied (not symlinked). See [docs/agents-bootstrap.md § CI environment variable setup](../docs/agents-bootstrap.md#ci-environment-variable-setup) for the full GitHub Actions excerpt.

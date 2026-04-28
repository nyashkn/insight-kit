# Skills setup

Symlink the skills in this directory into your local Claude Code skills dir so
the AI loop can discover them.

## macOS / Linux

```bash
cd /Users/njui/Documents/dev_work/naisiae_lema/insight-kit
for f in .agents/skills/*.md; do
  [ "$(basename "$f")" = "SETUP.md" ] && continue
  ln -sf "$(realpath "$f")" "$HOME/.claude/skills/$(basename "$f")"
done
```

After symlinking, restart Claude Code OR run `/find-skills` to refresh.

## Windows

Symlinks aren't reliable on Windows. Copy instead:

```powershell
Copy-Item -Path .agents\skills\*.md -Destination $env:USERPROFILE\.claude\skills\ -Force
```

CI/agents need the files copied (not symlinked) into the runner's `~/.claude/skills/`.

## Verification

```bash
ls ~/.claude/skills/ | grep -E "(preflight|viz-evidence-authoring)"
```

Should show both files.

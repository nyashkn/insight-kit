# Skills setup

Symlink the skills in this directory into your local Claude Code skills dir so
the AI loop can discover them.

## macOS / Linux

Skills are organized in subdirectories, each containing a `SKILL.md` file. Symlink directories:

```bash
cd /Users/njui/Documents/dev_work/naisiae_lema/insight-kit
for d in .agents/skills/*/; do
  skill_name="$(basename "$d")"
  ln -sf "$(realpath "$d")" "$HOME/.claude/skills/$skill_name"
done
```

After symlinking, restart Claude Code OR run `/find-skills` to refresh.

## Windows

Symlinks aren't reliable on Windows. Copy directories instead:

```powershell
Copy-Item -Path .agents\skills\* -Destination $env:USERPROFILE\.claude\skills\ -Recurse -Force
```

CI/agents need the skill directories copied (not symlinked) into the runner's `~/.claude/skills/`.

## Verification

```bash
ls -d ~/.claude/skills/{preflight,viz-evidence-authoring}
cat ~/.claude/skills/preflight/SKILL.md | head -5
```

Should show both skill directories with `SKILL.md` files.

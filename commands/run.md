---
description: Open an insight-kit Run context for a given role and topic
allowed-tools: Bash, Read, Edit, Write, Glob
argument-hint: <role> <topic>
---

Open an insight-kit Run context using the role and topic from `$ARGUMENTS`.

Parse `$ARGUMENTS` as: first token = ROLE, remaining tokens joined with `_` = TOPIC.

Example: `/insight-kit:run analyst march_revenue` → ROLE=`analyst`, TOPIC=`march_revenue`.

Steps:

1. **Validate inputs**: Confirm ROLE and TOPIC are non-empty. If either is missing, print usage and stop:
   ```
   Usage: /insight-kit:run <role> <topic>
   Example: /insight-kit:run analyst march_revenue
   ```

2. **Confirm kit root**: Run `uv run python -c "from insight_kit.provenance.root import find_kit_root; from pathlib import Path; print(find_kit_root(Path('.')))"` to confirm `.insight-kit/` is reachable. If it fails, advise the user to run `/insight-kit:bootstrap` first.

3. **Open the Run**: Construct and execute a Python REPL block:
   ```python
   from insight_kit.provenance import Run
   from pathlib import Path

   with Run(topic="TOPIC", agent="ROLE", kit_start=Path(".")) as r:
       r.note("Run opened via /insight-kit:run slash command.")
       print("Run dir:", r.run_dir)
       print("Run ID:", r.run_id)
   ```
   Substitute TOPIC and ROLE with the parsed values.

4. **Report**: After the `with` block exits, print:
   - Run directory path
   - Run ID
   - Next suggested actions: add claims via `/insight-kit:claim`, run preflight via `/insight-kit:preflight`, promote claims via `/insight-kit:promote <run_id>`.

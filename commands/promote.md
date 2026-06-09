---
description: Promote claims from a run into the project claims registry
allowed-tools: Bash, Read, Edit, Write, Glob
argument-hint: <run_id>
---

Promote claims from a completed run into `.insight-kit/claims_registry.yaml`.

Parse `$ARGUMENTS` as RUN_ID. This is the run directory name under `.insight-kit/runs/` (e.g., `2026-04-25_2030_analyst-meadows-v1_march_reconcile`).

Steps:

1. **Locate the run**: Read `.insight-kit/runs/<RUN_ID>/claims.jsonl`. If the file does not exist, print an error and list the available run directories.

2. **Read the registry**: Read `.insight-kit/claims_registry.yaml`. Note the current namespace and any existing claim IDs to detect collisions.

3. **For each claim in claims.jsonl**:
   - Check for ID collision with the registry. If the claim ID already exists and the statement has changed, flag as CONFLICT and ask the user whether to overwrite, skip, or rename.
   - If the claim is new, add it to the registry under the correct tier section.
   - If the claim statement contains new domain terms not in `.insight-kit/glossary.yaml` (if it exists), flag each term and ask the user if it should be added to the glossary.

4. **Write updates**:
   - Write the updated `claims_registry.yaml`.
   - If glossary additions were confirmed, append new terms to `.insight-kit/glossary.yaml` (create if missing).

5. **Report**:
   ```
   Promoted N claims from run <RUN_ID>:
     NMK-D-001  added
     NMK-C-002  added
     NMK-V-003  skipped (already in registry, identical)
   Glossary: 1 new term added
   ```

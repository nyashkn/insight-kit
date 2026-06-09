---
description: List all agent roles and their bound skills and compatible personas
allowed-tools: Bash, Read, Edit, Write, Glob
argument-hint: ""
---

List all agent roles defined in `.agents/agents/*/AGENT.md` with their bound skills and compatible personas.

Steps:

1. **Discover AGENT.md files**: Use Glob to find all `.agents/agents/*/AGENT.md` files.

2. **Parse each AGENT.md**: For each file, read the YAML frontmatter to extract:
   - `role` (or the directory name as fallback)
   - `skills_using` (list of skill names this role invokes)
   - `personas_compatible` (list of persona identifiers)
   - `default_role_for` (optional routing key)

3. **Also read `.agents/config.yaml`** to get the `default_role` and any routing config.

4. **Output a formatted table**:
   ```
   Role                  Skills Used                          Personas Compatible
   ────────────────────  ───────────────────────────────────  ──────────────────────
   analyst               claim-authoring, ingest-flow,        meadows-v1, oak-v1
                         layer-a-validation, eval-protocol
   critic                preflight, citation-hygiene,         summit-v1
                         schema-drift
   writer                evidence-page-creation,              river-v1
                         viz-evidence-authoring
   ...
   ```

5. **Append a routing summary**: Show which role handles each `default_role_for` key if configured.

6. **Tip**: To install all skill symlinks for these roles, run `/insight-kit:bootstrap`.

---
description: Run insight-kit preflight checks across all 6 evidence layers
allowed-tools: Bash, Read, Edit, Write, Glob
argument-hint: [--page=path/to/page.md]
---

Run preflight checks using the `insight-kit:preflight` skill.

Parse `$ARGUMENTS`: if `--page=<path>` is provided, scope the check to that page. Otherwise run project-wide.

Steps:

1. **Confirm kit root**: Verify `.insight-kit/` is reachable. If not, stop and advise running `/insight-kit:bootstrap`.

2. **Invoke `insight-kit:preflight`**: Apply the preflight skill to run all 6 layer checks:
   - Layer 1: Schema validity — `.insight-kit/config.yaml`, `agents.yaml`, `claims_registry.yaml`
   - Layer 2: Run integrity — manifest hashes vs. artifact checksums in `.insight-kit/runs/`
   - Layer 3: Claim coverage — all open goals have at least one supporting claim
   - Layer 4: Evidence density — claims with tier C/I/V/X have cited evidence
   - Layer 5: Evidence viz — Evidence pages compile without error (if `--page` is set, only that page)
   - Layer 6: Skill availability — all 12 project skills are symlinked and discoverable

3. **If `--page` is specified**: Read the page at the given path, validate frontmatter, check that all `claim_ids` referenced exist in `claims_registry.yaml`, and confirm the Evidence component syntax is valid.

4. **Report**: Print a pass/fail table:
   ```
   Layer 1 Schema validity      PASS
   Layer 2 Run integrity        PASS
   Layer 3 Claim coverage       WARN  (2 open goals have no claims)
   Layer 4 Evidence density     PASS
   Layer 5 Evidence viz         PASS
   Layer 6 Skill availability   PASS
   ```
   List any failures with actionable remediation steps.

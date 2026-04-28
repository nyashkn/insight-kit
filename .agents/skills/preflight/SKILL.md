---
name: preflight
type: skill
description: Run insight-kit preflight checks against an Evidence reports dir. Use when validating before deploy, after adding/editing pages, or diagnosing render failures. Covers 6 layers: SQL blocks, build gate, render check, numeric sanity, provenance integrity, layout-type compliance.
validated_against:
  evidence: "v40"
  duckdb: "1.x"
  bun: "1.3.x"
---

## When to use

Trigger preflight in these scenarios:
- Before deploying to production
- After adding or editing Evidence pages
- When validating dashboard rendering
- Diagnosing "Application Error" or render failures
- Any `ik preflight` invocation in the build pipeline

## Quick start

```bash
ik preflight --reports-dir ./reports
ik preflight --explain
ik preflight --layer 1,6 --pages slug1,slug2
ik preflight --strict
```

## Layer reference

| Layer | Name | Catches | When | Typical fix |
|-------|------|---------|------|-------------|
| L1 | SQL blocks | Syntax errors, invalid DuckDB | Immediately | Fix query syntax |
| L2 | Build gate | Missing dependencies, unresolved imports | Build step | Run `bun run build:claim-views` |
| L3 | Render check | Template syntax, missing components | Full build | Add/import missing components |
| L4 | Numeric sanity | Out-of-range values (>999%), NaN, Inf | Chart validation | Review upstream calc or fmt prop |
| L5 | Provenance integrity | Claim cycles, broken supersedes chain | Publish | Break cycle in claim YAML |
| L6 | Layout-type compliance | Missing/invalid `layout_type:` frontmatter | Page contract | Add required frontmatter |

## Interpreting findings

Each finding has: `file:line | snippet | hint | severity`

- **error**: preflight fails on this finding; fix required
- **warn**: informational; fix recommended but non-blocking unless `--strict`

```
reports/my-page.md:12 | <ClaimBlock claim_id="X" /> | Application Error: ClaimX is not defined | error
```

Fix: Add `evidenceInclude=true` const literal to component's `<script context="module">`.

## Common failures + fixes

| Finding | Root cause | Fix |
|---------|-----------|-----|
| `Expected valid tag name` | Unescaped `<` in claim statement | HTML-escape in generator script |
| `Application Error: ClaimX is not defined` | Component missing `evidenceInclude=true` | Add `const evidenceInclude = true;` in `<script context="module">` |
| `layout-type-missing` | Page lacks frontmatter | Add `layout_type: receipt\|narrative\|investigation\|metric\|browse\|audit` |
| `provenance-cycle` | Claim cites form a cycle | Review/fix supersedes chain in claim YAML |
| `bigvalue-overflow-pct` | BigValue renders >999% | Check fmt prop or upstream percentage calc |
| `duckdb-syntax-error` | Invalid SQL in view or query | Fix DuckDB syntax (e.g., `.sql` file) |

## Exit codes

- `0`: all checks passed
- `1`: any failure, or any warning if `--strict`

Run `ik preflight --help` for full option list.

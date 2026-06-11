# viz-kit + JS Preflight — Multi-Slice Rollout Plan

**Date:** 2026-04-28
**Repos:** insight-kit · example-ops-insight-kit (feat/insight-kit-adoption) · example-shop/growth_insights
**Decisions taken** (via AskUserQuestion):
1. Replace Python preflight — port L1-L4 to JS, add L5/L6
2. Aggressive extraction — components + layouts + generators + preflight all to insight-kit
3. Full abstract plugin contract — Renderer protocol + PageType enum
4. Both distribution — npm package (runtime) + skill in `.agents/skills/` symlinked to `~/.claude/skills/`

---

## Layer-to-TS mapping (preflight_check.py → new TS)

| Python layer | New home | Notes |
|---|---|---|
| L1 SQL block validation | `viz/core/checks/sqlBlocks.ts` | Port DuckDB attach via `@duckdb/node-api`; skip `${...}` template expressions |
| L2 Evidence build gate | `viz/core/checks/buildGate.ts` | `child_process.spawn` replacing subprocess.run |
| L3 agent-browser render | `viz/core/checks/renderCheck.ts` | Use existing `agent-browser` CLI; eval payload moves to `evalPayloads/l3.js` |
| L4 numeric/render sanity | `viz/core/checks/numericSanity.ts` + `evalPayloads/l4.js` | JS IIFE payload lifts verbatim |
| L5 provenance integrity (NEW) | `viz/core/checks/provenanceInteg.ts` | Cite resolution + Tarjan SCC for cycle detection |
| L6 layout-type compliance (NEW) | `viz/core/checks/layoutCompliance.ts` | Read frontmatter `layout_type`, apply per-PageType rules |

---

## Page-Type Rule Matrix (L6)

| PageType | Required components | Min charts | ProvenanceRail | Frontmatter |
|---|---|---|---|---|
| receipt | ≥1 ClaimBlock | 0 | NO (page IS receipt) | `hide_sidebar: true` |
| narrative | ≥1 ClaimBlock or ClaimInline | 0 | YES | none |
| investigation | ≥1 ClaimBlock | ≥1 | Optional | none |
| metric | none | ≥1 | Optional | none |
| browse | none | 0 | NO | none |
| audit | none | 0 | NO | none |

---

## Slices Table

| ID | Name | Risk | LOC | Depends | Parallel With | Model |
|---|---|---|---|---|---|---|
| M0 | Spike: Evidence npm component auto-discovery (de-risk R1) | CRIT | 50 | — | — | Sonnet |
| M1 | viz/core/ — types + contracts | LOW | 200 | M0 | — | Haiku |
| M2 | viz/core/checks/ — L1 + L2 + L4 + L5 + L6 | MED | 600 | M1 | M3, M4, M5, M6 | Sonnet |
| M3 | viz/core/checks/ — L3 render | MED | 250 | M1 | M2, M4, M5, M6 | Sonnet |
| M4 | viz/evidence/components/ — 6 Svelte | LOW | 1500 | M0, M1 | M2, M3, M5, M6 | Haiku |
| M5 | viz/evidence/layouts/ — 6 templates + install | LOW | 200 | M1 | M2, M3, M4, M6 | Haiku |
| M6 | viz/evidence/generators/ — 3 scripts | MED | 650 | M1 | M2, M3, M4, M5 | Sonnet |
| M7 | insight-kit/cli/ — kit preflight + viz install | MED | 300 | M2, M3 | M8 | Sonnet |
| M8 | .agents/skills/ — preflight + authoring + symlink doc | LOW | 200 | M7 | M9 | Haiku |
| M9 | example-ops migration | HIGH | 150 | M4, M5, M6, M7 | M10 (must be after) | Sonnet |
| M10 | growth_insights migration | HIGH | 100 | M7, M9 | — | Sonnet |
| M11 | Integration tests CI harness | MED | 200 | M9, M10 | — | Sonnet |

---

## Sequencing

```
M0 (de-risk, BLOCKING)
  ↓
M1 (BLOCKING)
  ↓
  ┌─ M2 ─┐
  ├─ M3 ─┤  ← all PARALLEL (5-way peak)
  ├─ M4 ─┤
  ├─ M5 ─┤
  └─ M6 ─┘
  ↓
M7 (needs M2+M3 done)
  ↓
  ┌─ M8 ─┐
  └─ M9 ─┘  ← parallel
  ↓
M10
  ↓
M11
```

**Critical serial chain:** M0 → M1 → {M2+M3} → M7 → M9 → M10 → M11 (7 steps).
**Parallelism peak:** 5 simultaneous workstreams between M1 and M7.

---

## Risk Register

**R1 — Evidence npm component auto-discovery (CRITICAL)**
Whether Evidence's sveltekit-autoimport crawls `node_modules/@insight-kit/viz-evidence/` for `evidenceInclude = true` is unverified. Mitigation: M0 spike with throwaway 1-component dummy package.

**R2 — DuckDB createRequire path resolution (HIGH)**
`sqlBlocks.ts` must load `@duckdb/node-api` from consumer's `reports/node_modules`, not insight-kit's. Mitigation: caller-parameterized `duckdbModulePath` arg.

**R3 — deploy_insights.sh CI replacement (HIGH)**
`uv run python scripts/preflight_check.py` invoked twice (lines 87-88). Replacing with `ik preflight` requires `ik` on PATH in CI. Mitigation: M10 adds `command -v ik` guard + 1-sprint Python fallback.

---

## Critical files

- `insight-kit/viz/core/types.ts` — central types, all slices depend on it
- `insight-kit/viz/core/checks/sqlBlocks.ts` — highest behavioral-parity risk vs Python
- `insight-kit/viz/evidence/components/ClaimTree.svelte` — canonical `evidenceInclude = true` reference (others need patching)
- `growth_insights/scripts/deploy_insights.sh` — only CI file with hard `preflight_check.py` reference

---

## Total

**12 slices** (added M0 spike). **~4,600 LOC**. **5-way peak parallelism** after M1.

Status field per slice maintained inline as work progresses.

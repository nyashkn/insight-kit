---
name: viz-evidence-authoring
description: Author Evidence pages with insight-kit's claim components and layout-type contract. Use when creating/editing .md pages that consume ClaimBlock, ClaimInline, ClaimDelta, ClaimTree, or ProvenanceRail; or when authoring new layout types or generator scripts.
---

## Page-type contract

Every Evidence page consuming claim components must declare its `layout_type:` in frontmatter. This is mandatory and enforced by L6 preflight.

```yaml
---
layout_type: receipt|narrative|investigation|metric|browse|audit
---
```

## 6-page-type matrix

| Type | Required components | Min charts | Rail | Constraints |
|------|--------------------|-----------:|------|-------------|
| receipt | ClaimBlock (focal) | 0 | forbidden | Transactional; single claim focus |
| narrative | ClaimInline + ClaimBlock | 1 | optional | Story-driven; multi-claim arc |
| investigation | ClaimBlock + ClaimTree | 2 | required | Ancestry/supersedes chains mandatory |
| metric | BigValue + ClaimInline | 1 | optional | KPI dashboard style |
| browse | ClaimInline (grid) | 0 | forbidden | Link-heavy; minimal charts |
| audit | ClaimBlock + ProvenanceRail | 1 | required | Full provenance visible |

## Component catalog

**ClaimBlock** — Focal claim card with supporting metadata and audit trail
- Props: `claim_id` (string, required), `showAuditTrail` (bool, default true)
- Example: `<ClaimBlock claim_id="C001" />`

**ClaimInline** — Citation chip; displays claim ID and confidence inline
- Props: `claim_id` (string, required), `compact` (bool, default false)
- Example: `<ClaimInline claim_id="C001" />`

**ClaimDelta** — Side-by-side comparison of superseding claim pair
- Props: `from_claim_id` (string), `to_claim_id` (string), both required
- Example: `<ClaimDelta from_claim_id="C001" to_claim_id="C002" />`

**ClaimTree** — Recursive ancestry/provenance tree from root claim
- Props: `claim_id` (string, required), `maxDepth` (number, default 3)
- Example: `<ClaimTree claim_id="C001" maxDepth={4} />`

**ProvenanceRail** — Sticky pre/post panel; shows full derivation context
- Props: `claim_id` (string, required), `position` ('left'|'right', default 'right')
- Example: `<ProvenanceRail claim_id="C001" position="left" />`

## Generator workflow

Run in this order (dependencies enforce sequence):

1. `npm run build:claim-views` — Generate DuckDB views from Python + claim manifests
2. `npm run build:provenance` — Per-receipt `.md` authoring from views
3. `npm run build:indexes` — By-tier indexes + ancestry trees

Skipping a step breaks downstream steps. Re-run all if claim YAML changes.

## Source-claim sidecars

Co-locate `<query>.claim.yaml` next to `<query>.sql` for ETL_M-tier provenance tracking.

```yaml
# revenue.sql.claim.yaml
claim_id: C_REVENUE_001
source_table: raw_transactions
upstream_claims:
  - C_TRANSACTIONS_DEDUPED
supersedes: C_REVENUE_000
confidence: 0.95
```

Scripts ingest via `scripts/index_source_claims.py` (or kit equivalent). Prevents manual chart rewrites on supersedes edits.

## HTML escaping rule

Claim statements may contain `<`, `>`, `&`. Generators MUST escape these characters. Pages should reference claims via component (e.g., `<ClaimBlock claim_id="..." />`), never inline raw statement text.

```svelte
// WRONG
<p>Claim: {claim.statement}</p>

// RIGHT
<ClaimBlock claim_id={claim.id} />
```

## Critic-stability rule

Chart SQL references `claim_id` column and `dockblocks.<source>` table names, NOT free-text statements. Supersedes-chain edits then propagate automatically without manual chart SQL rewrites.

```sql
SELECT revenue FROM reports WHERE claim_id = 'C_001'
-- safe to supersede C_001 → chart still works
```

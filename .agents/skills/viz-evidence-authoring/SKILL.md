---
name: viz-evidence-authoring
description: Author Evidence .md pages with claim components (ClaimBlock, ClaimInline, ClaimDelta, ClaimTree, ProvenanceRail). Invoke on missing evidenceInclude=true, user says "create evidence page", or layout_type contract violations.
---

> For the canonical page-type rules (component requirements, claim density, ProvenanceRail), see [evidence-page-creation](../evidence-page-creation/SKILL.md). This skill is a component reference for ClaimBlock, ClaimInline, ClaimDelta, ClaimTree, ProvenanceRail.

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

1. `bun run build:claim-views` — Generate DuckDB views from Python + claim manifests
2. `bun run build:provenance` — Per-receipt `.md` authoring from views
3. `bun run build:indexes` — By-tier indexes + ancestry trees

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

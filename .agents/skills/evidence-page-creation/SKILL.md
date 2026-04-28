---
name: evidence-page-creation
type: skill
description: Create Evidence .md pages with the correct layout_type frontmatter, required components, and ProvenanceRail placement per the PAGE_TYPE_RULES matrix.
roles_using: [renderer]
validated_against:
  evidence: "v40"
  duckdb: "1.x"
  bun: "1.3.x"
metadata:
  last_verified: 2026-04-29
---

> **Canonical**: This skill is the source of truth for the 6-page-type matrix (receipt | narrative | investigation | metric | browse | audit). Other skills must reference, not duplicate.

## Purpose

Every Evidence page that uses insight-kit claim components must declare a `layout_type:` in frontmatter. The value drives L6 preflight enforcement: wrong or missing `layout_type` causes the preflight to exit 1 with `layout-type-missing` or `layout-type-rule-violation`. This skill maps page intent to the correct `layout_type` and enforces the component/chart minimums.

## When to invoke

- When creating a new `.md` page in an Evidence reports directory.
- When L6 preflight fails with `layout-type-missing` or a component-minimum violation.
- When choosing whether to put `ProvenanceRail` on a page.
- When the page intent (receipt vs narrative vs investigation etc.) is unclear.

## PAGE_TYPE_RULES matrix

From `viz/core/pageTypeRules.ts`:

| layout_type | Min ClaimBlocks | Min ClaimInline or ClaimBlock | Min charts | ProvenanceRail | Constraints |
|-------------|----------------:|-----------------------------:|-----------:|----------------|-------------|
| `receipt` | 1 | — | 0 | **forbidden** | `hide_sidebar: true` required in frontmatter. Single column. |
| `narrative` | — | 1 (either type) | 0 | **required** | Story with inline claims. Rail anchors the provenance context. |
| `investigation` | 1 | — | 1 | optional | Analyst depth page. Charts + claim chips. |
| `metric` | — | — | 1 | optional | KPI dashboard. BigValue + charts. No prose body required. |
| `browse` | — | — | 0 | optional | DataTables index. No prose body required. |
| `audit` | — | — | 0 | optional | Debug/QA. Graph viewers, raw data. No claim refs required. |

## Procedure

### 1. Choose the layout_type

Ask: what is the primary purpose of this page?

| Purpose | layout_type |
|---------|-------------|
| Show a single provenance receipt for one claim chain | `receipt` |
| Tell an analytical story with supporting claims inline | `narrative` |
| Deep-dive analyst page with charts and claim chips | `investigation` |
| KPI dashboard with metrics | `metric` |
| Index or search list of claims/data | `browse` |
| Debug/QA output, raw data viewer | `audit` |

### 2. Create the frontmatter

```markdown
---
title: Q1 2026 Revenue Analysis
layout_type: investigation
---
```

For `receipt` pages, also add:

```markdown
---
title: Claim NMK-D-042 Provenance Receipt
layout_type: receipt
hide_sidebar: true
---
```

### 3. Add required components

**receipt page:**

```svelte
<script>
  import { ClaimBlock } from '@insight-kit/claim-components';
</script>

# NMK-D-042 — Gross Margin Receipt

<ClaimBlock claim_id="NMK-D-042" showAuditTrail={true} />
```

Note: `receipt` **forbids** `ProvenanceRail`. Do not add it.

**narrative page:**

```svelte
<script>
  import { ClaimInline, ProvenanceRail } from '@insight-kit/claim-components';
</script>

<ProvenanceRail claim_id="NMK-D-042" position="right" />

# Revenue Narrative

Gross margin improved by 3.3pp in Q1 2026 <ClaimInline claim_id="NMK-D-042" />, driven by
lower variable costs.
```

Note: `narrative` **requires** `ProvenanceRail`.

**investigation page:**

```svelte
<script>
  import { ClaimBlock } from '@insight-kit/claim-components';
</script>

# Pricing Investigation

```sql orders_by_tier
SELECT tier, COUNT(*) as orders, AVG(amount_usd) as avg_amount
FROM orders_bronze
GROUP BY tier
```

<BarChart
  data={orders_by_tier}
  x="tier"
  y="avg_amount"
  title="Average Order by Tier"
/>

<ClaimBlock claim_id="NMK-D-042" />
```

**metric page:**

```svelte
# KPI Dashboard

```sql gross_margin
SELECT 38.4 as value, 'Q1 2026' as period
```

<BigValue data={gross_margin} value="value" title="Gross Margin %" />
```

No `ClaimBlock` or `ClaimInline` required for `metric`, but `ProvenanceRail` is optional.

**browse page:**

```svelte
---
title: All Claims Index
layout_type: browse
---

```sql all_claims
SELECT claim_id, statement, tier, confidence FROM agent_run.claims_manifest
ORDER BY claim_id
```

<DataTable data={all_claims} search={true} />
```

**audit page:**

```svelte
---
title: Run Audit — 2026-04-28
layout_type: audit
---

```sql run_manifest
SELECT * FROM agent_run.runs_latest LIMIT 50
```

<DataTable data={run_manifest} />
```

### 4. Run L6 preflight to validate

```bash
ik preflight --layer 6 --reports-dir ./reports
# must exit 0
```

If it fails with `layout-type-missing`, confirm the frontmatter `layout_type:` key is present and one of the 6 valid values.

If it fails with a component minimum (e.g., `receipt requires minClaimBlocks=1`), add the missing component.

### 5. Full preflight before deploy

```bash
ik preflight --reports-dir ./reports
# must exit 0 (all 6 layers)
```

## Acceptance criteria

- Page frontmatter has `layout_type:` set to one of `receipt|narrative|investigation|metric|browse|audit`.
- `ik preflight --layer 6 --reports-dir ./reports` exits 0.
- `receipt` pages have `hide_sidebar: true` and no `ProvenanceRail`.
- `narrative` pages have at least one `ClaimInline` or `ClaimBlock` and include `ProvenanceRail`.
- `investigation` pages have at least one `ClaimBlock` and one chart.
- `metric` pages have at least one chart.

## Common pitfalls

**ProvenanceRail on a receipt page:** `receipt` forbids the rail (`forbidsProvenanceRail: true`). Adding it causes L6 failure. The receipt page IS the provenance chain — the rail is redundant.

**Missing ProvenanceRail on narrative:** `narrative` requires the rail (`requiresProvenanceRail: true`). Forgetting it causes L6 failure.

**Wrong component import path:** Component names are `ClaimBlock`, `ClaimInline`, `ClaimDelta`, `ClaimTree`, `ProvenanceRail`. Using `<Claim>` or `<ProvRail>` will produce a Svelte compile error at `evidenceInclude=true` check time.

**Unescaped `<` in rendered claim statement:** If the claim statement contains `<` (e.g., `"margin < 30%"`), Evidence will fail with `Expected valid tag name`. Claims must be rendered via `<ClaimBlock>`, never as raw `{claim.statement}` interpolation.

**`layout_type` with wrong case:** `investigation` not `Investigation`. The value is lowercase and case-sensitive.

## Examples

### Receipt page skeleton

```markdown
---
title: NMK-D-042 Provenance Receipt
layout_type: receipt
hide_sidebar: true
---

<ClaimBlock claim_id="NMK-D-042" showAuditTrail={true} />
```

### Investigation page with supersedes diff

```markdown
---
title: Margin Analysis — Q1 2026
layout_type: investigation
---

```sql margin_trend
SELECT period, gross_margin_pct FROM metrics.gross_margin ORDER BY period
```

<LineChart data={margin_trend} x="period" y="gross_margin_pct" title="Gross Margin Trend" />

<ClaimBlock claim_id="NMK-D-042" />

<ClaimDelta from_claim_id="NMK-D-040" to_claim_id="NMK-D-042" />
```

## Related skills

- `viz-evidence-authoring` — component catalog and HTML-escape rules.
- `preflight` — full 6-layer validation including L6 layout checks.
- `agent-browser-verify` — verify that Evidence pages hydrate correctly after build.

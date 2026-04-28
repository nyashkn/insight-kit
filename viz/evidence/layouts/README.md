# Evidence Layout Templates

This directory contains SvelteKit layout templates for the 6 Evidence page types. Each template provides page-type-specific styling and structure via `<slot />` pass-through.

## Purpose

Layout templates establish a baseline visual and semantic structure for each Evidence page type. They are thin wrappers that:
- Wrap content in a semantic container (e.g., `<div class="layout-receipt">`)
- Apply type-specific CSS rules (typography, print styling, header emphasis, etc.)
- Pass all content through to child pages unchanged (`<slot />`)

Templates are **not** page chrome (no header, nav, sidebar). They are installed into consumer projects and remain fully editable.

## Layouts Catalog

| Page Type | Template | Source Folder | Purpose |
|-----------|----------|---------------|---------|
| `receipt` | `receipt.svelte` | `provenance` | Provenance receipt — exec audience, narrow body, print-friendly |
| `narrative` | `narrative.svelte` | `narratives` | Story with charts + provenance rail — reviewer-focused |
| `investigation` | `investigation.svelte` | `funnel` | Analyst depth: charts + claim chips + filters |
| `metric` | `metric.svelte` | `metrics` | Dashboard-style KPI grid |
| `browse` | `browse.svelte` | `index` | Index/list/search catalog view, header emphasis |
| `audit` | `audit.svelte` | `debug` | Debug/QA — graphs, raw data viewers |

## Install Command

### Default install (all 6 types)

```bash
node viz/evidence/layouts/install.mjs --reports-dir ./reports
```

This will create:
- `reports/pages/provenance/+layout.svelte` (receipt)
- `reports/pages/narratives/+layout.svelte` (narrative)
- `reports/pages/funnel/+layout.svelte` (investigation)
- `reports/pages/metrics/+layout.svelte` (metric)
- `reports/pages/index/+layout.svelte` (browse)
- `reports/pages/debug/+layout.svelte` (audit)

### Selective install

```bash
node viz/evidence/layouts/install.mjs --reports-dir ./reports --types receipt,metric,browse
```

### Force overwrite

```bash
node viz/evidence/layouts/install.mjs --reports-dir ./reports --force
```

### Help

```bash
node viz/evidence/layouts/install.mjs --help
```

## Default Folder Mapping

The layout installer uses a **convention** mapping: each `PageType` has a default destination folder. This is documented in `LAYOUT_MAP.json` and enforced by the installer for consistency.

**Override note:** The folder mapping (`pageType` → `folder`) is a convention, not a hard constraint. Consumers may manually place `+layout.svelte` files in non-standard locations after installation. The installer will not copy to custom paths — edit manually or re-run with `--force` after moving files.

## Customization

After install, layout files are fully editable in-place:

```svelte
<!-- reports/pages/<folder>/+layout.svelte -->
<div class="layout-<type>">
  <slot />
</div>

<style>
  /* Add project-specific rules here */
  :global(.layout-<type>) {
    /* your CSS */
  }
</style>
```

**Updates:** To update a layout template from a future version of `@insight-kit/viz-evidence`, re-run the install with `--force`:

```bash
node viz/evidence/layouts/install.mjs --reports-dir ./reports --force
```

This will overwrite existing files. Keep a git diff to review changes.

## Implementation Notes

- All templates preserve optional CSS (print rules, typography, etc.) from the source.
- None include legacy `EvidenceDefaultLayout` imports (K3 fix).
- All are plain `.svelte` files — no preprocessing, no external dependencies.
- Install script uses Node 20 built-ins only (`node:util`, `node:fs/promises`, `node:path`).

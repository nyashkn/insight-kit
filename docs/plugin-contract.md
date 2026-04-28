# Renderer Plugin Contract

**Package:** `@insight-kit/viz-core` v0.1  
**Source:** `viz/core/renderer.ts`, `viz/core/types.ts`, `viz/core/pageTypeRules.ts`

---

## 1. Overview

A **Renderer plugin** is an npm package that teaches insight-kit how to turn
markdown + data sources into a rendered report inside a specific visualization
framework. Today the only production renderer is `@insight-kit/viz-evidence`
(Evidence v5). Tomorrow, `markdown-seaborn`, `malloy`, or `lightdash` renderers
will follow the identical contract.

Each renderer:
- installs its layout/component files into the consumer's `reports/` directory,
- defines a build gate that returns pass/fail on the rendered output, and
- exposes preflight rules (L2+) that the core runner dispatches.

The consumer picks a renderer via `registerRenderer()` and the `ik` CLI
delegates `install`, `buildGate`, and layer checks to it.

---

## 2. Renderer Interface

Full TypeScript surface, verbatim from `viz/core/renderer.ts`:

```typescript
import type { PageType, PreflightRule, PreflightResult, CheckContext } from './types.js';

export interface Renderer {
  /** Plugin identifier, e.g. 'evidence', 'markdown', 'malloy'. */
  name: string;
  /** Page types this renderer can produce. */
  pageTypes: PageType[];
  /** Copy/symlink components, layouts, generators into the consumer reports dir. */
  install(reportsDir: string, options?: Record<string, unknown>): Promise<void>;
  /** Renderer-specific build gate (e.g. evidence build, seaborn render). */
  buildGate(ctx: CheckContext): Promise<PreflightResult>;
  /** Renderer-specific preflight rules (Layer 2 + plugin-specific layers). */
  rules: PreflightRule[];
}
```

Supporting types from `viz/core/types.ts`:

```typescript
export type PageType =
  | 'receipt'        // page IS the provenance receipt — exec audience
  | 'narrative'      // story with charts + provenance rail — reviewer
  | 'investigation'  // analyst depth: charts + claim chips + filters
  | 'metric'         // dashboard-style KPI grid
  | 'browse'         // index/list/search
  | 'audit';         // debug/QA — graphs, raw data viewers

export interface CheckContext {
  reportsDir: string;
  pagesDir: string;
  sourcesDir: string;
  projectRoot: string;
  duckdbPath?: string;
  duckdbModulePath?: string;
  pagesFilter?: string[];
  baseUrl?: string;
  agentBrowserPath?: string;
}

export interface PreflightResult {
  pass: boolean;
  findings: Finding[];
  pagesChecked: number;
  durationMs: number;
  layers: { [k: number]: { passed: number; failed: number; durationMs: number } };
}

export interface PreflightRule {
  id: string;
  layer: number;
  appliesTo?: PageType[];
  severity: Severity;
  description: string;
  hint?: string;
  check: (ctx: CheckContext) => Promise<Finding[]>;
}
```

---

## 3. PageType Enum + PAGE\_TYPE\_RULES

Six page types are defined. Each has a rule set enforced by L6 (layout
compliance). Source: `viz/core/pageTypeRules.ts` and
`PLANS/viz-kit-extraction-2026-04-28.md`.

| PageType      | Min ClaimBlocks | Min Claims (any) | Min Charts | ProvenanceRail | Required Frontmatter      |
|---------------|-----------------|------------------|------------|----------------|---------------------------|
| `receipt`     | ≥1              | —                | 0          | FORBIDDEN      | `hide_sidebar: true`      |
| `narrative`   | —               | ≥1               | 0          | REQUIRED       | none                      |
| `investigation` | ≥1            | —                | ≥1         | optional       | none                      |
| `metric`      | —               | —                | ≥1         | optional       | none                      |
| `browse`      | —               | —                | 0          | none           | none                      |
| `audit`       | —               | —                | 0          | none           | none                      |

`PAGE_TYPE_RULES` is a `Record<PageType, PageTypeRuleSet>` exported from
`@insight-kit/viz-core`. Each value has:

```typescript
interface PageTypeRuleSet {
  requiredFrontmatter?: Record<string, unknown>;
  minClaimBlocks?: number;
  minClaimInlineOrBlock?: number;
  minCharts?: number;
  requiresProvenanceRail?: boolean;
  forbidsProvenanceRail?: boolean;
  description: string;
}
```

---

## 4. Required Exports for an Evidence-Like Renderer

An Evidence-compatible renderer package must expose components that Evidence's
sveltekit-autoimport can discover. The discovery mechanism relies on:

### 4.1 `evidenceInclude = true` marker

Every Svelte component that should be auto-imported by Evidence must export the
constant in a `<script context="module">` block at the top of the file:

```svelte
<script context="module">
  export const evidenceInclude = true;
</script>
```

Reference: `viz/evidence/components/ClaimBlock.svelte` (canonical example).

### 4.2 `package.json` `evidence` field

The renderer package's `package.json` must declare:

```json
{
  "evidence": {
    "components": true
  }
}
```

This signals to Evidence that the package contains auto-importable components.
See `viz/evidence/package.json`.

### 4.3 Component entry point

`package.json` `"main"` and `"exports[\".\"]"` must point to a barrel file that
re-exports all auto-importable Svelte components:

```json
{
  "main": "components/index.js",
  "exports": {
    ".": "./components/index.js"
  }
}
```

---

## 5. Install Hook

The renderer must expose an install script at `<plugin>/layouts/install.ts` (or
equivalent). It is invoked as:

```sh
bun <plugin>/layouts/install.ts --reports-dir <path> [--force] [--types <list>]
```

The install script must:

1. Load a `LAYOUT_MAP.json` file (co-located) that maps each `PageType` to a
   source layout file and a target folder name.
2. Resolve the consumer's `reports/pages/` directory from `--reports-dir`.
3. For each page type in scope, create `reports/pages/<folder>/+layout.svelte`
   by copying the source template. Skip existing files unless `--force` is
   passed.
4. Print a human-readable summary (installed / skipped / failed).
5. Exit `0` on full success, exit `1` if any layout copy fails.

Reference implementation: `viz/evidence/layouts/install.ts`.

---

## 6. Build Gate (L2) Hook

The `buildGate(ctx: CheckContext)` method is called by the core preflight runner
as Layer 2. It must:

1. Invoke the renderer's build command (e.g. `npx evidence build` for the
   Evidence renderer) as a subprocess against `ctx.reportsDir`.
2. Capture stdout/stderr. A non-zero exit code means the build failed.
3. Return a `PreflightResult` where `pass = false` and `findings` contains at
   least one `{ layer: 2, rule: 'build-gate-failed', severity: 'error', ... }`
   finding on failure.
4. Return `pass = true` with an empty `findings` array on success.

The build command used by the Evidence renderer:

```sh
npx evidence build --outDir .evidence/build
```

A non-zero exit code propagates as a hard error that blocks deployment.

---

## 7. How to Add a New Renderer Plugin

Follow these steps to scaffold a renderer (e.g. `markdown-seaborn`):

1. **Scaffold the package directory.**
   Create `viz/<name>/` with `package.json`, `tsconfig.json`, and a `src/`
   folder. Add `"@insight-kit/viz-core": "file:../core"` as a dependency.

2. **Implement the `Renderer` interface.**
   Create `viz/<name>/index.ts`:
   ```typescript
   import { type Renderer } from '@insight-kit/viz-core';
   export const myRenderer: Renderer = {
     name: '<name>',
     pageTypes: ['narrative', 'metric'],
     install: async (reportsDir, opts) => { /* ... */ },
     buildGate: async (ctx) => { /* ... */ },
     rules: [],
   };
   ```

3. **Register via `registerRenderer()`.**
   In the consumer's setup entrypoint (or `viz/sdk/index.ts`):
   ```typescript
   import { registerRenderer } from '@insight-kit/viz-core';
   import { myRenderer } from '@insight-kit/viz-<name>';
   registerRenderer(myRenderer);
   ```

4. **Add to `viz/sdk` facade.**
   Re-export the renderer from `viz/sdk/index.ts` so consumers import from a
   single surface: `import { myRenderer } from '@insight-kit/viz'`.

5. **Wire a CLI flag.**
   Add `--renderer <name>` to `viz/core/cli.ts` so `ik preflight` can select
   the active renderer at runtime.

6. **Add tests.**
   Create `viz/<name>/tests/` with at minimum:
   - A unit test for `install()` against a tmp dir.
   - A unit test for `buildGate()` with a stubbed subprocess.
   Register tests under `"scripts": { "test": "bun test" }` in the package.

7. **Publish.**
   Add the package to the root workspace (`viz/*` glob picks it up
   automatically). Run `bun run typecheck` and `bun test` from repo root before
   tagging.

---

## 8. Versioning + Compatibility

- The `Renderer` interface follows **semver**. Adding optional fields is minor;
  removing or changing existing fields is **major**.
- Current interface version: **0.1** (pre-stable). Breaking changes are
  expected before 1.0.
- When the interface changes, bump `@insight-kit/viz-core` major version and
  update all renderer packages to implement the new surface.
- Consumers should pin `@insight-kit/viz-core` with a caret range
  (`"^0.1.0"`) and review the changelog on each minor bump during the 0.x
  series.

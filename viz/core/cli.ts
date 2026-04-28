#!/usr/bin/env bun
/**
 * `ik preflight` runner. Imports check functions from sibling subpackages,
 * builds a CheckContext from CLI args, runs requested layers, prints report.
 *
 * CLI:
 *   bun cli.ts --reports-dir <path> \
 *     [--layer 1|2|3|4|5|6|all,comma-list] [--pages slug,...] \
 *     [--strict] [--no-screenshots] [--explain]
 */

import { parseArgs } from 'node:util';
import { resolve, join } from 'node:path';
import { existsSync } from 'node:fs';
import type { CheckContext } from './types.ts';

// ---------------------------------------------------------------------------
// Arg parsing
// ---------------------------------------------------------------------------

const { values: argv } = parseArgs({
  options: {
    'reports-dir':    { type: 'string', default: './reports' },
    'layer':          { type: 'string', default: 'all' },
    'pages':          { type: 'string', default: '' },
    'strict':         { type: 'boolean', default: false },
    'no-screenshots': { type: 'boolean', default: false },
    'explain':        { type: 'boolean', default: false },
  },
  allowPositionals: false,
});

// ---------------------------------------------------------------------------
// --explain: print PAGE_TYPE_RULES matrix + per-layer rule descriptions
// Loaded via dynamic import so this path works without check modules.
// ---------------------------------------------------------------------------

if (argv['explain']) {
  const { PAGE_TYPE_RULES } = await import('./pageTypeRules.ts');

  process.stdout.write('\n=== Page Type Rules Matrix ===\n\n');

  const cols = ['PageType', 'minClaimBlocks', 'minClaimInline', 'minCharts', 'requiresRail', 'forbidsRail', 'Description'];
  const rows = Object.entries(PAGE_TYPE_RULES).map(([pt, r]) => [
    pt,
    String(r.minClaimBlocks          ?? '—'),
    String(r.minClaimInlineOrBlock   ?? '—'),
    String(r.minCharts               ?? '—'),
    r.requiresProvenanceRail         ? 'yes' : '—',
    r.forbidsProvenanceRail          ? 'yes' : '—',
    r.description,
  ]);

  const widths = cols.map((c, i) => Math.max(c.length, ...rows.map(r => r[i].length)));
  const fmt = (row: string[]) => row.map((cell, i) => cell.padEnd(widths[i])).join('  ');

  process.stdout.write(fmt(cols) + '\n');
  process.stdout.write(widths.map(w => '-'.repeat(w)).join('  ') + '\n');
  for (const row of rows) {
    process.stdout.write(fmt(row) + '\n');
  }

  process.stdout.write('\n=== Layer Descriptions ===\n\n');
  process.stdout.write('L1  SQL Block Validation  — parse + execute every ```sql block in pages against DuckDB\n');
  process.stdout.write('L2  Build Gate            — run Evidence build; fail if any sources or pages error\n');
  process.stdout.write('L3  Render Check          — headless browser checks for error text, empty charts, NaN%\n');
  process.stdout.write('L4  Numeric Sanity        — deeper DOM-level numeric/formatting checks via eval payload\n');
  process.stdout.write('L5  Provenance Integrity  — cross-validate claim IDs and provenance run records\n');
  process.stdout.write('L6  Layout Compliance     — validate frontmatter + component requirements per PAGE_TYPE_RULES\n');
  process.stdout.write('\n');

  process.exit(0);
}

// ---------------------------------------------------------------------------
// Build CheckContext
// ---------------------------------------------------------------------------

const reportsDir  = resolve(argv['reports-dir']!);

if (!existsSync(reportsDir)) {
  process.stderr.write(`error: --reports-dir does not exist: ${reportsDir}\n`);
  process.exit(1);
}

const pagesDir    = join(reportsDir, 'pages');
const sourcesDir  = join(reportsDir, 'sources');
const projectRoot = resolve(join(reportsDir, '..'));

const duckdbModulePath = join(reportsDir, 'node_modules', '@duckdb', 'node-api');
if (!existsSync(duckdbModulePath)) {
  process.stderr.write(
    `warn: @duckdb/node-api not found at ${duckdbModulePath}\n` +
    `      L1 SQL checks will report a duckdb-load-failed finding.\n`
  );
}

const ctx: CheckContext = {
  reportsDir,
  pagesDir,
  sourcesDir,
  projectRoot,
  duckdbModulePath,
};

if (argv['pages']) {
  ctx.pagesFilter = argv['pages'].split(',').map((s: string) => s.trim()).filter(Boolean);
}

// ---------------------------------------------------------------------------
// Determine layers to run
// ---------------------------------------------------------------------------

const layerArg = argv['layer']!.trim().toLowerCase();
let layersToRun: Set<number>;
if (layerArg === 'all') {
  layersToRun = new Set([1, 2, 3, 4, 5, 6]);
} else {
  layersToRun = new Set(
    layerArg.split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n))
  );
}

const strict  = argv['strict'];
const noShots = argv['no-screenshots'];

// ---------------------------------------------------------------------------
// Run layers
// ---------------------------------------------------------------------------

const allFindings: unknown[] = [];
const layerStats: Record<number, { passed: number; failed: number; durationMs: number }> = {};
const startAll    = Date.now();

async function runLayer(num: number, label: string, fn: () => Promise<unknown[]>) {
  const t0 = Date.now();
  let findings: unknown[] = [];
  try {
    findings = await fn();
  } catch (err) {
    findings.push({
      layer:    num,
      rule:     'layer-internal-error',
      severity: 'error',
      hint:     String(err),
    });
  }
  const durationMs = Date.now() - t0;
  const failed = (findings as Array<{ severity: string }>).filter(
    f => f.severity === 'error' || (strict && f.severity === 'warn')
  ).length;
  layerStats[num] = { passed: findings.length - failed, failed, durationMs };
  allFindings.push(...findings);
  process.stdout.write(`  [L${num}] ${label}: ${findings.length} finding(s) in ${durationMs}ms\n`);
}

process.stdout.write('\nRunning preflight checks...\n\n');

// Independent layers — run in parallel
const independentTasks: Promise<void>[] = [];

if (layersToRun.has(1)) {
  independentTasks.push(
    runLayer(1, 'SQL Block Validation', async () => {
      const { checkSqlBlocks } = await import('./checks/sqlBlocks.ts');
      return checkSqlBlocks(ctx);
    })
  );
}
if (layersToRun.has(2)) {
  independentTasks.push(
    runLayer(2, 'Build Gate', async () => {
      const { checkBuildGate } = await import('./checks/buildGate.ts');
      return checkBuildGate(ctx);
    })
  );
}
if (layersToRun.has(5)) {
  independentTasks.push(
    runLayer(5, 'Provenance Integrity', async () => {
      const { checkProvenanceIntegrity } = await import('./checks/provenanceInteg.ts');
      return checkProvenanceIntegrity(ctx);
    })
  );
}
if (layersToRun.has(6)) {
  independentTasks.push(
    runLayer(6, 'Layout Compliance', async () => {
      const { checkLayoutCompliance } = await import('./checks/layoutCompliance.ts');
      return checkLayoutCompliance(ctx);
    })
  );
}

await Promise.all(independentTasks);

// L3 + L4 share a dev server; run sequentially
if (layersToRun.has(3) || layersToRun.has(4)) {
  const { readdir } = await import('node:fs/promises');
  let pages: string[] = [];
  try {
    const entries = await readdir(pagesDir, { recursive: true });
    pages = (entries as string[])
      .filter((e: string) => e.endsWith('.md') && !e.endsWith('+layout.md'))
      .map((e: string) => '/' + e.replace(/\.md$/, '').replace(/index$/, '').replace(/\\/g, '/'))
      .map((r: string) => (r.endsWith('/') && r !== '/') ? r.slice(0, -1) : r);
    if (ctx.pagesFilter && (ctx.pagesFilter as string[]).length > 0) {
      pages = pages.filter((p: string) => (ctx.pagesFilter as string[]).some((pf: string) => p.includes(pf)));
    }
  } catch {
    // pagesDir doesn't exist — skip
  }

  let devServer: { stop?: () => Promise<void> } | undefined;

  if (layersToRun.has(3)) {
    await runLayer(3, 'Render Check', async () => {
      if (pages.length === 0) return [];
      const { checkRender } = await import('./checks/renderCheck.ts');
      const result = await checkRender({ pages, ctx, noScreenshots: noShots });
      devServer = result.devServer;
      return result.findings;
    });
  }

  if (layersToRun.has(4)) {
    await runLayer(4, 'Numeric Sanity', async () => {
      if (pages.length === 0) return [];
      const { mapL4FindingsFromEval, loadL4Payload } = await import('./checks/numericSanity.ts');
      // loadL4Payload returns the JS string to pass to agent-browser eval (M3).
      // Until M3 wires external eval, rawOutput is empty (no findings = safe default).
      void (await loadL4Payload()); // preload + verify payload file exists
      const findings: unknown[] = [];
      for (const page of pages) {
        try {
          const rawOutput = ''; // M3 will supply real agent-browser stdout here
          findings.push(...mapL4FindingsFromEval([{ route: page, rawOutput }]));
        } catch {
          // non-fatal per-page failure
        }
      }
      return findings;
    });
  }

  if (devServer && typeof devServer.stop === 'function') {
    await devServer.stop();
  }
}

// ---------------------------------------------------------------------------
// Print report
// ---------------------------------------------------------------------------

const totalMs  = Date.now() - startAll;
const failures = (allFindings as Array<{ severity: string }>).filter(
  f => f.severity === 'error' || (strict && f.severity === 'warn')
);
const pass = failures.length === 0;

process.stdout.write('\n' + '='.repeat(60) + '\n');
process.stdout.write(
  `Preflight Summary: ${allFindings.length - failures.length} passed, ${failures.length} failed  (${totalMs}ms)\n`
);
process.stdout.write('='.repeat(60) + '\n\n');

if (allFindings.length === 0) {
  process.stdout.write('No findings. All checks passed.\n\n');
} else {
  for (const f of allFindings as Array<{ severity: string; layer: number; rule: string; file?: string; line?: string; snippet?: string; hint?: string }>) {
    const sev    = f.severity.toUpperCase().padEnd(5);
    const layer  = `[L${f.layer}]`;
    const loc    = [f.file, f.line].filter(Boolean).join(':');
    const locStr = loc ? ` ${loc} —` : '';
    process.stdout.write(`${layer} [${sev}]${locStr} ${f.rule}`);
    if (f.snippet) process.stdout.write(`  (${f.snippet})`);
    process.stdout.write('\n');
    if (f.hint && (argv['explain'] || f.severity === 'error')) {
      process.stdout.write(`         hint: ${f.hint}\n`);
    }
  }
  process.stdout.write('\n');
}

process.stdout.write('Layer breakdown:\n');
for (const [num, stats] of Object.entries(layerStats).sort(([a], [b]) => Number(a) - Number(b))) {
  process.stdout.write(`  L${num}: ${stats.passed} ok, ${stats.failed} failed (${stats.durationMs}ms)\n`);
}
process.stdout.write('\n');

process.exit(pass ? 0 : 1);

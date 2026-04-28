#!/usr/bin/env bun
/**
 * build_indexes.ts — generate index pages for claims by tier and reasoning trees.
 *
 * Produces:
 *   1. <reports-dir>/pages/index/by-tier.md — All claims grouped by tier with Evidence DataTable
 *   2. <reports-dir>/pages/index/trees.md   — ClaimTree components from each Tier-I claim
 *
 * Usage:
 *   bun build_indexes.ts --project-root /path/to/consumer
 *   bun build_indexes.ts --project-root /path/to/consumer --reports-dir /path/to/reports
 *   bun build_indexes.ts --project-root /path/to/consumer --db /path/to/file.duckdb
 */

import { createRequire } from 'node:module';
import { parseArgs } from 'node:util';
import { join, resolve, basename } from 'node:path';
import fs from 'node:fs';

// ── CLI args ─────────────────────────────────────────────────────────────────

const { values: args } = parseArgs({
  options: {
    'project-root': { type: 'string' },
    'reports-dir':  { type: 'string' },
    'db':           { type: 'string' },
    'runs-dir':     { type: 'string' },
  },
  strict: false,
});

if (!args['project-root']) {
  console.error('ERROR: --project-root is required.');
  console.error('  bun build_indexes.ts --project-root /path/to/consumer');
  process.exit(1);
}

const PROJECT_ROOT = resolve(args['project-root']!);
const REPORTS_DIR  = args['reports-dir'] ? resolve(args['reports-dir']) : join(PROJECT_ROOT, 'reports');
const RUNS_DIR     = args['runs-dir']    ? resolve(args['runs-dir'])    : join(PROJECT_ROOT, '.insight-kit', 'runs');

// Derive DB path from .insight-kit/duckdb/, fall back to project dir name
function inferDbPath(): string {
  const duckDir = join(PROJECT_ROOT, '.insight-kit', 'duckdb');
  if (fs.existsSync(duckDir)) {
    const files = fs.readdirSync(duckDir).filter(f => f.endsWith('.duckdb'));
    if (files.length > 0) return join(duckDir, files[0]);
  }
  const name = basename(PROJECT_ROOT);
  return join(PROJECT_ROOT, '.insight-kit', 'duckdb', `${name}.duckdb`);
}

const DB_PATH    = args['db'] ? resolve(args['db']) : inferDbPath();
const PAGES_DIR  = join(REPORTS_DIR, 'pages', 'index');

// ── Load @duckdb/node-api from consumer's reports/node_modules ───────────────

function loadDuckDb(reportsDir: string): { DuckDBInstance: { create(path: string): Promise<{ connect(): Promise<{ run(sql: string): Promise<{ getRows(): Promise<unknown[][]> }>; closeSync(): void }> }> } } {
  const pkgJson = resolve(reportsDir, 'package.json');
  let consumerRequire: NodeRequire;
  try {
    consumerRequire = createRequire(pkgJson);
  } catch {
    consumerRequire = createRequire(resolve(reportsDir, 'index.js'));
  }
  try {
    return consumerRequire('@duckdb/node-api');
  } catch {
    console.error(`ERROR: @duckdb/node-api not found in ${reportsDir}/node_modules.`);
    console.error('  Run `npm install` in the reports dir first.');
    process.exit(1);
  }
}

const { DuckDBInstance } = loadDuckDb(REPORTS_DIR);

// ── Tier helpers ─────────────────────────────────────────────────────────────

const TIER_DISPLAY: Record<string, string> = {
  initiative:      'Initiative (I)',
  counterfactual:  'Counterfactual (C)',
  causal:          'Causal (C)',
  critic:          'Critic (X)',
  derived:         'Derived (D)',
  raw:             'Raw (R)',
  etl_metric:      'Other',
  viz:             'Other',
};

const TIER_ORDER: Record<string, number> = {
  initiative: 0,
  causal: 1,
  counterfactual: 2,
  critic: 3,
  derived: 4,
  raw: 5,
};

function normalizeTier(tier: string): string {
  const t = (tier || '').toLowerCase().trim();
  const map: Record<string, string> = {
    initiative:     'initiative',
    causal:         'causal',
    counterfactual: 'counterfactual',
    critic:         'critic',
    derived:        'derived',
    raw:            'raw',
    etl_metric:     'Other',
    viz:            'Other',
  };
  return map[t] || 'Other';
}

function tierDisplayName(tier: string): string {
  return TIER_DISPLAY[tier] || tier;
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  if (!fs.existsSync(DB_PATH)) {
    console.error(`[ERR] DuckDB not found: ${DB_PATH}`);
    console.error("      Run 'python3 build_evidence_views.py --project-root " + PROJECT_ROOT + "' first");
    process.exit(1);
  }

  console.log(`Project root : ${PROJECT_ROOT}`);
  console.log(`Reports dir  : ${REPORTS_DIR}`);
  console.log(`DuckDB       : ${DB_PATH}`);
  console.log(`Output       : ${PAGES_DIR}/\n`);

  fs.mkdirSync(PAGES_DIR, { recursive: true });

  console.log(`Connecting to DuckDB: ${DB_PATH}`);
  const instance = await DuckDBInstance.create(DB_PATH);
  const con = await instance.connect();

  async function run(sql: string): Promise<unknown[][]> {
    const result = await con.run(sql);
    return result.getRows();
  }

  // ── by-tier.md ──────────────────────────────────────────────────────────────
  console.log('Building by-tier index...');

  const tierCountRows = await run(`
    SELECT tier, COUNT(*) as cnt
    FROM claims_manifest
    GROUP BY tier
    ORDER BY tier
  `) as [string, number][];

  const tierCounts: Record<string, number> = {};
  for (const [tier, cnt] of tierCountRows) {
    const norm = normalizeTier(tier);
    tierCounts[norm] = (tierCounts[norm] || 0) + Number(cnt);
  }

  const sortedTiers = Object.keys(tierCounts).sort(
    (a, b) => (TIER_ORDER[a] ?? 999) - (TIER_ORDER[b] ?? 999)
  );

  const total = Object.values(tierCounts).reduce((s, n) => s + n, 0);

  const btLines = [
    '---',
    'title: All Claims by Tier',
    '---',
    '',
    '```sql kpis',
    'select',
    "  count(*) filter (where lower(tier)='initiative')      as initiative_count,",
    "  count(*) filter (where lower(tier) in ('causal','counterfactual')) as causal_count,",
    "  count(*) filter (where lower(tier)='raw')             as raw_count,",
    '  count(*) as total',
    'from claims_manifest',
    '```',
    '',
    '## Summary',
    '',
    '<BigValue',
    '  data={kpis}',
    '  title="Total Claims"',
    '  value=total',
    '/>',
    '',
  ];

  btLines.push('| Tier | Count |', '|------|-------|');
  for (const tier of sortedTiers) {
    btLines.push(`| ${tierDisplayName(tier)} | ${tierCounts[tier]} |`);
  }
  btLines.push(`\n**Total:** ${total} claims\n`);

  for (const tier of sortedTiers) {
    const tierLc = tier.toLowerCase().replace(/[^a-z0-9]/g, '_');
    const cnt = tierCounts[tier];
    btLines.push(`## ${tierDisplayName(tier)} (${cnt})`, '');

    btLines.push(
      `\`\`\`sql tier_${tierLc}`,
      'select',
      '  claim_id,',
      "  replace(replace(replace(statement, '&', '&amp;'), '<', '&lt;'), '>', '&gt;') as statement,",
      '  confidence,',
      '  run_id',
      'from claims_manifest',
      `where lower(tier) = '${tier.toLowerCase()}'`,
      'order by claim_id',
      '```',
      '',
    );

    btLines.push(
      `<DataTable data={tier_${tierLc}} search=true>`,
      '  <Column id="claim_id" title="Claim ID" />',
      '  <Column id="statement" title="Statement" />',
      '  <Column id="confidence" title="Conf" />',
      '  <Column id="run_id" title="Run" />',
      '</DataTable>',
      '',
    );
  }

  const byTierPath = join(PAGES_DIR, 'by-tier.md');
  fs.writeFileSync(byTierPath, btLines.join('\n'), 'utf8');
  console.log(`  [${fs.statSync(byTierPath).size} bytes] ${byTierPath}`);

  // ── trees.md ─────────────────────────────────────────────────────────────────
  console.log('Building reasoning trees...');

  const tierIRows = await run(`
    SELECT claim_id, tier, statement, confidence, run_id
    FROM claims_manifest
    WHERE LOWER(tier) = 'initiative'
    ORDER BY claim_id
  `) as [string, string, string, number, string][];

  const treesLines = [
    '---',
    'title: Reasoning Trees',
    'description: Ancestry from each Tier-I claim down to raw data',
    '---',
    '',
  ];

  const treesGenerated: { claimId: string }[] = [];

  for (const [claimId, , statement] of tierIRows) {
    const stmt = statement && statement.length > 80
      ? statement.slice(0, 77) + '...'
      : (statement || '');

    treesLines.push(`## ${claimId}`, '', `**${stmt}**`, '');

    const treeSqlName = `tree_${claimId.toLowerCase().replace(/[^a-z0-9]/g, '_')}`;

    treesLines.push(
      `\`\`\`sql ${treeSqlName}`,
      'with recursive anc as (',
      `  select claim_id, null::varchar as parent_id, 0 as depth, tier, statement, confidence`,
      `  from claims_manifest where claim_id = '${claimId}'`,
      '  union all',
      '  select c.claim_id, e.from_id as parent_id, anc.depth + 1, c.tier, c.statement, c.confidence',
      '  from claim_edges e',
      '  join claims_manifest c on c.claim_id = e.to_id',
      '  join anc on anc.claim_id = e.from_id',
      "  where e.edge_type in ('input_claims', 'supports')",
      '    and anc.depth < 8',
      ')',
      'select distinct',
      '  claim_id,',
      '  parent_id,',
      '  depth,',
      '  tier,',
      "  replace(replace(replace(statement, '&', '&amp;'), '<', '&lt;'), '>', '&gt;') as statement,",
      '  confidence',
      'from anc',
      'order by depth, claim_id',
      '```',
      '',
      `<ClaimTree data={${treeSqlName}} root="${claimId}" />`,
      '',
      `[View provenance for ${claimId}](/provenance/${claimId})`,
      '',
    );

    treesGenerated.push({ claimId });
  }

  const treesPath = join(PAGES_DIR, 'trees.md');
  fs.writeFileSync(treesPath, treesLines.join('\n'), 'utf8');
  console.log(`  [${fs.statSync(treesPath).size} bytes] ${treesPath}`);

  con.closeSync();

  console.log(`\nIndex generation complete:`);
  console.log(`  by-tier.md: ${fs.statSync(byTierPath).size} bytes`);
  console.log(`  trees.md:   ${fs.statSync(treesPath).size} bytes`);
  console.log(`  Trees generated: ${treesGenerated.length}`);
}

main().catch(err => {
  console.error('[FATAL]', err);
  process.exit(1);
});

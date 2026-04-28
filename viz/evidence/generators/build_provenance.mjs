#!/usr/bin/env node
/**
 * build_provenance.mjs — generate per-claim provenance receipt pages (ESM).
 *
 * For each claim with tier in {initiative, causal}, walks ancestors recursively
 * via input_claims + supports edges, emitting linear top-down provenance chains
 * as Markdown pages safe for Evidence / Svelte (HTML-escaped statements).
 *
 * Output:
 *   <reports-dir>/pages/provenance/<claim_id>.md   — individual receipt page
 *   <reports-dir>/pages/provenance/index.md        — index of all receipts
 *
 * Usage:
 *   node build_provenance.mjs --project-root /path/to/consumer
 *   node build_provenance.mjs --project-root /path/to/consumer --reports-dir /path/to/reports
 *   node build_provenance.mjs --project-root /path/to/consumer --db /path/to/file.duckdb
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
  console.error('  node build_provenance.mjs --project-root /path/to/consumer');
  process.exit(1);
}

const PROJECT_ROOT  = resolve(args['project-root']);
const REPORTS_DIR   = args['reports-dir']  ? resolve(args['reports-dir'])  : join(PROJECT_ROOT, 'reports');
const RUNS_DIR      = args['runs-dir']     ? resolve(args['runs-dir'])     : join(PROJECT_ROOT, '.insight-kit', 'runs');

// Derive DB basename from the first *.duckdb file found in .insight-kit/duckdb/, fall back to project dir name
function inferDbPath() {
  const duckDir = join(PROJECT_ROOT, '.insight-kit', 'duckdb');
  if (fs.existsSync(duckDir)) {
    const files = fs.readdirSync(duckDir).filter(f => f.endsWith('.duckdb'));
    if (files.length > 0) return join(duckDir, files[0]);
  }
  const name = basename(PROJECT_ROOT);
  return join(PROJECT_ROOT, '.insight-kit', 'duckdb', `${name}.duckdb`);
}

const DB_PATH       = args['db'] ? resolve(args['db']) : inferDbPath();
const PROVENANCE_DIR = join(REPORTS_DIR, 'pages', 'provenance');

// ── Load @duckdb/node-api from consumer's reports/node_modules ───────────────

function loadDuckDb(reportsDir) {
  const pkgJson = resolve(reportsDir, 'package.json');
  let consumerRequire;
  try {
    consumerRequire = createRequire(pkgJson);
  } catch {
    // package.json may not exist yet; use reportsDir directly as base
    consumerRequire = createRequire(resolve(reportsDir, 'index.js'));
  }
  try {
    return consumerRequire('@duckdb/node-api');
  } catch (err) {
    console.error(`ERROR: @duckdb/node-api not found in ${reportsDir}/node_modules.`);
    console.error('  Run `npm install` in the reports dir first.');
    process.exit(1);
  }
}

const { DuckDBInstance } = loadDuckDb(REPORTS_DIR);

// ── Helpers ──────────────────────────────────────────────────────────────────

/** HTML-escape text to prevent Svelte/markdown-it treating < > & as HTML/tags. */
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Truncate string to maxLen chars. */
function truncate(str, maxLen) {
  if (!str) return '';
  return str.length > maxLen ? str.slice(0, maxLen - 3) + '...' : str;
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  if (!fs.existsSync(DB_PATH)) {
    console.error(`ERROR: DuckDB not found at ${DB_PATH}`);
    console.error('Run: python3 build_evidence_views.py --project-root ' + PROJECT_ROOT);
    process.exit(1);
  }

  console.log(`Project root : ${PROJECT_ROOT}`);
  console.log(`Reports dir  : ${REPORTS_DIR}`);
  console.log(`DuckDB       : ${DB_PATH}`);
  console.log(`Output       : ${PROVENANCE_DIR}/\n`);

  const instance = await DuckDBInstance.create(DB_PATH);
  const con = await instance.connect();

  /**
   * Run a parameterized query using positional ? placeholders.
   * Returns array of row-arrays.
   */
  async function query(sql, params = []) {
    let s = sql;
    for (const p of params) {
      const escaped = typeof p === 'string' ? `'${p.replace(/'/g, "''")}'` : p;
      s = s.replace('?', escaped);
    }
    const result = await con.run(s);
    return result.getRows();
  }

  // Fetch all Initiative and Causal tier claims
  const focalRows = await query(`
    SELECT claim_id, tier, statement
    FROM claims_manifest
    WHERE LOWER(tier) IN ('initiative', 'causal')
    ORDER BY tier, claim_id
  `);

  if (focalRows.length === 0) {
    console.log('No claims with tier in {initiative, causal} found.');
    con.closeSync();
    process.exit(0);
  }

  console.log(`Found ${focalRows.length} focal claims (tier I or C).\n`);

  // Build ancestor walker using a DFS over claim_edges
  async function getAncestors(claimId) {
    const visited = new Set();
    const order = [];

    async function visit(cid) {
      if (visited.has(cid)) return;
      visited.add(cid);

      const ancestors = await query(`
        SELECT DISTINCT to_id
        FROM claim_edges
        WHERE from_id = ? AND edge_type IN ('input_claims', 'supports')
        ORDER BY to_id
      `, [cid]);

      for (const [ancestorId] of ancestors) {
        await visit(ancestorId);
      }
      order.push(cid);
    }

    await visit(claimId);
    return order;
  }

  async function buildChainMarkdown(focalClaimId, ancestors) {
    const focalRows2 = await query(`
      SELECT claim_id, tier, statement, confidence, run_id, agent_id
      FROM claims_manifest
      WHERE claim_id = ?
      LIMIT 1
    `, [focalClaimId]);

    if (focalRows2.length === 0) {
      throw new Error(`Claim ${focalClaimId} not found in claims_manifest`);
    }

    const [focalId, focalTier, focalStmt] = focalRows2[0];

    const description = escHtml(truncate(focalStmt, 80));

    const lines = [
      '---',
      `title: "Provenance: ${focalId}"`,
      `description: "${description}"`,
      'hide_sidebar: true',
      '---',
      '',
      '```sql focal_claim',
      `select claim_id, tier, statement, confidence, run_id, agent_id`,
      `from claims_manifest where claim_id = '${focalId}' limit 1`,
      '```',
      '',
    ];

    // Breadcrumb
    lines.push(
      '<div class="dock-breadcrumb">',
      '  <a href="/">Home</a>',
      '  <span class="sep">/</span>',
      '  <a href="/provenance">Provenance</a>',
      '  <span class="sep">/</span>',
      `  <span class="current">${focalId}</span>`,
      '</div>',
      '',
      `# Provenance: ${focalId}`,
      '',
    );

    const safeStmt = escHtml(focalStmt);
    lines.push(
      `<div class="page-tagline">Linear provenance chain for <strong>${focalId}</strong> (${focalTier}). Trace from recommendation to finding to decomposition to raw data.</div>`,
      '',
      '---',
      '',
      '## Provenance Chain',
      '',
    );

    // Emit one SQL block per ancestor, then render with ClaimBlock
    if (ancestors.length > 0) {
      // Verify which ancestors exist in claims_manifest
      const placeholders = ancestors.map(() => '?').join(', ');
      const existingRows = await query(`
        SELECT claim_id
        FROM claims_manifest
        WHERE claim_id IN (${placeholders})
      `, ancestors);
      const existingSet = new Set(existingRows.map(r => r[0]));

      // Emit SQL blocks first (Evidence requires them before component refs)
      for (const ancestorId of ancestors) {
        if (!existingSet.has(ancestorId)) {
          lines.push(`<!-- Skipped ${ancestorId}: not in claims_manifest -->`);
          continue;
        }
        // Safe SQL alias: replace hyphens and dots with underscores
        const alias = `chain_${ancestorId.replace(/[^a-zA-Z0-9]/g, '_')}`;
        lines.push(
          `\`\`\`sql ${alias}`,
          `select claim_id, tier, statement, confidence, run_id, agent_id`,
          `from claims_manifest where claim_id = '${ancestorId}' limit 1`,
          '```',
          '',
        );
      }

      // Emit ClaimBlock components with chain-arrow separators
      const validAncestors = ancestors.filter(id => existingSet.has(id));
      for (let i = 0; i < validAncestors.length; i++) {
        const ancestorId = validAncestors[i];
        const alias = `chain_${ancestorId.replace(/[^a-zA-Z0-9]/g, '_')}`;

        lines.push(
          `<ClaimBlock claim={${alias}[0]} />`,
          '',
        );

        if (i < validAncestors.length - 1) {
          lines.push(
            '<div class="provenance-arrow">',
            '  <span class="chain-arrow">&#x2193;</span>',
            '  <span class="chain-label">derived from</span>',
            '</div>',
            '',
          );
        }
      }
    }

    return lines.join('\n');
  }

  fs.mkdirSync(PROVENANCE_DIR, { recursive: true });

  const generatedPages = [];
  for (const [claimId, tier, statement] of focalRows) {
    try {
      const ancestors = await getAncestors(claimId);
      const markdown = await buildChainMarkdown(claimId, ancestors);

      const pagePath = join(PROVENANCE_DIR, `${claimId}.md`);
      fs.writeFileSync(pagePath, markdown, 'utf8');

      generatedPages.push([claimId, tier, statement]);
      console.log(`  [OK] ${claimId} (${tier}) — ${ancestors.length} nodes in chain`);
    } catch (err) {
      console.error(`  [ERR] ${claimId}: ${err.message}`);
    }
  }

  // Generate index page
  const indexLines = [
    '---',
    'title: "Provenance Index"',
    'description: "Linear provenance receipts: one per Tier-I or Tier-C claim."',
    '---',
    '',
    '<div class="dock-breadcrumb">',
    '  <a href="/">Home</a>',
    '  <span class="sep">/</span>',
    '  <span class="current">Provenance</span>',
    '</div>',
    '',
    '# Provenance Index',
    '',
    '<div class="page-tagline">Linear provenance receipts for each initiative and causal claim. Each page traces the claim\'s ancestors from top-level finding to decomposed findings to raw data sources.</div>',
    '',
    '---',
    '',
  ];

  // Group by tier
  const byTier = {};
  for (const [claimId, tier, statement] of generatedPages) {
    if (!byTier[tier]) byTier[tier] = [];
    byTier[tier].push([claimId, tier, statement]);
  }

  const tierOrder = ['initiative', 'causal'];
  for (const tier of tierOrder) {
    if (!byTier[tier]) continue;

    const tierLabel = tier === 'initiative' ? 'Initiatives' : 'Causal Claims';
    indexLines.push(`## ${tierLabel}`, '');

    for (const [claimId, , statement] of byTier[tier]) {
      const preview = statement.length > 73 ? statement.slice(0, 70) + '...' : statement;
      indexLines.push(`- **[${claimId}](/provenance/${claimId})**: ${escHtml(preview)}`);
    }
    indexLines.push('');
  }

  const indexPath = join(PROVENANCE_DIR, 'index.md');
  fs.writeFileSync(indexPath, indexLines.join('\n'), 'utf8');

  con.closeSync();

  console.log(`\n[OK] Generated ${generatedPages.length} provenance pages + index.md`);
  console.log(`  Output: ${PROVENANCE_DIR}/`);
}

main().catch(err => {
  console.error('[FATAL]', err);
  process.exit(1);
});

/**
 * Unit tests for layoutCompliance.ts (L6 check)
 *
 * Uses Node built-in test runner. Creates fixture .md files in a tmp dir.
 */

import { test } from 'node:test';
import * as assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import { checkLayoutCompliance } from '../layoutCompliance.ts';
import type { CheckContext } from '@insight-kit/viz-core/types.ts';

async function makeTmpDir(): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), 'layout-compliance-test-'));
}

async function makeCtx(tmpDir: string, overrides: Partial<CheckContext> = {}): Promise<CheckContext> {
  const pagesDir = path.join(tmpDir, 'pages');
  await fs.mkdir(pagesDir, { recursive: true });
  return {
    reportsDir: tmpDir,
    pagesDir,
    sourcesDir: path.join(tmpDir, 'sources'),
    projectRoot: tmpDir,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Helper: write a page with given frontmatter + body
// ---------------------------------------------------------------------------
async function writePage(pagesDir: string, name: string, frontmatter: string, body: string): Promise<string> {
  const filePath = path.join(pagesDir, name);
  const content = `---\n${frontmatter}\n---\n${body}`;
  await fs.writeFile(filePath, content, 'utf8');
  return filePath;
}

// ---------------------------------------------------------------------------
// Test: no frontmatter = no findings
// ---------------------------------------------------------------------------
test('checkLayoutCompliance emits nothing for pages without frontmatter', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    await fs.writeFile(
      path.join(ctx.pagesDir, 'no-fm.md'),
      '# Hello\nNo frontmatter here.\n',
      'utf8'
    );
    const findings = await checkLayoutCompliance(ctx);
    assert.equal(findings.length, 0);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: missing layout_type emits warn
// ---------------------------------------------------------------------------
test('checkLayoutCompliance warns when layout_type is absent', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    await writePage(ctx.pagesDir, 'page.md', 'title: My Page', '# Body\n');
    const findings = await checkLayoutCompliance(ctx);
    const warn = findings.find(f => f.rule === 'layout-type-missing');
    assert.ok(warn, 'Expected layout-type-missing finding');
    assert.equal(warn!.severity, 'warn');
    assert.equal(warn!.layer, 6);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: valid receipt page — no findings
// ---------------------------------------------------------------------------
test('checkLayoutCompliance passes a well-formed receipt page', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    const fm = 'layout_type: receipt\nhide_sidebar: true';
    const body = '<ClaimBlock id="c1" />\n';
    await writePage(ctx.pagesDir, 'receipt.md', fm, body);
    const findings = await checkLayoutCompliance(ctx);
    assert.equal(findings.length, 0, `Unexpected findings: ${JSON.stringify(findings)}`);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: receipt page missing hide_sidebar + missing ClaimBlock + has ProvenanceRail
// ---------------------------------------------------------------------------
test('checkLayoutCompliance catches multiple violations on receipt page', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    const fm = 'layout_type: receipt\nhide_sidebar: false';
    const body = 'No claims here.\n<ProvenanceRail />\n';
    await writePage(ctx.pagesDir, 'bad-receipt.md', fm, body);
    const findings = await checkLayoutCompliance(ctx);

    const rules = findings.map(f => f.rule);
    assert.ok(rules.includes('required-frontmatter-missing'), 'Should flag hide_sidebar mismatch');
    assert.ok(rules.includes('min-claim-blocks'), 'Should flag missing ClaimBlock');
    assert.ok(rules.includes('provenance-rail-forbidden'), 'Should flag forbidden ProvenanceRail');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: narrative page without ProvenanceRail
// ---------------------------------------------------------------------------
test('checkLayoutCompliance flags narrative page missing ProvenanceRail', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    const fm = 'layout_type: narrative';
    const body = '<ClaimInline id="c1" /> Some narrative text.\n';
    await writePage(ctx.pagesDir, 'narr.md', fm, body);
    const findings = await checkLayoutCompliance(ctx);

    const railFinding = findings.find(f => f.rule === 'provenance-rail-required');
    assert.ok(railFinding, 'Expected provenance-rail-required finding');
    assert.equal(railFinding!.severity, 'error');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: investigation page missing minCharts
// ---------------------------------------------------------------------------
test('checkLayoutCompliance flags investigation page missing charts', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    const fm = 'layout_type: investigation';
    const body = '<ClaimBlock id="c1" />\n<!-- no charts -->\n';
    await writePage(ctx.pagesDir, 'invest.md', fm, body);
    const findings = await checkLayoutCompliance(ctx);

    const chartFinding = findings.find(f => f.rule === 'min-charts');
    assert.ok(chartFinding, 'Expected min-charts finding');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: unknown layout_type emits warn
// ---------------------------------------------------------------------------
test('checkLayoutCompliance warns for unknown layout_type', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    const fm = 'layout_type: banana_page';
    await writePage(ctx.pagesDir, 'unknown.md', fm, '# Content\n');
    const findings = await checkLayoutCompliance(ctx);

    const unknownFinding = findings.find(f => f.rule === 'layout-type-unknown');
    assert.ok(unknownFinding, 'Expected layout-type-unknown finding');
    assert.equal(unknownFinding!.severity, 'warn');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

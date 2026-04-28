/**
 * Integration test: preflight flow (L1 + L6) against a tmp Evidence project fixture.
 */
import { describe, test, expect, afterAll } from 'bun:test';
import * as os from 'node:os';
import * as path from 'node:path';
import * as fs from 'node:fs/promises';
import { checkLayoutCompliance } from '../../checks/layoutCompliance.js';
import type { CheckContext, Finding } from '../../types.js';

// ---------------------------------------------------------------------------
// Fixture setup
// ---------------------------------------------------------------------------

const TMP_DIR = path.join(os.tmpdir(), `insight-kit-test-${Math.random().toString(36).slice(2)}`);
const REPORTS_DIR = path.join(TMP_DIR, 'reports');
const PAGES_DIR   = path.join(REPORTS_DIR, 'pages');
const SOURCES_DIR = path.join(REPORTS_DIR, 'sources');

async function writeFixture(relPath: string, content: string) {
  const abs = path.join(REPORTS_DIR, relPath);
  await fs.mkdir(path.dirname(abs), { recursive: true });
  await fs.writeFile(abs, content, 'utf8');
}

async function buildCtx(): Promise<CheckContext> {
  return {
    reportsDir:  REPORTS_DIR,
    pagesDir:    PAGES_DIR,
    sourcesDir:  SOURCES_DIR,
    projectRoot: TMP_DIR,
  };
}

// Create fixture once before all tests
let ctx: CheckContext;

async function setup() {
  await fs.mkdir(PAGES_DIR, { recursive: true });
  await fs.mkdir(SOURCES_DIR, { recursive: true });

  // evidence.config.yaml stub
  await writeFixture('evidence.config.yaml', 'sources:\n  - name: x\n');

  // sources/x/y.sql
  await writeFixture('sources/x/y.sql', 'SELECT 1 AS n');

  // page WITH frontmatter but NO layout_type → should trigger layout_type_missing
  await writeFixture('pages/no-layout.md', '---\ntitle: No Layout\n---\n\n# No layout type here\n');

  // page WITH valid layout_type → should PASS L6
  await writeFixture(
    'pages/good-metric.md',
    '---\nlayout_type: metric\ntitle: Good Metric\n---\n\n<LineChart data={sales} />\n'
  );

  // page with NO frontmatter at all → should be ignored by L6
  await writeFixture('pages/no-frontmatter.md', '# Plain page\n\nNo frontmatter at all.\n');

  ctx = await buildCtx();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('preflightFlow integration', () => {
  test('setup fixture', async () => {
    await setup();
    const stat = await fs.stat(PAGES_DIR);
    expect(stat.isDirectory()).toBe(true);
  });

  test('PreflightResult has expected shape from checkLayoutCompliance', async () => {
    const findings: Finding[] = await checkLayoutCompliance(ctx);
    expect(Array.isArray(findings)).toBe(true);
    for (const f of findings) {
      expect(typeof f.layer).toBe('number');
      expect(typeof f.rule).toBe('string');
      expect(['error', 'warn', 'info']).toContain(f.severity);
    }
  });

  test('L6 catches layout_type_missing on page without layout_type in frontmatter', async () => {
    const findings = await checkLayoutCompliance(ctx);
    const missingFindings = findings.filter(f =>
      f.rule === 'layout-type-missing' && f.file?.includes('no-layout')
    );
    expect(missingFindings.length).toBeGreaterThan(0);
    expect(missingFindings[0]!.layer).toBe(6);
    expect(missingFindings[0]!.severity).toBe('warn');
  });

  test('L6 passes page WITH proper layout_type frontmatter', async () => {
    const findings = await checkLayoutCompliance(ctx);
    const goodFindings = findings.filter(f => f.file?.includes('good-metric'));
    expect(goodFindings.length).toBe(0);
  });

  test('L6 ignores page with no frontmatter at all', async () => {
    const findings = await checkLayoutCompliance(ctx);
    const noFm = findings.filter(f => f.file?.includes('no-frontmatter'));
    expect(noFm.length).toBe(0);
  });
});

afterAll(async () => {
  await fs.rm(TMP_DIR, { recursive: true, force: true });
});

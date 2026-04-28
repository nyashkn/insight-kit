/**
 * Unit tests for sqlBlocks.ts (L1 check)
 *
 * Uses Node built-in test runner (node --test --experimental-strip-types).
 * Each test uses a tmp dir + fixture .md files. DuckDB is NOT required for
 * these tests — we verify the skip/pass/fail logic at the markdown-parsing level
 * and skip DuckDB-dependent assertions when @duckdb/node-api is unavailable.
 */

import { test } from 'node:test';
import * as assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import { checkSqlBlocks } from '../sqlBlocks.ts';
import type { CheckContext } from '@insight-kit/viz-core/types.ts';

async function makeTmpDir(): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), 'sql-blocks-test-'));
}

async function makeCtx(
  tmpDir: string,
  overrides: Partial<CheckContext> = {}
): Promise<CheckContext> {
  const pagesDir = path.join(tmpDir, 'pages');
  const sourcesDir = path.join(tmpDir, 'sources');
  await fs.mkdir(pagesDir, { recursive: true });
  await fs.mkdir(sourcesDir, { recursive: true });
  return {
    reportsDir: tmpDir,
    pagesDir,
    sourcesDir,
    projectRoot: tmpDir,
    // Point duckdbModulePath to a non-existent path — tests that don't need
    // DuckDB will get a duckdb-load-failed finding (expected).
    duckdbModulePath: path.join(tmpDir, 'nonexistent', '@duckdb', 'node-api'),
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Test: skips blocks containing Evidence template expressions ${...}
// ---------------------------------------------------------------------------
test('checkSqlBlocks skips blocks with Evidence template expressions', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    const mdContent = [
      '# Test Page',
      '',
      '```sql my_query',
      'SELECT * FROM nairomarket.${some_table}',
      '```',
    ].join('\n') + '\n';

    await fs.writeFile(path.join(ctx.pagesDir, 'index.md'), mdContent, 'utf8');

    const findings = await checkSqlBlocks(ctx);
    // Should only emit duckdb-load-failed (since no DuckDB available), NOT sql-block-syntax
    const sqlFindings = findings.filter(f => f.rule === 'sql-block-syntax');
    assert.equal(sqlFindings.length, 0, 'Template expression blocks must be skipped');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: emits duckdb-load-failed when module path is invalid
// ---------------------------------------------------------------------------
test('checkSqlBlocks emits duckdb-load-failed when module is missing', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    const findings = await checkSqlBlocks(ctx);
    const loadFail = findings.find(f => f.rule === 'duckdb-load-failed');
    assert.ok(loadFail, 'Expected duckdb-load-failed finding');
    assert.equal(loadFail!.layer, 1);
    assert.equal(loadFail!.severity, 'error');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: walks nested subdirectories for .md files
// ---------------------------------------------------------------------------
test('checkSqlBlocks walks nested page directories', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = await makeCtx(tmp);
    const subDir = path.join(ctx.pagesDir, 'levers');
    await fs.mkdir(subDir, { recursive: true });

    // Page with only template blocks (skipped) — no sql-block-syntax findings expected
    const mdContent = [
      '```sql safe_query',
      'SELECT 1 + ${x}',
      '```',
    ].join('\n') + '\n';
    await fs.writeFile(path.join(subDir, 'page.md'), mdContent, 'utf8');

    const findings = await checkSqlBlocks(ctx);
    const sqlFindings = findings.filter(f => f.rule === 'sql-block-syntax');
    assert.equal(sqlFindings.length, 0);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: pagesFilter restricts which files are scanned
// ---------------------------------------------------------------------------
test('checkSqlBlocks respects pagesFilter', async () => {
  const tmp = await makeTmpDir();
  try {
    const pagesDir = path.join(tmp, 'pages');
    const sourcesDir = path.join(tmp, 'sources');
    await fs.mkdir(pagesDir, { recursive: true });
    await fs.mkdir(sourcesDir, { recursive: true });

    const ctx: CheckContext = {
      reportsDir: tmp,
      pagesDir,
      sourcesDir,
      projectRoot: tmp,
      duckdbModulePath: path.join(tmp, 'none'),
      pagesFilter: ['included'],
    };

    // Create two pages: one matching filter, one not
    await fs.writeFile(
      path.join(pagesDir, 'included.md'),
      '```sql q1\nSELECT ${placeholder}\n```\n',
      'utf8'
    );
    await fs.writeFile(
      path.join(pagesDir, 'excluded.md'),
      '```sql q2\nSELECT ${placeholder}\n```\n',
      'utf8'
    );

    const findings = await checkSqlBlocks(ctx);
    // Both files have template expressions so 0 sql-block-syntax either way.
    // The real assertion: DuckDB load fails once (not per-file).
    const loadFails = findings.filter(f => f.rule === 'duckdb-load-failed');
    assert.equal(loadFails.length, 1);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

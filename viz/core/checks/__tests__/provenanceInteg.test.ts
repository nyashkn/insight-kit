/**
 * Unit tests for provenanceInteg.ts (L5 check)
 *
 * Uses Node built-in test runner. Creates .insight-kit/runs/ fixture dirs with
 * claims.jsonl files to simulate real provenance data.
 */

import { test } from 'node:test';
import * as assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import { checkProvenanceIntegrity } from '../provenanceInteg.ts';
import type { CheckContext } from '@insight-kit/viz-core/types.ts';

async function makeTmpDir(): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), 'provenance-test-'));
}

function makeCtx(projectRoot: string): CheckContext {
  return {
    reportsDir: path.join(projectRoot, 'reports'),
    pagesDir: path.join(projectRoot, 'reports', 'pages'),
    sourcesDir: path.join(projectRoot, 'reports', 'sources'),
    projectRoot,
  };
}

interface ClaimRecord {
  id: string;
  cites?: string[];
  file?: string;
}

async function writeClaimsJsonl(runDir: string, claims: ClaimRecord[]): Promise<void> {
  await fs.mkdir(runDir, { recursive: true });
  const lines = claims.map(c => JSON.stringify(c)).join('\n');
  await fs.writeFile(path.join(runDir, 'claims.jsonl'), lines + '\n', 'utf8');
}

// ---------------------------------------------------------------------------
// Test: no .insight-kit/runs dir = no findings
// ---------------------------------------------------------------------------
test('checkProvenanceIntegrity returns no findings when runs dir absent', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = makeCtx(tmp);
    const findings = await checkProvenanceIntegrity(ctx);
    assert.equal(findings.length, 0);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: valid DAG — no findings
// ---------------------------------------------------------------------------
test('checkProvenanceIntegrity passes a clean claim DAG', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = makeCtx(tmp);
    const runDir = path.join(tmp, '.insight-kit', 'runs', '2026-04-28T10-00');

    // A -> B -> C (simple chain, no cycles)
    await writeClaimsJsonl(runDir, [
      { id: 'c1', cites: ['c2'] },
      { id: 'c2', cites: ['c3'] },
      { id: 'c3', cites: [] },
    ]);

    const findings = await checkProvenanceIntegrity(ctx);
    // c3 cites nothing and IS cited by c2, so not orphan.
    // c1 cites c2, c2 cites c3 — valid.
    const errors = findings.filter(f => f.severity === 'error');
    assert.equal(errors.length, 0, `Unexpected errors: ${JSON.stringify(errors)}`);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: cite-not-found finding
// ---------------------------------------------------------------------------
test('checkProvenanceIntegrity emits cite-not-found for dangling reference', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = makeCtx(tmp);
    const runDir = path.join(tmp, '.insight-kit', 'runs', 'run-01');

    await writeClaimsJsonl(runDir, [
      { id: 'c1', cites: ['c999'] }, // c999 does not exist
    ]);

    const findings = await checkProvenanceIntegrity(ctx);
    const notFound = findings.find(f => f.rule === 'cite-not-found');
    assert.ok(notFound, 'Expected cite-not-found finding');
    assert.equal(notFound!.layer, 5);
    assert.equal(notFound!.severity, 'error');
    assert.ok(notFound!.snippet?.includes('c999'), 'Snippet should name the missing id');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: cycle detection via Tarjan SCC
// ---------------------------------------------------------------------------
test('checkProvenanceIntegrity detects provenance-cycle', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = makeCtx(tmp);
    const runDir = path.join(tmp, '.insight-kit', 'runs', 'run-02');

    // A -> B -> C -> A (cycle)
    await writeClaimsJsonl(runDir, [
      { id: 'cA', cites: ['cB'] },
      { id: 'cB', cites: ['cC'] },
      { id: 'cC', cites: ['cA'] },
    ]);

    const findings = await checkProvenanceIntegrity(ctx);
    const cycle = findings.find(f => f.rule === 'provenance-cycle');
    assert.ok(cycle, 'Expected provenance-cycle finding');
    assert.equal(cycle!.layer, 5);
    assert.equal(cycle!.severity, 'error');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: orphan-claim warning
// ---------------------------------------------------------------------------
test('checkProvenanceIntegrity emits orphan-claim warning', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = makeCtx(tmp);
    const runDir = path.join(tmp, '.insight-kit', 'runs', 'run-03');

    await writeClaimsJsonl(runDir, [
      { id: 'c1', cites: ['c2'] },
      { id: 'c2', cites: [] },
      { id: 'c_orphan', cites: [] }, // not cited, no cites
    ]);

    const findings = await checkProvenanceIntegrity(ctx);
    const orphans = findings.filter(f => f.rule === 'orphan-claim');
    assert.ok(orphans.some(f => f.snippet?.includes('c_orphan')), 'Expected orphan finding for c_orphan');
    assert.equal(orphans[0].severity, 'warn');
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Test: claims.json fallback (array format)
// ---------------------------------------------------------------------------
test('checkProvenanceIntegrity reads claims.json when jsonl absent', async () => {
  const tmp = await makeTmpDir();
  try {
    const ctx = makeCtx(tmp);
    const runDir = path.join(tmp, '.insight-kit', 'runs', 'run-04');
    await fs.mkdir(runDir, { recursive: true });

    const claims: ClaimRecord[] = [
      { id: 'x1', cites: ['x2'] },
      { id: 'x2', cites: [] },
    ];
    await fs.writeFile(path.join(runDir, 'claims.json'), JSON.stringify(claims), 'utf8');

    const findings = await checkProvenanceIntegrity(ctx);
    const errors = findings.filter(f => f.severity === 'error');
    assert.equal(errors.length, 0, `Unexpected errors: ${JSON.stringify(errors)}`);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
});

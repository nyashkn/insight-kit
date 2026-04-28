/**
 * L3 render check — integration tests.
 *
 * Tests are skipped when agent-browser is not available on PATH.
 * When available, they run against a live Evidence dev server (reportsDir from ctx).
 */

import { describe, it, before } from 'node:test';
import assert from 'node:assert/strict';
import { checkAgentBrowserAvailable } from '../agentBrowser.js';
import { checkRender } from '../renderCheck.js';
import type { CheckContext } from '@insight-kit/viz-core/types';
import { join } from 'node:path';
import { existsSync } from 'node:fs';

// Attempt to locate a live reports dir (dockblocks or nairomarket growth_insights)
const CANDIDATE_REPORTS_DIRS = [
  '/Users/njui/Documents/dev_work/naisiae_lema/nairomarket/growth_insights/reports',
  '/Users/njui/Documents/dev_work/naisiae_lema/dockblocks-ops/reports',
];

function findReportsDir(): string | undefined {
  return CANDIDATE_REPORTS_DIRS.find((d) => existsSync(d));
}

describe('renderCheck (L3)', async () => {
  let skip = false;

  before(async () => {
    const available = await checkAgentBrowserAvailable();
    if (!available) {
      console.log('  [SKIP] agent-browser not found in PATH — skipping L3 integration tests');
      skip = true;
    }
  });

  it('returns agent-browser-missing finding when binary is absent', async () => {
    const result = await checkRender({
      pages: ['/'],
      ctx: {
        reportsDir: '/nonexistent',
        pagesDir: '/nonexistent/pages',
        sourcesDir: '/nonexistent/sources',
        projectRoot: '/nonexistent',
        agentBrowserPath: '/no/such/binary/agent-browser',
      },
    });
    assert.equal(result.findings.length, 1);
    assert.equal(result.findings[0].rule, 'agent-browser-missing');
    assert.equal(result.findings[0].layer, 3);
  });

  it('smoke-checks a real page when agent-browser is available', async function () {
    if (skip) return;

    const reportsDir = findReportsDir();
    if (!reportsDir) {
      console.log('  [SKIP] no reports dir found — skipping live render test');
      return;
    }

    const ctx: CheckContext = {
      reportsDir,
      pagesDir: join(reportsDir, 'pages'),
      sourcesDir: join(reportsDir, 'sources'),
      projectRoot: join(reportsDir, '..'),
    };

    // Use a short timeout page — just the index
    const result = await checkRender({
      pages: ['/'],
      ctx,
      noScreenshots: true,
      concurrency: 1,
    });

    // All findings must be layer 3
    for (const f of result.findings) {
      assert.equal(f.layer, 3);
    }

    // Clean up dev server if returned
    if (result.devServer) {
      await result.devServer.stop();
    }
  });
});

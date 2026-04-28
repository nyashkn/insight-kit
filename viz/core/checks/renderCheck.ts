import type { Finding, CheckContext } from '@insight-kit/viz-core/types';
import { ab, checkAgentBrowserAvailable } from './agentBrowser.js';
import { startDevServer, type DevServer } from './devServer.js';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { mkdir } from 'node:fs/promises';

const FAIL_PATTERNS = [
  'unknown hex color',
  'Error in Query',
  'Parser Error',
  'Binder Error',
  'Missed substition',
  'Build failed',
] as const;

const BIG_VALUE_BUG_RE = /\d{4,}%|\d{3,}\.\d+%/;

/** Convert a route like /levers/g5_ltv_cac to a safe filename slug. */
function slug(route: string): string {
  return route.replace(/^\//, '').replace(/\//g, '_').replace(/[^a-zA-Z0-9_-]/g, '-') || 'index';
}

/** Minimal concurrency pool — no p-limit dependency. */
async function pool<T, R>(items: T[], n: number, fn: (t: T) => Promise<R>): Promise<R[]> {
  const out: R[] = [];
  const queue = items.slice();
  await Promise.all(
    Array.from({ length: n }, async () => {
      while (queue.length) {
        const it = queue.shift()!;
        out.push(await fn(it));
      }
    }),
  );
  return out;
}

export interface RenderCheckOpts {
  /** Routes to check, e.g. ["/levers/g5_ltv_cac"] */
  pages: string[];
  /** Optional base URL override; if omitted, a dev server is spun up. */
  baseUrl?: string;
  ctx: CheckContext;
  noScreenshots?: boolean;
  screenshotDir?: string;
  /** Default 2 (matches Python). */
  concurrency?: number;
  /** Pass-through if M2's L4 already started a server. */
  reuseDevServer?: DevServer;
}

interface PageResult {
  route: string;
  findings: Finding[];
}

export async function checkRender(opts: RenderCheckOpts): Promise<{
  findings: Finding[];
  devServer?: DevServer;
}> {
  const {
    pages,
    ctx,
    noScreenshots = false,
    screenshotDir,
    concurrency = 2,
    reuseDevServer,
  } = opts;

  // 1. Verify agent-browser is available
  const abAvailable = await checkAgentBrowserAvailable(ctx.agentBrowserPath);
  if (!abAvailable) {
    return {
      findings: [
        {
          layer: 3,
          rule: 'agent-browser-missing',
          severity: 'error',
          hint: 'Install agent-browser and ensure it is on PATH before running L3 render checks.',
        },
      ],
    };
  }

  // 2. Start dev server if no base URL and no reuse handle provided
  let devServer: DevServer | undefined = reuseDevServer;
  let ownedServer = false;

  if (!opts.baseUrl && !devServer) {
    devServer = await startDevServer({
      reportsDir: ctx.reportsDir,
      port: 3100,
      env: {
        EVIDENCE_VAR__PROJECT_ROOT: ctx.projectRoot,
      },
    });
    ownedServer = true;
  }

  const baseUrl = opts.baseUrl ?? devServer!.baseUrl;

  // 3. Read the L3 eval payload JS
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const evalJs = await readFile(join(__dirname, 'evalPayloads', 'l3.js'), 'utf8');

  // Ensure screenshot dir exists if needed
  if (!noScreenshots && screenshotDir) {
    await mkdir(screenshotDir, { recursive: true });
  }

  // 4. Check each page with concurrency limit
  const allFindings: Finding[] = [];

  const pageResults = await pool<string, PageResult>(pages, concurrency, async (route, ..._rest) => {
    const idx = pages.indexOf(route);
    const sessionId = `preflight-${(idx % 4) + 1}`;
    const url = `${baseUrl}${route}`;
    const pageFindings: Finding[] = [];

    try {
      // Open page
      const openResult = await ab(sessionId, ['open', url], {
        timeoutMs: 30_000,
        binPath: ctx.agentBrowserPath,
      });
      if (openResult.code !== 0) {
        pageFindings.push({
          layer: 3,
          rule: 'page-open-failed',
          severity: 'error',
          file: route,
          snippet: openResult.output.slice(0, 200),
        });
      }

      // Wait for network idle
      const waitResult = await ab(sessionId, ['wait', '--load', 'networkidle'], {
        timeoutMs: 45_000,
        binPath: ctx.agentBrowserPath,
      });
      if (waitResult.code !== 0) {
        pageFindings.push({
          layer: 3,
          rule: 'page-wait-failed',
          severity: 'warn',
          file: route,
          snippet: waitResult.output.slice(0, 200),
        });
      }

      // Screenshot (non-fatal)
      if (!noScreenshots && screenshotDir && pageFindings.length === 0) {
        const shotPath = join(screenshotDir, `${slug(route)}.png`);
        await ab(sessionId, ['screenshot', shotPath], {
          timeoutMs: 20_000,
          binPath: ctx.agentBrowserPath,
        });
        // Failures are intentionally ignored (matches Python behaviour)
      }

      // Eval JS payload (skip if page already failed to open/load)
      if (pageFindings.length === 0) {
        const evalResult = await ab(sessionId, ['eval', '--stdin'], {
          timeoutMs: 30_000,
          stdin: evalJs,
          binPath: ctx.agentBrowserPath,
        });

        if (evalResult.code !== 0) {
          pageFindings.push({
            layer: 3,
            rule: 'eval-failed',
            severity: 'error',
            file: route,
            snippet: evalResult.output.slice(0, 200),
          });
        } else {
          // agent-browser eval can return double-encoded JSON: parse once then again if inner is string
          let data: Record<string, unknown> | null = null;
          try {
            const inner: unknown = JSON.parse(evalResult.output.trim());
            data = (typeof inner === 'string' ? JSON.parse(inner) : inner) as Record<string, unknown>;
          } catch {
            const match = evalResult.output.match(/(\{.*\})/s);
            if (match) {
              try {
                data = JSON.parse(match[1]) as Record<string, unknown>;
              } catch {
                // fall through to null
              }
            }
          }

          if (data) {
            const bodyText = typeof data['bodyText'] === 'string' ? data['bodyText'] : '';
            const svgPathCounts = Array.isArray(data['svgPathCounts'])
              ? (data['svgPathCounts'] as number[])
              : [];
            const bigValues = Array.isArray(data['bigValues'])
              ? (data['bigValues'] as string[])
              : [];

            // Check for error strings in body
            for (const pat of FAIL_PATTERNS) {
              if (bodyText.toLowerCase().includes(pat.toLowerCase())) {
                pageFindings.push({
                  layer: 3,
                  rule: 'body-error-text',
                  severity: 'error',
                  file: route,
                  snippet: pat,
                  hint: `Page body contains error pattern: "${pat}"`,
                });
              }
            }

            // Check for NaN%
            if (bodyText.includes('NaN%')) {
              pageFindings.push({
                layer: 3,
                rule: 'body-nan-pct',
                severity: 'error',
                file: route,
                hint: 'Page body contains "NaN%" — likely a division-by-zero or missing value in a metric.',
              });
            }

            // Check for bare undefined
            if (/\bundefined\b/.test(bodyText)) {
              pageFindings.push({
                layer: 3,
                rule: 'body-undefined',
                severity: 'warn',
                file: route,
                hint: 'Page body contains the word "undefined" — likely an unresolved template variable.',
              });
            }

            // Check for empty SVG charts
            const emptyChartIndexes = svgPathCounts
              .map((c, i) => (c === 0 ? i : -1))
              .filter((i) => i >= 0);
            if (emptyChartIndexes.length > 0) {
              pageFindings.push({
                layer: 3,
                rule: 'empty-svg-chart',
                severity: 'error',
                file: route,
                snippet: `SVG chart(s) at index [${emptyChartIndexes.join(', ')}] have 0 path elements`,
                hint: 'Charts rendered with no paths — likely an empty dataset or query error.',
              });
            }

            // Check big-value overflow
            for (const bv of bigValues) {
              if (BIG_VALUE_BUG_RE.test(bv)) {
                pageFindings.push({
                  layer: 3,
                  rule: 'bigvalue-overflow-pct',
                  severity: 'error',
                  file: route,
                  snippet: bv,
                  hint: `Big-value shows suspiciously large percentage: "${bv}" — check yFmt or percent multiplier.`,
                });
              }
            }
          } else {
            pageFindings.push({
              layer: 3,
              rule: 'eval-no-json',
              severity: 'warn',
              file: route,
              snippet: evalResult.output.slice(0, 200),
              hint: 'eval returned output but no parseable JSON — check the l3.js payload.',
            });
          }
        }
      }
    } finally {
      // Always close the session
      await ab(sessionId, ['close'], {
        timeoutMs: 15_000,
        binPath: ctx.agentBrowserPath,
      });
    }

    return { route, findings: pageFindings };
  });

  for (const pr of pageResults) {
    allFindings.push(...pr.findings);
  }

  // 5. Tear down our own dev server unless caller wants to reuse it
  if (ownedServer && devServer) {
    // Return the server so caller can close later; they are responsible for teardown.
    // If caller does not capture it, it will eventually be GC'd — not ideal, but matches
    // the "return devServer so caller can hand to L4" contract in the spec.
    return { findings: allFindings, devServer };
  }

  return { findings: allFindings };
}

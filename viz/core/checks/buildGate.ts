/**
 * L2 — Evidence Build Gate
 *
 * Runs `npm run sources -- --changed` then `npx evidence build` in reportsDir.
 * Mirrors Python layer2() in growth_insights/scripts/preflight_check.py.
 */

import type { Finding, CheckContext } from '@insight-kit/viz-core/types';
import { spawn } from 'node:child_process';

// Mirror Python BUILD_FAIL_RE exactly (re.IGNORECASE)
const BUILD_FAIL_RE =
  /Error in Query!|Parser Error|Binder Error|Conversion Error|Missed substition|Build failed|error TS\d+/i;

/**
 * Run a command in a directory, returning { code, output }.
 * Accumulates stdout + stderr into a single string.
 */
function runCommand(
  cmd: string,
  args: string[],
  cwd: string,
  env?: NodeJS.ProcessEnv
): Promise<{ code: number; output: string }> {
  return new Promise(resolve => {
    const proc = spawn(cmd, args, {
      cwd,
      env: env ?? process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    const chunks: Buffer[] = [];
    proc.stdout.on('data', (d: Buffer) => chunks.push(d));
    proc.stderr.on('data', (d: Buffer) => chunks.push(d));

    proc.on('close', code => {
      resolve({ code: code ?? 1, output: Buffer.concat(chunks).toString('utf8') });
    });

    proc.on('error', err => {
      resolve({ code: 1, output: err.message });
    });
  });
}

export async function checkBuildGate(ctx: CheckContext): Promise<Finding[]> {
  const findings: Finding[] = [];

  const steps: Array<{ name: string; cmd: string; args: string[] }> = [
    { name: 'sources-refresh', cmd: 'npm', args: ['run', 'sources', '--', '--changed'] },
    { name: 'evidence-build',  cmd: 'npx', args: ['evidence', 'build'] },
  ];

  const env = {
    ...process.env,
    EVIDENCE_VAR__PROJECT_ROOT: ctx.projectRoot,
  };

  for (const step of steps) {
    const { code, output } = await runCommand(step.cmd, step.args, ctx.reportsDir, env);

    const failLines = output
      .split('\n')
      .filter(l => BUILD_FAIL_RE.test(l));

    if (code !== 0 || failLines.length > 0) {
      const snippet = failLines.length > 0
        ? failLines.slice(0, 5).join('\n')
        : output.split('\n').slice(-10).join('\n');

      findings.push({
        layer: 2,
        rule: 'build-gate-failed',
        severity: 'error',
        location: step.name,
        snippet: snippet.slice(0, 400),
        hint: `Step "${step.name}" exited with code ${code}. Fix build errors before deploying.`,
      });
      // Abort remaining steps on first failure (build depends on sources)
      break;
    }
  }

  return findings;
}

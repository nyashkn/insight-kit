#!/usr/bin/env -S node --experimental-strip-types
/**
 * `ik viz install evidence <reports-dir>`:
 *   1. Run viz/evidence/layouts/install.mjs --reports-dir <path>
 *   2. Verify <reports-dir>/evidence.config.yaml exists; if missing, exit 1.
 *   3. Read evidence.config.yaml; if `plugins.components` doesn't include
 *      "@insight-kit/viz-evidence": {}, append it (preserve YAML formatting
 *      via simple string manipulation — no yaml dep).
 *   4. Detect @insight-kit/viz-evidence in reports/package.json dependencies.
 *      If missing, print suggestion: `npm install file:<path-to-insight-kit/viz/evidence>`.
 *      DO NOT auto-modify package.json.
 *   5. Print success summary: layouts installed, plugin registered, dep result.
 */

import { parseArgs } from 'node:util';
import { spawn } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname  = dirname(__filename);

// ---------------------------------------------------------------------------
// Arg parsing
// ---------------------------------------------------------------------------

const { values: argv } = parseArgs({
  options: {
    'reports-dir': { type: 'string' },
    'force':       { type: 'boolean', default: false },
    'help':        { type: 'boolean', default: false },
  },
  allowPositionals: false,
});

if (argv['help'] || !argv['reports-dir']) {
  process.stdout.write(`
ik viz install evidence — install 6 layout templates + register plugin.

Usage:
  node --experimental-strip-types install-cli.mjs --reports-dir <path> [--force]

Options:
  --reports-dir <path>   Path to Evidence reports directory (required)
  --force                Overwrite existing +layout.svelte files
  --help                 Show this message
`);
  process.exit(argv['help'] ? 0 : 1);
}

const reportsDir = resolve(argv['reports-dir']);

if (!existsSync(reportsDir)) {
  process.stderr.write(`error: --reports-dir does not exist: ${reportsDir}\n`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Helper: spawn a child process and collect its output
// ---------------------------------------------------------------------------

function runCommand(cmd, args, opts = {}) {
  return new Promise((res) => {
    const child = spawn(cmd, args, {
      stdio: ['ignore', 'pipe', 'pipe'],
      ...opts,
    });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => { stdout += d; process.stdout.write(d); });
    child.stderr.on('data', (d) => { stderr += d; process.stderr.write(d); });
    child.on('close', (code) => res({ code, stdout, stderr }));
  });
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  // ---- Step 1: run layouts/install.mjs ----
  const installMjs = join(__dirname, 'layouts', 'install.mjs');
  if (!existsSync(installMjs)) {
    process.stderr.write(`error: layouts/install.mjs not found at ${installMjs}\n`);
    process.exit(1);
  }

  process.stdout.write('\n[1/4] Installing Evidence layout templates...\n\n');
  const installArgs = ['--experimental-strip-types', installMjs, '--reports-dir', reportsDir];
  if (argv['force']) installArgs.push('--force');

  const installResult = await runCommand('node', installArgs);
  if (installResult.code !== 0) {
    process.stderr.write(`error: layouts/install.mjs exited with code ${installResult.code}\n`);
    process.exit(installResult.code);
  }

  // ---- Step 2: verify evidence.config.yaml exists ----
  process.stdout.write('\n[2/4] Verifying evidence.config.yaml...\n');
  const configPath = join(reportsDir, 'evidence.config.yaml');
  if (!existsSync(configPath)) {
    process.stderr.write(
      `error: evidence.config.yaml not found at ${configPath}\n` +
      `       Run "npx degit evidence-dev/template" in ${reportsDir} first.\n`
    );
    process.exit(1);
  }
  process.stdout.write(`  found: ${configPath}\n`);

  // ---- Step 3: register @insight-kit/viz-evidence plugin ----
  process.stdout.write('\n[3/4] Registering @insight-kit/viz-evidence in evidence.config.yaml...\n');

  let configText = await readFile(configPath, 'utf-8');
  const pluginEntry = '"@insight-kit/viz-evidence": {}';
  const pluginKey   = '@insight-kit/viz-evidence';

  let pluginRegistered = false;

  if (configText.includes(pluginKey)) {
    process.stdout.write(`  already registered — no change needed.\n`);
    pluginRegistered = true;
  } else {
    // Find or create plugins.components section using string manipulation.
    // Strategy:
    //   a) If `components:` exists inside a `plugins:` block → append under it.
    //   b) If `plugins:` exists but no `components:` → append components block.
    //   c) If neither → append plugins block at end.

    const hasPlugins    = /^plugins\s*:/m.test(configText);
    const hasComponents = /^\s+components\s*:/m.test(configText);

    if (hasPlugins && hasComponents) {
      // Insert after the `components:` line
      configText = configText.replace(
        /([ \t]+components\s*:\s*\n)/,
        `$1      ${pluginEntry}\n`
      );
    } else if (hasPlugins) {
      // Append components block inside plugins
      configText = configText.replace(
        /(^plugins\s*:\s*\n)/m,
        `$1  components:\n      ${pluginEntry}\n`
      );
    } else {
      // Append whole plugins block at end
      const suffix = `\nplugins:\n  components:\n    ${pluginEntry}\n`;
      configText = configText.trimEnd() + suffix;
    }

    await writeFile(configPath, configText, 'utf-8');

    // Validate: confirm key is now present
    if (!configText.includes(pluginKey)) {
      process.stderr.write(`error: YAML manipulation failed — ${pluginKey} not found after write.\n`);
      process.exit(1);
    }

    process.stdout.write(`  registered: ${pluginEntry}\n`);
    pluginRegistered = true;
  }

  // ---- Step 4: detect dependency in package.json ----
  process.stdout.write('\n[4/4] Checking reports/package.json for @insight-kit/viz-evidence...\n');

  const pkgPath = join(reportsDir, 'package.json');
  let depDetected = false;

  if (existsSync(pkgPath)) {
    let pkgText;
    try {
      pkgText = await readFile(pkgPath, 'utf-8');
      depDetected = pkgText.includes('@insight-kit/viz-evidence');
    } catch {
      // ignore
    }
  }

  if (depDetected) {
    process.stdout.write(`  @insight-kit/viz-evidence found in package.json.\n`);
  } else {
    // Compute path from reports dir to viz/evidence
    const vizEvidencePath = join(__dirname);  // install-cli.mjs is in viz/evidence/
    process.stdout.write(
      `  @insight-kit/viz-evidence NOT found in package.json.\n` +
      `  To install, run:\n\n` +
      `    npm install file:${vizEvidencePath}\n\n` +
      `  (or add it manually to your reports/package.json)\n`
    );
  }

  // ---- Summary ----
  process.stdout.write('\n' + '='.repeat(56) + '\n');
  process.stdout.write('ik viz install evidence — complete\n');
  process.stdout.write('  6 layout templates installed/checked\n');
  process.stdout.write(`  plugin registered:   ${pluginRegistered ? 'yes' : 'no'}\n`);
  process.stdout.write(`  dep in package.json: ${depDetected ? 'yes' : 'missing (see above)'}\n`);
  process.stdout.write('='.repeat(56) + '\n\n');
}

main().catch((err) => {
  process.stderr.write(`fatal: ${err.message}\n`);
  process.exit(1);
});

#!/usr/bin/env node
/**
 * Install Evidence layout templates into a consumer's reports/pages/<folder>/+layout.svelte.
 *
 * Usage:
 *   node install.mjs --reports-dir <path> [--force] [--types <comma-list>]
 *
 * Defaults:
 *   --reports-dir   ./reports
 *   --types         all 6 (receipt,narrative,investigation,metric,browse,audit)
 *   --force         overwrite existing +layout.svelte files
 */

import { parseArgs } from 'node:util';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync } from 'node:fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const defaultTypes = [
  'receipt',
  'narrative',
  'investigation',
  'metric',
  'browse',
  'audit'
];

// Parse CLI arguments
const options = {
  'reports-dir': {
    type: 'string',
    default: './reports',
    description: 'Path to reports directory'
  },
  'force': {
    type: 'boolean',
    default: false,
    description: 'Overwrite existing +layout.svelte files'
  },
  'types': {
    type: 'string',
    description: 'Comma-separated list of page types to install'
  },
  'help': {
    type: 'boolean',
    default: false,
    description: 'Show help message'
  }
};

const { values } = parseArgs({ options });

if (values.help) {
  console.log(`
Install Evidence layout templates.

Usage:
  node install.mjs [options]

Options:
  --reports-dir <path>    Path to reports directory (default: ./reports)
  --force                 Overwrite existing +layout.svelte files (default: false)
  --types <list>          Comma-separated page types (default: all 6)
  --help                  Show this message
`);
  process.exit(0);
}

async function main() {
  try {
    // Load LAYOUT_MAP.json
    const mapPath = join(__dirname, 'LAYOUT_MAP.json');
    const mapContent = await readFile(mapPath, 'utf-8');
    const layoutMap = JSON.parse(mapContent);

    // Resolve reports directory
    const reportsDir = resolve(values['reports-dir']);
    const pagesDir = join(reportsDir, 'pages');

    // Determine which types to install
    let typesToInstall = defaultTypes;
    if (values.types) {
      typesToInstall = values.types
        .split(',')
        .map(t => t.trim())
        .filter(t => t.length > 0);
    }

    const results = [];
    const errors = [];

    for (const layout of layoutMap.layouts) {
      if (!typesToInstall.includes(layout.pageType)) {
        continue;
      }

      const srcPath = join(__dirname, layout.file);
      const destDir = join(pagesDir, layout.folder);
      const destPath = join(destDir, '+layout.svelte');

      try {
        // Check if destination exists
        if (existsSync(destPath) && !values.force) {
          results.push({
            type: 'skip',
            pageType: layout.pageType,
            folder: layout.folder,
            reason: 'file exists (use --force to overwrite)'
          });
          continue;
        }

        // Create destination directory
        await mkdir(destDir, { recursive: true });

        // Read source and write to destination
        const content = await readFile(srcPath, 'utf-8');
        await writeFile(destPath, content, 'utf-8');

        results.push({
          type: 'installed',
          pageType: layout.pageType,
          folder: layout.folder,
          path: destPath
        });
      } catch (err) {
        errors.push({
          pageType: layout.pageType,
          folder: layout.folder,
          error: err.message
        });
      }
    }

    // Print summary
    console.log('\n=== Evidence Layout Installation Summary ===\n');

    const installed = results.filter(r => r.type === 'installed');
    const skipped = results.filter(r => r.type === 'skip');

    if (installed.length > 0) {
      console.log(`✓ Installed ${installed.length} layout(s):`);
      for (const r of installed) {
        console.log(`  • ${r.pageType} → ${r.folder}/+layout.svelte`);
      }
    }

    if (skipped.length > 0) {
      console.log(`\n⊘ Skipped ${skipped.length} layout(s):`);
      for (const r of skipped) {
        console.log(`  • ${r.pageType} (${r.reason})`);
      }
    }

    if (errors.length > 0) {
      console.log(`\n✗ Failed ${errors.length} layout(s):`);
      for (const e of errors) {
        console.log(`  • ${e.pageType}: ${e.error}`);
      }
      process.exit(1);
    }

    console.log('\n===========================================\n');
  } catch (err) {
    console.error('Fatal error:', err.message);
    process.exit(1);
  }
}

main();

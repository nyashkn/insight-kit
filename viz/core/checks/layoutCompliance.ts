/**
 * L6 — Layout Compliance Check (NEW)
 *
 * Walks pagesDir/**\/*.md, reads YAML frontmatter, validates against
 * PAGE_TYPE_RULES for the declared layout_type.
 * No gray-matter dependency — uses regex-based frontmatter extraction.
 */

import type { Finding, CheckContext } from '@insight-kit/viz-core/types';
import { PAGE_TYPE_RULES } from '@insight-kit/viz-core/page-type-rules';
import type { PageType } from '@insight-kit/viz-core/types';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

// ---------------------------------------------------------------------------
// Frontmatter parser — no gray-matter dep
// ---------------------------------------------------------------------------

/** Parse YAML frontmatter from markdown content. Returns null if no frontmatter. */
function parseFrontmatter(content: string): Record<string, unknown> | null {
  // Match ---\n ... \n---\n at top of file
  const match = /^---\n([\s\S]*?)\n---\n/.exec(content);
  if (!match) return null;

  const block = match[1];
  const result: Record<string, unknown> = {};

  for (const rawLine of block.split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;

    const colonIdx = line.indexOf(':');
    if (colonIdx === -1) continue;

    const key = line.slice(0, colonIdx).trim();
    const rawVal = line.slice(colonIdx + 1).trim();

    // Parse value: bool, number, or string
    if (rawVal === 'true') {
      result[key] = true;
    } else if (rawVal === 'false') {
      result[key] = false;
    } else if (rawVal === 'null' || rawVal === '~') {
      result[key] = null;
    } else if (/^-?\d+$/.test(rawVal)) {
      result[key] = parseInt(rawVal, 10);
    } else if (/^-?\d+\.\d+$/.test(rawVal)) {
      result[key] = parseFloat(rawVal);
    } else {
      // Strip surrounding quotes if present
      result[key] = rawVal.replace(/^['"]|['"]$/g, '');
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Component counting helpers
// ---------------------------------------------------------------------------

function countOccurrences(content: string, substring: string): number {
  let count = 0;
  let idx = 0;
  while ((idx = content.indexOf(substring, idx)) !== -1) {
    count++;
    idx += substring.length;
  }
  return count;
}

/** Count total ClaimBlock + ClaimInline occurrences in body. */
function countClaimInlineOrBlock(body: string): number {
  return countOccurrences(body, '<ClaimBlock') + countOccurrences(body, '<ClaimInline');
}

/** Count ClaimBlock-only occurrences. */
function countClaimBlocks(body: string): number {
  return countOccurrences(body, '<ClaimBlock');
}

/** Count chart component occurrences. */
function countCharts(body: string): number {
  const chartTags = [
    '<LineChart',
    '<BarChart',
    '<DotPlot',
    '<Heatmap',
    '<DataTable type="hist"',
    '<ScatterPlot',
    '<AreaChart',
    '<BubbleChart',
    '<FunnelChart',
  ];
  return chartTags.reduce((sum, tag) => sum + countOccurrences(body, tag), 0);
}

// ---------------------------------------------------------------------------
// Walk helpers
// ---------------------------------------------------------------------------

async function walkMdFiles(dir: string): Promise<string[]> {
  let entries: string[];
  try {
    entries = await fs.readdir(dir, { recursive: true }) as string[];
  } catch {
    return [];
  }
  return entries.filter(e => e.endsWith('.md')).map(e => path.join(dir, e));
}

function lineAt(content: string, offset: number): number {
  return content.slice(0, offset).split('\n').length;
}

// ---------------------------------------------------------------------------
// Main check
// ---------------------------------------------------------------------------

export async function checkLayoutCompliance(ctx: CheckContext): Promise<Finding[]> {
  const findings: Finding[] = [];

  const pagesFilter = ctx.pagesFilter;
  let mdFiles = await walkMdFiles(ctx.pagesDir);
  mdFiles.sort();

  if (pagesFilter && pagesFilter.length > 0) {
    mdFiles = mdFiles.filter(f => pagesFilter.some(pf => f.includes(pf)));
  }

  for (const mdPath of mdFiles) {
    const relPath = path.relative(ctx.projectRoot, mdPath);

    let content: string;
    try {
      content = await fs.readFile(mdPath, 'utf8');
    } catch {
      continue;
    }

    const frontmatter = parseFrontmatter(content);
    if (frontmatter === null) {
      // No frontmatter at all — skip layout_type check
      continue;
    }

    const layoutType = frontmatter['layout_type'] as string | undefined;

    if (!layoutType) {
      findings.push({
        layer: 6,
        rule: 'layout-type-missing',
        severity: 'warn',
        file: relPath,
        line: 1,
        hint: `Add a layout_type field to frontmatter. Valid values: ${Object.keys(PAGE_TYPE_RULES).join(', ')}`,
      });
      continue;
    }

    const rules = PAGE_TYPE_RULES[layoutType as PageType];
    if (!rules) {
      findings.push({
        layer: 6,
        rule: 'layout-type-unknown',
        severity: 'warn',
        file: relPath,
        line: 1,
        snippet: `layout_type: ${layoutType}`,
        hint: `Unknown layout_type "${layoutType}". Valid values: ${Object.keys(PAGE_TYPE_RULES).join(', ')}`,
      });
      continue;
    }

    // Strip frontmatter to get body for component counting
    const fmMatch = /^---\n[\s\S]*?\n---\n/.exec(content);
    const bodyStart = fmMatch ? fmMatch[0].length : 0;
    const body = content.slice(bodyStart);

    // ---- requiredFrontmatter ----
    if (rules.requiredFrontmatter) {
      for (const [key, expectedVal] of Object.entries(rules.requiredFrontmatter)) {
        const actualVal = frontmatter[key];
        if (actualVal !== expectedVal) {
          findings.push({
            layer: 6,
            rule: 'required-frontmatter-missing',
            severity: 'error',
            file: relPath,
            line: 1,
            snippet: `${key}: ${String(actualVal ?? '(missing)')}`,
            hint: `layout_type "${layoutType}" requires frontmatter \`${key}: ${String(expectedVal)}\``,
          });
        }
      }
    }

    // ---- minClaimBlocks ----
    if (rules.minClaimBlocks !== undefined) {
      const count = countClaimBlocks(body);
      if (count < rules.minClaimBlocks) {
        findings.push({
          layer: 6,
          rule: 'min-claim-blocks',
          severity: 'error',
          file: relPath,
          snippet: `found ${count} <ClaimBlock (need ≥${rules.minClaimBlocks})`,
          hint: `layout_type "${layoutType}" requires at least ${rules.minClaimBlocks} <ClaimBlock component(s).`,
        });
      }
    }

    // ---- minClaimInlineOrBlock ----
    if (rules.minClaimInlineOrBlock !== undefined) {
      const count = countClaimInlineOrBlock(body);
      if (count < rules.minClaimInlineOrBlock) {
        findings.push({
          layer: 6,
          rule: 'min-claim-inline-or-block',
          severity: 'error',
          file: relPath,
          snippet: `found ${count} claim component(s) (need ≥${rules.minClaimInlineOrBlock})`,
          hint: `layout_type "${layoutType}" requires at least ${rules.minClaimInlineOrBlock} <ClaimBlock or <ClaimInline component(s).`,
        });
      }
    }

    // ---- minCharts ----
    if (rules.minCharts !== undefined) {
      const count = countCharts(body);
      if (count < rules.minCharts) {
        findings.push({
          layer: 6,
          rule: 'min-charts',
          severity: 'error',
          file: relPath,
          snippet: `found ${count} chart(s) (need ≥${rules.minCharts})`,
          hint: `layout_type "${layoutType}" requires at least ${rules.minCharts} chart component(s).`,
        });
      }
    }

    // ---- requiresProvenanceRail ----
    if (rules.requiresProvenanceRail === true) {
      if (!body.includes('<ProvenanceRail')) {
        findings.push({
          layer: 6,
          rule: 'provenance-rail-required',
          severity: 'error',
          file: relPath,
          hint: `layout_type "${layoutType}" requires a <ProvenanceRail component.`,
        });
      }
    }

    // ---- forbidsProvenanceRail ----
    if (rules.forbidsProvenanceRail === true) {
      const idx = body.indexOf('<ProvenanceRail');
      if (idx !== -1) {
        findings.push({
          layer: 6,
          rule: 'provenance-rail-forbidden',
          severity: 'error',
          file: relPath,
          line: lineAt(content, bodyStart + idx),
          hint: `layout_type "${layoutType}" must NOT include a <ProvenanceRail component (page IS the receipt).`,
        });
      }
    }
  }

  return findings;
}

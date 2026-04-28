/**
 * Integration test: PAGE_TYPE_RULES contract for all 6 PageType values.
 *
 * Asserts each type has the expected required components / min charts /
 * provenance constraint per the spec in PLANS/viz-kit-extraction-2026-04-28.md.
 */
import { describe, test, expect } from 'bun:test';
import { PAGE_TYPE_RULES } from '../../pageTypeRules.js';
import type { PageType } from '../../types.js';

const ALL_TYPES: PageType[] = ['receipt', 'narrative', 'investigation', 'metric', 'browse', 'audit'];

describe('PAGE_TYPE_RULES completeness', () => {
  test('all 6 PageTypes are present', () => {
    const keys = Object.keys(PAGE_TYPE_RULES).sort();
    expect(keys).toEqual([...ALL_TYPES].sort());
  });

  test('every rule set has a non-empty description', () => {
    for (const type of ALL_TYPES) {
      expect(typeof PAGE_TYPE_RULES[type].description).toBe('string');
      expect(PAGE_TYPE_RULES[type].description.length).toBeGreaterThan(0);
    }
  });
});

describe('PAGE_TYPE_RULES per-type constraints', () => {
  // receipt: ≥1 ClaimBlock, forbidsProvenanceRail, hide_sidebar:true
  test('receipt: requires ≥1 ClaimBlock, forbids ProvenanceRail, requires hide_sidebar', () => {
    const r = PAGE_TYPE_RULES.receipt;
    expect(r.minClaimBlocks).toBeGreaterThanOrEqual(1);
    expect(r.forbidsProvenanceRail).toBe(true);
    expect(r.requiresProvenanceRail).toBeFalsy();
    expect(r.requiredFrontmatter?.['hide_sidebar']).toBe(true);
  });

  // narrative: ≥1 ClaimBlock or ClaimInline, requiresProvenanceRail
  test('narrative: requires ≥1 claim component, requires ProvenanceRail', () => {
    const r = PAGE_TYPE_RULES.narrative;
    expect((r.minClaimInlineOrBlock ?? 0)).toBeGreaterThanOrEqual(1);
    expect(r.requiresProvenanceRail).toBe(true);
    expect(r.forbidsProvenanceRail).toBeFalsy();
  });

  // investigation: ≥1 ClaimBlock, ≥1 chart
  test('investigation: requires ≥1 ClaimBlock and ≥1 chart', () => {
    const r = PAGE_TYPE_RULES.investigation;
    expect(r.minClaimBlocks).toBeGreaterThanOrEqual(1);
    expect(r.minCharts).toBeGreaterThanOrEqual(1);
  });

  // metric: ≥1 chart, no claim requirement
  test('metric: requires ≥1 chart, no mandatory claim components', () => {
    const r = PAGE_TYPE_RULES.metric;
    expect(r.minCharts).toBeGreaterThanOrEqual(1);
    expect(r.minClaimBlocks ?? 0).toBe(0);
    expect(r.minClaimInlineOrBlock ?? 0).toBe(0);
  });

  // browse: no chart, no claim requirement, no ProvenanceRail constraint
  test('browse: no minimum charts or claim components required', () => {
    const r = PAGE_TYPE_RULES.browse;
    expect(r.minCharts ?? 0).toBe(0);
    expect(r.minClaimBlocks ?? 0).toBe(0);
    expect(r.requiresProvenanceRail).toBeFalsy();
    expect(r.forbidsProvenanceRail).toBeFalsy();
  });

  // audit: no chart, no claim, no ProvenanceRail constraint
  test('audit: no minimum charts or claim components required', () => {
    const r = PAGE_TYPE_RULES.audit;
    expect(r.minCharts ?? 0).toBe(0);
    expect(r.minClaimBlocks ?? 0).toBe(0);
    expect(r.requiresProvenanceRail).toBeFalsy();
    expect(r.forbidsProvenanceRail).toBeFalsy();
  });
});

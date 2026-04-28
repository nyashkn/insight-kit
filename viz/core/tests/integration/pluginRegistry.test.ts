/**
 * Integration test: Renderer plugin registry contract.
 */
import { describe, test, expect } from 'bun:test';
import { registerRenderer, getRenderer, listRenderers } from '../../renderer.js';
import type { Renderer, PreflightResult } from '../../index.js';

// ---------------------------------------------------------------------------
// Fake renderer fixture
// ---------------------------------------------------------------------------

const fakeResult: PreflightResult = {
  pass: true,
  findings: [],
  pagesChecked: 0,
  durationMs: 0,
  layers: {},
};

const fakeRenderer: Renderer = {
  name: 'markdown-seaborn',
  pageTypes: ['narrative', 'investigation'],
  install: async (_reportsDir: string) => {},
  buildGate: async () => fakeResult,
  rules: [],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('pluginRegistry contract', () => {
  test('registerRenderer adds renderer to registry', () => {
    // Should not throw
    expect(() => registerRenderer(fakeRenderer)).not.toThrow();
  });

  test('getRenderer retrieves the registered renderer by name', () => {
    const retrieved = getRenderer('markdown-seaborn');
    expect(retrieved.name).toBe('markdown-seaborn');
    expect(retrieved.pageTypes).toEqual(['narrative', 'investigation']);
    expect(typeof retrieved.install).toBe('function');
    expect(typeof retrieved.buildGate).toBe('function');
    expect(Array.isArray(retrieved.rules)).toBe(true);
  });

  test('listRenderers includes the registered renderer', () => {
    const names = listRenderers();
    expect(names).toContain('markdown-seaborn');
  });

  test('registerRenderer throws on duplicate registration', () => {
    expect(() => registerRenderer(fakeRenderer)).toThrow(/already registered/i);
  });

  test('getRenderer throws for unknown renderer name', () => {
    expect(() => getRenderer('no-such-renderer')).toThrow(/not found/i);
  });

  test('buildGate returns valid PreflightResult shape', async () => {
    const retrieved = getRenderer('markdown-seaborn');
    const result = await retrieved.buildGate({
      reportsDir: '/tmp',
      pagesDir: '/tmp/pages',
      sourcesDir: '/tmp/sources',
      projectRoot: '/tmp',
    });
    expect(typeof result.pass).toBe('boolean');
    expect(Array.isArray(result.findings)).toBe(true);
    expect(typeof result.pagesChecked).toBe('number');
    expect(typeof result.durationMs).toBe('number');
  });
});

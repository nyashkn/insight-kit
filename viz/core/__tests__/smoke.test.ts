import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { PAGE_TYPE_RULES, registerRenderer, listRenderers } from '../index.js';

test('PAGE_TYPE_RULES has all 6 types', () => {
  assert.deepEqual(
    Object.keys(PAGE_TYPE_RULES).sort(),
    ['audit', 'browse', 'investigation', 'metric', 'narrative', 'receipt']
  );
});

test('registerRenderer + listRenderers round-trip', () => {
  registerRenderer({
    name: 'test',
    pageTypes: ['audit'],
    install: async () => {},
    buildGate: async () => ({
      pass: true,
      findings: [],
      pagesChecked: 0,
      durationMs: 0,
      layers: {},
    }),
    rules: [],
  });
  assert.ok(listRenderers().includes('test'));
});

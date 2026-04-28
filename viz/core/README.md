# @insight-kit/viz-core

## Purpose

Contract layer for the insight-kit visualization framework. Defines core types, the Renderer plugin protocol, and PageType rules that all viz slices import and depend on.

## Install

```bash
npm install @insight-kit/viz-core
```

## Exports

- **Types**: `PageType`, `Severity`, `Finding`, `PreflightResult`, `CheckContext`, `PreflightRule`
- **Renderer Protocol**: `Renderer` interface, `registerRenderer()`, `getRenderer()`, `listRenderers()`
- **Page Type Rules**: `PAGE_TYPE_RULES` record (matrix of 6 page types + structural requirements)

## Quick Start

```typescript
import { PAGE_TYPE_RULES, registerRenderer } from '@insight-kit/viz-core';

// Access rules for a page type
console.log(PAGE_TYPE_RULES.narrative);

// Register a renderer plugin
registerRenderer({
  name: 'my-renderer',
  pageTypes: ['receipt', 'narrative'],
  install: async (reportsDir) => { /* ... */ },
  buildGate: async (ctx) => { /* ... */ },
  rules: []
});
```

## Plugin Authoring

See plugin-contract.md (forthcoming in M11) for full renderer plugin guide.

## License

MIT

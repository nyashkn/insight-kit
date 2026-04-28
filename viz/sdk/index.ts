// @insight-kit/viz SDK facade — single import surface for core + evidence + generators

// Core API
export type { CheckContext, Finding, PreflightResult } from '@insight-kit/viz-core';
export type { PageType, Severity, PreflightRule } from '@insight-kit/viz-core';
export type { Renderer, PageTypeRuleSet } from '@insight-kit/viz-core';
export { registerRenderer, getRenderer, listRenderers } from '@insight-kit/viz-core';
export { PAGE_TYPE_RULES } from '@insight-kit/viz-core';

// Re-export all evidence exports (components + claim helpers)
export * from '@insight-kit/viz-evidence';
// Explicit re-export of claim helpers (from top-level index.js, not components/index.js)
export { indexClaims, getClaim, claimsByTier } from '@insight-kit/viz-evidence/index.js';

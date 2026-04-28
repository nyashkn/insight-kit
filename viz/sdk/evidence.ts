// Re-export evidence components and claim helpers
export * from '@insight-kit/viz-evidence';
// Explicit re-export of claim helpers (from top-level index.js, not components/index.js)
export { indexClaims, getClaim, claimsByTier } from '@insight-kit/viz-evidence/index.js';

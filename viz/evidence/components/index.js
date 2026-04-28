// Re-export components for direct consumers (those who don't use Evidence's
// auto-import). Evidence's plugin discovers components by scanning .svelte
// files in the dir indicated by `main` — `components/index.js` here points
// fileLoader at this directory.
export { default as ClaimBlock } from './ClaimBlock.svelte';
export { default as ClaimDelta } from './ClaimDelta.svelte';
export { default as ClaimInline } from './ClaimInline.svelte';
export { default as ClaimTree } from './ClaimTree.svelte';
export { default as ClaimTreeNode } from './ClaimTreeNode.svelte';
export { default as ProvenanceRail } from './ProvenanceRail.svelte';

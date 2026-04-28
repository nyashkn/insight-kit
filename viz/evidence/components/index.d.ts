// TypeScript type declarations for Svelte components
// These components are Svelte modules without explicit TS types
// @ts-ignore Svelte components — JSDoc types via component props

import type { ComponentType } from 'svelte';

export const ClaimBlock: ComponentType;
export const ClaimDelta: ComponentType;
export const ClaimInline: ComponentType;
export const ClaimTree: ComponentType;
export const ClaimTreeNode: ComponentType;
export const ProvenanceRail: ComponentType;

export function indexClaims(claims: any[]): Record<string, any>;
export function getClaim(manifest: any, id: string): any;
export function claimsByTier(manifest: any): Record<string, any[]>;

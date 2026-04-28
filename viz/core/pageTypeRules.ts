import type { PageType } from './types.js';

export interface PageTypeRuleSet {
  requiredFrontmatter?: Record<string, unknown>;  // exact key/value pairs that must be present
  minClaimBlocks?: number;
  minClaimInlineOrBlock?: number;  // sum of either
  minCharts?: number;
  requiresProvenanceRail?: boolean;
  forbidsProvenanceRail?: boolean;
  description: string;
}

export const PAGE_TYPE_RULES: Record<PageType, PageTypeRuleSet> = {
  receipt: {
    requiredFrontmatter: { hide_sidebar: true },
    minClaimBlocks: 1,
    forbidsProvenanceRail: true,
    description: 'Provenance receipt — page IS the chain. Single column, no sidebar.',
  },
  narrative: {
    minClaimInlineOrBlock: 1,
    requiresProvenanceRail: true,
    description: 'Story with charts and inline claims; ProvenanceRail required.',
  },
  investigation: {
    minClaimBlocks: 1,
    minCharts: 1,
    description: 'Analyst depth page — charts + claim chips.',
  },
  metric: {
    minCharts: 1,
    description: 'KPI dashboard — BigValue grid + charts.',
  },
  browse: {
    description: 'Index/list/search — DataTables. No prose body required.',
  },
  audit: {
    description: 'Debug/QA — graph viewers, raw data. No claim refs required.',
  },
};

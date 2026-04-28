export type PageType =
  | 'receipt'        // page IS the provenance receipt — exec audience
  | 'narrative'      // story with charts + provenance rail — reviewer
  | 'investigation'  // analyst depth: charts + claim chips + filters
  | 'metric'         // dashboard-style KPI grid
  | 'browse'         // index/list/search
  | 'audit';         // debug/QA — graphs, raw data viewers

export type Severity = 'error' | 'warn' | 'info';

export interface Finding {
  layer: number;            // 1..6
  rule: string;             // stable rule id, e.g. 'sql-block-syntax'
  severity: Severity;
  file?: string;            // page or source file
  line?: number;
  snippet?: string;         // short excerpt around the issue
  location?: string;        // human-readable location, e.g. 'body text near char 1234'
  hint?: string;            // actionable fix suggestion (used by --explain)
}

export interface PreflightResult {
  pass: boolean;
  findings: Finding[];
  pagesChecked: number;
  durationMs: number;
  layers: { [k: number]: { passed: number; failed: number; durationMs: number } };
}

export interface CheckContext {
  reportsDir: string;       // absolute path to reports/
  pagesDir: string;         // reportsDir + '/pages'
  sourcesDir: string;       // reportsDir + '/sources'
  projectRoot: string;      // typically reportsDir + '/..'
  duckdbPath?: string;      // path to .duckdb file, optional
  duckdbModulePath?: string; // resolved @duckdb/node-api path (caller-supplied to avoid resolution issues)
  pagesFilter?: string[];   // substring fragments to filter pages
  baseUrl?: string;         // dev server base, when relevant
  agentBrowserPath?: string;
}

export interface PreflightRule {
  id: string;
  layer: number;
  appliesTo?: PageType[];   // omit = all page types
  severity: Severity;
  description: string;
  hint?: string;
  check: (ctx: CheckContext) => Promise<Finding[]>;
}

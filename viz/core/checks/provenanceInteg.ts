/**
 * L5 — Provenance Integrity Check (NEW)
 *
 * Reads .insight-kit/runs/*\/claims.jsonl (or claims.json) under projectRoot.
 * Validates:
 *   - cite-not-found: each cites[] entry resolves to a known claim id
 *   - provenance-cycle: Tarjan SCC detects cycles in the citation graph
 *   - orphan-claim: claims with no cites and not cited by any other (warn)
 */

import type { Finding, CheckContext } from '@insight-kit/viz-core/types';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

/** Minimal claim shape from claims.jsonl / claims.json records. */
interface Claim {
  id: string;
  cites?: string[];
  /** source file path, if present in the record */
  file?: string;
}

/** Read claims from a single file (jsonl = one JSON per line, json = array or single object). */
async function readClaimsFile(filePath: string): Promise<Claim[]> {
  let text: string;
  try {
    text = await fs.readFile(filePath, 'utf8');
  } catch {
    return [];
  }

  const claims: Claim[] = [];

  if (filePath.endsWith('.jsonl')) {
    for (const line of text.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj = JSON.parse(trimmed) as Claim;
        if (obj && typeof obj.id === 'string') claims.push(obj);
      } catch {
        // malformed line — skip
      }
    }
  } else {
    // .json — may be array or single object
    try {
      const parsed = JSON.parse(text) as Claim | Claim[];
      if (Array.isArray(parsed)) {
        claims.push(...parsed.filter(c => c && typeof c.id === 'string'));
      } else if (parsed && typeof parsed.id === 'string') {
        claims.push(parsed);
      }
    } catch {
      // malformed
    }
  }

  return claims;
}

// ---------------------------------------------------------------------------
// Tarjan SCC — pure TS, ~40 lines
// ---------------------------------------------------------------------------

interface TarjanState {
  index: Map<string, number>;
  lowlink: Map<string, number>;
  onStack: Map<string, boolean>;
  stack: string[];
  counter: number;
  sccs: string[][];
}

function tarjanVisit(
  v: string,
  adj: Map<string, string[]>,
  state: TarjanState
): void {
  const idx = state.counter++;
  state.index.set(v, idx);
  state.lowlink.set(v, idx);
  state.stack.push(v);
  state.onStack.set(v, true);

  for (const w of (adj.get(v) ?? [])) {
    if (!state.index.has(w)) {
      tarjanVisit(w, adj, state);
      state.lowlink.set(v, Math.min(state.lowlink.get(v)!, state.lowlink.get(w)!));
    } else if (state.onStack.get(w)) {
      state.lowlink.set(v, Math.min(state.lowlink.get(v)!, state.index.get(w)!));
    }
  }

  // If v is a root node, pop the SCC
  if (state.lowlink.get(v) === state.index.get(v)) {
    const scc: string[] = [];
    let w: string;
    do {
      w = state.stack.pop()!;
      state.onStack.set(w, false);
      scc.push(w);
    } while (w !== v);
    state.sccs.push(scc);
  }
}

function tarjanSCCs(nodes: string[], adj: Map<string, string[]>): string[][] {
  const state: TarjanState = {
    index: new Map(),
    lowlink: new Map(),
    onStack: new Map(),
    stack: [],
    counter: 0,
    sccs: [],
  };

  for (const v of nodes) {
    if (!state.index.has(v)) {
      tarjanVisit(v, adj, state);
    }
  }

  // Return only non-singleton SCCs (these are cycles)
  return state.sccs.filter(scc => scc.length > 1);
}

// ---------------------------------------------------------------------------

export async function checkProvenanceIntegrity(ctx: CheckContext): Promise<Finding[]> {
  const findings: Finding[] = [];

  // ---- Discover runs directories ----
  const runsRoot = path.join(ctx.projectRoot, '.insight-kit', 'runs');

  let runDirs: string[];
  try {
    const entries = await fs.readdir(runsRoot, { withFileTypes: true });
    runDirs = entries
      .filter(e => e.isDirectory())
      .map(e => path.join(runsRoot, e.name));
  } catch {
    // No .insight-kit/runs dir — nothing to check
    return findings;
  }

  // ---- Load all claims across all runs ----
  const allClaims: Claim[] = [];
  const claimSourceFile = new Map<string, string>(); // claim id -> source file path

  for (const runDir of runDirs) {
    // Prefer claims.jsonl; fall back to claims.json
    const candidates = [
      path.join(runDir, 'claims.jsonl'),
      path.join(runDir, 'claims.json'),
    ];
    for (const candidate of candidates) {
      const claims = await readClaimsFile(candidate);
      if (claims.length > 0) {
        for (const c of claims) {
          allClaims.push(c);
          claimSourceFile.set(c.id, c.file ?? candidate);
        }
        break; // found claims for this run
      }
    }
  }

  if (allClaims.length === 0) return findings;

  // ---- Build id map ----
  const claimById = new Map<string, Claim>();
  for (const c of allClaims) {
    claimById.set(c.id, c);
  }

  // ---- Build adjacency list (from = citing, to = cited) ----
  const adj = new Map<string, string[]>();
  const citedBy = new Map<string, string[]>(); // reverse: cited -> [citers]

  for (const c of allClaims) {
    adj.set(c.id, []);
    if (!citedBy.has(c.id)) citedBy.set(c.id, []);
  }

  for (const c of allClaims) {
    for (const citedId of (c.cites ?? [])) {
      // cite-not-found
      if (!claimById.has(citedId)) {
        findings.push({
          layer: 5,
          rule: 'cite-not-found',
          severity: 'error',
          file: claimSourceFile.get(c.id),
          snippet: `claim "${c.id}" cites unknown id "${citedId}"`,
          hint: `Add a claim with id "${citedId}" or remove the citation.`,
        });
        continue;
      }
      adj.get(c.id)!.push(citedId);
      citedBy.get(citedId)!.push(c.id);
    }
  }

  // ---- Tarjan SCC cycle detection ----
  const nodes = Array.from(claimById.keys());
  const cycles = tarjanSCCs(nodes, adj);

  for (const cycle of cycles) {
    findings.push({
      layer: 5,
      rule: 'provenance-cycle',
      severity: 'error',
      snippet: cycle.join(' -> ') + ` -> ${cycle[cycle.length - 1]}`,
      hint: 'Break the citation cycle. Provenance graphs must be acyclic (DAG).',
    });
  }

  // ---- Orphan claims (no cites, not cited by any other) ----
  for (const c of allClaims) {
    const hasCites = (c.cites ?? []).length > 0;
    const isCited = (citedBy.get(c.id) ?? []).length > 0;
    if (!hasCites && !isCited) {
      findings.push({
        layer: 5,
        rule: 'orphan-claim',
        severity: 'warn',
        file: claimSourceFile.get(c.id),
        snippet: `claim "${c.id}" has no citations and is not cited by any other claim`,
        hint: 'Connect this claim to the provenance graph or remove it.',
      });
    }
  }

  return findings;
}

/**
 * L4 — Numeric / Render Sanity (orchestrator stub for M2)
 *
 * M3 owns agent-browser spawning. M2's contract: accept pre-computed eval-output
 * JSON (the stringified array returned by evalPayloads/l4.js) and map each row
 * to a Finding. Mirrors Python _check_page_l4() result mapping.
 */

import type { Finding } from '@insight-kit/viz-core/types';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Raw finding row emitted by the l4.js IIFE running in agent-browser. */
export interface L4RawFinding {
  check: string;
  snippet: string;
  location: string;
}

/** Pre-computed eval output for one page: route + raw agent-browser stdout. */
export interface L4PageEvalOutput {
  route: string;
  /** Raw stdout from agent-browser eval — may be double-encoded JSON string. */
  rawOutput: string;
}

/**
 * Parse double-encoded JSON output from agent-browser eval.
 * agent-browser wraps result in an outer JSON string: `"[{...}]"`.
 * Try outer JSON.parse first; if result is still a string, parse again.
 * Fallback: regex-extract a JSON array from raw output.
 */
function parseEvalOutput(rawOutput: string): L4RawFinding[] {
  const trimmed = rawOutput.trim();
  try {
    const outer = JSON.parse(trimmed);
    const inner = typeof outer === 'string' ? JSON.parse(outer) : outer;
    if (Array.isArray(inner)) return inner as L4RawFinding[];
  } catch {
    // fallback below
  }
  // Fallback: find JSON array
  const m = /(\[[\s\S]*\])/.exec(trimmed);
  if (m) {
    try {
      const arr = JSON.parse(m[1]);
      if (Array.isArray(arr)) return arr as L4RawFinding[];
    } catch {
      // nothing
    }
  }
  return [];
}

/**
 * Map L4 raw findings for one page into typed Finding objects.
 */
function mapFindings(route: string, raw: L4RawFinding[]): Finding[] {
  return raw.map(r => ({
    layer: 4,
    rule: `l4-${r.check}`,
    severity: 'warn' as const,
    file: route,
    snippet: r.snippet?.slice(0, 200),
    location: r.location,
    hint: `L4 numeric/render sanity check failed: ${r.check}`,
  }));
}

/**
 * Accept pre-computed eval-output JSON from M3's agent-browser orchestration
 * and return typed Finding[].
 *
 * @param pages - per-page eval outputs (route + raw agent-browser stdout)
 * @returns flat array of Findings across all pages
 */
export async function checkNumericSanity(
  pages: L4PageEvalOutput[]
): Promise<Finding[]> {
  const findings: Finding[] = [];

  for (const page of pages) {
    const raw = parseEvalOutput(page.rawOutput);
    findings.push(...mapFindings(page.route, raw));
  }

  return findings;
}

/**
 * Load the L4 eval payload JS string from evalPayloads/l4.js.
 * M3 passes this to agent-browser eval --stdin.
 */
export async function loadL4Payload(): Promise<string> {
  const payloadPath = path.join(__dirname, 'evalPayloads', 'l4.js');
  return fs.readFile(payloadPath, 'utf8');
}

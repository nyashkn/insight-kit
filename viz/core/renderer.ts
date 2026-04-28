import type { PageType, PreflightRule, PreflightResult, CheckContext } from './types.js';

export interface Renderer {
  /** Plugin identifier, e.g. 'evidence', 'markdown', 'malloy'. */
  name: string;
  /** Page types this renderer can produce. */
  pageTypes: PageType[];
  /** Copy/symlink components, layouts, generators into the consumer reports dir. */
  install(reportsDir: string, options?: Record<string, unknown>): Promise<void>;
  /** Renderer-specific build gate (e.g. evidence build, seaborn render). */
  buildGate(ctx: CheckContext): Promise<PreflightResult>;
  /** Renderer-specific preflight rules (Layer 2 + plugin-specific layers). */
  rules: PreflightRule[];
}

const _registry = new Map<string, Renderer>();

export function registerRenderer(r: Renderer): void {
  if (_registry.has(r.name)) throw new Error(`Renderer already registered: ${r.name}`);
  _registry.set(r.name, r);
}

export function getRenderer(name: string): Renderer {
  const r = _registry.get(name);
  if (!r) throw new Error(`Renderer not found: ${name}. Registered: ${[..._registry.keys()].join(', ')}`);
  return r;
}

export function listRenderers(): string[] {
  return [..._registry.keys()];
}

# @insight-kit/viz-evidence

Evidence renderer plugin for insight-kit: Svelte claim components, claim indexing utilities, and Evidence v40 integration.

## Installation

```bash
npm install @insight-kit/viz-evidence
```

### In Evidence v40 projects

Register the plugin in your `evidence.config.yaml`:

```yaml
plugins:
  components:
    "@insight-kit/viz-evidence": {}
```

Evidence will auto-discover all Svelte components in the package's `components/` directory.

## Component Catalog

### ClaimBlock
Full claim card renderer with confidence, tier, cites, challenges, and optional interpretation.
Props:
- `claim: Claim` — claim object
- `showInterpretation?: boolean` — show interpretation details (default: false)
- `variant?: "default" | "hero" | "compact"` — card style variant

### ClaimInline
Inline citation chip with click-to-expand popover. Use for inline textual references.
Props:
- `claimId: string` — ID of the claim to cite
- `text?: string` — optional label text before chip
- `manifest?: Record<string, Claim>` — indexed claim manifest (from claimsManifest.indexClaims)

### ClaimDelta
Side-by-side claim comparison renderer (e.g., claim revision, supersession).
Props:
- `from: Claim` — older/superseded claim
- `to: Claim` — newer/superseding claim
- `reason?: string` — explicit delta reason; defaults to claim IDs

### ClaimTree
Recursive claim hierarchy tree (DAG, cycle-aware, depth-based expansion).
Props:
- `data: TreeNode[]` — array of tree nodes with claim_id, parent_id, depth, tier, statement, confidence
- `root: string` — root claim_id (whose parent_id is null)

### ClaimTreeNode
Internal recursive renderer for ClaimTree. Not typically invoked directly.

### ProvenanceRail
Sticky right-rail provenance receipt for narrative pages. Shows upstream (PRE) and downstream (POST) claim references.
Props:
- `focal: string` — focal claim ID
- `manifest: Record<string, Claim>` — indexed claim manifest
- `edges: Array<{from: string, to: string, kind: string}>` — claim edges (supports, refutes, supersedes)
- `sourceClaim?: string` — optional ETL_M source claim ID for footer chip

## Utilities

### claimsManifest.js

**indexClaims(rows: Claim[]): Record<string, Claim>**
Build a claim ID lookup map from an array of claim objects. Use this with Evidence query results.

**getClaim(manifest: Record<string, Claim>, claimId: string): Claim|undefined**
Convenience lookup for a single claim in the manifest.

**claimsByTier(manifest: Record<string, Claim>, tier: string): Claim[]**
Filter claims by tier (e.g., "derived", "critic", "initiative").

## License

MIT

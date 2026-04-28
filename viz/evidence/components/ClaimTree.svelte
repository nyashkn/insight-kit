<script context="module">
  export const evidenceInclude = true;
</script>

<script>
  /**
   * ClaimTree — recursive interactive tree for DAG claim hierarchies.
   *
   * Renders a tree of claims with depth-based expansion, tier-tinted nodes,
   * and cycle/DAG deduplication (↻ notation for shared leaves).
   *
   * @typedef {Object} TreeNode
   * @property {string}  claim_id
   * @property {string|null}  parent_id
   * @property {number}  depth
   * @property {string}  tier
   * @property {string}  statement
   * @property {string}  [confidence]  - "High" | "Medium" | "Low"
   */

  import ClaimTreeNode from './ClaimTreeNode.svelte';

  /** @type {TreeNode[]} */
  export let data = [];

  /** Root claim_id (whose parent_id is null) */
  export let root = '';

  // Track expand/collapse state: Set of claim_ids to show expanded
  let expandedNodes = new Set();

  // Precompute root depth and build children index
  $: {
    // Reset expansion on data change
    expandedNodes = new Set();
    // Auto-expand depth 0, 1, 2
    if (data && Array.isArray(data)) {
      data.forEach((row) => {
        if (row.depth <= 2) {
          expandedNodes.add(row.claim_id);
        }
      });
    }
  }

  // Build index: parent_id → [children]
  $: childrenByParent = data.reduce((acc, row) => {
    if (!acc[row.parent_id]) acc[row.parent_id] = [];
    acc[row.parent_id].push(row);
    return acc;
  }, {});

  // Find root node
  $: rootNode = data?.find((n) => n.claim_id === root && n.parent_id === null);

  // Confidence color mapping
  const confColor = {
    High: '#16a34a',
    Medium: '#c08800',
    Low: '#dc2626',
  };

  // Tier color mapping (Okabe-Ito + existing palette)
  const tierColor = {
    I: '#003e7e',        // navy (Initiative)
    C: '#cc6677',        // red (Causal/Critic)
    X: '#ddaa33',        // amber (eXception)
    D: '#44aa99',        // teal (Decomposition)
    R: '#888888',        // gray (Raw/Reference)
    ETL_M: '#1f78b4',    // indigo
  };

  function getTierColor(tier) {
    if (!tier) return '#888888';
    if (tierColor[tier]) return tierColor[tier];
    return '#6b7280';
  }

  function getTierLabel(tier) {
    const labels = { I: 'Initiative', C: 'Critic', X: 'Exception', D: 'Decomp', R: 'Raw', ETL_M: 'ETL_M' };
    return labels[tier] || tier;
  }

  function toggleExpand(claimId) {
    if (expandedNodes.has(claimId)) {
      expandedNodes.delete(claimId);
    } else {
      expandedNodes.add(claimId);
    }
    expandedNodes = expandedNodes;
  }

  function truncateStatement(stmt, maxLen = 80) {
    if (!stmt) return '';
    if (stmt.length > maxLen) return stmt.slice(0, maxLen) + '…';
    return stmt;
  }

  function renderSubtree(nodeId, parentId, visitedPath = new Set()) {
    const node = data.find((n) => n.claim_id === nodeId && n.parent_id === parentId);
    if (!node) return null;

    if (visitedPath.has(nodeId)) {
      return { type: 'cycle', node };
    }

    const newPath = new Set(visitedPath);
    newPath.add(nodeId);

    const children = childrenByParent[nodeId] || [];
    const seenChildIds = new Set();
    const dedupedChildren = [];
    for (const child of children) {
      if (!seenChildIds.has(child.claim_id)) {
        seenChildIds.add(child.claim_id);
        dedupedChildren.push(child);
      }
    }

    return {
      type: 'node',
      node,
      children: dedupedChildren.map((c) => renderSubtree(c.claim_id, nodeId, newPath)),
    };
  }

  $: tree = rootNode ? renderSubtree(root, null) : null;
</script>

{#if !data || data.length === 0}
  <div class="claim-tree-empty">No tree data available</div>
{:else if !rootNode}
  <div class="claim-tree-empty">Root {root} not found</div>
{:else if tree}
  <ul class="claim-tree">
    <ClaimTreeNode {tree} {expandedNodes} {toggleExpand} {confColor} {getTierColor} {getTierLabel} {truncateStatement} />
  </ul>
{/if}

<style>
  .claim-tree {
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: 0.875rem;
    line-height: 1.5;
  }

  .claim-tree-empty {
    padding: 1rem;
    color: #94a3b8;
    font-style: italic;
    text-align: center;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    background: #f8fafc;
  }

  :global(.claim-tree ul) {
    list-style: none;
    padding: 0;
    margin: 0;
    border-left: 1px solid #ddd;
    margin-left: 0.5rem;
    padding-left: 1rem;
  }

  :global(.claim-tree-node) {
    margin: 0.4rem 0;
  }

  :global(.claim-node-card) {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.6rem;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    background: #fff;
    transition: background 0.15s;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
  }

  :global(.claim-node-card:hover) {
    background: #f8fafc;
  }

  :global(.claim-chevron) {
    min-width: 24px;
    min-height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 0.75rem;
    color: #64748b;
    flex-shrink: 0;
  }

  :global(.claim-chevron:hover) {
    color: #1e293b;
  }

  :global(.claim-chevron.hidden) {
    visibility: hidden;
  }

  :global(.claim-id) {
    font-family: monospace;
    font-size: 0.7rem;
    font-weight: 700;
    color: #64748b;
    flex-shrink: 0;
  }

  :global(.claim-tier-badge) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 28px;
    height: 20px;
    padding: 0 0.35rem;
    border-radius: 3px;
    font-size: 0.65rem;
    font-weight: 700;
    color: #fff;
    text-transform: uppercase;
    flex-shrink: 0;
  }

  :global(.claim-conf-chip) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 24px;
    height: 18px;
    padding: 0 0.25rem;
    border-radius: 2px;
    font-size: 0.6rem;
    font-weight: 700;
    color: #fff;
    background: #6b7280;
    flex-shrink: 0;
  }

  :global(.claim-statement-label) {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.8rem;
    color: #1e293b;
  }

  :global(.claim-children-toggle) {
    display: inline-block;
    font-size: 0.75rem;
    color: #94a3b8;
    margin-left: auto;
    flex-shrink: 0;
  }

  :global(.claim-cycle-marker) {
    color: #f8c900;
    font-weight: 600;
    cursor: pointer;
    text-decoration: underline;
    text-decoration-color: #f8c900;
  }

  @media print {
    :global(.claim-tree ul) {
      border-left: none;
      margin-left: 0;
      padding-left: 1rem;
    }
    :global(.claim-tree-node.collapsed) {
      display: block !important;
    }
  }
</style>

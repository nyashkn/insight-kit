<script context="module">export const evidenceInclude = true;</script>

<script>
  /**
   * ClaimTreeNode — recursive tree node renderer.
   * Used internally by ClaimTree.
   */

  import ClaimTreeNode from './ClaimTreeNode.svelte';

  /** @type {Object} */
  export let tree;

  /** @type {Set<string>} */
  export let expandedNodes;

  /** @type {Function} */
  export let toggleExpand;

  /** @type {Object} */
  export let confColor;

  /** @type {Function} */
  export let getTierColor;

  /** @type {Function} */
  export let getTierLabel;

  /** @type {Function} */
  export let truncateStatement;

  $: node = tree.node;
  $: isExpanded = expandedNodes.has(node.claim_id);
  $: hasChildren = tree.children && tree.children.length > 0;
  $: nonCycleChildren = tree.children?.filter((c) => c.type === 'node') || [];
  $: childCount = nonCycleChildren.length;
</script>

{#if tree.type === 'cycle'}
  <!-- Cycle marker: render as text link -->
  <li class="claim-tree-node claim-cycle-node">
    <a href="/provenance/{node.claim_id}" class="claim-cycle-marker">↻ {node.claim_id}</a>
  </li>
{:else if tree.type === 'node'}
  <li class="claim-tree-node" class:collapsed={!isExpanded && hasChildren}>
    <!-- Node card -->
    <div class="claim-node-card" on:click={() => hasChildren && toggleExpand(node.claim_id)}>
      <!-- Chevron -->
      <span
        class="claim-chevron"
        class:hidden={!hasChildren}
        on:click|stopPropagation={() => toggleExpand(node.claim_id)}
      >
        {isExpanded ? '▼' : '▶'}
      </span>

      <!-- Claim ID -->
      <span class="claim-id">{node.claim_id}</span>

      <!-- Tier badge -->
      <span
        class="claim-tier-badge"
        style="background-color: {getTierColor(node.tier)}"
        title="Tier: {getTierLabel(node.tier)}"
      >
        {node.tier}
      </span>

      <!-- Confidence chip -->
      {#if node.confidence}
        <span
          class="claim-conf-chip"
          style="background-color: {confColor[node.confidence] ?? '#6b7280'}"
          title="Confidence: {node.confidence}"
        >
          {node.confidence.charAt(0)}
        </span>
      {/if}

      <!-- Statement (truncated, full on hover) -->
      <span class="claim-statement-label" title={node.statement || ''}>
        {truncateStatement(node.statement)}
      </span>

      <!-- Children count toggle -->
      {#if hasChildren && !isExpanded}
        <span class="claim-children-toggle">▶ {childCount}</span>
      {/if}
    </div>

    <!-- Children list (if expanded) -->
    {#if isExpanded && hasChildren}
      <ul>
        {#each tree.children as child (child.node.claim_id)}
          <svelte:component
            this={ClaimTreeNode}
            tree={child}
            {expandedNodes}
            {toggleExpand}
            {confColor}
            {getTierColor}
            {getTierLabel}
            {truncateStatement}
          />
        {/each}
      </ul>
    {/if}
  </li>
{/if}

<style>
  .claim-tree-node {
    margin: 0.4rem 0;
  }

  .claim-tree-node.collapsed {
    list-style: none;
  }

  .claim-node-card {
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

  .claim-node-card:hover {
    background: #f8fafc;
  }

  .claim-chevron {
    min-width: 24px;
    min-height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 0.75rem;
    color: #64748b;
    flex-shrink: 0;
    user-select: none;
  }

  .claim-chevron:hover {
    color: #1e293b;
  }

  .claim-chevron.hidden {
    visibility: hidden;
  }

  .claim-id {
    font-family: monospace;
    font-size: 0.7rem;
    font-weight: 700;
    color: #64748b;
    flex-shrink: 0;
  }

  .claim-tier-badge {
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

  .claim-conf-chip {
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

  .claim-statement-label {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.8rem;
    color: #1e293b;
  }

  .claim-children-toggle {
    display: inline-block;
    font-size: 0.75rem;
    color: #94a3b8;
    margin-left: auto;
    flex-shrink: 0;
    user-select: none;
  }

  .claim-cycle-node {
    margin: 0.4rem 0;
  }

  .claim-cycle-marker {
    color: #f8c900;
    font-weight: 600;
    cursor: pointer;
    text-decoration: underline;
    text-decoration-color: #f8c900;
    font-size: 0.8rem;
    font-family: monospace;
  }

  .claim-cycle-marker:hover {
    text-decoration-thickness: 2px;
  }

  :global(ul) {
    list-style: none;
    padding: 0;
    margin: 0;
    border-left: 1px solid #ddd;
    margin-left: 0.5rem;
    padding-left: 1rem;
  }

  @media print {
    :global(ul) {
      border-left: none;
      margin-left: 0;
    }
  }
</style>

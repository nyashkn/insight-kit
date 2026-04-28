<script context="module">export const evidenceInclude = true;</script>

<script>
  /**
   * ClaimInline — inline citation chip with popover.
   *
   * Usage (parent has loaded claims manifest):
   *   <ClaimInline claimId="RC-01" manifest={claimsMap} />
   *   <ClaimInline claimId="RC-01" manifest={claimsMap} text="CVR collapsed" />
   *
   * @typedef {import('./ClaimBlock.svelte').Claim} Claim
   */

  /** @type {string} */
  export let claimId;

  /** @type {string|undefined} */
  export let text = undefined;

  /**
   * Map of claim_id → Claim object. Pass the result of loadClaimsManifest() here.
   * @type {Record<string,Claim>|undefined}
   */
  export let manifest = undefined;

  let open = false;

  $: claim = manifest?.[claimId];

  const confColor = {
    High:   '#16a34a',
    Medium: '#c08800',
    Low:    '#dc2626',
  };

  function toggle() { open = !open; }

  function handleKeydown(/** @type {KeyboardEvent} */ e) {
    if (e.key === 'Escape') open = false;
    if (e.key === 'Enter' || e.key === ' ') toggle();
  }
</script>

<span class="claim-inline-wrapper">
  {#if text}<span class="claim-text">{text}</span>{/if}
  <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
  <button
    class="claim-chip"
    aria-expanded={open}
    aria-label="Claim {claimId}"
    on:click={toggle}
    on:keydown={handleKeydown}
    style="border-color:{confColor[claim?.confidence ?? ''] ?? '#94a3b8'}"
  >
    ↗{claimId}
  </button>

  {#if open && claim}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="claim-popover" role="tooltip" on:click|stopPropagation>
      <div class="popover-header">
        <span class="popover-id">{claim.claim_id}</span>
        {#if claim.confidence}
          <span
            class="popover-conf"
            style="color:{confColor[claim.confidence] ?? '#6b7280'}"
          >{claim.confidence} confidence</span>
        {/if}
        <button class="popover-close" on:click={toggle} aria-label="Close">×</button>
      </div>
      <p class="popover-statement">{claim.statement}</p>
      {#if claim.confidence_reason}
        <p class="popover-reason">{claim.confidence_reason}</p>
      {/if}
    </div>
  {/if}

  {#if open && !claim}
    <div class="claim-popover claim-popover--missing" role="tooltip">
      <p>Claim <code>{claimId}</code> not found in manifest.</p>
    </div>
  {/if}
</span>

<style>
  .claim-inline-wrapper {
    display: inline;
    position: relative;
  }

  .claim-text {
    margin-right: 0.15em;
  }

  .claim-chip {
    display: inline-flex;
    align-items: center;
    font-size: 0.68rem;
    font-family: monospace;
    font-weight: 700;
    padding: 0.05rem 0.3rem;
    border: 1px solid #94a3b8;
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
    vertical-align: super;
    line-height: 1;
    color: inherit;
    transition: background 0.1s;
    white-space: nowrap;
  }

  .claim-chip:hover {
    background: #f1f5f9;
  }

  .claim-popover {
    position: absolute;
    z-index: 50;
    top: calc(100% + 0.4rem);
    left: 0;
    min-width: 260px;
    max-width: 360px;
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.1);
    padding: 0.75rem;
    font-size: 0.8rem;
    line-height: 1.45;
  }

  .claim-popover--missing {
    color: #dc2626;
    font-size: 0.8rem;
  }

  .popover-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.4rem;
  }

  .popover-id {
    font-family: monospace;
    font-size: 0.75rem;
    font-weight: 700;
    color: #64748b;
  }

  .popover-conf {
    font-size: 0.7rem;
    font-weight: 600;
  }

  .popover-close {
    margin-left: auto;
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
    color: #94a3b8;
    padding: 0;
  }

  .popover-statement {
    margin: 0 0 0.35rem;
    font-weight: 500;
    color: #1e293b;
  }

  .popover-reason {
    margin: 0;
    color: #64748b;
    font-style: italic;
    font-size: 0.75rem;
  }
</style>

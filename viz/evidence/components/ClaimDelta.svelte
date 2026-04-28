<script context="module">export const evidenceInclude = true;</script>

<script>
  /**
   * ClaimDelta — compares two claims (superseded chain or before/after).
   *
   * Props:
   *   from  — the older / superseded claim object
   *   to    — the newer / superseding claim object
   *   reason (optional) — explicit delta reason string; falls back to
   *                        diff between from.statement and to.statement
   *
   * @typedef {import('./ClaimBlock.svelte').Claim} Claim
   */

  /** @type {Claim} */
  export let from;

  /** @type {Claim} */
  export let to;

  /** @type {string|undefined} */
  export let reason = undefined;

  const confColor = {
    High:   '#16a34a',
    Medium: '#c08800',
    Low:    '#dc2626',
  };

  $: deltaReason = reason
    ?? (from?.claim_id && to?.claim_id
      ? `${from.claim_id} superseded by ${to.claim_id}`
      : 'Revised');

  $: confChanged = from?.confidence !== to?.confidence;
</script>

<div class="claim-delta" data-from={from?.claim_id} data-to={to?.claim_id}>
  <div class="delta-label">Claim revision</div>

  <div class="delta-row">
    <!-- FROM (old, struck-through) -->
    <div class="delta-from">
      <div class="delta-meta">
        <span class="delta-id">{from?.claim_id ?? '—'}</span>
        {#if from?.confidence}
          <span class="delta-conf" style="color:{confColor[from.confidence] ?? '#6b7280'}">
            {from.confidence}
          </span>
        {/if}
      </div>
      <p class="delta-statement delta-statement--old">{from?.statement ?? ''}</p>
    </div>

    <div class="delta-arrow" aria-hidden="true">→</div>

    <!-- TO (new) -->
    <div class="delta-to">
      <div class="delta-meta">
        <span class="delta-id">{to?.claim_id ?? '—'}</span>
        {#if to?.confidence}
          <span
            class="delta-conf"
            style="color:{confColor[to.confidence] ?? '#6b7280'}"
            class:delta-conf--changed={confChanged}
          >
            {to.confidence}{confChanged ? ' ↑' : ''}
          </span>
        {/if}
      </div>
      <p class="delta-statement delta-statement--new">{to?.statement ?? ''}</p>
    </div>
  </div>

  <div class="delta-reason">
    <span class="delta-reason-label">Why:</span>
    {deltaReason}
  </div>

  {#if from?.analyst || to?.analyst}
    <div class="delta-footer">
      {#if from?.analyst}<span>old: {from.analyst}</span>{/if}
      {#if to?.analyst}<span>new: {to.analyst}</span>{/if}
    </div>
  {/if}
</div>

<style>
  .claim-delta {
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 0.875rem 1rem;
    margin: 0.75rem 0;
    background: var(--background, #fff);
    font-size: 0.875rem;
  }

  .delta-label {
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 700;
    color: #94a3b8;
    margin-bottom: 0.6rem;
  }

  .delta-row {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 0.75rem;
    align-items: start;
  }

  .delta-arrow {
    font-size: 1.2rem;
    color: #94a3b8;
    padding-top: 1.4rem;
    user-select: none;
  }

  .delta-meta {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-bottom: 0.3rem;
  }

  .delta-id {
    font-family: monospace;
    font-size: 0.72rem;
    font-weight: 700;
    color: #64748b;
  }

  .delta-conf {
    font-size: 0.7rem;
    font-weight: 600;
  }

  .delta-conf--changed {
    font-weight: 800;
  }

  .delta-statement {
    margin: 0;
    line-height: 1.45;
  }

  .delta-statement--old {
    text-decoration: line-through;
    color: #94a3b8;
  }

  .delta-statement--new {
    color: #1e293b;
    font-weight: 500;
  }

  .delta-reason {
    margin-top: 0.75rem;
    font-size: 0.78rem;
    color: #475569;
    border-top: 1px dashed #e2e8f0;
    padding-top: 0.5rem;
  }

  .delta-reason-label {
    font-weight: 700;
    margin-right: 0.3rem;
    color: #64748b;
  }

  .delta-footer {
    display: flex;
    gap: 1rem;
    font-size: 0.68rem;
    color: #94a3b8;
    margin-top: 0.4rem;
  }
</style>

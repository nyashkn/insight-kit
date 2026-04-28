<script context="module">export const evidenceInclude = true;</script>

<script>
  /**
   * ClaimBlock — full claim card.
   *
   * @typedef {Object} Claim
   * @property {string}  claim_id
   * @property {string}  statement
   * @property {string}  [confidence]         - "High" | "Medium" | "Low"
   * @property {string}  [confidence_reason]
   * @property {string}  [tier]               - "derived" | "critic" | "initiative" | "viz"
   * @property {string[]} [cites]             - supports / citation IDs
   * @property {string}  [target_claim]       - refuted claim (critic tier)
   * @property {string}  [target]             - alternate refuted claim key
   * @property {string}  [verdict]            - critic verdict string
   * @property {string}  [severity]           - critic severity ("weakening" | "noted")
   * @property {string}  [interpretation]     - extended interpretation prose
   * @property {string[]} [caveats]           - optional caveats array
   * @property {string}  [analyst]            - analyst persona slug
   * @property {string}  [run_id]             - originating run id
   */

  /** @type {Claim} */
  export let claim;

  /** If true, shows full interpretation block. @type {boolean} */
  export let showInterpretation = false;

  /**
   * Display variant.
   * "default" — standard card
   * "hero"    — large anchor-claim card (left navy border, larger font)
   * "compact" — small card for use inside tables or lists
   * @type {"default"|"hero"|"compact"}
   */
  export let variant = 'default';

  const confidenceColor = {
    High:   'background-color:#16a34a;color:#fff',
    Medium: 'background-color:#f8c900;color:#1a1a1a',
    Low:    'background-color:#dc2626;color:#fff',
  };

  const tierBadgeStyle = {
    derived:    'background-color:#1d4ed8;color:#fff',
    critic:     'background-color:#7c3aed;color:#fff',
    initiative: 'background-color:#0369a1;color:#fff',
    viz:        'background-color:#0d9488;color:#fff',
  };

  $: conf     = claim?.confidence ?? '';
  $: tier     = claim?.tier ?? '';
  $: supports = claim?.cites ?? [];
  $: refutes  = [claim?.target_claim, claim?.target].filter(Boolean);
  $: caveats  = claim?.caveats ?? [];
</script>

<div class="claim-block {variant}" data-claim-id={claim?.claim_id} data-tier={tier}>
  <div class="claim-header">
    <span class="claim-id">{claim?.claim_id ?? '—'}</span>
    {#if tier}
      <span class="badge" style={tierBadgeStyle[tier] ?? 'background-color:#6b7280;color:#fff'}>{tier}</span>
    {/if}
    {#if conf}
      <span class="badge" style={confidenceColor[conf] ?? ''} title={claim?.confidence_reason ?? ''}>
        {conf}
      </span>
    {/if}
    {#if claim?.analyst}
      <span class="analyst-chip">via {claim.analyst}</span>
    {/if}
  </div>

  <p class="claim-statement">{claim?.statement ?? ''}</p>

  {#if claim?.verdict || claim?.severity}
    <div class="critic-verdict">
      {#if claim.severity}<span class="severity-{claim.severity}">{claim.severity}</span>{/if}
      {#if claim.verdict} · <em>{claim.verdict}</em>{/if}
    </div>
  {/if}

  {#if showInterpretation && claim?.interpretation}
    <details class="interpretation">
      <summary>Interpretation</summary>
      <p>{claim.interpretation}</p>
    </details>
  {/if}

  {#if caveats.length > 0}
    <ul class="caveats">
      {#each caveats as caveat}
        <li>{caveat}</li>
      {/each}
    </ul>
  {/if}

  <div class="claim-edges">
    {#if supports.length > 0}
      <span class="edges-label">cites:</span>
      {#each supports as id}
        <span class="edge-chip support">{id}</span>
      {/each}
    {/if}
    {#if refutes.length > 0}
      <span class="edges-label">challenges:</span>
      {#each refutes as id}
        <span class="edge-chip refute">{id}</span>
      {/each}
    {/if}
    {#if claim?.run_id}
      <span class="edges-label">run:</span>
      <span class="edge-chip run">{claim.run_id}</span>
    {/if}
  </div>
</div>

<style>
  .claim-block {
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 0.875rem 1rem;
    margin: 0.75rem 0;
    background: var(--background, #fff);
    font-size: 0.875rem;
    line-height: 1.5;
  }

  .claim-header {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
    margin-bottom: 0.5rem;
  }

  .claim-id {
    font-family: monospace;
    font-size: 0.75rem;
    color: #64748b;
    font-weight: 600;
  }

  .badge {
    font-size: 0.65rem;
    font-weight: 700;
    padding: 0.1rem 0.4rem;
    border-radius: 9999px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    cursor: help;
  }

  .analyst-chip {
    font-size: 0.65rem;
    color: #94a3b8;
    margin-left: auto;
  }

  .claim-statement {
    margin: 0 0 0.5rem;
    font-weight: 500;
    color: inherit;
  }

  .critic-verdict {
    font-size: 0.75rem;
    color: #7c3aed;
    margin-bottom: 0.4rem;
  }

  .severity-weakening { color: #dc2626; font-weight: 700; }
  .severity-noted     { color: #f8c900; font-weight: 700; }

  .interpretation {
    margin: 0.4rem 0;
    font-size: 0.8rem;
    color: #475569;
  }
  .interpretation summary {
    cursor: pointer;
    color: #64748b;
    user-select: none;
  }

  .caveats {
    font-size: 0.78rem;
    color: #92400e;
    padding-left: 1.2rem;
    margin: 0.4rem 0;
  }

  .claim-edges {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.3rem;
    margin-top: 0.5rem;
  }

  .edges-label {
    font-size: 0.65rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .edge-chip {
    font-size: 0.7rem;
    padding: 0.05rem 0.35rem;
    border-radius: 4px;
    font-family: monospace;
  }

  .edge-chip.support { background: #dbeafe; color: #1d4ed8; }
  .edge-chip.refute  { background: #fce7f3; color: #9d174d; }
  .edge-chip.run     { background: #f1f5f9; color: #475569; }

  /* ── hero variant ─────────────────────────────────────────────────────── */
  .claim-block.hero {
    border-left: 4px solid #0d3b6e;
    padding: 1.25rem 1.5rem;
    background: linear-gradient(135deg, rgba(13,59,110,0.05) 0%, rgba(36,113,163,0.03) 100%);
  }
  .claim-block.hero .claim-statement {
    font-size: 1rem;
    font-weight: 600;
    line-height: 1.65;
  }
  .claim-block.hero .claim-id {
    font-size: 0.82rem;
  }

  /* ── compact variant ──────────────────────────────────────────────────── */
  .claim-block.compact {
    padding: 0.45rem 0.7rem;
    margin: 0.25rem 0;
    border-radius: 4px;
    font-size: 0.78rem;
  }
  .claim-block.compact .claim-statement {
    margin-bottom: 0.2rem;
    font-size: 0.78rem;
  }
  .claim-block.compact .claim-header {
    margin-bottom: 0.2rem;
  }
  .claim-block.compact .claim-edges {
    margin-top: 0.2rem;
  }
  .claim-block.compact .interpretation,
  .claim-block.compact .caveats {
    display: none;
  }
</style>

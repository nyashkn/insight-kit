<script context="module">export const evidenceInclude = true;</script>

<script>
  /**
   * ProvenanceRail — sticky right-rail provenance receipt for narrative pages.
   *
   * Shows the focal claim's upstreams (PRE: cites/input_claims) and downstreams (POST: claims citing/refuting/superseding focal).
   * Click any upstream/downstream link to jump to /provenance/<claim_id>.
   *
   * @typedef {Object} Claim
   * @property {string}   claim_id
   * @property {string}   statement
   * @property {string}   [tier]
   * @property {string}   [confidence]
   * @property {string[]} [cites]
   * @property {string}   [target_claim]
   * @property {string}   [target]
   * @property {string}   [verdict]
   * @property {string}   [severity]
   */

  /** Focal claim ID (the narrative's primary claim). @type {string} */
  export let focal;

  /** Indexed claims: claim_id → Claim. @type {Record<string, Claim>} */
  export let manifest = {};

  /** Edge list: array of {from, to, kind}. @type {Array<{from: string, to: string, kind: string}>} */
  export let edges = [];

  /**
   * Optional ETL_M-tier source claim ID that feeds this page's Evidence source.
   * When provided, renders a "Reads from source:" footer chip linking to
   * /provenance/<sourceClaim>.
   * @type {string | undefined}
   */
  export let sourceClaim = undefined;

  $: focalClaim = manifest?.[focal];

  // Resolve the materializes label for the source claim chip (if provided and in manifest)
  $: sourceClaimLabel = sourceClaim
    ? (manifest?.[sourceClaim]?.materializes ?? sourceClaim)
    : undefined;

  // Upstream (PRE): claims that focal cites or claims that focal refutes
  // These are: edges FROM focal TO other claims (e.g., supports, refutes)
  $: upstreamClaims = edges
    .filter(e => e.from === focal && (e.kind === 'supports' || e.kind === 'refutes' || e.kind === 'supersedes'))
    .map(e => e.to)
    .filter((id, idx, arr) => arr.indexOf(id) === idx);

  // Downstream (POST): claims that cite focal or challenge focal
  // These are: edges TO focal FROM other claims
  $: downstreamClaims = edges
    .filter(e => e.to === focal)
    .map(e => e.from)
    .filter((id, idx, arr) => arr.indexOf(id) === idx);

  const tierColor = {
    derived:    '#1d4ed8',    // blue
    critic:     '#7c3aed',    // purple
    initiative: '#0369a1',    // cyan
    viz:        '#0d9488',    // teal
  };

  const confidenceColor = {
    High:   '#16a34a',        // green
    Medium: '#c08800',        // amber/gold
    Low:    '#dc2626',        // red
  };

  // Navy accent per Okabe-Ito + design spec
  const navyAccent = '#003e7e';
  const amberHighlight = '#ffa600';
</script>

<aside class="provenance-rail">
  {#if focalClaim}
    <!-- PRE: upstream claims -->
    <div class="rail-section pre">
      <div class="section-header">
        <span class="section-label">PRE</span>
        <span class="section-count">{upstreamClaims.length}</span>
      </div>
      <div class="section-title">Cites / Targets</div>

      {#if upstreamClaims.length > 0}
        <ul class="claim-list">
          {#each upstreamClaims as claimId}
            <li class="claim-item">
              <a href="/provenance/{claimId}" class="claim-link">
                <span class="claim-id">{claimId}</span>
              </a>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="empty-state">(none)</p>
      {/if}
    </div>

    <!-- FOCAL: the anchor claim -->
    <div class="rail-section focal">
      <div class="focal-card">
        <span class="focal-id" style="color:{navyAccent}">{focalClaim.claim_id}</span>
        <p class="focal-statement">{focalClaim.statement}</p>
        {#if focalClaim.confidence}
          <div class="focal-conf" style="color:{confidenceColor[focalClaim.confidence] ?? '#94a3b8'}">
            {focalClaim.confidence} confidence
          </div>
        {/if}
      </div>
    </div>

    <!-- POST: downstream citations -->
    <div class="rail-section post">
      <div class="section-header">
        <span class="section-label">POST</span>
        <span class="section-count">{downstreamClaims.length}</span>
      </div>
      <div class="section-title">Cited by</div>

      {#if downstreamClaims.length > 0}
        <ul class="claim-list">
          {#each downstreamClaims as claimId}
            <li class="claim-item">
              <a href="/provenance/{claimId}" class="claim-link">
                <span class="claim-id">{claimId}</span>
              </a>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="empty-state">(none)</p>
      {/if}
    </div>
  {/if}

  {#if sourceClaim}
    <!-- SOURCE: ETL_M source claim footer chip -->
    <div class="rail-section source-footer">
      <div class="source-label">Reads from source:</div>
      <a href="/provenance/{sourceClaim}" class="source-chip">
        <span class="source-claim-id">{sourceClaim}</span>
        {#if sourceClaimLabel && sourceClaimLabel !== sourceClaim}
          <span class="source-materializes">{sourceClaimLabel}</span>
        {/if}
      </a>
    </div>
  {/if}
</aside>

<style>
  .provenance-rail {
    position: sticky;
    top: 1rem;
    width: 100%;
    max-width: 280px;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    font-size: 0.875rem;
    line-height: 1.5;
  }

  .rail-section {
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 0.875rem 1rem;
    background: #fff;
  }

  .rail-section.focal {
    border-left: 4px solid #003e7e;
    background: linear-gradient(135deg, rgba(0, 62, 126, 0.05) 0%, rgba(255, 166, 0, 0.02) 100%);
  }

  .section-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.6rem;
    padding-bottom: 0.4rem;
    border-bottom: 1px solid #f1f5f9;
  }

  .section-label {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #64748b;
  }

  .section-count {
    font-size: 0.75rem;
    font-weight: 600;
    color: #94a3b8;
    margin-left: auto;
  }

  .section-title {
    font-size: 0.8rem;
    font-weight: 600;
    color: #1e293b;
    margin-bottom: 0.5rem;
  }

  .section-subtitle {
    font-size: 0.75rem;
    font-weight: 600;
    color: #64748b;
    margin-top: 0.6rem;
    margin-bottom: 0.4rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .claim-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .claim-item {
    margin: 0;
  }

  .claim-link {
    display: flex;
    align-items: center;
    padding: 0.35rem 0.5rem;
    border-radius: 4px;
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    text-decoration: none;
    color: #1e293b;
    font-size: 0.8rem;
    transition: all 0.15s;
    cursor: pointer;
  }

  .claim-link:hover {
    background: #f1f5f9;
    border-color: #cbd5e1;
  }

  .claim-link.refute {
    border-color: #fce7f3;
    background: #fef2f8;
    color: #9d174d;
  }

  .claim-link.refute:hover {
    background: #fce7f3;
    border-color: #fbcfe8;
  }

  .claim-id {
    font-family: monospace;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.02em;
  }

  .empty-state {
    margin: 0;
    padding: 0.35rem 0.5rem;
    font-size: 0.78rem;
    color: #cbd5e1;
    font-style: italic;
  }

  .focal-card {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .focal-id {
    font-family: monospace;
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.02em;
  }

  .focal-statement {
    margin: 0;
    font-size: 0.85rem;
    font-weight: 500;
    line-height: 1.45;
    color: #1e293b;
  }

  .focal-conf {
    font-size: 0.75rem;
    font-weight: 600;
  }

  /* ── source-footer chip ─────────────────────────────────────────────── */
  .rail-section.source-footer {
    border-top: 1px solid #e2e8f0;
    background: #f8fafc;
    padding: 0.6rem 0.75rem;
    margin-top: 0.25rem;
  }

  .source-label {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #94a3b8;
    margin-bottom: 0.35rem;
  }

  .source-chip {
    display: inline-flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: 0.3rem 0.5rem;
    border-radius: 4px;
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    text-decoration: none;
    color: #475569;
    transition: all 0.15s;
  }

  .source-chip:hover {
    background: #e2e8f0;
    border-color: #cbd5e1;
    color: #1e293b;
  }

  .source-claim-id {
    font-family: monospace;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    color: #64748b;
  }

  .source-materializes {
    font-size: 0.72rem;
    color: #94a3b8;
  }
</style>

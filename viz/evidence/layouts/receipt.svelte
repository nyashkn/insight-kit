<!-- @insight-kit/viz-evidence layouts/receipt.svelte
     Installed via `kit viz install evidence ./reports` into reports/pages/<folder>/+layout.svelte.
     Editable per-project; updates require re-running install with --force. -->
<script>
</script>

<div class="layout-provenance">
  <slot />
</div>

<style>
  /* Narrow receipt body */
  :global(.layout-provenance #evidence-main-article) {
    font-size: 1.05rem;
    line-height: 1.7;
  }

  /* Print: remove all chrome, expand cards to full width */
  @media print {
    :global(header),
    :global(nav),
    :global([data-sidebar]),
    :global(.print\:hidden) {
      display: none !important;
    }

    :global(#evidence-main-article) {
      margin: 0 !important;
      padding: 0 !important;
      max-width: 100% !important;
      font-size: 11pt !important;
    }

    :global(.dock-card),
    :global(.claim-card),
    :global(.receipt-card) {
      break-inside: avoid;
      border: 1px solid #ccc !important;
      box-shadow: none !important;
      page-break-inside: avoid;
    }

    :global(a) {
      color: inherit !important;
      text-decoration: none !important;
    }

    :global(.dock-breadcrumb) {
      display: block !important;
      margin-bottom: 0.5rem;
      font-size: 9pt;
      color: #666;
    }
  }
</style>

<!-- @insight-kit/viz-evidence layouts/browse.svelte
     Installed via `kit viz install evidence ./reports` into reports/pages/<folder>/+layout.svelte.
     Editable per-project; updates require re-running install with --force. -->
<script>
</script>

<div class="layout-index">
  <slot />
</div>

<style>
  /* Browse header emphasis — makes index pages feel catalog-like */
  :global(.index-browse-header) {
    border-bottom: 2px solid #0d3b6e;
    padding-bottom: 0.75rem;
    margin-bottom: 1.5rem;
  }

  :global(.layout-index #evidence-main-article h1:first-of-type) {
    font-size: 1.5rem;
    font-weight: 700;
    color: #0d3b6e;
    letter-spacing: -0.02em;
  }
</style>

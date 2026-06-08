"""insight_kit.examples — runnable, CI-safe examples for the insight-kit gate.

Subpackage contents
-------------------
shopify_meta_acquire
    End-to-end demo of the research -> skill_use -> claim acquisition chain
    (ik_acquire) applied to the real Meta/Shopify attribution pattern, plus the
    T32 endpoint-coverage critic.  Fixture mode uses captured shopify.dev/
    assistant/search output stored in examples/fixtures/.  Live doc-search
    available via --live flag (urllib, no third-party deps).  Credential-gated
    Meta/Shopify extraction is documented but never called in CI.

Usage
-----
    uv run python -m insight_kit.examples.shopify_meta_acquire          # fixture mode
    uv run python -m insight_kit.examples.shopify_meta_acquire --live   # live doc search
"""

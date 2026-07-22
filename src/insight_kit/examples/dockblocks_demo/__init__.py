"""dockblocks_demo — seeded synthetic testbed for agent-driven insight-kit runs.

A deterministic generator (``datagen``) produces the dockblocks-shaped source
tables — Meta + Google ad spend, orders with a returning-customer pre-window
pool, CRM contacts/deals, email lifecycle events — together with the metrics'
ground truth computed by construction from the same rows. A multi-layer
Hamilton module (``dag``) computes those metrics through the gate, so every
number an agent sees is traceable (item 7 lineage) and checkable against a
known answer.

Why synthetic-with-known-answers: because the generator computes the truth
from the rows it just emitted, a test (or a critic, or an LLM agent under
evaluation) can be graded exactly — including on the deliberately planted
traps (the returning-customer CAC inflation that produced the documented
1059-vs-1770 drift).

Nothing here is committed as data. ``generate(seed=...)`` is bit-stable per
seed; ``DemoData.write_parquet(dir)`` materializes files on demand (scale up
via ``days`` / ``scale`` for large agent-session fixtures).

Usage
-----
    from insight_kit.examples.dockblocks_demo import datagen, dag
    demo = datagen.generate(seed=42)
    demo.write_parquet(some_dir)          # optional: parquet on disk
    # run dag.blended_cac via the gate-backed driver; compare to
    # demo.ground_truth["cac_kes"].
"""

---
name: insight-kit-analyst
description: >-
  Produce a governed, provenance-tracked metric or number with insight-kit —
  the discover → compose → run → seal → verify loop over a Hamilton DAG. Use
  this whenever the task is to compute a metric, KPI, ratio, or analytical
  number that needs to be trustworthy and auditable: authoring a new measure,
  running an analysis through the gate, emitting a claim, or turning a "what is
  X" data question into a defensible answer. Trigger it even when the user does
  not say "insight-kit" — any request to compute a business number that someone
  will act on (CAC, ARPU, payback, conversion, MER, retention, a board figure)
  belongs here rather than an ad-hoc pandas snippet, because the whole point is
  that the number carries its own lineage back to the rows or upstream claims it
  came from. Do NOT use this for auditing or refuting numbers someone else
  produced — that is the insight-kit-critic skill.
---

# insight-kit: the analyst loop

Produce a number that carries its own provenance. Every claim this loop emits is
typed, content-addressed, and traceable back to the rows (or the upstream
claims) it came from — so a reader, or a critic, can verify it without trusting
you. Never hand-carry a number that skips the gate.

The full, harness-agnostic method is in `docs/method/analyst-loop.md`. Read it
if anything below is unclear. The loop is **discover → compose → run → seal →
verify**. `growth_demo` (`src/insight_kit/examples/growth_demo/dag.py`) is the
worked example — mirror its measures when authoring your own.

## 1. Discover — read the semantic layer first

Never rebuild a measure that already exists. Read what you can stand on, at what
grain, statically (no execution, no data):

```python
from insight_kit.integrations.hamilton import catalog, format_catalog
from insight_kit.examples.growth_demo import dag   # ← your module(s)

print(format_catalog(catalog([dag])))
```

`format_catalog` prints the measures (with grain, `claim_id`, base vs derived)
**and** the `@tag` authoring contract, so this one brief tells you both what
exists and how to add one. If a measure at the grain you need already exists,
reference it — don't recompute.

## 2. Compose — only if the measure doesn't exist

Author a Hamilton node tagged as a measure. The tag contract and composition
rule come from `authoring_guide()` (also printed by `format_catalog`). The rule
that matters most:

> **To derive from existing measures, name them as parameters of your node.**
> Hamilton binds each parameter to the upstream node of the same name, and the
> adapter records those measures as `input_claims` (claim→claim provenance)
> automatically. Only compose measures that share the same grain.

A derived (Layer-2) measure — inputs are other measures' *values*, not rows —
lands as `payload` provenance, backed by its `input_claims` edge rather than a
row fingerprint. That is correct, not a gap.

## 3. Run — execute through the gate-backed driver

```python
from insight_kit.platform.gate import RunState, new_run_dir
from insight_kit.integrations.hamilton import build_driver

run_dir = new_run_dir(workspace_dir)
rs = RunState(run_dir=run_dir)
dr = build_driver(rs, run_dir, [dag])
dr.execute(["cac_payback_ratio"], inputs={...})   # upstream measures emit too
```

Hamilton runs topologically, so upstream measures emit before the downstream
metric. Ask for the final metric; its inputs are gated transitively.

## 4. Guard, then seal

Run the two standing guards on the **live** run_state before sealing — they
surface, never block, so read their findings and stop if anything is flagged:

```python
from insight_kit.platform.gate import (
    guard_republished_claims, guard_refuted_inputs, seal_run,
)

republished = guard_republished_claims(workspace_dir, run_state=rs, run_dir=run_dir)
contaminated = guard_refuted_inputs(workspace_dir, run_state=rs, run_dir=run_dir)
# If either returns findings, the number stands on refuted ground — address it,
# do not publish over it.

seal_run(workspace_dir, run_dir, rs)
```

## 5. Verify — mechanical self-check

This step is deterministic (the bundle can't lie), so running it on your own
work is fine — it reports facts, it does not grade quality. Use the bundled
helper:

```bash
uv run python .claude/skills/insight-kit-analyst/scripts/verify_run.py <workspace_dir> <run_id>
```

It prints each claim's provenance source and lineage trace and flags any claim
carrying a standing refutation (exit 1 if so). For a single claim, `lineage_of`
/ `trace_to_rows` give the chain directly.

## What this loop does NOT do

It does not decide whether the number is *right* or *meaningful* — that is a
judgment call, and a producer must not grade its own homework. Hand a sealed run
to the **insight-kit-critic** skill for the adversarial, semantic audit.

# The analyst loop (harness-agnostic)

This is the canonical method an agent follows to produce a governed, provenance-
tracked number with insight-kit. It is written once here, independent of any
harness; each binding (the Claude Code `insight-kit-analyst` skill, the `pi`
extension) is a thin adapter that walks an agent through these same steps.

The loop is **discover → compose → run → seal → verify**. The guiding idea:
never hand-carry a number. Every claim the loop produces is typed, content-
addressed, and carries its own provenance, so a reader (or a critic) can trace
it back to the rows or the upstream claims it came from without trusting the
agent that produced it.

## 1. Discover — read the semantic layer before writing anything

An analyst composing a metric needs to know what it can *stand on*: which
measures already exist, at what grain, and which are base (computed from data)
versus derived (computed from other measures). Read that from the compiled
Hamilton graph — statically, no execution, no data:

```python
from insight_kit.integrations.hamilton import catalog, format_catalog
from insight_kit.examples.growth_demo import dag  # your module(s) here

cat = catalog([dag])
print(format_catalog(cat))   # measures + grain + claim_ids + the authoring contract
```

`format_catalog` prints the authoring contract by default, so the same brief
tells you both *what exists* and *how to add one*. Reuse before you rebuild: if
a measure already exists at the grain you need, reference it — don't recompute.

## 2. Compose — only if the measure you need doesn't exist

Author a Hamilton node tagged as a measure. The tag contract and the
composition rule are in `authoring_guide()` (also appended to `format_catalog`).
The one rule that matters most: **to derive from existing measures, name them
as parameters of your new node.** Hamilton binds each parameter to the upstream
node of the same name, and the adapter records those measures as `input_claims`
(claim→claim provenance) automatically. Only compose measures that share the
same grain.

A derived (Layer-2) measure has no live input rows of its own — its inputs are
the *values* of upstream claims — so it lands as `payload` provenance and its
backing is the `input_claims` edge, not a row fingerprint. That is correct and
expected; the number still traces back through the claims it was computed from.

## 3. Run — execute through the gate-backed driver

```python
from insight_kit.platform.gate import RunState, new_run_dir
from insight_kit.integrations.hamilton import build_driver

run_dir = new_run_dir(workspace_dir)      # a fresh dated run under the workspace
rs = RunState(run_dir=run_dir)
dr = build_driver(rs, run_dir, [dag])
dr.execute(["cac_payback_ratio"], inputs={...})   # upstream measures emit too
```

Hamilton executes topologically, so upstream measures emit their claims before
the downstream metric that derives from them. Ask for the final metric; the
inputs it needs are pulled (and gated) transitively.

## 4. Seal — freeze the run into the workspace

```python
from insight_kit.platform.gate import seal_run
seal_run(workspace_dir, run_dir, rs)
```

Sealing writes the immutable bundle and the manifest row. Once sealed, the run
is a stable target for lineage reads and for a critic to audit.

## 5. Verify — mechanical self-check (the bundle can't lie)

This step is deterministic — it is *not* a judgment call, so it is fine for the
producing agent to run it on its own work. It reads facts back out of the sealed
bundle and runs the two standing guards:

- `lineage_of(run_dir, record_id)` / `trace_to_rows(...)` — confirm each claim's
  provenance chain resolves (a derived claim traces up its `input_claims`; a base
  claim traces to its rows).
- `guard_republished_claims(workspace, ...)` — did this run republish a claim
  that was refuted before, without a superseding verdict?
- `guard_refuted_inputs(workspace, ...)` — does any claim in this run *derive*
  from something refuted (refutation contagion)?

Both guards **surface, never block**: they return findings. If a guard returns
findings, the number is standing on contaminated ground — stop and address it
before presenting the result, don't publish over it.

What this step deliberately does **not** do is decide whether the number is
*right* or *meaningful*. That is a judgment call, and a producer must not grade
its own homework — it belongs to a separate critic (see `critic-council.md`).

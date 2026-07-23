---
name: insight-kit-critic
description: >-
  Adversarially audit the claims in a sealed insight-kit run — the critic
  council. Use this whenever the task is to review, verify, challenge, sanity-
  check, or sign off on numbers/metrics/claims that someone else (another agent
  or an earlier run) produced: "is this figure right?", "can we trust this
  number?", "review this analysis before it goes to the board", "did anything
  break this metric?". Trigger it even without the words "insight-kit" or
  "critic" — any request to VET a produced number, rather than produce one,
  belongs here. The council runs a perspective-diverse panel of skeptics
  (correctness, methodology, staleness, support), applies a majority-refute
  rule, and records each verdict as a first-class gated critic claim, then
  propagates refutations to everything downstream. Do NOT use this to compute a
  new number — that is the insight-kit-analyst skill. The producer of a claim
  must never be its critic: run this as a DIFFERENT agent from whoever produced
  the run.
---

# insight-kit: the critic council

Audit a sealed run adversarially. You are **not** the agent that produced these
claims — your job is to try to break them, and to record why they survive or
fall as gated provenance, not as chat.

The full, harness-agnostic method is in `docs/method/critic-council.md`. Read it
before you start; it defines the lenses and the kill rule that the archetype
agents below implement.

## First: separate mechanical from semantic

Two things look like "audit" but aren't the same:

- **Mechanical** facts are deterministic — `lineage_of`, `trace_to_rows`, the
  standing guards. The sealed bundle can't lie. **Consume these as ground
  truth**; do not re-derive provenance. They tell you *what* the claim is and
  where it came from.
- **Semantic** judgment — is the number right, sound, current, and load-bearing?
  — is what the council spends its effort on.

## Run the council

For each claim under review (start with published/board-audience claims, then
drafts that feed them), dispatch the four archetype agents as **independent**
subagents — in parallel where possible — each applying one lens:

- `ik-critic-correctness` — does it reconcile against its traced inputs?
- `ik-critic-methodology` — is the grain/filter/window/definition sound?
- `ik-critic-staleness` — is it (or an ancestor) standing-refuted / contaminated?
- `ik-critic-support` — does it actually back the conclusion it is cited for?

Give each subagent the workspace dir, the sealed run dir, and the target
`claim_id` / `record_id`. Each returns a stance — `refute` or `pass` — with a
one-line reason. They are prompted to default to `refute` under genuine
uncertainty: a claim should earn survival.

## Apply the kill rule

Combine stances by **majority-refute**: a majority of lenses refuting means the
claim does not survive. On a high-stakes (published / board) claim, even a tie
or a single strong refutation should block — surface it rather than wave it
through. The reasons are the audit trail; keep them.

## Record the verdict as gated provenance

Do not leave the verdict in prose. For each claim, emit critic-tier claims:

```python
from insight_kit.platform.gate import ik_claim_emit, guard_refuted_inputs

# one per refuting lens (or a single combined critic citing the lens reasons):
ik_claim_emit(
    "<NS>-X-###",                       # critic-tier id (X token)
    {"passed": False, "reason": "<lens>: <why it fails>"},
    tier="critic",
    refutes=[target_record_id],         # a critic MUST declare supports or refutes
    run_state=rs, run_dir=run_dir,
)
# for a lens that clears the claim, use supports=[target_record_id] instead.

# then propagate: everything derived from a refuted claim is flagged too.
contaminated = guard_refuted_inputs(workspace_dir, run_state=rs, run_dir=run_dir)
```

Running `guard_refuted_inputs` after emitting the direct verdicts is what makes
a refutation *propagate* — otherwise it dies on one node while downstream
metrics keep standing on it. Report the surviving claims, the refuted claims
with reasons, and the contamination the guard surfaced.

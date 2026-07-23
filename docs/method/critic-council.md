# The critic council (harness-agnostic)

This is the canonical method for adversarially auditing the claims in a sealed
run. It is written once here, independent of any harness; each binding (the
Claude Code `insight-kit-critic` skill and its archetype agents, a future `pi`
extension) is a thin adapter that runs this same council.

## Why a separate critic at all

insight-kit splits "audit" into two things that look alike but aren't:

- **Mechanical audit** is deterministic — `lineage_of`, `trace_to_rows`, the
  gate's typing/provenance enforcement, and the two standing guards. No
  judgment, no LLM. The sealed bundle can't lie, so the *producer* may run this
  on its own work (it's step 5 of the analyst loop).
- **Semantic audit** is judgment — *is this the right metric? is the definition
  sound? is it stale or contradicted? does it actually support the conclusion it
  is cited for?* An agent blessing its own claim here is marking its own
  homework, which is exactly the failure mode the gate's `supports`/`refutes`
  edges and `standing_refutations` exist to prevent.

So the critic is a **different agent from the producer**, and it consumes the
mechanical lineage as ground truth — it does not recompute provenance, it spends
its judgment only on the semantic question.

## The council: diverse lenses, not redundant votes

A single skeptic misses failure modes it isn't looking for. The council is a
**perspective-diverse panel** — each archetype applies a distinct lens, so together
they cover ways a claim can be wrong that any one of them would miss. Run them
independently (in parallel where the harness allows), then combine.

Each archetype reads the sealed run and the claim under review, and returns a
stance: `refute` (with a reason) or `pass` (with a reason). Default to `refute`
when genuinely uncertain — a claim should earn survival, not get it by default.

### Archetypes

1. **Correctness** — does the number reconcile? Recompute the claim from its
   traced inputs (rows for a base claim, `input_claims` values for a derived
   one) and check the identity holds. This lens leans on the mechanical lineage;
   it refutes on an arithmetic/aggregation mismatch.
2. **Methodology** — is the grain, filter set, window, and definition sound for
   what the claim asserts? Refutes on grain mismatch, a filter that silently
   changes the population, a window that doesn't match the statement, or a
   definition that doesn't mean what the prose says.
3. **Staleness / contamination** — is this claim contradicted? Check
   `standing_refutations` for the claim_id, and run `guard_refuted_inputs` to see
   whether it derives from anything refuted. Refutes if the claim or any of its
   `input_claims` ancestors carries a standing refutation.
4. **Support** — does this claim actually back the conclusion it is attached to?
   Follow `cites` / the narrative it supports. Refutes if the claim is decorative
   — cited to lend weight to a conclusion it does not, on its own, establish.

Add or drop lenses to fit the claim; these four are the default panel. The point
is diversity of failure-mode coverage, not the exact count.

## The kill rule

Combine the stances with a **majority-refute** rule: if a majority of the lenses
refute, the claim does not survive. A tie or a single-lens refutation on a
high-stakes (published / board) claim should also block — surface it rather than
wave it through. Record *why*: the surviving/rejecting reasons are the audit
trail.

## Recording the verdict — as first-class gated provenance, not chat

The council's verdict is itself a claim, so it must be gated, not left as prose:

- For each refuting lens, emit a **critic-tier claim** that `refutes` the target
  record (or `supports`, for a lens that clears it). This is the `ik_claim_emit`
  `refutes=[...]` / `supports=[...]` edge — a critic-tier claim must declare at
  least one such target.
- After emitting the direct verdicts, run `guard_refuted_inputs` so a refutation
  **propagates**: everything downstream that derived from the refuted claim is
  flagged too, instead of the refutation dying on one node.

The result is an auditable verdict with the same provenance guarantees as the
claims it judges — a later reader can see who refuted what, why, and what the
refutation contaminated.

---
description: Author a structured claim and add it to the current or most recent run
allowed-tools: Bash, Read, Edit, Write, Glob
argument-hint: <tier> <claim text>
---

Author a structured claim using the `insight-kit:claim-authoring` skill.

Parse `$ARGUMENTS` as: first token = TIER, remaining = CLAIM_TEXT.

Valid tiers: `D` (Descriptive), `R` (Relational), `C` (Causal), `I` (Inferential), `V` (Validated), `X` (Counterfactual).

Steps:

1. **Validate tier**: If TIER is not one of `D R C I V X`, print the valid tiers table and stop:
   ```
   D  Descriptive   — observable fact, no inference
   R  Relational    — pattern/correlation between variables
   C  Causal        — asserts mechanism or cause-effect
   I  Inferential   — conclusion from evidence with stated assumptions
   V  Validated     — claim survived a formal critic/test protocol
   X  Counterfactual — what would have been true under different conditions
   ```

2. **Find the active run**: Check `.insight-kit/runs/` for the most recent run directory. Read its `claims.jsonl` to show the current claim count.

3. **Invoke `insight-kit:claim-authoring`**: Apply the claim-authoring skill to structure the claim. The skill will:
   - Prompt for any missing required fields (value, unit, confidence, evidence citations).
   - Validate that evidence citations are present for tiers C, I, V, X — if missing, ask the user to provide at least one evidence reference.
   - Generate a claim ID in the format `<NAMESPACE>-<TIER>-<NNN>` (e.g., `NMK-D-001`).

4. **Write to run**: Append the structured claim to `.insight-kit/runs/<run_dir>/claims.jsonl` using:
   ```python
   from insight_kit.provenance import Run
   # Or use r.claim(...) if inside an active Run context
   ```

5. **Confirm**: Print the generated claim ID, tier, statement, confidence, and the updated claim count for the run.

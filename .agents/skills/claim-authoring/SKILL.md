---
name: claim-authoring
type: skill
description: Author well-formed insight-kit claims with valid IDs, correct tier, supersedes chain, edges, and evidence references.
roles_using: [analyst, researcher, critic, data-engineer]
metadata:
  last_verified: 2026-04-29
---

## Purpose

Prevent Layer-A and Layer-B validation failures by ensuring every claim emitted via `Run.claim()` satisfies the regex contract, tier rules, edge requirements, and supersedes-chain invariants before execution. An invalid claim aborts the run context with a `ValidationError`; fixing post-hoc is expensive.

## When to invoke

- Before writing any `r.claim(claim_id=..., ...)` call in a new script.
- When adding a critic-tier claim that needs to reference supporting or refuting claims.
- When revising an existing claim (check supersedes chain before setting `supersedes=`).
- When the run exits with `[claim-id-format]`, `[critic-requires-edge]`, `[supersedes-already-deprecated]`, or `[claim-id-globally-unique]` ValidationError.

## Procedure

### 1. Determine the namespace

```bash
cat .insight-kit/config.yaml | grep namespace
# → namespace: NMK
```

Every `claim_id` must begin with that namespace prefix (case-sensitive, 2–5 uppercase letters).

### 2. Choose a tier letter

| Tier letter | Python `ClaimTier` | Use |
|-------------|-------------------|-----|
| D | derived | analyst-computed metric or conclusion |
| R | raw | passthrough from source, no transformation |
| C | critic | verdict that supports or refutes another claim |
| I | initiative | proposed action + impact projection |
| V | viz | chart specification |
| X | counterfactual | predicted behavior under alternate conditions |
| ETL_R | etl_raw | bronze ingest |
| ETL_C | etl_clean | silver transform |
| ETL_M | etl_metric | gold metric |

The full regex: `^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\d{3,}$`

Valid: `NMK-D-001`, `NMK-ETL_M-042`, `NMK-C-100`
Invalid: `nmk-D-001` (lowercase), `NMK-D-01` (only 2 digits), `TOOLONG-D-001` (namespace > 5 chars)

### 3. Check the claims registry for the next sequence number

```bash
grep -r '"claim_id"' .insight-kit/runs/*/claims.jsonl 2>/dev/null | grep '"NMK-D-' | sort | tail -5
```

Pick the next integer >= 3 digits. If the corpus is empty, start at `001`.

### 4. Check the supersedes chain before reusing a claim_id

```bash
python - <<'EOF'
import json, pathlib
target = "NMK-D-001"
already_superseded = set()
for f in pathlib.Path(".insight-kit/runs").rglob("claims.jsonl"):
    for line in f.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("supersedes"):
            already_superseded.add(rec["supersedes"])
print("already superseded:", already_superseded)
print(f"{target} can be superseded:", target not in already_superseded)
EOF
```

If the target is already superseded, you must supersede the most recent successor, not the original.

### 5. Emit the claim

```python
from insight_kit import Run

with Run(topic="revenue-analysis", agent="analyst", model="claude-sonnet-4-6") as r:
    # Base derived claim
    r.claim(
        claim_id="NMK-D-042",
        statement="Gross margin for Q1-2026 was 38.4% vs 35.1% Q1-2025.",
        tier="derived",
        confidence="high",
        caveats=["excludes_fx_adjustments"],
        period="2026-01/2026-03",
    )

    # Critic claim — MUST have supports or refutes
    r.claim(
        claim_id="NMK-C-011",
        statement="The margin improvement is partially explained by one-off cost deferrals.",
        tier="critic",
        confidence="medium",
        refutes=["NMK-D-042"],   # at least one edge required
    )
```

### 6. Add evidence references

```python
rec = r.ingest_external(
    kind="url",
    source_id="https://finance.example.com/q1-2026-report.pdf",
    content=pdf_bytes,
    content_type="application/pdf",
    caveats=["non_audited", "external_source"],
)
r.claim(
    claim_id="NMK-D-043",
    statement="Revenue grew 12% YoY per management report.",
    tier="derived",
    evidence_ref=rec.path,
    input_claims=["NMK-D-042"],
)
```

### 7. Run the test suite to confirm no regressions

```bash
uv run pytest tests/test_validation.py -q
```

## Acceptance criteria

- `uv run pytest tests/test_validation.py -q` exits 0.
- The new `claim_id` matches `^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\d{3,}$` (verify with `python -c "import re; print(re.match(r'^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\d{3,}$', 'NMK-D-042'))"` — must not be `None`).
- No `[claim-id-globally-unique]` error on `Run.__exit__`.
- Critic-tier claims have at least one `supports` or `refutes` entry.

## Common pitfalls

**Wrong namespace prefix (M1 fixture):** Using `DCK-` when config says `NMK` raises `[claim-id-namespace]` immediately. Always read `config.yaml` first.

**Two-digit sequence (M2 fixture):** `NMK-D-01` fails. Minimum is `001`.

**Critic with no edges (M3 fixture):** `tier="critic"` with empty `supports` and `refutes` raises `[critic-requires-edge]`. The critic must point at what it critiques.

**Re-superseding an already-superseded claim (M5 fixture):** If claim Y already `supersedes` X, a new claim Z `supersedes=X` raises `[supersedes-already-deprecated]`. Supersede Y instead.

**Duplicate claim_id in same run:** Emitting `NMK-D-042` twice in one Run raises `[claim-id-duplicate-in-run]` on the second call — fail is immediate, not deferred.

**Cross-run duplicate without supersedes:** Same `claim_id` appearing in two runs with no `supersedes` chain raises `[claim-id-globally-unique]` on `Run.__exit__`.

## Examples

### Valid claim sequence

```python
# Run 1 — original
r.claim(claim_id="NMK-D-001", statement="CAC was $48 in Q4-2025.", tier="derived")

# Run 2 — correction: supersede the original
r.claim(
    claim_id="NMK-D-002",
    statement="CAC was $51 in Q4-2025 after reclassifying field sales spend.",
    tier="derived",
    supersedes="NMK-D-001",
)
```

### ETL-tier claim

```python
r.claim(
    claim_id="NMK-ETL_M-001",
    statement="Bronze orders table reconciled: 12,450 rows, 0 nulls on order_id.",
    tier="etl_metric",
    confidence="high",
    caveats=["snapshot_2026-04-28"],
)
```

## Related skills

- `ingest-flow` — register external inputs before emitting claims that cite them.
- `citation-hygiene` — use `[[CITE: claim_id]]` patterns correctly in statement text.
- `eval-protocol` — verify claim stability across re-runs.
- `layer-a-validation` — understand which Layer-A guards fire and why.

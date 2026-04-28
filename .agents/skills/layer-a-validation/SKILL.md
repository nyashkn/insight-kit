---
name: layer-a-validation
type: skill
description: Understand what the 8 Phase 2 stress-test fixtures (M1-M8) reveal about Layer-A validation gaps, which rules are now enforced, and which gaps remain in Layer B/C.
roles_using: [critic, annotator, operator]
metadata:
  last_verified: 2026-04-29
---

## Purpose

The Phase 2 stress-test fixtures in `dockblocks-ops/phase3/empirical_rules.md` exposed that 4 out of 8 synthetic failure cases slipped past Layer A. This skill documents what each fixture tested, what happened, and the current enforcement status — so the critic and annotator can reason accurately about which guards are live and which are not.

## When to invoke

- Before asserting that a validation rule is enforced at emit time.
- When writing a critic claim that references a specific validation gap.
- When a run exits cleanly but a claim appears to have a structural defect (referential integrity, duplicate ID, stale supersedes).
- When annotating a run for the golden eval set.
- When writing new Layer-A tests.

## Fixture map

| Fixture | What it tested | What happened | Rule now enforced? | Rule ID |
|---------|---------------|---------------|-------------------|---------|
| M1 | `claim_id="DCK-D-099"` — wrong namespace prefix | ValidationError raised immediately | Yes, Layer A | `claim-id-namespace` |
| M2 | `claim_id="dock-001"` — lowercase, missing tier | ValidationError raised immediately | Yes, Layer A | `claim-id-format` |
| M3 | `tier="critic"`, no `supports` or `refutes` | ValidationError raised immediately | Yes, Layer A | `critic-requires-edge` |
| M4 | `ingest_external(caveats=[])` — explicit empty caveats | ValidationError raised immediately | Yes, Layer A | `external-requires-caveats` |
| M5 | Supersede an already-superseded claim (D-090 → D-001 which was already superseded) | No error raised — Layer C gap | Yes, Layer A (shipped v0.1.0a3) | `supersedes-already-deprecated` |
| M6 | `input_claims=["DOCK-D-999"]` — non-existent claim referenced | No error raised at emit — Layer B/C gap | Yes, Layer A (shipped v0.1.0a3) | `input-claims-referential-integrity` |
| M7 | Same `DOCK-D-001` re-emitted in a new run without `supersedes` | No error raised — Layer C gap | Yes, Layer B on `Run.__exit__` | `claim-id-globally-unique` |
| M8 | `metric_id="zzz_count_things"` — not in glossary | No error raised — glossary check missing | Yes, Layer A (shipped v0.1.0a3) | `metric-id-off-glossary` |

## Layer reference

| Layer | When it fires | Rule IDs |
|-------|--------------|----------|
| A | Immediately on `Run.claim()` or `Run.ingest_external()` emit | `claim-id-format`, `claim-id-namespace`, `critic-requires-edge`, `external-requires-caveats`, `supersedes-already-deprecated`, `input-claims-referential-integrity`, `claim-id-duplicate-in-run`, `citation-referential-integrity`, `metric-id-off-glossary` |
| B | On `Run.__exit__` (context manager exit) | `claim-id-globally-unique` |
| C | Offline / batch scan | reserved for future rules |

## Procedure: check a specific rule

### Check that M3 (critic-requires-edge) fires correctly

```python
from insight_kit.validation import check_critic_edges, ValidationError
import pytest

try:
    check_critic_edges("critic", [], [])
    print("BUG: no error raised")
except ValidationError as e:
    assert e.rule_id == "critic-requires-edge"
    print(f"OK: {e.rule_id}")
```

### Reproduce M5 (supersedes-already-deprecated) — now enforced

```bash
uv run pytest tests/test_validation.py::test_supersedes_chain_already_superseded_raises -v
# → PASSED
```

### Reproduce M8 (metric-id-off-glossary) — requires glossary fixture

```bash
uv run pytest tests/test_validation.py::test_metric_id_allowed_unknown_prefix_raises -v
# → PASSED  (needs kit_with_glossary fixture: glossary.yaml with topics: [funnel, zoho])
```

Note: without a `glossary.yaml`, the M8 check is permissive. The absence of a glossary is intentional for projects that have not yet defined their metric taxonomy.

### Run all stress-test-equivalent cases

```bash
uv run pytest tests/test_validation.py -v -q
# All 20+ tests must pass
```

## Known gaps and caveats (as of 2026-04-29)

1. **M8 requires glossary.yaml to enforce:** `metric-id-off-glossary` is only enforced when `.insight-kit/templates/glossary.yaml` exists and has `topics:` entries. A project without a glossary silently allows any metric name.

2. **Layer C rules not implemented:** The friction log flags `supersede-state-check` and `input-claims-referential-integrity` as Layer C candidates (cross-run batch scan). Currently only Layer B (`claim-id-globally-unique`) runs at `Run.__exit__`.

3. **F1 — run-persistence-on-claims-only:** `r.claim()` alone does not persist the run dir. The `skip_empty` guard fires silently. This is a library behavior, not a validation rule, but critics must account for it when reviewing runs that appear to have no associated claims.

4. **F4 — r.note() does not create parent dirs:** Calling `r.note()` before any ingest will fail with `FileNotFoundError` because the run dir has not been created yet. Call `r.ingest()` or `r._ensure_dirs()` first.

## Procedure: annotate a run for eval

```python
# When reviewing a run dir for correctness:
import json
from pathlib import Path

run_dir = Path(".insight-kit/runs/<run_id>")
claims = [json.loads(l) for l in (run_dir / "claims.jsonl").read_text().splitlines() if l.strip()]

for c in claims:
    # Check M3
    if c.get("tier") == "critic":
        if not c.get("supports") and not c.get("refutes"):
            print(f"ANNOTATE: {c['claim_id']} is critic with no edges — should have been blocked by Layer A")

    # Check M8
    if c.get("metric_id") and not any(
        c["metric_id"].startswith(p) for p in ["funnel", "zoho"]   # adjust per glossary
    ):
        print(f"ANNOTATE: {c['claim_id']} metric_id={c['metric_id']} may be off-glossary")
```

## Acceptance criteria

- `uv run pytest tests/test_validation.py -q` exits 0 (all 20+ tests pass).
- Any claim annotated as a critic has non-empty `supports` or `refutes` in `claims.jsonl`.
- No `metric_id` in `claims.jsonl` uses a prefix not in the project glossary (when glossary is configured).
- All 8 M1-M8 failure scenarios can be mapped to a `rule_id` with a known enforcement status.

## Common pitfalls

**Assuming M5-M8 were always enforced:** These were discovered as gaps in Phase 2 and shipped only in v0.1.0a3. Runs produced with earlier versions may contain structurally invalid claims that passed at emit time.

**Missing the permissive-glossary behavior:** If a project has no `glossary.yaml`, M8 (`metric-id-off-glossary`) is silently skipped. The critic should not flag a missing metric check as a bug unless a glossary is confirmed to exist.

**Confusing Layer A (emit-time) with Layer B (exit-time):** `claim-id-globally-unique` fires only on `Run.__exit__`, not during the run. If the run crashed before exit (e.g., exception inside the `with` block), the cross-run duplicate check never ran.

## Related skills

- `claim-authoring` — apply the rules proactively.
- `eval-protocol` — build the golden set using M1-M8 fixture patterns.
- `glossary-management` — configure the glossary to enable M8 enforcement.

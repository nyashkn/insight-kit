---
name: eval-protocol
type: skill
description: Regression testing: golden baselines, run-to-run diffs, claim-stability checks. Invoke after refactors, before promotions, or on value-drift >1%, unstable confidence/tier across runs.
roles_using: [evaluator]
validated_against:
  evidence: "v40"
  duckdb: "1.x"
  python: "3.11+"
metadata:
  last_verified: 2026-04-29
---

## Purpose

Deterministic claim outputs are not guaranteed — LLM agents may produce slightly different claims on re-run. The eval protocol establishes a golden set of approved claims, a diff workflow to detect regressions, and a stability check that flags claim_ids that flip confidence or tier between runs. Without this, a refactoring that subtly changes metric values goes undetected until a stakeholder notices a wrong chart.

## When to invoke

- After a significant refactor of an analyst or ETL script.
- Before promoting a run to "approved" status.
- When a critic reviews a claim chain and needs to verify it matches the prior approved baseline.
- After upgrading the insight-kit library version (regression guard).
- On a scheduled basis (e.g., weekly re-run to detect model drift).

## Golden set structure

```
.insight-kit/eval/
  golden/
    <run_topic>/
      claims.golden.jsonl      # approved claim snapshots (human-reviewed)
      manifest.golden.json     # approved run manifest fields (status, input hashes)
  diffs/
    <timestamp>_<run_topic>.diff.json  # regression diff output
  reports/
    stability_<date>.json      # claim stability across N runs
```

Create the directory:
```bash
mkdir -p .insight-kit/eval/golden .insight-kit/eval/diffs .insight-kit/eval/reports
```

## Procedure

### 1. Produce the golden baseline

After a human-reviewed run, copy its `claims.jsonl` to the golden set:

```bash
TOPIC="revenue-analysis"
LATEST_RUN=$(ls -t .insight-kit/runs/ | grep "_${TOPIC}$" | head -1)

mkdir -p ".insight-kit/eval/golden/${TOPIC}"
cp ".insight-kit/runs/${LATEST_RUN}/claims.jsonl" \
   ".insight-kit/eval/golden/${TOPIC}/claims.golden.jsonl"

echo "Golden baseline set from run: ${LATEST_RUN}"
```

### 2. Run regression diff against a new run

```python
import json
from pathlib import Path
from datetime import datetime

def load_claims(path: Path) -> dict[str, dict]:
    claims = {}
    for line in path.read_text().splitlines():
        rec = json.loads(line)
        claims[rec["claim_id"]] = rec
    return claims

def diff_claims(golden: dict, current: dict) -> list[dict]:
    findings = []

    for cid, gold in golden.items():
        if cid not in current:
            findings.append({"type": "missing", "claim_id": cid,
                             "detail": "present in golden, absent from current run"})
            continue
        curr = current[cid]

        # Check critical fields
        for field in ("tier", "confidence", "statement"):
            if gold.get(field) != curr.get(field):
                findings.append({
                    "type": "changed",
                    "claim_id": cid,
                    "field": field,
                    "golden": gold.get(field),
                    "current": curr.get(field),
                })

        # Numeric value drift
        gold_val = (gold.get("value") or {}).get("n")
        curr_val = (curr.get("value") or {}).get("n")
        if gold_val is not None and curr_val is not None:
            try:
                pct_diff = abs(float(curr_val) - float(gold_val)) / (abs(float(gold_val)) + 1e-9)
                if pct_diff > 0.01:  # >1% drift
                    findings.append({
                        "type": "value_drift",
                        "claim_id": cid,
                        "golden_value": gold_val,
                        "current_value": curr_val,
                        "pct_diff": round(pct_diff, 4),
                    })
            except (TypeError, ValueError):
                pass

    for cid in current:
        if cid not in golden:
            findings.append({"type": "new", "claim_id": cid,
                             "detail": "absent from golden, present in current run"})

    return findings


TOPIC = "revenue-analysis"
LATEST_RUN = sorted(
    (d for d in Path(".insight-kit/runs").iterdir() if d.name.endswith(f"_{TOPIC}")),
    reverse=True
)[0]

golden = load_claims(Path(f".insight-kit/eval/golden/{TOPIC}/claims.golden.jsonl"))
current = load_claims(LATEST_RUN / "claims.jsonl")
findings = diff_claims(golden, current)

ts = datetime.now().strftime("%Y-%m-%d_%H%M")
diff_path = Path(f".insight-kit/eval/diffs/{ts}_{TOPIC}.diff.json")
diff_path.parent.mkdir(parents=True, exist_ok=True)
diff_path.write_text(json.dumps({"run": LATEST_RUN.name, "findings": findings}, indent=2))

print(f"Diff written to {diff_path}")
print(f"Findings: {len(findings)}")
for f in findings:
    print(f"  [{f['type']}] {f['claim_id']}: {f.get('detail', f.get('field', ''))}")
```

### 3. Claim-stability check across N runs

```python
import json
from pathlib import Path
from collections import defaultdict

TOPIC = "revenue-analysis"
runs = sorted(
    (d for d in Path(".insight-kit/runs").iterdir() if d.name.endswith(f"_{TOPIC}")),
    reverse=True
)[:5]  # last 5 runs

# claim_id -> list of (run_name, confidence, tier)
history: dict[str, list] = defaultdict(list)

for run_dir in runs:
    claims_f = run_dir / "claims.jsonl"
    if not claims_f.exists():
        continue
    for line in claims_f.read_text().splitlines():
        rec = json.loads(line)
        history[rec["claim_id"]].append({
            "run": run_dir.name,
            "confidence": rec.get("confidence"),
            "tier": rec.get("tier"),
        })

unstable = []
for cid, entries in history.items():
    confidences = {e["confidence"] for e in entries}
    tiers = {e["tier"] for e in entries}
    if len(confidences) > 1 or len(tiers) > 1:
        unstable.append({"claim_id": cid, "confidences": list(confidences), "tiers": list(tiers)})

print(f"Unstable claims across {len(runs)} runs: {len(unstable)}")
for u in unstable:
    print(f"  {u['claim_id']}: confidence={u['confidences']}, tier={u['tiers']}")
```

### 4. Update the golden set after intentional change

When a claim is intentionally revised (e.g., after a data correction), update the golden:

```bash
# Confirm the new run is correct, then promote it
TOPIC="revenue-analysis"
NEW_RUN=$(ls -t .insight-kit/runs/ | grep "_${TOPIC}$" | head -1)
cp ".insight-kit/runs/${NEW_RUN}/claims.jsonl" \
   ".insight-kit/eval/golden/${TOPIC}/claims.golden.jsonl"
echo "Golden updated from run: ${NEW_RUN}"
```

### 5. Run the full test suite after eval

```bash
uv run pytest tests/ -q
```

## Acceptance criteria

- `diff_claims(golden, current)` returns 0 `"changed"` or `"missing"` findings on a clean re-run.
- `"value_drift"` findings have `pct_diff < 0.01` (within 1%).
- Stability check returns 0 unstable claims across the last 5 runs.
- The diff JSON is written to `.insight-kit/eval/diffs/`.
- `uv run pytest tests/ -q` exits 0.

## Common pitfalls

**Golden set from an unreviewed run:** If the golden was built from a run that had bugs, all regressions will look like improvements. Always have a human review the golden claims before promoting.

**New claim treated as regression:** A `"new"` finding is expected when a run adds new claims. New claims require human review but are not regressions. Only `"missing"` and `"changed"` findings are blockers.

**Value drift threshold too tight:** 0% tolerance will fail on floating-point rounding differences. 1% is a reasonable default for financial metrics; tighten to 0.1% for legally-reported figures.

**Not clearing the golden set after a supersedes chain:** When a claim is superseded, the old `claim_id` will show as `"missing"` in the next run. Update the golden to include only the current chain's tail.

**Stability check on too few runs:** Checking only 2 runs cannot distinguish a one-off fluctuation from a systematic instability. Use at least 5 runs.

## Examples

### Run the regression diff in one command

```bash
uv run python .insight-kit/eval/scripts/diff_run.py --topic revenue-analysis
```

(Create this script from the Step 2 code block above.)

### Check claim stability from the command line

```bash
uv run python - <<'EOF'
import json
from pathlib import Path
from collections import defaultdict

TOPIC = "revenue-analysis"
runs = sorted(
    [d for d in Path(".insight-kit/runs").iterdir() if d.name.endswith(f"_{TOPIC}")],
    reverse=True
)[:5]
history = defaultdict(list)
for run_dir in runs:
    f = run_dir / "claims.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            rec = json.loads(line)
            history[rec["claim_id"]].append(rec.get("confidence"))
for cid, confs in history.items():
    if len(set(confs)) > 1:
        print(f"UNSTABLE: {cid} confidences={set(confs)}")
EOF
```

## Related skills

- `layer-a-validation` — understand which Layer-A guards are active before running eval.
- `glossary-management` — include off-glossary metric scan in the eval suite.
- `claim-authoring` — fix claims that fail the regression diff.

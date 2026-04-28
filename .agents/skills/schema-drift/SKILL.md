---
name: schema-drift
type: skill
description: Detect and reconcile bronze schema changes using ETL_R claims and DuckDB column diffing; emit a reconciliation claim when drift is found.
roles_using: [data-engineer, evaluator]
metadata:
  last_verified: 2026-04-29
---

## Purpose

Bronze (raw ingest) tables silently gain, lose, or rename columns between runs. Undetected drift causes downstream ETL_C and ETL_M transforms to fail with misleading errors, or worse, silently produce wrong results. This skill establishes a repeatable watch-and-reconcile pattern using insight-kit's ETL_R claim tier and DuckDB.

## When to invoke

- Before running any ETL_C or ETL_M transform on a bronze table.
- When a downstream chart or metric returns unexpected nulls or zero-row results.
- After a source system upgrade or API version bump.
- When the data-engineer adds a new bronze source.
- When `pytest -m slow` fails with a column-not-found error.

## Procedure

### 1. Load the bronze table schema into DuckDB

```python
import duckdb
from insight_kit import Run
from pathlib import Path

BRONZE_PATH = Path("data/bronze/orders.parquet")

with Run(topic="schema-watch-orders", agent="data-engineer", kit_start=Path(".")) as r:
    con = duckdb.connect()
    current_cols = {
        row[0]: row[1]
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{BRONZE_PATH}')"
        ).fetchall()
    }
    # current_cols = {"order_id": "VARCHAR", "amount_usd": "DOUBLE", ...}
```

### 2. Load the prior schema from the most recent ETL_R claims.jsonl

```python
import json

RUNS_DIR = Path(".insight-kit/runs")
prior_cols: dict[str, str] = {}

# Find the most recent run with an ETL_R claim for this topic
for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
    claims_f = run_dir / "claims.jsonl"
    if not claims_f.exists():
        continue
    for line in claims_f.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("tier") == "etl_raw" and "orders" in rec.get("claim_id", ""):
            schema_str = rec.get("statement", "")
            # Convention: store columns as JSON in caveats[0] or a dedicated field
            if rec.get("caveats"):
                try:
                    prior_cols = json.loads(rec["caveats"][0])
                except Exception:
                    pass
            break
    if prior_cols:
        break
```

### 3. Diff the schemas

```python
added    = {k: v for k, v in current_cols.items() if k not in prior_cols}
removed  = {k: v for k, v in prior_cols.items()   if k not in current_cols}
type_changed = {
    k: (prior_cols[k], current_cols[k])
    for k in current_cols
    if k in prior_cols and current_cols[k] != prior_cols[k]
}

drift_detected = bool(added or removed or type_changed)
```

### 4. Emit an ETL_R claim with the current schema embedded

```python
import json

schema_json = json.dumps(current_cols)

r.claim(
    claim_id="NMK-ETL_R-012",
    statement=(
        f"Bronze orders schema at {BRONZE_PATH.name}: "
        f"{len(current_cols)} columns. "
        + (f"Drift detected — added: {list(added)}, removed: {list(removed)}, type_changed: {list(type_changed)}." if drift_detected
           else "No drift vs prior run.")
    ),
    tier="etl_raw",
    confidence="high" if not drift_detected else "medium",
    caveats=[schema_json, "bronze_snapshot"],
)
```

### 5. If drift detected, emit a reconciliation claim

```python
if drift_detected:
    r.claim(
        claim_id="NMK-ETL_R-013",
        statement=(
            f"Schema reconciliation required for orders bronze. "
            f"Added: {added}. Removed: {removed}. Type changes: {type_changed}. "
            f"ETL_C transform must be updated before promoting to silver."
        ),
        tier="etl_raw",
        confidence="high",
        supports=["NMK-ETL_R-012"],
        caveats=["reconciliation_pending"],
    )
    # Signal downstream: do NOT proceed to ETL_C until reconciled
    raise RuntimeError(
        f"Schema drift on bronze/orders.parquet — reconcile before ETL_C. "
        f"Added: {list(added)}, Removed: {list(removed)}"
    )
```

### 6. Update the ETL_C transform to handle the new schema

After manually reviewing the drift, update the transform script and emit a superseding claim:

```python
# In the next run after fix:
r.claim(
    claim_id="NMK-ETL_R-014",
    statement="Schema reconciliation complete: orders bronze adapted for added field 'discount_pct'.",
    tier="etl_raw",
    confidence="high",
    supersedes="NMK-ETL_R-013",   # closes out the reconciliation claim
    caveats=["reconciliation_resolved"],
)
```

### 7. Run the preflight check to confirm no downstream breaks

```bash
uv run pytest tests/ -q -m "not slow"
```

## Acceptance criteria

- An ETL_R claim is emitted every bronze ingest run with the current schema embedded in `caveats[0]` as a JSON string.
- Drift (column add/remove/rename) raises a `RuntimeError` before the ETL_C step executes.
- The reconciliation claim (`reconciliation_pending`) is superseded by a `reconciliation_resolved` claim in the fix run.
- `uv run pytest tests/ -q` exits 0 after the fix.

## Common pitfalls

**Silent drift via DOUBLE → FLOAT rename:** DuckDB `DESCRIBE` returns `DOUBLE` for `float64` columns; Polars may infer `Float32`. Normalize type names before comparing: `t.upper().replace("FLOAT", "DOUBLE")`.

**Comparing current schema to wrong prior run:** The sort by `run_id` (timestamp-prefixed) uses lexicographic order — always use `reverse=True` to get the most recent first.

**Removing a column that ETL_C references by name:** A `removed` column that appears in an ETL_C SQL query will fail with `Binder Error: Referenced column not found`. The reconciliation raise prevents this.

**Storing schema only in statement text (not caveats):** Parsing schema back out of free text is fragile. Store `json.dumps(current_cols)` as `caveats[0]` for machine-readable round-trip.

**Not superseding the reconciliation claim:** Leaving `reconciliation_pending` unresolved causes the evaluator's regression scan to flag every subsequent run as drifted.

## Examples

### Minimal column-watch one-liner

```python
# Quick diff for a one-off check without a full Run
import duckdb, json, pathlib

con = duckdb.connect()
cols = dict(con.execute("DESCRIBE SELECT * FROM read_parquet('data/bronze/events.parquet')").fetchall())
print(json.dumps(cols, indent=2))
```

### DuckDB view for monitoring

```sql
-- .insight-kit/duckdb/bronze_schema_watch.sql
CREATE OR REPLACE VIEW bronze_orders_columns AS
SELECT column_name, column_type
FROM (DESCRIBE SELECT * FROM read_parquet('data/bronze/orders.parquet'));
```

```bash
duckdb .insight-kit/duckdb/insights.duckdb -c "SELECT * FROM bronze_orders_columns;"
```

## Related skills

- `ingest-flow` — register bronze parquet before schema-watching.
- `glossary-management` — column names must match glossary metric_id prefixes for ETL_M claims.
- `eval-protocol` — include bronze schema stability as a regression check.

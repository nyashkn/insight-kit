---
name: glossary-management
type: skill
description: Create and maintain the project glossary.yaml that drives metric_id prefix enforcement (M8 Layer-A guard) and off-glossary detection.
roles_using: [operator, data-engineer, evaluator]
validated_against:
  evidence: "v40"
  duckdb: "1.x"
  python: "3.11+"
metadata:
  last_verified: 2026-04-29
---

## Purpose

The project glossary defines the allowed metric_id topic prefixes. Without a `glossary.yaml`, the `metric-id-off-glossary` Layer-A guard is permissive — any `metric_id` passes. With a glossary, `Run.emit_metric(name=...)` raises `[metric-id-off-glossary]` for names that don't start with a known topic prefix. The M8 stress-test fixture (`zzz_count_things`) demonstrated that uncontrolled metric naming creates a metric namespace that no one owns and no one can query coherently.

## When to invoke

- When initializing a new insight-kit project (create the initial glossary).
- When a data-engineer proposes a new metric that has no existing topic prefix.
- When `Run.emit_metric` raises `[metric-id-off-glossary]`.
- When the evaluator finds metrics in `claims.jsonl` that match no glossary topic.
- When a topic becomes obsolete and its metrics should be flagged for retirement.

## Glossary file location

```
.insight-kit/templates/glossary.yaml
```

This path is hardcoded in `check_metric_id_allowed` in `src/insight_kit/validation/__init__.py`. Do not move or rename the file.

## Glossary schema

```yaml
# .insight-kit/templates/glossary.yaml
namespace: NMK   # optional — for documentation only
version: 1
topics:
  - funnel          # matches: funnel_*, funnel_*
  - zoho            # matches: zoho_*
  - revenue         # matches: revenue_*
  - cac             # matches: cac_*
  - ltv             # matches: ltv_*
  - pipeline        # matches: pipeline_*
  - orders          # matches: orders_*
  - churn           # matches: churn_*
```

`topics` is a list of string prefixes. A metric name is valid if it starts with any entry. Matching is case-sensitive and uses `str.startswith`.

## Procedure

### 1. Initialize the glossary

```bash
cat > .insight-kit/templates/glossary.yaml <<'EOF'
namespace: NMK
version: 1
topics:
  - funnel
  - revenue
  - cac
  - ltv
EOF
```

Or with Python (for idempotent creation):

```python
import yaml
from pathlib import Path

glossary_path = Path(".insight-kit/templates/glossary.yaml")
glossary_path.parent.mkdir(parents=True, exist_ok=True)

if not glossary_path.exists():
    glossary_path.write_text(yaml.dump({
        "namespace": "NMK",
        "version": 1,
        "topics": ["funnel", "revenue", "cac", "ltv"],
    }))
    print(f"Created {glossary_path}")
else:
    print(f"Glossary already exists at {glossary_path}")
```

### 2. Add a new topic

Before emitting a new metric family, add the topic prefix:

```python
import yaml
from pathlib import Path

glossary_path = Path(".insight-kit/templates/glossary.yaml")
data = yaml.safe_load(glossary_path.read_text()) or {}
topics = data.get("topics", [])

new_topic = "pipeline"
if new_topic not in topics:
    topics.append(new_topic)
    data["topics"] = sorted(topics)   # keep sorted for readability
    glossary_path.write_text(yaml.dump(data, default_flow_style=False))
    print(f"Added topic: {new_topic}")
else:
    print(f"Topic already exists: {new_topic}")
```

### 3. Verify the guard works

```python
from insight_kit.validation import check_metric_id_allowed
from pathlib import Path

kit_root = Path(".")

# Should pass
check_metric_id_allowed("funnel_volume_b1", kit_root)
print("funnel_volume_b1: OK")

# Should raise
try:
    check_metric_id_allowed("zzz_count_things", kit_root)
    print("BUG: should have raised")
except Exception as e:
    print(f"Correctly blocked: {e}")
```

### 4. Scan existing claims for off-glossary metrics

```python
import json, yaml
from pathlib import Path

glossary_path = Path(".insight-kit/templates/glossary.yaml")
topics = yaml.safe_load(glossary_path.read_text()).get("topics", [])

off_glossary = []
for f in Path(".insight-kit/runs").rglob("claims.jsonl"):
    for line in f.read_text().splitlines():
        rec = json.loads(line)
        metric_id = rec.get("metric_id")
        if metric_id and not any(metric_id.startswith(t) for t in topics):
            off_glossary.append((rec["claim_id"], metric_id, f.parent.name))

for claim_id, metric_id, run in off_glossary:
    print(f"OFF-GLOSSARY: {claim_id} metric_id={metric_id!r} in run {run}")
```

### 5. Retire an obsolete topic

Retiring a topic does not delete existing claims — it marks new metrics with that prefix as off-glossary. Move the topic to a `retired_topics` list:

```yaml
topics:
  - funnel
  - revenue
retired_topics:
  - legacy_dashboard   # retired 2026-04-28; use funnel_* instead
```

Update `check_metric_id_allowed` to check `retired_topics` and emit a warning (not an error) for metrics using retired prefixes. This is a planned enhancement — for now, removing from `topics` is sufficient to block new emissions.

### 6. Cache invalidation after editing glossary.yaml

The `kit_config` function is LRU-cached. In long-running processes, changes to `glossary.yaml` are not picked up until the cache is cleared:

```python
from insight_kit.provenance.root import kit_config, find_kit_root
find_kit_root.cache_clear()
kit_config.cache_clear()
```

In scripts, this is handled automatically at process startup. In tests, use the `monkeypatch.chdir` pattern from `conftest.py` which clears caches via the fixture.

## Acceptance criteria

- `.insight-kit/templates/glossary.yaml` exists and has at least one entry in `topics`.
- `check_metric_id_allowed("zzz_count_things", Path("."))` raises `[metric-id-off-glossary]`.
- `check_metric_id_allowed("funnel_volume", Path("."))` does not raise.
- Off-glossary scan returns 0 results for all runs produced after the glossary was configured.
- `uv run pytest tests/test_validation.py -k "glossary" -q` exits 0.

## Common pitfalls

**M8 fixture: permissive without glossary.yaml:** If `.insight-kit/templates/glossary.yaml` does not exist, ALL metric names pass silently. The evaluator must confirm the glossary file exists before trusting that `metric-id-off-glossary` is enforced.

**Prefix too broad:** A single-letter topic like `r` would match every metric starting with "r" (revenue, refunds, retention, ...). Use at least 3-character prefixes.

**Case sensitivity:** `topics: [Funnel]` does NOT match `funnel_volume`. The `startswith` check is case-sensitive. Use lowercase prefixes consistently.

**Not clearing the cache in tests:** If `glossary.yaml` is created inside a test, `kit_config` may return a cached empty dict. Always call `kit_config.cache_clear()` after writing a new glossary in tests.

**zzz_ prefix anti-pattern (M8):** The M8 fixture used `zzz_count_things` as a synthetic off-glossary example. The `zzz_` prefix was intentionally chosen because no legitimate metric should start with `zzz`. If a real metric starts with `zzz`, rename it.

## Examples

### Minimal glossary for a SaaS analytics project

```yaml
namespace: SAAS
version: 1
topics:
  - arpu
  - churn
  - funnel
  - ltv
  - mrr
  - nrr
  - cac
  - pipeline
  - revenue
```

### Verifying M8 enforcement end-to-end

```bash
uv run pytest tests/test_validation.py::test_metric_id_allowed_unknown_prefix_raises \
              tests/test_validation.py::test_run_emit_metric_off_glossary_raises \
              tests/test_validation.py::test_metric_id_no_glossary_is_permissive \
              -v
# All 3 must PASS
```

## Related skills

- `layer-a-validation` — M8 fixture context and when the guard is enforced.
- `claim-authoring` — emit ETL_M claims with glossary-compliant metric_ids.
- `eval-protocol` — include off-glossary scan in the regression suite.

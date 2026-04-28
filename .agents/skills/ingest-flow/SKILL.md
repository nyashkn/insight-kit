---
name: ingest-flow
type: skill
description: Register external inputs and skill invocations into a Run using ingest_external, ingest_skill, and the convenience wrappers (ingest_search, ingest_url, ingest_api).
roles_using: [data-engineer, researcher, analyst, critic]
validated_against:
  evidence: "v40"
  duckdb: "1.x"
  python: "3.11+"
metadata:
  last_verified: 2026-04-29
---

## Purpose

All evidence entering an analysis must be hashed, snapshotted, and registered before any claim cites it. The `Run.ingest_*` family does this. Skipping ingest means claims have no traceable evidence trail and the run dir will not persist (the empty-run guard fires if only claims are emitted without ingest artifacts — see F1 pitfall below).

## When to invoke

- Any time a script fetches data from a URL, search API, or third-party service.
- When a skill (tavily-cli, perplexity-search, etc.) is called inside a Run.
- When loading a local file that will be cited in a claim (`Run.ingest` for local paths).
- When the critic needs to attach externally sourced counter-evidence.
- Before any `r.claim(evidence_ref=...)` call that needs a valid path.

## Procedure

### 1. Confirm the kit root is initialized

```bash
ls .insight-kit/config.yaml   # must exist
```

If missing: `uv run python -c "from insight_kit.provenance.root import init_kit; from pathlib import Path; init_kit(Path('.'), namespace='NMK')"` — or ask the operator to run `ik init`.

### 2. Open the Run context before any ingest

```python
from insight_kit import Run
from pathlib import Path

with Run(
    topic="competitor-pricing",
    agent="researcher-haiku",
    agent_kind="sub_agent",
    model="claude-haiku-4-5",
    kit_start=Path("."),   # explicit; avoids CWD ambiguity
) as r:
    ...
```

The `kit_start` argument overrides the `INSIGHT_KIT_ROOT` env var and CWD walk. Use it whenever the script may be invoked from a different working directory.

### 3. Ingest external content by kind

**Search result:**
```python
import json

raw = tavily_client.search("competitor pricing 2026")   # dict
rec = r.ingest_search(
    query="competitor pricing 2026",
    tool="tavily",
    results=raw,
    metadata={"depth": "advanced", "max_results": 10},
)
```

**URL body:**
```python
import requests

resp = requests.get("https://example.com/pricing.html", timeout=10)
rec = r.ingest_url(
    url="https://example.com/pricing.html",
    body=resp.text,
    fetcher="requests",
    status=resp.status_code,
    content_type="text/html",
)
```

**API response:**
```python
payload = stripe_client.list_invoices(limit=100)  # dict
rec = r.ingest_api(
    provider="stripe",
    endpoint="/v1/invoices",
    response=payload,
    params={"limit": 100},
    status=200,
)
```

**Skill invocation:**
```python
skill_output = run_skill("perplexity-search", prompt="What is Acme Corp Q1 EBITDA?")
rec = r.ingest_skill(
    skill_name="perplexity-search",
    input={"prompt": "What is Acme Corp Q1 EBITDA?"},
    output=skill_output,
    metadata={"model": "sonar-pro", "latency_ms": 1240},
)
```

**Local file:**
```python
import polars as pl

df = r.ingest(
    path="data/sales_q1.parquet",
    role="raw",
    loader=pl.read_parquet,
)
```

### 4. Reference the InputRecord in a claim

```python
r.claim(
    claim_id="NMK-R-001",
    statement="Competitor pricing page retrieved 2026-04-28 shows plan at $99/mo.",
    tier="raw",
    evidence_ref=rec.path,   # relative path inside run dir
    caveats=rec.default_caveats or [],
)
```

### 5. Verify the run dir was created and inputs snapshotted

```python
import os
print(r.run_dir)   # public attribute — use run_dir, NOT _run_dir (F2)
```

After the context exits:
```bash
ls .insight-kit/runs/$(ls -t .insight-kit/runs/ | head -1)/inputs/
# → external/search/<sha>.txt  external/search/<sha>.meta.json  external/search/<sha>.txt.sha256
```

## Run dir layout

```
.insight-kit/runs/<timestamp>_<agent>_<topic>/
  manifest.json          # full provenance record
  claims.jsonl           # append-only claim stream
  checksums.sha256       # content-addressed integrity manifest
  env.lock               # pip freeze at run time
  script.py              # caller script snapshot (if __main__)
  inputs/
    external/
      search/<sha>.txt + <sha>.txt.sha256 + <sha>.meta.json
      url/<sha>.html + ...
      api/<sha>.json + ...
    skill/<skill_name>/<sha>.output.txt + <sha>.input.json + <sha>.meta.json
  output/
    metrics/<name>.parquet + <name>.parquet.sha + <name>.schema.json
    critique/<name>.parquet
    viz/<name>.json
  logs/
```

## Acceptance criteria

- After `Run.__exit__`, `.insight-kit/runs/<run_id>/manifest.json` exists and has `"status": "completed"`.
- Each `ingest_external` call produces three files under `inputs/external/<kind>/`: `.{ext}`, `.{ext}.sha256`, `.meta.json`.
- `default_caveats` on the returned `InputRecord` is non-empty (defaults to `["external_source", "non_audited"]`).
- `uv run pytest tests/test_ingest_external.py tests/test_ingest_skill.py -q` exits 0.

## Common pitfalls

**F1 — run dir not persisted when only claims emitted:** `r.claim()` alone does not create the run dir; the empty-run guard fires. Fix: call at least one `r.ingest_*` or `r.ingest()` before the context exits, or call `r._ensure_dirs()` explicitly if the run truly has no inputs.

**F2 — accessing `r._run_dir` (private) instead of `r.run_dir` (public):** `r._run_dir` does not exist; use `r.run_dir` inside the context. The attribute is only valid inside the `with` block.

**caveats=[] raises immediately:** Passing an explicit empty list to `ingest_external(caveats=[])` raises `[external-requires-caveats]`. Either omit `caveats` (defaults applied) or pass a non-empty list.

**kit_start vs CWD:** If the script runs from a subdirectory and `kit_start` is omitted, `find_kit_root` walks up from CWD. This can find the wrong `.insight-kit/` on nested projects. Always pass `kit_start=Path(__file__).parent` or set `INSIGHT_KIT_ROOT`.

**Content-type mismatch:** `ingest_url` defaults to `text/html`. For JSON APIs called via `ingest_external` directly (not `ingest_api`), pass `content_type="application/json"` or the stored file will have an `.html` extension.

## Examples

### Researcher fetches and cites a web source

```python
import requests
from insight_kit import Run
from pathlib import Path

with Run(topic="market-size", agent="researcher", kit_start=Path(".")) as r:
    resp = requests.get("https://statista.com/market/123", timeout=15)
    rec = r.ingest_url(
        url="https://statista.com/market/123",
        body=resp.text,
        status=resp.status_code,
    )
    r.claim(
        claim_id="NMK-R-010",
        statement="Global TAM for B2B SaaS reported at $197B for 2025.",
        tier="raw",
        evidence_ref=rec.path,
        caveats=["external_source", "non_audited", "paywall_sample"],
    )
```

### Data-engineer ingests a skill + emits metric

```python
from insight_kit import Run
from pathlib import Path
import polars as pl

with Run(topic="pipeline-bronze", agent="data-engineer", kit_start=Path(".")) as r:
    raw_rows = fetch_from_api()
    rec = r.ingest_api(
        provider="internal-dwh",
        endpoint="/v2/orders/export",
        response=raw_rows,
        status=200,
    )
    df = pl.DataFrame(raw_rows)
    r.emit_metric(df, name="orders_bronze_q1")
    r.claim(
        claim_id="NMK-ETL_R-001",
        statement=f"Bronze orders ingested: {len(df)} rows.",
        tier="etl_raw",
        evidence_ref=rec.path,
    )
```

## Related skills

- `claim-authoring` — emit claims that cite the registered inputs.
- `schema-drift` — monitor bronze schema changes discovered during ingest.
- `citation-hygiene` — use `[[CITE: claim_id]]` inline references correctly.

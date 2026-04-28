---
name: citation-hygiene
type: skill
description: Cite external sources + archive. Invoke on [external-requires-caveats] error, dead-link checks, inline URLs in claims, or user says "archive source", "cite external", "dead link".
roles_using: [researcher, critic]
validated_against:
  evidence: "v40"
  duckdb: "1.x"
  bun: "1.3.x"
metadata:
  last_verified: 2026-04-29
---

## Purpose

A claim is only as trustworthy as its evidence trail. Poorly formatted citations, missing caveats, or ephemeral URLs produce claims that cannot be independently verified and will fail audit. This skill covers the full lifecycle: fetching, archiving, caveat-tagging, and inline `[[CITE:]]` reference patterns.

## When to invoke

- When a researcher adds a new external benchmark, study, or data point to a claim's statement.
- When the critic needs to cite an external source as the basis for a refutation.
- When a claim statement contains a URL inline (URL in statement text is a bug — use `evidence_ref` instead).
- When running a dead-link check before publishing an evidence page.
- When the `[external-requires-caveats]` ValidationError fires.

## Procedure

### 1. Fetch and archive the source inside a Run

Never store a raw URL in a `claim.statement`. Always ingest via `Run.ingest_url` or `Run.ingest_external` to create a content-addressed snapshot.

```python
import requests
from insight_kit import Run
from pathlib import Path

with Run(topic="competitor-pricing-audit", agent="researcher", kit_start=Path(".")) as r:
    resp = requests.get("https://competitor.com/pricing", timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Dead link: {resp.url} returned {resp.status_code}")

    rec = r.ingest_url(
        url="https://competitor.com/pricing",
        body=resp.text,
        fetcher="requests",
        status=resp.status_code,
        content_type="text/html",
    )
    # rec.sha256 is the content fingerprint — proves what was retrieved at this moment
```

### 2. Attach required caveats

External sources must always have at least one caveat. The default `["external_source", "non_audited"]` is applied automatically if `caveats` is omitted. For richer context, be explicit:

```python
rec = r.ingest_url(
    url="https://competitor.com/pricing",
    body=resp.text,
    caveats=["external_source", "non_audited", "pricing_may_change", "retrieved_2026-04-28"],
)
```

**Never pass `caveats=[]` explicitly.** That raises `[external-requires-caveats]` immediately.

Caveat vocabulary (add project-specific ones to glossary):

| Caveat | Meaning |
|--------|---------|
| `external_source` | Not under our control; may change |
| `non_audited` | Not verified by finance or legal |
| `paywall_sample` | Retrieved via trial/demo account |
| `stale_data` | Source known to lag by >30 days |
| `retrieved_<date>` | Explicit snapshot date for volatile pages |
| `methodology_unknown` | Study methodology not disclosed |

### 3. Emit the claim with evidence_ref and caveats

```python
r.claim(
    claim_id="NMK-R-007",
    statement="Competitor Pro plan listed at $149/mo as of 2026-04-28.",
    tier="raw",
    evidence_ref=rec.path,       # content-addressed path inside run dir
    caveats=rec.default_caveats + ["pricing_may_change"],
    confidence="medium",
)
```

### 4. Use [[CITE:]] for inline references in statement text

When one claim's statement text references another claim:

```python
r.claim(
    claim_id="NMK-D-020",
    statement=(
        "Our pricing is 32% below competitor (see [[CITE: NMK-R-007]] for competitor figure). "
        "Net advantage is estimated at $48/seat/year."
    ),
    tier="derived",
    input_claims=["NMK-R-007"],
)
```

The `[[CITE: NMK-R-007]]` pattern is validated by `check_citation_referential_integrity`. If `NMK-R-007` was not emitted earlier in the same run or a prior run's `claims.jsonl`, a `[citation-referential-integrity]` ValidationError fires immediately.

### 5. Dead-link detection (pre-publish check)

Before publishing an evidence page, verify all `evidence_ref` URLs are still reachable:

```python
import json, requests
from pathlib import Path

runs_dir = Path(".insight-kit/runs")
dead = []

for run_dir in runs_dir.iterdir():
    claims_f = run_dir / "claims.jsonl"
    if not claims_f.exists():
        continue
    for line in claims_f.read_text().splitlines():
        rec = json.loads(line)
        for meta_f in (run_dir / "inputs" / "external" / "url").glob("*.meta.json"):
            meta = json.loads(meta_f.read_text())
            url = meta.get("source_id", "")
            if url.startswith("http"):
                try:
                    r = requests.head(url, timeout=8, allow_redirects=True)
                    if r.status_code >= 400:
                        dead.append((url, r.status_code))
                except Exception as e:
                    dead.append((url, str(e)))

for url, status in dead:
    print(f"DEAD: {status}  {url}")
```

### 6. Source archival for volatile pages

For pages known to change (pricing, press releases), archive to Wayback Machine or a local cache before ingesting:

```python
import requests

TARGET_URL = "https://competitor.com/pricing"
wayback_req = requests.get(
    f"https://archive.org/wayback/available?url={TARGET_URL}",
    timeout=10,
)
snapshot_url = wayback_req.json().get("archived_snapshots", {}).get("closest", {}).get("url")
if not snapshot_url:
    # Trigger a new Wayback save
    requests.get(f"https://web.archive.org/save/{TARGET_URL}", timeout=30)
    snapshot_url = TARGET_URL  # fallback to live

rec = r.ingest_url(url=snapshot_url, body=requests.get(snapshot_url).text, ...)
```

## Acceptance criteria

- Every external claim has `evidence_ref` pointing to a file inside the run dir.
- No raw URLs appear in `claim.statement` text (grep check: `grep -r "http" .insight-kit/runs/*/claims.jsonl` should return no `statement` field matches).
- `default_caveats` on every `InputRecord` from `ingest_url`/`ingest_external` is non-empty.
- Dead-link scan returns 0 results before publishing.
- `[[CITE:]]` references in statements all resolve to known `claim_id`s.
- `uv run pytest tests/test_validation.py -k "citation" -q` exits 0.

## Common pitfalls

**URL in statement text:** `statement="See https://example.com for data"` is unfalsifiable — the URL may change. Use `evidence_ref=rec.path` and reference the claim via `[[CITE:]]` instead.

**Forgetting caveats on skill-based external sources:** `ingest_skill` defaults to `["external_source", "non_audited", "skill_invoked"]`. If you override with fewer caveats, the claim appears more confident than it is.

**[[CITE:]] before the cited claim is emitted:** If claim B cites `[[CITE: NMK-D-010]]` but `NMK-D-010` has not been emitted yet in this run and is not in any prior `claims.jsonl`, validation raises `[citation-referential-integrity]`. Emit claims in dependency order.

**Not archiving before a source changes:** A pricing page can update within hours. The content-addressed snapshot in `inputs/external/url/` preserves what was seen, but if no snapshot was taken before the page changed, the evidence trail is incomplete.

## Examples

### Critic citing an external refutation

```python
# Researcher already ingested the source in a prior run (NMK-R-007 in claims.jsonl)
with Run(topic="pricing-critique", agent="critic", kit_start=Path(".")) as r:
    r.claim(
        claim_id="NMK-C-003",
        statement=(
            "The 32% pricing advantage claim ([[CITE: NMK-D-020]]) relies on a "
            "list-price comparison; volume discounts reduce the net advantage to ~8%."
        ),
        tier="critic",
        refutes=["NMK-D-020"],
        input_claims=["NMK-D-020"],
        confidence="medium",
        caveats=["volume_discount_estimate_unverified"],
    )
```

### Quick caveat audit

```bash
python3 - <<'EOF'
import json
from pathlib import Path

for f in Path(".insight-kit/runs").rglob("claims.jsonl"):
    for line in f.read_text().splitlines():
        rec = json.loads(line)
        if rec.get("tier") in ("raw",) and not rec.get("caveats"):
            print(f"MISSING CAVEATS: {rec['claim_id']} in {f.parent.name}")
EOF
```

## Related skills

- `ingest-flow` — create the `InputRecord` that `evidence_ref` points to.
- `claim-authoring` — emit the claim with correct caveat fields.
- `evidence-page-creation` — render the archived evidence on a dedicated Evidence page.

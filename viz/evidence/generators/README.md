# Evidence Generators

Three scripts that build Evidence Markdown pages and refresh DuckDB views from
claim data. Run them from any directory — all paths are resolved from
`--project-root`.

## Prerequisites

- **Node.js 18+** (for `build_provenance.mjs` and `build_indexes.mjs`)
- **Python 3.10+** and `duckdb` package (for `build_evidence_views.py`)
- **`@duckdb/node-api`** installed in the consumer's `reports/node_modules`:
  ```bash
  cd /path/to/consumer/reports
  npm install
  ```

## CLI Flags

All three scripts accept the same flags:

| Flag | Required | Default | Description |
|---|---|---|---|
| `--project-root` | **yes** | — | Absolute path to consumer project root |
| `--reports-dir` | no | `<project-root>/reports` | Evidence project dir |
| `--db` | no | `<project-root>/.insight-kit/duckdb/<basename>.duckdb` | DuckDB file path |
| `--runs-dir` | no | `<project-root>/.insight-kit/runs` | claims.jsonl source dir |

The `.mjs` scripts auto-detect the `.duckdb` filename by scanning
`<project-root>/.insight-kit/duckdb/` for the first `*.duckdb` file.

## Run Order

Always run `build_evidence_views.py` first — it (re)creates the DuckDB views
that the two Node scripts read:

```bash
# 1. Refresh DuckDB views (Python)
python3 viz/evidence/generators/build_evidence_views.py \
  --project-root /path/to/dockblocks-ops-insight-kit

# 2. Generate per-claim provenance receipt pages (Node)
node viz/evidence/generators/build_provenance.mjs \
  --project-root /path/to/dockblocks-ops-insight-kit

# 3. Generate by-tier + reasoning-tree index pages (Node)
node viz/evidence/generators/build_indexes.mjs \
  --project-root /path/to/dockblocks-ops-insight-kit
```

## Invocation Patterns

### Developing from inside insight-kit

```bash
node viz/evidence/generators/build_provenance.mjs \
  --project-root /path/to/dockblocks-ops-insight-kit

node viz/evidence/generators/build_indexes.mjs \
  --project-root /path/to/dockblocks-ops-insight-kit

python3 viz/evidence/generators/build_evidence_views.py \
  --project-root /path/to/dockblocks-ops-insight-kit
```

### From the consumer project (after `kit viz install evidence` wires it up)

```bash
npm run build:views        # python3 ... build_evidence_views.py --project-root .
npm run build:provenance   # node ... build_provenance.mjs --project-root .
npm run build:indexes      # node ... build_indexes.mjs --project-root .
```

### Custom paths

```bash
node viz/evidence/generators/build_provenance.mjs \
  --project-root /path/to/consumer \
  --db /custom/path/to/file.duckdb \
  --reports-dir /custom/reports \
  --runs-dir /custom/runs
```

## Outputs

| Script | Output |
|---|---|
| `build_evidence_views.py` | DuckDB views: `claims_manifest`, `claims_dedup`, `claim_edges`, `annotations`, `runs_manifest` |
| `build_provenance.mjs` | `<reports-dir>/pages/provenance/<claim_id>.md` + `index.md` |
| `build_indexes.mjs` | `<reports-dir>/pages/index/by-tier.md` + `trees.md` |

All scripts are **idempotent** — safe to re-run; existing output files are
overwritten. DuckDB views use `CREATE OR REPLACE`.

## Claim Schema

Claims are read from `<runs-dir>/*/claims.jsonl` (one JSON object per line).
Required fields: `claim_id`, `tier`, `statement`. Optional: `confidence`,
`run_id`, `agent_id`, `status`, `version`, `supports`, `refutes`,
`supersedes`, `input_claims`.

Tier values that generate provenance receipt pages: `initiative`, `causal`.

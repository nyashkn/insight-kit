# insight-kit

> Provenance-first agent insights kit. Every number traceable to its run, script, and inputs.

**Status:** v0.1.0-alpha — early. APIs may change before v1.0.

---

## What it is

`insight-kit` is a lightweight Python package that gives agent-driven analytics projects a shared vocabulary for:

- **Run** — a context manager that wraps a script and writes an immutable, hash-verified run directory.
- **Claim** — a structured, cite-able unit of analyst output (value, unit, confidence, lineage).
- **Manifest** — every input, output, claim, API call, and code SHA captured per run.
- **Adapter** — bridge to Apache Hamilton DAGs for typed compute + auto-lineage.
- **`.insight-kit/`** — project-side state: agents, goals, queue, runs, duckdb catalog.

Designed for agentic workflows where multiple analyst, critic, and writer personas collaborate on a shared claim graph.

## Install

```bash
# path install (during local development)
uv pip install -e /abs/path/to/insight-kit

# git+ssh install (versioned, cross-project)
uv add "insight-kit @ git+ssh://git@github.com/nyashkn/insight-kit@v0.1.0a0"

# with optional extras
uv add "insight-kit[hamilton,polars,evidence]"
```

## Agent setup

insight-kit ships an agent council with role-bound skills. To install:

- **Quick:** see [.agents/SETUP.md](.agents/SETUP.md) — symlink the 12 project-local skills into your Claude Code skills dir.
- **Full bootstrap:** see [docs/agents-bootstrap.md](docs/agents-bootstrap.md) — covers council clone, kit init, CI env vars, and verification.

For non-Claude harnesses (Cursor, etc.), set `CLAUDE_SKILLS_DIR` before running the install loop.

## Plugin install (Claude Code)

For Claude Code users, install insight-kit as a plugin to get namespaced skills (`insight-kit:preflight`, `insight-kit:claim-authoring`, etc.) and 7 slash commands:

```bash
/plugin install /path/to/insight-kit
```

Slash commands: `/insight-kit:bootstrap`, `/insight-kit:run`, `/insight-kit:claim`, `/insight-kit:preflight`, `/insight-kit:promote`, `/insight-kit:roles`, `/insight-kit:goal`

The plugin is additive: existing symlink-based setup (.agents/SETUP.md) still works for non-Claude harnesses.

## Minimal example

```python
from insight_kit.provenance import Run
import polars as pl

with Run(topic="march_reconcile", agent="analyst-meadows-v1") as run:
    tx = run.ingest("data/raw/transactions.csv", loader=pl.read_csv)
    monthly = tx.group_by("month").agg(pl.col("amount").sum())

    run.emit_metric(monthly, name="monthly_revenue")
    run.claim(
        claim_id="MD-D-042",
        statement="March 2026 revenue is KES 1.18M",
        value=1_180_000,
        unit="KES",
        confidence="high",
    )
```

This produces:

```
.insight-kit/runs/2026-04-25_2030_analyst-meadows-v1_march_reconcile/
├── manifest.json          run metadata, claims, inputs/outputs, code SHA
├── claims.jsonl           append-only stream of structured claims
├── env.lock               pip freeze
├── script.py              caller copied verbatim
├── checksums.sha256       all artifact hashes
├── inputs/                symlinks to ingested files
└── output/
    ├── metrics/
    │   ├── monthly_revenue.parquet
    │   └── monthly_revenue.parquet.sha
    └── ...
```

## Project layout (`.insight-kit/`)

Each consumer repo holds its state in `.insight-kit/`:

```
your-project/
└── .insight-kit/
    ├── config.yaml          namespace, runs_dir override, kit version
    ├── agents.yaml          agent registry (id, persona, tools, signet_ref)
    ├── claims_registry.yaml claim ID namespace + validators
    ├── goals/
    │   ├── catalog.yaml
    │   ├── open_queue.jsonl
    │   └── closed.jsonl
    ├── prompts/             persona prompts
    ├── templates/           page yaml templates
    ├── runs/                run artifacts (per-project, isolated)
    └── duckdb/
        └── insights.duckdb  project-local catalog
```

`insight-kit` walks up the directory tree from CWD to find `.insight-kit/` (like `git`).

## Roadmap

| Version | Adds |
|---------|------|
| 0.1.x | `Run`, `Claim`, `Manifest`, explicit `emit_*` methods, `.insight-kit/` resolver, duckdb auto-register |
| 0.2.x | diagnostic vector (precision, evidence density, triangulation, counterfactual_declared, assumption_explicitness, critic_survival), counterfactual tier, learned weights |
| 0.3.x | Hamilton adapter, content-addressed parquet, pipeline critic, ETL primitives |
| 0.4.x | refinement loop, child-Run, outcome-only payout, PageRank authority |
| 0.5.x | signet identity binding, OpenLineage emitter |
| 1.0.0 | API stability after 3 months production + 2 consumer projects |

## Security

Pre-commit gitleaks scan enabled to prevent secret leaks. After cloning, run:

```bash
pre-commit install
```

The gitleaks hook will run automatically on every commit. To scan the current repository manually:

```bash
gitleaks detect --source . --no-banner --redact
```

## License

MIT. See [LICENSE](LICENSE).

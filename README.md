# insight-kit

> A typed provenance gate for AI analyst agents. Every claim an agent makes must cite the research and the data pull it came from, or the gate rejects it.

**Status:** v0.1.7 — alpha. The gate API may change before v1.0.

---

## What it is

`insight-kit` is a typed **provenance gate** for AI analyst agents. Every claim an
agent makes must cite the research and the data pull it came from, or the gate
rejects it. Records enter through one chain — `research → skill_use → claim` —
each schema-validated, hashed into a run directory, and open to inspection by
critics.

**Why use it:**

- **Catch hallucinated analysis before it ships.** The gate refuses to record a
  claim that isn't backed by a `research` + `skill_use` record (the `ik_acquire`
  chain). No source, no claim.
- **Catch the analysis the agent *didn't* do.** The endpoint-coverage critic
  (`check_coverage_from_run`) flags claims where a high-relevance API the docs
  search surfaced was never queried — e.g. concluding on customer mix without
  ever pulling `Customer.numberOfOrders`.
- **Every number is replayable.** Each run writes a hashed record directory
  (per-record JSON + source snapshots, append-only `claims.jsonl` /
  `records.jsonl`) so any figure traces back to the exact research, data pull,
  and fields that produced it.

**Who it's for:** engineers building multi-agent analytics/insight pipelines
(analyst / critic / writer personas over a shared claim graph), typically inside
Claude Code or Cursor harnesses.

The core building blocks:

- **Gate** (`insight_kit.platform.gate`) — typed emit wrappers (`ik_research_emit`,
  `ik_skill_use_emit`, `ik_claim_emit`), the `ik_acquire` chain, and `RunState` /
  `finalizeRun` accumulation.
- **Critics** — cross-checks like `check_coverage_from_run` and
  `check_annual_equals_monthly_sum` that fire on emitted records.
- **Hamilton adapter** (`insight_kit.integrations.hamilton`) — optional bridge to
  Apache Hamilton DAGs for typed compute.
- **`.insight-kit/`** — project-side state: config, agents, goals, runs, duckdb catalog.

## Install

```bash
# path install (during local development)
uv pip install -e /abs/path/to/insight-kit

# git+ssh install (versioned, cross-project)
uv add "insight-kit @ git+ssh://git@github.com/nyashkn/insight-kit@v0.1.0a3"

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

## Quickstart

Run the bundled, CI-safe example (no credentials needed):

```bash
uv run python -m insight_kit.examples.shopify_meta_acquire
```

It emits a `research → skill_use → claim` chain from captured fixtures, then
fires the endpoint-coverage critic — which flags that the run pulled orders via
`bulkOperationRunQuery` but never queried `Customer.numberOfOrders`, so
new-vs-returning composition is unknown:

```
T32 Coverage check: FAILED
  available high-relevance endpoints : 2
  endpoints actually used            : 1
  MISSED high-relevance endpoints    : ['Customer.numberOfOrders']
Critique fired: YES (critique.jsonl written)
```

Minimal hand-written version (every argument below is required or shown for
clarity; `claim_id` must match the gate's `<NS>-<TIER>-<NNN>` pattern):

```python
from pathlib import Path

from insight_kit.platform.gate import ik_acquire, check_coverage_from_run
from insight_kit.platform.gate.runstate import RunState

state = RunState()
result = ik_acquire(
    research_id="RES-001",
    skill_use_id="SKU-001",
    claim_id="ATTR-D-001",
    api_search_result={"query_results": {}, "source": "demo"},  # docs/search snapshot
    api_extraction_result={"orders": [{"id": 1}, {"id": 2}]},    # the data you pulled
    claim_fields={"total_orders": 2},
    research_query="orders pull",
    research_source="example.dev/search",
    skill_use_tool="example-extractor",
    skill_use_source="orders_endpoint",
    claim_tier="draft",
    run_state=state,
    run_dir=Path("./run-001"),
)

# Did the agent skip a high-relevance endpoint the search surfaced?
coverage = check_coverage_from_run(
    Path("./run-001"), result.research_ref.record_id, claim_id=result.claim_id
)
print(coverage.passed, coverage.missed_high_endpoints)  # True []
```

This writes a hashed record directory:

```
run-001/
├── records.jsonl              append-only index of every emitted record
├── claims.jsonl               append-only stream of claim records
└── records/
    └── <content-hash>/
        ├── record.json        the typed, schema-validated record
        └── snapshot.json      the source snapshot it cites (research / skill_use)
```

Call `finalizeRun(state)` to stamp completion and assert manifest completeness.

## Project layout (`.insight-kit/`)

Each consumer repo holds its state in `.insight-kit/`:

```
your-project/
└── .insight-kit/
    ├── config.yaml          namespace, runs_dir override, kit version
    ├── agents.yaml          agent registry (id, persona, tools, identity ref)
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

insight-kit is alpha; the gate API may change before 1.0.

- **Now (0.1.x):** typed record gate, the `ik_acquire` chain, the endpoint-coverage
  critic, the Hamilton adapter, the `ik` CLI, and Evidence viz install.
- **Next:** richer claim diagnostics (evidence density, triangulation, critic
  survival) surfaced as a scorecard; configurable critics.
- **Later:** OpenLineage emitter; pluggable identity backends.
- **1.0.0:** API freeze after sustained production use across ≥2 projects.

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

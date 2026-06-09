# `.pi/` — L3 pi orchestration layer (T18)

This directory is insight-kit's **L3** in the 3-layer pi-harness design. It is a
thin TypeScript adapter that exposes the frozen **L1** Python gate to the
[`pi` coding agent](https://www.npmjs.com/package/@earendil-works/pi-coding-agent).

```
L3  .pi/extensions/insight-kit.ts   pi extension — registers 4 tools, gates hooks
 │  .pi/lib/core.ts                 pure wire logic (uv-run argv, result parsing)
 │  .pi/lib/schema.generated.ts     pydantic-derived tool param schemas (C5)
 ▼  ── uv run subprocess (C4 lang seam) ──
L1  insight_kit.platform.gate.cli   Python CLI bridge over the gate
    insight_kit.platform.gate.emit  the frozen typed-record gate
```

## Tools

The extension registers the four `I.emit` typed wrappers as pi tools:
`ik_claim_emit`, `ik_intervention_emit`, `ik_research_emit`, `ik_skill_use_emit`.

Each tool's `execute` shells out — `uv run python -m insight_kit.platform.gate.cli
emit-<type> --payload <json>` — and returns the content-addressed record, or
throws the gate's reject reason (rule_id + suggestion) so the model can correct.

`INSIGHT_KIT_RUN_DIR` must be set — it is the run directory the gate writes
records into. The `tool_call` hook blocks an emit early when it is unset.

## Schema is single-sourced (C5)

`schema.generated.ts` is **generated** from the pydantic record models — never
hand-edit it. The chain: pydantic `model_json_schema()` → `$defs` inlined →
`insight_kit.platform.gate.cli export-schema` → `recordParamSchemas` → TypeBox
`Type.Unsafe`. Regenerate after any schema change:

```sh
bun run pi:gen-schema     # = bun run scripts/gen-pi-schema.ts
```

## Verify

```sh
bun run pi:typecheck      # tsc -p .pi/tsconfig.json
bun run pi:test           # bun test ./.pi/lib/   (seam logic — no pi runtime)
uv run pytest tests/platform/gate/test_cli.py   # the Python half of the seam
```

Tests live in `.pi/test/` — **never** in `.pi/extensions/`. pi's loader imports
every `.pi/extensions/*.ts` and calls its default export with the real `pi`; a
`.test.ts` placed there would crash the loader. Set `INSIGHT_KIT_DEBUG` to log
the per-session emit tally to stderr.

`@earendil-works/pi-coding-agent` + `typebox` are repo **devDependencies**
(pinned to the installed pi version) so the extension typechecks in-repo. At
runtime pi loads `extensions/*.ts` via jiti against its own install — no build
step. `core.ts` is dependency-free and unit-tested in isolation.

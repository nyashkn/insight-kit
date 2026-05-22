# ck:build — decision log

Running log of e2e build decisions for the insight-kit L1 typed-record gate
(see `SPEC.md`). Append-only; newest at the bottom. Each entry: decision · why.

## 2026-05-21 — Phase 0 (T1-T5)

- **Clean-room gate.** Build `src/insight_kit/gate/` fresh; legacy
  `provenance/run.py` + `provenance/claim.py` deleted only at the T25 cutover
  (C13). Why: stop the old page-D design biasing the rebuild; git history is
  the reference. Kept + reused: `provenance/root.py`, `validation/`, `errors.py`.
- **Storage model.** Content-addressed `records/{id}/record.json` (immutable) +
  derived regenerable `records.jsonl` index (V7, resolves RT2). The jsonl-line
  storage model was rejected.

## 2026-05-22 — Phase 1 (T6-T14, T19, T20)

- **Dispatch.** 3 sub-agents launched with `isolation: worktree`. Isolation did
  NOT hold — agents shared `feat/agents-system-v2` and raced. Recovered green
  because file-ownership was genuinely disjoint and git serialized the commits.
  **Lesson: gate-core builders run SERIAL / inline, never parallel sub-agents.**
- **T10 + T11 finished inline** by the orchestrator (coverage-warning gate;
  selection params + `check_annual_equals_monthly_sum` Layer-C cross-check).
- **Phase 1 complete** — 319 tests green, ruff clean. SPEC §T1-14/19/20 flipped.
- **Evidence SDK DEFERRED.** User reversed the earlier "adopt SDK now" answer.
  T15/T24 build on plain Evidence `.md` + `<ClaimNum>`/`<ClaimChart>` components
  + Altair-emitted Vega-Lite `chart.vl.json`. SPEC `I.evidence` already encodes
  this — no SPEC change. SDK revisited only if per-initiative page-curation
  becomes the real pain.

## 2026-05-22 — Phase 2 + cutover plan (autonomous e2e)

- **T17 constraint.** The eval harness containerizes real `nairomarket`/
  `growth_insights` business data — the image stays LOCAL, never pushed to any
  registry. Harness tests run against a synthetic/golden fixture.
- **Sequencing.** Gate-core tasks T21/T22/T23 (touch `schema.py`/`emit.py`/
  `store.py`) done SERIAL inline. TS-layer tasks T15/T16/T18/T24 are
  language-isolated (TS/Svelte) and may be grouped separately.

## 2026-05-22 — Phase 1 audit (opus, read-only)

Verdict: **clean-with-findings**. All 11 §V invariants genuinely enforced; no
cross-task regression from the racing dispatch; gate-step ordering correct
(every reject before any disk write — V2 holds).

Fixed now:
- **HIGH** — `test_env_capture.py::TestEnvModuleImportPurity` scanned the global
  in-process `sys.modules`, false-positiving whenever an earlier test imported
  hamilton; kept the full-repo suite red. Removed — purity is correctly covered
  by `test_purity.py` (AST scan + subprocess-isolated probe).
- **LOW** — `ik_run_check` had no subprocess timeout; a hung validator blocked
  the gate. Added `timeout=30.0s` + `TimeoutExpired` → failed `CheckResult`.

## 2026-05-22 — T21 intervention reconciliation (V19)

- **Gate step 5a** — `_check_intervention_reconciliation` rejects a published
  intervention with no `realized` (or status ∉ {applied,partial,failed}). Hard
  reject, not a downgrade — contrast T7.
- **Runs BEFORE the T7 tier gate**, on the caller's *declared* tier: the reject
  is on the intent to publish. (Coverage gate T10 runs *after* the downgrade —
  asymmetry is intentional and commented in `emit.py`.)
- **Promotion lock = free.** Records are immutable; promoting a pending draft
  means a fresh emit at `published`, which hits the same gate. No extra machinery.
- `partial`/`failed` are NOT rejects — V19 invariant is *reconciliation
  captured*, not *action succeeded*.
- 2 pre-existing `test_tier_gate.py` tests emitted a published intervention with
  no `realized` (legal pre-T21) — updated to pass `realized={status:applied}` so
  they still isolate the T7 downgrade. Test-only fix, no spec/code backprop.
- 327 gate tests green, ruff clean.

## 2026-05-22 — Phase 1 audit deferred follow-ups
- **MED** — `tests/test_hamilton.py::test_hamilton_failure_raises_exception`
  fails: legacy `provenance/run.py` `_gen_claim_id` yields `C-boom` (off-regex).
  Pre-existing, not a Phase-1 regression. Resolves at T25 when `provenance/run.py`
  + `test_hamilton.py` are deleted/rewritten. Until then full-repo suite = 1 fail.
- **LOW** — `_check_raw_parquet_path` does not catch a raw path passed as a plain
  `str` (off the wrapper's `bytes|dict|None` contract). Tighten at T21/T25.
- **LOW** — `RecordRef._claim_id` is injected via `object.__setattr__`; promote
  to a declared field during the T25 refactor.
- **LOW** — `check_annual_equals_monthly_sum` (V15 Layer-C) is not yet wired into
  any `ik_run_check` driver — latent. Wire at T16/T17.

## 2026-05-22 — Phase 2 decisions (Evidence / Harbor / credentials)

- **Evidence DEFERRED out of this loop.** T15 (claim read-end) + T24
  (intervention page) drop from the loop. Rationale (user): Evidence is the
  end-user consumption surface — if it is built, it should be built properly
  with the Evidence.dev SDK, not the plain `.md` + Altair cut. The cut version
  would only be redone. This loop closes at gate-core (T21-T23) + T16 audit +
  T17 harness + T18 pi extension + T25 cutover. Evidence becomes its own
  follow-up loop, SDK-based. §T15/§T24 stay `.` (not done, deferred).
- **Harbor DEFERRED.** T17's eval harness is built now as a plain verifier
  (containerized fixture + golden-diff classifier living in the claim gate).
  Harbor (Apache-2.0 Python pkg) is the right long-term shell — its
  task/adapter/RewardKit structure maps cleanly and enables the AutoAgent
  meta-loop — but it is early-stage (v0.7.1, 103 open issues); binding to it
  during the foundation phase is the risk. Wrap the stable verifier in a Harbor
  task (~1 day) when wiring the first AutoAgent run. "Freeze the gate" holds iff
  gate imports stay in Harbor's `tests/checks.py`, never in the agent's
  editable `agent.py`.
- **Credentials → Infisical.** App/harness-runtime secrets go in an Infisical
  project (`naimarket`), accessed via per-consumer Machine Identities
  (`mi-eval-harness`, later `mi-autoagent` — least privilege). The identity's
  bootstrap client credential is injected at container-launch via env, never
  baked into the LOCAL T17 image, never committed. `growth_insights/.env` keys
  migrate into Infisical and the on-disk `.env` is deleted. The frozen L1 gate
  never sees a credential. (Signet Secrets remains for agent-operational use —
  different layer.)

## 2026-05-22 — T22 research/skill_use knowledge records (V20, I.cites)

- **Snapshot persistence.** `ik_research_emit`/`ik_skill_use_emit` now require a
  `snapshot` dict (the captured-results payload). emit step 4b persists it as
  `records/{id}/snapshot.json` and folds its sha256 into `record_fingerprint`
  via the new `snapshot_fingerprint` field — the snapshot is content-addressed
  and tamper-evident. Empty/missing snapshot → hard reject
  (`knowledge-snapshot-missing`).
- **`snapshot_ref` demoted** from required load-bearing field to an optional
  human origin label. The real provenance is the hashed `snapshot`. The old
  `snapshot_ref`-points-to-a-string design was the RT10 hole.
- **cites-edge integrity** (`_check_cites_edges`, Layer-A guard) — every id in a
  record's `cites` must (a) resolve to an existing record and (b) be a
  research/skill_use record. A claim/intervention cited via `cites` → reject
  (`cites-wrong-type`); claim→claim corrections use `supersedes`.
- **Scope boundary (logged).** The gate enforces *integrity* of declared cites.
  It cannot infer that a claim *depended* on external knowledge — that honesty
  is a generator-side obligation ("freeze the gate, not the generator"). V20's
  "bare external assertion → reject" is therefore enforced as edge-integrity +
  hashed-snapshot provenance; a harder "must-cite" rule would need a §V backprop
  with an explicit caller-declared signal.
- ~16 existing research/skill_use emit call sites across 6 test files updated to
  pass `snapshot=` — mechanical, no behaviour change. `test_schema.py` unchanged
  (`snapshot_ref` still required, `snapshot_fingerprint` optional).
- T22 tests: `test_knowledge_records.py` (21 tests). Full gate suite green,
  ruff clean.

## 2026-05-22 — T23 post-hoc utility verdict (V21, I.events)

- New module `gate/verdict.py` — `ik_utility_verdict(record_id, verdict, ...)`
  appends a `useful`/`not_useful` event to
  `records/{id}/events/utility_verdict.jsonl`. `UtilityVerdict` StrEnum.
- **Event-only, by construction.** The function never calls `write_record` —
  it only `append_event`s. record.json cannot be mutated by it (V21). Verdict
  is revisable: each call appends a line; current verdict = last line.
- Placed in its own module (not `runstate.py`) — unlike the T12 critique gate
  it is post-hoc and carries no `RunState` coupling; mirrors `feature.py` as a
  small typed-API module.
- Rejections: invalid verdict value, missing target, or target not a
  research/skill_use record (`utility-verdict-{invalid,target-missing,wrong-type}`).
- T23 tests: `test_utility_verdict.py` (13 tests). Full gate suite green,
  ruff clean. **Gate-core (T21-T23) complete — every §V invariant enforced.**

## 2026-05-22 — T16 Layer-D render audit, modular (V8, V9, V12, I.audit)

- **User steer: make the render audit modular** — it must work across render
  backends (Evidence, Altair/Vega-Lite, later Superset / Lightdash / PowerBI /
  Malloy). This dissolved the earlier defer-or-build fork.
- **Split: backend-agnostic core + per-backend adapters.**
  - `gate/audit.py` — the core. `RenderedToken` normalized contract +
    `RenderAdapter` protocol; `audit_l5` (V9 token→claim join, orphan/unknown/
    mismatch), `audit_l6` (V8 prose lint — bare numeric literal in narrative.md
    prose; code blocks, inline code, `<ClaimNum>`/`<ClaimChart>` tags and list
    ordinals exempt); `run_render_audit` → `AuditReport`. Zero format-guessing
    risk — the core operates on the normalized contract, never raw HTML.
  - `gate/render_adapters.py` — `VegaLiteAdapter` for Altair `chart.vl.json`
    (a pinned public spec). Claim binding via the Vega-Lite `usermeta` slot:
    `usermeta.insight_kit.{claim_id, field_map}`. Unmapped numeric field →
    orphan token.
- **Adapters deferred:** `EvidenceAdapter` ships with the Evidence SDK loop;
  Superset/Lightdash/PowerBI/Malloy when adopted. The core never changes when a
  backend is added — only a new adapter module.
- **Scope note.** RT1 (downstream loop) is closed on the *enforcement* side;
  its other half (the actual `<ClaimNum>` Evidence render, T15) stays in the
  Evidence loop. L6's "field ref" contract = `<ClaimNum>`/`<ClaimChart>`.
- T16 tests: `test_render_audit.py` (34 tests). Full gate suite green, ruff clean.

## 2026-05-22 — T17 eval harness (V11, C10, C11)

- **Harbor deferred** (decided earlier) → T17 built as a plain Python verifier.
  `src/insight_kit/harness.py` — pure, no container, no credentials.
- **Semantic field-diff** `diff_run_against_golden` + `classify_field`: each
  golden field vs the run's claim → `match` / `regression` / `legitimate` /
  `coverage_drop`. Classification reads gate metadata already on the claim —
  thin `coverage` → coverage_drop; `supersedes` edge → legitimate; silent
  disagreement → regression. Only regressions fail the harness.
- **Negative fixtures** (C11/RT6): buggy runs (wrong values, no supersedes, no
  thin coverage) are classified `regression` — `test_harness.py` asserts the
  harness *catches* them, never certifies them.
- **V11 replay determinism** `check_replay_determinism` — value-equality under
  C10 tolerance, NOT fingerprint identity; `charts_byte_identical` for the
  published-tier chart check.
- **`eval/README.md`** — the LOCAL-only containerization recipe: real-data image
  never pushed, credentials pulled at runtime from Infisical (`naimarket`
  project, `mi-eval-harness` identity, `infisical run` env injection). Harness
  logic is what T17 ships + tests; the real-data container is the user's
  local step once the Infisical project exists.
- T17 tests: `test_harness.py` (20 tests). Harness suite green, ruff clean.

## 2026-05-22 — T18 L3 pi extension (C4, C5, I.emit, V1, V2, V5)

- **pi confirmed** = `@earendil-works/pi-coding-agent` v0.75.4. Extension API
  read from the installed package `.d.ts`: `.pi/extensions/*.ts` jiti-loaded,
  `export default fn(pi: ExtensionAPI)`, `pi.registerTool({parameters: TSchema,
  execute})`, `pi.on("tool_call"|"tool_result")`, `pi.exec(cmd,args,opts)` —
  **no stdin** (so the payload rides on argv).
- **Built the orchestrator-agnostic core; the pi glue is thin over it.**
  - `src/insight_kit/gate/cli.py` — the C4 lang seam. `python -m
    insight_kit.gate.cli emit-{claim,intervention,research,skill-use}` reads a
    JSON payload (`--payload` / stdin) → runs the matching `ik_*_emit` wrapper →
    prints one JSON line `{ok:true,record}` / `{ok:false,error}`; exit 0/1/2.
    `export-schema` prints the four tool param schemas. RunState is rehydrated
    from `records.jsonl` so the claim_id-unique-in-run guard spans the whole
    pi session, not one subprocess. V5 — imports no hamilton, no pi.
  - `scripts/gen-pi-schema.ts` → `.pi/lib/schema.generated.ts`. C5 chain:
    pydantic `model_json_schema()` → `$defs` inlined ref-free → `export-schema`
    → `recordParamSchemas` → TypeBox `Type.Unsafe`. Generated, never hand-kept.
  - `.pi/lib/core.ts` — dependency-free wire logic (argv build, result parse).
  - `.pi/extensions/insight-kit.ts` — registers the 4 `ik_*_emit` tools; the
    `tool_call` hook blocks an emit when `INSIGHT_KIT_RUN_DIR` is unset; the
    `tool_result` hook tallies emits (stderr, behind `INSIGHT_KIT_DEBUG`).
- **pi + typebox added as pinned repo devDependencies** (0.75.4) so the
  extension typechecks in-repo; at runtime pi loads it via jiti against its own
  install. `.pi/tsconfig.json` + `pi:gen-schema`/`pi:typecheck`/`pi:test` scripts.
- **Testing — researched, not assumed.** An opus agent dug the installed pi
  `docs/`+`examples/` and six pi-based repos in `/tmp/repos` (Fusion, pi-mono,
  pi-subagents, pi-autoresearch, autoagent). Verdict: pi ships no mock model, so
  the SDK route needs a real model; the mature pattern (pi-subagents
  `test/support/mock-pi.ts`) is a **fake `ExtensionAPI`** that captures
  `registerTool`/`on` and drives `execute`/hooks directly. Findings in
  `docs/hamilton-synthesis/pi-extension-testing.md`.
  - `.pi/test/fake-extension-api.ts` + `insight-kit.extension.test.ts` — 26
    tests: tool registration, TypeBox `Value.Check` param accept/reject, the
    `tool_call` block hook, `pi.exec` argv/timeout/signal shape, `tool_result`
    tally, and 3 real-`uv run` end-to-end cases (emit + gate-reject).
- **Decision: thin pi glue ships now** (not deferred) — the user asked for a
  real end-to-end pi run, and the extension is small over a frozen CLI seam.
- **Seam risks logged** (pi-extension-testing.md §d): payload-on-argv vs
  `ARG_MAX`; `parseGateResult` takes the last stdout line so the gate CLI must
  keep all logging on stderr; a `uv` timeout collapses to a generic
  "no output" error. None block T18; noted for the seam contract.
- Verification: `tests/gate/test_cli.py` 20 pytest green; `.pi` 38 bun tests
  green; `tsc -p .pi/tsconfig.json` exit 0. Pre-existing legacy failure
  `test_hamilton.py::test_hamilton_failure_raises_exception` (legacy
  `Run.claim` path) is untouched by T18 — T25 rewrites that test at cutover.

## 2026-05-22 — T25 cutover: rewire callers onto the gate, delete legacy provenance (C8, C13, V1)

- **Goal**: retire the legacy page-D provenance model (`Run` + `Claim`,
  jsonl-line storage, V7/RT2-rejected) and rewire every caller onto the frozen
  L1 gate. The gate (`src/insight_kit/gate/`, T1-T24) was not touched.
- **Deleted (C13)** — referenceable via git history only:
  - `src/insight_kit/provenance/run.py` (legacy `Run` context manager).
  - `src/insight_kit/provenance/claim.py` (legacy `Claim` dataclass).
- **Kept + reused (C13)**: `provenance/root.py` (kit-root discovery —
  `find_kit_root`, `init_kit`, `kit_config`, `bootstrap_*`, and the standalone
  `check_kit_version_drift` the legacy `Run.__init__` drift guard moved into),
  `validation/`, `errors.py`, `config/`.
- **Source rewired**:
  - `hamilton/adapter.py` — `InsightKitHook` now holds a `RunState` + `run_dir`
    and emits `claim` records via `ik_claim_emit` (was `Run.claim` /
    `Run.emit_metric`). `__init__(run_state, run_dir)` (was `__init__(run)`);
    `build_driver(run_state, run_dir, modules)`. A `@claim_tier` node and a node
    failure both produce a gate `claim`; the node failure still re-raises so the
    Hamilton DAG surfaces the error. The legacy `metric`/`critique`/`viz` emit
    tags have no gate record-type equivalent (gate is `claim|intervention|
    research|skill_use`) and were dropped — see "needs a decision" below. Local
    `_slug` copy retained (legacy module deleted). C1/V5 intact: gate imports no
    `hamilton`; the adapter imports the gate.
  - `insight_kit/__init__.py` — dropped `Run`/`Claim`/`ClaimTier`/`Confidence`
    exports; now lazily re-exports the gate surface (`ik_claim_emit`,
    `ik_intervention_emit`, `ik_research_emit`, `ik_skill_use_emit`, `RunState`,
    `finalizeRun`) + kept `find_kit_root`/`kit_config`.
  - `provenance/__init__.py` — no longer exports the deleted `Run`/`Claim`; now
    exports only the kept `root.py` surface.
  - `hamilton/__init__.py`, `validation/__init__.py` — docstrings + the
    `TYPE_CHECKING` `Run` import updated off the legacy model.
  - `cli/__main__.py` + `agents/` — inspected: neither imported
    `provenance.run`/`provenance.claim` or `Run`/`Claim`. The `ik` CLI uses only
    kept `root.py` + `validation`. No rewire needed.
- **Tests deleted** (pure legacy-storage coverage, no gate equivalent):
  `test_run.py`, `test_claim.py`, `test_run_backcompat.py`, `test_e2e.py`,
  `test_smoke.py`, `test_cli.py`, `test_ingest_convenience.py`,
  `test_ingest_external.py`, `test_ingest_skill.py` (9 files).
- **Tests rewritten** (behaviour still matters):
  - `test_hamilton.py` — exercises the gate-backed `InsightKitHook`: claim
    records land via the gate, the failure path still raises, `finalize()`
    seals the `RunState`.
  - `test_validation.py` — dropped the legacy `Run`-integration tests; all
    direct `check_*` guard tests kept (the `validation/` module is unchanged);
    `input_claims`/`ValidationError`-attr tests converted to direct calls.
  - `test_root.py` — the 3 `Run(kit_start=...)` U-18 tests rewritten to call
    `find_kit_root(start)` directly. The legacy-only `INSIGHT_KIT_ROOT` env var
    (a `Run` feature, not in `root.py`) is dropped.
  - `test_bootstrap_secrets.py` — the 4 kit_version-drift tests rewritten to
    call the kept `check_kit_version_drift()` (the guard moved from the deleted
    `Run.__init__` to `root.py`).
  - `tests/gate/test_input_provenance.py` — minimal: the `_make_hook()` helper
    updated to the new `InsightKitHook(RunState, run_dir)` signature. The T25
    cutover *necessarily* changes that signature (the `Run` type is gone), so a
    gate test that constructs the adapter with the legacy single-arg form had
    to follow. Only the 2-line construction helper changed; no gate coverage
    altered. Flagged below.
- **Verification**: `uv run pytest` → **542 passed, 0 failed, 1 deselected**
  (baseline pre-cutover was 629 passed / 1 failed — the drop is the 9 deleted
  legacy-storage test files; the 1 pre-existing failure
  `test_hamilton.py::test_hamilton_failure_raises_exception` is now green
  against the gate-backed adapter). `uv run ruff check src tests` → clean.
- **Needs a /ck:spec decision** (not edited here — §V/§B are `/ck:spec`-owned):
  the gate has four record types (`claim|intervention|research|skill_use`); the
  legacy Hamilton adapter also emitted `metric`/`critique`/`viz` via `@tag(emit=
  ...)`. The cutover dropped those tag paths — mapping them to `claim` records
  would invent semantics. If Hamilton nodes are still expected to emit non-claim
  artifacts, that is an unresolved spec gap for §I/§T to address.

### T25 follow-up fixes — 2026-05-22

Opus review of commit `df671b2` found four issues; all fixed in this session:

- **Fix 1 (HIGH) adapter tier bug** — `adapter.py:_emit_claim` was passing the
  Hamilton tier inside the `fields` dict as `"claim_tier"` instead of as the
  `tier=` keyword argument to `ik_claim_emit`. Every adapter-emitted claim
  silently landed at `tier="draft"`. Fixed by routing the `tier=` keyword
  correctly. Added `_to_gate_tier()` to map Hamilton-internal tiers (`derived`,
  `critic`, etc.) to valid gate `ClaimTier` values (`draft`|`published`); the
  Hamilton tier is preserved in `fields["claim_tier"]` for traceability.

- **Fix 2 (HIGH) test_hamilton.py tier assertions** — the gate-backed claim-emit
  tests never asserted `rec["tier"]` or `rec["fields"]["claim_tier"]`, so Fix 1
  was invisible to the test suite. Added assertions proving the correct gate tier
  and that the Hamilton tier is carried in fields.

- **Fix 3 (MED) ik CLI test coverage recovered** — `tests/test_cli.py` and
  `tests/test_e2e.py` were deleted in the T25 cutover, removing all coverage of
  the live `ik` CLI entry point. New `tests/test_ik_cli.py` covers `ik init`,
  `ik info`, `ik info` (no kit), and `ik validate` (clean / duplicate / supersedes
  chain / no-kit). No legacy `Run`/`Claim` model used.

- **Fix 4 (LOW) dead validation rule removed** — `check_external_caveats()` in
  `validation/__init__.py` referenced the deleted `ingest_external()` function.
  No live caller in `src/`. Function and its 4 test cases removed.

- **Verification**: `uv run pytest` → **546 passed, 1 deselected, 0 failed**.
  `uv run ruff check src tests` → clean.

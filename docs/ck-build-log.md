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

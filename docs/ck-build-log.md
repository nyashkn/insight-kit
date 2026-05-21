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

Deferred follow-ups (logged, non-blocking):
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

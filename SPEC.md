# SPEC — insight-kit · L1 typed-record gate

caveman spec. ck-governed. `/ck:spec` sole mutator. task status: `.` todo · `~` wip · `x` done.
scope = Layer 1 of the 3-layer pi-harness redesign (docs/hamilton-synthesis/pi-harness-redesign.html).
§R folds the 2026-05-21 opus red-team of the 3-layer design.

## §G — goal

L1 typed-record gate: sole typed entry for analytical RECORDS. validate → content-address → emit immutable.
record = one of four types — `claim | intervention | research | skill_use` — discriminated by a `record_type` field.
one gate, one provenance store, one immutable-record contract. runtime-agnostic — zero Hamilton dep, zero pi dep.
the layer Evidence, critic, and replay all trust. gate must close the loop at BOTH ends — emission AND
render-audit — else hallucinated numbers still ship. `claim` asserts a value; `intervention` acts on the
outside world; `research` + `skill_use` acquire knowledge that feeds `claim`/`intervention` via `cites` edges.

## §C — constraints

- C1 — runtime-agnostic. L1 module imports neither `hamilton` nor `@earendil-works/pi-coding-agent`. pure lib.
- C2 — deterministic. gate = pure fn of input. same input → same `record_fingerprint`, every run.
- C3 — record json immutable post-emit. correction = new record, never mutate. applies to all four types.
- C4 — lang seam. L1 gate = Python (insight-kit is a python lib, `src/insight_kit/`). L3 pi extension = TS, calls L1 via `uv run` subprocess — audit-engine `run_check` pattern.
- C5 — schema single-source. RESOLVED: pydantic = sole authored source. record schemas defined once as pydantic models (`RecordSchema` discriminated union); Python validates direct; TS pi-tool param derived chain: `.model_json_schema()` → JSON Schema → TypeBox `parameters` (pi `registerTool` wants a TypeBox schema, not raw JSON Schema — the JSON-Schema→TypeBox conversion is a T18 build step). no hand-kept twin.
- C6 — absorb page D fully. claim fields = dict `{name: (value, fmt_hint)}`. `<ClaimNum>`/`<ClaimChart>` = read-end. L5 post-render diff + L6 prose lint = first-class gate stages (V12), not Evidence trivia.
- C7 — audit mixed-by-tier. published = canonical value+spec replay (C10). draft = gate-decision + reasoning trace. applies to `claim` + `intervention` (both tiered); `research`/`skill_use` are untiered knowledge records.
- C8 — Hamilton lib untouched. the `InsightKitHook` adapter (`src/insight_kit/hamilton/adapter.py`) is insight-kit's own code — rewired at cutover (T25) to emit via the gate; the old `Run.claim` path it calls is deleted (C13). L1 gate module imports no `hamilton`.
- C9 — on-disk contract preserved. Evidence.dev consumes the run directory tree (current-state.html contract). L1 must not break it.
- C10 — replay contract is NOT bit-equality of process. value replay = re-derived field value matches `data_snapshot.parquet` under explicit decimal tolerance + canonical rounding. chart replay = `chart.vl.json` byte-identical (spec equality). PNG = vision-critic input only, never an audit artifact. [RT3]
- C11 — eval golden = audited-correct values (`docs/sprint3/03_page_numbers_audit.md` truth column), NOT raw historical `agent_runs`. buggy historical runs kept only as negative fixtures. [RT6]
- C12 — `initiatives_log.jsonl` retired as an ad-hoc fork. interventions are `record_type: intervention` records — they enter via the SAME gate, get the SAME content-addressing + immutability + provenance store. the Evidence intervention page renders from intervention records, not a hand-edited log. [RT9]
- C13 — clean-room rebuild, anti-bias. gate = new module `src/insight_kit/gate/`. legacy page-D model — `provenance/run.py` (`Run`) + `provenance/claim.py` (`Claim` dataclass), the jsonl-line storage V7/RT2 rejected — deleted at cutover (T25); referenceable via git history only; never imported by the gate. KEPT + reused: `provenance/root.py` (kit-root discovery), `validation/` (Layer-A guards, T8), `errors.py`, `config/`.

## §I — interfaces

- I.emit — typed wrappers over one core gate. `ik_claim_emit`, `ik_intervention_emit`, `ik_research_emit`, `ik_skill_use_emit` — each a thin Python fn + TS pi ToolDefinition; all funnel into one core `_record_emit(record_type, input)` gate. `ik_claim_emit` MUST survive as the claim wrapper — widely referenced. wrappers chosen over a single discriminant tool: per-type param schemas the model sees are tighter, autocomplete is honest, mis-typed records reject earlier; the core gate keeps validate/fingerprint/store single-impl.
- I.schema — `RecordSchema` — pydantic discriminated union on `record_type` over `ClaimSchema | InterventionSchema | ResearchSchema | SkillUseSchema`. doubles as validator + tool-param schema source (C5).
- I.runcheck — `ik_run_check(script) -> CheckResult`. validator runner (Layer B/C, hypothesis tests).
- I.store — `records/{id}/record.json` (canonical, immutable, content-addressed) + `records.jsonl` (derived index, regenerable, carries `record_type` discriminant) + bundle siblings per type (`claim`: narrative.md, chart.vl.json, chart.png, data_snapshot.parquet, fingerprints.json; `intervention`: intent.json, realized.json; `research`/`skill_use`: captured results snapshot). `claims.jsonl` kept as a regenerable `record_type==claim` projection view for Evidence back-compat.
- I.events — `records/{id}/events/*.jsonl`. append-only. mutable post-hoc artifacts — claim `staleness` + post-emit `critiques[]`; intervention reconciliation updates; research/skill_use post-hoc utility verdict — live here, never edited into `record.json`.
- I.run — `run.json` + `manifest.jsonl` per run dir.
- I.evidence — `<ClaimNum>` / `<ClaimChart>` Evidence components + intervention-page render. resolve field from index, hard error on miss.
- I.audit — Layer-D render audit. L5 HTML-token→claim join + L6 prose lint. CI stage, post-build.
- I.env — `INSIGHT_KIT_RUN_DIR` orchestrator artifact-dir override.
- I.cites — `cites` causal edge on records. `research → claim`, `skill_use → claim`, `research → intervention`. the knowledge-provenance chain — a `claim`/`intervention` records which `research`/`skill_use` records informed it.

## §V — invariants

- V1 — every record enters via I.emit. no other writer to `records.jsonl` / `record.json`. applies to all four record types.
- V2 — schema reject → raise, zero partial write. `RunState.rejectionCount++`.
- V3 — `record.json` immutable post-emit. correction = new record w/ `supersedes` edge. events/ append-only. records.jsonl regenerable from record.json set.
- V4 — `record_fingerprint` = sha256(canonical `record.json`). `data_fingerprint` = sha256(inputs). both present on every record.
- V5 — L1 module imports no `hamilton`, no `pi`. lint-enforced (T19).
- V6 — published-tier `claim`/`intervention`: `data_fingerprint` + `code_fingerprint` + `agent_version` + `env_fingerprint` (container digest + lockfile hash) all in run.json. missing any → reject as published, downgrade to draft. [RT3]
- V7 — `records/{id}/record.json` = canonical content-addressed unit. `records.jsonl` = derived index, one projection row/record carrying `record_type`, regenerable. emit writes record.json then appends the index row. one record, one immutable home. [RT2 — resolves D-vs-E]
- V8 — zero bare numeric literal in claim `narrative.md` prose — every number is a field ref. L6 lint.
- V9 — every numeric token rendered in Evidence resolves to a `records.jsonl` claim-projection field. orphan → L5 audit fail.
- V10 — `finalizeRun` idempotent — `completedAt` guard. `agent_end` + `session_shutdown` both safe to fire.
- V11 — gate determinism testable: re-run same input in the eval harness → field value matches under C10 tolerance, `chart.vl.json` byte-identical (published tier). NOT fingerprint-identical. [RT3]
- V12 — Layer-D render audit is gate-owned + CI-blocking on `published`/`audience:board`: L6 prose lint + L5 HTML-token→claim join, zero orphans. published replay re-runs L5. [RT1 — closes the downstream half of the loop]
- V13 — input provenance: every input `.pq`/feature carries a fingerprint from a registered upstream (h_dlt source or `@feature` node). raw agent-supplied parquet paths rejected at emit. [RT4]
- V14 — coverage warnings gate-enforced: a published `claim` whose inputs are partial-period or n<30 and lacks the matching `coverage_warning` → rejected at emit. [RT4]
- V15 — selection params explicit: date-window / baseline / filter params emitted as explicit claim fields, cross-checked by a Layer-C invariant (annual = Σ monthly template). not left implicit in prompt text. [RT4]
- V16 — critique severity gates the tier: an `open` critique of `severity ≥ high` on a `published`/`audience:board` `claim`/`intervention` = hard gate fail (block render, force published→draft). `RunState.critiqueRounds` counter; cap 3 then downgrade — enforced in code, not prose. [RT5]
- V17 — published-tier hooks fail closed: on published runs, manifest/finalize failure is fatal (run fails closed — no unauditable published record). draft stays passive. `finalizeRun` asserts `manifest_complete` — tool_call vs tool_result count, records.jsonl count vs `RunState.records.length`; mismatch blocks published finalize. [RT7]
- V18 — feature miss returns provisional: `ik_feature_get` miss returns a provisional in-session feature tagged `provenance: provisional`. claims built on it forced to `draft`, cannot promote to `published` until the feature is merged + `data_eng`-certified. loop never stalls on a human PR. [RT8]
- V19 — intervention reconciliation: an `intervention` record carries `intent` (intended action — what the agent decided) and `realized` (the actual external-API call result). emit of a `published` intervention is rejected unless `realized` is present and `realized.status` ∈ {`applied`,`partial`,`failed`}. a `draft` intervention may emit with `realized: null` (action pending), but cannot promote to `published` until `realized` is populated. intent≠realized (partial/failed) is NOT a reject — it is recorded and surfaced; the invariant is *reconciliation captured*, not *action succeeded*. [RT9]
- V20 — `research`/`skill_use` are knowledge records: assert no analytical value, change no outside world, carry no tier. emit requires a captured-results snapshot persisted under the record bundle (V13-style provenance — query/tool/source/timestamp + hashed payload). a `published` `claim`/`intervention` that depends on external knowledge MUST carry a `cites` edge (I.cites) to the `research`/`skill_use` record that supplied it; bare external assertion without a cited knowledge record → reject at emit. [RT10]
- V21 — post-hoc utility verdict is event-only: the mutable `useful`/`not_useful` verdict on a `research`/`skill_use` record lands in `records/{id}/events/*.jsonl`, never edited into `record.json`. mirrors V3 + claim `critiques[]`. the record's own json stays immutable; the verdict is an append-only event. [RT10]
- V22 — data_fingerprint provenance honesty: every record carries `data_fingerprint_source` ∈ {`registered_input`, `payload`}. `payload` = fallback fingerprint over the record's own fields when no registered upstream input was supplied — NOT input provenance. a `published`-tier `claim`/`intervention` with `data_fingerprint_source == payload` → reject; V6/V13 are unsatisfiable by a self-derived fingerprint. T7/T9 check the source, never mere presence of `data_fingerprint`. [RT4]

## §T — tasks

```
id  | st | desc                                                                                  | cites
T1  | x  | define RecordSchema — pydantic discriminated union on record_type over ClaimSchema/InterventionSchema/ResearchSchema/SkillUseSchema; claim = dict fields w/ fmt_hint + tier enum | V2,V8,C5
T2  | x  | impl core _record_emit gate + typed wrappers (ik_claim_emit/ik_intervention_emit/ik_research_emit/ik_skill_use_emit) — validate → fingerprint → write record.json → append index | V1,V2,I.emit
T3  | x  | content-address fingerprints — data/record/code/env, sha256 canonical-JSON, pin float repr, NFC-normalize unicode, tag data_fingerprint_source (registered_input|payload) | V4,V6,V22,C10
T4  | x  | storage — records/{id}/record.json canonical + records.jsonl derived index w/ record_type + events/*.jsonl; claims.jsonl as regenerable claim-projection view | V7,I.store,I.events
T5  | x  | RunState accumulator + idempotent finalizeRun + manifest_complete assert               | V10,V17,I.run
T6  | x  | supersession — new record w/ supersedes edge                                           | V3
T7  | x  | tier gate — published claim/intervention requires full fingerprint set (data/code/agent/env) + data_fingerprint_source==registered_input else downgrade | V6,V22,C7
T8  | x  | Layer A/B/C wiring — A at the gate (reuse validation/ guards), B/C post-run via ik_run_check | V2,I.runcheck,C13
T9  | x  | input-provenance check — reject raw parquet paths, require registered-upstream fingerprint; extend InsightKitHook.run_before_node_execution to capture node_input_types (dropped via **future_kwargs at adapter.py:79) + compute h_dlt fingerprint sha256(resource_name+schema) at hook time | V13,V22,C8
T10 | x  | coverage-warning gate — published + partial-period/n<30 + no warning → reject          | V14
T11 | x  | selection params as explicit claim fields + Layer-C cross-check (annual=Σmonthly)      | V15
T12 | x  | critique severity gate + critiqueRounds counter in RunState                            | V16
T13 | x  | published-tier fail-closed hooks — manifest/finalize fatal on published                | V17
T14 | x  | ik_feature_get — provisional-feature return on miss + draft-lock                       | V18
T15 | .  | Evidence read-end — <ClaimNum>/<ClaimChart> resolve from index, fingerprint vs record.json | V9,I.evidence
T16 | x  | Layer-D render audit — L5 HTML-token→claim join + L6 prose lint, CI-blocking on published | V12,I.audit
T17 | x  | eval harness — containerize growth_insights fixture, golden=audited-truth, semantic field-diff, classify regression/legitimate/coverage-drop, buggy runs as negative fixtures | V11,C10,C11
T18 | x  | L3 pi extension (.pi/extensions/*.ts) — typed-wrapper TS ToolDefinitions (ik_claim_emit + ik_intervention_emit + ik_research_emit + ik_skill_use_emit), call L1 via pi.exec uv-run subprocess, gen TypeBox parameters from pydantic JSON Schema, gate on tool_call/tool_result hooks | C4,C5,I.emit
T19 | x  | purity lint — no hamilton/pi import in L1 module                                       | V5
T20 | x  | env capture — container digest + lockfile hash into run.json                           | V6,C10
T21 | x  | intervention reconciliation — intent/realized fields, emit-time reconciliation gate, draft→published promotion lock until realized populated | V19,C12
T22 | x  | research/skill_use knowledge records — captured-results snapshot persist, cites-edge requirement on dependent published claim/intervention | V20,I.cites
T23 | x  | post-hoc utility verdict — append-only useful/not_useful event on research/skill_use records | V21,I.events
T24 | .  | Evidence intervention page — render per-intervention from intervention records (baseline/realized/delta/critic), replacing the initiatives_log.jsonl hand-edit | C12,I.evidence
T25 | .  | cutover — rewire InsightKitHook adapter + cli + agents + insight_kit/__init__ exports onto the gate; delete provenance/run.py + provenance/claim.py; delete/rewrite obsolete tests; full uv run pytest green | C8,C13,V1
```

## §R — risks (2026-05-21 opus red-team of the 3-layer design)

```
id   | sev  | risk                                                                          | resolved-by
RT1  | CRIT | page D read-end/enforcement (L5/L6/<ClaimNum>) absent from gate — loop open downstream of emit | V12,T16,T15
RT2  | CRIT | storage contradiction — D claim=jsonl-line vs E claim=bundle-dir              | V7,T4
RT3  | CRIT | bit-deterministic replay unachievable as specced — wrong things pinned        | V6,V11,C10,T3,T20
RT4  | HIGH | gate/generator leak — agent-chosen inputs/windows/params cross the frozen gate | V13,V14,V15,V22,T9,T10,T11
RT5  | HIGH | critiques[] non-blocking — adversarially wrong claims publish                  | V16,T12
RT6  | HIGH | eval goldens are buggy old agent_runs — harness certifies the bugs it hunts    | C11,T17
RT7  | MED  | passive hooks under-record manifest — published claim becomes unauditable      | V17,T13
RT8  | MED  | ik_feature_get miss = unbounded async PR block, or analyst routes around catalog | V18,T14
RT9  | HIGH | interventions bypass the gate via hand-edited initiatives_log.jsonl — consequential outside-world actions unaudited, no intent-vs-realized reconciliation | V19,C12,T21,T24
RT10 | MED  | research/skill_use knowledge acquisition untracked — external assertions enter claims with no cited provenance record, no utility feedback | V20,V21,T22,T23
```

## §B — bugs

```
id | date | cause | fix
```

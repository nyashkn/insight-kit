# insight-kit — Readiness Brief: What-Is-Next to Execute

> Opus architect brief. Branch `docs/e2e-explainer`. Gate 14 modules COMPLETE, ~411 tests green, §T 23/25 done (T15+T24 CUT). Every claim below is grounded to `file:line` on this worktree. This is a PROPOSAL document — it does NOT edit SPEC.md (that is `/ck:spec`'s job).

> **RESOLUTION (2026-06-09) — this brief's proposals are SHIPPED.** All five gaps were closed on this branch: GAP-2 supersedes-chain wire = T26 (`8efd46b`); GAP-1 critique persistence = T27 (`b2e6302`) + cites/supersedes graph query = T28 (`debd915`, `572c6af`); critic tier + `supports`/`refutes` + `input_claims` schema fields + their guards = T29 (`1a21583`, `cc76196`) — so the two guards this brief called "schema-blocked, defer" are now LIVE; GAP-5 API-ingestion chain = T30–T32 (`b259d73`, `785f917`, `e9aef1e` + end-to-end `731a7f3`, `c68f660`); GAP-4 render read-end = T33 (`eeacb1d`). The point-in-time analysis below (esp. the GAP-2 "only one guard bites / defer the other two" framing) is preserved as the reasoning record at brief-time and is **superseded** by the shipped work. Gate suite now 646 tests green (5 pre-existing hamilton optional-dep skips).

---

## State of play (one paragraph)

The L1 typed-record gate is real and closed at the emit end: `_record_emit` (`src/insight_kit/platform/gate/emit.py:432`) validates against the pydantic discriminated union (`schema.py:266`), runs Layer-A guards, fingerprints, writes immutable `record.json`, appends `records.jsonl` + `claims.jsonl` projections, and registers a `RecordRef` in `RunState`. The four typed wrappers, T7 tier gate, T9 input-provenance, T10 coverage, T14 feature, T16 render-audit (L5/L6), T20 env-capture, T21 intervention reconciliation, T22 knowledge-snapshot + cites-edge integrity, and T23 utility-verdict are all wired and tested. What is NOT closed: (1) the **critique loop is in-memory theater** — `apply_critique` bumps a counter and never persists, never traverses a graph; (2) **three validation/ guards are dead code** with tests but zero gate call-sites; (3) there is **no `Run`/ingest_* acquisition layer** in `src/` (the "two systems" gap — researchers/data-eng have nowhere to land external pulls as gate records except by hand-calling the emit wrappers); (4) the **render read-end is two siblings audited independently** (no embedded-chart pipeline); and (5) the **real-world API-ingestion chain** (RESEARCHER fetches API docs → DATA-ENGINEER extracts → CRITIC critiques coverage) has the record-type primitives to exist but no orchestration, no "available-endpoints index," and no critic query. The good news: the cites-edge plumbing GAP-5 needs is already live (`emit.py:133`), so GAP-5 is mostly orchestration + one index, not new gate machinery.

---

## Per-gap analysis

### GAP-2 — Dead validation guards *(DO-FIRST candidate)*

**What's missing.** Three guards in `src/insight_kit/libs/validation/__init__.py` are fully implemented and unit-tested but have **zero call-sites in `platform/gate/`**:
- `check_critic_edges` (`validation/__init__.py:73`) — a `tier=='critic'` claim must declare ≥1 `supports`/`refutes` edge.
- `check_input_claims_exist` (`validation/__init__.py:119`) — referential integrity of `input_claims` against current+prior runs.
- `check_supersedes_chain_integrity` (`validation/__init__.py:270`) — reject superseding an already-superseded claim.

Verified orphaned: `grep` for all three across `src/` returns only their definitions; the only other hits are in `tests/libs/test_validation.py`. `emit.py`'s `_run_layer_a_guards` (`emit.py:72`) wires only `check_claim_id_format` + `check_claim_id_unique_in_run`, plus two **local reimplementations** — `_check_supersedes_exists` (`emit.py:109`, existence only) and `_check_cites_edges` (`emit.py:133`) — neither of which is the validation/ chain-integrity guard.

**The smallest correct slice.** Wire the three guards into `_run_layer_a_guards`:
- `check_supersedes_chain_integrity` — call alongside the existing `_check_supersedes_exists` (`emit.py:101`) when `supersedes is not None`. This is **purely additive**: existence check stays, chain-integrity is layered on. Closes the "supersede an already-deprecated claim" hole that V3 implies but the gate never enforced.
- `check_critic_edges` — call inside the `record.record_type == "claim"` branch (`emit.py:93`). **CAVEAT (schema mismatch, see Risks):** `ClaimRecord` (`schema.py:99`) has **no `tier=='critic'` value** (`ClaimTier` = `draft|published`, `schema.py:35`) and **no `supports`/`refutes` fields**. So this guard is a *no-op against the current schema* — it can only fire if a `critic` tier + edge fields are added. Wiring it now is harmless (the `if tier == "critic"` short-circuits) but does nothing until GAP-1 lands the critique record type. **Recommend: wire the two that bite today (supersedes-chain + input_claims), defer check_critic_edges to GAP-1's slice** where it becomes meaningful.
- `check_input_claims_exist` — requires an `input_claims: list[str]` field on `ClaimRecord` that does not exist (`schema.py:99`). Like `check_critic_edges`, it is **schema-blocked**. The closest live concept is `cites` (knowledge edges) + `selection.baseline` (a claim_id) — neither is `input_claims`. **Recommend: defer; it needs a schema field first.**

**Net DO-FIRST reality check (validating the user's hypothesis): GAP-2 is the cheapest *real* win, but only ONE of the three guards bites against today's schema — `check_supersedes_chain_integrity`.** The other two are dead because the schema fields they validate don't exist. This *refines* the user's expectation: GAP-2 is not "wire three dead guards," it is "wire the one guard that has a live target (supersedes-chain), and recognize the other two are blocked on schema additions that belong to GAP-1." That single wire is S-effort, low-risk, and adds a genuine V3 enforcement the gate is currently missing.

**Effort: S** (one guard call + ~4 tests). **Risk: LOW.** **Dependency: none** (does not depend on any other gap; the other two guards depend on GAP-1 schema work).

---

### GAP-1 — Critique persistence + graph *(biggest; the loop's missing half)*

**What's missing.**
- `apply_critique` (`runstate.py:139`) does ZERO disk writes and ZERO graph traversal — it only does `run_state.critiqueRounds += 1` (`runstate.py:166`) and returns a downgrade dict. `record_id` is used only in the error string (`runstate.py:195`).
- `CritiqueState` (`runstate.py:93`) is in-memory only: `status`/`severity`/`reason`. No `critic_id`, no target back-ref, no timestamp. Never serialized.
- `critique` is NOT a `record_type` — the union (`schema.py:266`) is `claim|intervention|research|skill_use`.
- `append_event` (`store.py:233`) writes `records/{id}/events/{name}.jsonl` but is called ONLY by `ik_utility_verdict` (`verdict.py:114`), never by `apply_critique`.
- `claims.jsonl`/`records.jsonl` projections (`store.py:196`, `store.py:145`) carry no `cites`/`refutes`/`supports`; there is no edge store and no graph query in `src/`.

**The smallest correct slice.** Mirror the **T23 utility-verdict pattern** exactly (`verdict.py`), which already solves "mutable post-hoc judgement, append-only, never edits record.json, V21/V3-safe." A critique is the same shape:
1. Add `critic_id`, `target_record_id`, `timestamp` to `CritiqueState` (`runstate.py:93`).
2. In `apply_critique` (`runstate.py:139`), after the gate decision, call `append_event(run_dir, target_record_id, "critique", critique_event)` — exactly as `ik_utility_verdict` does (`verdict.py:114`). This makes the critique durable as `records/{id}/events/critique.jsonl` and back-references the target via the directory it lands in. **This alone closes "critique never persisted."**
3. (graph slice, separable) For the "could the critic traverse the graph" need: the `cites` edges are *already* on `record.json` and the validation chain already reads them (`emit.py:158`). A read-only `query_cites(run_dir)` that scans `records/*/record.json` for `cites`/`supersedes` and returns an adjacency view is the minimum graph. Do NOT add an edge-store column to projections yet (avoid V7 regen churn) — derive the graph from the canonical `record.json` set, same way `reindex` does (`store.py:258`).

**§V honesty check.** Persisting critique as an event is **V21-aligned by analogy** (V21 is utility-verdict; a critique is morally identical) and **V3-safe** (never touches record.json). But the SPEC has no invariant that says "critique persists" — V16 (`SPEC.md:62`) only governs the *severity gate*, and it says "enforced in code." So adding persistence does not violate V16; it *completes* it. Adding `critic_id`/`target` to `CritiqueState` is a non-breaking dataclass extension.

**Effort: M** (persistence slice) + **M** (read-only graph query). **Risk: MED** — touches the critique seam many tests exercise (`test_critique_gate.py`); must keep the existing gate-decision return contract intact (33 assertions reference the dict shape). **Dependency: unblocks the two schema-blocked GAP-2 guards** (if a `critic` tier + `supports`/`refutes`/`input_claims` land here, `check_critic_edges` + `check_input_claims_exist` become live).

---

### GAP-3 — Run / ingest_* acquisition layer

**What's missing.** `ingest_search`/`ingest_url`/`ingest_skill` and a `Run` class are **not in `src/`** (`grep` confirms zero hits). The sibling repo's `growth-insights-provenance` skill documents a `Run` context manager (`with Run(...) as run: run.ingest(...); run.claim(...)`) but that is the **legacy page-D model that C13 deletes** (`SPEC.md:30`). Only the gate-level `write_snapshot` (`store.py:107` → `records/{id}/snapshot.json`) exists. The acquisition methods would write `inputs/external/<kind>/` snapshot files and return an `InputRecord` usable as an `evidence_ref`.

**The smallest correct slice.** Do NOT resurrect `Run`. The gate already has the landing primitive: `ik_research_emit` / `ik_skill_use_emit` (`emit.py:704`, `emit.py:748`) persist a captured-results snapshot and return a `RecordRef` whose `record_id` IS the evidence ref. The missing piece is a thin **acquisition helper** that wraps "do the external pull → build snapshot dict → call `ik_skill_use_emit`" so data-eng doesn't hand-assemble payloads. This is GAP-5's concern — GAP-3 collapses into GAP-5. **Recommend: do not build a standalone `Run`; treat ingest as "emit a skill_use/research record" and let GAP-5 supply the ergonomic wrapper.**

**Effort: (folded into GAP-5).** **Risk: LOW.** **Dependency: blocks nothing; GAP-5 supersedes it.**

---

### GAP-4 — Vega read-end / render path

**What's missing.** `EvidenceAdapter` is Deferred (`render_adapters.py:13` docstring). Only `VegaLiteAdapter` ships (`render_adapters.py:59`). `run_render_audit` (`audit.py:299`) takes `narrative_md` and `artifact` (the chart) as **separate params** — `narrative.md` + `chart.vl.json` are audited independently, no markdown-embedded-chart pipeline. T15 + T24 (the Evidence read-end + intervention page) are CUT (`SPEC.md:88`, `SPEC.md:97`) precisely because the Vega path supersedes them.

**The smallest correct slice.** An `EvidenceAdapter`/embedded-chart pipeline is a **product surface, not a loop-closing gate gap** — the audit already covers both halves separately and CI-blocks on `passed==False` (`audit.py:313`). **Recommend: leave deferred. This is the lowest-leverage gap** — closing it adds a render convenience, not an integrity guarantee. Only revisit if a consumer needs single-file markdown-with-chart output.

**Effort: M.** **Risk: LOW.** **Dependency: none. Lowest priority.**

---

### GAP-5 — API-ingestion chain *(user's new priority; the real-world flow)*

**The current ad-hoc pattern being replaced** (read in the sibling repo):
- `search_docs.mjs` (`.../shopify-admin/scripts/search_docs.mjs:66`) — POSTs a query to `shopify.dev/assistant/search`, returns JSON doc hits. An ad-hoc API-doc search with no provenance record.
- `extract_g4f7_attribution.py` (`.../scripts/extract_g4f7_attribution.py`) — pulls Meta adset insights (`:92`) + Shopify bulk orders (`:195`), writes raw JSON/JSONL into `inputs/`, parquet into `output/`, and a **hand-rolled `claims.jsonl`** (`:270`) with a `claim_id`, `tier`, `raw_outputs`. This is exactly the orphan-script + hand-edited-claim pattern C12/RT9 condemns — no gate, no fingerprint, no cites edge, no input-provenance check.

**The mapping (current → gate records).** All three primitives already exist; the chain is orchestration, not new machinery:

| Ad-hoc step | Becomes | Gate primitive (file:line) | Edge |
|---|---|---|---|
| `search_docs.mjs "<query>"` (RESEARCHER finds the API doc) | `research` record | `ik_research_emit` (`emit.py:704`), snapshot = the doc-search JSON | — |
| (per chosen endpoint) | `skill_use` record | `ik_skill_use_emit` (`emit.py:748`), `tool="meta_graph"/"shopify_admin"`, snapshot = raw API payload | `cites=[research_id]` |
| `extract_*.py` Meta/Shopify pull → parquet (DATA-ENGINEER) | `claim` record | `ik_claim_emit` (`emit.py:602`), `input_data=` the registered upstream so `data_fingerprint_source=='registered_input'` (`emit.py:492`) | `cites=[research_id, skill_use_id]` |
| hand-rolled `claims.jsonl` (`extract:270`) | **deleted** — claim enters via the gate | `_record_emit` writes `claims.jsonl` projection (`store.py:211`) | — |

The `cites`-edge integrity guard is **already live**: `_check_cites_edges` (`emit.py:133`) verifies each cited id exists and is a `research`/`skill_use` record. So a data-eng claim that cites the research+skill_use records is enforced *today* — the only thing missing is the orchestration that emits the research/skill_use records first.

**The "available-endpoints index" (what the critic needs).** For the critic to ask *"could they have missed an important API/endpoint for this task?"* it needs a **denominator** — the set of endpoints that *could* have been queried — to compare against the **numerator** — the endpoints actually used (derivable from `skill_use` records' `source`/`tool`). The index is a small artifact, not new gate state:

```jsonc
// records/{research_id}/endpoint_index.json  (a field in the research snapshot)
{
  "api": "shopify_admin",
  "task": "new-vs-returning order composition",
  "available_endpoints": [
    {"id": "orders.bulkOperationRunQuery", "relevance": "high", "why": "order-level new/returning"},
    {"id": "customers.segment",            "relevance": "high", "why": "returning classification"},
    {"id": "products.inventoryLevels",     "relevance": "low",  "why": "not needed for this task"}
  ],
  "source": "shopify.dev/assistant/search results for the task query"
}
```

This index is **the natural output of the RESEARCHER step** — `search_docs.mjs` already returns the candidate operations (`search_docs.mjs:88` returns the parsed JSON of hits). The researcher's job becomes: run the doc search, distill the hits into `available_endpoints` with a relevance tag, and emit that as the `research` record's snapshot. Then:

**How the critic queries used-vs-available.** A read-only critic check (lives next to `ik_run_check`, the Layer-B/C runner, `runcheck.py`):
1. Load the `research` record's `endpoint_index.json` → `available = {e.id where relevance == high}`.
2. Scan `skill_use` records in the run → `used = {r.tool+"."+endpoint from each skill_use source}`.
3. `missed = available - used`. If `missed` is non-empty and any element is `relevance:high`, raise a critique (via GAP-1's `apply_critique` → persisted as a `critique` event on the data-eng claim).

This is the **coverage critique** the user wants, and it is mechanical: a set-difference between a researcher-declared denominator and a data-eng-realized numerator, both already gate records. It needs GAP-1 (so the critique persists) and GAP-5's orchestration (so the records exist), but **no new gate invariants** — it is a Layer-B/C check, exactly where the SPEC puts hypothesis tests (`I.runcheck`, `SPEC.md:36`).

**§V / C-constraint honesty check for GAP-5.** (a) The data-eng claim must pass `input_data=` a registered upstream or T7 (`emit.py:265`) downgrades it from published → draft, and V22 (`SPEC.md:68`) rejects a published claim with `data_fingerprint_source=='payload'`. The `extract_*.py` raw parquet must therefore be **registered** (h_dlt source or `@feature`), or the chain only produces *draft* claims — which is the honest outcome and does not violate any invariant. (b) Live API calls are non-deterministic, which collides with **C2 (determinism)** *only if* the API response is fed into a `record_fingerprint` expected to be stable — it is not: the skill_use snapshot is content-addressed (its hash IS the fingerprint, `emit.py:519`), and `research`/`skill_use` are *untiered knowledge records* (V20) explicitly exempt from replay (C10/V11 govern published claims, not knowledge records). So the chain is C2-safe as long as the *claim's* value-replay uses the persisted snapshot/parquet, not a fresh API call. (c) `ik_research_emit`/`ik_skill_use_emit` auto-timestamp (`emit.py:736`), which makes the fingerprint non-deterministic by design — pass explicit timestamps in the eval harness for reproducibility (already documented at `emit.py:726`).

**Effort: L** (orchestration wrapper + endpoint-index convention + critic check) — but each piece is S/M and independently landable. **Risk: MED** (touches the real external-API surface; must not let raw API output masquerade as registered input — V22 guards this). **Dependency: critic-coverage piece needs GAP-1; the research→skill_use→claim emit chain needs nothing new.**

---

## Dependency order (gaps)

```
GAP-2 (supersedes-chain wire) ──────────────► independent, ship first
GAP-1 (critique persist) ──┬──► unblocks GAP-2's two schema-blocked guards
                           └──► unblocks GAP-5 critic-coverage critique
GAP-5 (research→skill_use→claim chain) ──► emit chain independent;
                                            critic-coverage waits on GAP-1
GAP-3 ── folded into GAP-5 (do not build standalone Run)
GAP-4 ── independent, lowest leverage, leave deferred
```

---

## Proposed NEW §T tasks (PROPOSALS — for `/ck:spec`, not applied here)

Pipe-table, caveman, FORMAT.md shape. IDs continue monotonic from T25.

```
id  | st | desc                                                                                                       | cites
T26 | .  | wire check_supersedes_chain_integrity into _run_layer_a_guards alongside _check_supersedes_exists — reject superseding an already-superseded claim | V3,T6,C13
T27 | .  | critique persistence — extend CritiqueState w/ critic_id/target_record_id/timestamp; apply_critique appends records/{id}/events/critique.jsonl via append_event (mirror T23 utility-verdict); record.json untouched | V16,V21,V3,I.events
T28 | .  | read-only cites/supersedes graph query over record.json set (derive, not project) — query_cites(run_dir) adjacency view; reuse reindex scan pattern | I.cites,V7
T29 | .  | add critic tier + supports/refutes edges to ClaimRecord; wire check_critic_edges (critic claim needs >=1 edge) + check_input_claims_exist into _run_layer_a_guards | V2,C13,T27
T30 | .  | research->skill_use->claim API-ingestion chain — ergonomic acquire() wrapper: external pull -> snapshot -> ik_research_emit (api doc search) / ik_skill_use_emit (api extraction, cites research) -> ik_claim_emit (cites both, input_data=registered) | I.cites,I.emit,V20,V22,C12
T31 | .  | available-endpoints index — researcher distills search_docs hits into endpoint_index.json (available_endpoints + relevance) persisted in research snapshot | I.cites,V20
T32 | .  | critic coverage check (Layer-B/C) — set-diff used(skill_use.source) vs available(research endpoint_index high-relevance); missed-high -> critique via apply_critique | I.runcheck,V16,T27,T31
```

---

## DO-FIRST recommendation

**Ship T26 (GAP-2 supersedes-chain wire) first.** It is the cheapest *real* integrity win: one guard call wired into an existing branch (`emit.py:101`), ~4 tests, zero schema change, zero new invariant, no dependency on any other gap. It closes a hole V3 implies but the gate never enforced (superseding an already-deprecated claim). **It also validates-with-refinement the user's hypothesis:** GAP-2 *is* the cheapest win, but only ONE of its three guards has a live schema target — the other two (`check_critic_edges`, `check_input_claims_exist`) are dead because `ClaimRecord` lacks the `critic` tier / `supports`/`refutes` / `input_claims` fields they validate, so they belong to GAP-1's schema slice (T29), not to a standalone GAP-2 wire. Do not let "wire three dead guards" become the framing — it is "wire the one that bites, defer the two that are schema-blocked."

---

## Proposed dynamic workflows

### Workflow 1 — T26: wire supersedes-chain guard *(DO NOW, lands green fast)*

Scoped tightly to the DO-FIRST slice so it lands green.

- **Phase 1 — Locate & confirm (1 Explore haiku).** Re-confirm the single edit point: `_run_layer_a_guards` (`emit.py:72`), the `supersedes is not None` branch (`emit.py:101`). Confirm `check_supersedes_chain_integrity` signature (`validation/__init__.py:270`) needs `(claim_id, supersedes, kit_root, current_run_claim_ids)` — note it reads **prior runs under `.insight-kit/runs/`** via `kit_root`, NOT `run_dir`; the wire must resolve `kit_root` (use `find_kit_root` from `libs/provenance/root.py`) or pass the run_dir's parent appropriately. **This kit_root-vs-run_dir mismatch is the one real subtlety** — flag it to the implementer.
- **Phase 2 — Edit (1 general haiku).** In `_run_layer_a_guards`, inside the existing `if supersedes is not None and run_dir is not None` block (`emit.py:101`), after `_check_supersedes_exists`, add the `check_supersedes_chain_integrity` call. Pass `current_run_claim_ids = _claim_ids_in_run(run_state)` (already available, `emit.py:412`). Resolve kit_root from run_dir.
- **Phase 3 — Tests (1 general haiku, parallel-authored with Phase 2).** Add `tests/platform/gate/test_supersedes_chain_wiring.py` mirroring `test_layer_a_wiring.py` shape: (a) emit claim A, supersede A with B (passes), (b) attempt to supersede A again with C → raises `ValidationError(rule_id='supersedes-already-deprecated')`, (c) rejectionCount increments, (d) zero partial write (`index_path` unchanged on reject).
- **Verifies via:** `uv run pytest tests/platform/gate/test_supersedes_chain_wiring.py tests/platform/gate/test_supersession.py tests/platform/gate/test_layer_a_wiring.py tests/libs/test_validation.py -q` then **full** `uv run pytest -q` (must stay ~411 green).
- **Adversarial verification (1 Opus reviewer, read-only).** Confirm: the wire did not break the existing `_check_supersedes_exists` ordering; the kit_root resolution doesn't crash when `.insight-kit/runs/` is absent (the guard returns early, `validation/__init__.py:291`); no cross-run false-positive (a legit fresh supersede must still pass); the guard is a *raise*, not a downgrade (matches V3 hard-reject semantics).
- **Modifies:** `src/insight_kit/platform/gate/emit.py` (+~3 lines), `tests/platform/gate/test_supersedes_chain_wiring.py` (new).

### Workflow 2 — T27: critique persistence *(AFTER Workflow 1)*

The biggest-leverage loop-closing slice, scoped to persistence only (graph query T28 + critic T32 are separable follow-ons).

- **Phase 1 — Design echo (1 Explore haiku).** Re-read the T23 template (`verdict.py` entirely) — it is the exact pattern to mirror: validate target exists + is right type, build event dict, `append_event(...)`. Map every line of `ik_utility_verdict` to the critique equivalent.
- **Phase 2 — Schema/state edit (1 general sonnet — elevated because it touches the critique seam many tests exercise).** Extend `CritiqueState` (`runstate.py:93`) with `critic_id: str | None`, `target_record_id: str | None`, `timestamp: str | None` (all defaulted so existing constructors in `test_critique_gate.py` keep compiling). In `apply_critique` (`runstate.py:139`), after the gate-decision return value is computed but before returning, when `run_dir` is available, call `append_event(run_dir, record_id, "critique", {...status, severity, reason, critic_id, timestamp...})`. **Hard constraint: do not change the existing return-dict shape** (`{"downgraded": ..., "tier": ...}`) — 33 assertions in `test_critique_gate.py` depend on it. `apply_critique` currently has no `run_dir` param — add it as optional `run_dir: Path | None = None`; persistence is a no-op when absent (keeps unit tests storage-free, matching `manifest_complete`'s permissive pattern at `runstate.py:236`).
- **Phase 3 — Tests (1 general haiku, parallel).** New `tests/platform/gate/test_critique_persistence.py`: (a) `apply_critique` with a `run_dir` + emitted target writes `records/{id}/events/critique.jsonl`; (b) the event carries critic_id/target/timestamp; (c) `record.json` of the target is byte-unchanged after critique (V3); (d) multiple critiques append (don't overwrite); (e) `apply_critique` with `run_dir=None` still returns the same gate dict and writes nothing (back-compat).
- **Verifies via:** `uv run pytest tests/platform/gate/test_critique_persistence.py tests/platform/gate/test_critique_gate.py tests/platform/gate/test_utility_verdict.py -q` then full `uv run pytest -q`.
- **Adversarial verification (1 Opus reviewer, read-only).** Confirm: V3 not violated (record.json untouched — diff the target before/after); the event is append-only (mirrors V21); the new `run_dir` param is genuinely optional everywhere `apply_critique` is called (`grep` shows only tests call it today, all without run_dir, so they must still pass); severity-enum serializes deterministically into the event JSON (use `.name` or `.value`, not the IntEnum repr); no auto-timestamp non-determinism leaks into a fingerprint (events are not fingerprinted — confirm).
- **Modifies:** `src/insight_kit/platform/gate/runstate.py` (CritiqueState + apply_critique), `tests/platform/gate/test_critique_persistence.py` (new). Optionally re-export nothing new (apply_critique already internal).

---

## Ordered execution recommendation

**Workflow 1 = T26 supersedes-chain guard wire (DO NOW).** One edit, ~4 tests, no schema/invariant change, no cross-gap dependency, closes a live V3 hole, lands green within one cycle. Highest leverage-per-risk on the board.

**Workflow 2 = T27 critique persistence (AFTER).** Closes the loop's missing half by mirroring the proven T23 pattern; M-effort, MED-risk (critique seam), and it is the prerequisite that unblocks both GAP-2's two schema-blocked guards (T29) and GAP-5's critic-coverage critique (T32). Do it second so T28 (graph query), T29 (critic tier/edges), and the GAP-5 chain (T30–T32) all have a persisted critique to build on.

*(Defer: GAP-4 entirely — lowest leverage, no integrity gain. Fold GAP-3 into GAP-5 — do not resurrect the C13-deleted `Run`.)*

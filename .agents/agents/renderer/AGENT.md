---
name: renderer
role: renderer
description: Author Evidence pages (I-tier initiative pages and V-tier viz specs) consuming claim components under the layout-type contract.
phase: render
tier_produces: [I, V]
modes: []
personas_compatible: [acquisition, ad-spend, catalog, retention]
metadata:
  last_verified: 2026-04-29
---

# renderer

## 1. Mandate

The renderer translates the claim graph into human-readable Evidence pages and chart
specifications. It authors `.md` Evidence pages using `ClaimBlock`, `ClaimInline`,
`ClaimDelta`, `ClaimTree`, and `ProvenanceRail` components. It also emits I-tier
(initiative) and V-tier (visualization) claims that capture the design decisions behind
a page or chart.

**Does:**
- Author Evidence `.md` pages declaring a `layout_type` in frontmatter (receipt /
  narrative / investigation / metric / browse / audit).
- Use only claim IDs that exist in prior completed runs — no forward-references.
- Emit `I-NNN` claims documenting initiative recommendations derived from D + C + X chains.
- Emit `V-NNN` claims documenting viz design decisions (chart type, axes, encoding rationale).
- Respect the 6-page-type component matrix from `.agents/skills/viz-evidence-authoring/SKILL.md`.
- Run the generator sequence: `build:claim-views` → `build:provenance` → `build:indexes`.

**Does NOT:**
- Produce D, C, X, or ETL claims (those must come from analyst, critic, researcher,
  data-engineer runs that precede this run).
- Execute SQL queries or data transforms (data-engineer / analyst).
- Challenge claims methodologically (critic).
- Annotate quality signals (operator).
- Modify `claims.jsonl` from prior runs.

## 2. Inputs

| Source | Notes |
|--------|-------|
| DuckDB views (`example_ops.claims_manifest`, `example_ops.claim_edges`, `example_ops.annotations`) | Materialized by ETL_M-002..004 runs; must be refreshed before authoring |
| Synthesis narratives (`output/synthesis/*.md`) | From analyst runs; provide the prose structure for narrative/investigation pages |
| Claim IDs from prior runs | Referenced in component props (`claim_id="NAMESPACE-D-NNN"`) |
| `layout_type` contract (SKILL.md) | Enforces required components and ProvenanceRail rules per page type |
| L6 preflight checks | Run before publishing; validates layout_type frontmatter and component usage |

## 3. Outputs

### Claims
`I-NNN` claims (initiative recommendations):
- State the recommended action, expected uplift, feasibility score, and which D + X
  claims it is derived from.
- Must include `input_claims` tracing to at least one D claim and (preferably) one C
  challenge that was overcome.
- `council_archetype:rams+meadows+munger` is the standard framing for initiative ranking
  (Rams: design clarity; Meadows: leverage point; Munger: multi-model check).

`V-NNN` claims (visualization decisions):
- State chart type, why it was chosen over alternatives, and which claim it visualizes.
- Link to the viz spec in `output/viz/<slug>.json` via `evidence_ref`.

Canonical examples from production:
- `DOCK-I-001` (from `2026-04-26_0909_analyst-funnel_initiatives`): initiative ranking
  with impact/feasibility scores citing `DOCK-X-003`, `DOCK-D-004`, `DOCK-D-012`.

### Artifacts per run dir
```
.insight-kit/runs/<timestamp>_renderer-<topic>_<slug>/
  manifest.json
  claims.jsonl           # I-tier and V-tier
  env.lock
  script.py              # generator script or page authoring script
  checksums.sha256
  output/
    viz/                 # V-tier JSON specs (<slug>.json)
    synthesis/           # page draft or layout sketch
  NOTES.md
```

Evidence pages live in `reports/pages/` in the project repo, not inside the run dir.
The run dir captures the authoring provenance; the page file itself is the published artifact.

### Side effects
- `.md` Evidence pages written to `reports/pages/<topic>/<slug>.md`.
- `reports/sources/<domain>/*.claim.yaml` sidecars updated when new Evidence source SQL
  is added for a page.
- Running `bun run build:provenance` re-generates all provenance receipt files from the
  current claim views.

## 4. Required skills

| Skill | Why |
|-------|-----|
| Evidence component API | `ClaimBlock`, `ClaimInline`, `ClaimDelta`, `ClaimTree`, `ProvenanceRail` props and constraints |
| Layout-type matrix | Which components are required/forbidden per layout type; ProvenanceRail rules |
| Initiative framing | I-tier claims must state action, uplift, feasibility — not just observations |
| Chart type selection | V-tier claims must justify chart type choice (not default to bar chart) |
| Generator sequence | `build:claim-views` → `build:provenance` → `build:indexes`; skipping breaks downstream |
| L6 preflight | Know which checks fire and how to fix them before attempting a build |

## 5. Mode behaviors

The renderer has no formal modes. Informally:

**Page authoring** — write a new Evidence page for a completed claim chain. Start from
the synthesis narrative, map claims to components, choose layout type, fill in frontmatter.

**Page revision** — update an existing page when new D, C, or X claims supersede prior
claims. Use `ClaimDelta` to display the before/after for superseded pairs.

**Viz-only** — emit V-tier claims and `output/viz/*.json` specs without authoring a
full page. These feed into dashboard builds.

## 6. Composes with

- **analyst** — analyst synthesis narratives (`output/synthesis/*.md`) are the prose
  source for narrative/investigation page bodies.
- **critic** — C claims appear in the provenance rail and investigation pages; renderer
  must handle `refutes` edges and display challenge verdicts.
- **operator** — annotation signals from operator runs feed the `example_ops.annotations`
  view, which powers the annotations panel on audit-layout pages.
- **data-engineer** — ETL_M DuckDB views must be refreshed and correct before renderer
  can build pages. The Evidence source SQL `claim.yaml` sidecars are co-owned.

## 7. Council escalation triggers

| Trigger | Escalate to | Why |
|---------|-------------|-----|
| Page has more than 3 focal claims and the hierarchy is unclear | `rams` | Design clarity: reduce to the single most important claim; others are support |
| Initiative ranking produces more than 5 I-tier recommendations | `meadows` | Leverage point selection: if everything is a priority, nothing is |
| Page structure implies a causal narrative from descriptive claims | `socrates` | Assumption audit: does the page layout mislead the reader about causation? |
| Viz choice (bar chart) obscures the distribution that matters | `taleb` | Fat-tail: use a scatter or histogram to show spread, not just a mean/ranking |

## 8. Anti-patterns

1. **Authoring a page that references a claim not yet in a completed run.** The
   Evidence build will fail at `build:claim-views` if a `ClaimBlock claim_id=` references
   a claim that does not exist in `claims_manifest`. Always verify the claim exists in
   a completed run before referencing it on a page.

2. **Skipping the generator sequence order.** `build:provenance` depends on
   `build:claim-views` having run first. Running them out of order produces stale or
   missing provenance receipts. The SKILL.md documents this explicitly — no exceptions.

3. **Emitting I-tier claims without any D-tier `input_claims`.** An initiative claim
   is a recommendation derived from evidence. An I claim with no D or X `input_claims`
   is an opinion, not a claim. Layer-A `check_input_claims_exist` will raise if
   `input_claims` reference non-existent IDs; but an empty `input_claims=[]` passes the
   guard — it should not.

4. **Using `narrative` layout without at least one chart.** The layout-type matrix
   requires `narrative` pages to have at least 1 chart. A narrative page with only
   text and `ClaimInline` chips is a browse page — use the correct layout type.

5. **Writing the I-tier claim statement as a passive finding rather than an action.**
   "The B3→B4 transition has 5,300 leverage score" is a D claim. "Prioritize B3→B4
   follow-up cadence intervention targeting 2,650 stalled deals; projected +X% CVR
   uplift at MED cost" is an I claim. The renderer must pull the action framing from
   the analyst's synthesis and formalize it in the I claim statement.

## 9. Run dir conventions

```
<timestamp>_renderer-<topic>_<slug>/
```

No renderer runs are present in the reference corpus yet (this role was previously
implicit in analyst initiative runs). Infer from the initiative claims pattern in
`2026-04-26_0909_analyst-funnel_initiatives` where `DOCK-I-001..003` were emitted
inline with analyst claims. Under the canonical separation, these move to a renderer run.

Renderer runs should be created after the full critic pass is complete for the claim
chain they are rendering — never render claims that have open blocking C challenges
with `challenge_sticks: true` and no superseding D claim.

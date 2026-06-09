# D02 — 24-run isolation factorial: design + runner spec

**Status:** design spec landed 2026-06-09. Cards: `[[16_session-backlog-board]]` § D02.
**Scope:** operational spec to attribute the 2026-05-23 score jump (0.83 → 1.00) to agent / channel / model. Extends `[[15_t17-smoke-1pt0-critic]]` § §4 from analytical sketch to runnable experiment.

## The question

Three variables changed in commit `9f5b23d` (T17 swap):
- **AGENT**: pi 0.75.4 (Node-shim) → omp 15.2.4 (native Bun)
- **CHANNEL**: openrouter (per-call $) → opencode-go (paid sub)
- **MODEL**: claude-sonnet-4.6 (1M ctx, $3/M out) → deepseek-v4-flash (384K out, sub-included)

Score moved 0.83 → 1.00. n=1. Cannot attribute the jump. Any RL signal (`T24` Harbor) built on a confounded baseline overfits to whichever variable did the work — which we don't know.

## Factorial design

**2 × 2 × 2 full factorial, k=3 trials per cell, fully randomised.**

| Factor | Levels |
|--------|--------|
| AGENT | `pi-0.75.4`, `omp-15.2.4` |
| CHANNEL | `openrouter`, `opencode-go` |
| MODEL | `claude-sonnet-4.6`, `deepseek-v4-flash` |

8 cells × 3 trials = **24 runs**. Wall-time @ ~10 min/run = **~4 wall-clock hours** sequential. Parallel infeasible — single Docker host, single Infisical bootstrap cred, opencode-go rate cap shared across cells.

### Run order

Block-randomise across 3 blocks of 8 (one trial per cell per block). Within block, Latin-square-shuffle cell order. Rationale: protects against time-of-day / cred-token-age / opencode-go-backend-warm-cache confounds bleeding into a single factor.

```
block 1: shuffle([cells]) — trial 1 of each
block 2: shuffle([cells]) — trial 2 of each
block 3: shuffle([cells]) — trial 3 of each
```

Seed the shuffle with `--seed <n>` to make the experiment replayable.

## Response variables

Per run, capture:

| Variable | Source | Used for |
|----------|--------|----------|
| `score` | `insight_kit.platform.eval.score(run_dir)` (0..1, 9 checks) | primary response |
| `score_checks_passed` | per-check count (0..9) | fine-grained dx |
| `omp_exit` / `pi_exit` | subprocess exit code | agent robustness signal |
| `wall_seconds` | clock around the agent subprocess | speed effect |
| `socket_dropped` | bool — grep agent stderr for `"socket connection was closed"` | transport hypothesis directly |
| `critic_md_bytes` | `len(findings_critic.md.encode())` | model-verbosity hypothesis |
| `claim_count` | non-comment lines in `claims.jsonl` | model output cadence |
| `usage.input_tokens` / `usage.output_tokens` | omp session JSONL parsed via `insight_kit.integrations.omp.session_parser` (omp only — pi has no equivalent) | cost / verbosity (omp arm) |
| `cell_id` | `f"{agent}_{channel}_{model}"` | grouping key |
| `block` / `trial_in_block` | runner-assigned | randomisation audit |
| `started_at` / `ended_at` | wall clock | time-of-day cofactor |

## Analysis pipeline

Drop the 24 rows into `factorial_results.csv`. Then:

1. **Main effects** — 3-way ANOVA on `score` with AGENT, CHANNEL, MODEL as factors. Report F, p, partial η² per factor.
2. **2-way interactions** — same model. Surface AGENT×CHANNEL, AGENT×MODEL, CHANNEL×MODEL.
3. **Socket-drop marginal** — `socket_dropped` rate per CHANNEL (marginalise over AGENT, MODEL). Tests the §15 dominant hypothesis ("openrouter drops, opencode-go doesn't").
4. **Critic length marginal** — mean `critic_md_bytes` per MODEL × per CHANNEL × per AGENT. Tests model-verbosity-affects-check-9 hypothesis.
5. **Cell-variance floor** — variance of `score` within `(omp, opencode-go, deepseek-flash)` cell = repeatability floor. Any "RL improvement" smaller than this floor is noise.

## Pass/fail criteria

The experiment ships a verdict, not a value judgement:

- **GO on RL coupling (T24):** repeatability floor < 0.05 AND a single dominant factor explains ≥50% of score variance.
- **HOLD on RL coupling:** floor ≥ 0.05 (too noisy for a meaningful gradient) OR no single factor dominates (configuration coupled to multiple confounds).
- **HARD STOP:** any cell with all 3 trials at score 0.0 — that cell's stack is broken; either fix it or remove that level from the factor and redesign.

## Runner contract — `growth_insights/deploy/eval/factorial_runner.py`

Not yet implemented. Expected shape:

```python
# CLI: python -m deploy.eval.factorial_runner --seed 42 --out .eval/factorial/
#
# Per-cell pre-flight:
#   - if CHANNEL=openrouter: re-wire OPENROUTER_API_KEY via Infisical (currently
#     pulled in favour of opencode-go; one-time re-add to MI-eval-harness scope)
#   - if AGENT=pi:           rebuild image insight-eval-harness:t17-pi (one
#                            Dockerfile.factorial-pi keeping pi 0.75.4 + Node shim)
#
# Per-run:
#   - call docker run with the cell's env (OMP_PROVIDER, OMP_MODEL, AGENT_BIN)
#   - copy run_dir + score + stderr to .eval/factorial/cells/<cell_id>/trial<k>/
#   - append one CSV row to .eval/factorial/results.csv
#
# After 24 runs:
#   - python -m deploy.eval.factorial_analyze .eval/factorial/results.csv
#     emits factorial_summary.md with ANOVA table + marginal plots
```

Two Dockerfiles will exist during the run: the canonical `insight-eval-harness:t17` (omp/opencode-go/deepseek) plus a `t17-pi` variant. After the experiment, the `pi` variant can be removed — it exists only to back-fill the pre-swap level of the AGENT factor.

## Cost

Cost recap with current state (post-swap):
- 12 cells use `omp` (current Dockerfile) — no rebuild needed
- 12 cells use `pi` — requires `Dockerfile.factorial-pi` build + Node-shim re-wire
- 12 cells use `openrouter` — requires `OPENROUTER_API_KEY` re-add to Infisical `mi-eval-harness` scope
- 12 cells use `opencode-go` — already wired

Sequential wall time: ~4 hours. opencode-go cost: $0 (within sub). openrouter cost: ~$0.30-0.50/run × 12 = ~$5 max. Cred rewire: ~30 min ops time.

Total: half a day end-to-end. Cheap for the question.

## What this experiment does NOT settle

- **Score gate validity.** `insight_kit.platform.eval.score` is the 9-check gate; it does not read the analysis for correctness. A high-score run can still ship a wrong claim. Settling correctness requires `T24` (agent-as-judge into Harbor signal) on top of this baseline.
- **Long-tail failure modes.** 3 trials/cell catches gross repeatability; rare-failure modes (e.g., the May 25 `0.7778` omp `query_path` drift before B1 patched the score gate) need k≥10 to surface reliably. Defer to a post-RL stability sweep.
- **Cost vs. quality elbow.** Factorial answers "which factor caused the jump", not "is the current stack worth the $/run". Cost-quality lives in a follow-up sweep over model tiers (sonnet vs haiku vs deepseek-pro) on the winning stack.

## Cross-refs

- Causal sketch source: `[[15_t17-smoke-1pt0-critic]]` § §4 Three variables
- Score gate (response variable): `eval/README.md` § `insight_kit.platform.eval.score`
- omp session parser (token extraction): `eval/README.md` § `insight_kit.integrations.omp.session_parser`
- Blocks: `T24` (Harbor RL coupling — needs repeatability floor first)
- Board: `[[16_session-backlog-board]]` § discovered D02

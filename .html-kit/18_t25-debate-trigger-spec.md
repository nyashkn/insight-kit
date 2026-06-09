# T25 — Multi-agent debate orchestration: trigger spec

**Status:** spec landed 2026-06-09. Cards: `[[16_session-backlog-board]]` § T25.
**Scope:** *when* to spawn Opus-deep + N-sonnet-builder debate vs single-agent analyst/critic. Cost gate. Not architecture.

## Why a trigger gate

Debate run = O(5x) cost of single analyst/critic loop (1 opus deep + ~4 sonnet builders + synthesis). Default-on burns budget on the 80% of runs single-pass handles cleanly. Default-off leaves the 20% hard cases under-resolved.

Trigger = automatic escalation signal. Cheap to evaluate. False-positive cost = wasted ~5x run. False-negative cost = bad claim ships.

## Trigger primitives (OR-composed)

A run escalates to debate if **any** primitive fires.

### TR1 — Score floor
**Condition:** `insight_kit.platform.eval.score(run_dir) < 0.7` after analyst pass.

**Why:** below 0.7 means ≥3 of 9 gate checks failed. Structural floor breached → single-agent retry rarely recovers. Empirical anchor: T17 May 25 real run = 0.8889. 0.7 = ~3σ below the working-baseline ceiling.

**Tuning hook:** `T25_SCORE_FLOOR` env. Default 0.7.

### TR2 — Critic severity cluster
**Condition:** critic emits ≥2 claims with `severity ∈ {HIGH, CRITICAL}` against the analyst's published claims in a single pass.

**Why:** one HIGH/CRIT can be a single-issue patch; two+ signals systemic disagreement that debate is designed to resolve. Single critic is one perspective; debate adds adversarial diversity.

**Tuning hook:** `T25_CRITIC_THRESHOLD` env. Default 2.

### TR3 — Stagnation across runs
**Condition:** rolling 3-run score window shows `Δ_max < 0.05` AND latest score `< 0.85`.

**Why:** flat-and-mediocre = single-agent loop has converged on a local minimum. Debate forces re-attack from independent angles. Excludes flat-at-the-top (≥0.85) since flat-good is the goal state, not stagnation.

**Tuning hook:** `T25_STAGNATION_WINDOW` (default 3), `T25_STAGNATION_DELTA` (default 0.05), `T25_STAGNATION_CEILING` (default 0.85).

### TR4 — Cite-graph contradiction
**Condition:** `query_cites` over `record.json` surfaces a published claim A whose `cites` includes a claim B where B is itself `refuted` by a sibling critic claim (T29 supports/refutes edges).

**Why:** publishing on a refuted foundation is a data-integrity bug, not a style issue. Single-pass critic missed it (or the refutation came later). Debate forces re-derivation. Catches RT5 (adversarially wrong claims publish) at the cite layer.

**Tuning hook:** none — boolean trigger.

### TR5 — Manual override
**Condition:** `--debate` flag passed to eval runner, OR `T25_FORCE_DEBATE=1` env set.

**Why:** human-in-the-loop override for known-hard goals (founder explicitly says "go deep on this one"). No automatic equivalent — judgment call lives with the operator.

## Composition rule

Escalate if `TR1 OR TR2 OR TR3 OR TR4 OR TR5`. No AND-gating — any single fire is sufficient. Rationale: false-positive (debate on an easy run) costs ~5x; false-negative (single-pass on a hard run) ships a bad claim into the Harbor RL signal. Asymmetric → bias toward over-escalation.

## What does NOT trigger

- **Single LOW/MED critic claim.** Single-pass critic-then-revise handles this without debate.
- **Score ≥0.7 but <0.85 on first pass.** Normal working band. Let the critic loop retry once before debating.
- **Long wall-time.** Slow ≠ hard. Cred/network latency is not a content signal.
- **Tool-call count.** High tool-call count = analyst used the tools they were given. Not a quality signal.

## Implementation surface (forward-pointer)

When wiring lands, expected shape (NOT spec'd here):

```python
from insight_kit.platform.orchestration.debate import (
    should_escalate, DebateTrigger,
)

triggers: list[DebateTrigger] = should_escalate(
    run_dir=run_dir,
    rolling_window=load_recent_scores(n=3),
    critic_severity_threshold=int(os.getenv("T25_CRITIC_THRESHOLD", "2")),
    score_floor=float(os.getenv("T25_SCORE_FLOOR", "0.7")),
)
if triggers or args.debate:
    run_debate(run_dir, reason=triggers or "manual")
else:
    finalize_single_pass(run_dir)
```

Module `insight_kit.platform.orchestration.debate` does not exist yet. Card moves to `next` when implementation is claimed.

## Open questions (not spec'd here — defer to impl session)

- Builder count N — 2, 3, 4? Cost-quality elbow not measured.
- Builder model — sonnet 4.6 vs sonnet 4.8? Pre-empts the same question for council.
- Synthesis step — single opus pass or a 2nd debate round? Defaulting to single pass; revisit if synth quality is the bottleneck.
- Cite-graph TR4 — requires T29 critic edges to be live in the consumer repo. `consumer-repo` status: T29 shipped on `insight-kit` gate, consumer wiring TBC.

## Cross-refs

- Cost model: `[[14_agentic-coding-observability]]` § §6 single-pass economics
- Critic edges schema: `SPEC.md` § §T T29
- Score gate: `eval/README.md` § `insight_kit.platform.eval.score`
- Board: `[[16_session-backlog-board]]` § next-up T25

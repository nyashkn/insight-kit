# Changelog

All notable changes to insight-kit are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the project is pre-1.0 (Alpha), minor versions may carry breaking changes;
each such change is called out under **Changed** or **Removed**.

Releases up to and including `0.1.7` predate this file; their history lives in
the git log. This changelog starts at `0.2.0`.

## [Unreleased]

## [0.2.0] - 2026-07-23

### Added

- **Cross-run workspace substrate** (`platform.gate.workspace`): a run manifest
  (`new_run_dir`, `seal_run`, `list_runs`, `reindex_runs`), claim-history queries
  (`claim_history`, `claim_by_id`), and standing-verdict resolution
  (`standing_refutations`). Claims now accumulate and are auditable across runs,
  not just within one.
- **Republish guard** (`guard_republished_claims`): surfaces current-run claims
  whose `claim_id` carries a standing refutation from a sealed run, emitting a
  critic-tier claim and applying a high-severity critique. Surface-never-block:
  the guard returns findings rather than raising.
- **Refutation contagion** (`guard_refuted_inputs`): extends the republish guard
  one edge outward — flags current-run claims that *derive* (transitively, via
  `input_claims`) from a refuted claim, whether the refutation is standing
  (cross-run) or in-run. Emits a marked contagion critic and critique per
  contaminated claim; idempotent and surface-never-block like the republish
  guard. A refuted number no longer taints only itself — everything computed
  from it is flagged too.
- **Hamilton graph lineage**: the adapter stamps each metric claim's upstream
  closure, and the gate exposes `lineage_of` / `trace_to_rows` to read the
  provenance chain back from a sealed bundle.
- **Layer-2 derived metrics**: a metric computed from other metrics' values
  lands as `payload` provenance and records the upstream claims it was derived
  from as `input_claims` (claim→claim data lineage), so a derived number still
  traces back to what produced it.
- **Agent skills + method spec**: a harness-agnostic method (`docs/method/`) for
  the producer loop (discover → compose → run → seal → verify) and the critic
  council (perspective-diverse lenses, majority-refute, verdicts as gated
  critic claims), bound to Claude Code as two directly-invocable skills
  (`.claude/skills/insight-kit-analyst`, `.claude/skills/insight-kit-critic`) and
  four archetype agents (`.claude/agents/ik-critic-*`). Gate logic stays L1
  Python, archetype prompts stay data, the binding stays thin — so a `pi`
  binding can reuse the same spec. Includes a `verify_run.py` self-check helper.
- **Measure catalog** (`integrations.hamilton.catalog`): a static semantic layer
  read from the compiled Hamilton graph and `@tag` metadata (no execution, no
  data). Distinguishes base from derived measures, advertises the `claim_id`
  each will emit, and is self-authoring — `authoring_guide()` / `format_catalog()`
  carry the `ik_*` tag contract and the composition rule an agent needs to add a
  measure.

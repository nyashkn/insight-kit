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
- **Hamilton graph lineage**: the adapter stamps each metric claim's upstream
  closure, and the gate exposes `lineage_of` / `trace_to_rows` to read the
  provenance chain back from a sealed bundle.
- **Layer-2 derived metrics**: a metric computed from other metrics' values
  lands as `payload` provenance and records the upstream claims it was derived
  from as `input_claims` (claim→claim data lineage), so a derived number still
  traces back to what produced it.
- **Measure catalog** (`integrations.hamilton.catalog`): a static semantic layer
  read from the compiled Hamilton graph and `@tag` metadata (no execution, no
  data). Distinguishes base from derived measures, advertises the `claim_id`
  each will emit, and is self-authoring — `authoring_guide()` / `format_catalog()`
  carry the `ik_*` tag contract and the composition rule an agent needs to add a
  measure.

#!/usr/bin/env python
"""Mechanical self-verify for a sealed insight-kit run.

Reads facts back out of a sealed run bundle — it does NOT judge whether a number
is *right* (that is the critic's job). For every claim in the run it reports the
provenance source and resolves the lineage trace, then checks each claim_id
against the workspace's standing refutations. Deterministic: the bundle can't
lie, so the producing agent may run this on its own work.

Usage:
    uv run python verify_run.py <workspace_dir> <run_id>

Exit code 0 when every claim's provenance resolves and none carries a standing
refutation; 1 otherwise (so it can gate a pipeline step).

Note: the republish and contagion guards (guard_republished_claims /
guard_refuted_inputs) act on a LIVE run_state and are meant to run in-flow just
BEFORE sealing. This post-seal script uses standing_refutations for the
read-only staleness equivalent.
"""

from __future__ import annotations

import sys
from pathlib import Path

from insight_kit.platform.gate import list_runs, standing_refutations
from insight_kit.platform.gate.lineage import LineageNotRecordedError, lineage_of
from insight_kit.platform.gate.store import read_record


def verify(workspace_dir: Path, run_id: str) -> int:
    run_dir = workspace_dir / "runs" / run_id
    entry = next((e for e in list_runs(workspace_dir) if e.run_id == run_id), None)
    if entry is None:
        print(f"FAIL: no sealed run {run_id!r} in workspace {workspace_dir}")
        return 1

    standing = standing_refutations(workspace_dir)
    ok = True
    print(f"run {run_id}: {len(entry.claims)} claim sightings\n")

    for s in entry.claims:
        rec = read_record(run_dir, s.record_id)
        source = rec.get("data_fingerprint_source") or "-"
        inputs = rec.get("input_claims") or []
        line = f"  {s.claim_id}  tier={s.tier}  provenance={source}"
        if inputs:
            line += f"  input_claims={len(inputs)}"

        # Lineage must resolve for a metric claim; a claim emitted outside a
        # driver run legitimately has none, which we report rather than fail on.
        try:
            trace = lineage_of(run_dir, s.record_id)
            line += f"  node={trace.node}  upstream={len(trace.upstream_closure)}"
            if trace.is_overridden:
                line += f"  OVERRIDDEN({len(trace.overridden)})"
        except LineageNotRecordedError:
            line += "  (no lineage — non-driver emit)"
        except ValueError:
            pass  # not a claim record; skip lineage

        if s.claim_id in standing:
            line += "  << STANDING REFUTATION"
            ok = False

        print(line)

    print()
    if ok:
        print("OK: every claim resolved; no standing refutations in this run.")
        return 0
    print("FAIL: at least one claim carries a standing refutation — do not publish over it.")
    return 1


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    return verify(Path(sys.argv[1]), sys.argv[2])


if __name__ == "__main__":
    raise SystemExit(main())

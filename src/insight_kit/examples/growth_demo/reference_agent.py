"""Reference agent: the read-history -> diff -> report loop over the fixture.

This is the worked example the cross-run substrate exists for. It plays two
"pulse days" over the seeded growth fixture and shows a memoryless agent doing
what a single run cannot:

  day 1  run the DAG, emit CAC/MER/naive-CAC claims, reconcile each against the
         fixture's ground truth (true CAC supported, the P5-trap naive CAC
         refuted), then seal the run into the workspace.
  day 2  the window has advanced (more days of spend + customers), so re-run.
         Before sealing, walk the sealed history: report how blended CAC
         drifted since day 1, and run the persistent republish guard — which
         catches that the naive-CAC claim, refuted on day 1, was re-emitted on
         day 2 without a superseding verdict.

Nothing here holds state between the two runs in memory. Everything day 2 knows
about day 1 it reads back from the sealed workspace bundle (claim_history,
standing_refutations, the guard) — exactly how an external, ephemeral agent
would reconstruct context each time it wakes.

Run it directly::

    python -m insight_kit.examples.growth_demo.reference_agent

Requires the optional ``hamilton`` extra (the DAG runs through the gate-backed
driver). Cites: item 6 (workspace substrate), item 7 (lineage), T29 (critic
edges), V16 (republish guard).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from insight_kit.platform.gate import (
    RepublishFinding,
    RunState,
    check_ratio_identity,
    claim_by_id,
    claim_history,
    emit_reconciliation_critique,
    guard_republished_claims,
    new_run_dir,
    seal_run,
)
from insight_kit.platform.gate.store import read_record

# claim_id -> the ik_metric field name the adapter stores the value under.
_TRUE_CAC = "DEMO-D-010"
_MER = "DEMO-D-011"
_NAIVE_CAC = "DEMO-D-012"
_METRIC_FIELD = {
    _TRUE_CAC: "blended_cac_kes",
    _MER: "mer",
    _NAIVE_CAC: "naive_cac_kes",
}


@dataclass(frozen=True)
class RunSummary:
    """What one pulse day produced."""

    run_id: str
    days: int
    blended_cac: float
    mer: float
    naive_cac: float
    naive_refuted: bool
    guard_findings: list[RepublishFinding] = field(default_factory=list)


@dataclass(frozen=True)
class LoopReport:
    """The cross-run answer the loop assembles from sealed history."""

    runs: list[RunSummary]
    blended_cac_drift: float
    blended_cac_drift_pct: float
    republished_refuted: list[str]


def _record_id_for(run_state: RunState, run_dir: Path, claim_id: str) -> str:
    """The current run's content-addressed record_id for a gate claim_id."""
    for ref in run_state.records:
        if ref.record_type != "claim":
            continue
        if read_record(run_dir, ref.record_id).get("claim_id") == claim_id:
            return ref.record_id
    raise KeyError(f"claim {claim_id} not emitted in this run")


def _metric_value(record: dict[str, Any], field_name: str) -> float:
    """Pull a metric value back out of a sealed claim record's fields."""
    entry = (record.get("fields") or {}).get(field_name)
    return float(entry["value"]) if isinstance(entry, dict) else float("nan")


def run_once(
    workspace_dir: Path | str,
    *,
    run_id: str,
    days: int,
    emit_timestamp: str | None = None,
) -> RunSummary:
    """Play one pulse day: execute the DAG, reconcile, guard against prior runs, seal.

    The guard runs BEFORE the seal — it checks the claims of THIS (still
    unsealed) run against the standing refutations of already-SEALED runs, then
    seal_run adds this run to the history the next day will read.
    """
    from insight_kit.examples.growth_demo import dag, datagen
    from insight_kit.integrations.hamilton import build_driver

    workspace_dir = Path(workspace_dir)
    demo = datagen.generate(seed=42, days=days)
    run_dir = new_run_dir(workspace_dir, run_id=run_id)

    run_state = RunState(run_dir=run_dir)
    driver = build_driver(run_state, run_dir, [dag], emit_timestamp=emit_timestamp)
    out = driver.execute(
        ["blended_cac", "demo_mer", "naive_cac"],
        inputs={
            "meta_ads_raw": demo.meta_ads,
            "google_ads_raw": demo.google_ads,
            "orders_raw": demo.orders,
        },
    )

    # Reconcile each CAC against the fixture's by-construction components. The
    # true CAC satisfies spend / new_customers and is supported; the naive CAC
    # (P5 trap: divides by distinct customers) fails the identity and is refuted.
    gt = demo.ground_truth
    for claim_id, value, critic_id in (
        (_TRUE_CAC, out["blended_cac"], "DEMO-C-010"),
        (_NAIVE_CAC, out["naive_cac"], "DEMO-C-012"),
    ):
        result = check_ratio_identity(
            value, gt["total_spend_kes"], gt["new_customers"], label="cac"
        )
        emit_reconciliation_critique(
            result,
            _record_id_for(run_state, run_dir, claim_id),
            critic_id,
            run_state=run_state,
            run_dir=run_dir,
        )

    # Persistent guard: did any draft/published claim here carry a standing
    # refutation from a prior SEALED run? (Empty on day 1 — nothing sealed yet.)
    findings = guard_republished_claims(workspace_dir, run_state=run_state, run_dir=run_dir)

    seal_run(workspace_dir, run_dir, run_state)

    naive_sighting = claim_by_id(workspace_dir, _NAIVE_CAC)
    return RunSummary(
        run_id=run_id,
        days=days,
        blended_cac=out["blended_cac"],
        mer=out["demo_mer"],
        naive_cac=out["naive_cac"],
        naive_refuted=bool(naive_sighting and naive_sighting.is_refuted),
        guard_findings=findings,
    )


def run_reference_loop(
    workspace_dir: Path | str,
    *,
    emit_timestamp: str | None = None,
) -> LoopReport:
    """Two pulse days over the fixture; assemble the cross-run delta report.

    Day 2's window is longer (45 vs 30 days), so blended CAC drifts. The report
    is built purely from sealed history (claim_history / the guard), not from
    the live run objects — the substrate is the memory.
    """
    workspace_dir = Path(workspace_dir)
    day1 = run_once(
        workspace_dir, run_id="pulse-2026-01-30", days=30, emit_timestamp=emit_timestamp
    )
    day2 = run_once(
        workspace_dir, run_id="pulse-2026-02-14", days=45, emit_timestamp=emit_timestamp
    )

    # Drift on the true CAC, read back from the two sealed sightings.
    history = claim_history(workspace_dir, _TRUE_CAC)
    values = [_metric_value(s.load(workspace_dir), _METRIC_FIELD[_TRUE_CAC]) for s in history]
    first, last = values[0], values[-1]
    drift = last - first
    drift_pct = drift / first if first else float("nan")

    republished = sorted({f.claim_id for f in day2.guard_findings})
    return LoopReport(
        runs=[day1, day2],
        blended_cac_drift=drift,
        blended_cac_drift_pct=drift_pct,
        republished_refuted=republished,
    )


def format_report(report: LoopReport) -> str:
    """Render the loop's findings as a short human-readable brief."""
    lines: list[str] = ["growth-demo reference agent — cross-run pulse", ""]
    for r in report.runs:
        lines.append(
            f"  [{r.run_id}] {r.days}d window: "
            f"blended_cac={r.blended_cac:,.0f}  mer={r.mer:.2f}  "
            f"naive_cac={r.naive_cac:,.0f} ({'refuted' if r.naive_refuted else 'unverdicted'})"
        )
    lines += [
        "",
        f"  blended CAC drift day1->day2: {report.blended_cac_drift:+,.0f} KES "
        f"({report.blended_cac_drift_pct:+.1%})",
    ]
    if report.republished_refuted:
        lines.append(
            "  guard: republished-after-refutation caught for "
            + ", ".join(report.republished_refuted)
            + " (naive CAC was refuted on day 1 and re-emitted on day 2)"
        )
    else:
        lines.append("  guard: no refuted claim was republished")
    return "\n".join(lines)


def main() -> None:
    """Run the loop in a throwaway workspace and print the brief."""
    with tempfile.TemporaryDirectory(prefix="ik-growth-demo-") as tmp:
        report = run_reference_loop(tmp)
        print(format_report(report))


if __name__ == "__main__":
    main()

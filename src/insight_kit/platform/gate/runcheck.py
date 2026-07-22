"""T8 — ik_run_check: Layer-B/C validator script runner (I.runcheck).

Generic post-run checker: runs a validator script (hypothesis-style Layer B/C
tests) as a subprocess and returns a structured CheckResult.

The runner is intentionally content-agnostic — it does not inspect, parse, or
interpret the check logic. It delegates entirely to the script's exit code.

T32 — check_endpoint_coverage_gap: Layer-B/C pure-fn check for endpoint coverage
gaps (V16). Detects when a claim used only a subset of available high-relevance
API endpoints. Callers fire a critique via apply_critique when missed_high
endpoints are found.

T32 extension — derive_used_endpoints: scans skill_use record.json files under
run_dir/records/* and collects their .source values, building the real used-set
from emitted data rather than a hand-fed list.

check_coverage_from_run: convenience that wires derive_used_endpoints +
read_endpoint_index into check_endpoint_coverage_gap for end-to-end critic runs.

Cites: I.runcheck, V2, V16, C1, T32.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CheckResult — structured return value
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Structured result from a validator script run (I.runcheck).

    passed:    True iff the script exited with code 0.
    exit_code: raw process exit code (0 = pass, non-zero = fail).
    details:   human-readable summary / error detail (may be None).
    stdout:    captured stdout from the script (empty string if none).
    stderr:    captured stderr from the script (empty string if none).
    """

    passed: bool
    exit_code: int = 0
    details: str | None = None
    stdout: str = field(default="")
    stderr: str = field(default="")


# ---------------------------------------------------------------------------
# ik_run_check — generic Layer-B/C runner
# ---------------------------------------------------------------------------


def ik_run_check(script: str, *, timeout: float = 30.0) -> CheckResult:
    """Run a validator script and return a structured CheckResult.

    The runner is generic: it executes `script` as a Python subprocess using
    the current interpreter and captures stdout/stderr.  It does NOT inspect
    the check logic — the script is responsible for its own assertions.

    A script that exits 0 → CheckResult.passed = True.
    Any non-zero exit code (including unhandled exceptions) → passed = False.

    If the script file does not exist the runner returns a failed CheckResult
    rather than raising, so callers get a consistent interface.

    Args:
        script:  absolute or relative path to the Python validator script.
        timeout: max seconds the validator may run before it is killed and a
                 failed CheckResult is returned (default 30s).

    Returns:
        CheckResult with pass/fail + captured output.

    Cites: I.runcheck, V2 (schema reject → raise; generic runner never partial-
           writes, it only reads/executes external check logic).
    """
    try:
        proc = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            passed=False,
            exit_code=-1,
            details=f"Validator script timed out after {timeout}s: {script!r}",
            stdout="",
            stderr="",
        )
    except FileNotFoundError:
        # Interpreter found but script file missing — or interpreter not found.
        return CheckResult(
            passed=False,
            exit_code=-1,
            details=f"Script not found or not executable: {script!r}",
            stdout="",
            stderr="",
        )
    except OSError as exc:
        return CheckResult(
            passed=False,
            exit_code=-1,
            details=f"OS error running script {script!r}: {exc}",
            stdout="",
            stderr="",
        )

    passed = proc.returncode == 0
    details: str | None = None
    if not passed and proc.stderr:
        details = proc.stderr.strip()
    elif not passed:
        details = f"Script exited with code {proc.returncode}"

    return CheckResult(
        passed=passed,
        exit_code=proc.returncode,
        details=details,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


# ---------------------------------------------------------------------------
# Layer-C cross-claim invariants (T11/V15)
# ---------------------------------------------------------------------------


@dataclass
class CrossCheckResult:
    """Structured result of a Layer-C cross-claim invariant check (T11/V15).

    passed:   True iff the invariant holds within tolerance.
    expected: the value the invariant predicts.
    actual:   the value actually asserted by the claim under check.
    rel_diff: relative difference |actual-expected| / |expected|
              (0.0 when expected == actual; inf when expected == 0 != actual).
    message:  human-readable summary.
    """

    passed: bool
    expected: float
    actual: float
    rel_diff: float
    message: str


def check_annual_equals_monthly_sum(
    annual_value: float,
    monthly_values: list[float],
    *,
    tolerance: float = 0.01,
) -> CrossCheckResult:
    """T11/V15 Layer-C cross-check — an annual figure must equal its monthly parts.

    Catches the partial-month / wrong-grain class (RT4): an annual claim whose
    value silently disagrees with the monthly claims it should aggregate.

    Pure function — a standalone Layer-C invariant. It is NOT wired into the
    emit gate; a caller runs it post-run over a set of related claims (e.g. via
    ik_run_check driving a script that calls this).

    Args:
        annual_value:   the asserted annual value.
        monthly_values: the per-month values that should sum to the annual.
        tolerance:      relative tolerance (fraction) for the equality check.

    Returns:
        CrossCheckResult — passed True iff |annual - sum(monthly)| within tolerance.
    """
    expected = sum(monthly_values)
    actual = annual_value
    if expected != 0:
        rel_diff = abs(actual - expected) / abs(expected)
    else:
        rel_diff = 0.0 if actual == expected else float("inf")
    passed = rel_diff <= tolerance
    n_months = len(monthly_values)
    if passed:
        message = (
            f"annual={actual} matches the sum of {n_months} monthly values "
            f"({expected}) within tolerance {tolerance}"
        )
    else:
        message = (
            f"annual={actual} disagrees with the sum of {n_months} monthly "
            f"values ({expected}); relative difference {rel_diff:.4f} exceeds "
            f"tolerance {tolerance} — possible partial-month or wrong-grain "
            f"claim (V15/RT4)"
        )
    return CrossCheckResult(
        passed=passed,
        expected=expected,
        actual=actual,
        rel_diff=rel_diff,
        message=message,
    )


def check_ratio_identity(
    ratio: float,
    numerator: float,
    denominator: float,
    *,
    tolerance: float = 0.01,
    label: str = "ratio",
) -> CrossCheckResult:
    """Reconciliation identity for a ratio/product metric (deductive check).

    Generalizes ``check_annual_equals_monthly_sum`` from the additive identity
    (total == Σ parts) to the ratio identity (ratio == numerator / denominator).
    This covers the metric class the CAC/MER work lives in:

        CAC == spend / new_customers
        MER == revenue / ad_spend

    Independently recomputing the ratio from its two component claims and
    comparing to the asserted ratio catches the drift class where the headline
    number and its components silently disagree (the CAC-1059-vs-1770 case).

    A deductive identity: a violation is a proof of a bug, so the caller may
    emit a *refuting* critique (see ``emit_reconciliation_critique``) that blocks
    promotion — never merely a warning.

    Args:
        ratio:       the asserted ratio value under check.
        numerator:   the asserted numerator (e.g. spend, revenue).
        denominator: the asserted denominator (e.g. new_customers, ad_spend).
        tolerance:   relative tolerance (fraction). Keep it per-metric and
                     empirically calibrated — refunds/FX/timing give real
                     identities structural slack (brief §04, guardrail 1).
        label:       metric name for the message (descriptive).

    Returns:
        CrossCheckResult — passed True iff |ratio - numerator/denominator|
        within tolerance. A zero denominator with a non-zero numerator is an
        undefined ratio and always fails (rel_diff = inf).
    """
    if denominator == 0:
        expected = 0.0 if numerator == 0 else float("inf")
    else:
        expected = numerator / denominator
    actual = ratio
    if expected in (0.0,):
        rel_diff = 0.0 if actual == expected else float("inf")
    elif expected == float("inf"):
        rel_diff = float("inf")
    else:
        rel_diff = abs(actual - expected) / abs(expected)
    passed = rel_diff <= tolerance
    if passed:
        message = (
            f"{label}={actual} matches numerator/denominator "
            f"({numerator}/{denominator}={expected}) within tolerance {tolerance}"
        )
    else:
        message = (
            f"{label}={actual} disagrees with numerator/denominator "
            f"({numerator}/{denominator}={expected}); relative difference "
            f"{rel_diff:.4f} exceeds tolerance {tolerance} — the headline value "
            f"and its components disagree (reconciliation failure)"
        )
    return CrossCheckResult(
        passed=passed,
        expected=expected if expected != float("inf") else 0.0,
        actual=actual,
        rel_diff=rel_diff,
        message=message,
    )


def emit_reconciliation_critique(
    result: CrossCheckResult,
    target_claim_record_id: str,
    critic_claim_id: str,
    *,
    run_state: Any,
    run_dir: Path | None = None,
    statement: str | None = None,
) -> Any:
    """Turn a reconciliation verdict into a critic-tier claim (I.emit, T29).

    A reconciliation always leaves an auditable verdict edge on the claim it
    checked (constraint-library design: checks leave verdicts):
      * passed  → a critic claim that ``supports`` the target.
      * failed  → a critic claim that ``refutes`` the target. The refutes edge
        is what the pulse/assembly step uses to block promotion to published.

    Args:
        result:                 the CrossCheckResult from a reconciliation check.
        target_claim_record_id: content-addressed record_id of the claim checked
                                (must already exist in run_dir as a claim record).
        critic_claim_id:        gate-valid claim_id for the critic claim
                                (e.g. "DEMO-C-001").
        run_state:              RunState accumulator for the run.
        run_dir:                run directory (resolved from env if None).
        statement:              optional override for the critique statement;
                                defaults to result.message.

    Returns:
        RecordRef for the emitted critic claim.
    """
    from insight_kit.platform.gate.emit import ik_claim_emit

    fields = {
        "reconciliation": {"value": statement or result.message, "fmt_hint": None},
        "expected": {"value": result.expected, "fmt_hint": None},
        "actual": {"value": result.actual, "fmt_hint": None},
        "rel_diff": {"value": result.rel_diff, "fmt_hint": None},
        "passed": {"value": result.passed, "fmt_hint": None},
    }
    return ik_claim_emit(
        critic_claim_id,
        fields,
        tier="critic",
        supports=[target_claim_record_id] if result.passed else None,
        refutes=[target_claim_record_id] if not result.passed else None,
        run_state=run_state,
        run_dir=run_dir,
    )


# ---------------------------------------------------------------------------
# T32 — endpoint coverage gap check (V16/I.runcheck)
# ---------------------------------------------------------------------------


@dataclass
class CheckEndpointCoverageResult:
    """Result of endpoint coverage gap check (T32, V16).

    passed:               True iff no missed high-relevance endpoints.
    missed_high_endpoints: list of endpoint ids with relevance=='high' not used.
    available_high_count: number of high-relevance endpoints available.
    used_endpoint_count:  number of unique endpoints actually used.
    message:              human-readable summary.
    """

    passed: bool
    missed_high_endpoints: list[str]
    available_high_count: int
    used_endpoint_count: int
    message: str


def check_endpoint_coverage_gap(
    endpoint_index: dict[str, Any] | None,
    used_endpoints: list[str],
    *,
    claim_id: str | None = None,
) -> CheckEndpointCoverageResult:
    """T32/V16/I.runcheck — Layer-B/C pure-fn check for endpoint coverage gaps.

    Detects when a claim used only a subset of available high-relevance API endpoints.
    Compares endpoints actually used (from skill_use.source values) against endpoints
    available in the research record's endpoint_index with relevance=='high'.

    Pure function — not wired into emit. A caller invokes this post-run over a set of
    related skill_use records (e.g. via ik_run_check driving a script that calls this).
    When missed_high endpoints are detected, the caller may fire a critique via
    apply_critique with severity='high' (V16).

    Namespace contract (I.cites, T32):
        Coverage matching uses string identity. An element in ``used_endpoints``
        (derived from ``skill_use.source``) registers as covering an endpoint in
        ``endpoint_index`` only when it equals the entry's ``id`` field exactly
        (falling back to ``endpoint`` then ``name`` if ``id`` is absent).
        Callers MUST ensure that ``skill_use.source`` is set to the same string
        used as the endpoint ``id`` in the index — no normalisation or alias
        resolution is performed here.

    Args:
        endpoint_index: the research record's endpoint_index dict from snapshot.
                       Contains 'available_endpoints' list of {id, relevance, why, ...}.
                       May be None or missing 'available_endpoints' → returns passed=True.
        used_endpoints: list of endpoint ids actually used (derived from skill_use.source).
        claim_id: optional claim_id for the message (descriptive, not load-bearing).

    Returns:
        CheckEndpointCoverageResult — passed True iff no high-relevance endpoints missed.
    """
    label = f"claim {claim_id!r}" if claim_id else "claim"

    # Graceful handling: no denominator → no gate
    if endpoint_index is None:
        return CheckEndpointCoverageResult(
            passed=True,
            missed_high_endpoints=[],
            available_high_count=0,
            used_endpoint_count=len(set(used_endpoints)),
            message=f"{label}: no endpoint_index provided — coverage check skipped (T32/V16)",
        )

    available_endpoints: list[dict[str, Any]] = endpoint_index.get("available_endpoints", [])
    if not available_endpoints:
        return CheckEndpointCoverageResult(
            passed=True,
            missed_high_endpoints=[],
            available_high_count=0,
            used_endpoint_count=len(set(used_endpoints)),
            message=f"{label}: endpoint_index has no available_endpoints — coverage check skipped (T32/V16)",
        )

    # Collect high-relevance endpoint ids (use 'id' key, fall back to 'endpoint' key)
    high_endpoints: list[str] = []
    for ep in available_endpoints:
        if ep.get("relevance") == "high":
            ep_id = ep.get("id") or ep.get("endpoint") or ep.get("name")
            if ep_id:
                high_endpoints.append(str(ep_id))

    if not high_endpoints:
        return CheckEndpointCoverageResult(
            passed=True,
            missed_high_endpoints=[],
            available_high_count=0,
            used_endpoint_count=len(set(used_endpoints)),
            message=f"{label}: no high-relevance endpoints in index — coverage check skipped (T32/V16)",
        )

    used_set = set(used_endpoints)
    missed = [ep_id for ep_id in high_endpoints if ep_id not in used_set]

    if missed:
        missed_str = ", ".join(repr(m) for m in missed)
        message = (
            f"{label}: missed {len(missed)} high-relevance endpoint(s) out of "
            f"{len(high_endpoints)} available: {missed_str} — "
            f"possible incomplete API coverage (T32/V16)"
        )
        return CheckEndpointCoverageResult(
            passed=False,
            missed_high_endpoints=missed,
            available_high_count=len(high_endpoints),
            used_endpoint_count=len(used_set),
            message=message,
        )

    return CheckEndpointCoverageResult(
        passed=True,
        missed_high_endpoints=[],
        available_high_count=len(high_endpoints),
        used_endpoint_count=len(used_set),
        message=(
            f"{label}: all {len(high_endpoints)} high-relevance endpoint(s) covered "
            f"(T32/V16)"
        ),
    )


# ---------------------------------------------------------------------------
# T32 extension — derive_used_endpoints + check_coverage_from_run
# ---------------------------------------------------------------------------


def derive_used_endpoints(
    run_dir: Path,
    research_record_id: str | None = None,
) -> set[str]:
    """Scan skill_use record.json files and collect their .source values.

    Walks records/*/record.json under run_dir, reads every record whose
    record_type == 'skill_use', and accumulates the non-empty `source` field
    values into a set.  This derives the real used-endpoint set from emitted
    data rather than requiring the caller to hand-feed a list.

    Skips corrupt or unreadable record.json files with a WARNING log (mirrors
    the store.reindex / graph_query.query_cites skip pattern).

    Namespace contract (I.cites, T32):
        When ``research_record_id`` is provided, only skill_use records whose
        ``cites`` list contains that id are included.  This scopes the used-set
        to the specific research bundle under check, preventing endpoint usage
        from a *different* research bundle from masking a real gap (the
        cross-bundle false-negative, T32 hardening).  When ``research_record_id``
        is None the full run-global set is returned (backward-compatible).

        Coverage then relies on string identity between ``skill_use.source`` and
        the endpoint ``id`` in the endpoint_index — no normalisation is applied.
        Callers MUST use the same string in both places (I.cites, T32).

    Args:
        run_dir:              path to the run directory (must exist; records/ scanned).
        research_record_id:   when provided, restrict to skill_use records whose
                              ``cites`` list contains this id.  None = run-global
                              (backward compatible).

    Returns:
        set[str] of source values from matching skill_use records.
        Empty set if no matching skill_use records are found or run_dir has no records/.

    Cites: T32, V16, I.store, I.cites.
    """
    run_dir = Path(run_dir).resolve()
    records_root = run_dir / "records"
    used: set[str] = set()

    if not records_root.exists():
        return used

    for rec_path in sorted(records_root.glob("*/record.json")):
        try:
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
        except Exception:
            log.warning(
                "derive_used_endpoints: skipping corrupt record at %s", rec_path
            )
            continue

        if rec.get("record_type") != "skill_use":
            continue

        # T32 hardening: when a research bundle is specified, only count
        # skill_use records that cite that bundle.  This prevents a skill_use
        # from a *different* research chain from falsely satisfying coverage.
        if research_record_id is not None:
            cites: list[str] = rec.get("cites") or []
            if research_record_id not in cites:
                continue

        source = rec.get("source", "")
        if source:
            used.add(str(source))

    return used


def check_coverage_from_run(
    run_dir: Path,
    research_record_id: str,
    *,
    claim_id: str | None = None,
) -> CheckEndpointCoverageResult:
    """End-to-end coverage check: derive used-set + read index + run gap check.

    Convenience that wires three steps together for the T32 end-to-end critic:
      1. derive_used_endpoints(run_dir, research_record_id)  — sources from
         skill_use records scoped to the bundle under check (T32 hardening).
      2. read_endpoint_index(run_dir, research_record_id)  — load stored index.
      3. check_endpoint_coverage_gap(index, used_list, claim_id=claim_id).

    Passes ``research_record_id`` to ``derive_used_endpoints`` so that endpoint
    usage from *other* research bundles in the same run cannot mask a real gap
    (cross-bundle false-negative, T32 hardening).

    Args:
        run_dir:             run directory containing records/.
        research_record_id:  record_id (directory name) of the research record
                             whose endpoint_index.json should be loaded, and the
                             bundle id used to scope the used-set.
        claim_id:            optional claim_id forwarded to the gap check for
                             descriptive messages.

    Returns:
        CheckEndpointCoverageResult from check_endpoint_coverage_gap.

    Cites: T32, V16.
    """
    from insight_kit.platform.gate.store import read_endpoint_index

    used_set = derive_used_endpoints(run_dir, research_record_id=research_record_id)
    endpoint_index = read_endpoint_index(run_dir, research_record_id)
    return check_endpoint_coverage_gap(
        endpoint_index,
        list(used_set),
        claim_id=claim_id,
    )

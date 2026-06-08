"""T8 — ik_run_check: Layer-B/C validator script runner (I.runcheck).

Generic post-run checker: runs a validator script (hypothesis-style Layer B/C
tests) as a subprocess and returns a structured CheckResult.

The runner is intentionally content-agnostic — it does not inspect, parse, or
interpret the check logic. It delegates entirely to the script's exit code.

T32 — check_endpoint_coverage_gap: Layer-B/C pure-fn check for endpoint coverage
gaps (V16). Detects when a claim used only a subset of available high-relevance
API endpoints. Callers fire a critique via apply_critique when missed_high
endpoints are found.

Cites: I.runcheck, V2, V16, C1, T32.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

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

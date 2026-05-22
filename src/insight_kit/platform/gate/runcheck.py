"""T8 — ik_run_check: Layer-B/C validator script runner (I.runcheck).

Generic post-run checker: runs a validator script (hypothesis-style Layer B/C
tests) as a subprocess and returns a structured CheckResult.

The runner is intentionally content-agnostic — it does not inspect, parse, or
interpret the check logic. It delegates entirely to the script's exit code.

Cites: I.runcheck, V2, C1.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field

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

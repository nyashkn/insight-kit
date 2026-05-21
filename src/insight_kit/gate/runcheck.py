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


def ik_run_check(script: str) -> CheckResult:
    """Run a validator script and return a structured CheckResult.

    The runner is generic: it executes `script` as a Python subprocess using
    the current interpreter and captures stdout/stderr.  It does NOT inspect
    the check logic — the script is responsible for its own assertions.

    A script that exits 0 → CheckResult.passed = True.
    Any non-zero exit code (including unhandled exceptions) → passed = False.

    If the script file does not exist the runner returns a failed CheckResult
    rather than raising, so callers get a consistent interface.

    Args:
        script: absolute or relative path to the Python validator script.

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

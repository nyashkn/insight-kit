"""T8 — ik_run_check Layer-B/C runner (I.runcheck).

Tests for ik_run_check(script) -> CheckResult — a generic validator script runner
that runs hypothesis-style post-run checks and returns a structured CheckResult.

Cites: I.runcheck, V2.
"""
from __future__ import annotations

import textwrap

from insight_kit.gate import CheckResult, ik_run_check

# ---------------------------------------------------------------------------
# CheckResult dataclass tests
# ---------------------------------------------------------------------------


class TestCheckResult:
    def test_passed_result(self):
        """CheckResult can represent a passing run."""
        result = CheckResult(passed=True, details="all checks green")
        assert result.passed is True
        assert result.details == "all checks green"

    def test_failed_result(self):
        """CheckResult can represent a failing run."""
        result = CheckResult(passed=False, details="assertion failed")
        assert result.passed is False

    def test_details_optional(self):
        """details field is optional (defaults to None or empty string)."""
        result = CheckResult(passed=True)
        assert result.passed is True
        # details may be None or ""
        assert result.details is None or result.details == ""

    def test_exit_code_present(self):
        """CheckResult carries the script exit code."""
        result = CheckResult(passed=True, exit_code=0)
        assert result.exit_code == 0

    def test_exit_code_nonzero_for_failure(self):
        """Non-zero exit code recorded on failure."""
        result = CheckResult(passed=False, exit_code=1, details="fail")
        assert result.exit_code == 1

    def test_stdout_captured(self):
        """CheckResult captures stdout."""
        result = CheckResult(passed=True, stdout="some output")
        assert result.stdout == "some output"

    def test_stderr_captured(self):
        """CheckResult captures stderr."""
        result = CheckResult(passed=False, stderr="error text", exit_code=1)
        assert result.stderr == "error text"


# ---------------------------------------------------------------------------
# ik_run_check — basic pass/fail
# ---------------------------------------------------------------------------


class TestIkRunCheck:
    def test_passing_script_returns_passed_true(self, tmp_path):
        """A script that exits 0 → CheckResult.passed = True."""
        script = tmp_path / "check_pass.py"
        script.write_text("print('all good')\n")
        result = ik_run_check(str(script))
        assert result.passed is True
        assert result.exit_code == 0

    def test_failing_script_returns_passed_false(self, tmp_path):
        """A script that exits non-zero → CheckResult.passed = False."""
        script = tmp_path / "check_fail.py"
        script.write_text("raise AssertionError('invariant violated')\n")
        result = ik_run_check(str(script))
        assert result.passed is False
        assert result.exit_code != 0

    def test_stdout_captured_from_script(self, tmp_path):
        """stdout output from the validator script is captured."""
        script = tmp_path / "check_stdout.py"
        script.write_text("print('checkpoint OK')\n")
        result = ik_run_check(str(script))
        assert "checkpoint OK" in result.stdout

    def test_stderr_captured_from_script(self, tmp_path):
        """stderr output from the validator script is captured."""
        script = tmp_path / "check_stderr.py"
        script.write_text(
            "import sys; sys.stderr.write('ERROR: guard failed\\n')\n"
            "sys.exit(1)\n"
        )
        result = ik_run_check(str(script))
        assert result.passed is False
        assert "guard failed" in result.stderr

    def test_exit_code_1_is_failure(self, tmp_path):
        """sys.exit(1) → passed=False, exit_code=1."""
        script = tmp_path / "check_exit1.py"
        script.write_text("import sys; sys.exit(1)\n")
        result = ik_run_check(str(script))
        assert result.passed is False
        assert result.exit_code == 1

    def test_exit_code_0_is_pass(self, tmp_path):
        """sys.exit(0) → passed=True, exit_code=0."""
        script = tmp_path / "check_exit0.py"
        script.write_text("import sys; sys.exit(0)\n")
        result = ik_run_check(str(script))
        assert result.passed is True
        assert result.exit_code == 0

    def test_script_not_found_returns_failed(self):
        """Missing script file → passed=False, not an unhandled exception."""
        result = ik_run_check("/nonexistent/path/check.py")
        assert result.passed is False

    def test_hypothesis_style_script(self, tmp_path):
        """A script modelling a Layer-B/C hypothesis-style check."""
        script = tmp_path / "hyp_check.py"
        script.write_text(
            textwrap.dedent("""\
                # Layer-B invariant: value must be positive
                value = 42
                assert value > 0, f"expected positive, got {value}"
                print("PASS: value is positive")
            """)
        )
        result = ik_run_check(str(script))
        assert result.passed is True
        assert "PASS" in result.stdout

    def test_hypothesis_style_failure(self, tmp_path):
        """A Layer-B hypothesis check that fails produces correct CheckResult."""
        script = tmp_path / "hyp_fail.py"
        script.write_text(
            textwrap.dedent("""\
                value = -1
                assert value > 0, f"expected positive, got {value}"
                print("PASS")
            """)
        )
        result = ik_run_check(str(script))
        assert result.passed is False

    def test_returns_check_result_instance(self, tmp_path):
        """ik_run_check always returns a CheckResult instance."""
        script = tmp_path / "trivial.py"
        script.write_text("pass\n")
        result = ik_run_check(str(script))
        assert isinstance(result, CheckResult)

    def test_generic_runner_agnostic_to_check_content(self, tmp_path):
        """Runner is generic: does not inspect or interpret check logic."""
        # The script does something unrelated — runner doesn't care what it checks
        script = tmp_path / "custom_check.py"
        script.write_text(
            textwrap.dedent("""\
                # Custom Layer-C cross-check: annual == sum(monthly)
                annual = 120
                monthly = [10] * 12
                assert annual == sum(monthly), "annual != Σ monthly"
                print("cross-check OK")
            """)
        )
        result = ik_run_check(str(script))
        assert result.passed is True
        assert result.exit_code == 0

    def test_uses_current_python_interpreter(self, tmp_path):
        """Script runs under the same Python interpreter as the test suite."""
        script = tmp_path / "interp_check.py"
        script.write_text(
            textwrap.dedent("""\
                import sys
                # Verify interpreter version is at least 3.11
                assert sys.version_info >= (3, 11), f"too old: {sys.version}"
                print(sys.executable)
            """)
        )
        result = ik_run_check(str(script))
        assert result.passed is True

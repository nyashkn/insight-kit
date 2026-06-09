"""C13 — gate import purity.

Importing insight_kit.gate must NOT transitively load insight_kit.provenance.run
or insight_kit.provenance.claim.  Verified in a subprocess with a clean sys.modules
so no prior import in the test session can mask the violation.
"""
from __future__ import annotations

import subprocess
import sys

_PROBE = """\
import sys
import insight_kit.platform.gate  # noqa: F401 — side-effect import under test

forbidden = [
    "insight_kit.provenance.run",
    "insight_kit.provenance.claim",
]
loaded = [m for m in forbidden if m in sys.modules]
if loaded:
    raise AssertionError(
        f"C13 violated: gate import pulled in provenance modules: {loaded}"
    )
print("OK")
"""


def test_gate_import_does_not_pull_provenance_run_or_claim():
    """Import insight_kit.platform.gate in a fresh interpreter — provenance.run/.claim must stay out."""
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"C13 violated.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.stdout.strip() == "OK"

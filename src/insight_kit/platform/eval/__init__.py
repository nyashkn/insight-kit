"""insight_kit.platform.eval — score gate for analyst/critic run output.

Public surface:
    from insight_kit.platform.eval.score import score, CLAIM_ID_RE
                                                FINDINGS_MIN_BYTES, FINDINGS_MAX_BYTES
"""
from __future__ import annotations

from insight_kit.platform.eval.score import (
    CLAIM_ID_RE,
    FINDINGS_MAX_BYTES,
    FINDINGS_MIN_BYTES,
    score,
)

__all__ = ["score", "CLAIM_ID_RE", "FINDINGS_MIN_BYTES", "FINDINGS_MAX_BYTES"]

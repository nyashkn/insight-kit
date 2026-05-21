"""insight-kit · provenance-first agent insights primitives."""
from __future__ import annotations

from typing import TYPE_CHECKING

__version__ = "0.1.0a3"

__all__ = [
    "Claim",
    "ClaimTier",
    "Confidence",
    "Run",
    "__version__",
    "find_kit_root",
    "kit_config",
]

# C13: gate subpackage must NOT transitively load provenance.run or provenance.claim.
# All provenance re-exports are lazy via PEP 562 module-level __getattr__ so that
# `import insight_kit.gate` never pulls in insight_kit.provenance.run / .claim.

if TYPE_CHECKING:
    # Type checkers see these as normal imports; at runtime they go through __getattr__.
    from insight_kit.provenance.claim import Claim, ClaimTier, Confidence
    from insight_kit.provenance.root import find_kit_root, kit_config
    from insight_kit.provenance.run import Run


def __getattr__(name: str) -> object:
    if name in ("Claim", "ClaimTier", "Confidence"):
        from insight_kit.provenance.claim import Claim, ClaimTier, Confidence

        globals().update({"Claim": Claim, "ClaimTier": ClaimTier, "Confidence": Confidence})
        return globals()[name]
    if name == "Run":
        from insight_kit.provenance.run import Run

        globals()["Run"] = Run
        return Run
    if name in ("find_kit_root", "kit_config"):
        from insight_kit.provenance.root import find_kit_root, kit_config

        globals().update({"find_kit_root": find_kit_root, "kit_config": kit_config})
        return globals()[name]
    raise AttributeError(f"module 'insight_kit' has no attribute {name!r}")

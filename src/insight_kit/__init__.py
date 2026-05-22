"""insight-kit · L1 typed-record gate + provenance primitives.

T25 cutover (C13): the legacy page-D `Run` / `Claim` model is deleted. Records
now enter exclusively through the L1 gate (`insight_kit.gate`). The gate's
public surface — typed emit wrappers, RunState, finalizeRun — is re-exported
here for convenience.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

__version__ = "0.1.0a3"

__all__ = [
    "RunState",
    "__version__",
    "finalizeRun",
    "find_kit_root",
    "ik_claim_emit",
    "ik_intervention_emit",
    "ik_research_emit",
    "ik_skill_use_emit",
    "kit_config",
]

# Re-exports are lazy via PEP 562 module-level __getattr__. This keeps
# `import insight_kit` light and avoids importing pydantic / the gate eagerly
# for callers that only need kit-root discovery.

if TYPE_CHECKING:
    # Type checkers see these as normal imports; at runtime they go through __getattr__.
    from insight_kit.gate import (
        RunState,
        finalizeRun,
        ik_claim_emit,
        ik_intervention_emit,
        ik_research_emit,
        ik_skill_use_emit,
    )
    from insight_kit.provenance.root import find_kit_root, kit_config

_GATE_EXPORTS = frozenset(
    {
        "RunState",
        "finalizeRun",
        "ik_claim_emit",
        "ik_intervention_emit",
        "ik_research_emit",
        "ik_skill_use_emit",
    }
)


def __getattr__(name: str) -> object:
    if name in _GATE_EXPORTS:
        import insight_kit.gate as _gate

        value = getattr(_gate, name)
        globals()[name] = value
        return value
    if name in ("find_kit_root", "kit_config"):
        from insight_kit.provenance.root import find_kit_root, kit_config

        globals().update({"find_kit_root": find_kit_root, "kit_config": kit_config})
        return globals()[name]
    raise AttributeError(f"module 'insight_kit' has no attribute {name!r}")

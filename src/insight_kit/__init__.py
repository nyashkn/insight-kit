"""insight-kit · L1 typed-record gate + provenance primitives.

T25 cutover (C13): the legacy page-D `Run` / `Claim` model is deleted. Records
now enter exclusively through the L1 gate (`insight_kit.platform.gate`). The
gate's public surface — typed emit wrappers, RunState, finalizeRun — is
re-exported here for convenience.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import TYPE_CHECKING

# __version__ single source of truth = pyproject.toml [project].version, read at
# import time via installed package metadata. Falls back to "0.0.0+unknown" only
# when the package is not installed (e.g. running from a source tree without an
# editable install). This keeps __version__ from drifting out of sync with the build.
try:
    __version__ = _pkg_version("insight-kit")
except PackageNotFoundError:  # pragma: no cover - source-tree-without-install
    __version__ = "0.0.0+unknown"

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
    from insight_kit.libs.provenance.root import find_kit_root, kit_config
    from insight_kit.platform.gate import (
        RunState,
        finalizeRun,
        ik_claim_emit,
        ik_intervention_emit,
        ik_research_emit,
        ik_skill_use_emit,
    )

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
        import insight_kit.platform.gate as _gate

        value = getattr(_gate, name)
        globals()[name] = value
        return value
    if name in ("find_kit_root", "kit_config"):
        from insight_kit.libs.provenance.root import find_kit_root, kit_config

        globals().update({"find_kit_root": find_kit_root, "kit_config": kit_config})
        return globals()[name]
    raise AttributeError(f"module 'insight_kit' has no attribute {name!r}")

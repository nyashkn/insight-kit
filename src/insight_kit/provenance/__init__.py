"""Provenance primitives — kit-root discovery + config.

T25 cutover (C13): the legacy page-D model — `Run` (`provenance/run.py`) and the
`Claim` dataclass (`provenance/claim.py`) — is deleted. Records now enter through
the L1 gate (`insight_kit.gate`); see SPEC §C13. Kit-root discovery (`root.py`)
is kept + reused.
"""

from insight_kit.provenance.root import (
    bootstrap_is_stale,
    bootstrap_marker,
    check_kit_version_drift,
    find_kit_root,
    init_kit,
    kit_config,
)

__all__ = [
    "bootstrap_is_stale",
    "bootstrap_marker",
    "check_kit_version_drift",
    "find_kit_root",
    "init_kit",
    "kit_config",
]

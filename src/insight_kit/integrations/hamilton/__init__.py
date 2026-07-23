"""Hamilton adapter — bridge @node execution to the L1 gate (ik_claim_emit)."""

from insight_kit.integrations.hamilton.adapter import InsightKitHook, build_driver
from insight_kit.integrations.hamilton.catalog import (
    Catalog,
    MeasureSpec,
    catalog,
    format_catalog,
)

__all__ = [
    "Catalog",
    "InsightKitHook",
    "MeasureSpec",
    "build_driver",
    "catalog",
    "format_catalog",
]

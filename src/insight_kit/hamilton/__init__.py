"""Hamilton adapter — bridge @node execution to Run.emit_metric / Run.claim."""

from insight_kit.hamilton.adapter import InsightKitHook, build_driver

__all__ = ["InsightKitHook", "build_driver"]

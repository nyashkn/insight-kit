"""insight_kit.platform.observability — Laminar-shaped tracing helpers.

Optional dependency: requires `lmnr` (and its `opentelemetry` transitive
deps). Install via `pip install insight-kit[observability]`.

Public surface:
    from insight_kit.platform.observability.lmnr import (
        init_from_env, RunIdentity,
        emit_session_spans, score_check_span, read_capped,
    )
"""
from __future__ import annotations

from insight_kit.platform.observability.lmnr import (
    RunIdentity,
    emit_session_spans,
    init_from_env,
    read_capped,
    score_check_span,
)

__all__ = [
    "RunIdentity",
    "emit_session_spans",
    "init_from_env",
    "read_capped",
    "score_check_span",
]

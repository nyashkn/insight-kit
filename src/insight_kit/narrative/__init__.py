"""insight_kit.narrative — reusable prompt skeletons for analyst/critic runs.

Public surface:
    from insight_kit.narrative.analyst_prompt import (
        ANALYST_PROMPT_TEMPLATE, render_analyst_prompt,
    )
"""
from __future__ import annotations

from insight_kit.narrative.analyst_prompt import (
    ANALYST_PROMPT_TEMPLATE,
    render_analyst_prompt,
)

__all__ = ["ANALYST_PROMPT_TEMPLATE", "render_analyst_prompt"]

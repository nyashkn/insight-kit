"""T1 — RecordSchema: pydantic v2 discriminated union over four record types.

record_type discriminant selects one of:
  ClaimRecord | InterventionRecord | ResearchRecord | SkillUseRecord

Cites: V2, V8, C5.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class ClaimTier(StrEnum):
    """Tier enum for claim/intervention records (C7)."""

    draft = "draft"
    published = "published"


class FieldEntry(BaseModel):
    """One named field inside a claim's fields dict.

    value: the actual numeric or string value being asserted.
    fmt_hint: optional formatting hint for Evidence render (e.g. "%.1f%%", "$,.0f").
    """

    value: Any
    fmt_hint: str | None = None

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# ClaimRecord  (C6 — claim fields dict + tier + narrative ref)
# ---------------------------------------------------------------------------


class ClaimRecord(BaseModel):
    """A typed analytical assertion.

    fields: dict mapping field name → FieldEntry (value + fmt_hint).
    tier:   draft | published.
    audience: optional intended audience tag (e.g. "board", "ops").
    narrative_ref: optional path/id pointing to narrative.md for this claim.
    cites: list of research/skill_use record ids that informed this claim (I.cites).
    supersedes: id of the prior record this corrects (T6 seam, not yet enforced here).
    """

    record_type: Literal["claim"] = "claim"

    claim_id: str = Field(..., description="Stable ID matching ^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\\d{3,}$")
    fields: dict[str, FieldEntry] = Field(
        ..., description="Named values being asserted, each with optional fmt_hint."
    )
    tier: ClaimTier = ClaimTier.draft
    audience: str | None = None
    narrative_ref: str | None = None
    cites: list[str] = Field(default_factory=list)
    supersedes: str | None = None

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# InterventionRecord  (C12 — replaces initiatives_log.jsonl)
# ---------------------------------------------------------------------------


class IntentPayload(BaseModel):
    """What the agent decided to do."""

    description: str
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class RealizedPayload(BaseModel):
    """What actually happened when the intent was executed externally.

    status must be one of: applied | partial | failed  (V19).
    """

    status: Literal["applied", "partial", "failed"]
    details: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class InterventionRecord(BaseModel):
    """An outside-world action record.

    intent: what the agent decided to do.
    realized: the actual external result (nullable on draft — V19).
    """

    record_type: Literal["intervention"] = "intervention"

    intervention_id: str = Field(..., description="Stable ID for this intervention.")
    intent: IntentPayload
    realized: RealizedPayload | None = None
    tier: ClaimTier = ClaimTier.draft
    audience: str | None = None
    cites: list[str] = Field(default_factory=list)
    supersedes: str | None = None

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# ResearchRecord  (V20 — knowledge acquisition record)
# ---------------------------------------------------------------------------


class ResearchRecord(BaseModel):
    """A knowledge-acquisition record: external research.

    Untiered (knowledge only — V20).
    snapshot_ref: path/id pointing to the captured-results snapshot artifact.
    query: the research question or query string.
    source: data source identifier (URL, tool name, dataset id, etc.).
    timestamp: ISO-8601 string of when research was conducted.
    """

    record_type: Literal["research"] = "research"

    research_id: str = Field(..., description="Stable ID for this research record.")
    snapshot_ref: str = Field(..., description="Ref to captured results snapshot.")
    query: str
    source: str
    timestamp: str = Field(..., description="ISO-8601 timestamp of research.")
    cites: list[str] = Field(default_factory=list)
    supersedes: str | None = None

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# SkillUseRecord  (V20 — knowledge acquisition via tool/skill)
# ---------------------------------------------------------------------------


class SkillUseRecord(BaseModel):
    """A knowledge-acquisition record: tool/skill use.

    Untiered (knowledge only — V20).
    snapshot_ref: path/id pointing to the captured-results snapshot artifact.
    tool: name of the tool or skill used.
    source: data source or endpoint the tool queried.
    timestamp: ISO-8601 string of when the skill was invoked.
    """

    record_type: Literal["skill_use"] = "skill_use"

    skill_use_id: str = Field(..., description="Stable ID for this skill-use record.")
    snapshot_ref: str = Field(..., description="Ref to captured results snapshot.")
    tool: str
    source: str
    timestamp: str = Field(..., description="ISO-8601 timestamp of skill invocation.")
    cites: list[str] = Field(default_factory=list)
    supersedes: str | None = None

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# RecordSchema — discriminated union (C5)
# ---------------------------------------------------------------------------

RecordSchema = Annotated[
    ClaimRecord | InterventionRecord | ResearchRecord | SkillUseRecord,
    Field(discriminator="record_type"),
]
"""Pydantic v2 discriminated union over all four record types.

Use pydantic.TypeAdapter(RecordSchema).validate_python(data) to validate
an unknown record dict, or instantiate the typed subclass directly.
"""

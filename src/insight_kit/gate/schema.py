"""T1 — RecordSchema: pydantic v2 discriminated union over four record types.

record_type discriminant selects one of:
  ClaimRecord | InterventionRecord | ResearchRecord | SkillUseRecord

Cites: V2, V8, C5, V22.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class DataFingerprintSource(StrEnum):
    """V22 — provenance honesty for data_fingerprint.

    registered_input: fingerprint was derived from a real upstream input supplied
                      via input_data= at emit time.  Satisfies V6/V13.
    payload:          fallback — fingerprint was derived from the record's own
                      fields when no registered upstream input was supplied.
                      NOT input provenance; a published-tier claim/intervention
                      with this source cannot satisfy V6/V13 (T7 enforces rejection).
    """

    registered_input = "registered_input"
    payload = "payload"


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


class CoverageInfo(BaseModel):
    """V14 — input-coverage metadata for a claim.

    n: sample size of the claim's inputs (rows / observations behind the value).
    partial_period: True when the input window is an incomplete calendar period
                    (e.g. month-to-date treated as if it were a full month).

    Optional: when absent the gate cannot assess coverage. When present and
    "thin" (partial_period, or n < 30) a published claim MUST carry a
    coverage_warning or it is rejected at emit (T10/V14).
    """

    n: int | None = None
    partial_period: bool = False

    model_config = {"extra": "forbid"}


class SelectionParams(BaseModel):
    """V15 — explicit selection params for a claim.

    Date-window / baseline / filter / grain selections MUST be emitted as
    explicit, structured claim fields — never left implicit in prompt text
    (RT4: an agent-chosen window/filter must not cross the gate unrecorded).

    date_window: selected window, e.g. "2026-03-01/2026-03-31".
    baseline:    baseline period or baseline claim_id the value is measured against.
    grain:       aggregation grain, e.g. "month", "week", "day".
    filters:     dimension filters applied, e.g. {"channel": "meta"}.
    """

    date_window: str | None = None
    baseline: str | None = None
    grain: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)

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
    supersedes: id of the prior record this corrects (T6 — emit validates the target exists).
    coverage: optional input-coverage metadata (n, partial_period) — T10/V14.
    coverage_warning: warning text; a published claim with thin coverage
        (partial_period or n<30) must carry one or emit rejects (T10/V14).
    selection: optional explicit selection params (window/baseline/grain/filters) — T11/V15.
    data_fingerprint_source: V22 provenance honesty — set by emit, not caller.
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
    # T10/V14 — input coverage + the warning thin coverage requires.
    coverage: CoverageInfo | None = None
    coverage_warning: str | None = None
    # T11/V15 — explicit selection params (window / baseline / grain / filters).
    selection: SelectionParams | None = None
    # V22 — injected by _record_emit; callers must not set this manually.
    data_fingerprint_source: DataFingerprintSource = DataFingerprintSource.payload

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
    data_fingerprint_source: V22 provenance honesty — set by emit, not caller.
    """

    record_type: Literal["intervention"] = "intervention"

    intervention_id: str = Field(..., description="Stable ID for this intervention.")
    intent: IntentPayload
    realized: RealizedPayload | None = None
    tier: ClaimTier = ClaimTier.draft
    audience: str | None = None
    cites: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    # V22 — injected by _record_emit; callers must not set this manually.
    data_fingerprint_source: DataFingerprintSource = DataFingerprintSource.payload

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# ResearchRecord  (V20 — knowledge acquisition record)
# ---------------------------------------------------------------------------


class ResearchRecord(BaseModel):
    """A knowledge-acquisition record: external research.

    Untiered (knowledge only — V20).
    snapshot_ref: caller-facing origin label for the captured results
        (URL, dataset id, cache key) — descriptive, not load-bearing.
    snapshot_fingerprint: T22/V20 — sha256 of the captured-results snapshot
        that emit persisted under the record bundle. Injected by _record_emit;
        callers must not set it. THIS is the load-bearing provenance — it is
        folded into record_fingerprint, so the snapshot is content-addressed.
    query: the research question or query string.
    source: data source identifier (URL, tool name, dataset id, etc.).
    timestamp: ISO-8601 string of when research was conducted.
    data_fingerprint_source: V22 provenance honesty — set by emit, not caller.
    """

    record_type: Literal["research"] = "research"

    research_id: str = Field(..., description="Stable ID for this research record.")
    snapshot_ref: str = Field(..., description="Origin label for the captured results.")
    query: str
    source: str
    timestamp: str = Field(..., description="ISO-8601 timestamp of research.")
    cites: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    # T22/V20 — injected by _record_emit (sha256 of the persisted snapshot).
    snapshot_fingerprint: str | None = None
    # V22 — injected by _record_emit; callers must not set this manually.
    data_fingerprint_source: DataFingerprintSource = DataFingerprintSource.payload

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# SkillUseRecord  (V20 — knowledge acquisition via tool/skill)
# ---------------------------------------------------------------------------


class SkillUseRecord(BaseModel):
    """A knowledge-acquisition record: tool/skill use.

    Untiered (knowledge only — V20).
    snapshot_ref: caller-facing origin label for the captured results
        (endpoint, cache key) — descriptive, not load-bearing.
    snapshot_fingerprint: T22/V20 — sha256 of the captured-results snapshot
        that emit persisted under the record bundle. Injected by _record_emit;
        callers must not set it. Folded into record_fingerprint.
    tool: name of the tool or skill used.
    source: data source or endpoint the tool queried.
    timestamp: ISO-8601 string of when the skill was invoked.
    data_fingerprint_source: V22 provenance honesty — set by emit, not caller.
    """

    record_type: Literal["skill_use"] = "skill_use"

    skill_use_id: str = Field(..., description="Stable ID for this skill-use record.")
    snapshot_ref: str = Field(..., description="Origin label for the captured results.")
    tool: str
    source: str
    timestamp: str = Field(..., description="ISO-8601 timestamp of skill invocation.")
    cites: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    # T22/V20 — injected by _record_emit (sha256 of the persisted snapshot).
    snapshot_fingerprint: str | None = None
    # V22 — injected by _record_emit; callers must not set this manually.
    data_fingerprint_source: DataFingerprintSource = DataFingerprintSource.payload

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

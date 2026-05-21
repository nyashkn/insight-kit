"""insight-kit L1 typed-record gate.

Public API:
  Typed emit wrappers:
    ik_claim_emit, ik_intervention_emit, ik_research_emit, ik_skill_use_emit

  Schema (pydantic discriminated union):
    RecordSchema, ClaimRecord, InterventionRecord, ResearchRecord, SkillUseRecord

  Run accumulator:
    RunState, RecordRef, finalizeRun, ManifestError

  Key types:
    ClaimTier, FieldEntry, IntentPayload, RealizedPayload

Cites: C1, C5, I.emit, I.schema, I.run.
"""
from __future__ import annotations

from insight_kit.gate.emit import (
    ik_claim_emit,
    ik_intervention_emit,
    ik_research_emit,
    ik_skill_use_emit,
)
from insight_kit.gate.runstate import (
    ManifestError,
    RecordRef,
    RunState,
    finalizeRun,
)
from insight_kit.gate.schema import (
    ClaimRecord,
    ClaimTier,
    FieldEntry,
    IntentPayload,
    InterventionRecord,
    RealizedPayload,
    RecordSchema,
    ResearchRecord,
    SkillUseRecord,
)

__all__ = [
    "ClaimRecord",
    "ClaimTier",
    "FieldEntry",
    "IntentPayload",
    "InterventionRecord",
    "ManifestError",
    "RealizedPayload",
    "RecordRef",
    "RecordSchema",
    "ResearchRecord",
    "RunState",
    "SkillUseRecord",
    "finalizeRun",
    "ik_claim_emit",
    "ik_intervention_emit",
    "ik_research_emit",
    "ik_skill_use_emit",
]

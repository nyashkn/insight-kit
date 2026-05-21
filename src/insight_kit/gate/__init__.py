"""insight-kit L1 typed-record gate.

Public API:
  Typed emit wrappers:
    ik_claim_emit, ik_intervention_emit, ik_research_emit, ik_skill_use_emit

  Schema (pydantic discriminated union):
    RecordSchema, ClaimRecord, InterventionRecord, ResearchRecord, SkillUseRecord

  Run accumulator:
    RunState, RecordRef, finalizeRun, ManifestError

  Layer-B/C runner + cross-checks (I.runcheck):
    ik_run_check, CheckResult, check_annual_equals_monthly_sum, CrossCheckResult

  Feature catalog (V18):
    ik_feature_get, ProvisionalFeature

  Key types:
    ClaimTier, FieldEntry, CoverageInfo, SelectionParams, IntentPayload, RealizedPayload

Cites: C1, C5, I.emit, I.schema, I.run, I.runcheck, V14, V15, V18.
"""
from __future__ import annotations

from insight_kit.gate.emit import (
    ik_claim_emit,
    ik_intervention_emit,
    ik_research_emit,
    ik_skill_use_emit,
)
from insight_kit.gate.feature import (
    ProvisionalFeature,
    ik_feature_get,
)
from insight_kit.gate.runcheck import (
    CheckResult,
    CrossCheckResult,
    check_annual_equals_monthly_sum,
    ik_run_check,
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
    CoverageInfo,
    FieldEntry,
    IntentPayload,
    InterventionRecord,
    RealizedPayload,
    RecordSchema,
    ResearchRecord,
    SelectionParams,
    SkillUseRecord,
)

__all__ = [
    "CheckResult",
    "ClaimRecord",
    "ClaimTier",
    "CoverageInfo",
    "CrossCheckResult",
    "FieldEntry",
    "IntentPayload",
    "InterventionRecord",
    "ManifestError",
    "ProvisionalFeature",
    "RealizedPayload",
    "RecordRef",
    "RecordSchema",
    "ResearchRecord",
    "RunState",
    "SelectionParams",
    "SkillUseRecord",
    "check_annual_equals_monthly_sum",
    "finalizeRun",
    "ik_claim_emit",
    "ik_feature_get",
    "ik_intervention_emit",
    "ik_research_emit",
    "ik_run_check",
    "ik_skill_use_emit",
]

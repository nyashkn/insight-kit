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

  Post-hoc utility verdict on knowledge records (V21, I.events):
    ik_utility_verdict, UtilityVerdict

  Layer-D render audit (V12, I.audit):
    run_render_audit, audit_l5, audit_l6, load_claims_index, RenderedToken,
    ClaimFieldRef, RenderAdapter, AuditReport, VegaLiteAdapter

  Key types:
    ClaimTier, FieldEntry, CoverageInfo, SelectionParams, IntentPayload, RealizedPayload

Cites: C1, C5, I.emit, I.schema, I.run, I.runcheck, I.events, I.audit, V12, V14,
V15, V18, V21.
"""
from __future__ import annotations

from insight_kit.platform.gate.audit import (
    AuditReport,
    ClaimFieldRef,
    RenderAdapter,
    RenderedToken,
    audit_l5,
    audit_l6,
    load_claims_index,
    run_render_audit,
)
from insight_kit.platform.gate.emit import (
    ik_claim_emit,
    ik_intervention_emit,
    ik_research_emit,
    ik_skill_use_emit,
)
from insight_kit.platform.gate.feature import (
    ProvisionalFeature,
    ik_feature_get,
)
from insight_kit.platform.gate.render_adapters import VegaLiteAdapter
from insight_kit.platform.gate.runcheck import (
    CheckResult,
    CrossCheckResult,
    check_annual_equals_monthly_sum,
    ik_run_check,
)
from insight_kit.platform.gate.runstate import (
    ManifestError,
    RecordRef,
    RunState,
    finalizeRun,
)
from insight_kit.platform.gate.schema import (
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
from insight_kit.platform.gate.verdict import (
    UtilityVerdict,
    ik_utility_verdict,
)

__all__ = [
    "AuditReport",
    "CheckResult",
    "ClaimFieldRef",
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
    "RenderAdapter",
    "RenderedToken",
    "ResearchRecord",
    "RunState",
    "SelectionParams",
    "SkillUseRecord",
    "UtilityVerdict",
    "VegaLiteAdapter",
    "audit_l5",
    "audit_l6",
    "check_annual_equals_monthly_sum",
    "finalizeRun",
    "ik_claim_emit",
    "ik_feature_get",
    "ik_intervention_emit",
    "ik_research_emit",
    "ik_run_check",
    "ik_skill_use_emit",
    "ik_utility_verdict",
    "load_claims_index",
    "run_render_audit",
]

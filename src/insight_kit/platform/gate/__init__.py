"""insight-kit L1 typed-record gate.

Public API:
  Typed emit wrappers:
    ik_claim_emit, ik_intervention_emit, ik_research_emit, ik_skill_use_emit

  Schema (pydantic discriminated union):
    RecordSchema, ClaimRecord, InterventionRecord, ResearchRecord, SkillUseRecord

  Run accumulator:
    RunState, RecordRef, finalizeRun, ManifestError

  Layer-B/C runner + cross-checks (I.runcheck):
    ik_run_check, CheckResult, check_annual_equals_monthly_sum, CrossCheckResult,
    check_endpoint_coverage_gap, CheckEndpointCoverageResult

  Feature catalog (V18):
    ik_feature_get, ProvisionalFeature

  Post-hoc utility verdict on knowledge records (V21, I.events):
    ik_utility_verdict, UtilityVerdict

  Layer-D render audit (V12, I.audit):
    run_render_audit, audit_l5, audit_l6, load_claims_index, RenderedToken,
    ClaimFieldRef, RenderAdapter, AuditReport, VegaLiteAdapter,
    MarkdownVegaAdapter

  Gate-native render composer (T33, I.audit):
    compose_record, parse_refs, verify_chart_bindings, ComposeError,
    ChartBindingResult

  API-ingestion chain wrapper (T30, C12, I.cites, I.emit, V20, V22):
    ik_acquire, AcquireResult

  Available-endpoints index helpers (T31, I.cites, V20):
    endpoint_index_path, write_endpoint_index, read_endpoint_index

  Deterministic DAG lineage read-back (item 7, I.lineage):
    lineage_of, trace_to_rows, LineageTrace, LineageNotRecordedError

  Cross-run workspace substrate (I.workspace): dated run dirs, runs.jsonl
  manifest, claim history queries, persistent refuted-claim republish guard:
    new_run_dir, seal_run, list_runs, reindex_runs, claim_history, claim_by_id,
    standing_refutations, guard_republished_claims, guard_refuted_inputs
    (refutation contagion along input_claims), ClaimSighting, RunEntry,
    RepublishFinding, ContagionFinding, RunNotSealedError, WorkspaceNotFoundError

  Key types:
    ClaimTier, FieldEntry, CoverageInfo, SelectionParams, IntentPayload, RealizedPayload

Cites: C1, C5, I.emit, I.schema, I.run, I.runcheck, I.events, I.audit, V12, V14,
V15, V16, V18, V21, T30, T31, T32, T33.
"""

from __future__ import annotations

from insight_kit.platform.gate.acquire import (
    AcquireResult,
    ik_acquire,
)
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
from insight_kit.platform.gate.compose import (
    ChartBindingResult,
    ComposeError,
    compose_record,
    parse_refs,
    verify_chart_bindings,
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
from insight_kit.platform.gate.graph_query import (
    AdjacencyNode,
    GraphAdjacency,
    query_cites,
)
from insight_kit.platform.gate.lineage import (
    LineageNotRecordedError,
    LineageTrace,
    lineage_of,
    trace_to_rows,
)
from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter, VegaLiteAdapter
from insight_kit.platform.gate.runcheck import (
    CheckEndpointCoverageResult,
    CheckResult,
    CrossCheckResult,
    check_annual_equals_monthly_sum,
    check_coverage_from_run,
    check_endpoint_coverage_gap,
    check_ratio_identity,
    derive_used_endpoints,
    emit_reconciliation_critique,
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
from insight_kit.platform.gate.store import (
    endpoint_index_path,
    read_endpoint_index,
    write_endpoint_index,
)
from insight_kit.platform.gate.verdict import (
    UtilityVerdict,
    ik_utility_verdict,
)
from insight_kit.platform.gate.workspace import (
    ClaimSighting,
    ContagionFinding,
    RepublishFinding,
    RunEntry,
    RunNotSealedError,
    WorkspaceNotFoundError,
    claim_by_id,
    claim_history,
    guard_refuted_inputs,
    guard_republished_claims,
    list_runs,
    new_run_dir,
    reindex_runs,
    seal_run,
    standing_refutations,
)

__all__ = [
    "AcquireResult",
    "AdjacencyNode",
    "AuditReport",
    "ChartBindingResult",
    "CheckEndpointCoverageResult",
    "CheckResult",
    "ClaimFieldRef",
    "ClaimRecord",
    "ClaimSighting",
    "ClaimTier",
    "ComposeError",
    "ContagionFinding",
    "CoverageInfo",
    "CrossCheckResult",
    "FieldEntry",
    "GraphAdjacency",
    "IntentPayload",
    "InterventionRecord",
    "LineageNotRecordedError",
    "LineageTrace",
    "ManifestError",
    "MarkdownVegaAdapter",
    "ProvisionalFeature",
    "RealizedPayload",
    "RecordRef",
    "RecordSchema",
    "RenderAdapter",
    "RenderedToken",
    "RepublishFinding",
    "ResearchRecord",
    "RunEntry",
    "RunNotSealedError",
    "RunState",
    "SelectionParams",
    "SkillUseRecord",
    "UtilityVerdict",
    "VegaLiteAdapter",
    "WorkspaceNotFoundError",
    "audit_l5",
    "audit_l6",
    "check_annual_equals_monthly_sum",
    "check_coverage_from_run",
    "check_endpoint_coverage_gap",
    "check_ratio_identity",
    "claim_by_id",
    "claim_history",
    "compose_record",
    "derive_used_endpoints",
    "emit_reconciliation_critique",
    "endpoint_index_path",
    "finalizeRun",
    "guard_refuted_inputs",
    "guard_republished_claims",
    "ik_acquire",
    "ik_claim_emit",
    "ik_feature_get",
    "ik_intervention_emit",
    "ik_research_emit",
    "ik_run_check",
    "ik_skill_use_emit",
    "ik_utility_verdict",
    "lineage_of",
    "list_runs",
    "load_claims_index",
    "new_run_dir",
    "parse_refs",
    "query_cites",
    "read_endpoint_index",
    "reindex_runs",
    "run_render_audit",
    "seal_run",
    "standing_refutations",
    "trace_to_rows",
    "verify_chart_bindings",
    "write_endpoint_index",
]

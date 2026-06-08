"""T30 — Ergonomic acquire() wrapper for the research->skill_use->claim ingestion chain.

Composes the three typed emit wrappers (ik_research_emit, ik_skill_use_emit,
ik_claim_emit) into a single ergonomic call for the canonical API-ingestion
pattern:

  1. ik_research_emit  — the api-doc-search result (untiered knowledge, V20).
  2. ik_skill_use_emit — the api-data-extraction result (cites the research record).
  3. ik_claim_emit     — the analytic assertion (cites both research+skill_use,
                         input_data=api_extraction_result for V22 fingerprinting).

All three records are content-addressed.  Partial-write is impossible by
construction — each emit is atomic (V2) and uses the underlying _record_emit
gate unchanged.

Cites: C12, I.cites, I.emit, V20, V22, T30.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from insight_kit.platform.gate.emit import (
    ik_claim_emit,
    ik_research_emit,
    ik_skill_use_emit,
)
from insight_kit.platform.gate.runstate import RecordRef, RunState

# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class AcquireResult:
    """Return value from ik_acquire: the three linked records + their ids.

    research_ref:   RecordRef for the ik_research_emit record.
    skill_use_ref:  RecordRef for the ik_skill_use_emit record.
    claim_ref:      RecordRef for the ik_claim_emit record.
    research_id:    stable human-assigned research_id (NOT record_id).
    skill_use_id:   stable human-assigned skill_use_id.
    claim_id:       stable human-assigned claim_id.
    """

    research_ref: RecordRef
    skill_use_ref: RecordRef
    claim_ref: RecordRef
    research_id: str
    skill_use_id: str
    claim_id: str


# ---------------------------------------------------------------------------
# Public wrapper
# ---------------------------------------------------------------------------


def ik_acquire(
    research_id: str,
    skill_use_id: str,
    claim_id: str,
    api_search_result: dict[str, Any],
    api_extraction_result: dict[str, Any],
    claim_fields: dict[str, Any],
    *,
    # knowledge-record snapshot overrides (optional human-label refs)
    research_snapshot_ref: str | None = None,
    skill_use_snapshot_ref: str | None = None,
    # research-record fields
    research_query: str = "",
    research_source: str = "",
    research_timestamp: str | None = None,
    # skill_use-record fields
    skill_use_tool: str = "",
    skill_use_source: str = "",
    skill_use_timestamp: str | None = None,
    # claim fields
    claim_tier: str = "draft",
    claim_audience: str | None = None,
    claim_narrative_ref: str | None = None,
    claim_coverage: dict[str, Any] | None = None,
    claim_coverage_warning: str | None = None,
    claim_selection: dict[str, Any] | None = None,
    # run wiring
    run_state: RunState,
    run_dir: Path | None = None,
) -> AcquireResult:
    """Emit a research -> skill_use -> claim acquisition chain atomically.

    The three records are chained by cites edges:
      research      — snapshot=api_search_result, untiered (V20).
      skill_use     — snapshot=api_extraction_result, cites=[research.record_id].
      claim         — cites=[research.record_id, skill_use.record_id],
                      input_data=api_extraction_result (V22: registered_input).

    Args:
        research_id:           stable id for the research record.
        skill_use_id:          stable id for the skill_use record.
        claim_id:              stable claim_id (must match gate regex).
        api_search_result:     captured api-doc-search payload (research snapshot).
        api_extraction_result: captured api-data-extraction payload
                               (skill_use snapshot + claim input_data).
        claim_fields:          claim fields dict; accepts scalar, (value, fmt_hint)
                               tuple, or FieldEntry-dict per ik_claim_emit convention.
        research_snapshot_ref: human label for the research snapshot origin.
        skill_use_snapshot_ref: human label for the skill_use snapshot origin.
        research_query:        research query string (forwarded to ik_research_emit).
        research_source:       research source id (forwarded to ik_research_emit).
        research_timestamp:    ISO-8601 string; auto-UTC if None.
        skill_use_tool:        tool name (forwarded to ik_skill_use_emit).
        skill_use_source:      source endpoint (forwarded to ik_skill_use_emit).
        skill_use_timestamp:   ISO-8601 string; auto-UTC if None.
        claim_tier:            tier for the claim (default "draft").
        claim_audience:        optional audience tag.
        claim_narrative_ref:   optional narrative ref path/id.
        claim_coverage:        optional CoverageInfo dict.
        claim_coverage_warning: optional coverage_warning string.
        claim_selection:       optional SelectionParams dict.
        run_state:             mutable RunState accumulator for this run session.
        run_dir:               run directory; resolved from env if None.

    Returns:
        AcquireResult with RecordRef objects for all three records.

    Raises:
        LayerAValidationError — any emit-level guard fires (V2: no partial write
        for the failing step; prior successful steps remain on disk).
    """
    # 1. Research record — the api-doc-search snapshot.
    research_ref = ik_research_emit(
        research_id,
        research_snapshot_ref or f"api-search:{research_id}",
        research_query,
        research_source,
        snapshot=api_search_result,
        timestamp=research_timestamp,
        run_state=run_state,
        run_dir=run_dir,
    )

    # 2. Skill-use record — the api-data-extraction; cites the research record.
    skill_use_ref = ik_skill_use_emit(
        skill_use_id,
        skill_use_snapshot_ref or f"api-extract:{skill_use_id}",
        skill_use_tool,
        skill_use_source,
        snapshot=api_extraction_result,
        cites=[research_ref.record_id],
        timestamp=skill_use_timestamp,
        run_state=run_state,
        run_dir=run_dir,
    )

    # 3. Claim record — cites both knowledge records; registered input (V22).
    claim_ref = ik_claim_emit(
        claim_id,
        claim_fields,
        tier=claim_tier,
        audience=claim_audience,
        narrative_ref=claim_narrative_ref,
        cites=[research_ref.record_id, skill_use_ref.record_id],
        coverage=claim_coverage,
        coverage_warning=claim_coverage_warning,
        selection=claim_selection,
        run_state=run_state,
        run_dir=run_dir,
        input_data=api_extraction_result,
    )

    return AcquireResult(
        research_ref=research_ref,
        skill_use_ref=skill_use_ref,
        claim_ref=claim_ref,
        research_id=research_id,
        skill_use_id=skill_use_id,
        claim_id=claim_id,
    )

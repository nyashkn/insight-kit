"""T2 — Core _record_emit gate + typed wrappers.

Pipeline for every emit:
  1. Pydantic-validate payload against RecordSchema (discriminated union).
  2. Run applicable Layer-A validation/ guards (claim_id format, duplicate-in-run,
     T6 supersedes existence).
  3. On reject → raise, ZERO partial write, increment RunState.rejectionCount.
  4. Compute record_fingerprint + data_fingerprint.
  5. Inject fingerprints into the record dict.
  5a. T21 intervention reconciliation: a published intervention with no
      realized result → reject (V19).
  5b. T7 tier gate: if tier==published but fingerprint set incomplete or
      data_fingerprint_source==payload → downgrade to draft + record reason (V6,V22,C7).
  5c. T10 coverage gate: published claim with thin coverage + no warning →
      reject (V14).
  6. Write records/{id}/record.json (immutable, C3).
  7. Append projection row to records.jsonl.
  8. Append claim projection row to claims.jsonl (claim records only).
  9. Register RecordRef in RunState.records.

Typed wrappers:
  ik_claim_emit       — ergonomic claim entry point (widely referenced, I.emit)
  ik_intervention_emit
  ik_research_emit
  ik_skill_use_emit

Cites: V1, V2, V3, V6, V14, V19, V22, C7, I.emit.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from insight_kit.gate.fingerprint import (
    data_fingerprint as _data_fingerprint,
)
from insight_kit.gate.fingerprint import (
    record_fingerprint as _record_fingerprint,
)
from insight_kit.gate.fingerprint import (
    record_id_from_fingerprint,
)
from insight_kit.gate.runstate import RecordRef, RunState
from insight_kit.gate.schema import (
    RecordSchema,
)
from insight_kit.gate.store import (
    append_claims_row,
    append_index_row,
    resolve_run_dir,
    write_record,
)
from insight_kit.validation import ValidationError as LayerAValidationError

# Pydantic TypeAdapter for RecordSchema discriminated union
_RECORD_ADAPTER: TypeAdapter[Any] = TypeAdapter(RecordSchema)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_layer_a_guards(
    record: Any,
    run_state: RunState,
    run_dir: Path | None = None,
) -> None:
    """Run applicable Layer-A guards from insight_kit.validation.

    Guards that apply to claims:
      - check_claim_id_format  (claim_id must match the regex)
      - check_claim_id_unique_in_run  (no duplicate within session)

    Guards that apply to all record types:
      - check_supersedes_exists  (T6 — V3: superseded record must exist in run dir)

    Raises LayerAValidationError on failure (V2 — no partial write).
    """
    from insight_kit.validation import (
        check_claim_id_format,
        check_claim_id_unique_in_run,
    )

    if record.record_type == "claim":
        check_claim_id_format(record.claim_id)

        # claim_ids from records already emitted in this run session
        check_claim_id_unique_in_run(record.claim_id, _claim_ids_in_run(run_state))

    # T6/V3 — validate supersedes target exists in run dir
    supersedes = getattr(record, "supersedes", None)
    if supersedes is not None and run_dir is not None:
        _check_supersedes_exists(supersedes, run_dir)


def _check_supersedes_exists(supersedes_id: str, run_dir: Path) -> None:
    """T6/V3 — verify the superseded record exists in the run dir.

    Raises LayerAValidationError if the target record.json is not found.
    """
    from insight_kit.gate.store import record_path

    target = record_path(run_dir, supersedes_id)
    if not target.exists():
        raise LayerAValidationError(
            rule_id="supersedes-not-found",
            message=(
                f"supersedes={supersedes_id!r} does not correspond to any existing "
                f"record in the run directory. Records are immutable post-emit (V3) — "
                f"a supersession edge must point to a record that exists."
            ),
            suggestion=(
                f"Emit the record you intend to supersede first, then emit the "
                f"correcting record with supersedes={supersedes_id!r}. "
                f"Or check the record_id is correct."
            ),
        )


_PARQUET_EXTENSIONS: tuple[bytes, ...] = (b".pq", b".parquet")
_PARQUET_STR_EXTENSIONS: tuple[str, ...] = (".pq", ".parquet")


def _check_raw_parquet_path(input_data: bytes | dict[str, Any] | None) -> None:
    """T9/V13 — Reject raw agent-supplied parquet file paths as inputs.

    Raw file paths are detectable as bytes that look like a file system path
    ending in .pq / .parquet, or a dict with a path_ref value ending in those
    extensions. These are NOT registered upstream fingerprints and must be
    rejected so the gate enforces real input provenance (V13, V22).

    Raises LayerAValidationError(rule_id='raw-parquet-path') on detection.
    """
    if input_data is None:
        return

    if isinstance(input_data, (bytes, bytearray)):
        stripped = input_data.strip()
        if any(stripped.endswith(ext) for ext in _PARQUET_EXTENSIONS):
            raise LayerAValidationError(
                rule_id="raw-parquet-path",
                message=(
                    f"input_data appears to be a raw file path: {stripped!r}. "
                    "Raw agent-supplied parquet paths are rejected at emit (V13). "
                    "Every input must carry a fingerprint from a registered upstream "
                    "(h_dlt source or @feature node), not a bare file path."
                ),
                suggestion=(
                    "Pass the actual file contents as bytes, or use a registered upstream "
                    "fingerprint dict with 'upstream_fingerprint' key. "
                    "Do not pass a file path string as input_data."
                ),
            )

    if isinstance(input_data, dict):
        for val in input_data.values():
            if isinstance(val, str) and any(
                val.strip().endswith(ext) for ext in _PARQUET_STR_EXTENSIONS
            ):
                raise LayerAValidationError(
                    rule_id="raw-parquet-path",
                    message=(
                        f"input_data dict contains a raw parquet file path: {val!r}. "
                        "Raw agent-supplied parquet paths are rejected at emit (V13). "
                        "Use a registered upstream fingerprint instead."
                    ),
                    suggestion=(
                        "Replace the path_ref with an 'upstream_fingerprint' from a "
                        "registered h_dlt source or @feature node."
                    ),
                )


_REQUIRED_FP_KEYS: frozenset[str] = frozenset(
    {"data_fingerprint", "code_fingerprint", "agent_version", "env_fingerprint"}
)


def _apply_tier_gate(
    record_dict: dict[str, Any],
    run_dir: Path,
) -> None:
    """T7/V6/V22/C7 — Published tier gate: downgrade to draft if fingerprints incomplete.

    A published-tier claim or intervention requires ALL of:
      - data_fingerprint, code_fingerprint, agent_version, env_fingerprint present in run.json
      - data_fingerprint_source == "registered_input"

    If either condition fails, the tier is downgraded to "draft" and the reason is
    stored in "tier_downgrade_reason". This is NOT a rejection — the record still emits.

    Applies only to record types with tier (claim, intervention).
    Draft records and untiered records (research, skill_use) are not affected.
    """
    if record_dict.get("tier") != "published":
        return  # only applies to published
    if record_dict.get("record_type") not in ("claim", "intervention"):
        return  # only tiered types

    reasons: list[str] = []

    # Check data_fingerprint_source (V22)
    if record_dict.get("data_fingerprint_source") != "registered_input":
        reasons.append(
            "data_fingerprint_source is 'payload' (self-derived) — "
            "published-tier requires registered_input (V22)"
        )

    # Check run.json has full fingerprint set (V6)
    run_json_path = run_dir / "run.json"
    if not run_json_path.exists():
        reasons.append(
            "run.json not found — published-tier requires full fingerprint set in run.json (V6)"
        )
    else:
        try:
            run_meta = json.loads(run_json_path.read_text(encoding="utf-8"))
        except Exception:
            run_meta = {}
        missing = _REQUIRED_FP_KEYS - set(run_meta.keys())
        if missing:
            reasons.append(
                f"run.json missing required fingerprint keys: {sorted(missing)} (V6)"
            )

    if reasons:
        record_dict["tier"] = "draft"
        record_dict["tier_downgrade_reason"] = "; ".join(reasons)


_MIN_SAMPLE_N: int = 30


def _check_coverage_warning(record_dict: dict[str, Any]) -> None:
    """T10/V14 — published claim with thin coverage must carry a coverage_warning.

    "Thin" coverage = the claim declares a CoverageInfo whose inputs are
    partial-period OR have n < 30. A published-tier claim that is thin and lacks
    a non-empty coverage_warning is REJECTED at emit (V14) — unlike the tier gate
    (T7) this is a hard reject, not a downgrade.

    Runs AFTER the tier gate, so a record already downgraded published->draft is
    no longer subject to this check. Claims that declare no CoverageInfo are not
    enforced — the gate can only assess coverage it was told about.

    Raises LayerAValidationError(rule_id='coverage-warning-missing') on failure.
    """
    if record_dict.get("record_type") != "claim":
        return
    if record_dict.get("tier") != "published":
        return
    coverage = record_dict.get("coverage")
    if not coverage:
        return  # no coverage declared → gate cannot assess

    n = coverage.get("n")
    thin_reasons: list[str] = []
    if coverage.get("partial_period"):
        thin_reasons.append("inputs are partial-period")
    if n is not None and n < _MIN_SAMPLE_N:
        thin_reasons.append(f"sample size n={n} is below {_MIN_SAMPLE_N}")
    if not thin_reasons:
        return  # coverage is adequate

    if not (record_dict.get("coverage_warning") or "").strip():
        raise LayerAValidationError(
            rule_id="coverage-warning-missing",
            message=(
                "Published-tier claim has thin input coverage ("
                + "; ".join(thin_reasons)
                + ") but carries no coverage_warning. V14 — a published claim "
                "whose inputs are partial-period or n<30 must declare the "
                "matching coverage_warning or it is rejected at emit."
            ),
            suggestion=(
                "Add a coverage_warning describing the limitation (e.g. "
                "'March figure is month-to-date, not a full month'), or emit "
                "the claim at tier='draft'."
            ),
        )


_REALIZED_STATUSES: frozenset[str] = frozenset({"applied", "partial", "failed"})


def _check_intervention_reconciliation(record_dict: dict[str, Any]) -> None:
    """T21/V19 — a published intervention must carry a reconciled `realized` result.

    V19: emit of a published-tier intervention is rejected unless `realized` is
    present and `realized.status` ∈ {applied, partial, failed}. A draft
    intervention may emit with realized=None (the external action is still
    pending). Because records are immutable (V3), "promoting" a draft
    intervention to published means emitting a NEW record (typically with a
    supersedes edge) at tier='published' — that new emit hits this same gate, so
    the draft→published promotion lock needs no separate machinery.

    intent≠realized is NOT a reject — a realized.status of 'partial' or 'failed'
    passes. The invariant is *reconciliation captured*, not *action succeeded*.

    Runs on the caller's DECLARED tier, BEFORE the T7 tier gate — the reject is
    on the intent to publish. (Contrast _check_coverage_warning, which runs
    AFTER the tier downgrade because a downgraded draft claim is legitimately
    allowed to be thin.)

    Hard reject — raises LayerAValidationError, never downgrades.
    """
    if record_dict.get("record_type") != "intervention":
        return
    if record_dict.get("tier") != "published":
        return  # draft interventions may carry realized=None (action pending)

    realized = record_dict.get("realized")
    if realized is None:
        raise LayerAValidationError(
            rule_id="intervention-unreconciled",
            message=(
                "Published-tier intervention has no `realized` result. V19 — a "
                "published intervention must record the actual external outcome "
                "(realized.status ∈ {applied, partial, failed}); an intervention "
                "whose action is still pending stays at tier='draft'."
            ),
            suggestion=(
                "Emit the intervention at tier='draft' until the external action "
                "completes, then emit a published record (with a supersedes edge "
                "to the draft) carrying the realized result."
            ),
        )
    # realized present — pydantic (RealizedPayload) already constrains status to
    # a valid Literal; this is a defensive re-check of the explicit V19 contract.
    if realized.get("status") not in _REALIZED_STATUSES:
        raise LayerAValidationError(
            rule_id="intervention-unreconciled",
            message=(
                f"Published-tier intervention realized.status is "
                f"{realized.get('status')!r}; V19 requires it ∈ "
                f"{sorted(_REALIZED_STATUSES)}."
            ),
            suggestion="Set realized.status to one of: applied, partial, failed.",
        )


def _claim_ids_in_run(run_state: RunState) -> set[str]:
    """Extract claim_ids from RunState.records metadata.

    We attach claim_id as an attribute on RecordRef for claims so this is fast.
    """
    ids: set[str] = set()
    for ref in run_state.records:
        if ref.record_type == "claim":
            # claim_id stored as extra attr on RecordRef (set by _record_emit)
            cid = getattr(ref, "_claim_id", None)
            if cid:
                ids.add(cid)
    return ids


# ---------------------------------------------------------------------------
# Core gate
# ---------------------------------------------------------------------------


def _record_emit(
    payload: dict[str, Any],
    run_state: RunState,
    run_dir: Path | None = None,
    input_data: bytes | dict[str, Any] | None = None,
) -> RecordRef:
    """Core typed-record gate.

    Args:
        payload:    raw dict to validate against RecordSchema.
        run_state:  mutable accumulator for this run session.
        run_dir:    run directory; resolved from INSIGHT_KIT_RUN_DIR if None.
        input_data: optional raw inputs for data_fingerprint (V4).
                   If None, fingerprints the payload itself (draft convenience).

    Returns RecordRef on success.
    Raises on validation failure — ZERO partial write (V2).
    """
    # --- Step 1: Pydantic validation ---
    try:
        record = _RECORD_ADAPTER.validate_python(payload)
    except PydanticValidationError as exc:
        run_state.rejectionCount += 1
        raise LayerAValidationError(
            rule_id="schema-validation",
            message=f"RecordSchema validation failed: {exc}",
            suggestion="Fix the payload fields to match the schema for the given record_type.",
        ) from exc

    # Resolve run_dir early so Layer-A guards (T6 supersedes check) can use it.
    resolved_dir = resolve_run_dir(run_dir)

    # --- Step 2: Layer-A guards ---
    try:
        _run_layer_a_guards(record, run_state, run_dir=resolved_dir)
    except LayerAValidationError:
        run_state.rejectionCount += 1
        raise  # re-raise unchanged — caller sees the structured ValidationError

    # --- Step 2c: T9/V13 input-provenance check ---
    # Reject raw parquet file paths passed as input_data (V13, V22, C8).
    # Must be BEFORE storage (zero partial write) and before fingerprinting.
    try:
        _check_raw_parquet_path(input_data)
    except LayerAValidationError:
        run_state.rejectionCount += 1
        raise

    # --- Steps 3-5: Fingerprint ---
    record_dict = record.model_dump(mode="json")

    # V22 — data_fingerprint_source honesty: distinguish real input provenance from
    # self-derived fallback. "payload" = fallback over record's own fields; NOT input
    # provenance. T7 checks the source, never mere presence of data_fingerprint.
    if input_data is not None:
        dfp = _data_fingerprint(input_data)
        record_dict["data_fingerprint_source"] = "registered_input"
    else:
        dfp = _data_fingerprint(record_dict)
        record_dict["data_fingerprint_source"] = "payload"
    record_dict["data_fingerprint"] = dfp

    # --- Step 5a: T21/V19 intervention reconciliation gate ---
    # Runs on the caller's DECLARED tier, BEFORE the T7 tier gate — a published
    # intervention with no reconciled `realized` result is rejected outright
    # (zero partial write, V2). This also enforces the draft→published promotion
    # lock: promotion is a fresh emit and hits this same check.
    try:
        _check_intervention_reconciliation(record_dict)
    except LayerAValidationError:
        run_state.rejectionCount += 1
        raise

    # --- Step 5b: T7 Tier gate (V6, V22, C7) ---
    # Must run AFTER data_fingerprint_source is set, BEFORE record_fingerprint.
    # Downgrade mutates record_dict["tier"] and adds "tier_downgrade_reason" if needed.
    _apply_tier_gate(record_dict, resolved_dir)

    # --- Step 5c: T10/V14 coverage-warning gate ---
    # After the tier gate (a downgraded record is no longer 'published'), and
    # before fingerprint + storage so a reject is zero-partial-write (V2).
    try:
        _check_coverage_warning(record_dict)
    except LayerAValidationError:
        run_state.rejectionCount += 1
        raise

    # record_fingerprint: sha256 of the canonical record dict (includes tier + downgrade reason
    # so a downgraded record has a different fingerprint than the same record at published).
    rfp = _record_fingerprint(record_dict)
    record_dict["record_fingerprint"] = rfp

    # Derive content-addressed record id
    record_id = record_id_from_fingerprint(rfp)

    # --- Steps 6-8: Storage ---
    # resolved_dir was already computed above (before Layer-A guards).
    # V2 — content-address collision: translate FileExistsError into a structured
    # ValidationError and increment rejectionCount (duplicate record is a schema reject).
    try:
        write_record(resolved_dir, record_id, record_dict)
    except FileExistsError as exc:
        run_state.rejectionCount += 1
        raise LayerAValidationError(
            rule_id="record-duplicate",
            message=(
                f"A record with record_id={record_id!r} already exists on disk "
                "(content-address collision — identical payload was already emitted). "
                "Records are immutable post-emit (V3)."
            ),
            suggestion=(
                "If this is a correction, create a new record with a 'supersedes' edge "
                "pointing to the prior record_id instead of re-emitting the same content."
            ),
        ) from exc
    append_index_row(resolved_dir, record_dict, record_id)
    append_claims_row(resolved_dir, record_dict, record_id)

    # --- Step 9: Register in RunState ---
    ref = RecordRef(
        record_id=record_id,
        record_type=record_dict["record_type"],
        record_fingerprint=rfp,
        run_dir=resolved_dir,
    )
    # Attach claim_id for duplicate-in-run guard
    if record.record_type == "claim":
        object.__setattr__(ref, "_claim_id", record.claim_id)

    run_state.records.append(ref)
    return ref


# ---------------------------------------------------------------------------
# Typed wrappers (I.emit)
# ---------------------------------------------------------------------------


def ik_claim_emit(
    claim_id: str,
    fields: dict[str, Any | tuple[Any, str | None]],
    *,
    tier: str = "draft",
    audience: str | None = None,
    narrative_ref: str | None = None,
    cites: list[str] | None = None,
    supersedes: str | None = None,
    coverage: dict[str, Any] | None = None,
    coverage_warning: str | None = None,
    selection: dict[str, Any] | None = None,
    run_state: RunState,
    run_dir: Path | None = None,
    input_data: bytes | dict[str, Any] | None = None,
) -> RecordRef:
    """Ergonomic claim emit wrapper (widely referenced, I.emit).

    `fields` accepts two forms for each entry:
      - value only:        {"revenue": 123456}
      - value + fmt_hint:  {"revenue": (123456, "$,.0f")}
      - FieldEntry dict:   {"revenue": {"value": 123456, "fmt_hint": "$,.0f"}}

    All forms normalised to FieldEntry before validation.

    coverage / coverage_warning — T10/V14: a published claim with thin coverage
    (coverage={"partial_period": True} or coverage={"n": <30}) is rejected at
    emit unless coverage_warning is set.

    selection — T11/V15: explicit window/baseline/grain/filters params; emit
    them as structured fields, never implicit in prose.
    """
    # Normalise fields
    normalised: dict[str, dict[str, Any]] = {}
    for name, v in fields.items():
        if isinstance(v, tuple) and len(v) == 2:
            normalised[name] = {"value": v[0], "fmt_hint": v[1]}
        elif isinstance(v, dict) and "value" in v:
            normalised[name] = v
        else:
            normalised[name] = {"value": v, "fmt_hint": None}

    payload: dict[str, Any] = {
        "record_type": "claim",
        "claim_id": claim_id,
        "fields": normalised,
        "tier": tier,
    }
    if audience is not None:
        payload["audience"] = audience
    if narrative_ref is not None:
        payload["narrative_ref"] = narrative_ref
    if cites:
        payload["cites"] = cites
    if supersedes is not None:
        payload["supersedes"] = supersedes
    if coverage is not None:
        payload["coverage"] = coverage
    if coverage_warning is not None:
        payload["coverage_warning"] = coverage_warning
    if selection is not None:
        payload["selection"] = selection

    return _record_emit(payload, run_state=run_state, run_dir=run_dir, input_data=input_data)


def ik_intervention_emit(
    intervention_id: str,
    intent: dict[str, Any],
    *,
    realized: dict[str, Any] | None = None,
    tier: str = "draft",
    audience: str | None = None,
    cites: list[str] | None = None,
    supersedes: str | None = None,
    run_state: RunState,
    run_dir: Path | None = None,
    input_data: bytes | dict[str, Any] | None = None,
) -> RecordRef:
    """Typed intervention emit wrapper.

    intent:   dict with at minimum {"description": "..."}.
    realized: dict with {"status": "applied|partial|failed", ...} or None for draft.
    """
    payload: dict[str, Any] = {
        "record_type": "intervention",
        "intervention_id": intervention_id,
        "intent": intent,
        "tier": tier,
    }
    if realized is not None:
        payload["realized"] = realized
    if audience is not None:
        payload["audience"] = audience
    if cites:
        payload["cites"] = cites
    if supersedes is not None:
        payload["supersedes"] = supersedes

    return _record_emit(payload, run_state=run_state, run_dir=run_dir, input_data=input_data)


def ik_research_emit(
    research_id: str,
    snapshot_ref: str,
    query: str,
    source: str,
    *,
    timestamp: str | None = None,
    cites: list[str] | None = None,
    supersedes: str | None = None,
    run_state: RunState,
    run_dir: Path | None = None,
    input_data: bytes | dict[str, Any] | None = None,
) -> RecordRef:
    """Typed research emit wrapper.

    timestamp: ISO-8601 string; defaults to current UTC time if not provided.
              Auto-timestamp makes the record non-deterministic by design —
              pass an explicit timestamp for a reproducible fingerprint.
    """
    payload: dict[str, Any] = {
        "record_type": "research",
        "research_id": research_id,
        "snapshot_ref": snapshot_ref,
        "query": query,
        "source": source,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }
    if cites:
        payload["cites"] = cites
    if supersedes is not None:
        payload["supersedes"] = supersedes

    return _record_emit(payload, run_state=run_state, run_dir=run_dir, input_data=input_data)


def ik_skill_use_emit(
    skill_use_id: str,
    snapshot_ref: str,
    tool: str,
    source: str,
    *,
    timestamp: str | None = None,
    cites: list[str] | None = None,
    supersedes: str | None = None,
    run_state: RunState,
    run_dir: Path | None = None,
    input_data: bytes | dict[str, Any] | None = None,
) -> RecordRef:
    """Typed skill-use emit wrapper.

    timestamp: ISO-8601 string; defaults to current UTC time if not provided.
              Auto-timestamp makes the record non-deterministic by design —
              pass an explicit timestamp for a reproducible fingerprint.
    """
    payload: dict[str, Any] = {
        "record_type": "skill_use",
        "skill_use_id": skill_use_id,
        "snapshot_ref": snapshot_ref,
        "tool": tool,
        "source": source,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }
    if cites:
        payload["cites"] = cites
    if supersedes is not None:
        payload["supersedes"] = supersedes

    return _record_emit(payload, run_state=run_state, run_dir=run_dir, input_data=input_data)

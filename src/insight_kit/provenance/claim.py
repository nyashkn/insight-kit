"""Claim — typed, cite-able, falsifiable unit. v2 schema per docs/helpers/v2/."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ClaimTier = Literal[
    "raw",          # passthrough from source
    "derived",      # analyst-computed
    "critic",       # critic verdict
    "initiative",   # proposed action + impact projection
    "viz",          # chart spec
    "counterfactual",  # predicted behavior under alternate conditions
    "etl_raw",      # bronze
    "etl_clean",    # silver
    "etl_metric",   # gold
]

Confidence = Literal["high", "medium", "low", "speculative"]
ClaimStatus = Literal["proposed", "supported", "disputed", "refuted", "superseded", "retired"]


@dataclass
class ClaimValue:
    n: float | int | str | None = None
    unit: str | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    ci_method: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Claim:
    """Structured cite-able claim. See docs/helpers/v2/05_claim_schema.md."""

    # identity
    claim_id: str
    statement: str
    tier: ClaimTier = "derived"
    version: int = 1

    # content
    value: ClaimValue | None = None
    metric_id: str | None = None
    period: str | None = None  # ISO interval

    # provenance
    run_id: str | None = None
    node_id: str | None = None
    query_path: str | None = None
    input_datasets: list[str] = field(default_factory=list)
    input_claims: list[str] = field(default_factory=list)
    code_sha: str | None = None
    script_sha: str | None = None
    evidence_ref: str | None = None  # legacy v1 compat

    # agent
    agent_id: str | None = None
    model: str | None = None
    prompt_sha: str | None = None
    signet_ref: str | None = None

    # epistemics
    confidence: Confidence = "medium"
    confidence_reason: str | None = None
    assumptions: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    # lifecycle
    status: ClaimStatus = "proposed"
    supports: list[str] = field(default_factory=list)
    refutes: list[str] = field(default_factory=list)
    supersedes: str | None = None
    superseded_by: str | None = None

    # initiative tier only
    initiative: dict[str, Any] | None = None

    # counterfactual tier only
    counterfactual_predicate: str | None = None
    counterfactual_test_at: str | None = None

    # annotations + reviews (append-only)
    annotations: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)

    # legacy
    cites: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        if self.value is not None:
            d["value"] = self.value.to_json()
        # drop None top-level fields for compactness, keep empty lists for stability
        return {
            k: v for k, v in d.items()
            if v is not None and not (isinstance(v, list) and len(v) == 0 and k not in {"input_claims", "supports"})
        }

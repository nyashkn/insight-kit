"""Layer-A real-time validation guards.

Fires at emit time (Run.claim, Run.ingest_external). Raises ValidationError
with rule_id + suggestion so the calling agent can self-correct in the same Run.
"""
from __future__ import annotations

import re

# ---------- error class ----------

CLAIM_ID_REGEX = re.compile(r"^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\d{3,}$")


class ValidationError(ValueError):
    """Structured validation failure with rule_id and suggestion."""

    def __init__(self, rule_id: str, message: str, suggestion: str | None = None) -> None:
        self.rule_id = rule_id
        self.suggestion = suggestion
        full = f"[{rule_id}] {message}"
        if suggestion:
            full += f" Suggestion: {suggestion}"
        super().__init__(full)


# ---------- rule implementations ----------


def check_claim_id_format(claim_id: str) -> None:
    """Rule: claim-id-format.

    claim_id must match ^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\\d{3,}$.
    """
    if not CLAIM_ID_REGEX.match(claim_id):
        raise ValidationError(
            rule_id="claim-id-format",
            message=(
                f"claim_id={claim_id!r} does not match "
                r"^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\d{3,}$"
            ),
            suggestion=(
                f"claim_id={claim_id!r} must match "
                r"^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\d{3,}$. "
                "Example: 'TEST-D-001'"
            ),
        )


def check_claim_id_namespace(claim_id: str, namespace: str) -> None:
    """Rule: claim-id-namespace.

    claim_id must start with ``<namespace>-``.
    """
    if not claim_id.startswith(f"{namespace}-"):
        raise ValidationError(
            rule_id="claim-id-namespace",
            message=(
                f"claim_id={claim_id!r} must start with namespace {namespace!r}-"
            ),
            suggestion=(
                f"claim_id={claim_id!r} must start with {namespace!r}-. "
                f"Example: '{namespace}-D-001'"
            ),
        )


def check_critic_edges(
    tier: str,
    supports: list[str] | None,
    refutes: list[str] | None,
) -> None:
    """Rule: critic-requires-edge.

    A claim with tier='critic' must declare at least one supports or refutes edge.
    """
    if tier == "critic":
        has_supports = bool(supports)
        has_refutes = bool(refutes)
        if not has_supports and not has_refutes:
            raise ValidationError(
                rule_id="critic-requires-edge",
                message="critic-tier claim must have at least one supports or refutes edge",
                suggestion="critic-tier claim must declare supports=[...] or refutes=[...]",
            )


def check_external_caveats(caveats: list[str] | None) -> None:
    """Rule: external-requires-caveats.

    ingest_external() results must have non-empty caveats.
    Raises if explicit empty list passed; defaults are applied upstream.
    """
    if caveats is not None and len(caveats) == 0:
        raise ValidationError(
            rule_id="external-requires-caveats",
            message="ingest_external requires non-empty caveats list",
            suggestion="ingest_external requires non-empty caveats. "
            "Default: ['external_source','non_audited']",
        )

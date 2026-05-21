"""T16 — Layer-D render audit: L5 token→claim join + L6 prose lint (V12, I.audit).

The render audit is the downstream half of the claim loop — it verifies that
what a user finally SEES is backed by gate-emitted claims:

  L5 (V9) — every numeric token in a rendered artifact resolves to a claim
            field in the claims projection. A number on the page bound to no
            claim ("orphan") fails the audit.
  L6 (V8) — claim narrative.md prose carries zero bare numeric literals; every
            number is a claim field reference (<ClaimNum>/<ClaimChart>).

Gate-owned and CI-blocking on published / audience:board (V12).

Backend-agnostic by construction: L5 operates on a normalized RenderedToken
stream, never on raw HTML/JSON. A RenderAdapter (one thin module per backend —
Vega-Lite, Evidence, Superset, Lightdash, ...) turns a concrete render artifact
into RenderedTokens. This audit core never changes when a backend is added.

Cites: V8, V9, V12, I.audit.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Normalized render contract — the seam between backends and the audit core
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimFieldRef:
    """A render token's declared binding to a claim field (claim_id + field)."""

    claim_id: str
    field: str


@dataclass(frozen=True)
class RenderedToken:
    """One numeric token extracted from a rendered artifact.

    raw:       the token exactly as it appears in the artifact ("1,234.5", "12%").
    value:     parsed numeric value, or None when the adapter could not parse it.
    claim_ref: the claim field the render binds this token to; None = the render
               declared no binding — an orphan candidate (V9 fails on orphans).
    location:  human-readable locus inside the artifact, for audit messages.
    """

    raw: str
    value: float | None
    claim_ref: ClaimFieldRef | None
    location: str


@runtime_checkable
class RenderAdapter(Protocol):
    """Turns a concrete render artifact into normalized RenderedTokens.

    One adapter per render backend. The audit core depends only on this
    protocol — never on a backend's concrete format.
    """

    backend: str

    def extract_tokens(self, artifact: Any) -> list[RenderedToken]:
        """Extract every numeric token the backend would render to a user."""
        ...


# ---------------------------------------------------------------------------
# Claims index — claim_id -> {field_name: value}
# ---------------------------------------------------------------------------

ClaimsIndex = dict[str, dict[str, Any]]


def build_claims_index(claims_rows: list[dict[str, Any]]) -> ClaimsIndex:
    """Build a claim_id -> {field: value} index from claims.jsonl rows."""
    index: ClaimsIndex = {}
    for row in claims_rows:
        claim_id = row.get("claim_id")
        if not claim_id:
            continue
        fields = row.get("fields") or {}
        index[claim_id] = {
            fname: fentry.get("value") if isinstance(fentry, dict) else fentry
            for fname, fentry in fields.items()
        }
    return index


def load_claims_index(run_dir: Path) -> ClaimsIndex:
    """Load + index the claims projection (claims.jsonl) for a run dir."""
    from insight_kit.gate.store import claims_index_path

    path = claims_index_path(run_dir)
    if not path.exists():
        return {}
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return build_claims_index(rows)


# ---------------------------------------------------------------------------
# L5 — HTML/render token -> claim join (V9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class L5Violation:
    """One L5 audit failure.

    kind: orphan | unknown-claim | unknown-field | value-mismatch.
    """

    kind: str
    token: RenderedToken
    detail: str


@dataclass
class L5Result:
    passed: bool
    violations: list[L5Violation] = field(default_factory=list)


def _value_matches(token_value: float, field_value: Any, *, rel_tol: float) -> bool:
    """True iff a rendered token value agrees with a claim field value.

    Scalar field → numeric closeness. List field → membership (a chart token is
    one point of a series field). Non-numeric field → never matches a number.
    """
    if isinstance(field_value, bool):
        return False
    if isinstance(field_value, (int, float)):
        return math.isclose(token_value, float(field_value), rel_tol=rel_tol, abs_tol=1e-12)
    if isinstance(field_value, (list, tuple)):
        return any(
            _value_matches(token_value, item, rel_tol=rel_tol) for item in field_value
        )
    return False


def audit_l5(
    tokens: list[RenderedToken],
    claims_index: ClaimsIndex,
    *,
    rel_tol: float = 1e-6,
) -> L5Result:
    """L5/V9 — every rendered numeric token must resolve to a claim field.

    A token with no claim_ref is an orphan (a number backed by nothing) and
    fails. A token whose claim_ref points to a missing claim or missing field
    fails. A token whose value disagrees with the claim field fails.
    """
    violations: list[L5Violation] = []
    for tok in tokens:
        if tok.claim_ref is None:
            violations.append(
                L5Violation(
                    kind="orphan",
                    token=tok,
                    detail=(
                        f"numeric token {tok.raw!r} at {tok.location} is bound to "
                        "no claim — every rendered number must resolve to a "
                        "claims-projection field (V9)."
                    ),
                )
            )
            continue
        cid, fld = tok.claim_ref.claim_id, tok.claim_ref.field
        claim = claims_index.get(cid)
        if claim is None:
            violations.append(
                L5Violation(
                    kind="unknown-claim",
                    token=tok,
                    detail=f"token at {tok.location} cites claim {cid!r}, not in the index.",
                )
            )
            continue
        if fld not in claim:
            violations.append(
                L5Violation(
                    kind="unknown-field",
                    token=tok,
                    detail=f"token at {tok.location} cites {cid}.{fld}, no such field.",
                )
            )
            continue
        if tok.value is not None and not _value_matches(
            tok.value, claim[fld], rel_tol=rel_tol
        ):
            violations.append(
                L5Violation(
                    kind="value-mismatch",
                    token=tok,
                    detail=(
                        f"token at {tok.location} renders {tok.value!r} but claim "
                        f"field {cid}.{fld} = {claim[fld]!r}."
                    ),
                )
            )
    return L5Result(passed=not violations, violations=violations)


# ---------------------------------------------------------------------------
# L6 — narrative.md prose lint (V8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class L6Violation:
    """One bare numeric literal found in claim narrative prose."""

    line: int
    token: str
    detail: str


@dataclass
class L6Result:
    passed: bool
    violations: list[L6Violation] = field(default_factory=list)


# A claim reference component — the ONLY legal way a number reaches prose.
_CLAIM_TAG = re.compile(r"</?Claim(?:Num|Chart)\b[^>]*>", re.IGNORECASE)
_INLINE_CODE = re.compile(r"`[^`]*`")
_LIST_ORDINAL = re.compile(r"^\s*\d+\.\s")
_NUMERIC = re.compile(r"\d[\d,]*(?:\.\d+)?")


def audit_l6(narrative_md: str) -> L6Result:
    """L6/V8 — claim narrative.md prose must contain zero bare numeric literals.

    Every number in narrative prose must be a claim field reference
    (<ClaimNum>/<ClaimChart>). A typed digit drifts from the claim it stands
    for — V8 forbids it.

    Exempt from the lint (numbers here are not prose claims):
      - fenced code blocks (``` … ```) and inline code (`…`),
      - the <ClaimNum>/<ClaimChart> reference components themselves,
      - leading ordered-list markers ("1. ", "2. ") — markdown structure.
    """
    violations: list[L6Violation] = []
    in_fence = False
    for lineno, line in enumerate(narrative_md.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        scrubbed = _INLINE_CODE.sub("", line)
        scrubbed = _CLAIM_TAG.sub("", scrubbed)
        scrubbed = _LIST_ORDINAL.sub("", scrubbed)
        for match in _NUMERIC.finditer(scrubbed):
            violations.append(
                L6Violation(
                    line=lineno,
                    token=match.group(),
                    detail=(
                        f"bare numeric literal {match.group()!r} in narrative prose "
                        f"(line {lineno}) — use a <ClaimNum>/<ClaimChart> field "
                        "reference instead (V8)."
                    ),
                )
            )
    return L6Result(passed=not violations, violations=violations)


# ---------------------------------------------------------------------------
# Combined render audit (V12)
# ---------------------------------------------------------------------------


@dataclass
class AuditReport:
    """Result of a full Layer-D render audit (L5 + L6).

    V12: this audit is CI-blocking on published / audience:board. `passed` is
    the gate signal — a CI stage blocks the render when a published/board
    artifact reports passed == False.
    """

    passed: bool
    l5: L5Result
    l6: L6Result


def run_render_audit(
    *,
    artifact: Any,
    adapter: RenderAdapter,
    narrative_md: str,
    claims_index: ClaimsIndex,
    rel_tol: float = 1e-6,
) -> AuditReport:
    """Run the full Layer-D render audit (V12) — L5 token join + L6 prose lint.

    The adapter turns `artifact` (a backend-specific render output) into
    normalized RenderedTokens; L5 joins them to `claims_index`; L6 lints
    `narrative_md`. The artifact passes only when both stages pass.
    """
    tokens = adapter.extract_tokens(artifact)
    l5 = audit_l5(tokens, claims_index, rel_tol=rel_tol)
    l6 = audit_l6(narrative_md)
    return AuditReport(passed=l5.passed and l6.passed, l5=l5, l6=l6)

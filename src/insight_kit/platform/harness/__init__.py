"""T17 — eval harness: semantic field-diff vs audited-truth golden (V11, C10, C11).

The harness re-runs a claim-producing pipeline and checks the claim field values
it emitted against a GOLDEN of audited-correct truth.

C11 — the golden is the audit truth column (e.g. docs/sprint3/03_page_numbers_
audit.md), NEVER raw historical agent_runs. Historical buggy runs are kept only
as NEGATIVE fixtures: the harness must classify them as regressions (RT6 — a
harness goldened on buggy runs certifies the bugs it hunts).

Each field difference is classified:
  match          — run value == golden within C10 tolerance (V11 determinism).
  regression     — run value disagrees with golden, unexplained → harness FAILS.
  legitimate     — value differs but the claim records why (a supersedes edge).
  coverage_drop  — value differs and the claim's coverage is thin/partial — the
                   value moved because inputs shrank, not because of a bug.

Only `regression` fails the harness. The harness image that containerizes real
business data is LOCAL-only and never pushed (see eval/README.md); this module
and its tests run entirely on synthetic golden + negative fixtures.

Cites: V11, C10, C11.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Golden — audited-truth field values: {claim_id: {field: value}}
# ---------------------------------------------------------------------------

Golden = dict[str, dict[str, Any]]

# C10 default replay tolerance — a published field value must match within this.
DEFAULT_REL_TOL: float = 1e-6


def load_golden(path: Path) -> Golden:
    """Load an audited-truth golden ({claim_id: {field: value}}) from JSON."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _claim_index(run_claims: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index claim record dicts by claim_id → the raw record (for metadata reads)."""
    return {c["claim_id"]: c for c in run_claims if c.get("claim_id")}


def _field_value(claim: dict[str, Any], field_name: str) -> Any:
    """Read a field value out of a claim record's fields dict (or None)."""
    entry = (claim.get("fields") or {}).get(field_name)
    if isinstance(entry, dict):
        return entry.get("value")
    return entry


def _close(a: Any, b: Any, *, rel_tol: float) -> bool:
    """Numeric closeness; non-numeric values compare by equality."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=1e-12)
    return a == b


# ---------------------------------------------------------------------------
# Field diff + classification
# ---------------------------------------------------------------------------


class DiffClass(StrEnum):
    """Classification of a single golden-vs-run field difference."""

    match = "match"
    regression = "regression"
    legitimate = "legitimate"
    coverage_drop = "coverage_drop"


@dataclass(frozen=True)
class FieldDiff:
    """One golden-vs-run comparison for a single claim field."""

    claim_id: str
    field: str
    golden_value: Any
    run_value: Any
    classification: DiffClass
    detail: str


def _coverage_is_thin(claim: dict[str, Any]) -> bool:
    """True iff the claim declares thin coverage (partial_period or n<30) — V14."""
    coverage = claim.get("coverage")
    if not isinstance(coverage, dict):
        return False
    if coverage.get("partial_period"):
        return True
    n = coverage.get("n")
    return isinstance(n, int) and n < 30


def classify_field(
    claim_id: str,
    field_name: str,
    golden_value: Any,
    claim: dict[str, Any] | None,
    *,
    rel_tol: float = DEFAULT_REL_TOL,
) -> FieldDiff:
    """Classify one golden field against the run's claim (C11).

    `claim` is the run's claim record dict, or None when the run emitted no
    claim for `claim_id` at all.
    """
    if claim is None:
        return FieldDiff(
            claim_id, field_name, golden_value, None, DiffClass.regression,
            f"run emitted no claim {claim_id!r} — golden field {field_name!r} is unmet.",
        )

    run_value = _field_value(claim, field_name)
    if run_value is None and field_name not in (claim.get("fields") or {}):
        return FieldDiff(
            claim_id, field_name, golden_value, None, DiffClass.regression,
            f"run claim {claim_id} is missing the golden field {field_name!r}.",
        )

    if _close(run_value, golden_value, rel_tol=rel_tol):
        return FieldDiff(
            claim_id, field_name, golden_value, run_value, DiffClass.match,
            f"{claim_id}.{field_name} matches golden within tolerance.",
        )

    # Value differs — classify the reason.
    if _coverage_is_thin(claim):
        return FieldDiff(
            claim_id, field_name, golden_value, run_value, DiffClass.coverage_drop,
            f"{claim_id}.{field_name} differs from golden but the claim declares "
            "thin coverage — value moved with input coverage, not a bug.",
        )
    if claim.get("supersedes"):
        return FieldDiff(
            claim_id, field_name, golden_value, run_value, DiffClass.legitimate,
            f"{claim_id}.{field_name} differs from golden but the claim carries a "
            f"supersedes edge ({claim['supersedes']}) — a documented correction.",
        )
    return FieldDiff(
        claim_id, field_name, golden_value, run_value, DiffClass.regression,
        f"{claim_id}.{field_name} = {run_value!r} disagrees with golden "
        f"{golden_value!r}, with no supersedes edge and no thin-coverage reason.",
    )


def diff_run_against_golden(
    run_claims: list[dict[str, Any]],
    golden: Golden,
    *,
    rel_tol: float = DEFAULT_REL_TOL,
) -> list[FieldDiff]:
    """Compare every golden field against a run's emitted claim records (C11)."""
    index = _claim_index(run_claims)
    diffs: list[FieldDiff] = []
    for claim_id, fields in golden.items():
        claim = index.get(claim_id)
        for field_name, golden_value in fields.items():
            diffs.append(
                classify_field(claim_id, field_name, golden_value, claim, rel_tol=rel_tol)
            )
    return diffs


# ---------------------------------------------------------------------------
# Harness report
# ---------------------------------------------------------------------------


@dataclass
class HarnessReport:
    """Outcome of an eval-harness run against the golden.

    passed is False iff any field is a regression. coverage_drop and legitimate
    diffs are surfaced but do not fail the harness.
    """

    passed: bool
    diffs: list[FieldDiff] = field(default_factory=list)

    def by_class(self, cls: DiffClass) -> list[FieldDiff]:
        return [d for d in self.diffs if d.classification == cls]

    @property
    def regressions(self) -> list[FieldDiff]:
        return self.by_class(DiffClass.regression)


def run_harness(
    run_claims: list[dict[str, Any]],
    golden: Golden,
    *,
    rel_tol: float = DEFAULT_REL_TOL,
) -> HarnessReport:
    """Run the eval harness — diff a run against the golden, fail on any regression."""
    diffs = diff_run_against_golden(run_claims, golden, rel_tol=rel_tol)
    passed = not any(d.classification == DiffClass.regression for d in diffs)
    return HarnessReport(passed=passed, diffs=diffs)


# ---------------------------------------------------------------------------
# V11 — replay determinism
# ---------------------------------------------------------------------------


@dataclass
class ReplayResult:
    """Result of a V11 determinism check between two runs of the same input."""

    deterministic: bool
    mismatches: list[FieldDiff] = field(default_factory=list)


def check_replay_determinism(
    run_a: list[dict[str, Any]],
    run_b: list[dict[str, Any]],
    *,
    rel_tol: float = DEFAULT_REL_TOL,
) -> ReplayResult:
    """V11 — re-running the same input must reproduce every claim field value.

    Determinism is value-equality under C10 tolerance — NOT fingerprint
    identity (V11 explicitly: fingerprints may differ; field values may not).
    """
    index_b = _claim_index(run_b)
    mismatches: list[FieldDiff] = []
    for claim in run_a:
        claim_id = claim.get("claim_id")
        if not claim_id:
            continue
        other = index_b.get(claim_id)
        for field_name in (claim.get("fields") or {}):
            a_val = _field_value(claim, field_name)
            b_val = _field_value(other, field_name) if other else None
            if not _close(a_val, b_val, rel_tol=rel_tol):
                mismatches.append(
                    FieldDiff(
                        claim_id, field_name, a_val, b_val, DiffClass.regression,
                        f"replay non-determinism: {claim_id}.{field_name} was "
                        f"{a_val!r} then {b_val!r}.",
                    )
                )
    return ReplayResult(deterministic=not mismatches, mismatches=mismatches)


def charts_byte_identical(chart_a: str | bytes, chart_b: str | bytes) -> bool:
    """V11 — a published-tier chart.vl.json must replay byte-identical."""
    a = chart_a.encode("utf-8") if isinstance(chart_a, str) else chart_a
    b = chart_b.encode("utf-8") if isinstance(chart_b, str) else chart_b
    return a == b

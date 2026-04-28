"""Layer-A real-time validation guards.

Fires at emit time (Run.claim, Run.ingest_external). Raises ValidationError
with rule_id + suggestion so the calling agent can self-correct in the same Run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from insight_kit.provenance.run import Run as Run

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


def _load_prior_claim_ids(kit_root: Path) -> set[str]:
    """Collect all claim_ids from prior completed runs in .insight-kit/runs/."""
    ids: set[str] = set()
    runs_base = kit_root / ".insight-kit" / "runs"
    if not runs_base.exists():
        return ids
    for run_dir in runs_base.iterdir():
        if not run_dir.is_dir():
            continue
        claims_file = run_dir / "claims.jsonl"
        if not claims_file.exists():
            continue
        try:
            for line in claims_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                cid = rec.get("claim_id")
                if cid:
                    ids.add(cid)
        except Exception:
            continue
    return ids


def check_input_claims_exist(
    claim_id: str,
    input_claims: list[str],
    current_run_claim_ids: set[str],
    kit_root: Path,
) -> None:
    """Rule: input-claims-referential-integrity.

    Every claim_id in input_claims must exist in the current run's claims so far
    OR in prior runs' claims.jsonl files under .insight-kit/runs/.
    """
    if not input_claims:
        return
    prior_ids = _load_prior_claim_ids(kit_root)
    all_known = current_run_claim_ids | prior_ids
    dangling = [ref for ref in input_claims if ref not in all_known]
    if dangling:
        raise ValidationError(
            rule_id="input-claims-referential-integrity",
            message=(
                f"claim {claim_id!r} references unknown input_claims: {dangling!r}. "
                "Referenced claims must exist in current run or prior runs."
            ),
            suggestion=(
                f"Ensure input_claims refs exist before referencing them. "
                f"Dangling refs: {dangling!r}"
            ),
        )


def check_claim_id_unique(kit_root: Path) -> list[ValidationError]:
    """Rule: claim-id-globally-unique (Layer B/C).

    Scan all claims.jsonl under .insight-kit/runs/. If the same claim_id appears
    in 2+ different runs without a supersedes chain, return ValidationError list.
    """
    runs_base = kit_root / ".insight-kit" / "runs"
    if not runs_base.exists():
        return []

    # claim_id -> list of (run_dir_name, supersedes value)
    seen: dict[str, list[tuple[str, str | None]]] = {}

    for run_dir in runs_base.iterdir():
        if not run_dir.is_dir():
            continue
        claims_file = run_dir / "claims.jsonl"
        if not claims_file.exists():
            continue
        try:
            for line in claims_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                cid = rec.get("claim_id")
                if not cid:
                    continue
                supersedes = rec.get("supersedes")
                if cid not in seen:
                    seen[cid] = []
                seen[cid].append((run_dir.name, supersedes))
        except Exception:
            continue

    errors: list[ValidationError] = []
    for cid, appearances in seen.items():
        if len(appearances) < 2:
            continue
        # Allow duplicates only if at least one has a supersedes chain
        has_supersedes = any(sup is not None for _, sup in appearances)
        if not has_supersedes:
            run_names = [r for r, _ in appearances]
            errors.append(
                ValidationError(
                    rule_id="claim-id-globally-unique",
                    message=(
                        f"claim_id {cid!r} appears in {len(appearances)} runs "
                        f"without supersedes chain: {run_names}"
                    ),
                    suggestion=(
                        f"Use a unique claim_id per run, or set supersedes=<prior_claim_id> "
                        f"to form a valid replacement chain. Duplicate runs: {run_names}"
                    ),
                )
            )
    return errors


def check_claim_id_unique_in_run(
    claim_id: str,
    current_run_claim_ids: set[str],
) -> None:
    """Rule: claim-id-duplicate-in-run (Layer-A).

    Emitting two claims with the same claim_id within ONE Run should raise immediately
    on the 2nd emit, not wait for __exit__.
    """
    if claim_id in current_run_claim_ids:
        raise ValidationError(
            rule_id="claim-id-duplicate-in-run",
            message=(
                f"claim_id {claim_id!r} has already been emitted in this run. "
                "Each claim_id must be unique within a run."
            ),
            suggestion=(
                f"Use a unique claim_id for each claim. "
                f"{claim_id!r} was already emitted in this run."
            ),
        )


CITE_PATTERN = re.compile(r"\[\[CITE:\s*([^\]]+?)\s*\]\]")


def check_citation_referential_integrity(
    statement: str,
    interpretation: str | None,
    current_run_claim_ids: set[str],
    kit_root: Path,
) -> None:
    """Rule: citation-referential-integrity.

    Parse statement and interpretation strings for [[CITE: <ID>]] patterns.
    Each <ID> must exist in current run or prior runs.
    """
    cited: list[str] = CITE_PATTERN.findall(statement or "")
    if interpretation:
        cited.extend(CITE_PATTERN.findall(interpretation))

    if not cited:
        return

    prior_ids = _load_prior_claim_ids(kit_root)
    all_known = current_run_claim_ids | prior_ids

    dangling = [cid for cid in cited if cid not in all_known]
    if dangling:
        raise ValidationError(
            rule_id="citation-referential-integrity",
            message=(
                f"Statement/interpretation contains [[CITE:]] references to unknown "
                f"claim_ids: {dangling!r}. Each cited ID must exist in current run or prior runs."
            ),
            suggestion=(
                f"Ensure all [[CITE: ID]] references exist before citing them. "
                f"Dangling citations: {dangling!r}"
            ),
        )


def check_supersedes_chain_integrity(
    claim_id: str,
    supersedes: str | None,
    kit_root: Path,
    current_run_claim_ids: set[str],
) -> None:
    """Rule: supersedes-already-deprecated.

    If claim X already has a successor in the chain (anything supersedes X already),
    then a new claim Y supersedes=[X] must raise.
    """
    if supersedes is None:
        return

    target = supersedes

    # Build a set of all claim_ids that already have a successor (someone else supersedes them)
    already_superseded: set[str] = set()

    # Check prior runs
    runs_base = kit_root / ".insight-kit" / "runs"
    if runs_base.exists():
        for run_dir in runs_base.iterdir():
            if not run_dir.is_dir():
                continue
            claims_file = run_dir / "claims.jsonl"
            if not claims_file.exists():
                continue
            try:
                for line in claims_file.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    sup = rec.get("supersedes")
                    if sup:
                        already_superseded.add(sup)
            except Exception:
                continue

    if target in already_superseded:
        raise ValidationError(
            rule_id="supersedes-already-deprecated",
            message=(
                f"claim {claim_id!r} tries to supersede {target!r}, "
                f"but {target!r} already has a successor in the chain."
            ),
            suggestion=(
                f"Cannot supersede {target!r} because it has already been superseded. "
                f"Supersede the latest claim in the chain instead."
            ),
        )


def _load_glossary_topics(kit_root: Path) -> list[str] | None:
    """Load allowed metric name prefixes from project glossary.

    Returns list of topic strings if a glossary.yaml exists and has topics,
    or None if no project glossary is configured (check is skipped).
    """
    glossary_path = kit_root / ".insight-kit" / "templates" / "glossary.yaml"
    if glossary_path.exists():
        try:
            data = yaml.safe_load(glossary_path.read_text()) or {}
            topics = data.get("topics", [])
            if topics:
                return list(topics)
        except Exception:
            pass
    return None


def check_metric_id_allowed(name: str, kit_root: Path) -> None:
    """Rule: metric-id-off-glossary.

    emit_metric(name=...) must start with a prefix from the project glossary topics allow-list.
    Reads .insight-kit/templates/glossary.yaml. If no glossary is configured, check is skipped.
    """
    allowed_prefixes = _load_glossary_topics(kit_root)
    if allowed_prefixes is None:
        # No project glossary configured — permissive (no enforcement)
        return
    for prefix in allowed_prefixes:
        if name.startswith(prefix):
            return
    raise ValidationError(
        rule_id="metric-id-off-glossary",
        message=(
            f"metric name {name!r} does not start with any allowed glossary topic prefix. "
            f"Allowed prefixes: {allowed_prefixes!r}"
        ),
        suggestion=(
            f"Use a metric name starting with one of the glossary topics: {allowed_prefixes!r}. "
            f"Example: '{allowed_prefixes[0]}_{name}' or define a new topic in "
            f".insight-kit/templates/glossary.yaml."
        ),
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

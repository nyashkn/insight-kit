"""T23 — post-hoc utility verdict on knowledge records (V21, I.events).

A research/skill_use record can be judged useful or not_useful AFTER the fact —
once downstream work either relied on its captured knowledge or didn't. V21: that
verdict is event-only. It is appended to records/{id}/events/utility_verdict.jsonl
and is NEVER edited into record.json — the record's own json stays immutable
(mirrors V3 supersession + the claim critiques[] pattern).

Cites: V21, I.events.
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from insight_kit.platform.gate.store import (
    append_event,
    read_record,
    record_path,
    resolve_run_dir,
)
from insight_kit.validation import ValidationError as LayerAValidationError

UTILITY_VERDICT_EVENT: str = "utility_verdict"
"""events/*.jsonl basename for the post-hoc utility verdict log."""


class UtilityVerdict(StrEnum):
    """The post-hoc judgement on a knowledge record's usefulness (V21)."""

    useful = "useful"
    not_useful = "not_useful"


_KNOWLEDGE_TYPES: frozenset[str] = frozenset({"research", "skill_use"})


def ik_utility_verdict(
    record_id: str,
    verdict: str,
    *,
    run_dir: Path | None = None,
    rationale: str | None = None,
    timestamp: str | None = None,
) -> Path:
    """T23/V21 — append a post-hoc utility verdict to a knowledge record.

    The verdict (useful | not_useful) is the mutable post-hoc judgement on
    whether a research/skill_use record's captured knowledge proved useful. It
    is written ONLY as an append-only event under
    records/{id}/events/utility_verdict.jsonl — record.json is never touched
    (V21, I.events). The verdict may be revised: each call appends a new event,
    and the current verdict is the most recent line.

    Args:
        record_id: the research/skill_use record being judged.
        verdict:   "useful" or "not_useful".
        run_dir:   run directory; resolved from INSIGHT_KIT_RUN_DIR if None.
        rationale: optional free-text reason for the verdict.
        timestamp: ISO-8601 string; defaults to current UTC time.

    Returns the path to the utility_verdict.jsonl event log.

    Raises LayerAValidationError if the verdict value is invalid, the target
    record does not exist, or the target is not a research/skill_use record.
    """
    resolved = resolve_run_dir(run_dir)

    try:
        chosen = UtilityVerdict(verdict)
    except ValueError as exc:
        raise LayerAValidationError(
            rule_id="utility-verdict-invalid",
            message=(
                f"utility verdict must be one of {[m.value for m in UtilityVerdict]}; "
                f"got {verdict!r}."
            ),
            suggestion="Pass verdict='useful' or verdict='not_useful'.",
        ) from exc

    if not record_path(resolved, record_id).exists():
        raise LayerAValidationError(
            rule_id="utility-verdict-target-missing",
            message=(
                f"utility verdict targets {record_id!r}, which does not correspond "
                "to any record in the run directory."
            ),
            suggestion="Check the record_id; the knowledge record must be emitted first.",
        )

    record_type = read_record(resolved, record_id).get("record_type")
    if record_type not in _KNOWLEDGE_TYPES:
        raise LayerAValidationError(
            rule_id="utility-verdict-wrong-type",
            message=(
                f"utility verdict targets a {record_type!r} record. V21 — the "
                "useful/not_useful verdict applies only to research/skill_use "
                "knowledge records."
            ),
            suggestion=(
                "A claim is revised with `supersedes`; an intervention is "
                "reconciled via `realized`. The utility verdict is for knowledge "
                "records only."
            ),
        )

    event: dict[str, Any] = {
        "verdict": chosen.value,
        "rationale": rationale,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }
    return append_event(resolved, record_id, UTILITY_VERDICT_EVENT, event)

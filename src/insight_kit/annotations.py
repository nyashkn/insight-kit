"""Binary annotation MVP — human signal on claim outcomes."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from insight_kit.provenance.root import find_kit_root

ANNOTATIONS_FILE = "annotations.jsonl"


def _path() -> Path:
    return find_kit_root() / ".insight-kit" / ANNOTATIONS_FILE


def annotate(
    claim_id: str,
    acted_on: bool,
    validated: bool,
    note: str | None = None,
    annotator: str | None = None,
) -> dict:
    """Append an annotation. Returns the record written."""
    rec = {
        "annotation_id": f"ann-{secrets.token_hex(4)}",
        "claim_id": claim_id,
        "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "annotator": annotator or os.environ.get("USER", "anon"),
        "acted_on": acted_on,
        "validated": validated,
    }
    if note:
        rec["note"] = note
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def iter_annotations(claim_id: str | None = None) -> Iterator[dict]:
    p = _path()
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if claim_id is None or rec["claim_id"] == claim_id:
            yield rec

"""Render-audit adapters — one per render backend (T16, I.audit).

Each adapter implements the RenderAdapter protocol from `audit.py`: it turns a
concrete render artifact into a normalized list[RenderedToken] the
backend-agnostic audit core consumes. Adding a render backend = adding an
adapter here; the audit core never changes.

Implemented:
  VegaLiteAdapter — Altair-emitted chart.vl.json (the Vega-Lite spec, a stable
                    public format — no SDK dependence).

Deferred (each ships with its backend):
  EvidenceAdapter   — Evidence .md / HTML, with the Evidence SDK loop.
  SupersetAdapter / LightdashAdapter / PowerBIAdapter / MalloyAdapter — when
                    those backends are adopted.

Claim-binding contract — a chart declares its claim binding in the Vega-Lite
`usermeta` slot (Vega-Lite's official arbitrary-metadata key):

    "usermeta": {"insight_kit": {
        "claim_id": "ABC-D-001",
        "field_map": {"<vega data field>": "<claim field name>"}
    }}

A numeric data value in a mapped field → a RenderedToken bound to that claim
field. A numeric data value in an unmapped field → an orphan token
(claim_ref=None) — L5 fails on it (V9).

Cites: V9, I.audit, C5.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from insight_kit.gate.audit import ClaimFieldRef, RenderedToken


def _as_number(value: Any) -> float | None:
    """Coerce a Vega-Lite data value to a float, or None if it is not numeric.

    bool is excluded (it is an int subclass but not a rendered number); numeric
    strings with thousands separators ("1,234") are parsed.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


class VegaLiteAdapter:
    """RenderAdapter for Altair-emitted Vega-Lite chart specs (chart.vl.json)."""

    backend = "vega-lite"

    def extract_tokens(self, artifact: dict[str, Any] | Path | str) -> list[RenderedToken]:
        """Extract every numeric data value a Vega-Lite chart would render.

        `artifact` may be the parsed spec dict, or a Path to a chart.vl.json
        file. Numbers in fields named by `usermeta.insight_kit.field_map` are
        bound to that claim; numbers in any other field are orphan tokens.
        """
        spec = self._load(artifact)
        meta = (spec.get("usermeta") or {}).get("insight_kit") or {}
        claim_id = meta.get("claim_id")
        field_map: dict[str, str] = meta.get("field_map") or {}

        values = (spec.get("data") or {}).get("values") or []
        tokens: list[RenderedToken] = []
        for i, row in enumerate(values):
            if not isinstance(row, dict):
                continue
            for key, raw_value in row.items():
                number = _as_number(raw_value)
                if number is None:
                    continue
                ref: ClaimFieldRef | None = None
                if claim_id and key in field_map:
                    ref = ClaimFieldRef(claim_id=claim_id, field=field_map[key])
                tokens.append(
                    RenderedToken(
                        raw=str(raw_value),
                        value=number,
                        claim_ref=ref,
                        location=f"data.values[{i}].{key}",
                    )
                )
        return tokens

    @staticmethod
    def _load(artifact: dict[str, Any] | Path | str) -> dict[str, Any]:
        if isinstance(artifact, dict):
            return artifact
        return json.loads(Path(artifact).read_text(encoding="utf-8"))

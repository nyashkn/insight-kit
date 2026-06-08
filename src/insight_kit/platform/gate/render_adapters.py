"""Render-audit adapters — one per render backend (T16, I.audit).

Each adapter implements the RenderAdapter protocol from `audit.py`: it turns a
concrete render artifact into a normalized list[RenderedToken] the
backend-agnostic audit core consumes. Adding a render backend = adding an
adapter here; the audit core never changes.

Implemented:
  VegaLiteAdapter    — Altair-emitted chart.vl.json (the Vega-Lite spec, a stable
                       public format — no SDK dependence).
  MarkdownVegaAdapter — T33 composer — narrative.md with <ClaimChart src> refs;
                        delegates per-chart token extraction to VegaLiteAdapter.

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

from insight_kit.platform.gate.audit import ClaimFieldRef, RenderedToken


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


class MarkdownVegaAdapter:
    """T33 — RenderAdapter for narrative.md files containing <ClaimChart src> refs.

    Finds every <ClaimChart src="chart.vl.json" claim="..."/> tag in the
    narrative, resolves each src relative to the narrative file's parent
    directory, and delegates token extraction to VegaLiteAdapter. Returns the
    concatenated list[RenderedToken] from all charts found.

    This allows run_render_audit to audit a composed narrative's charts against
    the claim index without re-implementing any Vega-Lite token logic.

    artifact: str (narrative.md content) or Path to the narrative.md file.
    When artifact is a Path, sibling .vl.json files are resolved relative to
    artifact.parent. When artifact is a string, sibling resolution requires
    that the string was read from a known location — in that case pass a Path
    instead for correct sibling resolution.
    """

    backend = "markdown-vega"

    def extract_tokens(
        self,
        artifact: str | Path,
        *,
        base_dir: Path | None = None,
    ) -> list[RenderedToken]:
        """Extract RenderedTokens from all <ClaimChart> refs in a narrative.md.

        For each <ClaimChart src="..."> tag, loads the sibling Vega-Lite spec
        and delegates to VegaLiteAdapter.extract_tokens(spec).
        Returns concatenated tokens from all charts (order: appearance in doc).

        artifact:
          - Path    → content read from file; sibling_dir = artifact.parent.
          - str of an existing file path → treated as Path (resolved automatically).
          - str of raw narrative content → sibling_dir = base_dir (raise if a
            relative src is present and base_dir is None).

        base_dir: optional override for sibling resolution when artifact is a
          raw content string. Ignored when artifact is a Path or a path string
          that resolves to an existing file.
        """
        from insight_kit.platform.gate.compose import parse_refs  # avoid circular at module level

        if isinstance(artifact, Path):
            content = artifact.read_text(encoding="utf-8")
            sibling_dir: Path | None = artifact.parent
        else:
            # str: first check whether it is an existing file path.
            candidate = Path(artifact)
            if candidate.exists():
                content = candidate.read_text(encoding="utf-8")
                sibling_dir = candidate.parent
            else:
                # Treat as raw narrative content string.
                content = artifact
                sibling_dir = base_dir

        refs = parse_refs(content)
        vla = VegaLiteAdapter()
        tokens: list[RenderedToken] = []

        for chart_ref in refs.chart_refs:
            if sibling_dir is not None:
                spec_path = sibling_dir / chart_ref.src
            else:
                src_path = Path(chart_ref.src)
                if src_path.is_absolute():
                    spec_path = src_path
                else:
                    raise ValueError(
                        f"MarkdownVegaAdapter: cannot resolve relative chart src "
                        f"{chart_ref.src!r} — pass artifact as a Path or provide "
                        f"base_dir when using a raw content string."
                    )

            spec = VegaLiteAdapter._load(spec_path)
            tokens.extend(vla.extract_tokens(spec))

        return tokens

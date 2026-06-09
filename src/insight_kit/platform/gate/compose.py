"""T33 — Gate-native render composer (Layer-D, I.audit).

Turns a claim record's narrative.md + sibling chart.vl.json files into a
self-contained HTML page with:
  - <ClaimNum> tags resolved to formatted field values (fmt_hint applied).
  - <ClaimChart> tags rendered via vega-embed (pinned CDN, spec JSON inlined).

Binding checks:
  - Every <ClaimChart src> must resolve to an existing sibling .vl.json.
  - That spec's usermeta.insight_kit.claim_id must equal the tag's claim attr.
  - Every <ClaimNum claim/field> must resolve to a real claim field.

Cites: V8, V9, V12, I.audit, C10.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Domain error
# ---------------------------------------------------------------------------


class ComposeError(Exception):
    """Raised when compose_record cannot produce a valid HTML output.

    Covers: unresolved ClaimNum refs, missing sibling chart files, and
    usermeta claim_id binding mismatches.
    """


# ---------------------------------------------------------------------------
# Ref-tag regexes — superset of audit.py _CLAIM_TAG so L6 audit exempts them
# ---------------------------------------------------------------------------

_RE_CLAIM_NUM = re.compile(
    r'<ClaimNum\b[^>]*\bclaim="(?P<claim>[^"]+)"[^>]*\bfield="(?P<field>[^"]+)"[^>]*/?>',
    re.IGNORECASE,
)
# Also handle field before claim attribute order
_RE_CLAIM_NUM_ALT = re.compile(
    r'<ClaimNum\b[^>]*\bfield="(?P<field>[^"]+)"[^>]*\bclaim="(?P<claim>[^"]+)"[^>]*/?>',
    re.IGNORECASE,
)
_RE_CLAIM_CHART = re.compile(
    r'<ClaimChart\b[^>]*\bsrc="(?P<src>[^"]+)"[^>]*\bclaim="(?P<claim>[^"]+)"[^>]*/?>',
    re.IGNORECASE,
)
# Also handle claim before src attribute order
_RE_CLAIM_CHART_ALT = re.compile(
    r'<ClaimChart\b[^>]*\bclaim="(?P<claim>[^"]+)"[^>]*\bsrc="(?P<src>[^"]+)"[^>]*/?>',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClaimNumRef:
    """A parsed <ClaimNum> tag."""

    claim: str
    field_name: str
    match_start: int
    match_end: int
    raw: str  # the full tag text


@dataclass(frozen=True)
class ClaimChartRef:
    """A parsed <ClaimChart> tag."""

    src: str
    claim: str
    match_start: int
    match_end: int
    raw: str  # the full tag text


@dataclass
class ParsedRefs:
    """All claim reference tags found in a narrative.md."""

    num_refs: list[ClaimNumRef] = field(default_factory=list)
    chart_refs: list[ClaimChartRef] = field(default_factory=list)


def parse_refs(narrative_md: str) -> ParsedRefs:
    """Parse all <ClaimNum> and <ClaimChart> tags from narrative_md.

    Tolerant of attribute order and self-closing variants. Both orderings of
    claim/field (or src/claim) are matched.
    """
    result = ParsedRefs()

    # Collect ClaimNum matches (both attribute orderings); deduplicate by span
    num_spans: set[tuple[int, int]] = set()
    for pattern in (_RE_CLAIM_NUM, _RE_CLAIM_NUM_ALT):
        for m in pattern.finditer(narrative_md):
            span = (m.start(), m.end())
            if span in num_spans:
                continue
            num_spans.add(span)
            result.num_refs.append(
                ClaimNumRef(
                    claim=m.group("claim"),
                    field_name=m.group("field"),
                    match_start=m.start(),
                    match_end=m.end(),
                    raw=m.group(),
                )
            )

    # Sort by position for deterministic ordering
    result.num_refs.sort(key=lambda r: r.match_start)

    # Collect ClaimChart matches (both attribute orderings); deduplicate by span
    chart_spans: set[tuple[int, int]] = set()
    for pattern in (_RE_CLAIM_CHART, _RE_CLAIM_CHART_ALT):
        for m in pattern.finditer(narrative_md):
            span = (m.start(), m.end())
            if span in chart_spans:
                continue
            chart_spans.add(span)
            result.chart_refs.append(
                ClaimChartRef(
                    src=m.group("src"),
                    claim=m.group("claim"),
                    match_start=m.start(),
                    match_end=m.end(),
                    raw=m.group(),
                )
            )

    result.chart_refs.sort(key=lambda r: r.match_start)
    return result


# ---------------------------------------------------------------------------
# fmt_hint formatter
# ---------------------------------------------------------------------------


def _apply_fmt_hint(value: Any, fmt_hint: str | None) -> str:
    """Apply a printf-style fmt_hint to value, falling back to str(value)."""
    if fmt_hint is None:
        return str(value)
    try:
        return fmt_hint % value
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Claims field reader (needs fmt_hint — cannot go through build_claims_index)
# ---------------------------------------------------------------------------


def _load_claim_fields_with_hints(run_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """Load claims.jsonl and return claim_id -> {field_name -> {value, fmt_hint}}.

    build_claims_index strips fmt_hint; the composer needs it for ClaimNum
    formatting. We read claims.jsonl directly here.
    """
    from insight_kit.platform.gate.store import claims_index_path

    path = claims_index_path(run_dir)
    if not path.exists():
        return {}

    index: dict[str, dict[str, dict[str, Any]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        claim_id = row.get("claim_id")
        if not claim_id:
            continue
        raw_fields = row.get("fields") or {}
        index[claim_id] = {}
        for fname, fentry in raw_fields.items():
            if isinstance(fentry, dict):
                index[claim_id][fname] = {
                    "value": fentry.get("value"),
                    "fmt_hint": fentry.get("fmt_hint"),
                }
            else:
                index[claim_id][fname] = {"value": fentry, "fmt_hint": None}
    return index


# ---------------------------------------------------------------------------
# Binding verification (audit seam — src-exists + usermeta claim_id == tag claim)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChartBindingError:
    """One binding error found by verify_chart_bindings."""

    kind: str   # "src-missing" | "claim-id-mismatch"
    src: str
    claim: str
    detail: str


@dataclass
class ChartBindingResult:
    """Result of verify_chart_bindings — consistent with L5Result/AuditReport style."""

    passed: bool
    violations: list[ChartBindingError] = field(default_factory=list)


def verify_chart_bindings(run_dir: Path, record_id: str) -> ChartBindingResult:
    """Verify every <ClaimChart src=...> in the record's narrative.md.

    Checks:
      (a) src resolves to an existing sibling file under records/{record_id}/.
      (b) that spec's usermeta.insight_kit.claim_id == tag's claim attr.

    Returns ChartBindingResult (passed=True when all charts bind correctly).
    Raises ComposeError if narrative.md itself is absent.
    """
    from insight_kit.platform.gate.store import record_path

    rec_dir = record_path(run_dir, record_id).parent
    narrative_path = rec_dir / "narrative.md"

    if not narrative_path.exists():
        raise ComposeError(
            f"narrative.md not found for record {record_id!r}: {narrative_path}"
        )

    narrative_md = narrative_path.read_text(encoding="utf-8")
    refs = parse_refs(narrative_md)

    errors: list[ChartBindingError] = []

    for chart_ref in refs.chart_refs:
        sibling_path = rec_dir / chart_ref.src
        if not sibling_path.exists():
            errors.append(
                ChartBindingError(
                    kind="src-missing",
                    src=chart_ref.src,
                    claim=chart_ref.claim,
                    detail=(
                        f"<ClaimChart src={chart_ref.src!r} claim={chart_ref.claim!r}> "
                        f"references a file that does not exist: {sibling_path}"
                    ),
                )
            )
            continue

        try:
            spec = json.loads(sibling_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(
                ChartBindingError(
                    kind="src-missing",
                    src=chart_ref.src,
                    claim=chart_ref.claim,
                    detail=(
                        f"<ClaimChart src={chart_ref.src!r}> could not be parsed as JSON: {exc}"
                    ),
                )
            )
            continue

        meta = (spec.get("usermeta") or {}).get("insight_kit") or {}
        spec_claim_id = meta.get("claim_id")

        if spec_claim_id != chart_ref.claim:
            errors.append(
                ChartBindingError(
                    kind="claim-id-mismatch",
                    src=chart_ref.src,
                    claim=chart_ref.claim,
                    detail=(
                        f"<ClaimChart src={chart_ref.src!r} claim={chart_ref.claim!r}>: "
                        f"spec usermeta.insight_kit.claim_id={spec_claim_id!r} "
                        f"does not match tag claim attr {chart_ref.claim!r}."
                    ),
                )
            )

    return ChartBindingResult(passed=not errors, violations=errors)


# ---------------------------------------------------------------------------
# HTML composer
# ---------------------------------------------------------------------------

_VEGA_CDN = """\
<script src="https://cdn.jsdelivr.net/npm/vega@5/build/vega.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-lite@5/build/vega-lite.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/vega-embed@6/build/vega-embed.min.js"></script>"""


def _chart_embed_html(chart_id: str, spec: dict[str, Any]) -> str:
    """Produce the HTML snippet for one vega-embed chart."""
    spec_json = json.dumps(spec, separators=(",", ":"), ensure_ascii=False)
    return (
        f'<div id="{chart_id}" class="ik-chart"></div>\n'
        f"<script>\n"
        f'  vegaEmbed("#{chart_id}", {spec_json}, {{renderer: "canvas"}});\n'
        f"</script>"
    )


def _markdown_to_html_paragraphs(text: str) -> str:
    """Minimal markdown-to-HTML: wrap non-blank lines in <p> blocks.

    This is intentionally minimal — the narrative is trusted prose with
    ClaimNum values already resolved. Full markdown rendering is out of scope
    for this slice.
    """
    lines = text.split("\n")
    out: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + " ".join(para) + "</p>")
            para.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            flush_para()
            out.append(f"<h1>{stripped[2:]}</h1>")
        elif stripped.startswith("## "):
            flush_para()
            out.append(f"<h2>{stripped[3:]}</h2>")
        elif stripped.startswith("### "):
            flush_para()
            out.append(f"<h3>{stripped[4:]}</h3>")
        elif stripped == "":
            flush_para()
        else:
            para.append(stripped)

    flush_para()
    return "\n".join(out)


def compose_record(run_dir: Path, record_id: str) -> str:
    """Compose a self-contained HTML string for a claim record's narrative.

    Resolves <ClaimNum> tags to formatted field values (fmt_hint applied) and
    renders each <ClaimChart> as an interactive vega-embed widget with the
    spec JSON inlined.

    Raises ComposeError on:
      - missing narrative.md
      - unresolved ClaimNum (unknown claim or field)
      - missing chart sibling file
      - usermeta claim_id binding mismatch

    run_dir: the gate run directory (contains claims.jsonl + records/).
    record_id: the record bundle id under records/{record_id}/.
    """
    from insight_kit.platform.gate.store import record_path

    rec_dir = record_path(run_dir, record_id).parent
    narrative_path = rec_dir / "narrative.md"

    if not narrative_path.exists():
        raise ComposeError(
            f"narrative.md not found for record {record_id!r}: {narrative_path}"
        )

    narrative_md = narrative_path.read_text(encoding="utf-8")
    refs = parse_refs(narrative_md)

    # Load claim fields with fmt_hint (build_claims_index strips it)
    claim_fields = _load_claim_fields_with_hints(run_dir)

    # -----------------------------------------------------------------------
    # Step 1: Resolve ClaimNum tags
    # -----------------------------------------------------------------------
    # Walk backwards so replacement offsets stay valid
    resolved_md = narrative_md
    for num_ref in reversed(refs.num_refs):
        cid = num_ref.claim
        fname = num_ref.field_name
        claim_data = claim_fields.get(cid)
        if claim_data is None:
            raise ComposeError(
                f"<ClaimNum claim={cid!r} field={fname!r}>: "
                f"claim {cid!r} not found in claims index for run_dir {run_dir}."
            )
        field_entry = claim_data.get(fname)
        if field_entry is None:
            raise ComposeError(
                f"<ClaimNum claim={cid!r} field={fname!r}>: "
                f"field {fname!r} not found in claim {cid!r}. "
                f"Available fields: {list(claim_data.keys())}"
            )
        formatted = _apply_fmt_hint(field_entry["value"], field_entry["fmt_hint"])
        resolved_md = (
            resolved_md[: num_ref.match_start]
            + formatted
            + resolved_md[num_ref.match_end :]
        )

    # -----------------------------------------------------------------------
    # Step 2: Replace ClaimChart tags with placeholder IDs, collect specs
    # -----------------------------------------------------------------------
    # Re-parse after ClaimNum replacement (positions of ClaimChart tags shift if
    # ClaimNum tags appear before them). We re-parse the ORIGINAL narrative for
    # ClaimChart positions (ClaimNum replacement may shift offsets), so we work
    # from the original positions on the original string, then rebuild.
    #
    # Simpler approach: replace chart tags in the resolved_md using regex (which
    # is now ClaimNum-resolved but still contains ClaimChart tags verbatim).

    chart_specs: list[tuple[str, dict[str, Any]]] = []  # (chart_id, spec)

    # Apply to resolved_md (ClaimNum already resolved, ClaimChart still tags)
    # Both attribute orderings
    _chart_pattern = re.compile(
        r'<ClaimChart\b(?:[^>]*\bsrc="(?P<src>[^"]+)"[^>]*\bclaim="(?P<claim>[^"]+)"'
        r'|[^>]*\bclaim="(?P<claim2>[^"]+)"[^>]*\bsrc="(?P<src2>[^"]+)")'
        r'[^>]*/?>',
        re.IGNORECASE,
    )

    def _unified_chart_replace(m: re.Match) -> str:  # type: ignore[type-arg]
        src = m.group("src") or m.group("src2")
        claim = m.group("claim") or m.group("claim2")
        chart_idx = len(chart_specs)
        chart_id = f"ik-chart-{record_id}-{chart_idx}"

        sibling_path = rec_dir / src
        if not sibling_path.exists():
            raise ComposeError(
                f"<ClaimChart src={src!r} claim={claim!r}>: "
                f"sibling file not found: {sibling_path}"
            )

        try:
            spec = json.loads(sibling_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ComposeError(
                f"<ClaimChart src={src!r}>: could not parse as JSON: {exc}"
            ) from exc

        meta = (spec.get("usermeta") or {}).get("insight_kit") or {}
        spec_claim_id = meta.get("claim_id")
        if spec_claim_id != claim:
            raise ComposeError(
                f"<ClaimChart src={src!r} claim={claim!r}>: "
                f"spec usermeta.insight_kit.claim_id={spec_claim_id!r} "
                f"does not match tag claim attr {claim!r}."
            )

        embed = _chart_embed_html(chart_id, spec)
        chart_specs.append((chart_id, spec))
        return embed

    # Replace ClaimChart tags directly with embed HTML (preserves order)
    html_body_source = _chart_pattern.sub(_unified_chart_replace, resolved_md)

    # -----------------------------------------------------------------------
    # Step 3: Minimal markdown → HTML
    # -----------------------------------------------------------------------
    body_html = _markdown_to_html_paragraphs(html_body_source)

    # -----------------------------------------------------------------------
    # Step 4: Wrap into a self-contained HTML page
    # -----------------------------------------------------------------------
    record_title = f"Insight Kit — {record_id}"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{record_title}</title>
  {_VEGA_CDN}
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      max-width: 900px;
      margin: 2rem auto;
      padding: 0 1.5rem;
      color: #1a1a1a;
      line-height: 1.6;
    }}
    h1 {{ font-size: 1.75rem; margin-top: 2rem; }}
    h2 {{ font-size: 1.35rem; margin-top: 1.75rem; }}
    h3 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
    p {{ margin: 0.75rem 0; }}
    .ik-chart {{ margin: 1.5rem 0; }}
    .ik-record-id {{
      font-size: 0.75rem;
      color: #666;
      margin-bottom: 1.5rem;
      font-family: monospace;
    }}
  </style>
</head>
<body>
  <div class="ik-record-id">record: {record_id}</div>
  {body_html}
</body>
</html>"""

    return page

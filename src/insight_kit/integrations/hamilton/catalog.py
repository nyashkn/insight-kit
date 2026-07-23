"""Measure catalog — the discoverable semantic layer over a Hamilton DAG.

An analyst agent composing a new metric needs to know what it can *stand on*:
which measures already exist, at what grain, and which are base (computed from
data) versus derived (computed from other measures). This module answers that
from the compiled graph and the ``@tag`` metadata alone — no execution, no data.

It is the interface the ephemeral agent reads before authoring a node: every
``MeasureSpec.measure`` is a name the agent can put in a Hamilton function
signature to reuse that measure's value, and (via the adapter) inherit a
claim->claim ``input_claims`` provenance edge for free.

    from insight_kit.integrations.hamilton import catalog
    from insight_kit.examples.growth_demo import dag

    cat = catalog([dag])
    print(cat.names())                      # ('arpu', 'blended_cac', ...)
    spec = cat.by_name("blended_cac")
    spec.grain, spec.claim_id               # ('window', 'DEMO-D-010')

Dimensions are surfaced per-measure as ``grain``/``filters`` (the selection the
measure was computed under); they are not yet first-class reusable objects.
Cites: T29 (input_claims), item 7 (lineage), issue #6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from insight_kit.libs.validation import mint_claim_id


@dataclass(frozen=True)
class MeasureSpec:
    """One governed measure the agent can reference by name.

    measure:         the node name — put this in a function signature to reuse it.
    claim_id:        the gate claim_id the measure emits (explicit ik_claim_id, or
                     minted identically to how the adapter will mint it at emit).
    metric_field:    the field name the value lands under (ik_metric).
    grain:           selection grain the measure is computed at (ik_grain).
    filters:         ik_filters string, if any (a coarse dimension marker).
    statement:       human-readable definition (ik_statement).
    fmt:             display hint (ik_fmt).
    tier:            requested lifecycle tier (ik_tier; draft/published).
    kind:            "base" (derives from data) or "derived" (derives from measures).
    direct_upstream: all direct graph dependencies of the node.
    derives_from:    the subset of direct_upstream that are themselves measures —
                     the claim->claim edges this measure will carry as input_claims.
    """

    measure: str
    claim_id: str | None
    metric_field: str | None
    grain: str | None
    filters: str | None
    statement: str | None
    fmt: str | None
    tier: str
    kind: str
    direct_upstream: tuple[str, ...]
    derives_from: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    """The measures defined across a set of Hamilton modules, plus raw inputs."""

    measures: tuple[MeasureSpec, ...]
    inputs: tuple[str, ...]

    def names(self) -> tuple[str, ...]:
        """Measure names, sorted — the vocabulary an agent can reference."""
        return tuple(m.measure for m in self.measures)

    def by_name(self, name: str) -> MeasureSpec | None:
        """The spec for a measure, or None if not defined."""
        return next((m for m in self.measures if m.measure == name), None)

    def base(self) -> tuple[MeasureSpec, ...]:
        """Measures computed from data (no upstream measures)."""
        return tuple(m for m in self.measures if m.kind == "base")

    def derived(self) -> tuple[MeasureSpec, ...]:
        """Measures computed from other measures (Layer-2+)."""
        return tuple(m for m in self.measures if m.kind == "derived")


def _claim_id_for(name: str, tags: dict[str, Any]) -> str:
    """The claim_id the measure emits — explicit ik_claim_id, else minted.

    Mirrors the adapter's ``_gen_metric_claim_id`` exactly (same namespace, tier
    token, seed, and digits), so the catalog advertises the id the run will emit.
    """
    explicit = tags.get("ik_claim_id")
    if explicit:
        return explicit
    return mint_claim_id(
        tags.get("ik_namespace", "IK"), tags.get("ik_id_tier", "D"), name, digits=3
    )


def catalog(modules: list[Any]) -> Catalog:
    """Build the measure catalog from Hamilton modules, statically.

    Compiles the graph (no execution) and reads ``@tag`` metadata + dependencies
    off every ``ik_emit="metric"`` node. A measure whose direct dependencies
    include another measure is ``derived``; otherwise ``base``.

    Raises ImportError if Hamilton is not installed.
    """
    try:
        from hamilton import driver
    except ImportError as e:  # pragma: no cover - exercised only without hamilton
        raise ImportError(
            "Hamilton not installed. Install with: pip install sf-hamilton>=1.83"
        ) from e

    dr = driver.Builder().with_modules(*modules).build()
    variables = dr.list_available_variables()

    # First pass: the set of measure node names, so derivation can be detected.
    measure_names = {
        v.name for v in variables if (getattr(v, "tags", {}) or {}).get("ik_emit") == "metric"
    }
    inputs = tuple(sorted(v.name for v in variables if getattr(v, "is_external_input", False)))

    specs: list[MeasureSpec] = []
    for v in variables:
        tags = getattr(v, "tags", {}) or {}
        if tags.get("ik_emit") != "metric":
            continue
        deps = tuple(
            sorted(
                set(getattr(v, "required_dependencies", ()) or ())
                | set(getattr(v, "optional_dependencies", ()) or ())
            )
        )
        derives_from = tuple(d for d in deps if d in measure_names)
        specs.append(
            MeasureSpec(
                measure=v.name,
                claim_id=_claim_id_for(v.name, tags),
                metric_field=tags.get("ik_metric"),
                grain=tags.get("ik_grain"),
                filters=tags.get("ik_filters"),
                statement=tags.get("ik_statement"),
                fmt=tags.get("ik_fmt"),
                tier=tags.get("ik_tier", "draft"),
                kind="derived" if derives_from else "base",
                direct_upstream=deps,
                derives_from=derives_from,
            )
        )

    specs.sort(key=lambda m: m.measure)
    return Catalog(measures=tuple(specs), inputs=inputs)


# The @tag contract for authoring a measure. Kept here — next to discovery —
# so the brief an agent reads to know WHAT exists also tells it HOW to add one,
# without hunting through adapter internals. (name, required?, description).
MEASURE_TAG_REFERENCE: tuple[tuple[str, bool, str], ...] = (
    ("ik_emit", True, 'must be "metric" — marks the node as a measure'),
    ("ik_metric", False, "field name the value lands under (default: slug of the node name)"),
    ("ik_claim_id", False, "explicit gate claim_id; else minted from namespace+tier+node name"),
    ("ik_namespace", False, '2-5 uppercase letters for a minted id (default "IK")'),
    ("ik_id_tier", False, 'id-grammar tier token D|R|C|I|V|X|ETL_[RCM] (default "D")'),
    ("ik_statement", False, "human-readable definition of the measure"),
    ("ik_grain", False, "selection grain, e.g. window/day/channel — match it when composing"),
    ("ik_filters", False, 'comma-separated k=v selection filters, e.g. "channel=meta"'),
    ("ik_date_window", False, "selection date window"),
    ("ik_baseline", False, "selection baseline"),
    ("ik_fmt", False, 'display format hint, e.g. ",.0f" or ".2f"'),
    ("ik_tier", False, 'lifecycle tier draft|published (default "draft")'),
)


def authoring_guide() -> str:
    """How to author a new measure — the @tag contract + the composition rule.

    Returned as text an agent can read before the COMPOSE step. The key rule an
    agent needs is the last line: reference an existing measure BY NAME in the
    new node's signature and the adapter records it as input_claims automatically.
    """
    lines = ["to add a measure: tag a Hamilton node with @tag(...):"]
    for name, required, desc in MEASURE_TAG_REFERENCE:
        flag = "required" if required else "optional"
        lines.append(f"  {name:16} ({flag}) {desc}")
    lines += [
        "",
        "to derive from existing measures: name them as parameters of the new node —",
        "Hamilton binds each kwarg to the measure of the same name, and the adapter",
        "records those measures as input_claims (claim->claim provenance) for free.",
        "Only compose measures that share the same grain.",
    ]
    return "\n".join(lines)


def format_catalog(cat: Catalog, *, authoring: bool = True) -> str:
    """Render the catalog as the brief an analyst agent reads before composing.

    With ``authoring=True`` (default) the render is self-contained: it appends
    the @tag authoring contract, so the same brief covers both discovering what
    measures exist and authoring a new one.
    """
    lines: list[str] = [f"measure catalog — {len(cat.measures)} measures"]
    if cat.inputs:
        lines.append(f"raw inputs: {', '.join(cat.inputs)}")
    lines.append("")
    for m in cat.measures:
        head = f"  {m.measure}  [{m.claim_id}]  ({m.kind}"
        if m.derives_from:
            head += f" <- {', '.join(m.derives_from)}"
        head += ")"
        lines.append(head)
        meta = f"    grain={m.grain or '-'}  field={m.metric_field or '-'}  tier={m.tier}"
        if m.filters:
            meta += f"  filters={m.filters}"
        lines.append(meta)
        if m.statement:
            lines.append(f"    {m.statement}")
    if authoring:
        lines += ["", authoring_guide()]
    return "\n".join(lines)

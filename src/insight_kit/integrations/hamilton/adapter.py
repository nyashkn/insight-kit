"""InsightKitHook — Hamilton NodeExecutionHook adapter wired onto the L1 gate.

T25 cutover (C8, C13, V1): the adapter no longer drives the legacy `Run` /
`Run.claim` path — that module is deleted. The hook now holds a `RunState` and
emits records through the frozen L1 gate (`ik_claim_emit`, I.emit). The L1 gate
imports no `hamilton` (C1/V5); this adapter — insight-kit's own code — may
import the gate.

A Hamilton @node tagged with `claim_tier` (or a failing node) produces a
`claim` record through the gate. A node failure additionally re-raises so the
Hamilton DAG still surfaces the error to the caller.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import structlog
from hamilton.lifecycle import GraphExecutionHook, NodeExecutionHook

from insight_kit.libs.validation import ValidationError, mint_claim_id
from insight_kit.platform.gate import (
    RecordRef,
    RunState,
    finalizeRun,
    ik_claim_emit,
    ik_research_emit,
    ik_skill_use_emit,
)

logger = structlog.get_logger("insight_kit.hamilton")


# ---------- helpers ----------


def _slug(s: str) -> str:
    """Lowercase, replace non-alphanumeric runs with underscores, strip edges.

    Local copy of the legacy provenance `_slug` (the legacy module is deleted at
    T25 cutover); the adapter still needs it to build claim ids from node names.
    """
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s.lower()).strip("_")


def _to_arrow(result: Any) -> Any | None:
    """Convert pandas/polars/dict-like to PyArrow table. Log warning if unconvertible."""
    import pyarrow as pa

    # already arrow
    if isinstance(result, pa.Table):
        return result

    # polars
    if hasattr(result, "to_arrow"):
        try:
            return result.to_arrow()
        except Exception as e:
            logger.warning("polars_to_arrow_failed", error=str(e), type=type(result).__name__)
            return None

    # pandas DataFrame
    try:
        # Check if it's a pandas DataFrame by checking for common attributes
        if hasattr(result, "columns") and hasattr(result, "index"):
            return pa.Table.from_pandas(result)
    except Exception as e:
        logger.warning("pandas_to_arrow_failed", error=str(e), type=type(result).__name__)

    # dict-of-lists
    if isinstance(result, dict):
        try:
            return pa.table(result)
        except Exception as e:
            logger.warning("dict_to_arrow_failed", error=str(e))
            return None

    # unconvertible
    logger.warning(
        "unconvertible_result_type",
        type=type(result).__name__,
        hint="emit won't be called for this node",
    )
    return None


def _hash_source(source_code: str) -> str:
    """SHA256 of source code."""
    return hashlib.sha256(source_code.encode()).hexdigest()


def compute_h_dlt_fingerprint(resource_name: str, schema: str) -> str:
    """T9/C8 — Compute h_dlt upstream fingerprint: sha256(resource_name + schema).

    Called at run_before_node_execution time when node_input_types is available,
    so registered upstreams supply real fingerprints rather than bare file paths.

    Args:
        resource_name: Identifier of the h_dlt source (e.g. 'h_dlt://metrics/revenue').
        schema: Schema version string (e.g. 'v2', JSON schema hash, column list).

    Returns:
        64-char hex sha256 string.
    """
    raw = (resource_name + schema).encode()
    return hashlib.sha256(raw).hexdigest()


# ---------- InsightKitHook ----------


class InsightKitHook(NodeExecutionHook, GraphExecutionHook):
    """Hamilton NodeExecutionHook adapter binding @node lifecycle to the L1 gate.

    The hook holds a `RunState` accumulator and a run directory. Every claim a
    tagged node produces is funnelled through `ik_claim_emit` — the same frozen
    gate every other writer uses (V1). Call `finalize()` once the DAG run is
    complete to seal the RunState (V10).

    Item 7 (deterministic lineage): the hook also implements GraphExecutionHook
    so it sees the compiled `HamiltonGraph` before execution. The per-node
    dependency map derived from that graph is code-derived — the same function
    signatures Hamilton compiled, not prose or heuristics — and each metric
    claim carries its node's full transitive upstream closure as a `lineage`
    field, with the extraction skill_use snapshot carrying the same trace next
    to the captured rows.
    """

    def __init__(
        self,
        run_state: RunState,
        run_dir: Path | str,
        *,
        emit_timestamp: str | None = None,
    ) -> None:
        """Init the hook with a gate RunState + run directory.

        Args:
            run_state: gate RunState accumulator; records emitted by tagged nodes
                       are registered here.
            run_dir:   run directory the gate writes records under.
            emit_timestamp: optional fixed ISO timestamp passed to knowledge-record
                       emits. The gate folds emit time into record fingerprints, so
                       the default (wall clock) makes record_ids per-run only;
                       supply a fixed timestamp for cross-run reproducible ids
                       (golden replays, cached pipelines).
        """
        self.run_state = run_state
        self.run_dir = Path(run_dir)
        self.emit_timestamp = emit_timestamp
        # Item 7 — populated by run_before_graph_execution from the compiled graph.
        self._graph_deps: dict[str, tuple[str, ...]] = {}
        self._graph_external: frozenset[str] = frozenset()
        self._graph_overrides: frozenset[str] = frozenset()
        # claim_ids already emitted by this hook — guards re-execute() on the same
        # RunState from emitting orphaned provenance for a claim the gate rejects.
        self._emitted_claim_ids: set[str] = set()
        # node_name -> the RecordRef of the claim that node emitted this run. A
        # downstream metric whose own kwargs are the *values* of these nodes cites
        # them as input_claims (claim->claim data lineage) — the provenance a
        # derived metric has instead of live input rows (issue #6 nugget).
        self._node_to_claim_ref: dict[str, RecordRef] = {}

    # ---------- graph lineage capture (item 7) ----------

    def run_before_graph_execution(
        self,
        *,
        graph: Any,
        final_vars: list[str],
        inputs: dict[str, Any],
        overrides: dict[str, Any],
        execution_path: Any,
        run_id: str,
        **future_kwargs: Any,
    ) -> None:
        """Capture the compiled graph's dependency structure before execution.

        `graph` is a hamilton.graph_types.HamiltonGraph; each HamiltonNode names
        its required/optional dependencies, so the upstream map is deterministic
        (derived from function signatures, not from execution traces).
        """
        deps: dict[str, tuple[str, ...]] = {}
        external: set[str] = set()
        for node in graph.nodes:
            required = set(getattr(node, "required_dependencies", ()) or ())
            optional = set(getattr(node, "optional_dependencies", ()) or ())
            deps[node.name] = tuple(sorted(required | optional))
            if getattr(node, "is_external_input", False):
                external.add(node.name)
        self._graph_deps = deps
        self._graph_external = frozenset(external)
        # Execute-time overrides replace a node's computed value with a
        # caller-supplied one — everything upstream of an overridden node is NOT
        # read this run, so the closure walk must stop there (else the stamped
        # lineage would assert sources that were never touched).
        self._graph_overrides = frozenset((overrides or {}).keys())
        logger.debug(
            "graph.lineage_captured",
            nodes=len(deps),
            external=len(external),
            overridden=sorted(self._graph_overrides),
        )

    def run_after_graph_execution(
        self,
        *,
        graph: Any,
        success: bool,
        error: Exception | None,
        run_id: str,
        **future_kwargs: Any,
    ) -> None:
        """No-op: the captured dependency map is kept for post-run queries."""

    def _lineage_for(self, node_name: str) -> dict[str, Any] | None:
        """Transitive upstream closure of a node from the captured graph.

        Returns None when no graph was captured (e.g. the hook is exercised
        outside a driver run) — the claim then simply carries no lineage field,
        it is never guessed.

        Overridden nodes truncate the walk: an execute-time override replaces
        that node's value with caller-supplied data, so its static upstreams
        were never read this run. They are excluded from the closure and the
        override point is recorded in ``overridden`` — a claim fed through an
        override says so on its face instead of asserting the bypassed sources.
        """
        if node_name not in self._graph_deps:
            return None
        direct = list(self._graph_deps[node_name])
        seen: set[str] = set()
        overridden: set[str] = set()
        stack = list(direct)
        while stack:
            upstream = stack.pop()
            if upstream in seen:
                continue
            seen.add(upstream)
            if upstream in self._graph_overrides:
                overridden.add(upstream)
                continue  # value came from the caller — do not walk past it
            stack.extend(self._graph_deps.get(upstream, ()))
        return {
            "node": node_name,
            "direct_upstream": direct,
            "upstream_closure": sorted(seen),
            "external_inputs": sorted(n for n in seen if n in self._graph_external),
            "overridden": sorted(overridden),
        }

    # Gate tier values accepted by the L1 schema (ClaimTier enum).
    _GATE_TIERS: frozenset[str] = frozenset({"draft", "published"})

    @classmethod
    def _to_gate_tier(cls, hamilton_tier: str) -> str:
        """Map a Hamilton @tag claim_tier value to a valid gate ClaimTier.

        The gate schema only accepts 'draft' | 'published'. Hamilton-specific
        tiers (derived, critic, etl_raw, etl_clean, etl_metric, viz,
        counterfactual, initiative) carry semantics internal to the DAG; they
        land as 'draft' at the gate so the record is emitted without rejection.
        Only a node explicitly tagged claim_tier='published' produces a
        published-tier gate record.
        """
        return hamilton_tier if hamilton_tier in cls._GATE_TIERS else "draft"

    # ---------- gate emit ----------

    def _emit_claim(self, claim_id: str, statement: str, *, tier: str, node_name: str) -> None:
        """Emit a claim record through the L1 gate (I.emit, V1).

        The Hamilton notion of a claim (a statement + a node-derived tier) maps
        onto a gate `claim` record: the statement and the originating node are
        carried as claim fields. The Hamilton-specific tier value is stored in
        the `claim_tier` field for traceability; the gate-level `tier=` is
        always a valid ClaimTier ('draft' | 'published'). Gate rejects (e.g.
        claim-id-format) are logged, never raised — a node-level emit failure
        must not abort the DAG.
        """
        gate_tier = self._to_gate_tier(tier)
        try:
            ik_claim_emit(
                claim_id,
                {
                    "statement": statement,
                    "node_id": node_name,
                    "claim_tier": tier,
                },
                tier=gate_tier,
                run_state=self.run_state,
                run_dir=self.run_dir,
            )
            logger.info(
                "claim.emitted",
                claim_id=claim_id,
                node=node_name,
                tier=gate_tier,
                hamilton_tier=tier,
            )
        except ValidationError as e:
            logger.error("claim.emit_rejected", claim_id=claim_id, node=node_name, error=str(e))
        except Exception as e:
            logger.error("claim.emit_failed", claim_id=claim_id, node=node_name, error=str(e))

    def finalize(self) -> RunState:
        """Seal the RunState once the DAG run is complete (V10, idempotent)."""
        return finalizeRun(self.run_state, assert_manifest=False)

    def run_before_node_execution(
        self,
        *,
        node_name: str,
        node_tags: dict[str, Any],
        node_kwargs: dict[str, Any],
        node_input_types: dict[str, Any] | None = None,
        **future_kwargs: Any,
    ) -> None:
        """Invoked before each Hamilton node executes.

        T9/C8: node_input_types is captured explicitly (not dropped via **future_kwargs)
        so that h_dlt fingerprints can be computed for registered upstream inputs.

        Args:
            node_name: name of the node (function name)
            node_tags: dict of tags on the node
            node_kwargs: kwargs passed to node (inputs)
            node_input_types: dict mapping input name → type annotation (from Hamilton).
                             Captured here for h_dlt fingerprint computation (C8).
            **future_kwargs: catch future Hamilton additions
        """
        if node_input_types:
            # T9/C8: compute h_dlt fingerprints for registered upstream inputs.
            # The fingerprint sha256(resource_name + schema) is available at hook time
            # so downstream emit calls can supply registered_input provenance.
            for input_name, input_type in node_input_types.items():
                schema_str = str(input_type)
                fp = compute_h_dlt_fingerprint(input_name, schema_str)
                logger.debug(
                    "h_dlt_fingerprint_computed",
                    node=node_name,
                    input_name=input_name,
                    schema=schema_str,
                    fingerprint=fp[:16],  # log prefix only
                )

    def run_after_node_execution(
        self,
        *,
        node_name: str,
        node_tags: dict[str, Any],
        node_kwargs: dict[str, Any],
        node_return_type: type,
        result: Any,
        error: Exception | None,
        success: bool,
        task_id: str | None,
        run_id: str,
        **future_kwargs: Any,
    ) -> None:
        """Invoked after each Hamilton node executes.

        Args:
            node_name: name of the node (function name)
            node_tags: dict of tags on the node
            node_kwargs: kwargs passed to node (inputs)
            node_return_type: type hint of node return
            result: return value if success=True
            error: Exception if success=False
            success: whether node executed without exception
            task_id: optional Hamilton task ID
            run_id: optional Hamilton run ID
            **future_kwargs: catch future Hamilton additions
        """
        logger.debug("node_executed", node=node_name, tags=node_tags, success=success)

        # Handle failure: emit a claim record documenting the failure, then let
        # Hamilton re-raise the original error to the DAG caller.
        if not success and error is not None:
            claim_id = self._gen_claim_id(
                "critic",
                node_name,
                node_tags.get("claim_id"),
            )
            self._emit_claim(
                claim_id,
                f"Node {node_name} failed during execution: {type(error).__name__}: {error}",
                tier="critic",
                node_name=node_name,
            )
            logger.info(
                "node.failure.claim",
                node=node_name,
                claim_id=claim_id,
                error_type=type(error).__name__,
            )
            return

        if not success:
            return

        # On success: hardened metric path — a node tagged ik_emit="metric"
        # emits a typed claim whose value is the metric and whose registered
        # input is the node's own input rows (V22 registered_input).
        if node_tags.get("ik_emit") == "metric":
            self._emit_metric_from_node(node_name, result, node_kwargs, node_tags)

        # On success: legacy statement path — a node tagged claim_tier emits a
        # statement claim. Independent of the metric path above.
        if node_tags.get("claim_tier"):
            self._emit_claim_from_node(node_name, result, node_tags)

    # ---------- emit methods ----------

    def _emit_claim_from_node(self, node_name: str, result: Any, node_tags: dict[str, Any]) -> None:
        """Emit a structured claim record based on @tag(claim_tier=...)."""
        claim_tier = node_tags.get("claim_tier", "derived")
        claim_statement = node_tags.get("claim_statement")
        claim_id = self._gen_claim_id(
            claim_tier,
            node_name,
            node_tags.get("claim_id"),
        )

        if not claim_statement:
            logger.warning("claim.skip_no_statement", node=node_name, claim_id=claim_id)
            return

        self._emit_claim(claim_id, claim_statement, tier=claim_tier, node_name=node_name)

    # ---------- hardened metric emit (ik_emit="metric") ----------

    def _emit_metric_from_node(
        self,
        node_name: str,
        result: Any,
        node_kwargs: dict[str, Any],
        node_tags: dict[str, Any],
    ) -> None:
        """Emit a typed metric claim, fingerprinting the node's input rows (V22).

        A node tagged ``ik_emit="metric"`` asserts a measured value. The claim's
        registered input is the node's own input rows (``node_kwargs``), so the
        fingerprint is over *values*, not source text — a CAC that was not
        computed from live rows (a hardcoded literal, a value read off code) has
        no registered input, lands as ``data_fingerprint_source=payload``, and
        cannot publish (T7). That is the P1 "verdict-from-proxy" guard.

        Tags consumed:
          ik_metric     — field name for the asserted value (default: slug(node)).
          ik_claim_id   — explicit gate claim_id; else generated from namespace+tier.
          ik_namespace  — 2-5 letter namespace for a generated id (default "IK").
          ik_id_tier    — id-grammar tier token D|R|C|I|V|X|ETL_[RCM] (default "D").
          ik_fmt        — fmt_hint carried on the field.
          ik_tier       — gate lifecycle tier draft|published|critic (default draft).
          ik_grain / ik_date_window / ik_baseline / ik_filters — selection params (V15).
        """
        metric = node_tags.get("ik_metric") or _slug(node_name)
        claim_id = self._gen_metric_claim_id(
            node_tags.get("ik_namespace", "IK"),
            node_tags.get("ik_id_tier", "D"),
            node_name,
            node_tags.get("ik_claim_id"),
        )
        # Re-executing the same driver/RunState would re-derive this claim_id;
        # the gate rejects the duplicate claim AFTER the provenance records land,
        # orphaning them. Skip the whole emission up front instead — a re-run
        # needs a fresh RunState/driver, not a silently half-written bundle.
        if claim_id in self._emitted_claim_ids:
            logger.warning(
                "metric.claim.duplicate_skipped",
                claim_id=claim_id,
                node=node_name,
                hint="one execute() per RunState — build a fresh driver/RunState to re-run",
            )
            return
        value = self._extract_metric_value(result, metric)
        fields: dict[str, Any] = {
            metric: {"value": value, "fmt_hint": node_tags.get("ik_fmt")},
            "node_id": {"value": node_name, "fmt_hint": None},
        }
        if node_tags.get("ik_statement"):
            fields["statement"] = {"value": node_tags["ik_statement"], "fmt_hint": None}
        # Item 7 — deterministic lineage: the node's transitive upstream closure
        # from the compiled graph rides on the claim itself, so the ProvenanceRail
        # (and any critic) can see where the number came from without re-running.
        lineage = self._lineage_for(node_name)
        if lineage is not None:
            fields["lineage"] = {"value": lineage, "fmt_hint": None}
        selection = self._build_selection(node_tags)
        input_data = self._rows_as_input_data(node_kwargs)
        gate_tier = self._to_gate_tier(node_tags.get("ik_tier", "draft"))

        # Provenance chain (item 1): when the node has live input rows, emit the
        # knowledge records the claim cites, so the claim is backed by a real
        # research/skill_use chain — not just a fingerprint. A node with no
        # convertible input rows emits a claim-only record (payload provenance),
        # which is the correct P1 outcome (a value with no live upstream).
        cites = self._emit_metric_provenance(
            node_name, node_kwargs, input_data, node_tags, claim_id, lineage=lineage
        )

        # Claim->claim data lineage (T29 / issue #6): when a metric node's own
        # inputs are the values of upstream claim-emitting nodes (a Hamilton kwarg
        # binds to the node of the same name), record those claims as input_claims.
        # Hamilton executes topologically, so an upstream metric has already
        # emitted and registered its ref by the time this node runs. A Layer-2
        # metric (e.g. payback = arpu / blended_cac) has no live input rows of its
        # own — these edges are the provenance it carries in their place.
        input_claims = [
            self._node_to_claim_ref[dep].record_id
            for dep in node_kwargs
            if dep in self._node_to_claim_ref
        ]

        try:
            ref = ik_claim_emit(
                claim_id,
                fields,
                tier=gate_tier,
                selection=selection,
                cites=cites or None,
                input_claims=input_claims or None,
                run_state=self.run_state,
                run_dir=self.run_dir,
                input_data=input_data,
            )
            self._emitted_claim_ids.add(claim_id)
            self._node_to_claim_ref[node_name] = ref
            logger.info(
                "metric.claim.emitted",
                claim_id=claim_id,
                node=node_name,
                metric=metric,
                value=value,
                registered_input=input_data is not None,
                cites=cites,
                tier=gate_tier,
            )
        except ValidationError as e:
            logger.error("metric.claim.rejected", claim_id=claim_id, node=node_name, error=str(e))
        except Exception as e:  # emit failure must never abort the DAG
            logger.error("metric.claim.failed", claim_id=claim_id, node=node_name, error=str(e))

    def _emit_metric_provenance(
        self,
        node_name: str,
        node_kwargs: dict[str, Any],
        input_data: dict[str, Any] | None,
        node_tags: dict[str, Any],
        claim_id: str,
        *,
        lineage: dict[str, Any] | None = None,
    ) -> list[str]:
        """Emit the knowledge records a metric claim cites (item 1).

        Returns the list of record_ids the claim should cite:
          * skill_use — the data extraction: the node's input rows as the
            captured snapshot, tool="hamilton", source = the upstream node names.
            Emitted whenever live input rows are present. The snapshot carries
            the rows under ``input_rows`` and (item 7) the node's deterministic
            upstream ``lineage`` next to them, so a trace from claim → rows →
            graph position needs no re-execution.
          * research  — optional: only when the node is tagged with
            ``ik_research_source`` (and/or ``ik_research_query``), capturing an
            external doc/source the metric relied on. A pure compute node has no
            research, so none is faked.

        Emit failures here are logged and swallowed — a missing knowledge record
        degrades the claim to uncited, it must not abort the DAG.
        """
        if not input_data:
            return []  # no live rows → no knowledge chain (payload claim)

        cites: list[str] = []
        source = ",".join(node_kwargs.keys()) or node_name

        # Optional research record (only if the node declares an external source).
        research_source = node_tags.get("ik_research_source")
        if research_source:
            try:
                research_ref = ik_research_emit(
                    f"{claim_id}-RESEARCH",
                    node_tags.get("ik_research_ref", f"research:{node_name}"),
                    node_tags.get("ik_research_query", ""),
                    research_source,
                    snapshot={"source": research_source, "node": node_name},
                    timestamp=self.emit_timestamp,
                    run_state=self.run_state,
                    run_dir=self.run_dir,
                )
                cites.append(research_ref.record_id)
            except Exception as e:
                logger.error("metric.research.failed", node=node_name, error=str(e))

        # skill_use record — the extraction the claim is computed from. The
        # snapshot pairs the captured rows with the node's graph lineage; the
        # input_data= param stays the bare rows so the data fingerprint is over
        # values only (V22), independent of graph shape.
        snapshot: dict[str, Any] = {"input_rows": input_data}
        if lineage is not None:
            snapshot["lineage"] = lineage
        try:
            skill_ref = ik_skill_use_emit(
                f"{claim_id}-EXTRACT",
                f"hamilton:{node_name}",
                "hamilton",
                source,
                snapshot=snapshot,
                timestamp=self.emit_timestamp,
                cites=cites or None,
                run_state=self.run_state,
                run_dir=self.run_dir,
                input_data=input_data,
            )
            cites.append(skill_ref.record_id)
        except Exception as e:
            logger.error("metric.skill_use.failed", node=node_name, error=str(e))

        return cites

    @classmethod
    def _gen_metric_claim_id(
        cls,
        namespace: str,
        id_tier: str,
        node_name: str,
        explicit: str | None = None,
    ) -> str:
        """Generate a claim_id that satisfies the gate grammar.

        Grammar (libs.validation.CLAIM_ID_REGEX):
            ^[A-Z]{2,5}-(D|R|C|I|V|X|ETL_[RCM])-\\d{3,}$

        Explicit > generated. A generated id derives a stable 3-digit sequence
        from a hash of the node name (via the shared libs.validation minter) so
        the same node yields the same id across runs without shared counter state.
        """
        if explicit:
            return explicit
        return mint_claim_id(namespace, id_tier, node_name, digits=3)

    @staticmethod
    def _extract_metric_value(result: Any, metric: str) -> Any:
        """Pull the asserted scalar from a metric node's return.

        Accepts a plain number (preferred), or an Arrow-convertible table with a
        column named `metric` (last row wins). Falls back to str() for anything
        else so the claim still records something inspectable.
        """
        if isinstance(result, bool):
            return result
        if isinstance(result, (int, float)):
            return result
        arrow = _to_arrow(result)
        if arrow is not None and metric in getattr(arrow, "column_names", []):
            col = arrow.column(metric).to_pylist()
            if col:
                return col[-1]
        if isinstance(result, str):
            return result
        return str(result)

    @staticmethod
    def _build_selection(node_tags: dict[str, Any]) -> dict[str, Any] | None:
        """Assemble explicit SelectionParams (V15) from ik_* tags.

        `ik_filters` is a comma-separated `k=v` string (e.g.
        "customer_order_index=1,channel=meta") parsed into a filters dict.
        Returns None when no selection tags are present.
        """
        sel: dict[str, Any] = {}
        if node_tags.get("ik_grain"):
            sel["grain"] = node_tags["ik_grain"]
        if node_tags.get("ik_date_window"):
            sel["date_window"] = node_tags["ik_date_window"]
        if node_tags.get("ik_baseline"):
            sel["baseline"] = node_tags["ik_baseline"]
        raw_filters = node_tags.get("ik_filters")
        if raw_filters:
            fdict: dict[str, str] = {}
            for part in str(raw_filters).split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    fdict[k.strip()] = v.strip()
            if fdict:
                sel["filters"] = fdict
        return sel or None

    @staticmethod
    def _rows_as_input_data(node_kwargs: dict[str, Any]) -> dict[str, Any] | None:
        """Build a registered-input dict from a node's input rows (V22).

        Each Arrow-convertible input becomes a JSON-safe column dict; scalar
        inputs ride along ONLY next to at least one row table. A node fed
        nothing but scalars (e.g. ``cac(spend: float, customers: float)``) gets
        None — payload provenance, cannot publish. Bare literals are exactly
        the P1 verdict-from-proxy shape; letting them register as live input
        would launder a hardcoded number into publishable provenance.
        """
        data: dict[str, Any] = {}
        has_rows = False
        for name, val in node_kwargs.items():
            arrow = _to_arrow(val)
            if arrow is not None:
                try:
                    # json round-trip with default=str guarantees serializability
                    # (e.g. Arrow date/timestamp cells) before the gate fingerprints it.
                    data[name] = json.loads(json.dumps(arrow.to_pydict(), default=str))
                    has_rows = True
                except Exception as e:
                    logger.warning("metric.input_rows_skipped", input=name, error=str(e))
            elif val is None or isinstance(val, (int, float, str, bool)):
                data[name] = val
        if not has_rows:
            return None
        return data

    # ---------- claim id generation ----------

    @staticmethod
    def _gen_claim_id(tier: str, node_name: str, explicit_id: str | None = None) -> str:
        """Generate claim_id: explicit > auto from tier + slug(node_name).

        Convention: {tier_prefix}-{slug(node_name)}
        tier_prefix: derived→D, critic→C, raw→R, etc.
        """
        if explicit_id:
            return explicit_id

        tier_map = {
            "derived": "D",
            "critic": "C",
            "raw": "R",
            "etl_raw": "ETL-R",
            "etl_clean": "ETL-S",
            "etl_metric": "ETL-M",
            "viz": "VIZ",
            "counterfactual": "CF",
            "initiative": "INIT",
        }
        prefix = tier_map.get(tier, tier.upper()[:3])
        slug = _slug(node_name)
        return f"{prefix}-{slug}"


# ---------- driver builder ----------


def build_driver(
    run_state: RunState,
    run_dir: Path | str,
    modules: list[Any],
    *,
    emit_timestamp: str | None = None,
) -> Any:
    """Construct a Hamilton Driver with a gate-backed InsightKitHook adapter.

    One driver + RunState pair per execute(): re-running a metric node against
    the same RunState re-derives the same claim_id, which the hook skips (with
    a warning) rather than emitting a duplicate the gate would reject.

    Args:
        run_state: gate RunState accumulator the hook emits records into.
        run_dir:   run directory the gate writes records under.
        modules:   Hamilton modules (list of Python modules or module objects).
        emit_timestamp: optional fixed ISO timestamp for knowledge-record emits —
                   makes record ids reproducible across identical runs (see
                   InsightKitHook).

    Returns:
        hamilton.driver.Driver instance ready to execute.

    Example:
        from hamilton import driver
        from insight_kit.platform.gate import RunState
        from insight_kit.integrations.hamilton import build_driver
        import my_hamilton_module

        run_state = RunState(run_dir=run_dir)
        dr = build_driver(run_state, run_dir, [my_hamilton_module])
        result = dr.execute(["my_node"])
    """
    try:
        from hamilton import driver
    except ImportError as e:
        raise ImportError(
            "Hamilton not installed. Install with: pip install sf-hamilton[visualization,caching]>=1.83"
        ) from e

    # Build driver with the gate-backed InsightKit hook attached
    builder = (
        driver.Builder()
        .with_modules(*modules)
        .with_adapters(InsightKitHook(run_state, run_dir, emit_timestamp=emit_timestamp))
    )

    dr = builder.build()
    logger.info("driver.built", modules_count=len(modules))
    return dr

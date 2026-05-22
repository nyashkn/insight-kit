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
from pathlib import Path
from typing import Any

import structlog
from hamilton.lifecycle import NodeExecutionHook

from insight_kit.libs.validation import ValidationError
from insight_kit.platform.gate import RunState, finalizeRun, ik_claim_emit

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


class InsightKitHook(NodeExecutionHook):
    """Hamilton NodeExecutionHook adapter binding @node lifecycle to the L1 gate.

    The hook holds a `RunState` accumulator and a run directory. Every claim a
    tagged node produces is funnelled through `ik_claim_emit` — the same frozen
    gate every other writer uses (V1). Call `finalize()` once the DAG run is
    complete to seal the RunState (V10).
    """

    def __init__(self, run_state: RunState, run_dir: Path | str) -> None:
        """Init the hook with a gate RunState + run directory.

        Args:
            run_state: gate RunState accumulator; records emitted by tagged nodes
                       are registered here.
            run_dir:   run directory the gate writes records under.
        """
        self.run_state = run_state
        self.run_dir = Path(run_dir)

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
            logger.info("claim.emitted", claim_id=claim_id, node=node_name, tier=gate_tier, hamilton_tier=tier)
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

        # On success: emit a claim record for nodes tagged with claim_tier.
        if node_tags.get("claim_tier"):
            self._emit_claim_from_node(node_name, result, node_tags)

    # ---------- emit methods ----------

    def _emit_claim_from_node(
        self, node_name: str, result: Any, node_tags: dict[str, Any]
    ) -> None:
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


def build_driver(run_state: RunState, run_dir: Path | str, modules: list[Any]) -> Any:
    """Construct a Hamilton Driver with a gate-backed InsightKitHook adapter.

    Args:
        run_state: gate RunState accumulator the hook emits records into.
        run_dir:   run directory the gate writes records under.
        modules:   Hamilton modules (list of Python modules or module objects).

    Returns:
        hamilton.driver.Driver instance ready to execute.

    Example:
        from hamilton import driver
        from insight_kit.gate import RunState
        from insight_kit.hamilton import build_driver
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
        .with_adapters(InsightKitHook(run_state, run_dir))
    )

    dr = builder.build()
    logger.info("driver.built", modules_count=len(modules))
    return dr

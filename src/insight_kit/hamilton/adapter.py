"""InsightKitHook — Hamilton NodeExecutionHook adapter for Run provenance."""

from __future__ import annotations

import hashlib
from typing import Any

import structlog
from hamilton.lifecycle import NodeExecutionHook

from insight_kit.provenance.run import Run, _slug

logger = structlog.get_logger("insight_kit.hamilton")


# ---------- type conversion helpers ----------


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


# ---------- InsightKitHook ----------


class InsightKitHook(NodeExecutionHook):
    """Hamilton NodeExecutionHook adapter binding @node lifecycle to Run provenance."""

    def __init__(self, run: Run) -> None:
        """Init hook with a Run context.

        Args:
            run: Active Run context manager
        """
        self.run = run

    def run_before_node_execution(
        self,
        *,
        node_name: str,
        node_tags: dict[str, Any],
        node_kwargs: dict[str, Any],
        **future_kwargs: Any,
    ) -> None:
        """Invoked before each Hamilton node executes.

        Args:
            node_name: name of the node (function name)
            node_tags: dict of tags on the node
            node_kwargs: kwargs passed to node (inputs)
            **future_kwargs: catch future Hamilton additions
        """
        # Pre-execution hook - can be used for setup if needed
        pass

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

        # Handle failure: emit critic-tier claim documenting the failure
        if not success and error is not None:
            claim_id = self._gen_claim_id(
                "critic",
                node_name,
                node_tags.get("claim_id"),
            )
            self.run.claim(
                claim_id=claim_id,
                statement=f"Node {node_name} failed during execution: {type(error).__name__}",
                tier="critic",
                node_id=node_name,
                confidence="high",
                caveats=[str(error)],
            )
            logger.info(
                "node.failure.claim",
                node=node_name,
                claim_id=claim_id,
                error_type=type(error).__name__,
            )
            return

        # On success: check for emit/claim tags
        if not success:
            return

        # Emit metric if tagged
        if node_tags.get("emit") == "metric":
            self._emit_metric_from_node(node_name, result, node_tags)

        # Emit critique if tagged
        if node_tags.get("emit") == "critique":
            self._emit_critique_from_node(node_name, result, node_tags)

        # Emit viz if tagged
        if node_tags.get("emit") == "viz":
            self._emit_viz_from_node(node_name, result, node_tags)

        # Emit claim if tagged
        if node_tags.get("claim_tier"):
            self._emit_claim_from_node(node_name, result, node_tags)

    # ---------- emit methods ----------

    def _emit_metric_from_node(
        self, node_name: str, result: Any, node_tags: dict[str, Any]
    ) -> None:
        """Emit result as metric if convertible to arrow."""
        arrow_result = _to_arrow(result)
        if arrow_result is None:
            logger.warning("metric_emit.skip_unconvertible", node=node_name)
            return

        layer = node_tags.get("layer", "metrics")
        try:
            self.run.emit_metric(arrow_result, name=node_name, duckdb_view=None)
            logger.info("metric.emitted", node=node_name, layer=layer)
        except Exception as e:
            logger.error("metric.emit_failed", node=node_name, error=str(e))

    def _emit_critique_from_node(
        self, node_name: str, result: Any, node_tags: dict[str, Any]
    ) -> None:
        """Emit result as critique if convertible."""
        arrow_result = _to_arrow(result)
        if arrow_result is None:
            logger.warning("critique_emit.skip_unconvertible", node=node_name)
            return

        try:
            self.run.emit_critique(arrow_result, name=node_name)
            logger.info("critique.emitted", node=node_name)
        except Exception as e:
            logger.error("critique.emit_failed", node=node_name, error=str(e))

    def _emit_viz_from_node(self, node_name: str, result: Any, node_tags: dict[str, Any]) -> None:
        """Emit result as viz (assume JSON-serializable spec)."""
        if not isinstance(result, (dict, list)):
            logger.warning(
                "viz.emit_skip.not_json",
                node=node_name,
                type=type(result).__name__,
            )
            return

        try:
            self.run.emit_viz(result, name=node_name)
            logger.info("viz.emitted", node=node_name)
        except Exception as e:
            logger.error("viz.emit_failed", node=node_name, error=str(e))

    def _emit_claim_from_node(
        self, node_name: str, result: Any, node_tags: dict[str, Any]
    ) -> None:
        """Emit a structured claim based on @tag(claim_tier=...)."""
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

        try:
            self.run.claim(
                claim_id=claim_id,
                statement=claim_statement,
                tier=claim_tier,  # type: ignore[arg-type]
                node_id=node_name,
                confidence=node_tags.get("confidence", "medium"),  # type: ignore[arg-type]
            )
            logger.info("claim.emitted", claim_id=claim_id, node=node_name, tier=claim_tier)
        except Exception as e:
            logger.error("claim.emit_failed", claim_id=claim_id, error=str(e))

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


def build_driver(run: Run, modules: list[Any]) -> Any:
    """Construct a Hamilton Driver with InsightKitHook adapter.

    Args:
        run: Active Run context
        modules: Hamilton modules (can be list of Python modules or module objects)

    Returns:
        hamilton.driver.Driver instance ready to execute

    Example:
        from hamilton import driver
        from insight_kit import Run
        from insight_kit.hamilton import build_driver
        import my_hamilton_module

        with Run(topic="analytics", agent="analyst") as r:
            dr = build_driver(r, [my_hamilton_module])
            result = dr.execute(["my_node"])
    """
    try:
        from hamilton import driver
    except ImportError as e:
        raise ImportError(
            "Hamilton not installed. Install with: pip install sf-hamilton[visualization,caching]>=1.83"
        ) from e

    # Build driver with InsightKit hook attached
    builder = driver.Builder().with_modules(*modules).with_adapters(InsightKitHook(run))

    dr = builder.build()
    logger.info("driver.built", modules_count=len(modules))
    return dr

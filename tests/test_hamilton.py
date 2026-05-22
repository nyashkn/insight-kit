"""Unit + e2e tests for the gate-backed Hamilton adapter (T25 cutover).

The InsightKitHook is rewired onto the L1 gate (C8, V1): it holds a RunState +
run_dir and emits `claim` records through `ik_claim_emit`. These tests exercise
the adapter against the frozen gate, not the deleted legacy `Run` model.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from insight_kit.gate import RunState

# Try importing Hamilton; skip all tests if not available
HAS_HAMILTON = False
try:
    import pyarrow as pa
    from hamilton import driver  # noqa: F401  (availability gate)
    from hamilton.function_modifiers import tag  # noqa: F401  (availability gate)
    HAS_HAMILTON = True
except ImportError:
    pass


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """A bare run directory the gate writes records under."""
    d = tmp_path / "run"
    d.mkdir()
    return d


# Skip entire module if Hamilton not installed
pytestmark = pytest.mark.skipif(not HAS_HAMILTON, reason=f"Hamilton not installed: {HAS_HAMILTON}")


# ---------- helper: create test Hamilton modules (as .py files) ----------


def _create_module_from_code(name: str, code: str):
    """Create a module from source code string."""
    spec = importlib.util.spec_from_loader(name, loader=None)
    mod = importlib.util.module_from_spec(spec)
    exec(code, mod.__dict__)
    sys.modules[name] = mod
    return mod


def _make_metric_module():
    """Sample Hamilton module with a plain (untagged) node."""
    code = """
import pyarrow as pa
from hamilton.function_modifiers import tag

def daily_revenue() -> pa.Table:
    return pa.table({"day": [1, 2, 3], "rev": [100, 200, 150]})
"""
    return _create_module_from_code("hamilton_metric_mod", code)


def _make_claim_module():
    """Sample Hamilton module with a @claim_tier node carrying an explicit claim_id."""
    code = """
import pyarrow as pa
from hamilton.function_modifiers import tag

def daily_revenue() -> pa.Table:
    return pa.table({"day": [1, 2, 3], "rev": [100, 200, 150]})

@tag(claim_tier="derived", claim_statement="revenue trend is positive", claim_id="TEST-D-001")
def trend_check(daily_revenue: pa.Table) -> str:
    return "positive"
"""
    return _create_module_from_code("hamilton_claim_mod", code)


def _make_fail_module():
    """Sample Hamilton module with a node that raises."""
    code = """
import pyarrow as pa
from hamilton.function_modifiers import tag

def boom() -> pa.Table:
    raise RuntimeError("synthetic failure")
"""
    return _create_module_from_code("hamilton_fail_mod", code)


# ---------- Unit tests ----------


def test_hook_attaches_to_run_state(run_dir: Path) -> None:
    """InsightKitHook stores the RunState + run_dir references."""
    from insight_kit.hamilton import InsightKitHook

    rs = RunState(run_dir=run_dir)
    hook = InsightKitHook(rs, run_dir)
    assert hook.run_state is rs
    assert hook.run_dir == run_dir


def test_gen_claim_id_explicit() -> None:
    """Claim ID: explicit override."""
    from insight_kit.hamilton import InsightKitHook

    cid = InsightKitHook._gen_claim_id("derived", "my_node", explicit_id="CUSTOM-123")
    assert cid == "CUSTOM-123"


def test_gen_claim_id_derived() -> None:
    """Claim ID: auto from derived tier."""
    from insight_kit.hamilton import InsightKitHook

    cid = InsightKitHook._gen_claim_id("derived", "daily_revenue")
    assert cid == "D-daily_revenue"


def test_gen_claim_id_critic() -> None:
    """Claim ID: auto from critic tier."""
    from insight_kit.hamilton import InsightKitHook

    cid = InsightKitHook._gen_claim_id("critic", "data_quality_check")
    assert cid == "C-data_quality_check"


def test_gen_claim_id_etl_raw() -> None:
    """Claim ID: auto from ETL raw tier."""
    from insight_kit.hamilton import InsightKitHook

    cid = InsightKitHook._gen_claim_id("etl_raw", "shopify_orders")
    assert cid == "ETL-R-shopify_orders"


def test_to_arrow_from_pyarrow() -> None:
    """Conversion: PyArrow table passthrough."""
    from insight_kit.hamilton.adapter import _to_arrow

    t = pa.table({"x": [1, 2]})
    result = _to_arrow(t)
    assert result is t


def test_to_arrow_from_dict_of_lists() -> None:
    """Conversion: dict-of-lists → PyArrow."""
    from insight_kit.hamilton.adapter import _to_arrow

    d = {"x": [1, 2, 3], "y": [4, 5, 6]}
    result = _to_arrow(d)
    assert isinstance(result, pa.Table)
    assert result.num_rows == 3


def test_to_arrow_from_pandas() -> None:
    """Conversion: pandas DataFrame → PyArrow."""
    pd = pytest.importorskip("pandas")
    from insight_kit.hamilton.adapter import _to_arrow

    df = pd.DataFrame({"x": [1, 2, 3]})
    result = _to_arrow(df)
    assert isinstance(result, pa.Table)
    assert result.num_rows == 3


def test_to_arrow_from_polars() -> None:
    """Conversion: polars DataFrame → PyArrow."""
    pytest.importorskip("polars")
    import polars as pl

    from insight_kit.hamilton.adapter import _to_arrow

    df = pl.DataFrame({"x": [1, 2, 3]})
    result = _to_arrow(df)
    assert isinstance(result, pa.Table)
    assert result.num_rows == 3


def test_to_arrow_unconvertible() -> None:
    """Conversion: unconvertible type logs warning, returns None."""
    from insight_kit.hamilton.adapter import _to_arrow

    result = _to_arrow("not a dataframe")
    assert result is None


# ---------- E2E tests against the gate ----------


def test_hamilton_plain_node_executes(run_dir: Path) -> None:
    """E2E: a plain (untagged) Hamilton node runs; no claim is emitted."""
    from insight_kit.hamilton import build_driver

    mod = _make_metric_module()
    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [mod])
    out = dr.execute(["daily_revenue"])
    assert isinstance(out["daily_revenue"], pa.Table)
    assert out["daily_revenue"].num_rows == 3
    # untagged node → no record emitted
    assert rs.records == []


def test_hamilton_claim_node_emits_through_gate(run_dir: Path) -> None:
    """E2E: a @claim_tier node emits a `claim` record through the L1 gate (V1)."""
    from insight_kit.gate.store import read_record
    from insight_kit.hamilton import build_driver

    mod = _make_claim_module()
    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [mod])
    out = dr.execute(["daily_revenue", "trend_check"])
    assert out["trend_check"] == "positive"

    # the gate registered exactly one claim record
    assert len(rs.records) == 1
    ref = rs.records[0]
    assert ref.record_type == "claim"

    # record.json was written under the run dir and carries the claim fields
    rec = read_record(run_dir, ref.record_id)
    assert rec["claim_id"] == "TEST-D-001"
    assert rec["fields"]["statement"]["value"] == "revenue trend is positive"
    assert rec["fields"]["node_id"]["value"] == "trend_check"
    # Fix 1 regression guard: gate tier= keyword must be passed correctly.
    # 'derived' is a Hamilton-internal tier; it maps to gate tier 'draft'.
    # The Hamilton tier is preserved in fields["claim_tier"] for traceability.
    assert rec["tier"] == "draft"
    assert rec["fields"]["claim_tier"]["value"] == "derived"


def test_hamilton_failure_raises_exception(run_dir: Path) -> None:
    """E2E: a node failure still raises to the DAG caller, and a critic claim is recorded.

    The auto-generated failure claim id (`C-boom`) does not match the gate
    claim-id regex, so the gate rejects it — the hook logs the reject and never
    raises from emit. The original RuntimeError must still surface.
    """
    from insight_kit.hamilton import build_driver

    mod = _make_fail_module()
    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [mod])
    with pytest.raises(RuntimeError, match="synthetic failure"):
        dr.execute(["boom"])


def test_hamilton_failure_emits_critic_claim_with_valid_id(run_dir: Path) -> None:
    """E2E: a failing node tagged with a valid claim_id records a critic claim via the gate."""
    code = """
import pyarrow as pa
from hamilton.function_modifiers import tag

@tag(claim_id="TEST-C-001")
def boom() -> pa.Table:
    raise RuntimeError("synthetic failure")
"""
    mod = _create_module_from_code("hamilton_fail_tagged_mod", code)
    from insight_kit.hamilton import build_driver

    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [mod])
    with pytest.raises(RuntimeError, match="synthetic failure"):
        dr.execute(["boom"])

    # the failure produced a recorded critic claim
    assert len(rs.records) == 1
    assert rs.records[0].record_type == "claim"

    # Fix 1 regression guard: gate tier= keyword must be passed correctly.
    # 'critic' is a Hamilton-internal tier; it maps to gate tier 'draft'.
    # The Hamilton tier is preserved in fields["claim_tier"] for traceability.
    from insight_kit.gate.store import read_record as _rr
    rec = _rr(run_dir, rs.records[0].record_id)
    assert rec["tier"] == "draft"
    assert rec["fields"]["claim_tier"]["value"] == "critic"


def test_hamilton_build_driver_returns_driver(run_dir: Path) -> None:
    """build_driver returns a usable Hamilton Driver."""
    from insight_kit.hamilton import build_driver

    mod = _make_metric_module()
    rs = RunState(run_dir=run_dir)
    dr = build_driver(rs, run_dir, [mod])
    assert dr is not None


def test_hamilton_finalize_seals_run_state(run_dir: Path) -> None:
    """The hook's finalize() seals the RunState idempotently (V10)."""
    from insight_kit.hamilton import InsightKitHook

    rs = RunState(run_dir=run_dir)
    hook = InsightKitHook(rs, run_dir)
    assert rs.completedAt is None
    hook.finalize()
    assert rs.completedAt is not None
    first = rs.completedAt
    hook.finalize()  # idempotent
    assert rs.completedAt == first

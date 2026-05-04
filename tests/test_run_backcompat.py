"""Back-compat tests: Run.claim(id=) alias and Run.emit() dispatch shim."""
from __future__ import annotations

import warnings
from pathlib import Path

import pyarrow as pa
import pytest

from insight_kit import Run
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config


# ── fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_kit(tmp_path, namespace="TEST")
    monkeypatch.chdir(tmp_path)
    find_kit_root.cache_clear()
    kit_config.cache_clear()
    return tmp_path


# ── Run.claim(id=...) back-compat ────────────────────────────────────────────

def test_claim_legacy_id_kwarg_raises_deprecation(kit: Path):
    """Run.claim(id=...) is accepted but emits DeprecationWarning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with Run(topic="bc", agent="test-agent") as r:
            c = r.claim(id="TEST-D-001", statement="test claim text", tier="derived")

    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)
                 and "id=" in str(w.message)]
    assert dep_warns, "Expected DeprecationWarning for Run.claim(id=...)"
    assert "claim_id=" in str(dep_warns[0].message)


def test_claim_legacy_id_registers_with_claim_id(kit: Path):
    """Claim registered via id= kwarg has claim_id set correctly."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        with Run(topic="bc2", agent="test-agent") as r:
            c = r.claim(id="TEST-D-001", statement="test claim text", tier="derived")

    assert c.claim_id == "TEST-D-001"


def test_claim_both_id_and_claim_id_raises_typeerror(kit: Path):
    """Passing both id= and claim_id= raises TypeError."""
    with Run(topic="bc3", agent="test-agent") as r:
        with pytest.raises(TypeError, match="claim_id="):
            r.claim(id="TEST-D-001", claim_id="TEST-D-002", statement="text", tier="derived")


def test_claim_canonical_claim_id_no_warning(kit: Path):
    """Using claim_id= directly does not emit a deprecation warning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with Run(topic="bc4", agent="test-agent") as r:
            r.claim(claim_id="TEST-D-001", statement="canonical usage", tier="derived")

    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)
                 and "id=" in str(w.message)]
    assert not dep_warns, f"Unexpected DeprecationWarning: {dep_warns}"


# ── Run.emit() dispatch shim ─────────────────────────────────────────────────

def test_emit_dataframe_routes_to_emit_raw(kit: Path):
    """Run.emit(df) routes to emit_raw and raises DeprecationWarning."""
    df = pa.table({"x": [1, 2, 3]})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with Run(topic="emit-raw", agent="test-agent") as r:
            result = r.emit(df, name="test_df")

    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)
                 and "emit()" in str(w.message)]
    assert dep_warns, "Expected DeprecationWarning for Run.emit()"
    assert result.exists()
    # landed in raw layer
    assert "raw" in str(result)


def test_emit_scalar_metric_kind_routes_to_emit_metric(kit: Path):
    """Run.emit(42, kind='metric', name='rows') routes to emit_metric."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with Run(topic="emit-metric", agent="test-agent") as r:
            result = r.emit(42, kind="metric", name="rows")

    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)
                 and "emit()" in str(w.message)]
    assert dep_warns, "Expected DeprecationWarning for Run.emit()"
    assert result.exists()
    assert "metrics" in str(result)


def test_emit_str_critique_kind_routes_to_emit_critique(kit: Path):
    """Run.emit(str, kind='critique') routes to emit_critique."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with Run(topic="emit-critique", agent="test-agent") as r:
            result = r.emit("This claim has no edge", kind="critique", name="notes")

    dep_warns = [w for w in caught if issubclass(w.category, DeprecationWarning)
                 and "emit()" in str(w.message)]
    assert dep_warns, "Expected DeprecationWarning for Run.emit()"
    assert result.exists()
    assert "critique" in str(result)


def test_emit_inferred_str_routes_to_emit_critique(kit: Path):
    """Run.emit(str) without kind= infers critique from str type."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        with Run(topic="emit-infer-str", agent="test-agent") as r:
            result = r.emit("some critique text", name="c")

    assert "critique" in str(result)


def test_emit_inferred_float_routes_to_emit_metric(kit: Path):
    """Run.emit(float) without kind= infers metric from numeric type."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        with Run(topic="emit-infer-num", agent="test-agent") as r:
            result = r.emit(3.14, name="pi")

    assert "metrics" in str(result)

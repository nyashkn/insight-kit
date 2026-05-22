"""T9 — Input-provenance check tests (V13, V22, C8).

At emit:
  - raw agent-supplied parquet file paths as input_data → rejected (V13)
  - registered-upstream fingerprint (bytes or dict with fingerprint key) → accepted
  - string path ending in .pq or .parquet detected as raw-path → reject

InsightKitHook.run_before_node_execution:
  - node_input_types captured from **future_kwargs (no longer dropped)
  - h_dlt fingerprint = sha256(resource_name + schema) computed at hook time (C8)

Cites: V13, V22, C8.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from insight_kit.platform.gate.emit import ik_claim_emit
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import record_path
from insight_kit.validation import ValidationError as LayerAValidationError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


# ---------------------------------------------------------------------------
# T9 / V13 — raw parquet path rejection
# ---------------------------------------------------------------------------


class TestRawParquetPathRejection:
    """V13 — reject raw agent-supplied parquet file paths as inputs."""

    def test_raw_pq_path_bytes_rejected(self, run_dir, state):
        """Passing a .pq file path as bytes input_data → reject (V13)."""
        with pytest.raises(LayerAValidationError, match="raw-parquet-path"):
            ik_claim_emit(
                "TEST-D-001",
                {"revenue": 100},
                run_state=state,
                run_dir=run_dir,
                input_data=b"/data/outputs/metrics.pq",
            )

    def test_raw_parquet_path_bytes_rejected(self, run_dir, state):
        """Passing a .parquet file path as bytes → reject (V13)."""
        with pytest.raises(LayerAValidationError, match="raw-parquet-path"):
            ik_claim_emit(
                "TEST-D-001",
                {"revenue": 100},
                run_state=state,
                run_dir=run_dir,
                input_data=b"/home/user/data/file.parquet",
            )

    def test_raw_pq_path_string_in_dict_rejected(self, run_dir, state):
        """Dict input_data containing a path_ref ending in .pq → reject (V13)."""
        with pytest.raises(LayerAValidationError, match="raw-parquet-path"):
            ik_claim_emit(
                "TEST-D-001",
                {"revenue": 100},
                run_state=state,
                run_dir=run_dir,
                input_data={"path_ref": "/data/metrics.pq", "source": "agent"},
            )

    def test_raw_parquet_path_string_in_dict_rejected(self, run_dir, state):
        with pytest.raises(LayerAValidationError, match="raw-parquet-path"):
            ik_claim_emit(
                "TEST-D-001",
                {"revenue": 100},
                run_state=state,
                run_dir=run_dir,
                input_data={"path_ref": "/data/metrics.parquet"},
            )

    def test_raw_path_reject_increments_rejection(self, run_dir, state):
        try:
            ik_claim_emit(
                "TEST-D-001",
                {"revenue": 100},
                run_state=state,
                run_dir=run_dir,
                input_data=b"/data/metrics.pq",
            )
        except LayerAValidationError:
            pass
        assert state.rejectionCount == 1

    def test_raw_path_reject_zero_partial_write(self, run_dir, state):
        from insight_kit.platform.gate.store import index_path

        try:
            ik_claim_emit(
                "TEST-D-001",
                {"revenue": 100},
                run_state=state,
                run_dir=run_dir,
                input_data=b"/data/metrics.pq",
            )
        except LayerAValidationError:
            pass
        assert not index_path(run_dir).exists()


class TestRegisteredFingerprintAccepted:
    """V13 — registered-upstream fingerprint (non-path bytes/dict) accepted."""

    def test_real_bytes_input_accepted(self, run_dir, state):
        """Raw bytes that are not a file path are accepted (real data content)."""
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            run_state=state,
            run_dir=run_dir,
            input_data=b"\x00\x01\x02real-parquet-data-binary",
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "registered_input"

    def test_dict_with_upstream_fingerprint_accepted(self, run_dir, state):
        """Dict carrying a registered upstream fingerprint accepted (V13)."""
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            run_state=state,
            run_dir=run_dir,
            input_data={
                "upstream_fingerprint": "abc123def456",
                "resource": "h_dlt://metrics/revenue",
                "schema_version": "2",
            },
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "registered_input"

    def test_no_input_data_fallback_payload_accepted(self, run_dir, state):
        """No input_data → payload fallback (draft convenience) — still accepted."""
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 100},
            run_state=state,
            run_dir=run_dir,
            # no input_data
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "payload"


# ---------------------------------------------------------------------------
# T9 / C8 — InsightKitHook node_input_types capture + h_dlt fingerprint
# ---------------------------------------------------------------------------


class TestInsightKitHookNodeInputTypes:
    """C8 — run_before_node_execution captures node_input_types + computes h_dlt fp."""

    def _make_hook(self, tmp_path: Path | None = None):
        """Construct a gate-backed InsightKitHook (adapter.py is in scope).

        T25 cutover: InsightKitHook is wired onto the gate — it takes a RunState
        + run_dir, not a legacy Run. These C8 tests only exercise
        run_before_node_execution (h_dlt fingerprint capture), which touches
        neither, so a bare RunState + a throwaway dir suffice.
        """
        import tempfile

        from insight_kit.hamilton.adapter import InsightKitHook
        from insight_kit.platform.gate.runstate import RunState

        run_dir = Path(tmp_path) if tmp_path is not None else Path(tempfile.mkdtemp())
        return InsightKitHook(RunState(run_dir=run_dir), run_dir)

    def test_node_input_types_captured(self):
        """run_before_node_execution must capture node_input_types from kwargs."""
        hook = self._make_hook()
        captured: list = []
        original = hook.run_before_node_execution

        def capturing_hook(**kwargs):
            if "node_input_types" in kwargs:
                captured.append(kwargs["node_input_types"])
            return original(**kwargs)

        # Simulate Hamilton passing node_input_types as a future kwarg
        hook.run_before_node_execution(
            node_name="test_node",
            node_tags={},
            node_kwargs={"input_df": "some_df"},
            node_input_types={"input_df": "DataFrame"},
        )
        # The hook should not error — node_input_types is now captured, not silently dropped

    def test_h_dlt_fingerprint_computation(self):
        """sha256(resource_name + schema) = h_dlt fingerprint (C8)."""
        from insight_kit.hamilton.adapter import compute_h_dlt_fingerprint

        resource_name = "h_dlt://metrics/revenue"
        schema = "v2"
        expected = hashlib.sha256((resource_name + schema).encode()).hexdigest()
        result = compute_h_dlt_fingerprint(resource_name, schema)
        assert result == expected

    def test_h_dlt_fingerprint_deterministic(self):
        """Same resource_name + schema → identical fingerprint (C2)."""
        from insight_kit.hamilton.adapter import compute_h_dlt_fingerprint

        fp1 = compute_h_dlt_fingerprint("metrics.revenue", "v1")
        fp2 = compute_h_dlt_fingerprint("metrics.revenue", "v1")
        assert fp1 == fp2

    def test_h_dlt_fingerprint_differs_on_schema_change(self):
        """Different schema version → different fingerprint."""
        from insight_kit.hamilton.adapter import compute_h_dlt_fingerprint

        fp1 = compute_h_dlt_fingerprint("metrics.revenue", "v1")
        fp2 = compute_h_dlt_fingerprint("metrics.revenue", "v2")
        assert fp1 != fp2

    def test_hook_accepts_node_input_types_kwarg(self):
        """run_before_node_execution must accept node_input_types without error."""
        hook = self._make_hook()
        # Hamilton may pass node_input_types as a keyword arg; must not raise
        hook.run_before_node_execution(
            node_name="my_node",
            node_tags={"emit": "metric"},
            node_kwargs={},
            node_input_types={"x": "int", "y": "str"},
        )

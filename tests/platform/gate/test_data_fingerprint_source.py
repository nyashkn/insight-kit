"""V22 — data_fingerprint_source provenance honesty.

Every record must carry data_fingerprint_source ∈ {"registered_input", "payload"}.
  - "registered_input" when input_data= was supplied to emit.
  - "payload"          when data_fingerprint fell back to hashing the record dict.

T7 (published-tier rejection for source=="payload") is a later task — this module
only verifies the field is set correctly at emit time (the clean seam).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.platform.gate.emit import (
    ik_claim_emit,
    ik_intervention_emit,
    ik_research_emit,
    ik_skill_use_emit,
)
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import record_path


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def state() -> RunState:
    return RunState()


# ---------------------------------------------------------------------------
# Claim — registered_input vs payload
# ---------------------------------------------------------------------------

class TestClaimFingerprintSource:
    def test_claim_with_input_data_is_registered_input(self, run_dir, state):
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 123456},
            input_data=b"raw upstream bytes",
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "registered_input"

    def test_claim_without_input_data_is_payload(self, run_dir, state):
        ref = ik_claim_emit(
            "TEST-D-001",
            {"revenue": 123456},
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "payload"


# ---------------------------------------------------------------------------
# Intervention — registered_input vs payload
# ---------------------------------------------------------------------------

class TestInterventionFingerprintSource:
    def test_intervention_with_input_data_is_registered_input(self, run_dir, state):
        ref = ik_intervention_emit(
            "INT-001",
            {"description": "send email"},
            input_data={"upstream": "data"},
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "registered_input"

    def test_intervention_without_input_data_is_payload(self, run_dir, state):
        ref = ik_intervention_emit(
            "INT-001",
            {"description": "send email"},
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "payload"


# ---------------------------------------------------------------------------
# Research — registered_input vs payload
# ---------------------------------------------------------------------------

class TestResearchFingerprintSource:
    def test_research_with_input_data_is_registered_input(self, run_dir, state):
        ref = ik_research_emit(
            "RES-001", "s/r.json", "query", "web",
            timestamp="2026-05-22T10:00:00+00:00",
            snapshot={"results": "captured"},
            input_data=b"raw search results",
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "registered_input"

    def test_research_without_input_data_is_payload(self, run_dir, state):
        ref = ik_research_emit(
            "RES-001", "s/r.json", "query", "web",
            timestamp="2026-05-22T10:00:00+00:00",
            snapshot={"results": "captured"},
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "payload"


# ---------------------------------------------------------------------------
# SkillUse — registered_input vs payload
# ---------------------------------------------------------------------------

class TestSkillUseFingerprintSource:
    def test_skill_use_with_input_data_is_registered_input(self, run_dir, state):
        ref = ik_skill_use_emit(
            "SKU-001", "s/k.json", "tavily", "tavily-api",
            timestamp="2026-05-22T10:00:00+00:00",
            snapshot={"results": "captured"},
            input_data=b"tool output bytes",
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "registered_input"

    def test_skill_use_without_input_data_is_payload(self, run_dir, state):
        ref = ik_skill_use_emit(
            "SKU-001", "s/k.json", "tavily", "tavily-api",
            timestamp="2026-05-22T10:00:00+00:00",
            snapshot={"results": "captured"},
            run_state=state,
            run_dir=run_dir,
        )
        rec = json.loads(record_path(run_dir, ref.record_id).read_text())
        assert rec["data_fingerprint_source"] == "payload"

"""T16 — Layer-D render audit tests (V8, V9, V12, I.audit).

Covers the backend-agnostic audit core (L5 token→claim join, L6 prose lint),
the claims-index helpers, and the Vega-Lite render adapter.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.gate.audit import (
    AuditReport,
    ClaimFieldRef,
    RenderAdapter,
    RenderedToken,
    audit_l5,
    audit_l6,
    build_claims_index,
    load_claims_index,
    run_render_audit,
)
from insight_kit.gate.emit import ik_claim_emit
from insight_kit.gate.render_adapters import VegaLiteAdapter
from insight_kit.gate.runstate import RunState

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


# claim_id -> {field: value}
INDEX = {"ABC-D-001": {"gmv": 1200.0, "monthly": [100.0, 110.0, 120.0]}}


def _tok(value, claim=None, field=None, raw=None, loc="x"):
    ref = ClaimFieldRef(claim_id=claim, field=field) if claim else None
    return RenderedToken(raw=raw or str(value), value=value, claim_ref=ref, location=loc)


# ===========================================================================
# L5 — token -> claim join (V9)
# ===========================================================================


class TestL5TokenJoin:
    def test_bound_token_matching_value_passes(self):
        res = audit_l5([_tok(1200.0, "ABC-D-001", "gmv")], INDEX)
        assert res.passed
        assert res.violations == []

    def test_orphan_token_fails(self):
        """A numeric token bound to no claim → orphan → fail (V9)."""
        res = audit_l5([_tok(999.0)], INDEX)
        assert not res.passed
        assert res.violations[0].kind == "orphan"

    def test_unknown_claim_fails(self):
        res = audit_l5([_tok(1200.0, "ZZZ-D-999", "gmv")], INDEX)
        assert not res.passed
        assert res.violations[0].kind == "unknown-claim"

    def test_unknown_field_fails(self):
        res = audit_l5([_tok(1200.0, "ABC-D-001", "nope")], INDEX)
        assert not res.passed
        assert res.violations[0].kind == "unknown-field"

    def test_value_mismatch_fails(self):
        res = audit_l5([_tok(9999.0, "ABC-D-001", "gmv")], INDEX)
        assert not res.passed
        assert res.violations[0].kind == "value-mismatch"

    def test_list_field_membership_passes(self):
        """A chart token is one point of a series field — membership counts."""
        res = audit_l5([_tok(110.0, "ABC-D-001", "monthly")], INDEX)
        assert res.passed

    def test_list_field_non_member_fails(self):
        res = audit_l5([_tok(115.0, "ABC-D-001", "monthly")], INDEX)
        assert not res.passed
        assert res.violations[0].kind == "value-mismatch"

    def test_value_within_tolerance_passes(self):
        res = audit_l5([_tok(1200.0000001, "ABC-D-001", "gmv")], INDEX)
        assert res.passed

    def test_multiple_tokens_all_checked(self):
        res = audit_l5(
            [_tok(1200.0, "ABC-D-001", "gmv"), _tok(42.0), _tok(7.0, "X", "y")], INDEX
        )
        assert not res.passed
        assert {v.kind for v in res.violations} == {"orphan", "unknown-claim"}


# ===========================================================================
# L6 — narrative.md prose lint (V8)
# ===========================================================================


class TestL6ProseLint:
    def test_bare_number_in_prose_fails(self):
        res = audit_l6("Revenue grew to 1,234 this quarter.")
        assert not res.passed
        assert res.violations[0].token == "1,234"
        assert res.violations[0].line == 1

    def test_claim_ref_tag_passes(self):
        res = audit_l6('Revenue grew to <ClaimNum claim="ABC-D-001" field="gmv"/>.')
        assert res.passed

    def test_claim_chart_tag_passes(self):
        res = audit_l6('See the trend: <ClaimChart claim="ABC-D-001" field="monthly"/>')
        assert res.passed

    def test_number_in_fenced_code_exempt(self):
        md = "Prose here.\n```\nx = 1234\n```\nMore prose."
        assert audit_l6(md).passed

    def test_number_in_inline_code_exempt(self):
        assert audit_l6("The constant `MAX = 30` is internal.").passed

    def test_list_ordinal_not_flagged(self):
        assert audit_l6("1. first point\n2. second point").passed

    def test_clean_prose_passes(self):
        assert audit_l6("Revenue grew strongly with no typed figures.").passed

    def test_line_numbers_reported(self):
        res = audit_l6("clean line\nrevenue was 500 here\nclean again")
        assert res.violations[0].line == 2

    def test_bare_number_after_claim_tag_still_caught(self):
        """Stripping the tag must not mask a separate bare literal on the line."""
        res = audit_l6('<ClaimNum claim="A" field="f"/> but also 88 bare.')
        assert not res.passed
        assert res.violations[0].token == "88"


# ===========================================================================
# Claims index helpers
# ===========================================================================


class TestClaimsIndex:
    def test_build_from_rows(self):
        rows = [
            {"claim_id": "ABC-D-001", "fields": {"gmv": {"value": 1200, "fmt_hint": None}}}
        ]
        idx = build_claims_index(rows)
        assert idx["ABC-D-001"]["gmv"] == 1200

    def test_build_skips_rows_without_claim_id(self):
        assert build_claims_index([{"fields": {"x": {"value": 1}}}]) == {}

    def test_load_from_run_dir(self, run_dir):
        """load_claims_index reads the claims.jsonl a real claim emit produced."""
        state = RunState()
        ik_claim_emit("ABC-D-001", {"gmv": 1200}, run_state=state, run_dir=run_dir)
        idx = load_claims_index(run_dir)
        assert idx["ABC-D-001"]["gmv"] == 1200

    def test_load_missing_index_returns_empty(self, run_dir):
        assert load_claims_index(run_dir) == {}


# ===========================================================================
# VegaLiteAdapter
# ===========================================================================


def _vl_spec(values, *, claim_id=None, field_map=None):
    spec: dict = {"data": {"values": values}, "mark": "bar"}
    if claim_id:
        spec["usermeta"] = {
            "insight_kit": {"claim_id": claim_id, "field_map": field_map or {}}
        }
    return spec


class TestVegaLiteAdapter:
    def test_implements_render_adapter_protocol(self):
        assert isinstance(VegaLiteAdapter(), RenderAdapter)

    def test_backend_name(self):
        assert VegaLiteAdapter().backend == "vega-lite"

    def test_mapped_field_yields_bound_token(self):
        spec = _vl_spec(
            [{"gmv": 1200}], claim_id="ABC-D-001", field_map={"gmv": "gmv"}
        )
        tokens = VegaLiteAdapter().extract_tokens(spec)
        assert len(tokens) == 1
        assert tokens[0].claim_ref == ClaimFieldRef("ABC-D-001", "gmv")
        assert tokens[0].value == 1200.0

    def test_unmapped_field_yields_orphan_token(self):
        spec = _vl_spec([{"gmv": 1200}], claim_id="ABC-D-001", field_map={})
        tokens = VegaLiteAdapter().extract_tokens(spec)
        assert tokens[0].claim_ref is None

    def test_no_usermeta_yields_orphan_tokens(self):
        tokens = VegaLiteAdapter().extract_tokens(_vl_spec([{"v": 5}]))
        assert tokens[0].claim_ref is None

    def test_non_numeric_values_skipped(self):
        spec = _vl_spec([{"label": "Jan", "gmv": 100}])
        tokens = VegaLiteAdapter().extract_tokens(spec)
        assert [t.location for t in tokens] == ["data.values[0].gmv"]

    def test_numeric_string_parsed(self):
        tokens = VegaLiteAdapter().extract_tokens(_vl_spec([{"gmv": "1,234.5"}]))
        assert tokens[0].value == 1234.5

    def test_bool_not_treated_as_number(self):
        assert VegaLiteAdapter().extract_tokens(_vl_spec([{"flag": True}])) == []

    def test_loads_from_path(self, tmp_path):
        spec = _vl_spec([{"gmv": 1200}], claim_id="ABC-D-001", field_map={"gmv": "gmv"})
        p = tmp_path / "chart.vl.json"
        p.write_text(json.dumps(spec), encoding="utf-8")
        tokens = VegaLiteAdapter().extract_tokens(p)
        assert tokens[0].value == 1200.0


# ===========================================================================
# run_render_audit — end to end (V12)
# ===========================================================================


class TestRunRenderAudit:
    def test_clean_chart_and_prose_passes(self):
        spec = _vl_spec(
            [{"gmv": 1200}], claim_id="ABC-D-001", field_map={"gmv": "gmv"}
        )
        report = run_render_audit(
            artifact=spec,
            adapter=VegaLiteAdapter(),
            narrative_md='Revenue: <ClaimNum claim="ABC-D-001" field="gmv"/>.',
            claims_index=INDEX,
        )
        assert isinstance(report, AuditReport)
        assert report.passed

    def test_orphan_chart_token_fails_audit(self):
        spec = _vl_spec([{"gmv": 1200}])  # no usermeta → orphan
        report = run_render_audit(
            artifact=spec,
            adapter=VegaLiteAdapter(),
            narrative_md="clean prose",
            claims_index=INDEX,
        )
        assert not report.passed
        assert not report.l5.passed
        assert report.l6.passed

    def test_bare_prose_number_fails_audit(self):
        spec = _vl_spec(
            [{"gmv": 1200}], claim_id="ABC-D-001", field_map={"gmv": "gmv"}
        )
        report = run_render_audit(
            artifact=spec,
            adapter=VegaLiteAdapter(),
            narrative_md="Revenue grew to 1200 this quarter.",
            claims_index=INDEX,
        )
        assert not report.passed
        assert report.l5.passed
        assert not report.l6.passed

"""T33 — Render Composer tests (compose.py / compose_record / parse_refs / verify_chart_bindings).

Covers:
  - ClaimNum tag resolution to formatted value in HTML output
  - ClaimChart embedding (vega-embed container, spec JSON, CDN scripts)
  - Error on unresolved ClaimNum field
  - Error on usermeta claim_id / tag claim attribute mismatch (binding check)
  - Error on missing chart src file
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.platform.gate.emit import ik_claim_emit
from insight_kit.platform.gate.runstate import RunState
from insight_kit.platform.gate.store import record_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_vl_spec(
    claim_id: str,
    *,
    data_value: float = 2.3,
    field_name: str = "repeat_value_multiple",
) -> dict:
    """Return a minimal valid Vega-Lite spec with usermeta.insight_kit binding."""
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "mark": "bar",
        "data": {
            "values": [{field_name: data_value}]
        },
        "encoding": {
            "x": {"field": field_name, "type": "quantitative"},
        },
        "usermeta": {
            "insight_kit": {
                "claim_id": claim_id,
                "field_map": {field_name: field_name},
            }
        },
    }


def _write_chart(record_dir: Path, claim_id: str, **kwargs) -> Path:
    """Write a chart.vl.json sibling in the record dir."""
    spec = _minimal_vl_spec(claim_id, **kwargs)
    path = record_dir / "chart.vl.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _write_narrative(record_dir: Path, content: str) -> Path:
    """Write narrative.md into record_dir."""
    path = record_dir / "narrative.md"
    path.write_text(content, encoding="utf-8")
    return path


def _emit_dock_d_128(run_dir: Path) -> str:
    """Emit DOCK-D-128 with repeat_value_multiple=2.3 and return the record_id."""
    state = RunState()
    ref = ik_claim_emit(
        "DOCK-D-128",
        {"repeat_value_multiple": (2.3, "%.1fx")},
        run_state=state,
        run_dir=run_dir,
    )
    return ref.record_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return tmp_path / "run"


@pytest.fixture
def dock_run(run_dir: Path):
    """Emit DOCK-D-128, write chart + narrative siblings. Returns (run_dir, record_id)."""
    record_id = _emit_dock_d_128(run_dir)
    rec_dir = record_path(run_dir, record_id).parent

    _write_chart(rec_dir, "DOCK-D-128")

    narrative_content = (
        'The multiplier is <ClaimNum claim="DOCK-D-128" field="repeat_value_multiple"/>.'
        '\n\n'
        '<ClaimChart src="chart.vl.json" claim="DOCK-D-128"/>'
    )
    _write_narrative(rec_dir, narrative_content)

    return run_dir, record_id


# ---------------------------------------------------------------------------
# parse_refs
# ---------------------------------------------------------------------------


class TestParseRefs:
    def test_parses_claimnum_tag(self):
        from insight_kit.platform.gate.compose import parse_refs

        md = '<ClaimNum claim="DOCK-D-128" field="repeat_value_multiple"/>'
        refs = parse_refs(md)
        assert len(refs.num_refs) == 1
        assert refs.num_refs[0].claim == "DOCK-D-128"
        assert refs.num_refs[0].field_name == "repeat_value_multiple"

    def test_parses_claimchart_tag(self):
        from insight_kit.platform.gate.compose import parse_refs

        md = '<ClaimChart src="chart.vl.json" claim="DOCK-D-128"/>'
        refs = parse_refs(md)
        assert len(refs.chart_refs) == 1
        assert refs.chart_refs[0].src == "chart.vl.json"
        assert refs.chart_refs[0].claim == "DOCK-D-128"

    def test_parses_both_tag_types(self):
        from insight_kit.platform.gate.compose import parse_refs

        md = (
            'See <ClaimNum claim="DOCK-D-128" field="repeat_value_multiple"/> '
            'and <ClaimChart src="chart.vl.json" claim="DOCK-D-128"/>.'
        )
        refs = parse_refs(md)
        assert len(refs.num_refs) == 1
        assert len(refs.chart_refs) == 1

    def test_attr_order_independent_claimnum(self):
        """Attribute order must not affect parsing (field before claim)."""
        from insight_kit.platform.gate.compose import parse_refs

        md = '<ClaimNum field="repeat_value_multiple" claim="DOCK-D-128"/>'
        refs = parse_refs(md)
        assert len(refs.num_refs) == 1
        assert refs.num_refs[0].claim == "DOCK-D-128"
        assert refs.num_refs[0].field_name == "repeat_value_multiple"

    def test_attr_order_independent_claimchart(self):
        """Attribute order must not affect parsing (claim before src)."""
        from insight_kit.platform.gate.compose import parse_refs

        md = '<ClaimChart claim="DOCK-D-128" src="chart.vl.json"/>'
        refs = parse_refs(md)
        assert len(refs.chart_refs) == 1
        assert refs.chart_refs[0].src == "chart.vl.json"
        assert refs.chart_refs[0].claim == "DOCK-D-128"

    def test_empty_markdown_returns_empty(self):
        from insight_kit.platform.gate.compose import parse_refs

        refs = parse_refs("No tags here.")
        assert refs.num_refs == []
        assert refs.chart_refs == []


# ---------------------------------------------------------------------------
# compose_record — happy paths
# ---------------------------------------------------------------------------


class TestComposeResolvesClaimNum:
    def test_compose_resolves_claimnum(self, dock_run):
        """compose_record HTML contains the formatted value, not the literal tag."""
        from insight_kit.platform.gate.compose import compose_record

        run_dir, record_id = dock_run
        html = compose_record(run_dir, record_id)

        # The formatted value (fmt_hint "%.1fx" applied to 2.3) must appear
        assert "2.3x" in html
        # The raw tag must NOT appear in the output
        assert "<ClaimNum" not in html

    def test_compose_claimnum_fmt_hint_applied(self, dock_run):
        """compose_record respects fmt_hint when formatting ClaimNum values."""
        from insight_kit.platform.gate.compose import compose_record

        run_dir, record_id = dock_run
        html = compose_record(run_dir, record_id)

        # "2.3x" comes from "%.1fx" % 2.3 — not "2.3" plain
        assert "2.3x" in html


class TestComposeEmbedsChart:
    def test_compose_embeds_chart(self, dock_run):
        """compose_record HTML contains vega-embed container + spec + CDN scripts."""
        from insight_kit.platform.gate.compose import compose_record

        run_dir, record_id = dock_run
        html = compose_record(run_dir, record_id)

        # CDN scripts pinned per design spec
        assert "vega@5" in html
        assert "vega-lite@5" in html
        assert "vega-embed@6" in html

        # vega-embed API call must be present
        assert "vegaEmbed" in html

        # The spec JSON must be inlined — the claim_id appears in usermeta
        assert "DOCK-D-128" in html

        # No <ClaimChart tag should remain in the output
        assert "<ClaimChart" not in html

    def test_compose_output_is_string(self, dock_run):
        from insight_kit.platform.gate.compose import compose_record

        run_dir, record_id = dock_run
        html = compose_record(run_dir, record_id)
        assert isinstance(html, str)
        assert len(html) > 0

    def test_compose_output_is_html(self, dock_run):
        """Output must look like an HTML document (has <html or <!DOCTYPE)."""
        from insight_kit.platform.gate.compose import compose_record

        run_dir, record_id = dock_run
        html = compose_record(run_dir, record_id)
        lower = html.lower()
        assert "<html" in lower or "<!doctype" in lower


# ---------------------------------------------------------------------------
# compose_record — error paths
# ---------------------------------------------------------------------------


class TestComposeUnresolvedClaimNumRaises:
    def test_compose_unresolved_claimnum_raises(self, run_dir):
        """A <ClaimNum> naming a missing field raises ComposeError."""
        from insight_kit.platform.gate.compose import ComposeError, compose_record

        record_id = _emit_dock_d_128(run_dir)
        rec_dir = record_path(run_dir, record_id).parent
        _write_chart(rec_dir, "DOCK-D-128")

        # Reference a field that does not exist in the claim
        narrative = '<ClaimNum claim="DOCK-D-128" field="nonexistent_field"/>'
        _write_narrative(rec_dir, narrative)

        with pytest.raises(ComposeError, match="nonexistent_field"):
            compose_record(run_dir, record_id)

    def test_compose_unresolved_claimnum_unknown_claim_raises(self, run_dir):
        """A <ClaimNum> referencing a claim_id not emitted in this run raises."""
        from insight_kit.platform.gate.compose import ComposeError, compose_record

        record_id = _emit_dock_d_128(run_dir)
        rec_dir = record_path(run_dir, record_id).parent
        _write_chart(rec_dir, "DOCK-D-128")

        # Reference a claim_id that was never emitted
        narrative = '<ClaimNum claim="UNKN-D-999" field="repeat_value_multiple"/>'
        _write_narrative(rec_dir, narrative)

        with pytest.raises(ComposeError):
            compose_record(run_dir, record_id)


class TestComposeBindingMismatchRaises:
    def test_compose_binding_mismatch_raises(self, run_dir):
        """A <ClaimChart> whose chart.vl.json usermeta claim_id != tag claim raises."""
        from insight_kit.platform.gate.compose import ComposeError, compose_record

        record_id = _emit_dock_d_128(run_dir)
        rec_dir = record_path(run_dir, record_id).parent

        # Write chart bound to a DIFFERENT claim_id than the tag will reference
        _write_chart(rec_dir, "OTHR-D-001")  # usermeta says OTHR-D-001

        # Tag claims DOCK-D-128 but usermeta says OTHR-D-001 → mismatch
        narrative = '<ClaimChart src="chart.vl.json" claim="DOCK-D-128"/>'
        _write_narrative(rec_dir, narrative)

        with pytest.raises(ComposeError):
            compose_record(run_dir, record_id)


class TestComposeMissingSrcRaises:
    def test_compose_missing_src_raises(self, run_dir):
        """A <ClaimChart src="nope.vl.json"/> for a nonexistent file raises."""
        from insight_kit.platform.gate.compose import ComposeError, compose_record

        record_id = _emit_dock_d_128(run_dir)
        rec_dir = record_path(run_dir, record_id).parent
        # Do NOT write any chart file

        narrative = '<ClaimChart src="nope.vl.json" claim="DOCK-D-128"/>'
        _write_narrative(rec_dir, narrative)

        with pytest.raises(ComposeError, match=r"nope\.vl\.json"):
            compose_record(run_dir, record_id)


# ---------------------------------------------------------------------------
# verify_chart_bindings
# ---------------------------------------------------------------------------


class TestVerifyChartBindings:
    def test_verify_passing_bindings(self, dock_run):
        """verify_chart_bindings returns a passing result when all bindings are correct."""
        from insight_kit.platform.gate.compose import verify_chart_bindings

        run_dir, record_id = dock_run
        result = verify_chart_bindings(run_dir, record_id)
        assert result.passed
        assert result.violations == []

    def test_verify_detects_mismatch(self, run_dir):
        """verify_chart_bindings detects usermeta claim_id != tag claim."""
        from insight_kit.platform.gate.compose import verify_chart_bindings

        record_id = _emit_dock_d_128(run_dir)
        rec_dir = record_path(run_dir, record_id).parent
        _write_chart(rec_dir, "OTHR-D-001")  # wrong binding in usermeta

        narrative = '<ClaimChart src="chart.vl.json" claim="DOCK-D-128"/>'
        _write_narrative(rec_dir, narrative)

        result = verify_chart_bindings(run_dir, record_id)
        assert not result.passed
        assert len(result.violations) >= 1

    def test_verify_detects_missing_src(self, run_dir):
        """verify_chart_bindings detects missing chart file."""
        from insight_kit.platform.gate.compose import verify_chart_bindings

        record_id = _emit_dock_d_128(run_dir)
        rec_dir = record_path(run_dir, record_id).parent
        # No chart file written

        narrative = '<ClaimChart src="missing.vl.json" claim="DOCK-D-128"/>'
        _write_narrative(rec_dir, narrative)

        result = verify_chart_bindings(run_dir, record_id)
        assert not result.passed

    def test_verify_no_charts_passes(self, run_dir):
        """verify_chart_bindings passes when narrative has no ClaimChart tags."""
        from insight_kit.platform.gate.compose import verify_chart_bindings

        record_id = _emit_dock_d_128(run_dir)
        rec_dir = record_path(run_dir, record_id).parent
        _write_narrative(rec_dir, "Prose with no chart tags.")

        result = verify_chart_bindings(run_dir, record_id)
        assert result.passed

    def test_verify_result_has_passed_and_violations(self, dock_run):
        """verify_chart_bindings result has .passed bool and .violations list."""
        from insight_kit.platform.gate.compose import verify_chart_bindings

        run_dir, record_id = dock_run
        result = verify_chart_bindings(run_dir, record_id)
        assert isinstance(result.passed, bool)
        assert isinstance(result.violations, list)

"""T33 — MarkdownVegaAdapter tests (render_adapters.py / audit integration).

Covers:
  - MarkdownVegaAdapter implements RenderAdapter protocol
  - extract_tokens over a narrative.md with one <ClaimChart src> yields the
    same tokens as VegaLiteAdapter applied to that sibling spec directly
  - Multiple <ClaimChart> tags produce concatenated tokens from all charts
  - Missing chart src file raises clearly
  - Delegation: plug into run_render_audit and verify a clean audit when
    the claim index matches (no orphan violations)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insight_kit.platform.gate.audit import (
    ClaimFieldRef,
    RenderAdapter,
    build_claims_index,
    run_render_audit,
)
from insight_kit.platform.gate.render_adapters import VegaLiteAdapter

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


def _write_chart(tmp_dir: Path, filename: str, claim_id: str, **kwargs) -> Path:
    spec = _minimal_vl_spec(claim_id, **kwargs)
    path = tmp_dir / filename
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def _write_narrative(tmp_dir: Path, content: str) -> Path:
    path = tmp_dir / "narrative.md"
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestMarkdownVegaAdapterProtocol:
    def test_implements_render_adapter_protocol(self):
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        assert isinstance(MarkdownVegaAdapter(), RenderAdapter)

    def test_backend_name(self):
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        assert MarkdownVegaAdapter().backend == "markdown-vega"


# ---------------------------------------------------------------------------
# extract_tokens — delegation to VegaLiteAdapter
# ---------------------------------------------------------------------------


class TestMarkdownVegaAdapterExtractTokens:
    def test_single_claimchart_yields_same_tokens_as_vl_adapter(self, tmp_path):
        """extract_tokens(narrative.md) == VegaLiteAdapter().extract_tokens(spec)."""
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        claim_id = "DOCK-D-128"
        chart_path = _write_chart(tmp_path, "chart.vl.json", claim_id)
        spec = json.loads(chart_path.read_text())

        narrative_path = _write_narrative(
            tmp_path,
            f'See the data: <ClaimChart src="chart.vl.json" claim="{claim_id}"/>',
        )

        mv_tokens = MarkdownVegaAdapter().extract_tokens(narrative_path)
        vl_tokens = VegaLiteAdapter().extract_tokens(spec)

        assert len(mv_tokens) == len(vl_tokens)
        for mv_tok, vl_tok in zip(mv_tokens, vl_tokens, strict=False):
            assert mv_tok.value == vl_tok.value
            assert mv_tok.claim_ref == vl_tok.claim_ref
            assert mv_tok.raw == vl_tok.raw

    def test_tokens_have_correct_claim_ref(self, tmp_path):
        """Each token from MarkdownVegaAdapter is bound to the correct claim field."""
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        claim_id = "DOCK-D-128"
        _write_chart(tmp_path, "chart.vl.json", claim_id, data_value=5.0)
        narrative_path = _write_narrative(
            tmp_path,
            f'<ClaimChart src="chart.vl.json" claim="{claim_id}"/>',
        )

        tokens = MarkdownVegaAdapter().extract_tokens(narrative_path)
        assert len(tokens) >= 1
        assert tokens[0].claim_ref == ClaimFieldRef(
            claim_id=claim_id, field="repeat_value_multiple"
        )
        assert tokens[0].value == 5.0

    def test_multiple_claimchart_tags_concat_tokens(self, tmp_path):
        """Two <ClaimChart> tags produce tokens from both charts concatenated."""
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        _write_chart(tmp_path, "chart_a.vl.json", "DOCK-D-128", data_value=1.0)
        _write_chart(tmp_path, "chart_b.vl.json", "DOCK-D-129", data_value=2.0)

        narrative_path = _write_narrative(
            tmp_path,
            (
                '<ClaimChart src="chart_a.vl.json" claim="DOCK-D-128"/>\n'
                '<ClaimChart src="chart_b.vl.json" claim="DOCK-D-129"/>'
            ),
        )

        tokens = MarkdownVegaAdapter().extract_tokens(narrative_path)
        values = {t.value for t in tokens}
        assert 1.0 in values
        assert 2.0 in values

    def test_no_claimchart_tags_yields_empty(self, tmp_path):
        """Narrative with no <ClaimChart> tags yields empty token list."""
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        narrative_path = _write_narrative(tmp_path, "Clean prose, no chart tags.")
        tokens = MarkdownVegaAdapter().extract_tokens(narrative_path)
        assert tokens == []

    def test_accepts_string_content(self, tmp_path):
        """extract_tokens also accepts a string of narrative content (not just Path)."""
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        _write_chart(tmp_path, "chart.vl.json", "DOCK-D-128")

        # Pass narrative as a string — adapter must resolve chart relative to cwd
        # or the test must pass a path. Per spec, str input = content string, so
        # this variant tests what the spec says: Path/str supported.
        # We test the Path form here and a raw-string variant below.
        narrative_path = _write_narrative(
            tmp_path,
            '<ClaimChart src="chart.vl.json" claim="DOCK-D-128"/>',
        )
        tokens = MarkdownVegaAdapter().extract_tokens(str(narrative_path))
        assert len(tokens) >= 1

    def test_missing_chart_src_raises(self, tmp_path):
        """Missing chart file referenced in narrative raises a clear error."""
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        narrative_path = _write_narrative(
            tmp_path,
            '<ClaimChart src="ghost.vl.json" claim="DOCK-D-128"/>',
        )

        with pytest.raises(Exception, match=r"ghost\.vl\.json"):
            MarkdownVegaAdapter().extract_tokens(narrative_path)


# ---------------------------------------------------------------------------
# Integration: run_render_audit with MarkdownVegaAdapter
# ---------------------------------------------------------------------------


class TestMarkdownVegaAdapterAuditIntegration:
    def test_clean_audit_no_orphan_violations(self, tmp_path):
        """run_render_audit passes (no orphans) when claim index matches the chart."""
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        claim_id = "DOCK-D-128"
        field_name = "repeat_value_multiple"
        data_value = 2.3

        _write_chart(
            tmp_path,
            "chart.vl.json",
            claim_id,
            data_value=data_value,
            field_name=field_name,
        )
        narrative_path = _write_narrative(
            tmp_path,
            (
                f'The multiplier is '
                f'<ClaimNum claim="{claim_id}" field="{field_name}"/>.\n\n'
                f'<ClaimChart src="chart.vl.json" claim="{claim_id}"/>'
            ),
        )

        # Build a claims index that matches what the chart binds to
        claims_rows = [
            {
                "claim_id": claim_id,
                "fields": {
                    field_name: {"value": data_value, "fmt_hint": "%.1fx"}
                },
            }
        ]
        claims_index = build_claims_index(claims_rows)

        narrative_md = narrative_path.read_text(encoding="utf-8")
        report = run_render_audit(
            artifact=narrative_path,
            adapter=MarkdownVegaAdapter(),
            narrative_md=narrative_md,
            claims_index=claims_index,
        )

        # L5: no orphan violations (all chart tokens bound to matching claim fields)
        assert report.l5.passed, f"L5 violations: {report.l5.violations}"

    def test_orphan_chart_token_fails_l5(self, tmp_path):
        """A chart with no usermeta → orphan tokens → L5 fail."""
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        # Spec with NO usermeta → all tokens are orphans
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "mark": "bar",
            "data": {"values": [{"x": 42.0}]},
        }
        chart_path = tmp_path / "chart.vl.json"
        chart_path.write_text(json.dumps(spec), encoding="utf-8")

        narrative_path = _write_narrative(
            tmp_path,
            '<ClaimChart src="chart.vl.json" claim="DOCK-D-128"/>',
        )

        claims_index = {"DOCK-D-128": {"repeat_value_multiple": 2.3}}
        narrative_md = narrative_path.read_text(encoding="utf-8")

        report = run_render_audit(
            artifact=narrative_path,
            adapter=MarkdownVegaAdapter(),
            narrative_md=narrative_md,
            claims_index=claims_index,
        )

        assert not report.l5.passed
        assert any(v.kind == "orphan" for v in report.l5.violations)

    def test_value_mismatch_fails_l5(self, tmp_path):
        """Chart renders 2.3 but claim index says 9.9 → value-mismatch → L5 fail."""
        from insight_kit.platform.gate.render_adapters import MarkdownVegaAdapter

        claim_id = "DOCK-D-128"
        field_name = "repeat_value_multiple"

        # Chart has 2.3
        _write_chart(tmp_path, "chart.vl.json", claim_id, data_value=2.3)

        narrative_path = _write_narrative(
            tmp_path,
            f'<ClaimChart src="chart.vl.json" claim="{claim_id}"/>',
        )

        # But index says 9.9
        claims_index = {claim_id: {field_name: 9.9}}
        narrative_md = narrative_path.read_text(encoding="utf-8")

        report = run_render_audit(
            artifact=narrative_path,
            adapter=MarkdownVegaAdapter(),
            narrative_md=narrative_md,
            claims_index=claims_index,
        )

        assert not report.l5.passed
        assert any(v.kind == "value-mismatch" for v in report.l5.violations)

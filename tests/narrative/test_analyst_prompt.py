"""Tests for insight_kit.narrative.analyst_prompt.

Covers:
  - Required structural pieces of the rendered prompt
  - Founder context: included when set, completely omitted when empty
  - JSON literal braces survive .format() (the `{{` / `}}` escapes)
  - run_dir accepts str + Path interchangeably
  - data_scope default vs custom
  - Strict query_path rules block is present (the omp-drift fix)
"""
from __future__ import annotations

from pathlib import Path

from insight_kit.narrative.analyst_prompt import (
    ANALYST_PROMPT_TEMPLATE,
    render_analyst_prompt,
)


# ---------------------------------------------------------------------------
# Render basics
# ---------------------------------------------------------------------------

def test_render_includes_goal_and_question() -> None:
    out = render_analyst_prompt(
        goal_slug="g4f7_attribution",
        question="Why did CPA fall?",
        run_dir="/app/data/agent_runs/r1",
    )
    assert "# Analyst run: g4f7_attribution" in out
    assert "**Goal question:** Why did CPA fall?" in out
    assert "/app/data/agent_runs/r1" in out


def test_render_accepts_path_or_str_for_run_dir(tmp_path: Path) -> None:
    out_path = render_analyst_prompt(
        goal_slug="g", question="q?", run_dir=tmp_path,
    )
    out_str = render_analyst_prompt(
        goal_slug="g", question="q?", run_dir=str(tmp_path),
    )
    assert str(tmp_path) in out_path
    assert str(tmp_path) in out_str


# ---------------------------------------------------------------------------
# Founder context
# ---------------------------------------------------------------------------

def test_founder_context_included_when_set() -> None:
    out = render_analyst_prompt(
        goal_slug="g", question="q?", run_dir="/r",
        founder_context="April is the worst month on record.",
    )
    assert "**Founder context:** April is the worst month on record." in out


def test_founder_context_block_omitted_when_empty() -> None:
    out = render_analyst_prompt(
        goal_slug="g", question="q?", run_dir="/r",
    )
    assert "**Founder context:**" not in out


# ---------------------------------------------------------------------------
# Data scope
# ---------------------------------------------------------------------------

def test_data_scope_default_placeholder() -> None:
    out = render_analyst_prompt(goal_slug="g", question="q?", run_dir="/r")
    assert "*(no data scope provided)*" in out


def test_data_scope_custom_markdown() -> None:
    scope = "### Meta metadata\n- m1: /path/m1.json\n\n### Shopify\n- s1: /path/s1.parquet"
    out = render_analyst_prompt(
        goal_slug="g", question="q?", run_dir="/r", data_scope=scope,
    )
    assert "### Meta metadata" in out
    assert "- m1: /path/m1.json" in out
    assert "- s1: /path/s1.parquet" in out


# ---------------------------------------------------------------------------
# Claim schema + JSON brace escaping
# ---------------------------------------------------------------------------

def test_claim_schema_json_block_renders_with_real_braces() -> None:
    out = render_analyst_prompt(goal_slug="g4", question="q?", run_dir="/r")
    # The JSON example block must render with literal { and }, not {{ / }}.
    assert '"claim_id":' in out
    assert '"goal":             "g4"' in out  # goal_slug interpolated inside JSON block
    assert "{{" not in out  # no leftover unescaped placeholder
    assert "}}" not in out


# ---------------------------------------------------------------------------
# Strict query_path rules (the omp-drift fix)
# ---------------------------------------------------------------------------

def test_query_path_rules_block_present() -> None:
    out = render_analyst_prompt(goal_slug="g", question="q?", run_dir="/r")
    assert "`query_path` rules — strict, no exceptions:" in out
    assert "Exactly ONE path. Single string. No spaces, no concatenation." in out
    assert "Format MUST be `queries/<claim_id>.sql`" in out
    assert "those upstream claim_ids in the `cites` array — NOT in `query_path`" in out


# ---------------------------------------------------------------------------
# Output file list + persona instructions hook
# ---------------------------------------------------------------------------

def test_output_files_list_present() -> None:
    out = render_analyst_prompt(goal_slug="g", question="q?", run_dir="/r")
    assert "Output files (relative to your run dir `/r`):" in out
    assert "- `findings_analyst.md`" in out
    assert "- `claims.jsonl` (append" in out
    assert "- `queries/<claim_id>.sql` for each query" in out


def test_prompt_ends_at_persona_instructions_heading() -> None:
    """Caller is expected to append persona text after this heading."""
    out = render_analyst_prompt(goal_slug="g", question="q?", run_dir="/r")
    assert out.rstrip().endswith("## Persona instructions")


# ---------------------------------------------------------------------------
# Template surface
# ---------------------------------------------------------------------------

def test_template_constant_exposes_named_placeholders() -> None:
    """The exported template must declare every kwarg render_analyst_prompt uses."""
    for placeholder in [
        "{goal_slug}", "{question}", "{run_dir}",
        "{data_scope}", "{founder_context_block}",
    ]:
        assert placeholder in ANALYST_PROMPT_TEMPLATE

"""analyst_prompt.py — render the standard analyst run header.

Captures the parts of the analyst prompt that recur across every consumer
project (claim schema, query_path rules, output file list, headings). Project-
specific bits (founder context, data scope description) are runtime params so
consumers like consumer-repo inject their own without forking the template.

Append persona instructions to the rendered string yourself — they vary per
council member and live in the consumer repo.

History:
- Original lived inline at consumer-repo/src/consumer-repo/analyst/runner.py
  as `_ANALYST_HEADER` from 2026-04-24 through 2026-06-09.
- 2026-06-09: extracted to insight-kit (B3 of eval-harness extraction).
- `query_path` rules block was hardened 2026-06-09 (PR #8 on consumer-repo)
  after omp drift emitted multi-source concatenated paths.
"""
from __future__ import annotations

from pathlib import Path

ANALYST_PROMPT_TEMPLATE = """\
# Analyst run: {goal_slug}

**Goal question:** {question}
{founder_context_block}
## Data scope

{data_scope}

## Your task

Apply your Analytical Method (from your identity file) to answer the goal question.

For each finding, emit a derived claim in `claims.jsonl` with the following fields:

```json
{{
  "claim_id":         "<allocated via ClaimAllocator(tier='derived')>",
  "tier":             "derived",
  "goal":             "{goal_slug}",
  "statement":        "<one sentence>",
  "query_path":       "queries/<claim_id>.sql",
  "result_snapshot":  "<key number or table>",
  "interpretation":   "<what it means for the goal>",
  "confidence":       "High | Med | Low",
  "confidence_reason":"<sample size, data freshness, known gaps>",
  "cites":            ["<MD-XX>", ...]
}}
```

**`query_path` rules — strict, no exceptions:**
- Exactly ONE path. Single string. No spaces, no concatenation.
- Format MUST be `queries/<claim_id>.sql` (full `.sql` extension required).
- For composite/derived claims that build on upstream queries, reference
  those upstream claim_ids in the `cites` array — NOT in `query_path`.
- Every claim writes its own SQL to `queries/<claim_id>.sql` even if that
  SQL only re-derives a small slice from upstream data.

Archive each SQL query to `queries/<claim_id>.sql`.

Write the narrative to `findings_analyst.md` — lead with the highest-leverage
finding, then support findings, then limitations.

Output files (relative to your run dir `{run_dir}`):
- `findings_analyst.md`
- `claims.jsonl` (append — file is pre-created with header comment)
- `queries/<claim_id>.sql` for each query

## Persona instructions
"""


def render_analyst_prompt(
    *,
    goal_slug: str,
    question: str,
    run_dir: Path | str,
    data_scope: str = "*(no data scope provided)*",
    founder_context: str = "",
) -> str:
    """Render the analyst prompt header.

    Args:
        goal_slug:       short kebab/snake identifier for the analyst run.
                         Used in the title heading + claim `goal` field.
        question:        the analyst's goal question (one or more paragraphs).
        run_dir:         path where the analyst should write outputs. Rendered
                         verbatim into the prompt — accept str or Path.
        data_scope:      pre-formatted markdown listing the data sources the
                         analyst should pull from. Consumers format this their
                         own way (Meta JSON paths, Shopify parquet tables,
                         prior MD-* claim files, etc.). Default placeholder
                         flags an unconfigured run.
        founder_context: optional one-paragraph business context that biases
                         the analyst's framing (e.g. "April is the worst
                         month on record..."). Omit (empty string) to skip
                         the entire **Founder context:** block.

    Returns:
        The full header string. Caller is responsible for appending persona
        instructions immediately after (the template ends at
        `## Persona instructions\\n`).
    """
    founder_block = ""
    if founder_context:
        founder_block = f"\n**Founder context:** {founder_context}\n"

    return ANALYST_PROMPT_TEMPLATE.format(
        goal_slug=goal_slug,
        question=question,
        run_dir=run_dir,
        data_scope=data_scope,
        founder_context_block=founder_block,
    )

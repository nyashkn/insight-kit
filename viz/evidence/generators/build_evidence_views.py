#!/usr/bin/env python3
"""build_evidence_views.py — create/refresh DuckDB views for Evidence reports.

Opens (or creates) <db> and builds views:
  1. claims_manifest — deduplicated claims from <runs-dir>/*/claims.jsonl
  2. claims_dedup    — latest run per claim_id
  3. claim_edges     — flattened supports/refutes/supersedes/input_claims arrays
  4. annotations     — reads <project-root>/.insight-kit/annotations.jsonl
  5. runs_manifest   — one row per run (run_id, agent_id, claim_count)

Usage:
  python3 build_evidence_views.py --project-root /path/to/consumer
  python3 build_evidence_views.py --project-root /path/to/consumer --db /path/to/file.duckdb
  python3 build_evidence_views.py --project-root /path/to/consumer --runs-dir /path/to/runs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create/refresh DuckDB views for Evidence reports.",
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="Absolute path to the consumer project root (e.g. example-ops-insight-kit/).",
    )
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="Evidence project dir. Default: <project-root>/reports",
    )
    parser.add_argument(
        "--db",
        default=None,
        help=(
            "DuckDB file path. "
            "Default: <project-root>/.insight-kit/duckdb/<basename>.duckdb"
        ),
    )
    parser.add_argument(
        "--runs-dir",
        default=None,
        help="claims.jsonl source dir. Default: <project-root>/.insight-kit/runs",
    )
    return parser.parse_args()


def resolve_paths(args: argparse.Namespace):
    project_root = Path(args.project_root).resolve()

    reports_dir = (
        Path(args.reports_dir).resolve()
        if args.reports_dir
        else project_root / "reports"
    )

    runs_dir = (
        Path(args.runs_dir).resolve()
        if args.runs_dir
        else project_root / ".insight-kit" / "runs"
    )

    if args.db:
        db_path = Path(args.db).resolve()
    else:
        # Infer from existing .duckdb files in .insight-kit/duckdb/
        duck_dir = project_root / ".insight-kit" / "duckdb"
        existing = sorted(duck_dir.glob("*.duckdb")) if duck_dir.exists() else []
        if existing:
            db_path = existing[0]
        else:
            db_path = duck_dir / f"{project_root.name}.duckdb"

    annotations_path = project_root / ".insight-kit" / "annotations.jsonl"

    return project_root, reports_dir, runs_dir, db_path, annotations_path


def sql_claims_manifest(claims_glob: str) -> str:
    return f"""
CREATE OR REPLACE VIEW claims_manifest AS
SELECT
  c.claim_id,
  c.tier,
  c.statement,
  c.confidence,
  c.run_id,
  c.agent_id,
  c.status,
  c.version,
  regexp_extract(filename, '([^/]+)/claims\\.jsonl$', 1) AS _src_run_id
FROM read_json(
  '{claims_glob}',
  format        = 'newline_delimited',
  union_by_name = true,
  filename      = true,
  ignore_errors = true
) AS c
WHERE c.claim_id IS NOT NULL
  AND c.statement IS NOT NULL
"""


def sql_claims_dedup() -> str:
    """Deduplicated view — latest run per claim_id."""
    return """
CREATE OR REPLACE VIEW claims_dedup AS
SELECT *
FROM (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY claim_id ORDER BY run_id DESC) AS rn
  FROM claims_manifest
)
WHERE rn = 1
ORDER BY claim_id
"""


def sql_claim_edges(claims_glob: str) -> str:
    """Flatten supports/refutes/supersedes/input_claims arrays → (from_id, to_id, edge_type)."""
    return f"""
CREATE OR REPLACE VIEW claim_edges AS
WITH base AS (
  SELECT
    c.claim_id,
    c.supports,
    c.refutes,
    c.supersedes,
    c.input_claims
  FROM read_json(
    '{claims_glob}',
    format        = 'newline_delimited',
    union_by_name = true,
    filename      = true,
    ignore_errors = true
  ) AS c
  WHERE c.claim_id IS NOT NULL
),
valid_ids AS (
  SELECT DISTINCT claim_id FROM base
),
unnested_supports AS (
  SELECT claim_id AS from_id, unnest(supports) AS to_id, 'supports' AS edge_type
  FROM base WHERE supports IS NOT NULL AND len(supports) > 0
),
unnested_refutes AS (
  SELECT claim_id AS from_id, unnest(refutes) AS to_id, 'refutes' AS edge_type
  FROM base WHERE refutes IS NOT NULL AND len(refutes) > 0
),
unnested_supersedes AS (
  SELECT claim_id AS from_id, unnest(supersedes) AS to_id, 'supersedes' AS edge_type
  FROM base WHERE supersedes IS NOT NULL AND len(supersedes) > 0
),
unnested_input AS (
  SELECT claim_id AS from_id, unnest(input_claims) AS to_id, 'input_claims' AS edge_type
  FROM base WHERE input_claims IS NOT NULL AND len(input_claims) > 0
),
all_edges AS (
  SELECT * FROM unnested_supports
  UNION ALL SELECT * FROM unnested_refutes
  UNION ALL SELECT * FROM unnested_supersedes
  UNION ALL SELECT * FROM unnested_input
)
SELECT DISTINCT
  from_id,
  to_id,
  edge_type
FROM all_edges
WHERE from_id IN (SELECT claim_id FROM valid_ids)
  AND to_id   IN (SELECT claim_id FROM valid_ids)
ORDER BY from_id, edge_type, to_id
"""


def sql_annotations(annotations_path: str) -> str:
    """Annotations view — reads .insight-kit/annotations.jsonl into a queryable view."""
    return f"""
CREATE OR REPLACE VIEW annotations AS
SELECT
  annotation_id,
  claim_id,
  annotator,
  ts,
  signal,
  value,
  rationale,
  acted_on,
  validated
FROM read_json(
  '{annotations_path}',
  format        = 'newline_delimited',
  union_by_name = true,
  ignore_errors = true
)
WHERE claim_id IS NOT NULL
ORDER BY claim_id, signal
"""


def sql_runs_manifest() -> str:
    return """
CREATE OR REPLACE VIEW runs_manifest AS
SELECT DISTINCT
  run_id,
  agent_id,
  COUNT(*) AS claim_count
FROM claims_manifest
GROUP BY run_id, agent_id
ORDER BY run_id DESC
"""


def main() -> None:
    args = parse_args()
    project_root, reports_dir, runs_dir, db_path, annotations_path = resolve_paths(args)

    claims_glob = str(runs_dir / "*/claims.jsonl")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Project root : {project_root}")
    print(f"Reports dir  : {reports_dir}")
    print(f"Runs dir     : {runs_dir}")
    print(f"DuckDB       : {db_path}")
    print(f"Annotations  : {annotations_path}")
    print()
    print(f"Opening DuckDB: {db_path}")
    con = duckdb.connect(str(db_path))

    views = [
        ("claims_manifest", sql_claims_manifest(claims_glob)),
        ("claims_dedup",    sql_claims_dedup()),
        ("runs_manifest",   sql_runs_manifest()),
        ("claim_edges",     sql_claim_edges(claims_glob)),
        ("annotations",     sql_annotations(str(annotations_path))),
    ]

    for name, sql in views:
        try:
            con.execute(sql)
            n = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"  [OK] {name}: {n} rows")
        except Exception as exc:
            print(f"  [ERR] {name}: {exc}")
            con.close()
            sys.exit(1)

    con.close()
    print(f"\nDuckDB ready: {db_path}")


if __name__ == "__main__":
    main()

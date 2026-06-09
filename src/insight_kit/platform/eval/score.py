#!/usr/bin/env python3
"""score.py — structural + semantic score for an analyst/critic run directory.

Scoring: 9 checks, score = passed / 9 (transparent flat weighting).
Rationale: flat weighting keeps the denominator obvious and deterministic;
structural-vs-semantic split would add opaque bucketing without calibrated
weights — revisit once Harbor reward functions are live and we have empirical
failure-mode frequency data.

Checks 1-6: structural completeness (original).
Check 7:    claim_id regex — guards against malformed/missing IDs.
            Accepts numeric (-001) and critic threading (-T01) suffixes.
Check 8:    citation cross-check — every MD-D-* claim must declare a non-empty
            query_path field, and every path it cites must exist on disk.
            Accepts .sql and .py (extraction script) citations, and whitespace-
            separated multi-source citations for derived/composite claims.
Check 9:    length prior on findings_*.md — guards stub-passes-as-substantive
            (the failure mode flagged in insight-kit/.html-kit/15_).

Length prior bounds (2000-50000 bytes) calibrated from the May 25 good run:
  findings_analyst.md = 7,526 bytes  findings_critic.md = 8,725 bytes
Lower bound 2000: well above a meaningful stub (~400 already catches the bare
minimum for findings_analyst; 2000 per file requires both to be substantive).
Upper bound 50000: 6x the real output — catches run-away noise / blob injection.

Prints diagnostics to stderr and a single float in [0.0, 1.0] on stdout.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Regex for valid claim IDs, derived from real analyst/critic runs:
#   analyst: MD-D-G6-001, MD-D-G6F7-001 (goal+sub-goal combined)
#   critic:  MD-C-G6-001, MD-C-G6F7-001, MD-C-G6-T01 (omp critic threading variant)
# Goal segment is [A-Z][A-Z0-9]+ to accept G6 and G6F7-style drift.
# Suffix accepts 3-digit numeric OR T-prefixed 2-digit (critic threading).
CLAIM_ID_RE = re.compile(r"^MD-[DC]-[A-Z][A-Z0-9]+-(?:\d{3}|T\d{2})$")

# Length prior bounds (bytes) — see module docstring for calibration notes
FINDINGS_MIN_BYTES = 2_000
FINDINGS_MAX_BYTES = 50_000


def score(run_dir: Path) -> float:
    checks: list[tuple[str, bool]] = []

    # --- checks 1-3: claims.jsonl structural ---
    claim_objs: list[dict] = []
    claims = run_dir / "claims.jsonl"
    if claims.exists():
        for line in claims.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                claim_objs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    checks.append(("claims.jsonl has >=1 valid claim", len(claim_objs) >= 1))
    checks.append(
        ("analyst claims (MD-D-*) present",
         any(str(c.get("claim_id", "")).startswith("MD-D") for c in claim_objs)))
    checks.append(
        ("critic claims (MD-C-*) present",
         any(str(c.get("claim_id", "")).startswith("MD-C") for c in claim_objs)))

    # --- check 4: findings_analyst.md structural ---
    fa = run_dir / "findings_analyst.md"
    fa_text = fa.read_text() if fa.exists() else ""
    checks.append(
        ("findings_analyst.md written (non-stub)",
         bool(fa_text) and "replace this stub" not in fa_text and len(fa_text) > 400))

    # --- check 5: findings_critic.md structural ---
    fc = run_dir / "findings_critic.md"
    fc_text = fc.read_text() if fc.exists() else ""
    checks.append(("findings_critic.md present", len(fc_text) > 200))

    # --- check 6: queries archived ---
    qdir = run_dir / "queries"
    checks.append(
        ("queries/*.sql archived", qdir.is_dir() and any(qdir.glob("*.sql"))))

    # --- check 7: claim_id regex validation ---
    invalid_ids = [
        str(c.get("claim_id", ""))
        for c in claim_objs
        if not CLAIM_ID_RE.match(str(c.get("claim_id", "")))
    ]
    check7_ok = len(invalid_ids) == 0
    if not check7_ok:
        print(
            f"  [FAIL] claim_id regex: {len(invalid_ids)} invalid ID(s): "
            f"{invalid_ids[:5]}{'...' if len(invalid_ids) > 5 else ''}",
            file=sys.stderr,
        )
    checks.append(("claim_id regex (^MD-[DC]-[A-Z][A-Z0-9]+-(\\d{3}|T\\d{2})$)", check7_ok))

    # --- check 8: citation cross-check ---
    # Honour the claim's declared query_path field instead of hardcoding
    # queries/<id>.sql. Supports .sql + .py extractors and whitespace-separated
    # multi-source citations (derived claims composed from upstream queries).
    citation_failures: list[str] = []
    for c in claim_objs:
        cid = str(c.get("claim_id", ""))
        if not cid.startswith("MD-D-"):
            continue
        qp = str(c.get("query_path", "")).strip()
        if not qp:
            citation_failures.append(f"{cid} (no query_path)")
            continue
        for tok in qp.split():
            rel = tok if "/" in tok else f"queries/{tok}"
            if not (run_dir / rel).exists():
                citation_failures.append(f"{cid}->{rel}")
    check8_ok = len(citation_failures) == 0
    if not check8_ok:
        print(
            f"  [FAIL] citation cross-check: {len(citation_failures)} failure(s): "
            f"{citation_failures[:5]}{'...' if len(citation_failures) > 5 else ''}",
            file=sys.stderr,
        )
    checks.append(("citation cross-check (query_path resolves on disk)", check8_ok))

    # --- check 9: length prior on findings_*.md ---
    fa_bytes = len(fa_text.encode())
    fc_bytes = len(fc_text.encode())
    length_failures: list[str] = []
    for name, nbytes in [("findings_analyst.md", fa_bytes), ("findings_critic.md", fc_bytes)]:
        if nbytes < FINDINGS_MIN_BYTES:
            length_failures.append(
                f"{name} too short ({nbytes} bytes < {FINDINGS_MIN_BYTES} — stub-like)")
        elif nbytes > FINDINGS_MAX_BYTES:
            length_failures.append(
                f"{name} too long ({nbytes} bytes > {FINDINGS_MAX_BYTES} — noise/blob)")
    check9_ok = len(length_failures) == 0
    if not check9_ok:
        for msg in length_failures:
            print(f"  [FAIL] length prior: {msg}", file=sys.stderr)
    checks.append((
        f"length prior ({FINDINGS_MIN_BYTES}-{FINDINGS_MAX_BYTES} bytes per findings file)",
        check9_ok,
    ))

    # --- summary ---
    passed = sum(1 for _, ok in checks if ok)
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}", file=sys.stderr)
    print(f"  {passed}/{len(checks)} checks passed", file=sys.stderr)
    return passed / len(checks)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m insight_kit.platform.eval.score <run_dir>", file=sys.stderr)
        sys.exit(2)

    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"run dir not found: {run_dir}", file=sys.stderr)
        print("0.0")
        return

    print(f"{score(run_dir):.4f}")


if __name__ == "__main__":
    main()

"""
ik_migrate_critic_inline.py
============================
Migrates standalone C-tier critic claims into inline ``critiques[]`` entries
embedded on their target D-tier claims, as specified by the provenance-loop
design at §3 L6 of provenance-loop.html.

WHY
---
The provenance-loop spec (§3 L6) proposes that critic challenges become a
``critiques[]`` array embedded directly on the challenged D-claim rather than
floating as independent sibling entries in claims.jsonl.  This makes the
challenge non-ignorable: any reader or tool looking at DOCK-D-005 will see its
critic record inline, without needing to cross-reference a separate run's
claims file.

CROSS-REFERENCE
---------------
docs/hamilton-synthesis/provenance-loop.html  §3 L6
"Critic challenge surfaces in ProvenanceRail"

WHAT THIS SCRIPT DOES
---------------------
1. Walks every claims.jsonl under <root> (default: .insight-kit/runs/).
2. Builds an index of all D-tier claims keyed by claim_id, recording which
   jsonl file and line number they live on.
3. For each C-tier claim, resolves its targets via:
     a. The ``refutes`` field (list of claim_ids), if present.
     b. Else the ``input_claims`` field.
4. Constructs a critique record:
     {
       "critique_id":            <C-claim's claim_id>,
       "by_run":                 <run name derived from the C-claim's file path>,
       "severity":               <C-claim's severity field, default "medium">,
       "statement":              <C-claim's statement>,
       "resolution":             "open",
       "original_c_claim_id":    <C-claim's claim_id>
     }
5. Dry-run: prints what would change and a summary count.
6. Real mode:
   - Creates a .bak sibling of the target jsonl before first modification.
   - Rewrites only the target D-claim's line in-place, appending to its
     ``critiques`` array (initialised to [] if absent).
7. Idempotent: skips if a critique with the same ``original_c_claim_id``
   already exists on the target claim.
8. Warns and skips gracefully if a target D-claim cannot be found.

USAGE
-----
  python scripts/ik_migrate_critic_inline.py                          # default root
  python scripts/ik_migrate_critic_inline.py .insight-kit/runs/ --dry-run
  python scripts/ik_migrate_critic_inline.py /abs/path/to/runs/

NO EXTERNAL DEPENDENCIES — stdlib only (json, pathlib, argparse, shutil).
"""

import argparse
import json
import shutil
import sys
import warnings
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_name_from_path(jsonl_path: Path) -> str:
    """Return the run directory name (immediate parent) from a claims.jsonl path."""
    return jsonl_path.parent.name


def _iter_claims(jsonl_path: Path):
    """Yield (line_index, raw_line, parsed_dict) for every non-comment, non-blank line."""
    with jsonl_path.open(encoding="utf-8") as fh:
        for idx, raw in enumerate(fh):
            stripped = raw.rstrip("\n")
            if not stripped or stripped.lstrip().startswith("#"):
                yield idx, stripped, None
            else:
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    warnings.warn(f"[WARN] Could not parse line {idx + 1} in {jsonl_path}: {stripped[:80]!r}")
                    yield idx, stripped, None
                else:
                    yield idx, stripped, parsed


def _rewrite_line(jsonl_path: Path, line_index: int, new_obj: dict, backed_up: set) -> None:
    """Rewrite a single JSON line in a claims.jsonl, creating a .bak first."""
    bak_path = jsonl_path.with_suffix(".jsonl.bak")
    if jsonl_path not in backed_up:
        shutil.copy2(jsonl_path, bak_path)
        backed_up.add(jsonl_path)

    lines = jsonl_path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_line = json.dumps(new_obj, ensure_ascii=False) + "\n"
    lines[line_index] = new_line
    jsonl_path.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def build_d_claim_index(root: Path) -> dict:
    """
    Walk every claims.jsonl under root.
    Return a dict: claim_id -> {"path": Path, "line_index": int, "obj": dict}
    Only indexes D-tier claims (tier == "D" or tier starts with "D" case-insensitive,
    or claim_id contains "-D-").
    """
    index: dict = {}
    for jsonl_path in sorted(root.rglob("claims.jsonl")):
        for line_idx, _, obj in _iter_claims(jsonl_path):
            if obj is None:
                continue
            tier = str(obj.get("tier", "")).upper()
            claim_id = obj.get("claim_id", "")
            # Accept tier=="D" or claim_id containing "-D-" (e.g. DOCK-D-005, MD-D-005)
            is_d = tier == "D" or tier == "DERIVED" or "-D-" in claim_id
            if is_d:
                if claim_id in index:
                    # Keep the first occurrence; warn on duplicates
                    existing = index[claim_id]
                    warnings.warn(
                        f"[WARN] Duplicate D-claim {claim_id!r}: "
                        f"already seen in {existing['path']}; "
                        f"ignoring copy in {jsonl_path}"
                    )
                else:
                    index[claim_id] = {
                        "path": jsonl_path,
                        "line_index": line_idx,
                        "obj": obj,
                    }
    return index


def build_critique_record(c_claim: dict, c_run_name: str) -> dict:
    """Construct the critique dict to embed on the target D-claim."""
    return {
        "critique_id": c_claim.get("claim_id", ""),
        "by_run": c_run_name,
        "severity": c_claim.get("severity", "medium"),
        "statement": c_claim.get("statement", ""),
        "resolution": "open",
        "original_c_claim_id": c_claim.get("claim_id", ""),
    }


def already_embedded(d_obj: dict, original_c_claim_id: str) -> bool:
    """Return True if a critique with this original_c_claim_id already exists."""
    for entry in d_obj.get("critiques", []):
        if entry.get("original_c_claim_id") == original_c_claim_id:
            return True
    return False


def resolve_targets(c_claim: dict) -> list:
    """Return the list of D-claim IDs this C-claim targets."""
    targets = c_claim.get("refutes")
    if targets:
        if isinstance(targets, str):
            return [targets]
        return list(targets)
    # Fallback to input_claims
    targets = c_claim.get("input_claims")
    if targets:
        if isinstance(targets, str):
            return [targets]
        return list(targets)
    return []


def migrate(root: Path, dry_run: bool) -> None:
    print(f"[info] Root: {root}")
    print(f"[info] Mode: {'DRY RUN (no files written)' if dry_run else 'REAL (files will be modified)'}")
    print()

    # Phase 1: build D-claim index
    d_index = build_d_claim_index(root)
    print(f"[info] Indexed {len(d_index)} D-tier claims across all runs.")

    # Phase 2: walk C-claims and plan mutations
    actions = []  # list of (c_claim, c_run_name, target_id, critique_record)
    skipped_no_target = 0
    skipped_idempotent = 0
    skipped_no_d_found = 0

    for jsonl_path in sorted(root.rglob("claims.jsonl")):
        run_name = _run_name_from_path(jsonl_path)
        for _, _, obj in _iter_claims(jsonl_path):
            if obj is None:
                continue
            tier = str(obj.get("tier", "")).upper()
            claim_id = obj.get("claim_id", "")
            is_c = tier == "C" or tier == "CRITIC" or "-C-" in claim_id
            if not is_c:
                continue

            # Already superseded in a previous run of this script
            if obj.get("superseded_by_inline"):
                continue

            targets = resolve_targets(obj)
            if not targets:
                warnings.warn(
                    f"[WARN] C-claim {claim_id!r} in {jsonl_path} has no "
                    f"'refutes' or 'input_claims' field — skipping."
                )
                skipped_no_target += 1
                continue

            critique = build_critique_record(obj, run_name)

            for target_id in targets:
                if target_id not in d_index:
                    warnings.warn(
                        f"[WARN] C-claim {claim_id!r} targets {target_id!r} "
                        f"but no D-claim with that id was found — skipping."
                    )
                    skipped_no_d_found += 1
                    continue

                d_entry = d_index[target_id]
                if already_embedded(d_entry["obj"], claim_id):
                    skipped_idempotent += 1
                    continue

                actions.append((obj, jsonl_path, run_name, target_id, critique))

    print(f"[info] C-claims skipped (no target field):  {skipped_no_target}")
    print(f"[info] C-claims skipped (target D missing): {skipped_no_d_found}")
    print(f"[info] C-claims skipped (already embedded): {skipped_idempotent}")
    print(f"[info] Actions to apply:                    {len(actions)}")
    print()

    if not actions:
        print("[info] Nothing to do.")
        return

    # Phase 3: apply (or print)
    backed_up: set = set()
    applied = 0

    for (c_obj, c_jsonl_path, run_name, target_id, critique) in actions:
        c_id = c_obj.get("claim_id", "")
        d_entry = d_index[target_id]
        d_jsonl_path = d_entry["path"]
        d_run = _run_name_from_path(d_jsonl_path)

        if dry_run:
            print(
                f"  would append critique {c_id!r} → claim {target_id!r} "
                f"in run {d_run!r}  ({d_jsonl_path})"
            )
        else:
            # Mutate the in-memory D-claim object
            d_obj = d_entry["obj"]
            if "critiques" not in d_obj:
                d_obj["critiques"] = []
            d_obj["critiques"].append(critique)

            # Rewrite the D-claim's line in its jsonl
            _rewrite_line(d_jsonl_path, d_entry["line_index"], d_obj, backed_up)

            # Mark the C-claim as superseded_by_inline in its own jsonl
            c_lines = list(_iter_claims(c_jsonl_path))
            for line_idx, _, parsed in c_lines:
                if parsed and parsed.get("claim_id") == c_id:
                    parsed["superseded_by_inline"] = True
                    _rewrite_line(c_jsonl_path, line_idx, parsed, backed_up)
                    break

            print(
                f"  [OK] embedded {c_id!r} → {target_id!r} "
                f"(run: {d_run!r})"
            )
            applied += 1

    print()
    if dry_run:
        print(f"[dry-run] Would apply {len(actions)} critique embedding(s). Re-run without --dry-run to commit.")
    else:
        print(f"[done] Applied {applied} critique embedding(s). Backups written with .jsonl.bak suffix.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Migrate standalone C-tier critic claims into inline critiques[] "
            "on their target D-claims. See provenance-loop.html §3 L6."
        )
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".insight-kit/runs/",
        help="Root directory to walk for claims.jsonl files (default: .insight-kit/runs/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without modifying any file.",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        print(f"[error] Root path does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    migrate(root, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

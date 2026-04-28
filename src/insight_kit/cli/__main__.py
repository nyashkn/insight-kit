"""`ik` CLI — minimal v0.1: init, info, annotate, preflight, viz."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from insight_kit import __version__
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config
from insight_kit.validation import check_claim_id_unique


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    target = init_kit(root, namespace=args.namespace, force=args.force)
    print(f"initialized: {target}")
    print(f"namespace:   {args.namespace}")
    print("next: edit .insight-kit/agents.yaml + .insight-kit/goals/catalog.yaml")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    try:
        root = find_kit_root()
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    cfg = kit_config()
    print(f"kit_root:    {root}")
    print(f"kit_dir:     {root / '.insight-kit'}")
    print(f"namespace:   {cfg.get('namespace', '(unset)')}")
    print(f"kit_version: {__version__}")
    return 0


def cmd_annotate(args: argparse.Namespace) -> int:
    from insight_kit.annotations import annotate

    rec = annotate(
        claim_id=args.claim_id,
        acted_on=args.acted,
        validated=args.validated,
        note=args.note,
        annotator=args.annotator,
    )
    print(
        f"recorded: {rec['annotation_id']}  claim={rec['claim_id']}  "
        f"acted={rec['acted_on']}  validated={rec['validated']}"
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Layer C: scan all runs and report validation errors."""
    try:
        root = find_kit_root()
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    errors = check_claim_id_unique(root)
    if not errors:
        print("ok: no validation errors found")
        return 0
    for err in errors:
        print(f"[{err.rule_id}] {err}", file=sys.stderr)
    print(f"error: {len(errors)} validation error(s) found", file=sys.stderr)
    return 1


def cmd_annotations(args: argparse.Namespace) -> int:
    from insight_kit.annotations import iter_annotations

    n = 0
    acted = 0
    validated = 0
    for rec in iter_annotations(args.claim_id):
        n += 1
        acted += int(rec.get("acted_on", False))
        validated += int(rec.get("validated", False))
        print(json.dumps(rec))
    if args.summary:
        print(
            f"--- total: {n}  acted: {acted}  validated: {validated} ---",
            file=sys.stderr,
        )
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    """Run preflight checks via Bun entry point."""
    cli_ts = Path(__file__).resolve().parents[3] / "viz" / "core" / "cli.ts"
    if not cli_ts.exists():
        print(f"error: cli.ts not found at {cli_ts}", file=sys.stderr)
        return 1

    cmd = ["bun", str(cli_ts)]
    cmd += ["--reports-dir", str(Path(args.reports_dir).resolve())]
    if args.layer != "all":
        cmd += ["--layer", args.layer]
    if args.pages:
        cmd += ["--pages", args.pages]
    if args.strict:
        cmd += ["--strict"]
    if args.no_screenshots:
        cmd += ["--no-screenshots"]
    if args.explain:
        cmd += ["--explain"]

    return subprocess.call(cmd)


def cmd_viz_install(args: argparse.Namespace) -> int:
    """Install a viz renderer's components/layouts into a consumer reports dir."""
    if args.renderer != "evidence":
        print(
            f"Renderer '{args.renderer}' not supported. Available: evidence",
            file=sys.stderr,
        )
        return 1

    install_ts = (
        Path(__file__).resolve().parents[3] / "viz" / "evidence" / "install-cli.ts"
    )
    if not install_ts.exists():
        print(f"error: install-cli.ts not found at {install_ts}", file=sys.stderr)
        return 1

    cmd = [
        "bun",
        str(install_ts),
        "--reports-dir",
        str(Path(args.reports_dir).resolve()),
    ]
    if args.force:
        cmd += ["--force"]
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ik", description="insight-kit CLI")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="scaffold .insight-kit/ in a project")
    p_init.add_argument("--path", default=".", help="project root (default: cwd)")
    p_init.add_argument("--namespace", required=True, help="claim namespace prefix (e.g. DOCK, MD)")
    p_init.add_argument("--force", action="store_true", help="overwrite existing .insight-kit/")
    p_init.set_defaults(func=cmd_init)

    p_info = sub.add_parser("info", help="show resolved kit root + config")
    p_info.set_defaults(func=cmd_info)

    p_annotate = sub.add_parser("annotate", help="record binary annotation on a claim")
    p_annotate.add_argument("claim_id", help="claim identifier (e.g. DOCK-D-001)")
    p_annotate.add_argument(
        "--acted",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="whether human acted on this claim",
    )
    p_annotate.add_argument(
        "--validated",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="whether human validated the outcome",
    )
    p_annotate.add_argument(
        "--note", default=None, help="optional freetext note on the annotation"
    )
    p_annotate.add_argument(
        "--annotator", default=None, help="annotator name (default: $USER)"
    )
    p_annotate.set_defaults(func=cmd_annotate)

    p_validate = sub.add_parser("validate", help="run Layer-C validations across all runs")
    p_validate.set_defaults(func=cmd_validate)

    p_annotations = sub.add_parser("annotations", help="list recorded annotations")
    p_annotations.add_argument(
        "--claim", dest="claim_id", default=None, help="filter by claim ID"
    )
    p_annotations.add_argument(
        "--summary",
        action="store_true",
        help="print summary stats to stderr",
    )
    p_annotations.set_defaults(func=cmd_annotations)

    p_preflight = sub.add_parser(
        "preflight", help="run preflight checks against an Evidence reports dir"
    )
    p_preflight.add_argument(
        "--reports-dir", default="./reports", help="path to Evidence reports dir"
    )
    p_preflight.add_argument(
        "--layer",
        default="all",
        help="comma-separated layer numbers (1-6) or 'all' (default: all)",
    )
    p_preflight.add_argument(
        "--pages",
        default=None,
        help="comma-separated page slug fragments to filter",
    )
    p_preflight.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures",
    )
    p_preflight.add_argument(
        "--no-screenshots",
        action="store_true",
        help="skip screenshot capture during L3 render checks",
    )
    p_preflight.add_argument(
        "--explain",
        action="store_true",
        help="print rule matrix and per-layer hints, then exit",
    )
    p_preflight.set_defaults(func=cmd_preflight)

    p_viz = sub.add_parser("viz", help="manage viz renderer plugins")
    viz_subs = p_viz.add_subparsers(dest="viz_cmd", required=True)
    viz_install = viz_subs.add_parser(
        "install", help="install a renderer into a reports dir"
    )
    viz_install.add_argument(
        "renderer", choices=["evidence"], help="renderer name (currently: evidence)"
    )
    viz_install.add_argument("reports_dir", help="path to the Evidence reports directory")
    viz_install.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing +layout.svelte files",
    )
    viz_install.set_defaults(func=cmd_viz_install)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

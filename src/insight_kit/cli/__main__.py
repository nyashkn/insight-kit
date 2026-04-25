"""`ik` CLI — minimal v0.1: init, info, annotate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from insight_kit import __version__
from insight_kit.provenance.root import find_kit_root, init_kit, kit_config


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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""`ik` CLI — minimal v0.1: init, info."""

from __future__ import annotations

import argparse
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

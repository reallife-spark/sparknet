#!/usr/bin/env python3
"""Check a GitFlow promotion edge without touching the repository."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from sparknet_loader import load_shared

GITFLOW = load_shared("sparknet-gitflow.py", "sparknet_gitflow_cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sparknet-gitflow")
    parser.add_argument("source", nargs="?", help="source branch")
    parser.add_argument("target", nargs="?", help="target branch")
    parser.add_argument("--describe", action="store_true")
    args = parser.parse_args(argv)
    if args.describe:
        print(json.dumps(GITFLOW.describe(), indent=2, sort_keys=True))
        return 0
    if not args.source or not args.target:
        parser.error("source and target are required unless --describe is given")
    try:
        GITFLOW.require_promotion(args.source, args.target)
    except GITFLOW.GitFlowError as exc:
        print(f"sparknet-gitflow: {exc.code}: {exc}", file=sys.stderr)
        return 2
    print(f"allow: {args.source} -> {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

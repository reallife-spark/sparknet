#!/usr/bin/env python3
"""Plan, apply and promote the O1→O2→O5 knowledge pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from sparknet_loader import load_shared

PIPELINE = load_shared("sparknet-pipeline.py", "sparknet_pipeline_cli")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sparknet-pipeline", description="O1→O2→O5 knowledge pipeline")
    parser.add_argument("--vault", default=os.environ.get("SPARKNET_VAULT_ROOT") or ".")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="show the deterministic pipeline plan")
    plan.add_argument("--today", help="date override (YYYY-MM-DD)")

    apply = sub.add_parser("apply", help="write/sign O2 and stage O5")
    apply.add_argument("--today", help="date override (YYYY-MM-DD)")
    apply.add_argument("--confirm", action="store_true", help="required to write")

    promote = sub.add_parser("promote", help="promote one staged O5 candidate")
    promote.add_argument("candidate", help="path under _staging/o5/")
    promote.add_argument("--category", required=True, choices=PIPELINE.O5_CATEGORIES)
    promote.add_argument("--confirm", action="store_true", help="required to write")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    vault = Path(args.vault).resolve()
    try:
        if args.command == "plan":
            print(json.dumps(PIPELINE.plan(vault, today=args.today), indent=2, sort_keys=True))
            return 0
        if args.command == "apply":
            planned = PIPELINE.plan(vault, today=args.today)
            result = PIPELINE.apply_plan(vault, planned["entries"], confirm=args.confirm)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        result = PIPELINE.promote(vault, args.candidate, args.category, confirm=args.confirm)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except PIPELINE.PipelineError as exc:
        print(f"sparknet-pipeline: {exc.code}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

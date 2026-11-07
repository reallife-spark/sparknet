#!/usr/bin/env python3
"""Validate one argv-only execution request; never executes it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from sparknet_loader import load_shared

EXEC = load_shared("sparknet-exec-rpc.py", "sparknet_exec_cli")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sparknet-exec", description="Validate an argv-only execution request")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate a request envelope")
    validate.add_argument("--request", required=True, help="JSON file containing the request")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        normalised = EXEC.validate_request(request, verified=True)
        print(json.dumps({"ok": True, "executed": False, "request": normalised}, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, EXEC.ExecError) as exc:
        print(f"sparknet-exec: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

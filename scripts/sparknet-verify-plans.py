#!/usr/bin/env python3
"""Rank candidate plans with the local reflex verifier — advisory only.

Input (file or stdin):
    {"query": "...", "rubric": "...", "plans": [{"id": "...", "title": "...", "body": "..."}]}

Output: the verifier result (verdict, recommendation, ranking, probabilities,
policy, latency). It never executes, grants, approves or widens anything.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY_PATH = REPO_ROOT / "shared" / "sparknet-verify.py"


def _load_verify() -> Any:
    if "sparknet_verify" in sys.modules:
        return sys.modules["sparknet_verify"]
    spec = importlib.util.spec_from_file_location("sparknet_verify", VERIFY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the verifier from {VERIFY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sparknet_verify"] = module
    spec.loader.exec_module(module)
    return module


def _read_input(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(
    argv: list[str] | None = None,
    *,
    verify_fn: Callable[..., dict[str, Any]] | None = None,
    input_loader: Callable[[str], Any] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="-", help="JSON input file, or - for stdin")
    parser.add_argument("--model", default="local", help="Model tag or the `local` sentinel")
    parser.add_argument("--timeout", type=float, default=10.0, help="Local LLM timeout in seconds")
    parser.add_argument("--min-top", type=float, default=None, help="Override the top-probability floor")
    parser.add_argument("--min-margin", type=float, default=None, help="Override the top/second margin floor")
    parser.add_argument("--policy-version", default=None, help="Policy version recorded in the result")
    parser.add_argument("--node-id", default=None, help="Node id recorded in the request")
    parser.add_argument("--compact", action="store_true", help="Emit one-line JSON")
    args = parser.parse_args(argv)

    loader = input_loader or _read_input
    try:
        payload = loader(args.input)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": f"cannot read input: {exc}"}), file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print(json.dumps({"error": "input must be an object"}), file=sys.stderr)
        return 2

    verify = verify_fn or _load_verify().verify_plans
    policy: dict[str, float] = {}
    if args.min_top is not None:
        policy["min_top"] = args.min_top
    if args.min_margin is not None:
        policy["min_margin"] = args.min_margin
    kwargs: dict[str, Any] = {"model": args.model, "timeout_s": args.timeout}
    if policy:
        kwargs["policy"] = policy
    if args.policy_version:
        kwargs["policy_version"] = args.policy_version
    if args.node_id:
        kwargs["node_id"] = args.node_id
    if payload.get("forbid") is not None:
        kwargs["forbid"] = payload["forbid"]

    try:
        result = verify(payload.get("query"), payload.get("rubric"), payload.get("plans"), **kwargs)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

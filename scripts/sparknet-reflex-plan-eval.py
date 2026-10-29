#!/usr/bin/env python3
"""Live calibration for ``plan.select`` — top-1 agreement, coverage, ECE.

The local LLM is advisory. This harness measures how often its recommendation
matches the golden label, how often the policy abstains, and whether the
probability it reports is calibrated. It is live-only: a fake backend can test
the metric code but cannot calibrate a model.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY_PATH = REPO_ROOT / "shared" / "sparknet-verify.py"
GOLDEN_PATH = REPO_ROOT / "tests" / "reflex" / "plans-golden.json"


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


def load_golden(path: Path, verify: Any) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"reflex-plan-eval: cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise SystemExit(f"reflex-plan-eval: {path} is not valid JSON: {exc}") from exc
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise SystemExit("reflex-plan-eval: golden set needs a non-empty 'cases' list")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"].strip():
            raise SystemExit(f"reflex-plan-eval: case[{index}] needs a non-empty 'id'")
        case_id = case["id"].strip()
        if case_id in seen:
            raise SystemExit(f"reflex-plan-eval: duplicate case id {case_id!r}")
        seen.add(case_id)
        try:
            plans = verify.normalize_plans(case.get("plans"))
        except verify.PlanEnvelopeError as exc:
            raise SystemExit(f"reflex-plan-eval: case {case_id}: {exc}") from exc
        expected = case.get("expected")
        plan_ids = {p["id"] for p in plans}
        if not isinstance(expected, str) or (expected != verify.NONE_OPTION and expected not in plan_ids):
            raise SystemExit(f"reflex-plan-eval: case {case_id}: expected must name a plan id or 'none'")
        for field in ("query", "rubric"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise SystemExit(f"reflex-plan-eval: case {case_id}: {field} must be a non-empty string")
        try:
            forbid = verify.normalize_forbid(case.get("forbid"))
        except verify.PlanEnvelopeError as exc:
            raise SystemExit(f"reflex-plan-eval: case {case_id}: {exc}") from exc
        normalized.append(
            {
                "id": case_id,
                "query": case["query"],
                "rubric": case["rubric"],
                "plans": plans,
                "expected": expected,
                "forbid": forbid,
            }
        )
    return {"name": payload.get("name", path.stem), "version": payload.get("version"), "cases": normalized}


def ece(rows: list[dict[str, Any]]) -> float:
    """Expected calibration error over accepted recommendations."""
    accepted = [row for row in rows if row["verdict"] == "accept" and row["top_probability"] is not None]
    if not accepted:
        return 0.0
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in accepted:
        index = max(0, min(9, int(row["top_probability"] * 10)))
        buckets.setdefault(index, []).append(row)
    total = len(accepted)
    value = 0.0
    for bucket in buckets.values():
        confidence = sum(float(row["top_probability"]) for row in bucket) / len(bucket)
        accuracy = sum(1 for row in bucket if row["correct"]) / len(bucket)
        value += (len(bucket) / total) * abs(accuracy - confidence)
    return value


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def evaluate(
    golden: dict[str, Any],
    *,
    verify_fn: Callable[..., dict[str, Any]],
    model: str,
    timeout: float,
    policy: dict[str, float] | None = None,
    policy_version: str | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in golden["cases"]:
        kwargs: dict[str, Any] = {"model": model, "timeout_s": timeout}
        if policy:
            kwargs["policy"] = policy
        if policy_version:
            kwargs["policy_version"] = policy_version
        if case.get("forbid"):
            kwargs["forbid"] = case["forbid"]
        result = verify_fn(case["query"], case["rubric"], case["plans"], **kwargs)
        recommendation = result.get("recommendation")
        top_probability = result["ranking"][0]["probability"] if result.get("ranking") else None
        # A correct decision is an accepted top-1 match, or an abstain when the
        # golden label is "none": abstaining on a violating plan is a success,
        # not a miss.
        if result.get("verdict") == "accept":
            correct = recommendation == case["expected"]
        else:
            correct = case["expected"] == "none"
        rows.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "verdict": result.get("verdict"),
                "reason": result.get("reason"),
                "recommendation": recommendation,
                "correct": correct,
                "top_probability": top_probability,
                "none_probability": result.get("none_probability"),
                "latency_ms": float(result.get("latency_ms") or 0.0),
                "backend": result.get("backend"),
                "model": result.get("model"),
                "policy_version": result.get("policy_version"),
            }
        )
    total = len(rows)
    accepted = [row for row in rows if row["verdict"] == "accept"]
    correct = sum(1 for row in rows if row["correct"] and row["verdict"] == "accept")
    false_accepts = sum(1 for row in accepted if not row["correct"])
    summary = {
        "golden": golden.get("name"),
        "golden_version": golden.get("version"),
        "cases": total,
        "model": model,
        "policy_version": policy_version,
        "policy": policy,
        "top1_agreement": correct / total if total else 0.0,
        "coverage": len(accepted) / total if total else 0.0,
        "abstain_rate": (total - len(accepted)) / total if total else 0.0,
        "false_accepts": false_accepts,
        "ece": ece(rows),
        "p95_latency_ms": percentile([row["latency_ms"] for row in rows], 0.95),
        "cost_per_1k_usd": 0.0,
    }
    return {"summary": summary, "rows": rows}


def _print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        f"reflex-plan-eval: golden={summary['golden']} cases={summary['cases']} "
        f"model={summary['model']} policy={summary['policy_version'] or 'default'}"
    )
    print(f"  top-1 agreement = {summary['top1_agreement']:.3f}")
    print(f"  coverage        = {summary['coverage']:.3f} (abstain {summary['abstain_rate']:.3f})")
    print(f"  ECE (accepted)  = {summary['ece']:.3f}")
    print(f"  false accepts   = {summary['false_accepts']}")
    print(f"  p95 latency     = {summary['p95_latency_ms']:.1f} ms")
    print(f"  cost / 1k       = ${summary['cost_per_1k_usd']:.4f}")
    for row in report["rows"]:
        if row["correct"] and row["verdict"] == "accept":
            mark = "ok"
        elif row["correct"] and row["verdict"] == "abstain":
            mark = "ok-abst"
        elif row["verdict"] == "abstain":
            mark = "abstain"
        else:
            mark = "MISS"
        probability = "-" if row["top_probability"] is None else f"{row['top_probability']:.3f}"
        print(
            f"  [{mark:7}] {row['id']}: expected={row['expected']} "
            f"recommendation={row['recommendation']} p={probability} "
            f"{row['latency_ms']:.0f} ms {row['reason'] or ''}".rstrip()
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--golden", default=str(GOLDEN_PATH), help="Golden plan set")
    parser.add_argument("--model", default="local", help="Model tag or the `local` sentinel")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-case local LLM timeout")
    parser.add_argument("--min-top", type=float, default=None, help="Override the top-probability floor")
    parser.add_argument("--min-margin", type=float, default=None, help="Override the top/second margin floor")
    parser.add_argument("--policy-version", default=None, help="Policy version recorded in the result")
    parser.add_argument("--json", default=None, help="Write the full report to this path (- for stdout)")
    parser.add_argument("--check", action="store_true", help="Print the configuration and exit")
    parser.add_argument("--live", action="store_true", help="Call the local model (required unless REFLEX_LIVE=1)")
    args = parser.parse_args(argv)

    if args.check:
        print(
            json.dumps(
                {
                    "service": "reflex-plan-eval",
                    "golden": args.golden,
                    "model": args.model,
                    "local_url": os.environ.get("SPARKNET_REFLEX_LOCAL_URL", "http://127.0.0.1:8000"),
                    "local_model": os.environ.get("SPARKNET_REFLEX_LOCAL_MODEL", ""),
                    "timeout": args.timeout,
                },
                indent=2,
            )
        )
        return 0

    live = args.live or os.environ.get("REFLEX_LIVE", "").strip().lower() in ("1", "true", "yes")
    if not live:
        print("reflex-plan-eval: pass --live (or REFLEX_LIVE=1) to call the local model", file=sys.stderr)
        return 2

    verify = _load_verify()
    golden = load_golden(Path(args.golden), verify)
    policy: dict[str, float] = {}
    if args.min_top is not None:
        policy["min_top"] = args.min_top
    if args.min_margin is not None:
        policy["min_margin"] = args.min_margin
    report = evaluate(
        golden,
        verify_fn=verify.verify_plans,
        model=args.model,
        timeout=args.timeout,
        policy=policy or None,
        policy_version=args.policy_version,
    )
    _print_report(report)
    if args.json is not None:
        payload = json.dumps(report, indent=2, sort_keys=True)
        if args.json == "-":
            print(payload)
        else:
            Path(args.json).write_text(payload + "\n", encoding="utf-8")
    if all(row["reason"] == "backend-error" for row in report["rows"]):
        print(
            "reflex-plan-eval: every case abstained at the backend; check "
            "SPARKNET_REFLEX_LOCAL_URL / SPARKNET_REFLEX_LOCAL_MODEL",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

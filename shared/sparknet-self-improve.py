#!/usr/bin/env python3
"""Bounded self-improvement run records and deterministic benchmark decisions.

A run is a proposal. It may create a worktree, apply a patch and run a benchmark,
but promotion is a separate explicit action. This module never merges, deploys or
runs a model by itself.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

SKILL_EVAL = load_shared("sparknet-skill-eval.py", "sparknet_skill_eval")

SCHEMA = "sparknet-self-improvement/1"
MODES = ("worktree", "firecracker")
DECISIONS = ("pending", "promote", "rollback")


class SelfImproveError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise SelfImproveError(code, message)


def _number(value: Any, code: str, field: str) -> float:
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), code, f"{field} must be a number")
    return float(value)


def _review_row(skill_eval: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate the reviewer verdict; any doubt is a block, never a pass."""
    if skill_eval is None:
        return {"passed": False, "reason": "missing"}
    if not isinstance(skill_eval, Mapping):
        return {"passed": False, "reason": "invalid", "detail": "record must be an object"}
    try:
        record = SKILL_EVAL.validate_record(dict(skill_eval))
    except SKILL_EVAL.SkillEvalError as exc:
        return {"passed": False, "reason": "invalid", "detail": str(exc)}
    verdict = record["verdict"]
    return {"passed": verdict == "pass", "reason": verdict}


def evaluate(
    metrics: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    *,
    skill_eval: Mapping[str, Any] | None = None,
    gate: bool = False,
) -> dict[str, Any]:
    """Return a deterministic decision and per-metric evidence.

    A threshold is either a number (minimum candidate) or `{ "min": number }`.
    A metric is either a number (candidate) or `{ "baseline": number,
    "candidate": number }`. Every threshold metric is required.

    In gate mode a promotion also needs a valid, passing skill-evaluation
    record. A missing, invalid, warn or fail verdict yields ``pending``: the
    candidate is neither promoted nor called a regression. A failed benchmark
    threshold still yields ``rollback``, whatever the review says.
    """
    _require(isinstance(metrics, Mapping), "benchmark-missing", "metrics must be an object")
    _require(
        isinstance(thresholds, Mapping) and thresholds, "benchmark-missing", "thresholds must be a non-empty object"
    )
    rows = []
    passed = True
    for name, threshold in thresholds.items():
        _require(name in metrics, "benchmark-missing", f"metric {name!r} is missing")
        value = metrics[name]
        if isinstance(value, Mapping):
            candidate = _number(value.get("candidate"), "threshold-regression", f"{name}.candidate")
            baseline = value.get("baseline")
            baseline_value = (
                _number(baseline, "threshold-regression", f"{name}.baseline") if baseline is not None else None
            )
        else:
            candidate = _number(value, "threshold-regression", name)
            baseline_value = None
        minimum = threshold.get("min") if isinstance(threshold, Mapping) else threshold
        minimum_value = _number(minimum, "threshold-regression", f"{name}.min")
        ok = candidate >= minimum_value
        passed = passed and ok
        rows.append(
            {
                "metric": name,
                "baseline": baseline_value,
                "candidate": candidate,
                "minimum": minimum_value,
                "delta": None if baseline_value is None else candidate - baseline_value,
                "passed": ok,
            }
        )
    review = _review_row(skill_eval) if gate else None
    if not passed:
        decision = "rollback"
    elif review is not None and not review["passed"]:
        decision = "pending"
    else:
        decision = "promote"
    result: dict[str, Any] = {"decision": decision, "metrics": rows}
    if review is not None:
        result["review"] = review
    return result


def run_message(record: Mapping[str, Any]) -> bytes:
    projected = {key: value for key, value in record.items() if key != "signature_b64"}
    return json.dumps(projected, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode(
        "utf-8"
    )


def validate_run(record: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(record, Mapping), "malformed-run", "run must be an object")
    _require(record.get("schema_version") == SCHEMA, "malformed-run", "unknown run schema")
    _require(record.get("mode") in MODES, "bad-mode", "mode must be worktree or firecracker")
    _require(record.get("decision") in DECISIONS, "malformed-run", "decision is unknown")
    for field in ("run_id", "base_commit", "worktree", "benchmark_suite", "created_at"):
        _require(
            isinstance(record.get(field), str) and bool(record[field].strip()), "malformed-run", f"{field} is required"
        )
    digest = record.get("mutation_sha256")
    _require(
        isinstance(digest, str) and len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest),
        "bad-digest",
        "mutation_sha256 must be 64 lowercase hex",
    )
    for field in ("source_branch", "target_branch"):
        value = record.get(field)
        if value is not None:
            _require(
                isinstance(value, str)
                and bool(value.strip())
                and not value.startswith("/")
                and not value.endswith("/")
                and ".." not in value
                and not any(ch.isspace() for ch in value),
                "bad-branch",
                f"{field} is invalid",
            )
    _require(isinstance(record.get("metrics"), Mapping), "benchmark-missing", "metrics must be an object")
    _require(isinstance(record.get("thresholds"), Mapping), "benchmark-missing", "thresholds must be an object")
    signature = record.get("signature_b64")
    _require(signature is None or isinstance(signature, str), "bad-signature", "signature_b64 must be a string or null")
    return dict(record)


def sign_run(record: Mapping[str, Any], private_key: Any, authz: Any) -> dict[str, Any]:
    normalised = validate_run(record)
    normalised["signature_b64"] = authz.sign_bytes(private_key, run_message(normalised))
    return normalised


def verify_run(record: Mapping[str, Any], public_key: Any, authz: Any) -> bool:
    try:
        normalised = validate_run(record)
        signature = normalised.get("signature_b64")
        return bool(
            isinstance(signature, str)
            and signature
            and authz.verify_signature(public_key, signature, run_message(normalised))
        )
    except (SelfImproveError, ValueError, TypeError):
        return False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

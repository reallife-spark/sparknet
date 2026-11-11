#!/usr/bin/env python3
"""Offline, deterministic golden-diff evaluation for the review skills.

The golden set (``tests/skill-evals/<skill>-golden.json``) pins the findings a
competent reviewer must produce for small diffs, plus a clean diff that must
produce none. The offline backend applies the skills' explicit rule vocabulary
to the diff, so it is deterministic, needs no model and reads nothing outside
the checkout.

The result is a ``sparknet-skill-eval/1`` record: a skill verdict bound to the
digest of the golden set. Live scoring with a local model is a later slice and
must be operator-gated like ``REFLEX_LIVE=1``.

Usage::

    scripts/sparknet-skill-eval.py [--golden FILE] [--disable-rule RULE] [--json FILE]

Exit codes: 0 the golden set passes, 1 input error, 2 the evaluation failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
from sparknet_loader import load_shared  # noqa: E402 - shared/ is added by path above

SKILL_EVAL = load_shared("sparknet-skill-eval.py", "sparknet_skill_eval_runner")

RULES = ("tdd.missing-test", "security.shell-true", "authority.second-copy")
PRODUCTION_PREFIXES = ("shared/", "services/", "internal/")
SHELL_PATTERN = re.compile(r"shell\s*=\s*True|os\.system\(")


def parse_diff(diff: str) -> dict[str, list[str]]:
    """Return ``{path: [added lines]}`` for one unified diff."""
    files: dict[str, list[str]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            current = path[2:] if path.startswith("b/") else path
            files.setdefault(current, [])
        elif line.startswith("+") and not line.startswith("+++"):
            if current is not None:
                files[current].append(line[1:])
    return files


def is_test_path(path: str) -> bool:
    return "tests" in path.split("/") or path.endswith("_test.go") or Path(path).name.startswith("test_")


def rule_tdd_missing_test(files: dict[str, list[str]], findings: list[dict[str, Any]]) -> None:
    production = [path for path in files if path.startswith(PRODUCTION_PREFIXES)]
    if production and not any(is_test_path(path) for path in files):
        findings.append(
            {
                "severity": "block",
                "rule": "tdd.missing-test",
                "message": "a production change has no accompanying test change",
                "location": production[0],
            }
        )


def rule_security_shell_true(files: dict[str, list[str]], findings: list[dict[str, Any]]) -> None:
    for path, lines in files.items():
        if any(SHELL_PATTERN.search(line) for line in lines):
            findings.append(
                {
                    "severity": "block",
                    "rule": "security.shell-true",
                    "message": "a shell invocation can turn data into a command",
                    "location": path,
                }
            )


def rule_authority_second_copy(files: dict[str, list[str]], findings: list[dict[str, Any]]) -> None:
    for path in files:
        if path.endswith("sparknet-authz.py") and not path.startswith("shared/"):
            findings.append(
                {
                    "severity": "block",
                    "rule": "authority.second-copy",
                    "message": "the authorization implementation must stay single-copy",
                    "location": path,
                }
            )


RULE_CHECKS = {
    "tdd.missing-test": rule_tdd_missing_test,
    "security.shell-true": rule_security_shell_true,
    "authority.second-copy": rule_authority_second_copy,
}


def evaluate(golden: dict[str, Any], disabled: set[str]) -> dict[str, Any]:
    true_positive = false_positive = false_negative = 0
    cases: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for case in golden["cases"]:
        files = parse_diff(case["diff"])
        found: list[dict[str, Any]] = []
        for rule in golden["rules"]:
            if rule not in disabled:
                RULE_CHECKS[rule](files, found)
        found_rules = {finding["rule"] for finding in found}
        expected = set(case["expected"])
        missing = expected - found_rules
        unexpected = found_rules - expected
        true_positive += len(expected & found_rules)
        false_positive += len(unexpected)
        false_negative += len(missing)
        cases.append(
            {
                "id": case["id"],
                "expected": sorted(expected),
                "found": sorted(found_rules),
                "missing": sorted(missing),
                "unexpected": sorted(unexpected),
                "passed": not missing and not unexpected,
            }
        )
        if missing:
            findings.append(
                {
                    "severity": "block",
                    "rule": "golden.miss",
                    "message": f"{case['id']} did not surface {', '.join(sorted(missing))}",
                    "location": case["id"],
                }
            )
        if unexpected:
            findings.append(
                {
                    "severity": "warn",
                    "rule": "golden.unexpected",
                    "message": f"{case['id']} surfaced {', '.join(sorted(unexpected))}",
                    "location": case["id"],
                }
            )
    ok = all(case["passed"] for case in cases)
    if not ok and not any(finding["severity"] == "block" for finding in findings):
        findings.append(
            {
                "severity": "block",
                "rule": "golden.case-failed",
                "message": "one or more golden cases did not match",
            }
        )
    denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    return {
        "ok": ok,
        "cases": cases,
        "precision": round(true_positive / denominator, 4) if denominator else 1.0,
        "recall": round(true_positive / recall_denominator, 4) if recall_denominator else 1.0,
        "findings": findings,
    }


def make_record(golden: dict[str, Any], golden_path: Path, findings: list[dict[str, Any]], ok: bool) -> dict[str, Any]:
    skill = {"name": golden["skill"], "origin": "mattpocock"}
    skill_md = ROOT / ".opencode" / "skills" / golden["skill"] / "SKILL.md"
    if skill_md.is_file():
        skill["digest"] = hashlib.sha256(skill_md.read_bytes()).hexdigest()
    subject_ref = golden_path.relative_to(ROOT).as_posix() if golden_path.is_relative_to(ROOT) else str(golden_path)
    return SKILL_EVAL.make_record(
        eval_id=f"skill-eval-{golden['skill']}",
        skill=skill,
        subject={
            "kind": "skill",
            "ref": subject_ref,
            "digest": hashlib.sha256(golden_path.read_bytes()).hexdigest(),
        },
        verdict="pass" if ok else "fail",
        findings=findings,
        evaluator={"kind": "harness", "id": "sparknet-skill-eval"},
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="offline golden-diff evaluation for a review skill")
    parser.add_argument("--golden", default=str(ROOT / "tests" / "skill-evals" / "code-review-golden.json"))
    parser.add_argument("--disable-rule", action="append", default=[], help="mutation check: omit one rule")
    parser.add_argument("--json", default="", help="also write the payload to this file")
    args = parser.parse_args(argv)

    golden_path = Path(args.golden)
    try:
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot read the golden set: {exc}"}))
        return 1
    if not isinstance(golden, dict) or golden.get("schema") != "sparknet-skill-eval-golden/1":
        print(json.dumps({"ok": False, "error": "golden set has an unknown schema"}))
        return 1
    unknown = sorted(set(args.disable_rule) - set(golden.get("rules") or ()))
    if unknown:
        print(json.dumps({"ok": False, "error": f"unknown rule(s): {', '.join(unknown)}"}))
        return 1

    outcome = evaluate(golden, set(args.disable_rule))
    record = make_record(golden, golden_path, outcome["findings"], outcome["ok"])
    payload = {**outcome, "record": record}
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if outcome["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

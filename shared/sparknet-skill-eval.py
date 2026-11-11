#!/usr/bin/env python3
"""Sparknet skill-evaluation record — audit evidence, never authority.

The installed review skills (code-review, tdd, impl-validator, ...) produce a
verdict about one work product: a delegate run, a self-improve candidate, a
plan, an RFI answer or another skill. This module is the single implementation
of that record. It is loaded by path like ``sparknet-reflex.py`` and stays
stdlib only.

A record is *evidence*. It never grants a capability, never signs, never
approves an application and never enters a knowledge channel. The promotion
gate reads the verdict; the Master may audit it; no AI answers from it.

The normative shape is ``contracts/skill-eval-schema.json``. Where this module
and the schema could disagree, this module is what runs; the tests pin the
agreement.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "sparknet-skill-eval/1"
VERDICTS = ("pass", "warn", "fail")
SUBJECT_KINDS = ("delegate-run", "self-improve-candidate", "plan", "rfi-answer", "skill")
EVALUATOR_KINDS = ("agent", "harness", "human")
FINDING_SEVERITIES = ("info", "warn", "block")
ORIGINS = ("mattpocock", "wiki", "understand", "local")

#: Authority-shaped keys are refused recursively. A verdict is a sensor
#: reading; these keys are how a reading tries to become a grant.
FORBIDDEN_FIELDS = {"capability", "grant", "signature", "approve", "application", "apply", "secret", "token", "key"}

TOP_FIELDS = {"schema", "eval_id", "skill", "subject", "verdict", "findings", "evaluator", "created_at", "body_sha256"}
SKILL_FIELDS = {"name", "origin", "digest"}
SUBJECT_FIELDS = {"kind", "ref", "digest"}
EVALUATOR_FIELDS = {"kind", "id", "model"}
FINDING_FIELDS = {"severity", "rule", "message", "location"}

MAX_EVAL_ID = 120
MAX_REF = 512
MAX_FINDINGS = 100
MAX_RULE = 200
MAX_MESSAGE = 2000
MAX_LOCATION = 512

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class SkillEvalError(Exception):
    """A skill-evaluation record violated the contract."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def record_digest(record: dict[str, Any]) -> str:
    """Digest the record body; ``body_sha256`` itself is not part of the body."""
    body = {key: value for key, value in record.items() if key != "body_sha256"}
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def _require(condition: bool, message: str, code: str = "invalid") -> None:
    if not condition:
        raise SkillEvalError(message, code)


def _check_no_forbidden(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            label = f"{path}.{key}" if path else str(key)
            if key in FORBIDDEN_FIELDS:
                raise SkillEvalError(f"forbidden authority field '{label}'", "forbidden")
            _check_no_forbidden(child, label)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_no_forbidden(item, f"{path}[{index}]" if path else f"[{index}]")


def _check_unknown(value: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(value) - allowed)
    _require(not unknown, f"unknown field(s) in {where}: {', '.join(unknown)}", "unknown")


def _check_text(value: Any, name: str, limit: int) -> str:
    _require(isinstance(value, str), f"{name} must be a string")
    _require(bool(value.strip()), f"{name} must be non-empty")
    _require("\n" not in value and "\r" not in value, f"{name} must be a single line")
    _require(len(value) <= limit, f"{name} must be at most {limit} characters")
    return value


def _check_digest_field(value: Any, name: str) -> None:
    if value is None:
        return
    _require(
        isinstance(value, str) and bool(_HEX64_RE.fullmatch(value)),
        f"{name} must be a lowercase sha256 hex digest",
    )


def _validate_skill(skill: Any) -> None:
    _require(isinstance(skill, dict), "skill must be an object")
    _check_unknown(skill, SKILL_FIELDS, "skill")
    _check_text(skill.get("name"), "skill.name", MAX_EVAL_ID)
    _require(skill.get("origin") in ORIGINS, f"skill.origin must be one of {list(ORIGINS)}")
    _check_digest_field(skill.get("digest"), "skill.digest")


def _validate_subject(subject: Any) -> None:
    _require(isinstance(subject, dict), "subject must be an object")
    _check_unknown(subject, SUBJECT_FIELDS, "subject")
    _require(subject.get("kind") in SUBJECT_KINDS, f"subject.kind must be one of {list(SUBJECT_KINDS)}")
    _check_text(subject.get("ref"), "subject.ref", MAX_REF)
    _check_digest_field(subject.get("digest"), "subject.digest")


def _validate_evaluator(evaluator: Any) -> None:
    _require(isinstance(evaluator, dict), "evaluator must be an object")
    _check_unknown(evaluator, EVALUATOR_FIELDS, "evaluator")
    _require(evaluator.get("kind") in EVALUATOR_KINDS, f"evaluator.kind must be one of {list(EVALUATOR_KINDS)}")
    _check_text(evaluator.get("id"), "evaluator.id", MAX_EVAL_ID)
    if evaluator.get("model") is not None:
        _check_text(evaluator["model"], "evaluator.model", MAX_EVAL_ID)


def _validate_findings(findings: Any) -> list[dict[str, Any]]:
    _require(isinstance(findings, list), "findings must be an array", "findings")
    _require(len(findings) <= MAX_FINDINGS, f"findings must hold at most {MAX_FINDINGS} entries", "findings")
    checked: list[dict[str, Any]] = []
    for index, finding in enumerate(findings):
        where = f"findings[{index}]"
        _require(isinstance(finding, dict), f"{where} must be an object", "findings")
        _check_unknown(finding, FINDING_FIELDS, where)
        _require(
            finding.get("severity") in FINDING_SEVERITIES,
            f"{where}.severity must be one of {list(FINDING_SEVERITIES)}",
            "findings",
        )
        _check_text(finding.get("rule"), f"{where}.rule", MAX_RULE)
        _check_text(finding.get("message"), f"{where}.message", MAX_MESSAGE)
        if finding.get("location") is not None:
            _check_text(finding["location"], f"{where}.location", MAX_LOCATION)
        checked.append(finding)
    return checked


def _check_verdict_matches_findings(verdict: str, findings: list[dict[str, Any]]) -> None:
    severities = {finding["severity"] for finding in findings}
    if verdict == "pass":
        _require(not severities & {"warn", "block"}, "verdict 'pass' cannot carry warn or block findings", "verdict")
    elif verdict == "warn":
        _require(bool(findings), "verdict 'warn' needs at least one finding", "findings")
        _require("block" not in severities, "verdict 'warn' cannot carry a block finding", "verdict")
    elif verdict == "fail":
        _require("block" in severities, "verdict 'fail' needs a block finding", "findings")


def validate_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate one record and its digest. Returns the record unchanged."""
    _require(isinstance(record, dict), "record must be an object")
    _check_no_forbidden(record)
    _check_unknown(record, TOP_FIELDS, "record")
    _require(record.get("schema") == SCHEMA, f"schema must be {SCHEMA}")
    _check_text(record.get("eval_id"), "eval_id", MAX_EVAL_ID)
    _validate_skill(record.get("skill"))
    _validate_subject(record.get("subject"))
    _require(record.get("verdict") in VERDICTS, f"verdict must be one of {list(VERDICTS)}")
    findings = _validate_findings(record.get("findings"))
    _validate_evaluator(record.get("evaluator"))

    declared = record.get("body_sha256")
    _require(isinstance(declared, str) and bool(_HEX64_RE.fullmatch(declared)), "body_sha256 must be a sha256 digest")
    _require(declared == record_digest(record), "body_sha256 does not match the record digest", "digest")

    _check_verdict_matches_findings(record["verdict"], findings)
    _require(
        isinstance(record.get("created_at"), str) and bool(_TIMESTAMP_RE.fullmatch(record["created_at"])),
        "created_at must be an ISO-8601 UTC timestamp",
        "created_at",
    )
    return record


def make_record(
    *,
    eval_id: str,
    skill: dict[str, Any],
    subject: dict[str, Any],
    verdict: str,
    findings: list[dict[str, Any]],
    evaluator: dict[str, Any],
    created_at: str,
    **extra: Any,
) -> dict[str, Any]:
    """Build and validate one record, computing its digest.

    ``extra`` exists so a caller that tries to smuggle an authority-shaped or
    unknown key reaches the contract's typed refusal instead of a Python
    ``TypeError``. The record stays closed: validation rejects the key.
    """
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "eval_id": eval_id,
        "skill": skill,
        "subject": subject,
        "verdict": verdict,
        "findings": findings,
        "evaluator": evaluator,
        "created_at": created_at,
        **extra,
    }
    record["body_sha256"] = record_digest(record)
    return validate_record(record)


def is_passing(record: dict[str, Any]) -> bool:
    """True only for a valid, passing record. Invalid records raise."""
    return validate_record(record)["verdict"] == "pass"

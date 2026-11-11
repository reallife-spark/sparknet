"""The skill-evaluation record: one shape, digest-bound, never authority.

A skill verdict is audit evidence attached to a work product (a delegate run, a
self-improve candidate, a plan, an RFI answer or another skill). It is produced
by the installed review skills and consumed by the promotion gate. It never
grants a capability, never signs, and never becomes knowledge.

This file is written before ``shared/sparknet-skill-eval.py`` exists: the RED
step is the module and contract being absent, not a vague behavioural gap.
"""

from __future__ import annotations

import json
from types import ModuleType

import pytest
from contract_helpers import REPO_ROOT, load
from sparknet_loader import load_by_path

SKILL_EVAL_PATH = REPO_ROOT / "shared" / "sparknet-skill-eval.py"
GOLDEN = REPO_ROOT / "tests" / "skill-evals" / "record-golden.json"


@pytest.fixture(scope="module")
def skill_eval() -> ModuleType:
    return load_by_path("sparknet_skill_eval", SKILL_EVAL_PATH)


@pytest.fixture(scope="module")
def schema() -> dict:
    return load("skill-eval-schema.json")


def _record(skill_eval: ModuleType, **overrides: object) -> dict:
    fields: dict[str, object] = {
        "eval_id": "review-run-1",
        "skill": {"name": "code-review", "origin": "mattpocock"},
        "subject": {"kind": "delegate-run", "ref": "run/2026-11-11-001"},
        "verdict": "pass",
        "findings": [],
        "evaluator": {"kind": "agent", "id": "project-reviewer"},
        "created_at": "2026-11-11T00:00:00Z",
    }
    fields.update(overrides)
    return skill_eval.make_record(**fields)


def test_contract_and_implementation_agree(skill_eval: ModuleType, schema: dict) -> None:
    assert schema["contract"] == "skill-eval"
    assert schema["schema_version"] == "1.0"
    assert schema["canonical_source"]["implementation"] == "shared/sparknet-skill-eval.py"
    assert skill_eval.SCHEMA == "sparknet-skill-eval/1"
    assert tuple(schema["verdicts"]) == skill_eval.VERDICTS
    assert tuple(schema["subject_kinds"]) == skill_eval.SUBJECT_KINDS


def test_a_valid_record_round_trips_and_is_digest_bound(skill_eval: ModuleType) -> None:
    record = _record(skill_eval)
    assert record["schema"] == "sparknet-skill-eval/1"
    assert record["body_sha256"] == skill_eval.record_digest(record)
    assert skill_eval.validate_record(record) == record


def test_the_digest_is_canonical_across_key_order(skill_eval: ModuleType) -> None:
    record = _record(skill_eval)
    reordered = dict(reversed(list(record.items())))
    assert reordered["body_sha256"] == record["body_sha256"]


def test_a_tampered_record_is_refused(skill_eval: ModuleType) -> None:
    record = _record(skill_eval)
    record["verdict"] = "warn"
    with pytest.raises(skill_eval.SkillEvalError, match="digest"):
        skill_eval.validate_record(record)


def test_unknown_verdict_is_refused(skill_eval: ModuleType) -> None:
    with pytest.raises(skill_eval.SkillEvalError, match="verdict"):
        _record(skill_eval, verdict="maybe")


def test_unknown_subject_kind_is_refused(skill_eval: ModuleType) -> None:
    with pytest.raises(skill_eval.SkillEvalError, match="subject"):
        _record(skill_eval, subject={"kind": "vibes", "ref": "x"})


def test_a_blank_subject_ref_is_refused(skill_eval: ModuleType) -> None:
    with pytest.raises(skill_eval.SkillEvalError, match="subject"):
        _record(skill_eval, subject={"kind": "plan", "ref": "  "})


def test_a_block_finding_cannot_pass(skill_eval: ModuleType) -> None:
    with pytest.raises(skill_eval.SkillEvalError, match="verdict"):
        _record(
            skill_eval,
            verdict="pass",
            findings=[{"severity": "block", "rule": "tdd.red-first", "message": "no failing test"}],
        )


def test_a_warn_needs_at_least_one_finding(skill_eval: ModuleType) -> None:
    with pytest.raises(skill_eval.SkillEvalError, match="finding"):
        _record(skill_eval, verdict="warn")


def test_findings_are_bounded(skill_eval: ModuleType) -> None:
    finding = {"severity": "warn", "rule": "x", "message": "y"}
    with pytest.raises(skill_eval.SkillEvalError, match="findings"):
        _record(skill_eval, verdict="fail", findings=[finding] * 101)


def test_authority_shaped_fields_are_refused(skill_eval: ModuleType) -> None:
    with pytest.raises(skill_eval.SkillEvalError, match="forbidden"):
        _record(skill_eval, grant={"scope": "vault"})


def test_unknown_fields_are_refused(skill_eval: ModuleType) -> None:
    with pytest.raises(skill_eval.SkillEvalError, match="unknown"):
        _record(skill_eval, approved=True)


def test_invalid_timestamp_is_refused(skill_eval: ModuleType) -> None:
    with pytest.raises(skill_eval.SkillEvalError, match="created_at"):
        _record(skill_eval, created_at="yesterday")


def test_passing_means_pass_and_nothing_else(skill_eval: ModuleType) -> None:
    assert skill_eval.is_passing(_record(skill_eval)) is True
    warn = _record(
        skill_eval,
        verdict="warn",
        findings=[{"severity": "warn", "rule": "naming", "message": "unclear name"}],
    )
    assert skill_eval.is_passing(warn) is False
    failing = _record(
        skill_eval,
        verdict="fail",
        findings=[{"severity": "block", "rule": "review", "message": "defect"}],
    )
    assert skill_eval.is_passing(failing) is False


def test_the_golden_record_is_valid(skill_eval: ModuleType) -> None:
    golden = json.loads(GOLDEN.read_text())
    assert skill_eval.validate_record(golden) == golden
    assert skill_eval.is_passing(golden) is True

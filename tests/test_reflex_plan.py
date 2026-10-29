"""Plan selection: the proposer/verifier pattern, advisory only.

The LLM proposes plans; ``shared/sparknet-verify.py`` builds one
``plan.select`` choice question, validates the typed answer, and applies a
versioned threshold policy. These tests use a fake backend: they pin the
ranking, the abstain rules, the envelope limits and the CLI contract, not a
model's judgment.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from contract_helpers import REPO_ROOT

REFLEX_PATH = REPO_ROOT / "shared" / "sparknet-reflex.py"
VERIFY_PATH = REPO_ROOT / "shared" / "sparknet-verify.py"
CLI_PATH = REPO_ROOT / "scripts" / "sparknet-verify-plans.py"
EVAL_PATH = REPO_ROOT / "scripts" / "sparknet-reflex-plan-eval.py"
GOLDEN_PATH = REPO_ROOT / "tests" / "reflex" / "plans-golden.json"

PLANS = [
    {"id": "local", "title": "Local", "body": "Run on the node with no network."},
    {"id": "cloud", "title": "Cloud", "body": "Send the data to a hosted API."},
    {"id": "hybrid", "title": "Hybrid", "body": "Draft locally and ask a cloud service."},
]
QUERY = "Choose the deployment approach for a node with no egress."
RUBRIC = "The plan must be local-only and require no cloud credential."


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def reflex() -> ModuleType:
    return _load("test_plan_reflex", REFLEX_PATH)


@pytest.fixture(scope="module")
def verify() -> ModuleType:
    return _load("test_plan_verify", VERIFY_PATH)


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return _load("test_plan_cli", CLI_PATH)


@pytest.fixture(scope="module")
def eval_mod() -> ModuleType:
    return _load("test_plan_eval", EVAL_PATH)


def _factory(answer: dict) -> object:
    def factory(model: str | None = None, timeout_s: float = 10.0):
        return lambda _request: answer

    return factory


def _answer(choice: str, probabilities: dict[str, float], confidence: float = 0.9) -> dict:
    return {
        "type": "choice",
        "choice": choice,
        "probabilities": probabilities,
        "confidence": confidence,
    }


def _run(verify: ModuleType, reflex: ModuleType, monkeypatch, answer: dict, **kwargs):
    monkeypatch.setattr(reflex, "local_llm_backend", _factory(answer))
    return verify.verify_plans(QUERY, RUBRIC, PLANS, reflex=reflex, **kwargs)


def test_a_clear_choice_is_recommended_and_ranked(verify: ModuleType, reflex: ModuleType, monkeypatch) -> None:
    answer = _answer("cloud", {"local": 0.05, "cloud": 0.8, "hybrid": 0.1, "none": 0.05})
    result = _run(verify, reflex, monkeypatch, answer)

    assert result["verdict"] == "accept"
    assert result["recommendation"] == "cloud"
    assert [row["id"] for row in result["ranking"]] == ["cloud", "hybrid", "local"]
    assert result["none_probability"] == pytest.approx(0.05)
    assert result["answer"]["choice"] == "cloud"
    assert result["advisory"] is True
    assert result["backend"] == "local-llm"
    assert result["decision"]["answer"]["choice"] == "cloud"


def test_a_zero_reported_confidence_does_not_veto_a_sharp_distribution(
    verify: ModuleType, reflex: ModuleType, monkeypatch
) -> None:
    answer = _answer("local", {"local": 0.9, "cloud": 0.05, "hybrid": 0.05, "none": 0.0}, confidence=0.0)
    result = _run(verify, reflex, monkeypatch, answer)
    assert result["verdict"] == "accept"
    assert result["recommendation"] == "local"
    assert result["decision"]["confidence"] == pytest.approx(0.9)


def test_none_is_an_abstain_not_a_plan(verify: ModuleType, reflex: ModuleType, monkeypatch) -> None:
    answer = _answer("none", {"local": 0.05, "cloud": 0.05, "hybrid": 0.1, "none": 0.8})
    result = _run(verify, reflex, monkeypatch, answer)

    assert result["verdict"] == "abstain"
    assert result["reason"] == "no-plan"
    assert result["recommendation"] is None
    assert [row["id"] for row in result["ranking"]] == ["hybrid", "cloud", "local"]
    assert result["none_probability"] == pytest.approx(0.8)


def test_a_thin_distribution_abstains_but_keeps_an_advisory_ranking(
    verify: ModuleType, reflex: ModuleType, monkeypatch
) -> None:
    answer = _answer("local", {"local": 0.4, "cloud": 0.35, "hybrid": 0.2, "none": 0.05}, confidence=0.9)
    result = _run(verify, reflex, monkeypatch, answer)

    assert result["verdict"] == "abstain"
    assert result["reason"] == "low-signal"
    assert result["recommendation"] is None
    assert result["ranking"][0]["id"] == "local"
    assert "answer" not in result["decision"], "the contract carries no answer on an abstain"


def test_a_probability_set_that_omits_a_plan_is_refused(verify: ModuleType, reflex: ModuleType, monkeypatch) -> None:
    answer = _answer("local", {"local": 0.7, "cloud": 0.2})
    result = _run(verify, reflex, monkeypatch, answer)

    assert result["verdict"] == "abstain"
    assert result["reason"] == "invalid-choice"
    assert result["ranking"] == []


def test_a_backend_error_abstains_without_a_ranking(verify: ModuleType, reflex: ModuleType, monkeypatch) -> None:
    def boom(model: str | None = None, timeout_s: float = 10.0):
        def call(_request):
            raise RuntimeError("local model down")

        return call

    monkeypatch.setattr(reflex, "local_llm_backend", boom)
    result = verify.verify_plans(QUERY, RUBRIC, PLANS, reflex=reflex)

    assert result["verdict"] == "abstain"
    assert result["reason"] == "backend-error"
    assert result["recommendation"] is None
    assert result["ranking"] == []


def test_a_sparse_but_complete_distribution_infers_zeroes(verify: ModuleType, reflex: ModuleType, monkeypatch) -> None:
    answer = _answer("local", {"local": 1.0})
    result = _run(verify, reflex, monkeypatch, answer)
    assert result["verdict"] == "accept"
    assert result["recommendation"] == "local"
    assert [row["id"] for row in result["ranking"]] == ["local", "cloud", "hybrid"]
    assert result["ranking"][1]["probability"] == 0.0


def test_the_envelope_limits_are_enforced(verify: ModuleType, reflex: ModuleType) -> None:
    with pytest.raises(verify.PlanEnvelopeError, match="2-8"):
        verify.verify_plans(QUERY, RUBRIC, PLANS[:1], reflex=reflex)
    with pytest.raises(verify.PlanEnvelopeError, match="2-8"):
        verify.verify_plans(QUERY, RUBRIC, PLANS * 3, reflex=reflex)

    duplicate = [dict(PLANS[0]), dict(PLANS[0])]
    with pytest.raises(verify.PlanEnvelopeError, match="duplicate"):
        verify.verify_plans(QUERY, RUBRIC, duplicate, reflex=reflex)

    too_big = [dict(PLANS[0], body="x" * (verify.MAX_PLAN_CHARS + 1)), dict(PLANS[1])]
    with pytest.raises(verify.PlanEnvelopeError, match="exceeds"):
        verify.verify_plans(QUERY, RUBRIC, too_big, reflex=reflex)


def test_the_request_is_plan_select_and_one_question(verify: ModuleType, reflex: ModuleType, monkeypatch) -> None:
    captured: dict = {}

    def factory(model: str | None = None, timeout_s: float = 10.0):
        def call(request):
            captured.update(request)
            return _answer("local", {"local": 0.8, "cloud": 0.1, "hybrid": 0.05, "none": 0.05})

        return call

    monkeypatch.setattr(reflex, "local_llm_backend", factory)
    verify.verify_plans(QUERY, RUBRIC, PLANS, reflex=reflex)

    assert captured["question_class"] == "plan.select"
    assert list(captured["questions"]) == ["choose"]
    assert captured["questions"]["choose"]["criteria"]["options"] == ["local", "cloud", "hybrid"]
    assert "none" not in captured["questions"]["choose"]["instructions"]


def test_the_policy_can_abstain_on_a_clear_answer(verify: ModuleType, reflex: ModuleType, monkeypatch) -> None:
    answer = _answer("cloud", {"local": 0.1, "cloud": 0.7, "hybrid": 0.15, "none": 0.05})
    result = _run(verify, reflex, monkeypatch, answer, policy={"min_top": 0.8})
    assert result["verdict"] == "abstain"
    assert result["reason"] == "low-confidence"


def test_a_forbidden_plan_is_refused_after_ranking(verify: ModuleType, reflex: ModuleType, monkeypatch) -> None:
    plans = [
        {"id": "k8s", "title": "Kubernetes", "body": "Install a managed Kubernetes cluster."},
        {"id": "local", "title": "Local", "body": "Keep the systemd units and run locally."},
    ]
    answer = _answer("k8s", {"k8s": 0.8, "local": 0.2})
    monkeypatch.setattr(reflex, "local_llm_backend", _factory(answer))
    result = verify.verify_plans(QUERY, RUBRIC, plans, reflex=reflex, forbid=["kubernetes"])

    assert result["verdict"] == "abstain"
    assert result["reason"] == "constraint-violation"
    assert result["recommendation"] is None
    assert result["constraint_violations"] == ["kubernetes"]
    assert result["ranking"][0]["id"] == "k8s", "the advisory ranking is still shown"


def test_the_cli_prints_the_result_and_rejects_malformed_input(cli: ModuleType, capsys) -> None:
    payload = {"query": QUERY, "rubric": RUBRIC, "plans": PLANS}

    def fake_verify(query, rubric, plans, **kwargs):
        return {"verdict": "accept", "recommendation": "local", "ranking": [{"id": "local", "probability": 0.9}]}

    assert cli.main(["--input", "-", "--compact"], verify_fn=fake_verify, input_loader=lambda _p: payload) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["recommendation"] == "local"

    assert cli.main(["--input", "-"], verify_fn=fake_verify, input_loader=lambda _p: []) == 2
    assert "error" in capsys.readouterr().err


def test_ece_is_measured_over_accepted_recommendations(eval_mod: ModuleType) -> None:
    rows = [
        {"verdict": "accept", "top_probability": 0.8, "correct": True},
        {"verdict": "accept", "top_probability": 0.6, "correct": False},
        {"verdict": "abstain", "top_probability": 0.4, "correct": False},
    ]
    assert eval_mod.ece(rows) == pytest.approx(0.4)


def test_evaluate_reports_agreement_coverage_and_false_accepts(eval_mod: ModuleType) -> None:
    golden = {
        "name": "test",
        "version": "1",
        "cases": [
            {"id": "a", "query": "a", "rubric": "r", "plans": PLANS, "expected": "local"},
            {"id": "b", "query": "b", "rubric": "r", "plans": PLANS, "expected": "local"},
        ],
    }

    def fake_verify(query, rubric, plans, **kwargs):
        if query == "a":
            return {
                "verdict": "accept",
                "recommendation": "local",
                "ranking": [{"id": "local", "probability": 0.8}],
                "none_probability": 0.05,
                "latency_ms": 10.0,
                "backend": "local-llm",
                "model": "local",
                "policy_version": "plan-select-v1",
            }
        return {
            "verdict": "abstain",
            "reason": "low-signal",
            "recommendation": None,
            "ranking": [{"id": "local", "probability": 0.4}],
            "none_probability": 0.05,
            "latency_ms": 20.0,
            "backend": "local-llm",
            "model": "local",
            "policy_version": "plan-select-v1",
        }

    report = eval_mod.evaluate(
        golden, verify_fn=fake_verify, model="local", timeout=1.0, policy_version="plan-select-v1"
    )
    summary = report["summary"]
    assert summary["cases"] == 2
    assert summary["top1_agreement"] == pytest.approx(0.5)
    assert summary["coverage"] == pytest.approx(0.5)
    assert summary["abstain_rate"] == pytest.approx(0.5)
    assert summary["false_accepts"] == 0
    assert summary["ece"] == pytest.approx(0.2)


def test_the_committed_golden_set_is_valid(eval_mod: ModuleType, verify: ModuleType) -> None:
    golden = eval_mod.load_golden(GOLDEN_PATH, verify)
    assert len(golden["cases"]) >= 12
    assert any(case["expected"] == "none" for case in golden["cases"])

"""Reflex decision contract: shapes, abstain rules, and no-authority invariants.

The reflex layer is a sensor. These tests pin the parts a caller is allowed to
rely on — a closed question vocabulary, abstain as a first-class outcome, an
audit line that carries no state — and the parts that keep it from becoming an
authority: forbidden authority fields, tighten-only helpers, and the guard /
signer / registry exclusion list.

Runs in the fabric suite (``tests/``); the implementation lives at
``shared/sparknet-reflex.py`` and the contract at
``contracts/reflex-schema.json``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from types import ModuleType

import pytest
from contract_helpers import REPO_ROOT, load

REFLEX_PATH = REPO_ROOT / "shared" / "sparknet-reflex.py"
GOLDEN = REPO_ROOT / "tests" / "reflex" / "golden" / "vectors.json"


@pytest.fixture(scope="module")
def reflex() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sparknet_reflex", REFLEX_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def schema() -> dict:
    return load("reflex-schema.json")


@pytest.fixture(scope="module")
def vectors() -> dict:
    return json.loads(GOLDEN.read_text())


def _request(reflex: ModuleType) -> dict:
    return reflex.make_request(
        "rag.relevance",
        "alpha",
        {"q": {"type": "noul", "instructions": "relevant?"}},
        "local",
        "policy-1",
        "node-a",
        "req-1",
    )


def test_contract_json_is_valid_and_versioned(schema: dict) -> None:
    assert schema["schema_version"] == "1.0"
    assert schema["contract"] == "reflex"
    assert schema["canonical_source"]["implementation"] == "shared/sparknet-reflex.py"


def test_module_constants_match_the_contract(reflex: ModuleType, schema: dict) -> None:
    """The vocabulary the code enforces must be the one the contract declares."""
    assert set(reflex.QUESTION_CLASSES) == set(schema["request"]["fields"]["question_class"]["enum"])
    assert set(reflex.QUESTION_TYPES) == set(schema["answer_types"])
    assert {f"{t}_question" for t in reflex.QUESTION_TYPES} <= set(schema["definitions"])
    assert set(reflex.VERDICTS) == set(schema["decision"]["fields"]["verdict"]["enum"])
    assert set(reflex.BACKENDS) == set(schema["decision"]["fields"]["backend"]["enum"])
    assert set(reflex.MODES) == set(schema["modes"]["values"])
    assert schema["schema_version"] == reflex.SCHEMA_VERSION


def test_default_modes_match_the_contract(reflex: ModuleType, schema: dict) -> None:
    assert reflex.default_modes() == schema["modes"]["per_class_defaults"]
    assert reflex.default_modes()["rag.relevance"] == {"mode": "local", "rollout": "shadow"}


def test_valid_request_roundtrips(reflex: ModuleType) -> None:
    req = _request(reflex)
    assert reflex.validate_request(req) == req


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda r: r.pop("model"), "missing required field: model"),
        (lambda r: r.__setitem__("question_class", "rag.magic"), "unknown question_class"),
        (lambda r: r.__setitem__("schema_version", "2.0"), "schema_version must be 1.0"),
        (lambda r: r.__setitem__("model", ""), "model must be non-empty"),
        (lambda r: r["questions"].clear(), "questions must be a non-empty object"),
        (lambda r: r["questions"].__setitem__("q", {"type": "magic", "instructions": "x"}), "unknown type"),
        (lambda r: r["questions"].__setitem__("q", {"type": "noul"}), "missing instructions"),
        (
            lambda r: r["questions"].__setitem__("q", {"type": "score", "instructions": "x", "criteria": ["a"]}),
            "2-10 levels",
        ),
    ],
)
def test_request_violations_are_refused(reflex: ModuleType, mutate, needle: str) -> None:
    req = _request(reflex)
    mutate(req)
    with pytest.raises(reflex.ReflexPolicyError, match=needle):
        reflex.validate_request(req)


@pytest.mark.parametrize("field", ["capability", "grant", "signature", "approve", "apply", "secret", "token", "key"])
def test_authority_fields_are_forbidden(reflex: ModuleType, field: str) -> None:
    req = _request(reflex)
    req[field] = "anything"
    with pytest.raises(reflex.ReflexPolicyError, match=f"forbidden field '{field}'"):
        reflex.validate_request(req)


def test_nested_authority_fields_are_forbidden_too(reflex: ModuleType) -> None:
    req = _request(reflex)
    req["questions"]["q"]["criteria"] = {"token": "x"}
    with pytest.raises(reflex.ReflexPolicyError, match="forbidden field 'token'"):
        reflex.validate_request(req)


def test_noul_abstains_on_doubt(reflex: ModuleType) -> None:
    assert reflex.noul_abstain(0.5) is True
    assert reflex.noul_abstain(0.55) is True
    assert reflex.noul_abstain(0.9) is False
    assert reflex.noul_abstain(0.1) is False


def test_choice_abstains_on_low_confidence_or_thin_margin(reflex: ModuleType) -> None:
    assert reflex.choice_abstain(0.9, 0.9, 0.1) is False
    assert reflex.choice_abstain(0.5, 0.9, 0.1) is True
    assert reflex.choice_abstain(0.9, 0.51, 0.49) is True
    assert reflex.choice_abstain(None, 0.9, 0.1) is True


def test_score_abstains_on_low_confidence(reflex: ModuleType) -> None:
    assert reflex.score_abstain(0.9) is False
    assert reflex.score_abstain(0.2) is True
    assert reflex.score_abstain(None) is True


def test_abstain_decision_is_first_class(reflex: ModuleType) -> None:
    req = _request(reflex)
    decision = reflex.abstain_decision("local", "broker", "policy-1", req)
    assert decision["verdict"] == "abstain"
    assert decision["confidence"] is None
    assert decision["backend"] == "broker"
    assert decision["state_digest"] == reflex._digest(req["state"])


def test_cache_key_changes_with_model_policy_and_state(reflex: ModuleType) -> None:
    req = _request(reflex)
    base = reflex.cache_key(req)

    req2 = _request(reflex)
    req2["model"] = "mistral-7b"
    assert reflex.cache_key(req2) != base

    req3 = _request(reflex)
    req3["policy_version"] = "policy-2"
    assert reflex.cache_key(req3) != base

    req4 = _request(reflex)
    req4["state"] = "beta"
    assert reflex.cache_key(req4) != base

    req5 = _request(reflex)
    req5["request_id"] = "req-2"
    assert reflex.cache_key(req5) == base, "cache must not be keyed on request correlation"


def test_audit_line_carries_no_state_or_questions(reflex: ModuleType) -> None:
    req = _request(reflex)
    decision = reflex.abstain_decision("local", "broker", "policy-1", req)
    line = json.loads(reflex.audit_line(decision, req, "rag.relevance", 12.5))
    assert line["class"] == "rag.relevance"
    assert line["verdict"] == "abstain"
    assert line["request_digest"]
    text = json.dumps(line)
    assert "alpha" not in text
    assert "relevant?" not in text
    assert "api_key" not in text


def test_authority_paths_are_excluded(reflex: ModuleType) -> None:
    for path in (
        "peer-node/services/sparknet-guard-d.py",
        "master-node/services/sparknet-signer.py",
        "shared/sparknet-authz.py",
        "manifests/node-authorizations.json",
        "services/sparknet-registry-client.py",
    ):
        assert reflex.is_authority_path(path) is True, path
    assert reflex.is_authority_path("peer-node/services/sparknet-dispatch-bridge.py") is False


def test_golden_vectors(reflex: ModuleType, vectors: dict) -> None:
    """Pin canonical bytes so a refactor cannot silently change the cache identity."""
    for case in vectors["cache_keys"]:
        req = reflex.make_request(
            case["question_class"],
            case["state"],
            case["questions"],
            case["model"],
            case["policy_version"],
            case["node_id"],
            case["request_id"],
        )
        assert reflex.cache_key(req) == case["expected"], case["name"]

    for case in vectors["noul"]:
        assert reflex.noul_abstain(case["p"]) is case["abstain"], case["p"]

    for case in vectors["choice"]:
        assert reflex.choice_abstain(case["confidence"], case["top_p"], case["second_p"]) is case["abstain"], case


def test_redaction_removes_pem_bearer_and_secrets(reflex: ModuleType) -> None:
    # The PEM markers are assembled at runtime, never written as one literal
    # here: this file is itself scanned by `make keys-check`, and a tracked file
    # containing the block the checker exists to detect is precisely what it
    # reports. tests/test_keys.py does the same, for the same reason.
    text = (
        "-----BEGIN " + "PRIVATE KEY-----\nMIIE...\n-----END " + "PRIVATE KEY-----\n"
        "Authorization: Bearer abc.def.ghi\napi_key=supersecret\ntoken: 12345"
    )
    out = reflex.redact(text)
    assert "MIIE" not in out
    assert "abc.def.ghi" not in out
    assert "supersecret" not in out
    assert "12345" not in out
    assert out.count("[REDACTED") >= 3


def test_redact_deep_replaces_secret_named_keys(reflex: ModuleType) -> None:
    out = reflex.redact_deep({"api_key": "x", "nested": {"password": "p", "ok": "visible"}})
    assert out["api_key"] == "[REDACTED]"
    assert out["nested"]["password"] == "[REDACTED]"
    assert out["nested"]["ok"] == "visible"


def test_redact_request_does_not_mutate_the_original(reflex: ModuleType) -> None:
    req = _request(reflex)
    req["state"] = {"text": "api_key=secret", "api_key": "secret"}
    out = reflex.redact_request(req)
    assert "secret" not in json.dumps(out)
    assert req["state"]["api_key"] == "secret", "redaction must be a copy"
    assert "secret" in json.dumps(req)


def test_noul_answer_maps_to_verdict(reflex: ModuleType) -> None:
    req = _request(reflex)
    accept = reflex.decision_from_answer({"type": "noul", "noul": 0.9}, req)
    reject = reflex.decision_from_answer({"type": "noul", "noul": 0.1}, req)
    abstain = reflex.decision_from_answer({"type": "noul", "noul": 0.5}, req)
    assert accept["verdict"] == "accept"
    assert reject["verdict"] == "reject"
    assert abstain["verdict"] == "abstain"


def test_choice_answer_uses_confidence_and_margin(reflex: ModuleType) -> None:
    req = _request(reflex)
    good = {"type": "choice", "choice": "yes", "probabilities": {"yes": 0.9, "no": 0.1}, "confidence": 0.9}
    thin = {"type": "choice", "choice": "yes", "probabilities": {"yes": 0.51, "no": 0.49}, "confidence": 0.9}
    assert reflex.decision_from_answer(good, req)["verdict"] == "accept"
    assert reflex.decision_from_answer(thin, req)["verdict"] == "abstain"


def test_malformed_and_unknown_answers_abstain(reflex: ModuleType) -> None:
    req = _request(reflex)
    for bad in (None, {}, {"type": "noul"}, {"type": "magic"}, {"type": "score"}):
        assert reflex.decision_from_answer(bad, req)["verdict"] == "abstain", bad


def test_consult_timeout_abstains_without_waiting_for_the_backend(reflex: ModuleType) -> None:
    req = _request(reflex)

    def slow(_req):
        import time as _t

        _t.sleep(0.5)
        return {"type": "noul", "noul": 0.9}

    import time as _t

    start = _t.monotonic()
    decision = reflex.consult(slow, req, timeout_s=0.05)
    elapsed = _t.monotonic() - start
    assert decision["verdict"] == "abstain"
    assert decision["_reason"] == "timeout"
    assert elapsed < 0.4


def test_consult_backend_error_abstains(reflex: ModuleType) -> None:
    req = _request(reflex)

    def boom(_req):
        raise RuntimeError("backend down")

    assert reflex.consult(boom, req, timeout_s=1.0)["_reason"] == "backend-error"


def test_consult_rejects_multiple_answers(reflex: ModuleType) -> None:
    req = _request(reflex)
    answer = {"answers": {"a": {"type": "noul", "noul": 0.9}, "b": {"type": "noul", "noul": 0.9}}}
    assert reflex.consult(lambda _r: answer, req)["_reason"] == "answer-count"


def test_consult_success_charges_the_budget(reflex: ModuleType) -> None:
    req = _request(reflex)
    budget = reflex.Budget(per_node_limit=1, global_limit=10)
    decision = reflex.consult(lambda _r: {"type": "noul", "noul": 0.9}, req, budget=budget)
    assert decision["verdict"] == "accept"
    assert budget.per_node_used == 1
    assert reflex.consult(lambda _r: {"type": "noul", "noul": 0.9}, req, budget=budget)["_reason"] == "budget-exhausted"


def test_consult_handles_a_backend_envelope(reflex: ModuleType) -> None:
    req = _request(reflex)
    envelope = {
        "model": "local",
        "answers": {"q": {"type": "noul", "noul": 0.9}},
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }
    decision = reflex.consult(lambda _r: envelope, req)
    assert decision["verdict"] == "accept"
    assert decision["usage"]["input_tokens"] == 10
    assert decision["latency_ms"] >= 0.0


def test_backend_selection_defaults_to_local(reflex: ModuleType, monkeypatch) -> None:
    monkeypatch.delenv("SPARKNET_REFLEX_BACKEND", raising=False)
    assert reflex.backend_from_env("rag.relevance") == "local-rerank"
    assert reflex.backend_from_env("routing") == "local-llm"
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "broker")
    assert reflex.backend_from_env("rag.relevance") == "broker"
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "jev")
    assert reflex.backend_from_env("rag.relevance") == "local-rerank", (
        "a retired cloud spelling must fall back to local; an operator's stale env var cannot select a backend "
        "that leaves the node"
    )
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "off")
    assert reflex.backend_from_env("rag.relevance") == "null"
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "rules")
    assert reflex.backend_from_env("routing") == "rules"


def test_backend_selection_rejects_unknown_values(reflex: ModuleType, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "cloud-saas")
    assert reflex.backend_from_env("rag.relevance") == "local-rerank"


def test_local_llm_backend_parses_openai_style_content(reflex: ModuleType, monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {"message": {"content": '{"type":"noul","noul":0.82}'}},
                    ]
                }
            ).encode()

    seen: dict = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode())
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(reflex, "_open_url", fake_urlopen)
    monkeypatch.setenv("SPARKNET_REFLEX_LOCAL_URL", "http://127.0.0.1:11434")
    backend = reflex.local_llm_backend(model="qwen2.5:3b", timeout_s=1.5)
    answer = backend(_request(reflex))
    assert answer["type"] == "noul"
    assert answer["noul"] == pytest.approx(0.82)
    assert seen["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert seen["body"]["model"] == "qwen2.5:3b"
    assert seen["timeout"] == 1.5


def test_local_llm_backend_reads_ollama_and_plain_content(reflex: ModuleType, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_LOCAL_MODEL", "qwen2.5-3b-32k")

    def fake(outer):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def read(self):
                return json.dumps(outer).encode()

        monkeypatch.setattr(reflex, "_open_url", lambda *_a, **_k: FakeResponse())
        return reflex.local_llm_backend()(_request(reflex))

    assert fake({"response": '{"type":"noul","noul":0.7}'})["noul"] == pytest.approx(0.7)
    assert fake({"message": {"content": '{"type":"noul","noul":0.6}'}})["noul"] == pytest.approx(0.6)
    assert fake({"content": '{"type":"noul","noul":0.5}'})["noul"] == pytest.approx(0.5)


def test_local_llm_backend_raises_on_transport_parse_and_empty_content(reflex: ModuleType, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_LOCAL_MODEL", "qwen2.5-3b-32k")
    backend = reflex.local_llm_backend()
    monkeypatch.setattr(reflex, "_open_url", lambda *_a, **_k: (_ for _ in ()).throw(OSError("refused")))
    with pytest.raises(RuntimeError, match="unreachable"):
        backend(_request(reflex))

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return self.body

    monkeypatch.setattr(reflex, "_open_url", lambda *_a, **_k: FakeResponse(b"not json"))
    with pytest.raises(RuntimeError, match="non-JSON"):
        backend(_request(reflex))

    monkeypatch.setattr(
        reflex,
        "_open_url",
        lambda *_a, **_k: FakeResponse(json.dumps({"choices": [{"message": {"content": ""}}]}).encode()),
    )
    with pytest.raises(RuntimeError, match="no content"):
        backend(_request(reflex))


def test_local_llm_failure_becomes_an_abstain_through_consult(reflex: ModuleType, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_LOCAL_MODEL", "qwen2.5-3b-32k")

    def boom(*_a, **_k):
        raise OSError("no local model")

    monkeypatch.setattr(reflex, "_open_url", boom)
    decision = reflex.consult(reflex.local_llm_backend(), _request(reflex), timeout_s=0.5)
    assert decision["verdict"] == "abstain"
    assert decision["_reason"] == "backend-error"


def test_resolve_local_model_maps_the_sentinel_to_the_configured_tag(reflex: ModuleType, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_LOCAL_MODEL", "sparknet-reflex:v1")
    assert reflex.resolve_local_model("local") == "sparknet-reflex:v1"
    assert reflex.resolve_local_model("LOCAL") == "sparknet-reflex:v1"
    assert reflex.resolve_local_model(None) == "sparknet-reflex:v1"
    assert reflex.resolve_local_model("qwen2.5-3b-32k") == "qwen2.5-3b-32k"
    monkeypatch.delenv("SPARKNET_REFLEX_LOCAL_MODEL", raising=False)
    monkeypatch.setenv("SPARKNET_LOCAL_MODEL", "fallback:v2")
    assert reflex.resolve_local_model("local") == "fallback:v2"
    monkeypatch.delenv("SPARKNET_LOCAL_MODEL", raising=False)
    with pytest.raises(reflex.ReflexPolicyError, match="no local model"):
        reflex.resolve_local_model("local")


def test_local_llm_backend_never_asks_for_a_model_named_local(reflex: ModuleType, monkeypatch) -> None:
    monkeypatch.delenv("SPARKNET_REFLEX_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("SPARKNET_LOCAL_MODEL", raising=False)
    opened: list = []
    monkeypatch.setattr(reflex, "_open_url", lambda *a, **k: opened.append((a, k)))
    with pytest.raises(reflex.ReflexPolicyError):
        reflex.local_llm_backend("local")
    assert opened == [], "an unconfigured endpoint must not open a socket"


def test_relevance_pair_requires_both_halves(reflex: ModuleType) -> None:
    pair = {"query": "guard nonce", "chunk": "the guard envelope nonce expired"}
    assert reflex.relevance_pair(pair) == ("guard nonce", "the guard envelope nonce expired")
    assert reflex.relevance_pair({"query": "guard nonce"}) == ("", "")
    assert reflex.relevance_pair({"chunk": "text"}) == ("", "")
    assert reflex.relevance_pair("alpha") == ("", "")
    assert reflex.relevance_pair(None) == ("", "")


def test_lexical_relevance_is_query_coverage(reflex: ModuleType) -> None:
    assert reflex.lexical_relevance("guard nonce", "the guard envelope nonce expired") == pytest.approx(1.0)
    assert reflex.lexical_relevance("guard nonce", "the guard envelope") == pytest.approx(0.5)
    assert reflex.lexical_relevance("guard nonce", "a recipe for soup") == 0.0
    assert reflex.lexical_relevance("", "anything") == 0.0


def test_local_relevance_answer_abstains_on_silence_instead_of_rejecting(reflex: ModuleType) -> None:
    request = _request(reflex)
    request["state"] = {"query": "guard nonce", "chunk": "the guard envelope nonce expired"}
    answer = reflex.local_relevance_answer(request)
    assert answer == {"type": "noul", "noul": pytest.approx(1.0)}

    request["state"] = {"query": "guard nonce", "chunk": "a recipe for soup"}
    with pytest.raises(reflex.ReflexNoSignal):
        reflex.local_relevance_answer(request)

    request["state"] = "alpha"
    with pytest.raises(reflex.ReflexNoSignal):
        reflex.local_relevance_answer(request)


def test_no_signal_becomes_a_low_signal_abstain_through_consult(reflex: ModuleType) -> None:
    request = _request(reflex)
    request["state"] = {"query": "guard nonce", "chunk": "a recipe for soup"}
    decision = reflex.consult(
        reflex.local_relevance_answer, request, timeout_s=0.5, backend="local-rerank", model="local"
    )
    assert decision["verdict"] == "abstain"
    assert decision["_reason"] == "low-signal"
    assert decision["backend"] == "local-rerank"


def test_exactly_one_question_per_request_is_enforced(reflex: ModuleType) -> None:
    req = _request(reflex)
    req["questions"]["second"] = {"type": "noul", "instructions": "also relevant?"}
    with pytest.raises(reflex.ReflexPolicyError, match="exactly one question"):
        reflex.validate_request(req)


def test_plan_select_is_in_the_closed_vocabulary(reflex: ModuleType, schema: dict) -> None:
    assert "plan.select" in reflex.QUESTION_CLASSES
    assert "plan.select" in schema["request"]["fields"]["question_class"]["enum"]
    assert schema["request"]["fields"]["questions"]["maxProperties"] == 1


def test_a_choice_decision_carries_the_typed_answer(reflex: ModuleType) -> None:
    req = reflex.make_request(
        "plan.select",
        {"query": "pick", "rubric": "local", "plans": [{"id": "a"}, {"id": "b"}]},
        {"choose": {"type": "choice", "instructions": "pick one", "criteria": ["a", "b"]}},
        "local",
        "plan-select-v1",
        "node-a",
        "req-1",
    )
    answer = {"type": "choice", "choice": "a", "probabilities": {"a": 0.8, "b": 0.2}, "confidence": 0.9}
    decision = reflex.decision_from_answer(answer, req)

    assert decision["verdict"] == "accept"
    assert decision["answer"] == {
        "type": "choice",
        "choice": "a",
        "probabilities": {"a": 0.8, "b": 0.2},
        "confidence": 0.9,
    }


def test_a_score_decision_carries_the_typed_answer(reflex: ModuleType) -> None:
    req = _request(reflex)
    answer = {"type": "score", "score": 0.9, "confidence": 0.9}
    decision = reflex.decision_from_answer(answer, req)
    assert decision["verdict"] == "accept"
    assert decision["answer"] == {"type": "score", "score": 0.9, "confidence": 0.9}


def test_an_abstain_carries_no_typed_answer(reflex: ModuleType) -> None:
    req = _request(reflex)
    thin = {"type": "choice", "choice": "a", "probabilities": {"a": 0.5, "b": 0.5}, "confidence": 0.9}
    decision = reflex.decision_from_answer(thin, req)
    assert decision["verdict"] == "abstain"
    assert "answer" not in decision


def test_a_non_dict_probability_set_is_malformed_not_a_crash(reflex: ModuleType) -> None:
    req = _request(reflex)
    answer = {"type": "choice", "choice": "a", "probabilities": ["a", "b"], "confidence": 0.9}
    decision = reflex.decision_from_answer(answer, req)
    assert decision["verdict"] == "abstain"
    assert decision["_reason"] == "malformed-answer"


def test_the_local_llm_asks_for_json_by_default(reflex: ModuleType, monkeypatch) -> None:
    seen: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"type":"noul","noul":0.9}'}}]}).encode()

    def fake_urlopen(request, timeout=None):
        seen["body"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setenv("SPARKNET_REFLEX_LOCAL_MODEL", "qwen2.5-3b-32k")
    monkeypatch.delenv("SPARKNET_REFLEX_STRUCTURED", raising=False)
    monkeypatch.setattr(reflex, "_open_url", fake_urlopen)
    reflex.local_llm_backend()(_request(reflex))
    assert seen["body"]["response_format"] == {"type": "json_object"}

    seen.clear()
    monkeypatch.setenv("SPARKNET_REFLEX_STRUCTURED", "0")
    reflex.local_llm_backend()(_request(reflex))
    assert "response_format" not in seen["body"]


def test_a_low_signal_abstain_records_the_measured_latency(reflex: ModuleType) -> None:
    import time as _t

    def answer(_req):
        _t.sleep(0.01)
        return {"type": "noul", "noul": 0.5}

    decision = reflex.consult(answer, _request(reflex), timeout_s=1.0)
    assert decision["verdict"] == "abstain"
    assert decision["latency_ms"] >= 5.0, "an abstain after a real call must not report 0 ms"


def test_a_non_string_choice_or_out_of_range_confidence_is_malformed(reflex: ModuleType) -> None:
    req = _request(reflex)
    bad_answers = [
        {"type": "choice", "choice": 1, "probabilities": {"1": 0.9, "b": 0.1}, "confidence": 0.9},
        {"type": "choice", "choice": "a", "probabilities": {"a": 0.9, "b": 0.1}, "confidence": 1.5},
        {"type": "score", "score": 0.9, "confidence": -0.1},
    ]
    for bad in bad_answers:
        decision = reflex.decision_from_answer(bad, req)
        assert decision["verdict"] == "abstain", bad
        assert decision["_reason"] == "malformed-answer", bad

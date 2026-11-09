"""The RAG reflex pilot (Step 64E): local reranker, metrics, shadow semantics."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sparknet_loader import load_by_path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, relative: str):
    return load_by_path(name, REPO_ROOT / relative)


vector = _load("test_reflex_vector", "scripts/sparknet-vector.py")
eval_mod = _load("test_reflex_eval", "scripts/sparknet-reflex-eval.py")

CANDIDATES = [
    {"id": "a", "path": "a.md", "document": "guard approval envelope nonce", "distance": 0.5},
    {"id": "b", "path": "b.md", "document": "unrelated cooking recipe", "distance": 0.5},
]


def test_golden_is_fabric_only_and_every_path_is_indexed():
    golden = eval_mod.load_golden(eval_mod.GOLDEN)
    assert golden["scope"] == "fabric"
    indexed = {doc["path"] for doc in vector.plan_index("fabric", REPO_ROOT)}
    for item in golden["queries"]:
        for path in item["expected"]:
            assert path in indexed, f"{path!r} is not in the fabric corpus"


def test_precision_counts_positions_not_unique_paths():
    assert eval_mod.precision_at_k(["a", "a", "b"], ["a"], 3) == pytest.approx(2 / 3)
    assert eval_mod.precision_at_k(["a", "b", "c"], ["a", "b"], 3) == pytest.approx(2 / 3)
    assert eval_mod.precision_at_k([], ["a"], 3) == 0.0


def test_recall_counts_relevant_paths_found():
    assert eval_mod.recall_at_k(["a", "a", "b"], ["a", "b"], 3) == 1.0
    assert eval_mod.recall_at_k(["a"], ["a", "b"], 3) == 0.5
    assert eval_mod.recall_at_k(["a"], [], 3) == 0.0


def test_percentile_is_nearest_rank():
    assert eval_mod.percentile([], 0.95) == 0.0
    assert eval_mod.percentile([1.0], 0.95) == 1.0
    assert eval_mod.percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert eval_mod.percentile(list(range(100)), 0.95) == 94


def test_lexical_relevance_is_query_coverage():
    assert vector.lexical_relevance("guard approval envelope", "guard approval envelope") == 1.0
    assert vector.lexical_relevance("guard approval envelope", "guard protocol") == pytest.approx(1 / 3)
    assert vector.lexical_relevance("the and of", "anything") == 0.0
    assert vector.lexical_relevance("", "anything") == 0.0


def test_rules_reranker_orders_by_lexical_signal(monkeypatch):
    monkeypatch.delenv("SPARKNET_RERANK_URL", raising=False)
    ordered, abstained, backend, latency_ms = vector.rerank_candidates("guard approval envelope", CANDIDATES)
    assert [candidate["path"] for candidate in ordered] == ["a.md", "b.md"]
    assert abstained is False
    assert backend == "rules"
    assert latency_ms >= 0.0


def test_rules_reranker_abstains_without_signal(monkeypatch):
    monkeypatch.delenv("SPARKNET_RERANK_URL", raising=False)
    ordered, abstained, backend, _ = vector.rerank_candidates("zzzz qqqq", CANDIDATES)
    assert abstained is True
    assert backend == "rules"
    assert [candidate["path"] for candidate in ordered] == ["a.md", "b.md"]


def test_http_reranker_wins_when_it_answers(monkeypatch):
    monkeypatch.setattr(vector, "http_rerank_scores", lambda _query, _documents: [0.0, 1.0])
    ordered, abstained, backend, _ = vector.rerank_candidates("guard approval envelope", CANDIDATES)
    assert [candidate["path"] for candidate in ordered] == ["b.md", "a.md"]
    assert abstained is False
    assert backend == "http-rerank"


def test_http_reranker_is_opt_in_and_fails_open(monkeypatch):
    monkeypatch.delenv("SPARKNET_RERANK_URL", raising=False)
    assert vector.http_rerank_scores("guard", ["document"]) is None
    monkeypatch.setenv("SPARKNET_RERANK_URL", "not-a-url")
    assert vector.http_rerank_scores("guard", ["document"]) is None


def test_cache_key_changes_with_query_and_candidates():
    first = vector._cache_key("guard", CANDIDATES)
    assert first == vector._cache_key("guard", CANDIDATES)
    assert first != vector._cache_key("approval", CANDIDATES)
    assert first != vector._cache_key("guard", CANDIDATES[:1])


def test_cache_hits_only_for_the_same_query(tmp_path, monkeypatch):
    monkeypatch.delenv("SPARKNET_RERANK_URL", raising=False)
    data_dir = tmp_path / "qdrant"
    first = vector.cached_rerank("guard approval envelope", CANDIDATES, data_dir)
    assert first[4] is False
    second = vector.cached_rerank("guard approval envelope", CANDIDATES, data_dir)
    assert second[4] is True
    assert second[3] == 0.0
    assert [candidate["path"] for candidate in second[0]] == [candidate["path"] for candidate in first[0]]
    third = vector.cached_rerank("different query", CANDIDATES, data_dir)
    assert third[4] is False


def test_cache_can_be_bypassed(tmp_path, monkeypatch):
    monkeypatch.delenv("SPARKNET_RERANK_URL", raising=False)
    data_dir = tmp_path / "qdrant"
    vector.cached_rerank("guard approval envelope", CANDIDATES, data_dir)
    bypass = vector.cached_rerank("guard approval envelope", CANDIDATES, data_dir, use_cache=False)
    assert bypass[4] is False


def test_order_overlap_is_jaccard():
    assert vector.order_overlap([], []) == 1.0
    assert vector.order_overlap(["a"], []) == 0.0
    assert vector.order_overlap(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)


class _FakeChroma:
    """The tiny surface ``evaluate`` needs, without Qdrant."""

    def open_checked(self, *_args, **_kwargs):
        return SimpleNamespace(name="sparknet-fabric")

    def query_candidates(self, _scope, _data_dir, _collection, _query, _n_results):
        return [dict(candidate) for candidate in CANDIDATES]

    def rerank_candidates(self, _query, candidates):
        return [candidates[1], candidates[0]], False, "rules", 2.0

    def order_overlap(self, left, right):
        return vector.order_overlap(left, right)


class _AbstainingChroma(_FakeChroma):
    def rerank_candidates(self, _query, candidates):
        return list(candidates), True, "rules", 1.0


GOLDEN_ONE = {"scope": "fabric", "queries": [{"query": "guard", "expected": ["b.md"]}]}


def test_shadow_serves_the_baseline_and_reports_the_reranked_signal():
    summary = eval_mod.evaluate(_FakeChroma(), "fabric", REPO_ROOT, REPO_ROOT, GOLDEN_ONE, "shadow", 1, 2)
    assert summary["baseline_precision_at_k"] == 0.0
    assert summary["reranked_precision_at_k"] == 1.0
    assert summary["served_precision_at_k"] == 0.0
    assert summary["shadow_agreement_at_k"] == 0.0
    assert summary["abstain_rate"] == 0.0


def test_assist_serves_the_reranked_order():
    summary = eval_mod.evaluate(_FakeChroma(), "fabric", REPO_ROOT, REPO_ROOT, GOLDEN_ONE, "assist", 1, 2)
    assert summary["served_precision_at_k"] == 1.0


def test_abstain_falls_back_to_the_baseline():
    summary = eval_mod.evaluate(_AbstainingChroma(), "fabric", REPO_ROOT, REPO_ROOT, GOLDEN_ONE, "assist", 1, 2)
    assert summary["served_precision_at_k"] == 0.0
    assert summary["abstain_rate"] == 1.0


LIVE_CONFIG = {
    "backend": "broker",
    "broker_url": "http://127.0.0.1:1",
    "model": "local",
    "node_id": "test-node",
    "policy_version": "rag-relevance-v1",
    "timeout": 0.1,
    "usd_per_1k_tokens": 0.0,
}


def test_live_preflight_has_one_gate_and_no_credential_to_leak():
    """The pilot gates on the broker answering, and on nothing else.

    It used to gate on three things because one backend could carry fabric text
    off the fabric, which made a governance approval and a 0600 credential
    meaningful. No backend can now, so those gates would only be theatre — and a
    config that has no key field cannot name a key to leak.
    """
    assert eval_mod.live_preflight(config=LIVE_CONFIG, check_health=False) == []
    assert "key_file" not in LIVE_CONFIG
    assert "governance" not in LIVE_CONFIG
    assert "key_file" not in eval_mod.live_config()
    assert "governance" not in eval_mod.live_config()


def test_live_preflight_reports_an_unreachable_broker(monkeypatch):
    def explode(*_args, **_kwargs):
        raise OSError("nothing listening")

    monkeypatch.setattr(eval_mod.urllib.request, "urlopen", explode)
    problems = eval_mod.live_preflight(config=LIVE_CONFIG, check_health=True)
    assert any("unreachable" in problem for problem in problems)


def test_live_preflight_refuses_a_healthz_that_is_not_ok(monkeypatch):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        @staticmethod
        def read():
            return b'{"ok": false}'

    monkeypatch.setattr(eval_mod.urllib.request, "urlopen", lambda *_a, **_k: _Response())
    problems = eval_mod.live_preflight(config=LIVE_CONFIG, check_health=True)
    assert any("healthz" in problem for problem in problems)


def test_post_decision_maps_transport_failure_to_abstain(monkeypatch):
    def explode(*_args, **_kwargs):
        raise OSError("broker down")

    monkeypatch.setattr(eval_mod.urllib.request, "urlopen", explode)
    decision = eval_mod.post_decision({}, LIVE_CONFIG)
    assert decision["verdict"] == "abstain"
    assert decision["_reason"] == "broker-error"
    assert decision["backend"] == "null", "an unreachable broker must not be reported as a cloud backend"


def test_live_relevance_orders_accepts_above_rejects():
    reflex = eval_mod._load_reflex()

    def post(request):
        if request["state"]["chunk"] == "alpha":
            return {
                "verdict": "reject",
                "confidence": 0.0,
                "backend": "local-rerank",
                "usage": {"total_tokens": 10},
            }
        return {
            "verdict": "accept",
            "confidence": 0.9,
            "backend": "local-rerank",
            "usage": {"total_tokens": 10},
        }

    candidates = [
        {"id": "a", "path": "a.md", "document": "alpha", "distance": 0.1},
        {"id": "b", "path": "b.md", "document": "beta", "distance": 0.2},
    ]
    ordered, abstained, backend, _latency, tokens = eval_mod.live_relevance(
        "guard", candidates, reflex=reflex, post=post, config=LIVE_CONFIG, limit=2
    )
    assert [candidate["path"] for candidate in ordered] == ["b.md", "a.md"]
    assert abstained is False
    assert backend == "local-rerank"
    assert tokens == 20


def test_live_relevance_all_abstain_keeps_order():
    reflex = eval_mod._load_reflex()
    candidates = [
        {"id": "a", "path": "a.md", "document": "alpha", "distance": 0.1},
        {"id": "b", "path": "b.md", "document": "beta", "distance": 0.2},
    ]
    ordered, abstained, _backend, _latency, tokens = eval_mod.live_relevance(
        "guard", candidates, reflex=reflex, post=lambda _request: {"verdict": "abstain"}, config=LIVE_CONFIG, limit=2
    )
    assert [candidate["path"] for candidate in ordered] == ["a.md", "b.md"]
    assert abstained is True
    assert tokens == 0


def test_live_relevance_maps_an_exception_to_abstain():
    reflex = eval_mod._load_reflex()

    def boom(_request):
        raise RuntimeError("injected")

    ordered, abstained, _backend, _latency, tokens = eval_mod.live_relevance(
        "guard", [dict(CANDIDATES[0])], reflex=reflex, post=boom, config=LIVE_CONFIG, limit=1
    )
    assert ordered[0]["reflex_verdict"] == "abstain"
    assert abstained is True
    assert tokens == 0


def test_live_evaluate_measures_tokens_and_cost():
    reflex = eval_mod._load_reflex()

    def post(_request):
        return {"verdict": "accept", "confidence": 0.9, "backend": "broker", "usage": {"total_tokens": 100}}

    summary = eval_mod.evaluate(
        _FakeChroma(),
        "fabric",
        REPO_ROOT,
        REPO_ROOT,
        GOLDEN_ONE,
        "assist",
        1,
        2,
        live=True,
        reflex=reflex,
        post=post,
        config={**LIVE_CONFIG, "usd_per_1k_tokens": 0.5},
        limit=2,
        rate=0.5,
    )
    assert summary["live"] is True
    assert summary["tokens_per_1k_queries"] == 200_000.0
    assert summary["cost_per_1k_usd"] == 100.0
    assert summary["backend"] == "broker"


def test_load_golden_rejects_malformed_sets(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"queries": [{"query": "x", "expected": []}]}), encoding="utf-8")
    with pytest.raises(SystemExit):
        eval_mod.load_golden(bad)
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        eval_mod.load_golden(bad)


def _query(monkeypatch, capsys, reflex: str) -> str:
    monkeypatch.setattr(vector, "open_checked", lambda *_args, **_kwargs: SimpleNamespace(name="sparknet-fabric"))
    monkeypatch.setattr(
        vector,
        "query_candidates",
        lambda *_args, **_kwargs: [dict(candidate) for candidate in CANDIDATES],
    )
    monkeypatch.setattr(
        vector,
        "cached_rerank",
        lambda _query, candidates, _data_dir, **_kwargs: ([candidates[1], candidates[0]], False, "rules", 1.0, False),
    )
    assert vector.cmd_query("fabric", REPO_ROOT, REPO_ROOT, "guard", 2, reflex=reflex) == 0
    return capsys.readouterr().out


def test_cmd_query_without_reflex_is_unchanged(monkeypatch, capsys):
    output = _query(monkeypatch, capsys, "off")
    assert "reflex=" not in output
    assert output.index("a.md") < output.index("b.md")


def test_cmd_query_shadow_returns_the_baseline_order(monkeypatch, capsys):
    output = _query(monkeypatch, capsys, "shadow")
    assert "reflex=shadow" in output
    assert "abstain=false" in output
    assert output.index("a.md") < output.index("b.md")


def test_cmd_query_assist_returns_the_reranked_order(monkeypatch, capsys):
    output = _query(monkeypatch, capsys, "assist")
    assert "reflex=assist" in output
    assert output.index("b.md") < output.index("a.md")

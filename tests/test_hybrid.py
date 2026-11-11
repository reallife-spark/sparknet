"""Hybrid retrieval returns both evidence sets, never a silent merge."""

from __future__ import annotations

import pytest
from contract_helpers import REPO_ROOT, load
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


HYBRID_PATH = REPO_ROOT / "shared" / "sparknet-hybrid.py"


def _load_hybrid():
    return load_by_path("sparknet_hybrid", HYBRID_PATH)


hybrid = _load_hybrid()


def semantic(**overrides):
    body = {
        "result_id": "sem-1",
        "source": "qdrant",
        "path": "05_Knowledge/a.md",
        "score": 0.91,
        "text": "semantic text",
        "classification": "internal",
        "provenance": {"source": "05_Knowledge/a.md", "digest": "a" * 64},
    }
    body.update(overrides)
    return hybrid.semantic_result(**body)


def agentic(**overrides):
    body = {
        "result_id": "agt-1",
        "tool": "vault_search",
        "action": "search",
        "result": {"hits": 2},
        "classification": "internal",
        "provenance": {"source": "05_Knowledge/a.md", "digest": "a" * 64},
    }
    body.update(overrides)
    return hybrid.agentic_result(**body)


def test_contract_vocabularies_match_the_module():
    schema = load("hybrid-schema.json")
    assert schema["bundle"]["schema"] == hybrid.BUNDLE_SCHEMA
    assert schema["semantic_result"]["schema"] == hybrid.SEMANTIC_SCHEMA
    assert schema["agentic_result"]["schema"] == hybrid.AGENTIC_SCHEMA
    assert set(schema["refusal_codes"]) >= {"missing-provenance", "classification-downgrade"}


def test_bundle_returns_both_sets_deterministically():
    built = hybrid.bundle(query="q", semantic=[semantic()], agentic=[agentic()])
    assert built["semantic"][0]["result_id"] == "sem-1"
    assert built["agentic"][0]["result_id"] == "agt-1"
    assert built["classification"] == "internal"
    assert "Semantic results" in hybrid.render_for_agent(built)
    assert "Agentic results" in hybrid.render_for_agent(built)


def test_empty_sets_are_stated_not_hidden():
    built = hybrid.bundle(query="q", semantic=[], agentic=[])
    rendered = hybrid.render_for_agent(built)
    assert rendered.count("(none)") == 2


def test_provenance_is_required():
    with pytest.raises(hybrid.HybridError) as refused:
        hybrid.semantic_result(
            result_id="sem-2",
            source="qdrant",
            path="05_Knowledge/a.md",
            score=0.5,
            text="x",
            provenance={},
            classification="internal",
        )
    assert refused.value.code == "missing-provenance"
    with pytest.raises(hybrid.HybridError):
        hybrid.agentic_result(
            result_id="agt-2",
            tool="t",
            action="a",
            result="r",
            provenance=None,
            classification="internal",
        )


def test_classification_is_the_highest_and_never_downgraded():
    built = hybrid.bundle(query="q", semantic=[semantic(classification="confidential")], agentic=[agentic()])
    assert built["classification"] == "confidential"
    with pytest.raises(hybrid.HybridError) as refused:
        hybrid.bundle(
            query="q",
            semantic=[semantic(classification="confidential")],
            agentic=[agentic()],
            classification="internal",
        )
    assert refused.value.code == "classification-downgrade"


def test_bundle_has_no_authority_fields():
    built = hybrid.bundle(query="q", semantic=[], agentic=[])
    assert "capabilities" not in built
    assert "grant" not in built


def test_prebuilt_rows_are_still_validated():
    bad = semantic()
    bad["classification"] = "secret"
    with pytest.raises(hybrid.HybridError) as refused:
        hybrid.bundle(query="q", semantic=[bad], agentic=[])
    assert refused.value.code == "unknown-classification"
    bad_path = semantic()
    bad_path["path"] = "../peer-user-2/00_System/keys"
    with pytest.raises(hybrid.HybridError) as escaped:
        hybrid.bundle(query="q", semantic=[bad_path], agentic=[])
    assert escaped.value.code == "bad-result"


def test_nan_score_is_refused():
    with pytest.raises(hybrid.HybridError) as refused:
        hybrid.semantic_result(
            result_id="sem-nan",
            source="qdrant",
            path="05_Knowledge/a.md",
            score=float("nan"),
            text="x",
            provenance={"source": "05_Knowledge/a.md"},
            classification="internal",
        )
    assert refused.value.code == "bad-score"


def test_render_refuses_an_unvalidated_bundle():
    with pytest.raises(hybrid.HybridError):
        hybrid.render_for_agent({"schema_version": hybrid.BUNDLE_SCHEMA, "query": "q", "semantic": [], "agentic": []})

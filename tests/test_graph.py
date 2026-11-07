"""The graph is a derived projection: deterministic, vault-scoped, no writes."""

from __future__ import annotations

import importlib.util
import sys

import pytest
from contract_helpers import REPO_ROOT, load

GRAPH_PATH = REPO_ROOT / "shared" / "sparknet-graph.py"


def _load_graph():
    spec = importlib.util.spec_from_file_location("sparknet_graph", GRAPH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


graph = _load_graph()


def test_contract_vocabularies_match_the_module():
    schema = load("graph-schema.json")
    assert schema["graph"]["schema"] == graph.GRAPH_SCHEMA
    assert tuple(schema["edge"]["kinds"]) == graph.EDGE_KINDS
    assert set(schema["refusal_codes"]) >= {"bad-path", "cross-vault-edge", "unknown-node"}


def test_build_graph_from_wikilinks():
    pages = [
        {
            "vault_id": "peer-user-1",
            "path": "05_Knowledge/a.md",
            "title": "A",
            "classification": "internal",
            "text": "See [[05_Knowledge/b#section|B]] and [[C]].",
        },
        {"vault_id": "peer-user-1", "path": "05_Knowledge/b.md", "title": "B", "classification": "internal"},
        {"vault_id": "peer-user-1", "path": "06_Projects/c.md", "title": "C", "classification": "internal"},
    ]
    built = graph.build_graph(pages)
    assert [node["id"] for node in built["nodes"]] == [
        "peer-user-1:05_Knowledge/a.md",
        "peer-user-1:05_Knowledge/b.md",
        "peer-user-1:06_Projects/c.md",
    ]
    assert [(edge["source"], edge["target"]) for edge in built["edges"]] == [
        ("peer-user-1:05_Knowledge/a.md", "peer-user-1:05_Knowledge/b.md"),
        ("peer-user-1:05_Knowledge/a.md", "peer-user-1:06_Projects/c.md"),
    ]
    assert graph.neighbors(built, "peer-user-1:05_Knowledge/a.md") == [
        "peer-user-1:05_Knowledge/b.md",
        "peer-user-1:06_Projects/c.md",
    ]
    assert graph.shortest_path(built, "peer-user-1:05_Knowledge/b.md", "peer-user-1:06_Projects/c.md") == [
        "peer-user-1:05_Knowledge/b.md",
        "peer-user-1:05_Knowledge/a.md",
        "peer-user-1:06_Projects/c.md",
    ]


def test_unresolved_and_cross_vault_links_are_reported():
    pages = [
        {
            "vault_id": "peer-user-1",
            "path": "05_Knowledge/a.md",
            "title": "A",
            "classification": "internal",
            "links": ["missing.md", "peer-user-2:05_Knowledge/b.md"],
        },
        {"vault_id": "peer-user-2", "path": "05_Knowledge/b.md", "title": "B", "classification": "internal"},
    ]
    built = graph.build_graph(pages)
    assert built["edges"] == []
    assert {row["reason"] for row in built["unresolved"]} == {"unresolved", "cross-vault-edge"}


def test_path_traversal_is_refused():
    with pytest.raises(graph.GraphError) as refused:
        graph.build_graph([{"vault_id": "peer-user-1", "path": "../secret.md", "classification": "internal"}])
    assert refused.value.code == "bad-path"


def test_graph_is_deterministic():
    pages = [
        {"vault_id": "v", "path": "b.md", "title": "B", "classification": "internal", "text": "[[a]]"},
        {"vault_id": "v", "path": "a.md", "title": "A", "classification": "internal"},
    ]
    assert graph.to_json(graph.build_graph(pages)) == graph.to_json(graph.build_graph(reversed(pages)))


def test_unknown_direction_and_node_are_refused():
    with pytest.raises(graph.GraphError) as direction:
        graph.neighbors({"nodes": [{"id": "v:a.md"}], "edges": []}, "v:a.md", "sideways")
    assert direction.value.code == "bad-direction"
    with pytest.raises(graph.GraphError) as missing:
        graph.neighbors({"nodes": [{"id": "v:a.md"}], "edges": []}, "v:missing.md")
    assert missing.value.code == "unknown-node"


def test_duplicate_nodes_and_colon_vaults_are_refused():
    with pytest.raises(graph.GraphError) as duplicate:
        graph.build_graph(
            [
                {"vault_id": "v", "path": "a.md", "title": "A", "classification": "internal"},
                {"vault_id": "v", "path": "a.md", "title": "A", "classification": "internal"},
            ]
        )
    assert duplicate.value.code == "duplicate-node"
    with pytest.raises(graph.GraphError) as vault:
        graph.build_graph([{"vault_id": "a:b", "path": "c.md", "title": "C", "classification": "internal"}])
    assert vault.value.code == "bad-vault"


def test_a_colon_in_a_filename_is_not_a_vault_prefix():
    built = graph.build_graph(
        [
            {
                "vault_id": "v",
                "path": "a.md",
                "title": "A",
                "classification": "internal",
                "text": "[[10:30.md]]",
            },
            {"vault_id": "v", "path": "10:30.md", "title": "10:30", "classification": "internal"},
        ]
    )
    assert built["unresolved"] == []
    assert built["edges"][0]["target"] == "v:10:30.md"


def test_graph_has_no_authority_fields():
    built = graph.build_graph([{"vault_id": "v", "path": "a.md", "title": "A", "classification": "internal"}])
    assert "capabilities" not in built
    assert "grant" not in built
    assert built["schema_version"] == "sparknet-graph/1"

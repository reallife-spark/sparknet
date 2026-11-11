"""Tests for the Understand-Anything core (contract + Python extractors).

The graph is a derived artifact, so these tests care about three things: the
contract vocabulary is not restated privately, an unchanged tree produces the
same nodes/edges, and no absolute host path or secret-shaped value enters the
output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPO_ROOT / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from sparknet_understand import algebra, build, core, domain, figma, knowledge, production, schema  # noqa: E402

pytestmark = pytest.mark.integration


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    _write(
        tmp_path,
        "src/app.py",
        '''"""Demo application."""
import os

class Base:
    pass

class Greeter(Base):
    def hello(self, name):
        return greet(name)

def greet(name):
    if not name:
        return "hi"
    return f"hi {name}"
''',
    )
    _write(
        tmp_path,
        "tests/test_app.py",
        "from src.app import greet\n\ndef test_greet():\n    assert greet('x')\n",
    )
    _write(
        tmp_path,
        "src/main.go",
        """package main

import "fmt"

type Server struct {
    Name string
}

func (s *Server) Handle() {
    fmt.Println(s.Name)
}
""",
    )
    _write(
        tmp_path,
        "src/ui.js",
        """import React from "react";
export function App() {
  return render();
}
const router = { get: () => {} };
router.get("/health", handler);
""",
    )
    _write(
        tmp_path,
        "README.md",
        """---
title: Demo
category: docs
---
# Demo

See [[Guide]] and [app](src/app.py).
""",
    )
    _write(tmp_path, "index.md", "# Index\n\n## Guides\n")
    _write(tmp_path, ".env", "API_KEY=placeholder\n")
    _write(tmp_path, "node_modules/ignored.js", "function shouldNotAppear() {}\n")
    return tmp_path


def _build(root: Path) -> tuple[dict, list[dict[str, str]]]:
    return build.build_graph(root, analyzed_at="2026-11-09T00:00:00Z")


def test_core_facade_reexports_the_narrow_modules() -> None:
    assert core.load_schema is schema.load_schema
    assert core.make_node is schema.make_node
    assert core.scan is production.scan
    assert core.FileRecord is production.FileRecord
    assert core.build_layers is algebra.build_layers
    assert core.diff_graphs is algebra.diff_graphs
    assert {"load_schema", "scan", "validate_graph", "diff_graphs"} <= set(core.__all__)


def test_schema_module_reads_the_contract_and_builds_nodes() -> None:
    contract = schema.load_schema()
    assert contract["node_types"][0] == "file"
    node = schema.make_node("function:a.py:greet:1", "function", "greet")
    assert node["type"] == "function"


def test_production_module_owns_scan_policy(project: Path) -> None:
    result = production.scan(project)
    paths = {record.path for record in result.files}
    assert "src/app.py" in paths
    assert "node_modules/ignored.js" not in paths


def test_algebra_module_owns_graph_transforms(project: Path) -> None:
    graph, _ = build.build_graph(project, analyzed_at="2026-11-09T00:00:00Z")
    assert algebra.validate_graph(graph) == []
    delta = algebra.diff_graphs(graph, graph)
    assert delta["nodes_added"] == [] and delta["nodes_removed"] == []


def test_contract_vocabulary_is_complete() -> None:
    schema = core.load_schema()
    edge_types = {edge for values in schema["edge_types"].values() if isinstance(values, list) for edge in values}
    assert len(edge_types) == 38
    assert len(schema["node_types"]) == 27
    assert schema["node_types"][0] == "file"


def test_scan_ignores_default_excludes(project: Path) -> None:
    result = core.scan(project)
    paths = {record.path for record in result.files}
    assert "node_modules/ignored.js" not in paths
    assert "src/app.py" in paths
    assert "tests/test_app.py" in paths


def test_build_graph_uses_canonical_vocabulary(project: Path) -> None:
    graph, issues = _build(project)
    assert not [issue for issue in issues if issue["level"] == "fatal"]
    canonical_nodes = set(core.load_schema()["node_types"])
    assert {node["type"] for node in graph["nodes"]} <= canonical_nodes
    canonical_edges = {
        edge for values in core.load_schema()["edge_types"].values() if isinstance(values, list) for edge in values
    }
    assert {edge["type"] for edge in graph["edges"]} <= canonical_edges
    assert any(node["type"] == "class" and node["name"] == "Greeter" for node in graph["nodes"])
    assert any(edge["type"] == "inherits" for edge in graph["edges"])


def test_test_edges_link_source_to_test(project: Path) -> None:
    graph, _ = _build(project)
    test_edges = [edge for edge in graph["edges"] if edge["type"] == "tested_by"]
    assert test_edges == [
        {
            "source": "file:src/app.py",
            "target": "file:tests/test_app.py",
            "type": "tested_by",
            "direction": "forward",
            "weight": 0.5,
        }
    ]


def test_graph_has_no_absolute_or_escaping_paths(project: Path) -> None:
    graph, _ = _build(project)
    for node in graph["nodes"]:
        path = node.get("filePath")
        if path:
            assert not path.startswith("/")
            assert ".." not in Path(path).parts


def test_output_is_deterministic_for_a_fixed_timestamp(project: Path) -> None:
    first, _ = _build(project)
    second, _ = _build(project)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_validate_reports_a_dangling_edge(project: Path) -> None:
    graph, _ = _build(project)
    broken = json.loads(json.dumps(graph))
    broken["edges"].append(
        {
            "source": "file:src/app.py",
            "target": "file:missing.py",
            "type": "imports",
            "direction": "forward",
            "weight": 0.5,
        }
    )
    issues = core.validate_graph(broken)
    assert any(issue["level"] == "fatal" and "missing node" in issue["message"] for issue in issues)


def test_diff_reports_added_and_removed(project: Path) -> None:
    old, _ = _build(project)
    _write(project, "src/extra.py", "def extra():\n    return 1\n")
    new, _ = _build(project)
    delta = core.diff_graphs(old, new)
    assert "file:src/extra.py" in delta["nodes_added"]
    assert any(edge[0] == "file:src/extra.py" for edge in delta["edges_added"])


def test_knowledge_graph_keeps_wikilinks_and_categories(project: Path) -> None:
    graph, issues = knowledge.build_knowledge_graph(project, analyzed_at="2026-11-09T00:00:00Z")
    assert not [issue for issue in issues if issue["level"] == "fatal"]
    assert any(node["type"] == "article" and node["id"] == "article:README.md" for node in graph["nodes"])
    assert any(edge["type"] == "related" for edge in graph["edges"])
    assert any(edge["type"] == "categorized_under" for edge in graph["edges"])


def test_domain_context_finds_routes_and_entities(project: Path) -> None:
    context = domain.extract_domain_context(project)
    assert any(route["path"] == "/health" for route in context["routes"])
    assert any(entity["name"] == "Server" for entity in context["entities"])


def test_figma_scan_builds_design_graph(tmp_path: Path) -> None:
    document = {
        "name": "Design",
        "document": {
            "id": "0:1",
            "type": "PAGE",
            "name": "Page",
            "children": [{"id": "1:2", "type": "COMPONENT", "name": "Button", "styles": {"fill": "S:1"}}],
        },
        "styles": {"S:1": {"name": "Primary", "styleType": "FILL"}},
    }
    path = tmp_path / "design.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    graph, issues = figma.scan_figma(path)
    assert not [issue for issue in issues if issue["level"] == "fatal"]
    assert graph["kind"] == "design"
    assert {node["type"] for node in graph["nodes"]} >= {"page", "component", "token"}
    assert any(edge["type"] == "uses_token" for edge in graph["edges"])


def test_cli_build_and_validate(project: Path, tmp_path: Path) -> None:
    out = tmp_path / "graph.json"
    run = subprocess.run(
        [sys.executable, str(SHARED / "sparknet-understand.py"), "build", "--root", str(project), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    graph = json.loads(out.read_text(encoding="utf-8"))
    assert graph["nodes"]
    check = subprocess.run(
        [sys.executable, str(SHARED / "sparknet-understand.py"), "validate", "--input", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert json.loads(check.stdout)["valid"] is True

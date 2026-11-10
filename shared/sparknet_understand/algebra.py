#!/usr/bin/env python3
"""Graph algebra: normalize, merge, validate, diff, layers and tour.

This module transforms graph data. It reads vocabulary and constructors from
``schema``; it never scans a tree and never writes a vault page.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .schema import _edge_types, _node_types, canonical_direction, canonical_edge_type, make_node


def _normalize_node(node: Mapping[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("id") or "").strip()
    if not node_id:
        raise ValueError("node has no id")
    result = make_node(
        node_id,
        node.get("type", "file"),
        node.get("name", node_id),
        summary=node.get("summary", node.get("name", node_id)),
        tags=node.get("tags", []),
        complexity=node.get("complexity", "moderate"),
        file_path=node.get("filePath"),
        line_range=tuple(node["lineRange"]) if isinstance(node.get("lineRange"), (list, tuple)) else None,
    )
    for key in ("languageNotes", "domainMeta", "knowledgeMeta", "figmaMeta"):
        if node.get(key) is not None:
            result[key] = node[key]
    return result


def _normalize_edge(edge: Mapping[str, Any]) -> dict[str, Any] | None:
    canonical = canonical_edge_type(edge.get("type"))
    if canonical is None:
        return None
    try:
        weight = max(0.0, min(1.0, float(edge.get("weight", 0.5))))
    except (TypeError, ValueError):
        weight = 0.5
    result: dict[str, Any] = {
        "source": str(edge.get("source") or ""),
        "target": str(edge.get("target") or ""),
        "type": canonical,
        "direction": canonical_direction(edge.get("direction")),
        "weight": weight,
    }
    if not result["source"] or not result["target"]:
        return None
    if edge.get("description"):
        result["description"] = str(edge["description"])
    return result


def build_layers(nodes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        file_path = node.get("filePath")
        if not file_path:
            continue
        parts = PurePosixPath(str(file_path)).parts
        groups[parts[0] if len(parts) > 1 else "root"].append(str(node["id"]))
    layers: list[dict[str, Any]] = []
    for name in sorted(groups):
        node_ids = sorted(set(groups[name]))
        if not node_ids:
            continue
        layers.append(
            {
                "id": f"layer:{name}",
                "name": name,
                "description": f"{len(node_ids)} node(s) under {name}",
                "nodeIds": node_ids,
            }
        )
    return layers


def build_tour(nodes: Iterable[Mapping[str, Any]], edges: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    nodes = list(nodes)
    degree: Counter[str] = Counter()
    for edge in edges:
        degree[str(edge["source"])] += 1
        degree[str(edge["target"])] += 1
    ranked = sorted(nodes, key=lambda node: (-degree[str(node["id"])], str(node["id"])))
    steps: list[dict[str, Any]] = []
    seen_layers: set[str] = set()
    chosen: list[Mapping[str, Any]] = []
    for node in ranked:
        file_path = node.get("filePath")
        layer = (
            PurePosixPath(str(file_path)).parts[0]
            if file_path and len(PurePosixPath(str(file_path)).parts) > 1
            else "root"
        )
        if layer in seen_layers and len(chosen) >= 4:
            continue
        seen_layers.add(layer)
        chosen.append(node)
        if len(chosen) >= 12:
            break
    for order, node in enumerate(chosen, start=1):
        steps.append(
            {
                "order": order,
                "title": str(node.get("name", node["id"])),
                "description": str(node.get("summary", "")),
                "nodeIds": [str(node["id"])],
            }
        )
    return steps


def merge_fragments(
    fragments: Iterable[Mapping[str, Any]],
    project: Mapping[str, Any],
    *,
    kind: str = "codebase",
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Merge per-file fragments into one graph, dropping broken references."""
    issues: list[dict[str, str]] = []
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    for fragment in fragments:
        for raw in fragment.get("nodes", []) or []:
            try:
                node = _normalize_node(raw)
            except (TypeError, ValueError) as exc:
                issues.append({"level": "dropped", "category": "node", "message": str(exc)})
                continue
            existing = nodes.get(node["id"])
            if existing is None:
                nodes[node["id"]] = node
                continue
            existing["tags"] = sorted(set(existing.get("tags", [])) | set(node.get("tags", [])))
            if existing.get("summary") in ("", existing["id"]):
                existing["summary"] = node.get("summary", existing["summary"])
        for raw in fragment.get("edges", []) or []:
            edge = _normalize_edge(raw)
            if edge is None:
                issues.append({"level": "dropped", "category": "edge", "message": "malformed edge"})
                continue
            key = (edge["source"], edge["target"], edge["type"])
            if key not in edges:
                edges[key] = edge
    for key, edge in list(edges.items()):
        if edge["source"] not in nodes or edge["target"] not in nodes:
            issues.append(
                {
                    "level": "dropped",
                    "category": "edge",
                    "message": f"{edge['source']} -{edge['type']}-> {edge['target']} references a missing node",
                }
            )
            del edges[key]
    ordered_nodes = [nodes[node_id] for node_id in sorted(nodes)]
    ordered_edges = [edges[key] for key in sorted(edges)]
    graph = {
        "version": "1.0",
        "kind": kind if kind in {"codebase", "knowledge", "design"} else "codebase",
        "project": dict(project),
        "nodes": ordered_nodes,
        "edges": ordered_edges,
        "layers": build_layers(ordered_nodes),
        "tour": build_tour(ordered_nodes, ordered_edges),
    }
    return graph, issues


def normalize_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    nodes = []
    for raw in graph.get("nodes", []) or []:
        try:
            nodes.append(_normalize_node(raw))
        except (TypeError, ValueError):
            continue
    nodes.sort(key=lambda node: str(node["id"]))
    known = {str(node["id"]) for node in nodes}
    edges = []
    for raw in graph.get("edges", []) or []:
        edge = _normalize_edge(raw)
        if edge and edge["source"] in known and edge["target"] in known:
            edges.append(edge)
    edges.sort(key=lambda edge: (edge["source"], edge["target"], edge["type"]))
    result = {
        "version": str(graph.get("version", "1.0")),
        "kind": graph.get("kind", "codebase"),
        "project": dict(graph.get("project", {})),
        "nodes": nodes,
        "edges": edges,
        "layers": build_layers(nodes),
        "tour": build_tour(nodes, edges),
    }
    return result


def validate_graph(graph: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return fatal and auto-correctable issues; never raise on caller data."""
    issues: list[dict[str, str]] = []
    for key in ("version", "project", "nodes", "edges", "layers", "tour"):
        if key not in graph:
            issues.append({"level": "fatal", "category": "missing-field", "message": f"missing {key}", "path": key})
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list):
        issues.append({"level": "fatal", "category": "invalid-collection", "message": "nodes must be an array"})
        nodes = []
    if not isinstance(edges, list):
        issues.append({"level": "fatal", "category": "invalid-collection", "message": "edges must be an array"})
        edges = []
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            issues.append({"level": "fatal", "category": "node", "message": f"nodes[{index}] is not an object"})
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            issues.append({"level": "fatal", "category": "node", "message": f"nodes[{index}] has no id"})
            continue
        if node_id in seen:
            issues.append({"level": "fatal", "category": "node", "message": f"duplicate node id {node_id}"})
        seen.add(node_id)
        if node.get("type") not in _node_types():
            issues.append(
                {"level": "auto-corrected", "category": "node", "message": f"{node_id} type is not canonical"}
            )
        if node.get("complexity") not in {"simple", "moderate", "complex"}:
            issues.append(
                {"level": "auto-corrected", "category": "node", "message": f"{node_id} complexity is invalid"}
            )
        file_path = node.get("filePath")
        if isinstance(file_path, str) and (file_path.startswith("/") or ".." in PurePosixPath(file_path).parts):
            issues.append(
                {"level": "fatal", "category": "path", "message": f"{node_id} has an absolute or escaping path"}
            )
    for index, edge in enumerate(edges):
        if not isinstance(edge, Mapping):
            issues.append({"level": "fatal", "category": "edge", "message": f"edges[{index}] is not an object"})
            continue
        if edge.get("type") not in _edge_types():
            issues.append({"level": "fatal", "category": "edge", "message": f"edges[{index}] type is not canonical"})
        if edge.get("source") not in seen or edge.get("target") not in seen:
            issues.append(
                {"level": "fatal", "category": "edge", "message": f"edges[{index}] references a missing node"}
            )
        weight = edge.get("weight")
        if not isinstance(weight, (int, float)) or not 0 <= float(weight) <= 1:
            issues.append(
                {"level": "auto-corrected", "category": "edge", "message": f"edges[{index}] weight is invalid"}
            )
    return issues


def diff_graphs(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    old_nodes = {
        str(node["id"]): node for node in old.get("nodes", []) or [] if isinstance(node, Mapping) and node.get("id")
    }
    new_nodes = {
        str(node["id"]): node for node in new.get("nodes", []) or [] if isinstance(node, Mapping) and node.get("id")
    }
    old_edges = {
        (str(edge["source"]), str(edge["target"]), str(edge["type"])): edge
        for edge in old.get("edges", []) or []
        if isinstance(edge, Mapping)
    }
    new_edges = {
        (str(edge["source"]), str(edge["target"]), str(edge["type"])): edge
        for edge in new.get("edges", []) or []
        if isinstance(edge, Mapping)
    }
    changed = []
    for node_id in sorted(set(old_nodes) & set(new_nodes)):
        if old_nodes[node_id] != new_nodes[node_id]:
            changed.append(node_id)
    return {
        "nodes_added": sorted(set(new_nodes) - set(old_nodes)),
        "nodes_removed": sorted(set(old_nodes) - set(new_nodes)),
        "nodes_changed": changed,
        "edges_added": sorted([list(key) for key in set(new_edges) - set(old_edges)]),
        "edges_removed": sorted([list(key) for key in set(old_edges) - set(new_edges)]),
    }


def write_graph(path: str | Path, graph: Mapping[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(graph, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def fragment(nodes: Iterable[Mapping[str, Any]] = (), edges: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    return {"nodes": list(nodes), "edges": [edge for edge in edges if edge]}

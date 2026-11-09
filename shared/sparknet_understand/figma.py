#!/usr/bin/env python3
"""Figma document to design graph.

The input is a Figma REST document (JSON) already fetched by the caller. The
graph records pages, screens, components, component sets, instances and design
tokens. It never calls the network and never stores a credential.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .core import make_edge, make_node, merge_fragments, normalize_graph, project_meta

TYPE_MAP = {
    "PAGE": "page",
    "FRAME": "screen",
    "GROUP": "screen",
    "COMPONENT": "component",
    "COMPONENT_SET": "componentSet",
    "INSTANCE": "instance",
    "TEXT": "page",
    "RECTANGLE": "screen",
    "ELLIPSE": "screen",
    "VECTOR": "screen",
    "BOOLEAN_OPERATION": "component",
}

TOKEN_KIND = {
    "FILL": "color",
    "TEXT": "type",
    "EFFECT": "effect",
    "GRID": "grid",
    "STROKE": "color",
}


def _figma_id(value: Any) -> str:
    return f"figma:{value}"


def _walk(
    node: Mapping[str, Any], nodes: list[dict[str, Any]], edges: list[dict[str, Any]], parent: str | None
) -> None:
    node_id = _figma_id(node.get("id", ""))
    node_type = TYPE_MAP.get(str(node.get("type", "")).upper(), "screen")
    name = str(node.get("name") or node.get("id") or "unnamed")
    line = node.get("absoluteBoundingBox") or {}
    nodes.append(
        make_node(
            node_id,
            node_type,
            name,
            summary=f"Figma {node.get('type', 'node')} {name}",
            tags=["figma", str(node.get("type", "node")).lower()],
            figmaMeta={
                "figmaType": node.get("type"),
                "nodeId": node.get("id"),
                "dimensions": {"width": line.get("width", 0), "height": line.get("height", 0)}
                if isinstance(line, Mapping)
                else None,
            },
        )
    )
    if parent:
        edges.append(make_edge(parent, node_id, "contains") or {})
    for child in node.get("children", []) or []:
        if isinstance(child, Mapping):
            _walk(child, nodes, edges, node_id)
    component_id = node.get("componentId")
    if component_id:
        edges.append(make_edge(node_id, _figma_id(component_id), "instance_of") or {})
    styles = node.get("styles", {}) or {}
    values = styles.values() if isinstance(styles, Mapping) else styles
    for style in values:
        edges.append(make_edge(node_id, _figma_id(f"style:{style}"), "uses_token") or {})


def scan_figma(path: str | Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    document = data.get("document") if isinstance(data, Mapping) else None
    if isinstance(document, Mapping):
        _walk(document, nodes, edges, None)
    for style_id, style in sorted((data.get("styles") or {}).items()):
        if not isinstance(style, Mapping):
            continue
        name = str(style.get("name") or style_id)
        kind = TOKEN_KIND.get(str(style.get("styleType", "")).upper(), "color")
        nodes.append(
            make_node(
                _figma_id(f"style:{style_id}"),
                "token",
                name,
                summary=f"design token {name}",
                tags=["figma", "token", kind],
                figmaMeta={"tokenKind": kind, "tokenValue": name},
            )
        )
    project = {
        "name": str(data.get("name") or source.stem),
        "languages": ["figma"],
        "frameworks": [],
        "description": "Figma design graph",
        "analyzedAt": project_meta(source.parent, [])["analyzedAt"],
        "gitCommitHash": "",
    }
    graph, issues = merge_fragments([{"nodes": nodes, "edges": edges}], project, kind="design")
    return normalize_graph(graph), issues

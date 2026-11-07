#!/usr/bin/env python3
"""Derived document-link graph over vault pages.

The graph is a projection. It is built from pages the caller already holds and
never written back into the vault, never read from another vault and never
treated as authority. Unresolved links are reported, never guessed.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

GRAPH_SCHEMA = "sparknet-graph/1"
NODE_SCHEMA = "sparknet-graph-node/1"
EDGE_SCHEMA = "sparknet-graph-edge/1"
EDGE_KINDS = ("wikilink", "frontmatter", "manual")
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
VAULT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


class GraphError(Exception):
    """A fail-closed graph refusal."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise GraphError(code, message)


def _nonempty(value: Any, field: str, code: str = "malformed-page") -> str:
    _require(isinstance(value, str) and bool(value.strip()), code, f"{field} must be a non-empty string")
    return value.strip()


def normalize_path(path: Any) -> str:
    _require(isinstance(path, str) and bool(path.strip()), "bad-path", "path must be a non-empty string")
    _require("\\" not in path, "bad-path", "path contains a backslash")
    candidate = PurePosixPath(path.strip())
    _require(
        not candidate.is_absolute() and not any(part in ("..", "") for part in candidate.parts),
        "bad-path",
        "path escapes its vault",
    )
    return candidate.as_posix()


def extract_wikilinks(text: Any) -> list[str]:
    """Targets from `[[target]]`, `[[target#anchor]]` and `[[target|alias]]`."""
    if not isinstance(text, str):
        return []
    return sorted({match.group(1).strip() for match in WIKILINK_RE.finditer(text) if match.group(1).strip()})


def _page(page: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(page, Mapping), "malformed-page", "page must be an object")
    path = normalize_path(page.get("path"))
    vault_id = _nonempty(page.get("vault_id"), "vault_id", "bad-vault")
    _require(bool(VAULT_ID_RE.fullmatch(vault_id)), "bad-vault", "vault_id has the wrong shape")
    classification = page.get("classification")
    _require(
        isinstance(classification, str) and classification in CLASSIFICATIONS,
        "malformed-page",
        "classification is required and must be in the closed vocabulary",
    )
    tags = page.get("tags", [])
    _require(
        isinstance(tags, (list, tuple)) and all(isinstance(tag, str) for tag in tags),
        "malformed-page",
        "tags must be a list of strings",
    )
    department = page.get("department")
    _require(department is None or isinstance(department, str), "malformed-page", "department must be a string or null")
    category = page.get("category") or PurePosixPath(path).parent.as_posix()
    title = page.get("title") or PurePosixPath(path).stem
    return {
        "id": f"{vault_id}:{path}",
        "path": path,
        "title": str(title),
        "category": str(category),
        "tags": sorted(set(tags)),
        "classification": classification,
        "department": department.strip() if isinstance(department, str) and department.strip() else None,
        "vault_id": vault_id,
    }


def _links(page: Mapping[str, Any]) -> list[tuple[str, str]]:
    explicit = page.get("links")
    if isinstance(explicit, (list, tuple)):
        links = []
        for item in explicit:
            if isinstance(item, str):
                links.append((item, "wikilink"))
            elif isinstance(item, Mapping):
                links.append((str(item.get("target") or ""), str(item.get("kind") or "wikilink")))
        return [(target, kind) for target, kind in links if target.strip()]
    text = page.get("text") or page.get("markdown") or ""
    return [(target, "wikilink") for target in extract_wikilinks(text)]


def build_graph(pages: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a deterministic graph; no cross-vault edge is ever created."""
    pages = list(pages)
    nodes = [_page(page) for page in pages]
    ids = [node["id"] for node in nodes]
    _require(len(ids) == len(set(ids)), "duplicate-node", "duplicate node id in the corpus")
    known_vaults = {node["vault_id"] for node in nodes}
    by_path = {(node["vault_id"], node["path"]): node["id"] for node in nodes}
    titles: dict[tuple[str, str], str] = {}
    duplicates: set[tuple[str, str]] = set()
    for node in nodes:
        key = (node["vault_id"], node["title"])
        if key in titles:
            duplicates.add(key)
        else:
            titles[key] = node["id"]
    edges = []
    unresolved = []
    for page in pages:
        source = _page(page)
        for literal, kind in _links(page):
            _require(kind in EDGE_KINDS, "malformed-page", f"unknown edge kind {kind!r}")
            target = literal.strip()
            vault_id = source["vault_id"]
            if ":" in target and not target.startswith("/"):
                prefix, rest = target.split(":", 1)
                if prefix in known_vaults and prefix != vault_id:
                    unresolved.append({"source": source["id"], "target": target, "reason": "cross-vault-edge"})
                    continue
                if prefix == vault_id:
                    target = rest
            try:
                target_path = normalize_path(target)
            except GraphError:
                unresolved.append({"source": source["id"], "target": target, "reason": "bad-path"})
                continue
            resolved = by_path.get((vault_id, target_path))
            if resolved is None and not target_path.endswith(".md"):
                resolved = by_path.get((vault_id, target_path + ".md"))
            if resolved is None:
                title_key = (vault_id, target_path)
                if title_key not in duplicates:
                    resolved = titles.get(title_key)
            if resolved is None:
                unresolved.append({"source": source["id"], "target": target, "reason": "unresolved"})
                continue
            edges.append(
                {
                    "source": source["id"],
                    "target": resolved,
                    "kind": kind,
                    "provenance": {"source": source["path"], "target": literal},
                }
            )
    nodes.sort(key=lambda node: node["id"])
    edges.sort(key=lambda edge: (edge["source"], edge["target"], edge["kind"]))
    unresolved.sort(key=lambda row: (row["source"], row["target"], row["reason"]))
    return {"schema_version": GRAPH_SCHEMA, "nodes": nodes, "edges": edges, "unresolved": unresolved}


def neighbors(graph: Mapping[str, Any], node_id: str, direction: str = "both") -> list[str]:
    _require(direction in ("in", "out", "both"), "bad-direction", "direction must be in, out or both")
    nodes = graph.get("nodes")
    _require(
        isinstance(nodes, list) and any(node.get("id") == node_id for node in nodes if isinstance(node, Mapping)),
        "unknown-node",
        "node is not in the graph",
    )
    edges = graph.get("edges")
    _require(isinstance(edges, list), "malformed-page", "graph has no edges")
    found = set()
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        if direction in ("out", "both") and edge.get("source") == node_id and isinstance(edge.get("target"), str):
            found.add(edge["target"])
        if direction in ("in", "both") and edge.get("target") == node_id and isinstance(edge.get("source"), str):
            found.add(edge["source"])
    return sorted(found)


def shortest_path(graph: Mapping[str, Any], source: str, target: str) -> list[str] | None:
    if source == target:
        return [source]
    adjacency: dict[str, list[str]] = {}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, Mapping):
            continue
        left, right = edge.get("source"), edge.get("target")
        if isinstance(left, str) and isinstance(right, str):
            adjacency.setdefault(left, []).append(right)
            adjacency.setdefault(right, []).append(left)
    queue = deque([(source, [source])])
    seen = {source}
    while queue:
        current, path = queue.popleft()
        for neighbour in sorted(adjacency.get(current, [])):
            if neighbour in seen:
                continue
            if neighbour == target:
                return [*path, neighbour]
            seen.add(neighbour)
            queue.append((neighbour, [*path, neighbour]))
    return None


def to_json(graph: Mapping[str, Any]) -> str:
    return json.dumps(graph, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)

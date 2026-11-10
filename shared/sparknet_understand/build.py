#!/usr/bin/env python3
"""Build a graph from a tree or from fragments produced by the Go service."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .algebra import merge_fragments, normalize_graph
from .extractors import extract, link_tests
from .production import project_meta, scan


def build_graph(
    root: str | Path,
    *,
    excludes: Iterable[str] = (),
    analyzed_at: str | None = None,
    description: str = "",
    kind: str = "codebase",
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Scan a tree, extract every file and merge one graph."""
    root_path = Path(root).resolve()
    if kind == "knowledge":
        from .knowledge import build_knowledge_graph

        return build_knowledge_graph(root_path, excludes=excludes, analyzed_at=analyzed_at)
    result = scan(root_path, excludes=excludes)
    fragments: list[dict[str, Any]] = []
    for record in result.files:
        path = root_path / record.path
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fragments.append(extract(record, text))
    project = project_meta(root_path, result.files, analyzed_at=analyzed_at, description=description)
    graph, issues = merge_fragments(fragments, project, kind=kind)
    link_tests(graph["nodes"], graph["edges"])
    graph = normalize_graph(graph)
    for error in result.errors:
        issues.append(
            {
                "level": "dropped",
                "category": "file",
                "message": f"{error['path']}: {error['reason']}",
            }
        )
    return graph, issues


def build_from_fragments(
    fragments: Iterable[Mapping[str, Any]],
    project: Mapping[str, Any],
    *,
    kind: str = "codebase",
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Merge fragments supplied by the Go service; no file is read here."""
    graph, issues = merge_fragments(fragments, project, kind=kind)
    link_tests(graph["nodes"], graph["edges"])
    return normalize_graph(graph), issues

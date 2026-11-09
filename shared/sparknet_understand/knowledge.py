#!/usr/bin/env python3
"""Karpathy-pattern wiki analysis for ``/understand-knowledge``.

The deterministic scan is the floor: articles, sources, topics, wikilinks and
index categories. An LLM analyzer may add implicit edges later; this module
never invents one. Article content is data and is carried only in
``knowledgeMeta.content`` for an analyzer to read, never executed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .core import (
    FileRecord,
    make_edge,
    make_node,
    merge_fragments,
    normalize_graph,
    project_meta,
    scan,
)

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled"


def _frontmatter(text: str) -> dict[str, Any]:
    from .extractors import _parse_yaml

    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            return _parse_yaml(text[3:end])
    return {}


def _content_without_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            return text[end + 4 :]
    return text


def _index_categories(text: str) -> list[tuple[str, str]]:
    """Return (heading, category slug) pairs from an index file."""
    categories: list[tuple[str, str]] = []
    for match in HEADING_RE.finditer(text):
        heading = match.group(2).strip()
        if heading.lower() in {"index", "contents", "table of contents"}:
            continue
        categories.append((heading, _slug(heading)))
    return categories


def parse_knowledge_base(root: str | Path, *, excludes: Iterable[str] = ()) -> dict[str, Any]:
    root_path = Path(root).resolve()
    result = scan(root_path, excludes=excludes)
    markdown = [record for record in result.files if record.language == "markdown"]
    index = next((record for record in markdown if PurePosixPath(record.path).name.lower() == "index.md"), None)
    categories = _index_categories(_read(root_path, index.path)) if index else []
    articles: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for record in markdown:
        name = PurePosixPath(record.path).name.lower()
        if name in {"index.md", "log.md"}:
            continue
        text = _read(root_path, record.path)
        meta = _frontmatter(text)
        links = sorted({match.group(1).strip() for match in WIKILINK_RE.finditer(text)})
        category = meta.get("category")
        if not category:
            for _heading, slug in categories:
                if slug in record.path.lower().split("/"):
                    category = slug
                    break
        is_source = any(part in record.path for part in ("/raw/", "_raw/", "03_Sources/", "references/"))
        entry = {
            "id": f"article:{record.path}",
            "path": record.path,
            "name": str(meta.get("title") or PurePosixPath(record.path).stem),
            "summary": str(meta.get("description") or _first_heading(text) or f"article {record.path}"),
            "category": str(category) if category else "",
            "wikilinks": links,
            "headings": [match.group(2).strip() for match in HEADING_RE.finditer(text)],
            "content": _content_without_frontmatter(text)[:20000],
        }
        if is_source:
            sources.append(entry)
        else:
            articles.append(entry)
    category_names = {heading: slug for heading, slug in categories}
    for article in articles:
        if article["category"] and article["category"] not in category_names.values():
            category_names[article["category"]] = article["category"]
    topics = [
        {"id": f"topic:{slug}", "name": heading, "slug": slug} for heading, slug in sorted(category_names.items())
    ]
    article_ids = {article["id"] for article in articles}
    article_names = {article["name"].lower(): article["id"] for article in articles}
    unresolved: list[dict[str, str]] = []
    stubs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for article in articles:
        for link in article["wikilinks"]:
            target = f"article:{_slug(link)}"
            if target not in article_ids:
                target = article_names.get(link.strip().lower(), target)
            if target not in article_ids:
                unresolved.append({"source": article["id"], "target": link})
                article_ids.add(target)
                stubs.append(
                    {
                        "id": target,
                        "path": "",
                        "name": link,
                        "summary": f"unresolved wikilink {link}",
                        "category": "",
                        "wikilinks": [],
                        "headings": [],
                        "content": "",
                    }
                )
            edges.append(make_edge(article["id"], target, "related", description="wikilink") or {})
        if article["category"]:
            edges.append(make_edge(article["id"], f"topic:{article['category']}", "categorized_under") or {})
        for source in sources:
            if source["name"].lower() in article["content"].lower():
                edges.append(make_edge(article["id"], source["id"], "cites") or {})
    articles.extend(stubs)
    return {
        "root": str(root_path),
        "articles": articles,
        "sources": sources,
        "topics": topics,
        "edges": [edge for edge in edges if edge],
        "unresolved": unresolved,
        "languages": result.languages,
        "errors": result.errors,
    }


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _first_heading(text: str) -> str:
    match = HEADING_RE.search(text)
    return match.group(2).strip() if match else ""


def build_knowledge_graph(
    root: str | Path,
    *,
    excludes: Iterable[str] = (),
    analyzed_at: str | None = None,
    analyses: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    root_path = Path(root).resolve()
    manifest = parse_knowledge_base(root_path, excludes=excludes)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = list(manifest["edges"])
    for article in manifest["articles"]:
        nodes.append(
            make_node(
                article["id"],
                "article",
                article["name"],
                summary=article["summary"],
                tags=["article", *([article["category"]] if article["category"] else [])],
                file_path=article["path"],
                knowledgeMeta={
                    "wikilinks": article["wikilinks"],
                    "category": article["category"],
                    "content": article["content"],
                },
            )
        )
    for source in manifest["sources"]:
        nodes.append(
            make_node(
                source["id"],
                "source",
                source["name"],
                summary=source["summary"],
                tags=["source"],
                file_path=source["path"],
                knowledgeMeta={"content": source["content"]},
            )
        )
    for topic in manifest["topics"]:
        nodes.append(make_node(topic["id"], "topic", topic["name"], summary=f"topic {topic['name']}", tags=["topic"]))
    for analysis in analyses:
        for raw in analysis.get("nodes", []) or []:
            nodes.append(raw)
        for raw in analysis.get("edges", []) or []:
            edges.append(raw)
    records = [
        FileRecord(path=item["path"], language="markdown", sha256="", size=0, mtime_ns=0)
        for item in manifest["articles"]
    ]
    project = project_meta(root_path, records, analyzed_at=analyzed_at, description="Knowledge graph")
    graph, issues = merge_fragments([{"nodes": nodes, "edges": edges}], project, kind="knowledge")
    return normalize_graph(graph), issues

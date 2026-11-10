#!/usr/bin/env python3
"""Schema, vocabulary, canonicalisation, IDs and graph constructors.

The contract is ``contracts/understand-schema.json``; this module reads it and
never restates the vocabulary. It is the producer's schema seam.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


SCHEMA_PATH = REPO_ROOT / "contracts" / "understand-schema.json"


DATA_DIR = ".ua"


LEGACY_DATA_DIR = ".understand-anything"


GRAPH_FILE = "knowledge-graph.json"


CONFIG_FILE = "config.json"


FINGERPRINT_FILE = "fingerprints.json"


def load_schema() -> dict[str, Any]:
    """Read the one contract; never carry a private vocabulary."""
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    return load_schema()


@lru_cache(maxsize=1)
def _node_types() -> frozenset[str]:
    return frozenset(_schema()["node_types"])


@lru_cache(maxsize=1)
def _edge_families() -> dict[str, list[str]]:
    families = _schema()["edge_types"]
    return {name: list(values) for name, values in families.items() if isinstance(values, list)}


@lru_cache(maxsize=1)
def _edge_types() -> frozenset[str]:
    return frozenset(edge for values in _edge_families().values() for edge in values)


@lru_cache(maxsize=1)
def _node_aliases() -> dict[str, str]:
    return dict(_schema()["node_type_aliases"])


@lru_cache(maxsize=1)
def _edge_aliases() -> dict[str, str]:
    aliases = dict(_schema()["edge_type_aliases"])
    aliases.update(_schema().get("non_design_edge_type_aliases", {}))
    return aliases


@lru_cache(maxsize=1)
def _complexity_aliases() -> dict[str, str]:
    return dict(_schema()["value_aliases"]["complexity"])


@lru_cache(maxsize=1)
def _direction_aliases() -> dict[str, str]:
    return dict(_schema()["value_aliases"]["direction"])


def canonical_node_type(value: Any) -> str:
    if not isinstance(value, str):
        return "file"
    value = value.strip()
    lowered = value.lower()
    mapped = _node_aliases().get(lowered, lowered)
    return mapped if mapped in _node_types() else "file"


def canonical_edge_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    mapped = _edge_aliases().get(lowered, lowered)
    return mapped if mapped in _edge_types() else None


def canonical_complexity(value: Any) -> str:
    if not isinstance(value, str):
        return "moderate"
    lowered = value.strip().lower()
    mapped = _complexity_aliases().get(lowered, lowered)
    return mapped if mapped in {"simple", "moderate", "complex"} else "moderate"


def canonical_direction(value: Any) -> str:
    if not isinstance(value, str):
        return "forward"
    lowered = value.strip().lower()
    mapped = _direction_aliases().get(lowered, lowered)
    return mapped if mapped in {"forward", "backward", "bidirectional"} else "forward"


def file_id(rel_path: str) -> str:
    return f"file:{rel_path}"


def module_id(name: str) -> str:
    return f"module:{name}"


def symbol_id(rel_path: str, kind: str, name: str, line: int) -> str:
    return f"{kind}:{rel_path}:{name}:{line}"


def config_id(rel_path: str, key: str) -> str:
    return f"config:{rel_path}:{key}"


def document_id(rel_path: str) -> str:
    return f"document:{rel_path}"


def make_node(
    node_id: str,
    node_type: str,
    name: str,
    *,
    summary: str = "",
    tags: Iterable[str] = (),
    complexity: str = "moderate",
    file_path: str | None = None,
    line_range: tuple[int, int] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": node_id,
        "type": canonical_node_type(node_type),
        "name": str(name),
        "summary": str(summary or name),
        "tags": sorted({str(tag) for tag in tags if str(tag).strip()}),
        "complexity": canonical_complexity(complexity),
    }
    if file_path:
        node["filePath"] = file_path
    if line_range:
        node["lineRange"] = [int(line_range[0]), int(line_range[1])]
    node.update({key: value for key, value in extra.items() if value is not None})
    return node


def make_edge(
    source: str,
    target: str,
    edge_type: str,
    *,
    description: str = "",
    weight: float = 0.5,
    direction: str = "forward",
) -> dict[str, Any] | None:
    canonical = canonical_edge_type(edge_type)
    if canonical is None:
        return None
    try:
        value = max(0.0, min(1.0, float(weight)))
    except (TypeError, ValueError):
        value = 0.5
    edge: dict[str, Any] = {
        "source": source,
        "target": target,
        "type": canonical,
        "direction": canonical_direction(direction),
        "weight": value,
    }
    if description:
        edge["description"] = str(description)
    return edge

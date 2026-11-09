#!/usr/bin/env python3
"""Schema, scan, merge and validation for the Understand-Anything graph.

The graph is a **derived build artifact**. It is regenerable, gitignored and
never knowledge: a user's AI may read it to understand code, not to answer from
it. The contract is ``contracts/understand-schema.json``; this module never
restates node or edge vocabularies, it reads them.

The walker is deliberately dependency-free. The repo's runtime allow-list is
``cryptography`` only, so the extractors live in ``extractors.py`` and use the
standard library. ``tree_sitter`` is an optional extra, imported lazily when it
is available; without it the native and generic extractors still produce a
graph.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "understand-schema.json"

DATA_DIR = ".ua"
LEGACY_DATA_DIR = ".understand-anything"
GRAPH_FILE = "knowledge-graph.json"
CONFIG_FILE = "config.json"
FINGERPRINT_FILE = "fingerprints.json"
IGNORE_FILE = ".understandignore"

MAX_FILE_BYTES = 2_000_000

DEFAULT_EXCLUDES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".ua",
        ".understand-anything",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".state",
        ".cache",
        ".obsidian",
        "dist",
        "build",
        "target",
        "coverage",
        "htmlcov",
        "vendor",
        "third_party",
        "_staging",
        "_archives",
        "references",
    }
)

LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".go": "go",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".jsonc": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".cs": "csharp",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".scala": "scala",
    ".dart": "dart",
    ".lua": "lua",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".csv": "csv",
    ".txt": "plaintext",
}

LANGUAGE_BY_NAME: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "dockerfile": "dockerfile",
    "Makefile": "makefile",
    "makefile": "makefile",
    "GNUmakefile": "makefile",
    "Jenkinsfile": "jenkinsfile",
}

TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)|(^|/)test_[^/]+$|_test\.[A-Za-z0-9]+$|\.test\.[A-Za-z0-9]+$|\.spec\.[A-Za-z0-9]+$"
)


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


def is_test_path(rel_path: str) -> bool:
    return bool(TEST_PATH_RE.search(rel_path))


def language_for(rel_path: str) -> str | None:
    name = PurePosixPath(rel_path).name
    if name in LANGUAGE_BY_NAME:
        return LANGUAGE_BY_NAME[name]
    if name.startswith(".env"):
        return "env"
    if "/.github/workflows/" in f"/{rel_path}" and name.endswith((".yml", ".yaml")):
        return "github-actions"
    if name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
        return "docker-compose"
    return LANGUAGE_BY_SUFFIX.get(PurePosixPath(rel_path).suffix.lower())


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class FileRecord:
    path: str
    language: str
    sha256: str
    size: int
    mtime_ns: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "sha256": self.sha256,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
        }


@dataclass
class ScanResult:
    root: str
    files: list[FileRecord] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def languages(self) -> list[str]:
        return sorted({record.language for record in self.files})

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": [record.as_dict() for record in self.files],
            "languages": self.languages,
            "errors": self.errors,
        }


def read_ignore(root: Path) -> list[str]:
    path = root / IGNORE_FILE
    if not path.is_file():
        return []
    patterns: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _matches_any(rel_path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        candidate = pattern.lstrip("/")
        if fnmatch.fnmatch(rel_path, candidate) or fnmatch.fnmatch(PurePosixPath(rel_path).name, candidate):
            return True
        if candidate.endswith("/") and rel_path.startswith(candidate.rstrip("/") + "/"):
            return True
    return False


def is_ignored(rel_path: str, patterns: Iterable[str]) -> bool:
    """Apply gitignore-style positive/negative patterns; last match wins."""
    if not patterns:
        return False
    ignored = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        candidate = pattern[1:] if negated else pattern
        if _matches_any(rel_path, [candidate]):
            ignored = not negated
    return ignored


def scan(
    root: str | Path,
    *,
    excludes: Iterable[str] = (),
    max_bytes: int = MAX_FILE_BYTES,
) -> ScanResult:
    """Walk a tree deterministically and fingerprint every supported file."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(f"not a directory: {root_path}")
    ignore = [*DEFAULT_EXCLUDES, *read_ignore(root_path), *excludes]
    result = ScanResult(root=str(root_path))
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        current = Path(dirpath)
        rel_dir = current.relative_to(root_path).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in DEFAULT_EXCLUDES and not is_ignored(f"{rel_dir}/{name}".lstrip("/"), ignore)
        )
        for filename in sorted(filenames):
            rel = f"{rel_dir}/{filename}".lstrip("/")
            if is_ignored(rel, ignore):
                continue
            language = language_for(rel)
            if language is None:
                continue
            path = current / filename
            try:
                stat = path.stat()
                if stat.st_size > max_bytes:
                    result.errors.append({"path": rel, "reason": "too-large"})
                    continue
                data = path.read_bytes()
            except OSError as exc:
                result.errors.append({"path": rel, "reason": f"unreadable: {exc.__class__.__name__}"})
                continue
            if _is_binary(data[:4096]):
                result.errors.append({"path": rel, "reason": "binary"})
                continue
            result.files.append(
                FileRecord(
                    path=rel,
                    language=language,
                    sha256=_sha256(data),
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                )
            )
    result.files.sort(key=lambda record: record.path)
    return result


def git_commit(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    commit = proc.stdout.strip()
    return commit if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", commit) else ""


def _git_time(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cI"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else ""


def default_analyzed_at(root: str | Path) -> str:
    """Prefer a stable timestamp so an unchanged tree yields the same graph."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), tz=UTC).isoformat().replace("+00:00", "Z")
    commit_time = _git_time(Path(root))
    if commit_time:
        return commit_time
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


FRAMEWORK_SIGNALS: dict[str, tuple[str, ...]] = {
    "django": ("django", "manage.py"),
    "fastapi": ("fastapi",),
    "flask": ("flask",),
    "express": ("express",),
    "gin": ("gin-gonic/gin",),
    "nextjs": ("next",),
    "rails": ("rails",),
    "react": ("react",),
    "spring": ("spring",),
    "vue": ("vue",),
}


def detect_frameworks(root: Path, records: Iterable[FileRecord]) -> list[str]:
    """Detect frameworks from manifest files, not from guesses about code."""
    found: set[str] = set()
    paths = {record.path for record in records}
    if "manage.py" in paths:
        found.add("django")
    for manifest in ("requirements.txt", "pyproject.toml", "package.json", "go.mod", "Gemfile"):
        if manifest not in paths:
            continue
        try:
            text = (root / manifest).read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        for framework, signals in FRAMEWORK_SIGNALS.items():
            if any(signal in text for signal in signals):
                found.add(framework)
    return sorted(found)


def project_meta(
    root: Path,
    records: Iterable[FileRecord],
    *,
    analyzed_at: str | None = None,
    description: str = "",
) -> dict[str, Any]:
    records = list(records)
    return {
        "name": root.name or "project",
        "languages": sorted({record.language for record in records}),
        "frameworks": detect_frameworks(root, records),
        "description": description or f"Code-understanding graph for {root.name or 'this project'}",
        "analyzedAt": analyzed_at or default_analyzed_at(root),
        "gitCommitHash": git_commit(root),
    }


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

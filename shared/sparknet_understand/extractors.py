#!/usr/bin/env python3
"""Per-language extractors for the Understand-Anything graph.

Each extractor turns one file into a fragment of nodes and edges. The graph
vocabulary is not restated here: ``make_node`` and ``make_edge`` canonicalise
against ``contracts/understand-schema.json``.

Native-first is deliberate. Python uses ``ast``; shell, markdown, JSON, YAML,
TOML and the config formats use the standard library or the fabric's YAML
subset. A tree-sitter path is available when the optional dependency is
installed, but it never replaces the native extractor for Python. When no
specialised extractor exists, the generic extractor still records the file and
the symbol-shaped lines it can prove; it never guesses an edge.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Iterable
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any

import tomllib

from .core import (
    REPO_ROOT,
    FileRecord,
    config_id,
    document_id,
    file_id,
    is_test_path,
    make_edge,
    make_node,
    module_id,
    symbol_id,
)

sys.path.insert(0, str(REPO_ROOT / "shared"))
from sparknet_loader import load_shared

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@lru_cache(maxsize=1)
def _yaml_parse() -> Any:
    """Load the fabric's YAML subset through the one loader; no third-party YAML dependency."""
    module = load_shared(
        "sparknet-yaml.py",
        "sparknet_yaml_for_understand",
        dirs=[REPO_ROOT / "shared"],
        missing_ok=True,
    )
    return getattr(module, "parse_yaml_subset", None) if module is not None else None


def _parse_yaml(text: str) -> dict[str, Any]:
    parser = _yaml_parse()
    if parser is None:
        return {}
    try:
        value = parser(text)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled"


def _first_line(text: str | None, limit: int = 240) -> str:
    if not text:
        return ""
    line = " ".join(text.strip().split())
    return line[:limit]


class Builder:
    """A per-file fragment that never emits a duplicate node id."""

    def __init__(self, record: FileRecord, *, node_type: str = "file") -> None:
        self.record = record
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.seen: set[str] = set()
        self.file_node = self.node(
            file_id(record.path),
            node_type,
            PurePosixPath(record.path).name,
            summary=f"{record.language} file {record.path}",
            tags=[record.language],
            file_path=record.path,
        )

    def node(self, node_id: str, node_type: str, name: str, **kwargs: Any) -> dict[str, Any]:
        if node_id in self.seen:
            return next(node for node in self.nodes if node["id"] == node_id)
        node = make_node(node_id, node_type, name, **kwargs)
        self.nodes.append(node)
        self.seen.add(node_id)
        return node

    def edge(self, source: str, target: str, edge_type: str, **kwargs: Any) -> None:
        edge = make_edge(source, target, edge_type, **kwargs)
        if edge is not None:
            self.edges.append(edge)

    def fragment(self) -> dict[str, Any]:
        return {"nodes": self.nodes, "edges": self.edges}


def _brace_end(text: str, start: int) -> int:
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def _body_after(text: str, offset: int) -> str:
    start = text.find("{", offset)
    if start < 0:
        return ""
    return text[start : _brace_end(text, start)]


# --- Python -------------------------------------------------------------------


def _python_complexity(node: ast.AST) -> str:
    branches = sum(
        isinstance(
            child,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.With,
                ast.AsyncWith,
                ast.BoolOp,
                ast.IfExp,
                ast.Match,
            ),
        )
        for child in ast.walk(node)
    )
    if branches <= 2:
        return "simple"
    if branches <= 8:
        return "moderate"
    return "complex"


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def extract_python(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    try:
        tree = ast.parse(text, filename=record.path)
    except SyntaxError as exc:
        builder.file_node["summary"] = f"unparsable Python file: {exc.msg}"
        builder.file_node["tags"] = sorted(set(builder.file_node["tags"]) | {"unparsable"})
        return builder.fragment()

    functions: dict[str, str] = {}
    classes: dict[str, str] = {}
    methods: dict[tuple[str, str], str] = {}

    def collect(node: ast.AST, parent_class: str | None = None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                node_id = symbol_id(record.path, "class", child.name, child.lineno)
                classes[child.name] = node_id
                for item in child.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods[(child.name, item.name)] = symbol_id(
                            record.path, "function", f"{child.name}.{item.name}", item.lineno
                        )
                    elif isinstance(child, ast.ClassDef):
                        pass
                collect(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if parent_class is None:
                    functions[child.name] = symbol_id(record.path, "function", child.name, child.lineno)
                collect(child, parent_class)
            else:
                collect(child, parent_class)

    collect(tree)

    module_doc = ast.get_docstring(tree)
    if module_doc:
        builder.file_node["summary"] = _first_line(module_doc)

    def add_def(node: ast.AST, parent_class: str | None = None) -> None:
        if isinstance(node, ast.ClassDef):
            node_id = classes[node.name]
            builder.node(
                node_id,
                "class",
                node.name,
                summary=_first_line(ast.get_docstring(node)) or f"class {node.name}",
                tags=["python", "class"],
                complexity=_python_complexity(node),
                file_path=record.path,
                line_range=(node.lineno, getattr(node, "end_lineno", node.lineno)),
            )
            builder.edge(builder.file_node["id"], node_id, "contains")
            for base in node.bases:
                base_name = _dotted(base)
                if not base_name:
                    continue
                target = classes.get(base_name) or f"class:{base_name.split('.')[-1]}"
                if target not in builder.seen:
                    builder.node(
                        target,
                        "class",
                        base_name.split(".")[-1],
                        summary=f"external base class {base_name}",
                        tags=["external"],
                    )
                builder.edge(node_id, target, "inherits")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    add_def(item, node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if parent_class is None:
                node_id = functions[node.name]
                name = node.name
            else:
                node_id = methods.get((parent_class, node.name)) or symbol_id(
                    record.path, "function", f"{parent_class}.{node.name}", node.lineno
                )
                name = f"{parent_class}.{node.name}"
            builder.node(
                node_id,
                "function",
                name,
                summary=_first_line(ast.get_docstring(node)) or f"function {name}",
                tags=["python", "function"],
                complexity=_python_complexity(node),
                file_path=record.path,
                line_range=(node.lineno, getattr(node, "end_lineno", node.lineno)),
            )
            builder.edge(
                builder.file_node["id"] if parent_class is None else classes[parent_class], node_id, "contains"
            )
            self_class = parent_class or ""
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                called = _dotted(child.func)
                target = None
                if called.startswith("self.") and self_class:
                    target = methods.get((self_class, called.split(".")[-1]))
                elif called in functions:
                    target = functions[called]
                elif called in classes:
                    target = classes[called]
                elif "." in called:
                    tail = called.split(".")[-1]
                    target = functions.get(tail) or classes.get(tail)
                if target and target != node_id:
                    builder.edge(node_id, target, "calls")

    for item in tree.body:
        if isinstance(item, (ast.Import, ast.ImportFrom)):
            if isinstance(item, ast.Import):
                names = [alias.name for alias in item.names]
            else:
                module = "." * item.level + (item.module or "")
                names = [module] if module else [alias.name for alias in item.names]
            for name in names:
                if not name:
                    continue
                target = module_id(name)
                builder.node(target, "module", name, summary=f"imported module {name}", tags=["python", "module"])
                builder.edge(builder.file_node["id"], target, "imports")
        elif isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            add_def(item)

    assigned_exports: list[str] = []
    for item in tree.body:
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__all__"
                    and isinstance(item.value, (ast.List, ast.Tuple))
                ):
                    assigned_exports = [
                        elt.value
                        for elt in item.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
    for name in assigned_exports:
        target = functions.get(name) or classes.get(name)
        if target:
            builder.edge(builder.file_node["id"], target, "exports")

    return builder.fragment()


# --- Go -----------------------------------------------------------------------


GO_KEYWORDS = {
    "if",
    "for",
    "range",
    "switch",
    "select",
    "return",
    "func",
    "defer",
    "go",
    "chan",
    "make",
    "new",
    "append",
    "len",
    "cap",
    "copy",
    "delete",
    "panic",
    "recover",
    "print",
    "println",
}


def extract_go(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    package = re.search(r"(?m)^\s*package\s+([A-Za-z_]\w*)", text)
    if package:
        target = module_id(package.group(1))
        builder.node(
            target, "module", package.group(1), summary=f"Go package {package.group(1)}", tags=["go", "package"]
        )
        builder.edge(builder.file_node["id"], target, "contains")

    for match in re.finditer(r'(?m)^\s*(?:import\s+)?\(?\s*"([^"]+)"', text):
        name = match.group(1)
        target = module_id(name)
        builder.node(target, "module", name, summary=f"Go import {name}", tags=["go", "import"])
        builder.edge(builder.file_node["id"], target, "imports")

    classes: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\s*type\s+([A-Za-z_]\w*)\s+(struct|interface)\b", text):
        name = match.group(1)
        node_id = symbol_id(record.path, "class", name, text.count("\n", 0, match.start()) + 1)
        classes[name] = node_id
        builder.node(
            node_id,
            "class",
            name,
            summary=f"Go {match.group(2)} {name}",
            tags=["go", match.group(2)],
            file_path=record.path,
            line_range=(text.count("\n", 0, match.start()) + 1, text.count("\n", 0, _brace_end(text, match.end())) + 1),
        )
        builder.edge(builder.file_node["id"], node_id, "contains")
        body = _body_after(text, match.end())
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("//") or ":" in line or line.startswith("}"):
                continue
            embedded = re.match(r"^([A-Za-z_]\w*)$", line)
            if embedded and embedded.group(1) in classes:
                builder.edge(node_id, classes[embedded.group(1)], "inherits")

    functions: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\s*func\s+(?:\(([^)]*)\)\s*)?([A-Za-z_]\w*)\s*\(", text):
        receiver = match.group(1) or ""
        name = match.group(2)
        receiver_type = re.search(r"\*?([A-Za-z_]\w*)\s*$", receiver)
        parent = classes.get(receiver_type.group(1)) if receiver_type else None
        node_id = symbol_id(
            record.path,
            "function",
            f"{receiver_type.group(1)}.{name}" if receiver_type else name,
            text.count("\n", 0, match.start()) + 1,
        )
        functions[name] = node_id
        builder.node(
            node_id,
            "function",
            f"{receiver_type.group(1)}.{name}" if receiver_type else name,
            summary=f"Go function {name}",
            tags=["go", "function"],
            file_path=record.path,
            line_range=(text.count("\n", 0, match.start()) + 1, text.count("\n", 0, _brace_end(text, match.end())) + 1),
        )
        builder.edge(parent or builder.file_node["id"], node_id, "contains")
        body = _body_after(text, match.end())
        if "http.ResponseWriter" in text[match.start() : match.end() + 200] or name.startswith("Handle"):
            endpoint_id = f"endpoint:{record.path}:{name}"
            builder.node(
                endpoint_id,
                "endpoint",
                name,
                summary=f"HTTP handler {name}",
                tags=["go", "http"],
                file_path=record.path,
            )
            builder.edge(node_id, endpoint_id, "serves")
        for call in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", body):
            called = call.group(1)
            if called in GO_KEYWORDS or called == name:
                continue
            target = functions.get(called)
            if target:
                builder.edge(node_id, target, "calls")

    for match in re.finditer(r"(?m)^\s*(?:const|var)\s+([A-Za-z_]\w*)", text):
        name = match.group(1)
        node_id = config_id(record.path, name)
        builder.node(node_id, "config", name, summary=f"Go {name}", tags=["go", "config"], file_path=record.path)
        builder.edge(builder.file_node["id"], node_id, "configures")

    return builder.fragment()


# --- JavaScript / TypeScript --------------------------------------------------


JS_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "function",
    "return",
    "typeof",
    "new",
    "throw",
    "await",
    "yield",
    "import",
    "require",
    "console",
}


def extract_javascript(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    for match in re.finditer(r"""(?m)^\s*import\s+(?:[^'"]+?\s+from\s+)?['"]([^'"]+)['"]""", text):
        name = match.group(1)
        target = module_id(name)
        builder.node(target, "module", name, summary=f"imported module {name}", tags=["js", "module"])
        builder.edge(builder.file_node["id"], target, "imports")
    for match in re.finditer(r"""require\(\s*['"]([^'"]+)['"]\s*\)""", text):
        name = match.group(1)
        target = module_id(name)
        builder.node(target, "module", name, summary=f"required module {name}", tags=["js", "module"])
        builder.edge(builder.file_node["id"], target, "imports")

    classes: dict[str, str] = {}
    functions: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:class|interface)\s+([A-Za-z_$][\w$]*)", text):
        name = match.group(1)
        node_id = symbol_id(record.path, "class", name, text.count("\n", 0, match.start()) + 1)
        classes[name] = node_id
        builder.node(node_id, "class", name, summary=f"class {name}", tags=["js", "class"], file_path=record.path)
        builder.edge(builder.file_node["id"], node_id, "contains")
    for match in re.finditer(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", text):
        name = match.group(1)
        node_id = symbol_id(record.path, "function", name, text.count("\n", 0, match.start()) + 1)
        functions[name] = node_id
        builder.node(
            node_id, "function", name, summary=f"function {name}", tags=["js", "function"], file_path=record.path
        )
        builder.edge(builder.file_node["id"], node_id, "contains")
    for match in re.finditer(
        r"(?m)^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", text
    ):
        name = match.group(1)
        if name in functions:
            continue
        node_id = symbol_id(record.path, "function", name, text.count("\n", 0, match.start()) + 1)
        functions[name] = node_id
        builder.node(
            node_id, "function", name, summary=f"arrow function {name}", tags=["js", "function"], file_path=record.path
        )
        builder.edge(builder.file_node["id"], node_id, "contains")

    for match in re.finditer(
        r"(?m)^\s*export\s+(?:default\s+)?(?:class|function|const|let|var)\s+([A-Za-z_$][\w$]*)", text
    ):
        name = match.group(1)
        target = functions.get(name) or classes.get(name)
        if target:
            builder.edge(builder.file_node["id"], target, "exports")

    for match in re.finditer(r"""(?:app|router|server)\.(get|post|put|patch|delete)\(\s*['"]([^'"]+)['"]""", text):
        route = match.group(2)
        node_id = f"endpoint:{record.path}:{match.group(1)}:{route}"
        builder.node(
            node_id,
            "endpoint",
            route,
            summary=f"{match.group(1).upper()} {route}",
            tags=["http", "route"],
            file_path=record.path,
        )
        builder.edge(builder.file_node["id"], node_id, "routes")

    for match in re.finditer(r"(?m)^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)[^{]*\{", text):
        name = match.group(1)
        body = _body_after(text, match.end() - 1)
        for call in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", body):
            called = call.group(1)
            if called in JS_KEYWORDS or called == name:
                continue
            target = functions.get(called)
            if target:
                builder.edge(functions[name], target, "calls")

    if record.path.endswith("package.json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for name in sorted((data.get(section) or {}).keys()):
                target = module_id(name)
                builder.node(target, "module", name, summary=f"npm dependency {name}", tags=["npm", "dependency"])
                builder.edge(builder.file_node["id"], target, "depends_on")

    return builder.fragment()


# --- shell --------------------------------------------------------------------


SH_EXTERNAL = {
    "python",
    "python3",
    "pip",
    "pip3",
    "make",
    "docker",
    "systemctl",
    "git",
    "go",
    "cargo",
    "npm",
    "node",
    "bash",
    "sh",
}


def extract_shell(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    functions: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\s*(?:function\s+)?([A-Za-z_]\w*)\s*(?:\(\))?\s*\{", text):
        name = match.group(1)
        node_id = symbol_id(record.path, "function", name, text.count("\n", 0, match.start()) + 1)
        functions[name] = node_id
        builder.node(
            node_id,
            "function",
            name,
            summary=f"shell function {name}",
            tags=["shell", "function"],
            file_path=record.path,
        )
        builder.edge(builder.file_node["id"], node_id, "contains")
    for match in re.finditer(r"(?m)^\s*(?:source|\.)\s+([^\s;]+)", text):
        name = match.group(1).strip("'\"")
        target = module_id(name)
        builder.node(target, "module", name, summary=f"sourced file {name}", tags=["shell", "source"])
        builder.edge(builder.file_node["id"], target, "imports")
    for match in re.finditer(r"(?m)^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=([^\n#]*)", text):
        name = match.group(1)
        node_id = config_id(record.path, name)
        builder.node(
            node_id, "config", name, summary=f"shell variable {name}", tags=["shell", "config"], file_path=record.path
        )
        builder.edge(builder.file_node["id"], node_id, "configures")
    for match in re.finditer(r"(?m)^\s*([A-Za-z_][\w-]*)\s+([^\n#|;&]*)", text):
        command = match.group(1)
        if command not in SH_EXTERNAL:
            continue
        target = module_id(command)
        builder.node(target, "module", command, summary=f"external command {command}", tags=["shell", "command"])
        builder.edge(builder.file_node["id"], target, "calls")
        for called in re.finditer(r"\b([A-Za-z_]\w*)\b", match.group(2)):
            name = called.group(1)
            if name in functions:
                builder.edge(builder.file_node["id"], functions[name], "calls")
    return builder.fragment()


# --- markdown -----------------------------------------------------------------


def extract_markdown(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record, node_type="document")
    frontmatter: dict[str, Any] = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            frontmatter = _parse_yaml(text[3:end])
    if frontmatter.get("title"):
        builder.file_node["name"] = str(frontmatter["title"])
    if frontmatter.get("description"):
        builder.file_node["summary"] = _first_line(str(frontmatter["description"]))
    for match in HEADING_RE.finditer(text):
        heading = match.group(2).strip()
        line = text.count("\n", 0, match.start()) + 1
        node_id = f"concept:{record.path}:{_slug(heading)}:{line}"
        builder.node(
            node_id,
            "concept",
            heading,
            summary=f"section {heading}",
            tags=["markdown", "section"],
            file_path=record.path,
            line_range=(line, line),
        )
        builder.edge(builder.file_node["id"], node_id, "contains")
    for match in WIKILINK_RE.finditer(text):
        target_name = match.group(1).strip()
        target = f"article:{_slug(target_name)}"
        builder.node(target, "article", target_name, summary=f"referenced page {target_name}", tags=["wikilink"])
        builder.edge(builder.file_node["id"], target, "related")
    for match in MARKDOWN_LINK_RE.finditer(text):
        target_name = match.group(1).strip()
        if target_name.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = document_id(target_name.lstrip("./"))
        builder.node(target, "document", target_name, summary=f"linked document {target_name}", tags=["link"])
        builder.edge(builder.file_node["id"], target, "documents")
    return builder.fragment()


# --- config formats -----------------------------------------------------------


def _add_keys(builder: Builder, mapping: dict[str, Any], language: str, prefix: str = "") -> None:
    for key in sorted(mapping):
        if not isinstance(key, str) or not key:
            continue
        name = f"{prefix}{key}"
        node_id = config_id(builder.record.path, name)
        builder.node(
            node_id,
            "config",
            name,
            summary=f"{language} key {name}",
            tags=[language, "config"],
            file_path=builder.record.path,
        )
        builder.edge(builder.file_node["id"], node_id, "configures")
        value = mapping[key]
        if isinstance(value, dict) and len(prefix.split(".")) < 2:
            _add_keys(builder, value, language, f"{name}.")


def extract_json(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return builder.fragment()
    if isinstance(data, dict):
        _add_keys(builder, data, "json")
    if record.path.endswith("package.json") and isinstance(data, dict):
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for name in sorted((data.get(section) or {}).keys()):
                target = module_id(name)
                builder.node(target, "module", name, summary=f"npm dependency {name}", tags=["npm", "dependency"])
                builder.edge(builder.file_node["id"], target, "depends_on")
    return builder.fragment()


def extract_yaml(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    data = _parse_yaml(text)
    if data:
        _add_keys(builder, data, "yaml")
    for match in re.finditer(r"(?m)^\s*([A-Za-z_][\w.-]*):\s*$", text):
        name = match.group(1)
        node_id = config_id(record.path, name)
        builder.node(
            node_id, "config", name, summary=f"yaml key {name}", tags=["yaml", "config"], file_path=record.path
        )
        builder.edge(builder.file_node["id"], node_id, "configures")
    return builder.fragment()


def extract_toml(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return builder.fragment()
    _add_keys(builder, data, "toml")
    return builder.fragment()


def extract_env(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    for match in re.finditer(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", text):
        name = match.group(1)
        node_id = config_id(record.path, name)
        builder.node(
            node_id, "config", name, summary=f"environment key {name}", tags=["env", "config"], file_path=record.path
        )
        builder.edge(builder.file_node["id"], node_id, "configures")
    return builder.fragment()


def extract_dockerfile(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    for match in re.finditer(r"(?mi)^\s*FROM\s+([^\s]+)", text):
        name = match.group(1)
        target = f"resource:docker-image:{_slug(name)}"
        builder.node(target, "resource", name, summary=f"container image {name}", tags=["docker", "image"])
        builder.edge(builder.file_node["id"], target, "deploys")
    for match in re.finditer(r"(?mi)^\s*(RUN|CMD|ENTRYPOINT)\s+(.+)", text):
        name = match.group(1).upper()
        node_id = f"pipeline:{record.path}:{name}"
        builder.node(
            node_id,
            "pipeline",
            name,
            summary=_first_line(match.group(2)),
            tags=["docker", "pipeline"],
            file_path=record.path,
        )
        builder.edge(builder.file_node["id"], node_id, "contains")
    return builder.fragment()


def extract_makefile(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    for match in re.finditer(r"(?m)^([A-Za-z0-9_.-]+)\s*:([^=\n]*)$", text):
        name = match.group(1)
        if name.startswith("."):
            continue
        node_id = f"pipeline:{record.path}:{name}"
        builder.node(
            node_id, "pipeline", name, summary=f"make target {name}", tags=["make", "target"], file_path=record.path
        )
        builder.edge(builder.file_node["id"], node_id, "contains")
        for dep in match.group(2).split():
            target = f"file:{dep}"
            builder.node(target, "file", dep, summary=f"make prerequisite {dep}", tags=["make", "prerequisite"])
            builder.edge(node_id, target, "depends_on")
    return builder.fragment()


def extract_sql(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    for match in re.finditer(r"(?i)\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w.]*)", text):
        name = match.group(1)
        node_id = f"table:{name}"
        builder.node(node_id, "table", name, summary=f"SQL table {name}", tags=["sql", "table"])
        builder.edge(builder.file_node["id"], node_id, "defines_schema")
    return builder.fragment()


def extract_graphql(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    for match in re.finditer(r"(?m)^\s*(type|interface|enum|input|union)\s+([A-Za-z_]\w*)", text):
        name = match.group(2)
        node_id = f"schema:{name}"
        builder.node(
            node_id, "schema", name, summary=f"GraphQL {match.group(1)} {name}", tags=["graphql", match.group(1)]
        )
        builder.edge(builder.file_node["id"], node_id, "defines_schema")
    return builder.fragment()


def extract_protobuf(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    for match in re.finditer(r"(?m)^\s*(message|service|enum)\s+([A-Za-z_]\w*)", text):
        name = match.group(2)
        node_id = f"schema:{name}"
        builder.node(
            node_id, "schema", name, summary=f"protobuf {match.group(1)} {name}", tags=["protobuf", match.group(1)]
        )
        builder.edge(builder.file_node["id"], node_id, "defines_schema")
    for match in re.finditer(r"(?m)^\s*rpc\s+([A-Za-z_]\w*)", text):
        name = match.group(1)
        node_id = f"endpoint:{name}"
        builder.node(node_id, "endpoint", name, summary=f"protobuf rpc {name}", tags=["protobuf", "rpc"])
        builder.edge(builder.file_node["id"], node_id, "routes")
    return builder.fragment()


def extract_terraform(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    for match in re.finditer(r'(?m)^\s*resource\s+"([^"]+)"\s+"([^"]+)"', text):
        name = f"{match.group(1)}.{match.group(2)}"
        node_id = f"resource:{name}"
        builder.node(node_id, "resource", name, summary=f"terraform resource {name}", tags=["terraform", "resource"])
        builder.edge(builder.file_node["id"], node_id, "provisions")
    for match in re.finditer(r'(?m)^\s*module\s+"([^"]+)"', text):
        name = match.group(1)
        node_id = module_id(f"terraform:{name}")
        builder.node(node_id, "module", name, summary=f"terraform module {name}", tags=["terraform", "module"])
        builder.edge(builder.file_node["id"], node_id, "depends_on")
    return builder.fragment()


def extract_html(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record, node_type="document")
    title = re.search(r"(?is)<title>(.*?)</title>", text)
    if title:
        builder.file_node["name"] = _first_line(title.group(1), 120)
    for match in re.finditer(r"(?is)<(script|link)[^>]+(?:src|href)=[\"']([^\"']+)[\"']", text):
        target = match.group(2)
        if target.startswith(("http://", "https://", "//", "#")):
            continue
        node_id = f"resource:{_slug(target)}"
        builder.node(node_id, "resource", target, summary=f"asset {target}", tags=["html", "asset"])
        builder.edge(builder.file_node["id"], node_id, "depends_on")
    return builder.fragment()


# --- generic fallback ---------------------------------------------------------


GENERIC_SYMBOL_RE = re.compile(
    r"(?m)^\s*(?:export\s+|public\s+|private\s+|protected\s+|static\s+|async\s+|def\s+|func\s+|fn\s+|class\s+|struct\s+|interface\s+|enum\s+|type\s+)?"
    r"([A-Za-z_]\w*)\s*(?:\(|:|\s*\{)"
)


def extract_generic(record: FileRecord, text: str) -> dict[str, Any]:
    builder = Builder(record)
    for match in GENERIC_SYMBOL_RE.finditer(text):
        name = match.group(1)
        if name.lower() in {"if", "for", "while", "switch", "return", "import", "package", "using", "namespace"}:
            continue
        line = text.count("\n", 0, match.start()) + 1
        node_id = symbol_id(record.path, "function", name, line)
        builder.node(
            node_id,
            "function",
            name,
            summary=f"{record.language} symbol {name}",
            tags=[record.language, "symbol"],
            file_path=record.path,
            line_range=(line, line),
        )
        builder.edge(builder.file_node["id"], node_id, "contains")
    return builder.fragment()


DISPATCH = {
    "python": extract_python,
    "go": extract_go,
    "javascript": extract_javascript,
    "typescript": extract_javascript,
    "shell": extract_shell,
    "markdown": extract_markdown,
    "json": extract_json,
    "yaml": extract_yaml,
    "github-actions": extract_yaml,
    "docker-compose": extract_yaml,
    "toml": extract_toml,
    "env": extract_env,
    "dockerfile": extract_dockerfile,
    "makefile": extract_makefile,
    "sql": extract_sql,
    "graphql": extract_graphql,
    "protobuf": extract_protobuf,
    "terraform": extract_terraform,
    "html": extract_html,
}


def extract_tree_sitter(record: FileRecord, text: str) -> dict[str, Any] | None:
    """Generic tree-sitter adapter for languages without a native extractor.

    The optional ``understand`` extra installs ``tree-sitter`` and the language
    pack. Without it this returns ``None`` and the caller falls back to the
    generic regex extractor. The adapter emits only relations it can prove from
    the AST (contains, imports); it never invents a call edge to a symbol it did
    not declare in the same file.
    """
    try:
        from tree_sitter_language_pack import get_parser
    except Exception:
        return None
    try:
        parser = get_parser(record.language)
        tree = parser.parse(text.encode("utf-8"))
    except Exception:
        return None
    builder = Builder(record)
    function_kinds = {
        "function_definition",
        "function_declaration",
        "method_definition",
        "function_item",
        "method_declaration",
    }
    class_kinds = {"class_definition", "class_declaration", "struct_item", "interface_declaration", "class_specifier"}
    import_kinds = {"import_statement", "import_declaration", "use_declaration", "include_directive"}

    def walk(node: Any) -> None:
        kind = node.type
        if kind in function_kinds or kind in class_kinds:
            name_node = node.child_by_field_name("name")
            name = text[name_node.start_byte : name_node.end_byte] if name_node else kind
            node_type = "function" if kind in function_kinds else "class"
            node_id = symbol_id(record.path, node_type, name, node.start_point[0] + 1)
            builder.node(
                node_id,
                node_type,
                name,
                summary=f"{record.language} {node_type} {name}",
                tags=[record.language, node_type],
                file_path=record.path,
                line_range=(node.start_point[0] + 1, node.end_point[0] + 1),
            )
            builder.edge(builder.file_node["id"], node_id, "contains")
        elif kind in import_kinds:
            name = " ".join(text[node.start_byte : node.end_byte].split())[:120]
            if name:
                target = module_id(name)
                builder.node(
                    target, "module", name, summary=f"{record.language} import", tags=[record.language, "import"]
                )
                builder.edge(builder.file_node["id"], target, "imports")
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return builder.fragment()


def extract(record: FileRecord, text: str) -> dict[str, Any]:
    extractor = DISPATCH.get(record.language)
    if extractor is None:
        tree = extract_tree_sitter(record, text)
        if tree is not None:
            return tree
        extractor = extract_generic
    try:
        return extractor(record, text)
    except Exception as exc:
        builder = Builder(record)
        builder.file_node["summary"] = f"extractor failed: {exc.__class__.__name__}"
        builder.file_node["tags"] = sorted(set(builder.file_node["tags"]) | {"extractor-error"})
        return builder.fragment()


def link_tests(nodes: Iterable[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """Add file-level ``tested_by`` edges without guessing across directories."""
    file_nodes = {str(node["filePath"]): node for node in nodes if node.get("filePath") and node.get("type") == "file"}
    by_basename: dict[str, list[str]] = {}
    for path in file_nodes:
        if is_test_path(path):
            continue
        by_basename.setdefault(PurePosixPath(path).name, []).append(path)
    for path, test_node in file_nodes.items():
        if not is_test_path(path):
            continue
        stem = PurePosixPath(path).name
        candidate_names: list[str] = []
        for prefix in ("test_", "spec_"):
            if stem.startswith(prefix):
                candidate_names.append(stem[len(prefix) :])
        for marker in (".test.", ".spec."):
            if marker in stem:
                candidate_names.append(stem.replace(marker, "."))
        for suffix in ("_test.go", "_test.py"):
            if stem.endswith(suffix):
                candidate_names.append(stem[: -len(suffix)] + PurePosixPath(stem).suffix)
        candidates = [PurePosixPath(path).with_name(name).as_posix() for name in candidate_names]
        target = next((candidate for candidate in candidates if candidate in file_nodes), None)
        if target is None:
            for name in candidate_names:
                matches = by_basename.get(name, [])
                if len(matches) == 1:
                    target = matches[0]
                    break
        if target:
            edges.append(make_edge(file_nodes[target]["id"], test_node["id"], "tested_by") or {})

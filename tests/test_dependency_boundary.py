"""The dependency boundary around the WebUI-only modules.

`shared/` is importable by both roles; its runtime allow-list is the standard
library plus `cryptography`. Two exceptions exist and are pinned here and in
ADR-0015: the Open WebUI memory filter (its dependencies are supplied by the
WebUI runtime) and the lazy optional tree-sitter extractor (the opt-in
`[understand]` extra). Neither may leak into a role's runtime path.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.layout

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"
FILTER = SHARED / "sparknet-memory-filter.py"
WEBUI_FILTER = ROOT / "webui" / "functions" / "sparknet_memory_filter.py"

ADAPTER_DEPENDENCIES = {"httpx", "pydantic"}
OPTIONAL_EXTRAS = {"tree_sitter_language_pack"}


class _Imports(ast.NodeVisitor):
    """Collect third-party imports by execution scope: module vs function-local."""

    def __init__(self) -> None:
        self.module: set[str] = set()
        self.lazy: set[str] = set()
        self._depth = 0

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def _record(self, name: str) -> None:
        target = self.module if self._depth == 0 else self.lazy
        target.add(name.split(".")[0])

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self._record(node.module)


def _shared_files() -> list[Path]:
    return sorted(path for path in SHARED.rglob("*.py") if "__pycache__" not in path.parts)


def _local_names() -> set[str]:
    names = {path.stem.replace("-", "_") for path in SHARED.glob("*.py")}
    names |= {path.name for path in SHARED.iterdir() if path.is_dir() and path.name != "__pycache__"}
    return names


def _third_party(imports: set[str]) -> set[str]:
    return {name for name in imports if name not in sys.stdlib_module_names and name not in _local_names()}


def test_module_level_imports_stay_on_the_runtime_allowlist() -> None:
    offenders = []
    for path in _shared_files():
        visitor = _Imports()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        allowed = {"cryptography"}
        if path == FILTER:
            allowed |= ADAPTER_DEPENDENCIES
        extra = sorted(_third_party(visitor.module) - allowed)
        if extra:
            offenders.append(f"{path.relative_to(ROOT).as_posix()}: {', '.join(extra)}")
    assert offenders == [], f"module-level imports outside the runtime allow-list: {offenders}"


def test_lazy_imports_are_only_the_optional_extras() -> None:
    offenders = []
    for path in _shared_files():
        visitor = _Imports()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        extra = sorted(_third_party(visitor.lazy) - OPTIONAL_EXTRAS - {"cryptography"})
        if extra:
            offenders.append(f"{path.relative_to(ROOT).as_posix()}: {', '.join(extra)}")
        if "tree_sitter_language_pack" in visitor.lazy and "sparknet_understand" not in path.parts:
            offenders.append(f"{path.relative_to(ROOT).as_posix()}: optional extractor outside its package")
    assert offenders == [], f"lazy imports outside the optional extras: {offenders}"


def test_the_webui_filter_is_one_physical_file() -> None:
    assert WEBUI_FILTER.is_symlink(), "webui/functions/sparknet_memory_filter.py must be a symlink, not a copy"
    assert WEBUI_FILTER.resolve() == FILTER.resolve(), "the WebUI filter must resolve to the shared adapter"


def test_runtime_code_never_references_the_memory_filter() -> None:
    runtime_roots = [SHARED, ROOT / "peer-node" / "services", ROOT / "master-node" / "services"]
    offenders = []
    for base in runtime_roots:
        for path in sorted(base.rglob("*.py")):
            if path == FILTER or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "sparknet-memory-filter" in text or "sparknet_memory_filter" in text:
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == [], f"runtime code references the WebUI adapter: {offenders}"

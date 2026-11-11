"""Every fabric test module declares its tier.

The registered tier vocabulary (`unit`, `integration`, `contract`, `layout`,
`slow`) is only real if selection is complete: an unmarked module is silently
excluded by every `-m` run. This meta-test fails when a new module arrives
without a module-level `pytestmark`, so the fast unit loop cannot decay.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import tomllib

pytestmark = pytest.mark.layout

TESTS = Path(__file__).resolve().parent
TIERS = {"unit", "integration", "contract", "layout", "slow"}
FORBIDDEN_MODULES = {"subprocess", "socket", "socketserver", "http.server"}
FORBIDDEN_OS_CALLS = {"system", "popen"}
FORBIDDEN_SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}


def _tier_marks(value: ast.expr) -> set[str]:
    marks: set[str] = set()
    for node in ast.walk(value):
        if not isinstance(node, ast.Attribute) or node.attr not in TIERS:
            continue
        mark = node.value
        if not isinstance(mark, ast.Attribute) or mark.attr != "mark":
            continue
        owner = mark.value
        if isinstance(owner, ast.Name) and owner.id == "pytest":
            marks.add(node.attr)
    return marks


def _module_tier(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            found |= _tier_marks(node.value)
    return found


def test_every_fabric_test_module_declares_a_tier() -> None:
    missing = [
        path.relative_to(TESTS).as_posix() for path in sorted(TESTS.rglob("test_*.py")) if not _module_tier(path)
    ]
    assert missing == [], f"test modules without a module-level tier mark: {missing}"


def _runtime_boundary_hits(tree: ast.Module) -> set[str]:
    hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits.update(f"import {alias.name}" for alias in node.names if alias.name in FORBIDDEN_MODULES)
        elif isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_MODULES:
            hits.add(f"from {node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "os" and node.func.attr in FORBIDDEN_OS_CALLS:
                hits.add(f"os.{node.func.attr}")
            if (
                isinstance(owner, ast.Name)
                and owner.id == "subprocess"
                and node.func.attr in FORBIDDEN_SUBPROCESS_CALLS
            ):
                hits.add(f"subprocess.{node.func.attr}")
            if isinstance(owner, ast.Name) and owner.id == "time" and node.func.attr == "sleep":
                hits.add("time.sleep")
    return hits


def test_unit_modules_do_not_reach_for_processes_or_sockets() -> None:
    offenders = []
    for path in sorted(TESTS.rglob("test_*.py")):
        if "unit" not in _module_tier(path):
            continue
        hits = _runtime_boundary_hits(ast.parse(path.read_text(encoding="utf-8")))
        if hits:
            offenders.append(f"{path.relative_to(TESTS).as_posix()}: {', '.join(sorted(hits))}")
    assert offenders == [], f"unit modules crossed the process/socket boundary: {offenders}"


def test_the_registered_marker_vocabulary_matches_the_tiers() -> None:
    config = tomllib.loads((TESTS.parent / "pyproject.toml").read_text(encoding="utf-8"))
    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    registered = {marker.split(":", 1)[0].strip() for marker in markers}
    assert registered == TIERS

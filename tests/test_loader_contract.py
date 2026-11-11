"""The one by-path loader is the only by-path loader in the fabric.

The shared modules proved the rule first; this guardrail extends it to role
services, root scripts and tests. A second implementation is how the two roles
silently stop agreeing about what they loaded, so the test scans for the
implementation (an AST call), not for a comment or a string in a test fixture.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract


ROOT = Path(__file__).resolve().parent.parent
LOADER = ROOT / "shared" / "sparknet_loader.py"

SCAN_ROOTS = (
    "shared",
    "scripts",
    "tests",
    "peer-node/services",
    "peer-node/tests",
    "peer-node/scripts",
    "peer-node/agents",
    "master-node/services",
    "master-node/tests",
    "master-node/scripts",
)

EXCLUDE_PARTS = {".opencode", "goagx", "dist", "__pycache__", ".venv", ".git", ".state"}


def _files(suffix: str) -> list[Path]:
    found: list[Path] = []
    for root in SCAN_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob(f"*{suffix}"):
            if path.is_file() and not (EXCLUDE_PARTS & set(path.parts)):
                found.append(path)
    return sorted(set(found))


def _spec_calls(path: Path) -> list[int]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "spec_from_file_location"
    ]


def test_only_the_loader_calls_spec_from_file_location() -> None:
    offenders = []
    for path in _files(".py"):
        if path == LOADER:
            continue
        for line in _spec_calls(path):
            offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert not offenders, "by-path loader reimplemented outside shared/sparknet_loader.py: " + ", ".join(offenders)


def test_shell_snippets_do_not_reimplement_the_loader() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in _files(".sh")
        if "spec_from_file_location" in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, "shell snippet reimplements the loader: " + ", ".join(offenders)


def test_production_loader_callers_have_a_shared_path_shim() -> None:
    production = [
        path
        for path in _files(".py")
        if not any(part in {"tests", "peer-node/tests", "master-node/tests"} for part in path.relative_to(ROOT).parts)
    ]
    offenders = []
    for path in production:
        text = path.read_text(encoding="utf-8")
        if "from sparknet_loader import" not in text:
            continue
        if "sys.path.insert" not in text or "shared" not in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, "loader import without a shared path shim: " + ", ".join(offenders)


def test_role_services_do_not_carry_a_shared_directory_resolver() -> None:
    """The loader owns resolution; a service may only call it.

    A local `_shared_dir`/`_shared_dirs`/`shared_dir` is how the search orders
    drifted before: one service accepted a role-local `shared/`, another did
    not, and one treated `SPARKNET_SHARED_DIR` as a root while another treated
    it as the directory. The one loader now accepts both meanings.
    """
    offenders: list[str] = []
    for path in _files(".py"):
        relative = path.relative_to(ROOT).as_posix()
        if not relative.startswith(("peer-node/services/", "master-node/services/")):
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"^def (?:shared_dir|_shared_dir|_shared_dirs)\b", text, re.MULTILINE):
            offenders.append(relative)
    assert not offenders, "role service reimplements shared-directory resolution: " + ", ".join(offenders)

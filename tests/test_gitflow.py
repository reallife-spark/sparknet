"""GitFlow policy: only declared promotion edges are allowed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("sparknet_gitflow_test", ROOT / "shared" / "sparknet-gitflow.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gitflow = _load()


def test_declared_gitflow_edges_are_allowed():
    assert gitflow.promotion_allowed("feature/registry", "develop")
    assert gitflow.promotion_allowed("release/1.2.0", "main")
    assert gitflow.promotion_allowed("release/1.2.0", "master")
    assert gitflow.promotion_allowed("hotfix/token", "main")
    assert gitflow.promotion_allowed("master", "master")


def test_undeclared_edges_are_refused():
    for source, target in [
        ("feature/registry", "main"),
        ("hotfix/token", "develop"),
        ("release/1.2.0", "develop"),
        ("main", "develop"),
        ("develop", "main"),
        ("random", "develop"),
    ]:
        assert not gitflow.promotion_allowed(source, target), (source, target)


def test_branch_names_fail_closed():
    for bad in ["", "..", "feature/../main", "feature//x", "feature/x.lock", "feature/x y", "feature/"]:
        try:
            gitflow.validate_branch(bad)
        except gitflow.GitFlowError as exc:
            assert exc.code == "branch-invalid"
        else:
            raise AssertionError(f"accepted invalid branch {bad!r}")


def test_require_promotion_reports_the_edge():
    try:
        gitflow.require_promotion("feature/x", "main")
    except gitflow.GitFlowError as exc:
        assert exc.code == "promotion-refused"
        assert "feature/* -> develop" in exc.message
    else:
        raise AssertionError("undeclared edge was accepted")

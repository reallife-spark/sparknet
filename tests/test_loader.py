"""The one by-path loader: caching, refusals and optional surfaces."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

from sparknet_loader import load_by_path, load_shared  # noqa: E402 - the shared path shim

pytestmark = pytest.mark.unit


def test_failed_load_is_not_cached(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("raise RuntimeError('boom')\n")
    name = "sparknet_bad_module_for_loader_test"
    sys.modules.pop(name, None)
    with pytest.raises(RuntimeError, match="boom"):
        load_by_path(name, bad)
    assert name not in sys.modules


def test_same_name_returns_the_same_module(tmp_path):
    module_path = tmp_path / "same.py"
    module_path.write_text("VALUE = 1\n")
    name = "sparknet_same_module_for_loader_test"
    sys.modules.pop(name, None)
    first = load_by_path(name, module_path)
    second = load_by_path(name, module_path)
    assert first is second
    assert first.VALUE == 1


def test_different_names_are_distinct_instances(tmp_path):
    module_path = tmp_path / "distinct.py"
    module_path.write_text("VALUE = 1\n")
    first_name = "sparknet_distinct_module_one"
    second_name = "sparknet_distinct_module_two"
    sys.modules.pop(first_name, None)
    sys.modules.pop(second_name, None)
    first = load_by_path(first_name, module_path)
    second = load_by_path(second_name, module_path)
    assert first is not second


def test_required_dependency_refuses_before_loading(tmp_path):
    module_path = tmp_path / "needs.py"
    module_path.write_text("VALUE = 1\n")
    with pytest.raises(FileNotFoundError, match=r"sparknet-missing\.py"):
        load_shared("needs.py", "sparknet_needs_module", dirs=[tmp_path], required=("sparknet-missing.py",))


def test_missing_ok_returns_none(tmp_path):
    assert load_shared("absent.py", "sparknet_absent_module", dirs=[tmp_path], missing_ok=True) is None


def test_missing_required_file_uses_the_callers_error(tmp_path):
    class Refusal(RuntimeError):
        pass

    with pytest.raises(Refusal, match="cannot locate"):
        load_shared("absent.py", "sparknet_absent_module", dirs=[tmp_path], error=Refusal)


def test_shared_dir_environment_accepts_a_directory_or_a_root(tmp_path, monkeypatch):
    marker = "tmp_loader_env_probe.py"
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / marker).write_text("VALUE = 'loaded'\n", encoding="utf-8")
    monkeypatch.delenv("VAULT_PATH", raising=False)

    monkeypatch.setenv("SPARKNET_SHARED_DIR", str(shared))
    direct = load_shared(marker, "sparknet_env_direct_probe", missing_ok=True)
    assert direct is not None and direct.VALUE == "loaded"

    sys.modules.pop("sparknet_env_root_probe", None)
    monkeypatch.setenv("SPARKNET_SHARED_DIR", str(tmp_path))
    root = load_shared(marker, "sparknet_env_root_probe", missing_ok=True)
    assert root is not None and root.VALUE == "loaded"


def test_loader_accepts_the_deployed_shared_path() -> None:
    from sparknet_loader import candidates

    paths = [str(path) for path in candidates("sparknet-authz.py")]
    assert "/srv/sparknet/shared/sparknet-authz.py" in paths


def test_missing_file_reports_candidate_paths(tmp_path):
    with pytest.raises(FileNotFoundError) as excinfo:
        load_shared("absent.py", "sparknet_absent_paths_module", dirs=[tmp_path])
    message = str(excinfo.value)
    assert "searched, in order" in message
    assert str(tmp_path / "absent.py") in message


def test_missing_required_sibling_reports_the_probed_directory(tmp_path):
    module_path = tmp_path / "needs.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError) as excinfo:
        load_shared(
            "needs.py",
            "sparknet_needs_paths_module",
            dirs=[tmp_path],
            required=("sparknet-missing.py",),
        )
    message = str(excinfo.value)
    assert "sparknet-missing.py" in message
    assert f"probed {module_path}" in message
    assert "searched, in order" in message

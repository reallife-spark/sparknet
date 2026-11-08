"""A corrupt registry install record fails closed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = ROOT / "shared" / "sparknet-registry-install.py"
    spec = importlib.util.spec_from_file_location("registry_install_record_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


install = _load()


def test_corrupt_registry_installation_record_is_refused(tmp_path):
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / install.INSTALLATION_FILE).write_text("{not json")
    with pytest.raises(install.InstallError) as refused:
        install.installation_record(tmp_path)
    assert refused.value.code == "installation-record-corrupt"
    with pytest.raises(install.InstallError):
        install.installed_sequence(tmp_path)

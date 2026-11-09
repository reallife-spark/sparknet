"""A corrupt registry install record fails closed."""

from __future__ import annotations

from pathlib import Path

import pytest
from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = ROOT / "shared" / "sparknet-registry-install.py"
    return load_by_path("registry_install_record_test", path)


install = _load()


def test_corrupt_registry_installation_record_is_refused(tmp_path):
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / install.INSTALLATION_FILE).write_text("{not json")
    with pytest.raises(install.InstallError) as refused:
        install.installation_record(tmp_path)
    assert refused.value.code == "installation-record-corrupt"
    with pytest.raises(install.InstallError):
        install.installed_sequence(tmp_path)


def test_malformed_sequence_is_refused_not_treated_as_zero(tmp_path):
    (tmp_path / "manifests").mkdir()
    (tmp_path / "manifests" / install.INSTALLATION_FILE).write_text(
        '{"sequence": "not-an-int", "registry_sha256": "' + "a" * 64 + '"}'
    )
    with pytest.raises(install.InstallError) as refused:
        install.installed_sequence(tmp_path)
    assert refused.value.code == "installation-record-corrupt"

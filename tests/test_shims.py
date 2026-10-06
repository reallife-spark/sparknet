"""Every legacy name must be a symlink to its numbered home.

`peer-node/` and `master-node/` now store vault content under
`00_System`–`07_Archives`, while the vendored wiki suite, the charters and
every old link still say `concepts/`, `_raw/`, `sessions/`. Shims are what
makes both spellings name one file. Three ways that breaks, all tested here:

1. a shim becomes a **real directory** — the next page written through the old
   name lands in a second copy that nothing else ever reads;
2. a shim **points somewhere else** — pages silently move;
3. a shim **vanishes** — every old link goes dead.

`make shims-check` is the cheap version of this test; it is a contract-level
command (`contracts/tracking-schema.json` → `layout.legacy_map`), so the
targets and both spellings are asserted against the contract, never against a
list written twice.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVENANCE_PATH = REPO_ROOT / "shared" / "sparknet-provenance.py"
CONTRACT = json.loads((REPO_ROOT / "contracts" / "tracking-schema.json").read_text())
LEGACY_MAP: dict[str, str] = CONTRACT["layout"]["legacy_map"]
PEER = REPO_ROOT / "peer-node"
MASTER = REPO_ROOT / "master-node"


@pytest.fixture(scope="module")
def provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sparknet_provenance_shims", PROVENANCE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def make_vault(root: Path) -> Path:
    """A miniature role vault with one symlink per entry in the contract."""
    for target in sorted(set(LEGACY_MAP.values())):
        (root / target).mkdir(parents=True, exist_ok=True)
        (root / target / ".gitkeep").write_text("")
    for name, target in LEGACY_MAP.items():
        os.symlink(target, root / name)
    return root


def test_the_peer_vaults_shims_match_the_contract(provenance: ModuleType):
    """The real peer vault is the one that has to be right."""
    code, text = provenance.check_shims(PEER)
    assert code == 0, text
    assert str(len(LEGACY_MAP)) in text


def test_a_rebuilt_vault_passes(provenance: ModuleType, tmp_path: Path):
    vault = make_vault(tmp_path / "vault")
    code, text = provenance.check_shims(vault)
    assert code == 0, text


def test_a_real_directory_instead_of_a_symlink_fails(provenance: ModuleType, tmp_path: Path):
    vault = make_vault(tmp_path / "vault")
    (vault / "concepts").unlink()
    (vault / "concepts").mkdir()
    (vault / "concepts" / "page.md").write_text("the second copy nobody reads")
    code, text = provenance.check_shims(vault)
    assert code == 1
    assert "concepts" in text and "not a symlink" in text


def test_a_symlink_pointing_at_the_wrong_place_fails(provenance: ModuleType, tmp_path: Path):
    vault = make_vault(tmp_path / "vault")
    (vault / "05_Knowledge").mkdir(exist_ok=True)
    (vault / "05_Knowledge" / "elsewhere").mkdir(exist_ok=True)
    (vault / "_raw").unlink()
    os.symlink("05_Knowledge/elsewhere", vault / "_raw")
    code, text = provenance.check_shims(vault)
    assert code == 1
    assert "_raw" in text and "expected" in text


def test_a_missing_symlink_fails(provenance: ModuleType, tmp_path: Path):
    vault = make_vault(tmp_path / "vault")
    (vault / "sessions").unlink()
    code, text = provenance.check_shims(vault)
    assert code == 1
    assert "sessions" in text and "missing" in text


def test_a_dangling_target_fails(provenance: ModuleType, tmp_path: Path):
    vault = make_vault(tmp_path / "vault")
    for p in sorted((vault / "02_Daily").iterdir()):
        p.unlink()
    (vault / "02_Daily").rmdir()
    code, text = provenance.check_shims(vault)
    assert code == 1
    assert "target" in text


def test_the_clis_shims_subcommand_is_wired():
    """`make shims-check` has to have something to call."""
    tool = PROVENANCE_PATH.read_text()
    assert '"shims"' in tool
    for role in (PEER, MASTER):
        makefile = (role / "Makefile").read_text()
        assert "shims-check:" in makefile and " shims" in makefile, role
    assert (REPO_ROOT / "Makefile").read_text().count("shims-check") >= 1


def test_each_role_vaults_shims_match_the_contract(provenance: ModuleType):
    """Both roles migrated to the numbered layout; the master is no longer legacy."""
    for role in (PEER, MASTER):
        code, text = provenance.check_shims(role)
        assert code == 0, f"{role}: {text}"
        assert str(len(LEGACY_MAP)) in text, role

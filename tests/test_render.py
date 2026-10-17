"""The contract manifest renderer (`scripts/sparknet-render.py`).

`contracts/*.json` is the machine source of truth; `contracts/manifest.json` is
its generated view. Three properties are locked down here because a generated
file is easy to let rot:

1. **It is fresh.** The committed manifest equals what the current contracts
   render — the drift gate `make render-check` runs in the pre-merge gate.
2. **It covers the SSOT.** Every JSON contract appears, and the projected
   capability and port tables equal their source files. A new contract that the
   manifest ignores is a contract the manifest lies about.
3. **`--check` really fails on drift.** A gate that never goes red is not a
   gate, so a mutated copy of the contracts must make `--check` exit non-zero.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "sparknet-render.py"
CONTRACTS = REPO_ROOT / "contracts"
MANIFEST = CONTRACTS / "manifest.json"
RUN = [sys.executable, str(SCRIPT)]


def _load() -> object:
    spec = importlib.util.spec_from_file_location("sparknet_render", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


render = _load()


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _json_contracts() -> list[str]:
    return sorted(p.name for p in CONTRACTS.glob("*.json") if p.name != "manifest.json")


# --- it is fresh and deterministic --------------------------------------------


def test_committed_manifest_is_fresh() -> None:
    proc = subprocess.run([*RUN, "--check"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_render_is_deterministic_and_matches_the_committed_file() -> None:
    first = render.render(render.build(CONTRACTS))
    second = render.render(render.build(CONTRACTS))
    assert first == second
    assert first == MANIFEST.read_text(encoding="utf-8")


# --- it covers the source of truth --------------------------------------------


def test_manifest_names_every_json_contract() -> None:
    files = [row["file"] for row in _manifest()["contracts"]]
    assert files == _json_contracts()


def test_manifest_capabilities_match_the_contract() -> None:
    caps = json.loads((CONTRACTS / "capabilities.json").read_text())
    assert _manifest()["known_capabilities"] == sorted(caps["known_capabilities"])


def test_manifest_ports_match_the_contract() -> None:
    ports = json.loads((CONTRACTS / "ports.json").read_text())["ports"]
    assert set(_manifest()["ports"]) == set(ports)


def test_manifest_node_ports_match_the_contract() -> None:
    src = json.loads((CONTRACTS / "ports.json").read_text())
    assert set(_manifest()["node_ports"]) == set(src.get("node_ports", {})), (
        "the node ports are a separate namespace from the fabric ports; both "
        "must reach the manifest, unmerged, so a shared number is not collapsed"
    )


def test_manifest_records_a_hash_for_each_contract() -> None:
    for row in _manifest()["contracts"]:
        assert len(row["sha256"]) == 64, f"{row['file']} has no sha256"


# --- the gate actually goes red ------------------------------------------------


def test_check_fails_when_a_contract_changes_without_a_rerender(tmp_path: Path) -> None:
    copied = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, copied)
    assert subprocess.run([*RUN, "--contracts", str(copied)], capture_output=True).returncode == 0
    assert subprocess.run([*RUN, "--contracts", str(copied), "--check"], capture_output=True).returncode == 0

    target = copied / "overlay.json"
    target.write_text(target.read_text() + "\n", encoding="utf-8")
    drift = subprocess.run([*RUN, "--contracts", str(copied), "--check"], capture_output=True, text=True)
    assert drift.returncode == 1
    assert "stale" in (drift.stdout + drift.stderr)


def test_check_fails_when_the_manifest_is_absent(tmp_path: Path) -> None:
    copied = tmp_path / "contracts"
    shutil.copytree(CONTRACTS, copied)
    (copied / "manifest.json").unlink()
    proc = subprocess.run([*RUN, "--contracts", str(copied), "--check"], capture_output=True, text=True)
    assert proc.returncode == 1
    assert "missing" in (proc.stdout + proc.stderr)


def test_a_missing_contracts_directory_fails_closed(tmp_path: Path) -> None:
    proc = subprocess.run([*RUN, "--contracts", str(tmp_path / "nope")], capture_output=True, text=True)
    assert proc.returncode == 1
    assert "not a directory" in (proc.stdout + proc.stderr)


# --- it answers --help without doing the work ----------------------------------


def test_help_exits_zero_and_prints() -> None:
    proc = subprocess.run([*RUN, "--help"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.strip()

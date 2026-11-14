"""The on-demand model runtime: leases, conflicts and the memory guard.

These tests never invoke docker. They exercise config validation, the real
compose command construction, the memory guard and the lease state machine with
``--dry-run``; an actual container start is a target-node check.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration


ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "scripts" / "sparknet-model-runtime.py"
CATALOG = ROOT / "contracts" / "model-catalog.json"


def _load() -> object:
    return load_by_path("sparknet_model_runtime_test", RUNTIME)


runtime = _load()
MODELS = {model["id"]: model for model in json.loads(CATALOG.read_text())["models"]}


@pytest.fixture
def peer_config() -> dict:
    return json.loads((ROOT / "peer-node" / "configs" / "model-runtime" / "runtime.json").read_text())


@pytest.fixture
def master_config() -> dict:
    return json.loads((ROOT / "master-node" / "configs" / "model-runtime" / "runtime.json").read_text())


@pytest.fixture
def store(tmp_path: Path) -> Path:
    model_id = "qwen3-30b-a3b-2507-q4-k-m"
    model_dir = tmp_path / model_id
    model_dir.mkdir()
    (model_dir / "model.gguf").write_bytes(b"model")
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / f"{model_id}.json").write_text(
        json.dumps(
            {
                "schema": "sparknet-model-manifest/1",
                "id": model_id,
                "pinned": True,
                "model_file": "model.gguf",
                "files": [{"path": "model.gguf", "sha256": "x", "size": 5}],
            }
        )
    )
    return tmp_path


def test_peer_config_is_valid(peer_config: dict) -> None:
    assert runtime.validate_config(peer_config, "peer", MODELS) == []


def test_master_config_is_valid(master_config: dict) -> None:
    assert runtime.validate_config(master_config, "master", MODELS) == []


def test_peer_cannot_define_a_teacher_profile(peer_config: dict) -> None:
    peer_config["profiles"]["teacher"] = dict(peer_config["profiles"]["student"])
    peer_config["profiles"]["teacher"]["model_id"] = "qwen3.6-35b-a3b-q4-k-m"
    errors = runtime.validate_config(peer_config, "peer", MODELS)
    assert any("not eligible for agx32" in error for error in errors)


def test_mem_available_reads_meminfo(tmp_path: Path) -> None:
    path = tmp_path / "meminfo"
    path.write_text("MemTotal: 1000 kB\nMemAvailable: 524288 kB\n")
    assert runtime.mem_available_gb(path) == 0.5


def test_compose_command_is_a_fixed_argv(master_config: dict) -> None:
    cmd = runtime.compose_command(master_config, "teacher", "up")
    assert cmd[:2] == ["docker", "compose"]
    assert "-f" in cmd and "-p" in cmd
    assert cmd[-3:] == ["up", "-d", "teacher"]


def test_start_dry_run_uses_the_manifest_model_file(
    master_config: dict, store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("SPARKNET_MODEL_RUNTIME_STATE", str(tmp_path / "state"))
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 67108864 kB\n")
    result = runtime.start(
        config=master_config,
        role="master",
        name="teacher",
        store=store,
        meminfo=meminfo,
        dry_run=True,
        force=False,
        replace=False,
        health_timeout=0,
        operator="test",
    )
    assert result["state"] == "dry-run"
    assert result["model_file"] == "/models/qwen3-30b-a3b-2507-q4-k-m/model.gguf"
    out = capsys.readouterr().out
    assert "docker compose" in out
    assert "up -d teacher" in out


def test_memory_guard_refuses_without_force(master_config: dict, store: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_MODEL_RUNTIME_STATE", str(tmp_path / "state"))
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 1024 kB\n")
    with pytest.raises(runtime.Refusal):
        runtime.start(
            config=master_config,
            role="master",
            name="teacher",
            store=store,
            meminfo=meminfo,
            dry_run=True,
            force=False,
            replace=False,
            health_timeout=0,
            operator="test",
        )


def test_conflicting_lease_refuses_without_replace(
    master_config: dict, store: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SPARKNET_MODEL_RUNTIME_STATE", str(tmp_path / "state"))
    lease = {
        "schema": "sparknet-model-lease/1",
        "role": "master",
        "node": "agx64",
        "profile": "teacher-reference",
        "model_id": "qwen3.6-35b-a3b-q4-k-m",
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "idle_stop_minutes": 30,
        "pinned": False,
    }
    runtime.write_lease("master", "teacher-reference", lease)
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable: 67108864 kB\n")
    with pytest.raises(runtime.Refusal, match="conflicts"):
        runtime.start(
            config=master_config,
            role="master",
            name="teacher",
            store=store,
            meminfo=meminfo,
            dry_run=True,
            force=False,
            replace=False,
            health_timeout=0,
            operator="test",
        )


def test_reap_stops_an_expired_lease(master_config: dict, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_MODEL_RUNTIME_STATE", str(tmp_path / "state"))
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    runtime.write_lease(
        "master",
        "teacher",
        {
            "schema": "sparknet-model-lease/1",
            "role": "master",
            "node": "agx64",
            "profile": "teacher",
            "model_id": "qwen3.6-35b-a3b-q4-k-m",
            "started_at": old,
            "idle_stop_minutes": 45,
            "pinned": False,
        },
    )
    stopped = runtime.reap(master_config, "master", tmp_path, "test", dry_run=True)
    assert stopped and stopped[0]["profile"] == "teacher"

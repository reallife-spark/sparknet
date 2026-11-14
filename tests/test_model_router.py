"""The model router is local-first and refuses user data remotely."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
ROUTER = ROOT / "shared" / "sparknet-model-router.py"


@pytest.fixture(scope="module")
def router():
    return load_by_path("sparknet_model_router_test", ROUTER)


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "master_public_key_b64": "x",
                "authorizations": [
                    {
                        "identity": {"node_id": "sparknet-node-0002"},
                        "node_pubkey_b64": "x",
                        "capabilities": ["telemetry", "p2p-sync", "push-receive", "model-route"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_local_alias_is_local(router) -> None:
    routes = {"qwen3-30b": ("chat", "http://127.0.0.1:8000/v1/chat/completions")}
    assert router._alias(routes, "qwen3-30b", "chat").endswith("/v1/chat/completions")
    assert router._alias(routes, "qwen3-30b", "embed") is None
    assert router._alias(routes, "missing", "chat") is None


def test_user_data_never_crosses_the_bridge(router, registry: Path) -> None:
    assert router._remote_allowed(key_id="sparknet-node-0002", data_class="user", registry_path=registry) is False
    assert router._remote_allowed(key_id="master", data_class="user", registry_path=registry) is False


def test_peer_needs_model_route(router, registry: Path, tmp_path: Path) -> None:
    assert router._remote_allowed(key_id="sparknet-node-0002", data_class="fabric", registry_path=registry) is True
    assert router._remote_allowed(key_id="sparknet-node-0002", data_class="support", registry_path=registry) is True
    no_cap = tmp_path / "no-cap.json"
    data = json.loads(registry.read_text())
    data["authorizations"][0]["capabilities"] = ["telemetry"]
    no_cap.write_text(json.dumps(data), encoding="utf-8")
    assert router._remote_allowed(key_id="sparknet-node-0002", data_class="support", registry_path=no_cap) is False


def test_master_support_is_allowed(router, registry: Path) -> None:
    assert router._remote_allowed(key_id="master", data_class="support", registry_path=registry) is True
    assert router._remote_allowed(key_id="master", data_class="contract", registry_path=registry) is False

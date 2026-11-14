"""Federated memory is fabric/admin read-only and never a user-vault channel."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "shared" / "sparknet-memory-router.py"


@pytest.fixture(scope="module")
def router():
    return load_by_path("sparknet_memory_router_test", MODULE)


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "master_public_key_b64": "x",
                "authorizations": [
                    {
                        "identity": {"node_id": "sparknet-node-0002"},
                        "node_pubkey_b64": "x",
                        "capabilities": ["memory-federate"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_peer_fabric_is_allowed(router, registry: Path) -> None:
    assert router._remote_allowed(key_id="sparknet-node-0002", scope="fabric", registry=registry) is True


def test_user_short_term_and_master_are_refused(router, registry: Path) -> None:
    assert router._remote_allowed(key_id="sparknet-node-0002", scope="user", registry=registry) is False
    assert router._remote_allowed(key_id="sparknet-node-0002", scope="short_term", registry=registry) is False
    assert router._remote_allowed(key_id="master", scope="fabric", registry=registry) is False


def test_missing_capability_is_refused(router, registry: Path, tmp_path: Path) -> None:
    data = json.loads(registry.read_text())
    data["authorizations"][0]["capabilities"] = ["telemetry"]
    path = tmp_path / "no-cap.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert router._remote_allowed(key_id="sparknet-node-0002", scope="fabric", registry=path) is False

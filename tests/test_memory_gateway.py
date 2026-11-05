"""The Python gateway is the only thing that may talk to the Go memory store.

These tests pin the boundary: a signed grant is bound to the role vault, an
Open WebUI session is bound to that user's provisioned vault, and a local
control token is the only way to select an arbitrary allowed vault.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"
NOW = datetime.now(timezone.utc)


def _load(name: str, filename: str):
    path = SHARED / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


authz = _load("sparknet_authz_gateway_test", "sparknet-authz.py")
gateway_mod = _load("sparknet_memory_gateway_test", "sparknet-memory-gateway.py")


def b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


class MemoryHandler(BaseHTTPRequestHandler):
    calls: ClassVar[list[dict]] = []

    def log_message(self, fmt, *args):
        return

    def _reply(self, status=200, payload=None):
        raw = json.dumps(payload or {"ok": True}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.calls.append(
            {
                "path": self.path,
                "body": body,
                "token": self.headers.get("X-Sparknet-Memory-Token"),
            }
        )
        self._reply(200, {"ok": True, "echo": body})

    def do_GET(self):
        self.calls.append({"path": self.path, "body": None, "token": self.headers.get("X-Sparknet-Memory-Token")})
        self._reply(200, {"ok": True, "records": 0})


class WebUIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path != "/api/v1/auths/":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != "Bearer webui-token":
            self.send_error(401)
            return
        raw = json.dumps({"id": "user-1", "role": "user", "email": "u@example.test"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def stack(tmp_path: Path):
    master = Ed25519PrivateKey.generate()
    identity = {
        "node_id": "node-1",
        "role": "peer",
        "wireguard_public_key_b64": b64(b"\x01" * 32),
        "overlay_ipv4": "10.100.0.2",
        "requested_capabilities": ["p2p-sync"],
    }
    entry = authz.sign_authorization(identity, master, ["p2p-sync"])
    public = master.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    registry = {
        "schema_version": "1.0",
        "master_public_key_b64": b64(public),
        "authorizations": [entry],
    }
    (tmp_path / "registry.json").write_text(json.dumps(registry))
    (tmp_path / "identity.json").write_text(json.dumps(identity))
    role = tmp_path / "role"
    knowledge = tmp_path / "knowledge"
    (knowledge / "peer-user-1").mkdir(parents=True)
    role.mkdir()

    memory = ThreadingHTTPServer(("127.0.0.1", 0), MemoryHandler)
    threading.Thread(target=memory.serve_forever, daemon=True).start()
    webui = ThreadingHTTPServer(("127.0.0.1", 0), WebUIHandler)
    threading.Thread(target=webui.serve_forever, daemon=True).start()
    try:
        gateway = gateway_mod.Gateway(
            memory_url=f"http://127.0.0.1:{memory.server_port}",
            memory_token="memory-token",
            local_token="local-token",
            vault_roots=[str(role), str(knowledge)],
            user_vault_root=str(knowledge),
            webui_url=f"http://127.0.0.1:{webui.server_port}",
            state_dir=tmp_path / "state",
            registry_path=tmp_path / "registry.json",
            identity_path=tmp_path / "identity.json",
        )
        grant = authz.mint_grant(
            node_identity=identity,
            grant_id="GRANT-MEMORY-1",
            user_identity="U-1",
            conversation_key="02020202-0202-0202-0202-020202020202-9",
            capabilities=["p2p-sync"],
            vault_scope=["06_Projects"],
            ttl_minutes=60,
            nonce="memory-nonce-1",
            master_private_key=master,
            registry=registry,
            now=NOW,
        )
        yield {
            "gateway": gateway,
            "role": role,
            "knowledge": knowledge,
            "grant": base64.urlsafe_b64encode(json.dumps(grant).encode()).decode(),
            "memory": memory,
        }
    finally:
        memory.shutdown()
        webui.shutdown()
        memory.server_close()
        webui.server_close()


def test_grant_is_bound_to_the_role_vault_and_user(stack):
    MemoryHandler.calls.clear()
    body = {
        "vault_path": str(stack["knowledge"] / "peer-user-1"),
        "record": {
            "memory_type": "episodic",
            "text": "a grant must not read a sibling vault",
            "source_kind": "session",
            "scope": {"user_id": "somebody-else"},
        },
    }
    headers = {"authorization": f"Bearer {stack['grant']}"}
    with pytest.raises(gateway_mod.GatewayError) as refusal:
        stack["gateway"].handle("POST", "/v1/memory/remember", headers, body)
    assert refusal.value.code == "vault-forbidden"


def test_grant_forces_the_user_scope(stack):
    MemoryHandler.calls.clear()
    body = {
        "record": {
            "memory_type": "episodic",
            "text": "scoped",
            "source_kind": "session",
            "scope": {"user_id": "attacker"},
        }
    }
    headers = {"authorization": f"Bearer {stack['grant']}"}
    status, payload = stack["gateway"].handle("POST", "/v1/memory/remember", headers, body)
    assert status == 200 and payload["ok"] is True
    call = MemoryHandler.calls[-1]
    assert call["body"]["record"]["scope"]["user_id"] == "U-1"
    assert call["body"]["vault_path"] == str(stack["role"])
    assert call["token"] == "memory-token"


def test_webui_token_is_bound_to_the_users_vault(stack):
    MemoryHandler.calls.clear()
    body = {"vault_path": "/etc", "record": {"memory_type": "episodic", "text": "x", "source_kind": "session"}}
    headers = {"authorization": "Bearer webui-token"}
    status, payload = stack["gateway"].handle("POST", "/v1/memory/remember", headers, body)
    assert status == 200 and payload["ok"] is True
    call = MemoryHandler.calls[-1]
    assert call["body"]["vault_path"] == str(stack["knowledge"] / "peer-user-1")
    assert call["body"]["record"]["scope"]["user_id"] == "user-1"


def test_local_token_can_select_an_allowed_vault(stack):
    MemoryHandler.calls.clear()
    body = {"record": {"memory_type": "episodic", "text": "local", "source_kind": "session"}}
    headers = {
        "x-sparknet-local-token": "local-token",
        "x-sparknet-vault-path": str(stack["role"]),
    }
    status, payload = stack["gateway"].handle("POST", "/v1/memory/remember", headers, body)
    assert status == 200 and payload["ok"] is True
    assert MemoryHandler.calls[-1]["body"]["vault_path"] == str(stack["role"])


def test_admin_inspection_requires_the_local_token(stack):
    with pytest.raises(gateway_mod.GatewayError) as refusal:
        stack["gateway"].handle(
            "POST",
            "/v1/admin/inspect",
            {"authorization": "Bearer webui-token"},
            {"query": "x"},
        )
    assert refusal.value.code in {"admin-refused", "vault-forbidden"}

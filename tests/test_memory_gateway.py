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
from datetime import datetime, timedelta, timezone
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
        empty = authz.mint_grant(
            node_identity=identity,
            grant_id="GRANT-MEMORY-EMPTY",
            user_identity="U-1",
            conversation_key="02020202-0202-0202-0202-020202020202-9",
            capabilities=["p2p-sync"],
            vault_scope=[],
            ttl_minutes=60,
            nonce="memory-nonce-2",
            master_private_key=master,
            registry=registry,
            now=NOW,
        )
        yield {
            "gateway": gateway,
            "role": role,
            "knowledge": knowledge,
            "grant": base64.urlsafe_b64encode(json.dumps(grant).encode()).decode(),
            "grant_empty": base64.urlsafe_b64encode(json.dumps(empty).encode()).decode(),
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


def test_authority_surfaces_are_not_readable_listed_or_searched(stack):
    role = stack["role"]
    (role / "00_System").mkdir()
    (role / "00_System" / "secret.md").write_text("SECRET AUTHORITY", encoding="utf-8")
    (role / "blockchain").mkdir()
    (role / "blockchain" / "ledger.json").write_text("SECRET LEDGER", encoding="utf-8")
    (role / "05_Knowledge").mkdir()
    (role / "05_Knowledge" / "note.md").write_text("hello world", encoding="utf-8")
    gateway = stack["gateway"]

    with pytest.raises(gateway_mod.GatewayError) as refused:
        gateway.vault_read(str(role), "00_System/secret.md")
    assert refused.value.code == "authority-surface"

    listed = gateway.vault_list(str(role))
    assert "00_System/secret.md" not in listed["paths"]
    assert "blockchain/ledger.json" not in listed["paths"]
    assert gateway.vault_search(str(role), "SECRET")["hits"] == []
    assert gateway.vault_read(str(role), "05_Knowledge/note.md")["content"] == "hello world"


def test_vault_graph_is_a_filtered_projection(stack):
    role = stack["role"]
    (role / "05_Knowledge").mkdir(exist_ok=True)
    (role / "05_Knowledge" / "a.md").write_text("# Alpha\n\nSee [[05_Knowledge/b]].\n", encoding="utf-8")
    (role / "05_Knowledge" / "b.md").write_text("# Beta\n", encoding="utf-8")
    (role / "00_System").mkdir(exist_ok=True)
    (role / "00_System" / "secret.md").write_text("# Secret\n[[05_Knowledge/a]]\n", encoding="utf-8")
    headers = {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)}
    status, payload = stack["gateway"].handle("GET", "/v1/vault/graph", headers, {})
    assert status == 200 and payload["ok"] is True
    graph = payload["graph"]
    paths = {node["path"] for node in graph["nodes"]}
    assert "05_Knowledge/a.md" in paths
    assert "00_System/secret.md" not in paths
    assert any(edge["target"].endswith("05_Knowledge/b.md") for edge in graph["edges"])


def test_grant_scope_narrows_read_list_search_and_graph(stack):
    role = stack["role"]
    (role / "06_Projects").mkdir()
    (role / "06_Projects" / "in.md").write_text("# In\n", encoding="utf-8")
    (role / "02_Daily").mkdir()
    (role / "02_Daily" / "secret.md").write_text("# Secret\n", encoding="utf-8")
    headers = {"authorization": f"Bearer {stack['grant']}"}
    gateway = stack["gateway"]

    status, payload = gateway.handle("GET", "/v1/vault/read", headers, {"path": "06_Projects/in.md"})
    assert status == 200 and payload["ok"] is True
    with pytest.raises(gateway_mod.GatewayError) as refused:
        gateway.handle("GET", "/v1/vault/read", headers, {"path": "02_Daily/secret.md"})
    assert refused.value.code == "scope-refused"

    _, listed = gateway.handle("GET", "/v1/vault/list", headers, {})
    assert "06_Projects/in.md" in listed["paths"]
    assert "02_Daily/secret.md" not in listed["paths"]
    _, searched = gateway.handle("GET", "/v1/vault/search", headers, {"query": "secret"})
    assert searched["hits"] == []
    _, graph = gateway.handle("GET", "/v1/vault/graph", headers, {})
    assert {node["path"] for node in graph["graph"]["nodes"]} == {"06_Projects/in.md"}


def test_empty_grant_scope_denies_knowledge_reads(stack):
    role = stack["role"]
    (role / "06_Projects").mkdir()
    (role / "06_Projects" / "in.md").write_text("# In\n", encoding="utf-8")
    headers = {"authorization": f"Bearer {stack['grant_empty']}"}
    with pytest.raises(gateway_mod.GatewayError) as refused:
        stack["gateway"].handle("GET", "/v1/vault/read", headers, {"path": "06_Projects/in.md"})
    assert refused.value.code == "scope-refused"
    _, listed = stack["gateway"].handle("GET", "/v1/vault/list", headers, {})
    assert listed["paths"] == []


def test_personal_names_are_not_listed_searched_or_graphed(stack):
    role = stack["role"]
    (role / "MEMORY.md").write_text("SECRET MEMORY", encoding="utf-8")
    (role / "secrets-index.json").write_text("SECRET INDEX", encoding="utf-8")
    (role / "05_Knowledge").mkdir(exist_ok=True)
    (role / "05_Knowledge" / "note.md").write_text("hello", encoding="utf-8")
    gateway = stack["gateway"]
    _, listed = gateway.handle("GET", "/v1/vault/list", {"x-sparknet-local-token": "local-token"}, {})
    assert "MEMORY.md" not in listed["paths"]
    assert "secrets-index.json" not in listed["paths"]
    _, searched = gateway.handle(
        "GET", "/v1/vault/search", {"x-sparknet-local-token": "local-token"}, {"query": "SECRET"}
    )
    assert searched["hits"] == []
    _, graph = gateway.handle("GET", "/v1/vault/graph", {"x-sparknet-local-token": "local-token"}, {})
    assert "MEMORY.md" not in {node["path"] for node in graph["graph"]["nodes"]}


def test_capture_cannot_escape_its_prefix_and_requires_post(stack):
    role = stack["role"]
    headers = {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)}
    with pytest.raises(gateway_mod.GatewayError) as refused:
        stack["gateway"].handle(
            "POST",
            "/v1/vault/capture",
            headers,
            {"title": "escape", "body": "x", "target": "01_Inbox/../rootnote"},
        )
    assert refused.value.code == "vault-forbidden"
    with pytest.raises(gateway_mod.GatewayError) as method:
        stack["gateway"].handle(
            "GET",
            "/v1/vault/capture",
            headers,
            {"title": "get", "body": "x"},
        )
    assert method.value.code == "method-not-allowed"


def test_grant_nonce_is_single_use_for_mutating_routes(stack):
    MemoryHandler.calls.clear()
    headers = {"authorization": f"Bearer {stack['grant']}"}
    body = {"record": {"memory_type": "episodic", "text": "once", "source_kind": "session"}}
    status, _payload = stack["gateway"].handle("POST", "/v1/memory/remember", headers, body)
    assert status == 200
    with pytest.raises(gateway_mod.GatewayError) as refused:
        stack["gateway"].handle("POST", "/v1/memory/remember", headers, body)
    assert refused.value.code == "grant-refused"


def test_vault_hybrid_returns_semantic_and_agentic_sets(stack):
    role = stack["role"]
    (role / "05_Knowledge").mkdir(exist_ok=True)
    (role / "05_Knowledge" / "alpha.md").write_text("# Alpha\n\nAlpha links [[05_Knowledge/beta]].\n", encoding="utf-8")
    (role / "05_Knowledge" / "beta.md").write_text("# Beta\n\nBeta is linked.\n", encoding="utf-8")
    headers = {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)}
    status, payload = stack["gateway"].handle("GET", "/v1/vault/hybrid", headers, {"query": "alpha"})
    assert status == 200 and payload["ok"] is True
    bundle = payload["bundle"]
    assert bundle["semantic"][0]["path"] == "05_Knowledge/alpha.md"
    assert bundle["agentic"][0]["tool"] == "vault_graph"
    assert "05_Knowledge/beta.md" in bundle["agentic"][0]["result"]["neighbors"]
    assert "Semantic results" in payload["rendered"]
    assert "Agentic results" in payload["rendered"]


def test_graph_and_hybrid_use_the_o1_classification(stack):
    role = stack["role"]
    (role / "05_Knowledge").mkdir(exist_ok=True)
    (role / "05_Knowledge" / "classified.md").write_text(
        "---\nclassification: restricted\ndepartment: red\n---\n# Classified\n\nclassified body\n",
        encoding="utf-8",
    )
    headers = {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)}
    gateway = stack["gateway"]
    status, payload = gateway.handle("GET", "/v1/vault/graph", headers, {})
    assert status == 200 and payload["ok"] is True
    node = next(row for row in payload["graph"]["nodes"] if row["path"] == "05_Knowledge/classified.md")
    assert node["classification"] == "restricted"
    assert node["department"] == "red"

    status, payload = gateway.handle("GET", "/v1/vault/hybrid", headers, {"query": "classified"})
    assert status == 200 and payload["ok"] is True
    assert payload["bundle"]["semantic"][0]["classification"] == "restricted"
    assert payload["bundle"]["department"] == "red"


def test_unknown_o1_classification_is_refused(stack):
    role = stack["role"]
    (role / "05_Knowledge").mkdir(exist_ok=True)
    (role / "05_Knowledge" / "bad.md").write_text(
        "---\nclassification: secret\n---\n# Bad\n",
        encoding="utf-8",
    )
    headers = {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)}
    with pytest.raises(gateway_mod.GatewayError) as refused:
        stack["gateway"].handle("GET", "/v1/vault/graph", headers, {})
    assert refused.value.code == "unknown-classification"


def test_collab_room_and_message_round_trip(stack):
    role = stack["role"]
    headers = {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)}
    gateway = stack["gateway"]
    status, created = gateway.handle(
        "POST",
        "/v1/collab/room",
        headers,
        {"room_id": "room-test", "classification": "internal"},
    )
    assert status == 200 and created["room"]["room_id"] == "room-test"
    assert (role / "01_Inbox" / "collab" / "room-test" / "room.json").is_file()

    status, posted = gateway.handle(
        "POST",
        "/v1/collab/message",
        headers,
        {"room_id": "room-test", "text": "hello"},
    )
    assert status == 200 and posted["message"]["text"] == "hello"
    status, listed = gateway.handle("GET", "/v1/collab/messages", headers, {"room_id": "room-test"})
    assert status == 200 and listed["messages"][0]["text"] == "hello"
    status, rooms = gateway.handle("GET", "/v1/collab/rooms", headers, {})
    assert status == 200 and rooms["rooms"][0]["room_id"] == "room-test"


def test_exec_validation_route_is_local_only(stack):
    role = stack["role"]
    request = {
        "schema_version": "sparknet-exec-request/1",
        "request_id": "req-1",
        "node_id": "sparknet-node-0002",
        "user_id": "user-1",
        "argv": ["pwd"],
        "cwd": "05_Knowledge",
        "env": {"PATH": "/usr/bin"},
        "timeout_seconds": 10,
        "operator_os": {"uid": 1000, "euid": 1000, "username": "raxxar", "groups": ["users"], "is_root": False},
        "capabilities": [],
        "nonce": "nonce-1",
        "issued_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
        "signature_b64": "test-signature",
    }
    headers = {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)}
    status, payload = stack["gateway"].handle("POST", "/v1/exec/validate", headers, {"request": request})
    assert status == 200
    assert payload["executed"] is False
    assert payload["request"]["argv"] == ["pwd"]
    with pytest.raises(gateway_mod.GatewayError) as refused:
        stack["gateway"].handle(
            "POST",
            "/v1/exec/validate",
            {"authorization": f"Bearer {stack['grant']}"},
            {"request": request},
        )
    assert refused.value.code == "local-only"


def test_collab_room_id_cannot_escape_the_collab_root(stack):
    role = stack["role"]
    headers = {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)}
    with pytest.raises(gateway_mod.GatewayError) as refused:
        stack["gateway"].handle(
            "POST",
            "/v1/collab/room",
            headers,
            {"room_id": "../../escape", "classification": "internal"},
        )
    assert refused.value.code == "bad-room-id"
    assert not (role.parent / "escape").exists()


def test_capture_respects_the_grant_scope_and_burns_the_nonce(stack):
    role = stack["role"]
    (role / "06_Projects").mkdir()
    headers = {"authorization": f"Bearer {stack['grant']}"}
    with pytest.raises(gateway_mod.GatewayError) as refused:
        stack["gateway"].handle(
            "POST",
            "/v1/vault/capture",
            headers,
            {"title": "outside", "body": "x", "target": "01_Inbox/outside.md"},
        )
    assert refused.value.code == "scope-refused"
    assert not (role / "01_Inbox" / "outside.md").exists()
    with pytest.raises(gateway_mod.GatewayError) as replay:
        stack["gateway"].handle(
            "POST",
            "/v1/vault/capture",
            headers,
            {"title": "outside", "body": "x", "target": "01_Inbox/outside.md"},
        )
    assert replay.value.code == "grant-refused"


def test_capture_redacts_secret_shaped_text(stack):
    role = stack["role"]
    headers = {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)}
    status, payload = stack["gateway"].handle(
        "POST",
        "/v1/vault/capture",
        headers,
        {
            "title": "token sk-abcdefghijklmnopqrstuvwx",
            "body": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n",
        },
    )
    assert status == 200 and payload["redacted"] is True
    text = (role / payload["path"]).read_text()
    assert "sk-abcdefghijklmnopqrstuvwx" not in text
    assert "abcdefghijklmnopqrstuvwxyz123456" not in text
    assert "[redacted key]" in text
    assert "Bearer [redacted]" in text


def test_collab_list_messages_rejects_room_traversal(stack):
    role = stack["role"]
    with pytest.raises(gateway_mod.GatewayError) as refused:
        stack["gateway"].handle(
            "GET",
            "/v1/collab/messages",
            {"x-sparknet-local-token": "local-token", "x-sparknet-vault-path": str(role)},
            {"room_id": "../../peer-user-1/01_Inbox/collab/room"},
        )
    assert refused.value.code == "bad-room-id"


def test_vault_walk_does_not_follow_directory_symlinks(stack):
    role = stack["role"]
    victim = stack["knowledge"] / "peer-user-1" / "05_Knowledge"
    victim.mkdir(parents=True, exist_ok=True)
    (victim / "secret.md").write_text("# another user's page\n", encoding="utf-8")
    (role / "05_Knowledge").mkdir()
    (role / "05_Knowledge" / "leak").symlink_to(victim, target_is_directory=True)
    listed = stack["gateway"].vault_list(str(role), prefix="05_Knowledge")
    assert listed["paths"] == []

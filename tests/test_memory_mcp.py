"""The OpenCode adapter is an MCP server, not an auto-discovered plugin.

OpenCode 1.18.35 hangs on any plugin in a role worktree, so the memory adapter
must load through `opencode.json`'s `mcp` block. These tests pin the protocol
handshake and the fact that the role configs use MCP, not `.opencode/plugin*`.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration


ROOT = Path(__file__).resolve().parent.parent
MCP = ROOT / "shared" / "sparknet-memory-mcp.py"


def _load():
    return load_by_path("sparknet_memory_mcp_test", MCP)


mcp = _load()


class _Gateway(BaseHTTPRequestHandler):
    calls: ClassVar[list[dict]] = []

    def log_message(self, *args):
        return

    def _reply(self, payload):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.calls.append({"path": self.path, "token": self.headers.get("X-Sparknet-Local-Token")})
        self._reply({"ok": True, "records": 2})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.calls.append(
            {
                "path": self.path,
                "token": self.headers.get("X-Sparknet-Local-Token"),
                "vault": self.headers.get("X-Sparknet-Vault-Path"),
                "body": body,
            }
        )
        self._reply({"ok": True, "hits": [{"record": {"text": "one"}}]})


def test_initialize_and_tool_list():
    server = mcp.MemoryMCP(Path("/tmp/vault"), "http://127.0.0.1:1", "token-1234567890", "U-1")
    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["serverInfo"]["name"] == "sparknet-memory"
    listing = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in listing["result"]["tools"]}
    assert {"memory_search", "memory_remember", "memory_status", "memory_forget", "project_delegate"} <= names


def test_missing_token_is_a_tool_error_not_a_crash():
    server = mcp.MemoryMCP(Path("/tmp/vault"), "http://127.0.0.1:1", "", "U-1")
    response = server.handle(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_status", "arguments": {}}}
    )
    assert response["result"]["isError"] is True
    assert "memory.local.token" in response["result"]["content"][0]["text"]


def test_tool_call_forwards_scoped_vault_and_token(tmp_path: Path):
    server, thread = ThreadingHTTPServer(("127.0.0.1", 0), _Gateway), None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _Gateway.calls.clear()
        client = mcp.MemoryMCP(tmp_path, f"http://127.0.0.1:{server.server_port}", "token-1234567890", "U-1")
        response = client.handle(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "memory_search", "arguments": {"query": "release"}},
            }
        )
        assert response["result"]["isError"] is False
        call = _Gateway.calls[-1]
        assert call["path"] == "/v1/memory/query"
        assert call["token"] == "token-1234567890"
        assert call["vault"] is None, "the local token is scoped by the gateway; no host path is sent"
        assert call["body"]["scope"]["user_id"] == "U-1"
    finally:
        server.shutdown()
        server.server_close()


def test_role_configs_use_mcp_and_no_plugin_directory():
    for role in ("peer", "master"):
        config = json.loads((ROOT / f"{role}-node" / "opencode.json").read_text())
        assert "sparknet-memory" in config["mcp"]
        assert config["mcp"]["sparknet-memory"]["enabled"] is True
        assert not (ROOT / f"{role}-node" / ".opencode" / "plugins").exists(), (
            "a role-local plugin directory reintroduces the opencode 1.18.35 hang"
        )


def test_non_object_request_and_malformed_params_do_not_crash():
    server = mcp.MemoryMCP(Path("/tmp/vault"), "http://127.0.0.1:1", "token-1234567890", "U-1")
    assert server.handle(["not", "an", "object"])["error"]["code"] == -32600
    response = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": []})
    assert response["result"]["isError"] is True

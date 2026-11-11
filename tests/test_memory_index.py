"""The vault indexer CLI is a thin, vault-scoped gateway call."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

pytestmark = pytest.mark.integration


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-memory-index.py"


class Gateway(BaseHTTPRequestHandler):
    calls: ClassVar[list[dict]] = []

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.calls.append({"path": self.path, "body": body})
        raw = json.dumps({"ok": True, "documents": 2}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_index_cli_forwards_vault_and_scope(tmp_path: Path):
    vault = tmp_path / "vault"
    state = tmp_path / "state"
    vault.mkdir()
    state.mkdir()
    (state / "memory.local.token").write_text("local-token-1234567890\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = {
            **os.environ,
            "SPARKNET_STATE_DIR": str(state),
            "SPARKNET_MEMORY_GATEWAY_URL": f"http://127.0.0.1:{server.server_port}",
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(vault), "--user", "U-1", "--project", "alpha"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        call = Gateway.calls[-1]
        assert call["path"] == "/v1/memory/index"
        assert call["body"]["vault_path"] == str(vault)
        assert call["body"]["user_id"] == "U-1"
        assert call["body"]["project_id"] == "alpha"
    finally:
        server.shutdown()
        server.server_close()

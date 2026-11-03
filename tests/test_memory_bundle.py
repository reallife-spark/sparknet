"""Memory bundles are bounded, reviewable payloads — not a new share type."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-memory-bundle.py"
BUNDLE = {
    "schema": "sparknet-memory-bundle/1",
    "vault_id": "v1",
    "records": [{"memory_type": "episodic", "text": "one"}],
}


class Gateway(BaseHTTPRequestHandler):
    calls: ClassVar[list[dict]] = []

    def log_message(self, *args):
        return

    def _reply(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.calls.append({"path": self.path, "body": body})
        if self.path == "/v1/memory/export":
            self._reply(200, BUNDLE)
        else:
            self._reply(200, {"ok": True, "vault_id": "v1", "result": {"imported": 1}})


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False)


def test_validate_rejects_short_term(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "sparknet-memory-bundle/1", "records": [{"memory_type": "short_term"}]}))
    result = _run(["validate", str(bad)], os.environ.copy())
    assert result.returncode != 0
    assert "short_term" in result.stderr


def test_export_stage_import(tmp_path: Path):
    vault = tmp_path / "vault"
    state = tmp_path / "state"
    vault.mkdir()
    state.mkdir()
    (state / "memory.local.token").write_text("local-token-1234567890\n")
    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    env = {
        **os.environ,
        "SPARKNET_STATE_DIR": str(state),
        "SPARKNET_MEMORY_GATEWAY_URL": f"http://127.0.0.1:{gateway.server_port}",
    }
    try:
        Gateway.calls.clear()
        bundle = tmp_path / "bundle.json"
        result = _run(["export", "--vault", str(vault), "--out", str(bundle)], env)
        assert result.returncode == 0, result.stderr
        assert json.loads(bundle.read_text())["records"][0]["text"] == "one"
        assert Gateway.calls[-1]["body"]["vault_path"] == str(vault)

        inbox = tmp_path / "01_Inbox" / "share-1"
        result = _run(["stage", "--bundle", str(bundle), "--inbox", str(inbox)], env)
        assert result.returncode == 0, result.stderr
        assert oct((inbox / "memory-bundle.json").stat().st_mode & 0o777) == "0o600"

        result = _run(["import", "--vault", str(vault), "--bundle", str(bundle)], env)
        assert result.returncode == 0, result.stderr
        assert Gateway.calls[-1]["path"] == "/v1/memory/import"
        assert Gateway.calls[-1]["body"]["bundle"]["schema"] == "sparknet-memory-bundle/1"
    finally:
        gateway.shutdown()
        gateway.server_close()

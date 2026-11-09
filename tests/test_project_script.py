"""06_Projects lifecycle: create a signed project, file a signed report.

The script is exercised as a subprocess against a throwaway vault and a fake
memory gateway. It must not need a live node; the report signature is the same
provenance implementation the vault uses.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-project.py"
PEER = ROOT / "peer-node"
SHARED = ROOT / "shared"


def _load(name: str, filename: str):
    return load_by_path(name, SHARED / filename)


prov = _load("sparknet_provenance_project_test", "sparknet-provenance.py")


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

    def do_GET(self):
        self.calls.append({"method": "GET", "path": self.path})
        if "/v1/delegates/runs/run-1" in self.path:
            self._reply(
                200,
                {
                    "ok": True,
                    "run": {
                        "run_id": "run-1",
                        "status": "succeeded",
                        "harness": "command",
                        "task": {"description": "compare three options"},
                        "result": {
                            "summary": "Option B wins on latency.",
                            "files_changed": ["NOTES/option-b.md"],
                            "verification": "pytest -q",
                        },
                        "error": "",
                    },
                },
            )
            return
        self._reply(200, {"ok": True, "runs": []})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.calls.append({"method": "POST", "path": self.path, "body": body})
        self._reply(202, {"ok": True, "runs": [{"run_id": "run-1", "plan_id": "plan-1"}]})


def _run(script_args: list[str], vault: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--vault", str(vault), *script_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_project_and_report_lifecycle(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(PEER, vault, ignore=shutil.ignore_patterns(".git", ".state", ".opencode", "__pycache__"))
    state = tmp_path / "state"
    env = {**os.environ, "SPARKNET_STATE_DIR": str(state), "SPARKNET_OWNER_ID": "U-12345"}
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(state))
    monkeypatch.setenv("SPARKNET_OWNER_ID", "U-12345")
    prov.user_init(vault, owner_id="U-12345", force=True)

    created = _run(["new", "alpha", "--title", "Alpha project"], vault, env)
    assert created.returncode == 0, created.stderr
    project = vault / "06_Projects" / "alpha" / "PROJECT.md"
    plan = vault / "06_Projects" / "alpha" / "PLAN.md"
    assert prov.verify_note(project, vault=vault)[0] == "valid"
    assert prov.verify_note(plan, vault=vault)[0] == "valid"

    listed = _run(["list"], vault, env)
    assert listed.returncode == 0
    payload = json.loads(listed.stdout)
    assert payload["projects"][0]["project_id"] == "alpha"

    token = state / "memory.local.token"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("local-token-1234567890\n")
    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    try:
        env["SPARKNET_MEMORY_GATEWAY_URL"] = f"http://127.0.0.1:{gateway.server_port}"
        run = _run(["run", "alpha", "--task", "compare options"], vault, env)
        assert run.returncode == 0, run.stderr
        assert Gateway.calls[-1]["path"] == "/v1/delegates/plan"
        assert Gateway.calls[-1]["body"]["plan"]["project_id"] == "alpha"

        report = _run(["report", "alpha", "--run-id", "run-1", "--title", "Option memo"], vault, env)
        assert report.returncode == 0, report.stderr
        report_path = vault / "06_Projects" / "alpha" / "REPORTS" / report_path_name(report)
        assert report_path.is_file()
        assert "Option B wins on latency." in report_path.read_text()
        assert prov.verify_note(report_path, vault=vault)[0] == "valid"

        status = _run(["status", "alpha"], vault, env)
        assert status.returncode == 0, status.stderr
        assert json.loads(status.stdout)["project_id"] == "alpha"
    finally:
        gateway.shutdown()
        gateway.server_close()


def report_path_name(completed: subprocess.CompletedProcess[str]) -> str:
    payload = json.loads(completed.stdout)
    return Path(payload["report"]).name

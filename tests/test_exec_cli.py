"""The exec CLI validates a request and never executes it."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-exec.py"


def _request():
    now = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=1)
    return {
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
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
        "signature_b64": "test-signature",
    }


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_exec_cli_help():
    result = _run("--help")
    assert result.returncode == 0
    assert "validate" in result.stdout


def test_exec_cli_validates_without_executing(tmp_path):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_request()), encoding="utf-8")
    result = _run("validate", "--request", str(path), "--allow-unverified")
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["executed"] is False
    assert payload["request"]["argv"] == ["pwd"]

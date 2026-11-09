"""The execution daemon verifies, binds and runs one argv vector; no shell."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-exec-daemon.py"
SHARED = ROOT / "shared"


def _load(name: str, filename: str):
    return load_by_path(name, SHARED / filename)


authz = _load("exec_daemon_authz_test", "sparknet-authz.py")
exec_rpc = _load("exec_daemon_rpc_test", "sparknet-exec-rpc.py")


def _request(private_key, *, argv=None, signature=None):
    now = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=1)
    request = exec_rpc.make_request(
        request_id="req-1",
        node_id="sparknet-node-0002",
        user_id="user-1",
        argv=argv or ["pwd"],
        cwd="sub",
        env={"HOME": "/home/raxxar"},
        timeout_seconds=10,
        operator_os={
            "uid": os.getuid(),
            "euid": os.geteuid(),
            "username": "operator",
            "groups": [],
            "is_root": os.geteuid() == 0,
        },
        capabilities=[],
        nonce="nonce-1",
        issued_at=now,
        expires_at=now + timedelta(minutes=15),
        signature_b64=signature or "placeholder",
        verified=True,
    )
    if signature is None:
        request["signature_b64"] = authz.sign_bytes(private_key, exec_rpc.request_message(request))
    return request


def _start_daemon(tmp_path, node_pub, daemon_key, *, allow_exec=True):
    socket_path = tmp_path / "exec.sock"
    vault = tmp_path / "vault"
    (vault / "sub").mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(SCRIPT),
        "--socket",
        str(socket_path),
        "--vault-root",
        str(vault),
        "--node-pub",
        str(node_pub),
        "--signing-key",
        str(daemon_key),
        "--once",
    ]
    if allow_exec:
        policy = tmp_path / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "schema": "sparknet-exec-policy/1",
                    "allowed_argv": [{"binary": "pwd", "args": []}],
                    "cwd_roots": ["sub"],
                    "env_allow": ["HOME"],
                    "max_timeout_seconds": 30,
                    "max_output_bytes": 65536,
                    "approval_ttl_seconds": 300,
                    "audit_path": ".state/exec-audit.jsonl",
                }
            )
        )
        command.extend(["--policy", str(policy), "--allow-exec"])
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        if socket_path.exists():
            return process, socket_path, vault
        if process.poll() is not None:
            break
        time.sleep(0.05)
    out, err = process.communicate(timeout=5)
    raise AssertionError(f"daemon did not start: {out}\n{err}")


def _call(socket_path, request):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(10)
    client.connect(str(socket_path))
    try:
        client.sendall(json.dumps(request).encode("utf-8") + b"\n")
        payload = b""
        while not payload.endswith(b"\n"):
            chunk = client.recv(4096)
            if not chunk:
                break
            payload += chunk
    finally:
        client.close()
    return json.loads(payload.decode("utf-8"))


def test_daemon_runs_argv_and_signs_the_response(tmp_path):
    node_private_b64, node_public_b64 = authz.generate_keypair()
    daemon_private_b64, daemon_public_b64 = authz.generate_keypair()
    node_private = authz.private_key_from_b64(node_private_b64)
    daemon_private = tmp_path / "daemon.key"
    daemon_private.write_text(daemon_private_b64, encoding="utf-8")
    node_pub = tmp_path / "node.pub"
    node_pub.write_text(node_public_b64, encoding="utf-8")
    process, socket_path, vault = _start_daemon(tmp_path, node_pub, daemon_private)
    try:
        result = _call(socket_path, _request(node_private))
    finally:
        process.wait(timeout=10)
    assert result["ok"] is True, result
    response = result["response"]
    assert response["exit_code"] == 0
    assert str(vault / "sub") in response["stdout"]
    daemon_public = authz.public_key_from_b64(daemon_public_b64)
    assert authz.verify_signature(daemon_public, response["signature_b64"], exec_rpc.response_message(response))


def test_daemon_refuses_a_shell_vector_and_a_bad_signature(tmp_path):
    node_private_b64, node_public_b64 = authz.generate_keypair()
    daemon_private_b64, _daemon_public_b64 = authz.generate_keypair()
    node_private = authz.private_key_from_b64(node_private_b64)
    daemon_private = tmp_path / "daemon.key"
    daemon_private.write_text(daemon_private_b64, encoding="utf-8")
    node_pub = tmp_path / "node.pub"
    node_pub.write_text(node_public_b64, encoding="utf-8")

    process, socket_path, _vault = _start_daemon(tmp_path, node_pub, daemon_private)
    try:
        result = _call(socket_path, _request(node_private, argv=["/bin/sh", "-c", "id"]))
    finally:
        process.wait(timeout=10)
    assert result["ok"] is False
    assert result["error"] == "bad-argv"

    process, socket_path, _vault = _start_daemon(tmp_path, node_pub, daemon_private)
    try:
        bad = _request(node_private, signature="not-a-signature")
        result = _call(socket_path, bad)
    finally:
        process.wait(timeout=10)
    assert result["ok"] is False
    assert result["error"] == "bad-signature"


def test_daemon_refuses_a_command_outside_the_allowlist(tmp_path):
    node_private_b64, node_public_b64 = authz.generate_keypair()
    daemon_private_b64, _ = authz.generate_keypair()
    node_private = authz.private_key_from_b64(node_private_b64)
    daemon_private = tmp_path / "daemon.key"
    daemon_private.write_text(daemon_private_b64)
    node_pub = tmp_path / "node.pub"
    node_pub.write_text(node_public_b64)
    process, socket_path, _vault = _start_daemon(tmp_path, node_pub, daemon_private)
    try:
        result = _call(socket_path, _request(node_private, argv=["id"]))
    finally:
        process.wait(timeout=10)
    assert result["ok"] is False
    assert result["error"] == "not-allowlisted"

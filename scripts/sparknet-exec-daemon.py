#!/usr/bin/env python3
"""User-privileged, argv-only execution daemon.

The daemon accepts one newline-delimited signed JSON request per Unix-socket
connection. It verifies the node signature, binds the request's operator_os to
the daemon's own OS identity, keeps cwd inside the configured vault root and
runs `argv` without a shell. A refusal is unsigned; a result is signed by the
daemon key. Run it only as the human whose permissions it should carry.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from sparknet_loader import load_shared

AUTHZ = load_shared("sparknet-authz.py", "sparknet_exec_daemon_authz")
EXEC = load_shared("sparknet-exec-rpc.py", "sparknet_exec_daemon_rpc")
MAX_REQUEST_BYTES = 1 << 20
SHELLS = {"sh", "bash", "dash", "zsh", "ksh", "fish", "csh", "tcsh"}


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _refusal(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


def _operator_matches(operator_os: dict[str, Any]) -> tuple[bool, str]:
    if operator_os.get("uid") != os.getuid() or operator_os.get("euid") != os.geteuid():
        return False, "operator OS uid/euid does not match this daemon"
    if bool(operator_os.get("is_root")) != (os.geteuid() == 0):
        return False, "operator is_root does not match this daemon"
    return True, ""


def _audit(path: Path, request: dict[str, Any], *, status: str, result: dict[str, Any] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {
        "request_id": request.get("request_id"),
        "node_id": request.get("node_id"),
        "user_id": request.get("user_id"),
        "argv": request.get("argv"),
        "cwd": request.get("cwd"),
        "status": status,
        "at": _iso(),
    }
    if result:
        record.update(
            {
                "exit_code": result.get("exit_code"),
                "stdout_bytes": len(str(result.get("stdout") or "").encode()),
                "stderr_bytes": len(str(result.get("stderr") or "").encode()),
                "truncated": bool(result.get("truncated")),
            }
        )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def _execute(
    request: dict[str, Any], *, vault_root: Path, max_output_bytes: int = EXEC.MAX_OUTPUT_BYTES
) -> dict[str, Any]:
    argv = request["argv"]
    executable = str(argv[0])
    if "/" in executable or "\\" in executable:
        return _refusal("bad-argv", "argv[0] must be a bare binary name")
    if executable.lower() in SHELLS:
        return _refusal("bad-argv", "a shell binary is not an allowed execution vector")
    cwd = (vault_root / request["cwd"]).resolve()
    try:
        cwd.relative_to(vault_root)
    except ValueError:
        return _refusal("bad-cwd", "cwd escapes the vault root")
    if not cwd.is_dir():
        return _refusal("bad-cwd", "cwd is not a directory")
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
    env.update({key: value for key, value in (request.get("env") or {}).items() if key != "PATH"})
    resolved = shutil.which(executable, path=env["PATH"])
    if not resolved:
        return _refusal("exec-failed", "binary not found on the trusted PATH")
    started = _iso()
    stdout = ""
    stderr = ""
    cut_out = False
    cut_err = False
    code = 0
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            process = subprocess.Popen(
                [resolved, *argv[1:]],
                cwd=str(cwd),
                env=env,
                shell=False,
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=request["timeout_seconds"])
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                code = 124
                stderr = f"execution timed out after {request['timeout_seconds']}s"
            out.seek(0)
            err.seek(0)
            stdout, cut_out = EXEC.truncate_output(out.read(max_output_bytes + 1), max_output_bytes)
            if not stderr:
                stderr, cut_err = EXEC.truncate_output(err.read(max_output_bytes + 1), max_output_bytes)
        except OSError as exc:
            return _refusal("exec-failed", str(exc))
    return {
        "ok": True,
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
        "started_at": started,
        "completed_at": _iso(),
        "truncated": bool(cut_out or cut_err),
    }


def _handle(
    raw: bytes,
    *,
    vault_root: Path,
    node_public: Any,
    signing_key: Any,
    allow_exec: bool,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        request = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _refusal("malformed", "request is not JSON")
    if not isinstance(request, dict):
        return _refusal("malformed", "request is not an object")
    try:
        normalised = EXEC.validate_request(request, verified=True)
    except EXEC.ExecError as exc:
        return _refusal(exc.code, exc.message)
    if not AUTHZ.verify_signature(node_public, normalised["signature_b64"], EXEC.request_message(normalised)):
        return _refusal("bad-signature", "request signature does not verify")
    matches, reason = _operator_matches(normalised["operator_os"])
    if not matches:
        return _refusal("operator-mismatch", reason)
    if not allow_exec:
        return _refusal("execution-disabled", "the daemon was started without --allow-exec")
    if policy is None:
        return _refusal("policy-missing", "execution requires a validated allowlist policy")
    if Path(normalised["argv"][0]).name.lower() in SHELLS:
        return _refusal("bad-argv", "a shell binary is not an allowed execution vector")
    allowed, reason = EXEC.policy_allows(normalised, policy)
    if not allowed:
        return _refusal(reason, f"request is not permitted by the execution policy: {reason}")
    audit_path = vault_root / policy["audit_path"]
    _audit(audit_path, normalised, status="started")
    result = _execute(normalised, vault_root=vault_root, max_output_bytes=policy["max_output_bytes"])
    _audit(audit_path, normalised, status="finished", result=result)
    if not result.get("ok"):
        return result
    response = EXEC.make_response(
        request_id=normalised["request_id"],
        node_id=normalised["node_id"],
        user_id=normalised["user_id"],
        exit_code=result["exit_code"],
        stdout=result["stdout"],
        stderr=result["stderr"],
        started_at=datetime.fromisoformat(result["started_at"].replace("Z", "+00:00")),
        completed_at=datetime.fromisoformat(result["completed_at"].replace("Z", "+00:00")),
        truncated=result["truncated"],
    )
    response["signature_b64"] = AUTHZ.sign_bytes(signing_key, EXEC.response_message(response))
    EXEC.validate_response(response)
    return {"ok": True, "response": response}


def _serve(socket_path: Path, handler: Any, *, once: bool) -> None:
    with contextlib.suppress(FileNotFoundError):
        socket_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    os.chmod(socket_path, 0o600)
    server.listen(8)
    try:
        while True:
            connection, _ = server.accept()
            with connection:
                stream = connection.makefile("rwb")
                line = stream.readline(MAX_REQUEST_BYTES + 1)
                if len(line) > MAX_REQUEST_BYTES:
                    payload = _refusal("too-large", "request exceeds the limit")
                else:
                    payload = handler(line.rstrip(b"\r\n"))
                stream.write(json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n")
                stream.flush()
            if once:
                return
    finally:
        server.close()
        with contextlib.suppress(OSError):
            socket_path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sparknet-exec-daemon", description="argv-only execution daemon")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--vault-root", required=True)
    parser.add_argument("--node-pub", required=True)
    parser.add_argument("--signing-key", required=True)
    parser.add_argument("--allow-exec", action="store_true", help="actually run requests; default is validate-only")
    parser.add_argument("--policy", help="execution allowlist JSON; required with --allow-exec")
    parser.add_argument("--once", action="store_true", help="serve one request then exit")
    args = parser.parse_args(argv)
    vault_root = Path(args.vault_root).resolve()
    if not vault_root.is_dir():
        print(f"sparknet-exec-daemon: vault root is not a directory: {vault_root}", file=sys.stderr)
        return 2
    try:
        node_public = AUTHZ.load_public_key(Path(args.node_pub))
        signing_key = AUTHZ.load_private_key(Path(args.signing_key))
    except (OSError, AUTHZ.AuthzError) as exc:
        print(f"sparknet-exec-daemon: {exc}", file=sys.stderr)
        return 2
    policy = None
    if args.policy:
        try:
            policy = EXEC.validate_policy(json.loads(Path(args.policy).read_text(encoding="utf-8")))
        except (OSError, ValueError, EXEC.ExecError) as exc:
            print(f"sparknet-exec-daemon: policy: {exc}", file=sys.stderr)
            return 2
    if args.allow_exec and policy is None:
        print("sparknet-exec-daemon: --allow-exec requires --policy", file=sys.stderr)
        return 2

    def handler(raw: bytes) -> dict[str, Any]:
        return _handle(
            raw,
            vault_root=vault_root,
            node_public=node_public,
            signing_key=signing_key,
            allow_exec=args.allow_exec,
            policy=policy,
        )

    _serve(Path(args.socket), handler, once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

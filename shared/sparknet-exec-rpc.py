#!/usr/bin/env python3
"""Signed argv-only execution contract.

A request is a vector, never a shell string. The daemon executes it under the
attested operator OS identity, inside the user's vault, with a bounded timeout
and bounded output. A signature proves provenance; it grants nothing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any

REQUEST_SCHEMA = "sparknet-exec-request/1"
POLICY_SCHEMA = "sparknet-exec-policy/1"
RESPONSE_SCHEMA = "sparknet-exec-response/1"
MAX_TIMEOUT_SECONDS = 300
MAX_REQUEST_TTL = 3600
CLOCK_SKEW = 300
MAX_OUTPUT_BYTES = 1 << 20
KNOWN_CAPABILITIES = (
    "telemetry",
    "p2p-sync",
    "push-receive",
    "guard-apply",
    "cluster-vote",
    "cluster-dispatch",
    "cluster-serve",
    "admin-supervise",
    "cross-department-share",
    "model-uplift",
    "memory-supervise",
)
ENV_ALLOW = (
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "TERM",
    "TMPDIR",
    "USER",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
)
REQUEST_SIGNED_FIELDS = (
    "schema_version",
    "request_id",
    "node_id",
    "user_id",
    "argv",
    "cwd",
    "env",
    "timeout_seconds",
    "operator_os",
    "capabilities",
    "nonce",
    "issued_at",
    "expires_at",
)


class ExecError(Exception):
    """A fail-closed execution refusal."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ExecError(code, message)


def _nonempty(value: Any, field: str, code: str = "malformed-request") -> str:
    _require(isinstance(value, str) and bool(value.strip()), code, f"{field} must be a non-empty string")
    return value.strip()


def _timestamp(value: Any, field: str) -> datetime:
    _require(isinstance(value, str) and bool(value.strip()), "malformed-request", f"{field} must be an ISO-8601 string")
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExecError("malformed-request", f"{field} is not a valid timestamp") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cwd(value: Any) -> str:
    _require(isinstance(value, str) and bool(value.strip()), "bad-cwd", "cwd must be a relative path")
    _require("\\" not in value and "\x00" not in value, "bad-cwd", "cwd contains an unsafe character")
    candidate = PurePosixPath(value.strip())
    _require(
        not candidate.is_absolute() and not any(part in ("..", "") for part in candidate.parts),
        "bad-cwd",
        "cwd escapes the user vault",
    )
    return candidate.as_posix()


def _argv(value: Any) -> list[str]:
    _require(isinstance(value, (list, tuple)) and bool(value), "bad-argv", "argv must be a non-empty list")
    argv = []
    for item in value:
        _require(
            isinstance(item, str) and item != "" and "\x00" not in item,
            "bad-argv",
            "argv entries must be non-empty strings without NUL",
        )
        argv.append(item)
    return argv


def _env(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    _require(isinstance(value, Mapping), "bad-env", "env must be an object")
    result = {}
    for key, item in value.items():
        _require(isinstance(key, str) and key in ENV_ALLOW, "bad-env", f"env key {key!r} is not allow-listed")
        _require(isinstance(item, str), "bad-env", "env values must be strings")
        result[key] = item
    return result


def _operator_os(value: Any) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "bad-operator-os", "operator_os is required")
    uid = value.get("uid")
    euid = value.get("euid")
    _require(
        isinstance(uid, int) and not isinstance(uid, bool) and uid >= 0, "bad-operator-os", "operator_os.uid is invalid"
    )
    _require(
        isinstance(euid, int) and not isinstance(euid, bool) and euid >= 0,
        "bad-operator-os",
        "operator_os.euid is invalid",
    )
    username = _nonempty(value.get("username"), "operator_os.username", "bad-operator-os")
    groups = value.get("groups")
    _require(
        isinstance(groups, (list, tuple)) and all(isinstance(group, str) for group in groups),
        "bad-operator-os",
        "operator_os.groups must be a list of strings",
    )
    is_root = value.get("is_root")
    _require(isinstance(is_root, bool), "bad-operator-os", "operator_os.is_root must be a boolean")
    return {
        "uid": uid,
        "euid": euid,
        "username": username,
        "groups": sorted(set(groups)),
        "is_root": is_root,
    }


def _capabilities(value: Any) -> list[str]:
    _require(
        isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value),
        "bad-capabilities",
        "capabilities must be a list of strings",
    )
    unknown = sorted(set(value) - set(KNOWN_CAPABILITIES))
    _require(not unknown, "bad-capabilities", f"unknown capabilities: {', '.join(unknown)}")
    return sorted(set(value))


def make_request(
    *,
    request_id: str,
    node_id: str,
    user_id: str,
    argv: Sequence[str],
    operator_os: Mapping[str, Any],
    nonce: str,
    cwd: str = ".",
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 30,
    capabilities: Sequence[str] = (),
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
    ttl_seconds: int = 60,
    signature_b64: str | None = None,
    verified: bool = False,
) -> dict[str, Any]:
    if verified is not True:
        raise ExecError("subject-unverified", "request needs a verified signature and grant")
    now = issued_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if expires_at is None:
        _require(
            isinstance(ttl_seconds, int) and 1 <= ttl_seconds <= 3600, "malformed-request", "ttl_seconds out of range"
        )
        expires_at = now + timedelta(seconds=ttl_seconds)
    request = {
        "schema_version": REQUEST_SCHEMA,
        "request_id": _nonempty(request_id, "request_id"),
        "node_id": _nonempty(node_id, "node_id"),
        "user_id": _nonempty(user_id, "user_id"),
        "argv": _argv(argv),
        "cwd": _cwd(cwd),
        "env": _env(env),
        "timeout_seconds": timeout_seconds,
        "operator_os": dict(operator_os),
        "capabilities": _capabilities(capabilities),
        "nonce": _nonempty(nonce, "nonce", "bad-nonce"),
        "issued_at": _iso(now),
        "expires_at": _iso(expires_at),
        "signature_b64": signature_b64,
    }
    return validate_request(request, verified=verified)


def validate_request(
    request: Mapping[str, Any],
    *,
    now: datetime | None = None,
    allow_expired: bool = False,
    require_signature: bool = True,
    require_verified: bool = True,
    verified: bool = False,
) -> dict[str, Any]:
    if require_verified and verified is not True:
        raise ExecError("subject-unverified", "request needs a verified signature and grant")
    _require(isinstance(request, Mapping), "malformed-request", "request must be an object")
    _require(request.get("schema_version") == REQUEST_SCHEMA, "malformed-request", "unknown execution request schema")
    timeout = request.get("timeout_seconds")
    _require(
        isinstance(timeout, int) and not isinstance(timeout, bool) and 1 <= timeout <= MAX_TIMEOUT_SECONDS,
        "bad-timeout",
        "timeout_seconds is out of range",
    )
    issued = _timestamp(request.get("issued_at"), "issued_at")
    expires = _timestamp(request.get("expires_at"), "expires_at")
    _require(expires > issued, "malformed-request", "expires_at must be after issued_at")
    _require(
        (expires - issued).total_seconds() <= MAX_REQUEST_TTL,
        "expired-request",
        "request lifetime exceeds the maximum",
    )
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _require(
        issued <= current + timedelta(seconds=CLOCK_SKEW), "malformed-request", "issued_at is too far in the future"
    )
    if not allow_expired:
        _require(expires > current, "expired-request", "request has expired")
    signature = request.get("signature_b64")
    if require_signature:
        _require(isinstance(signature, str) and bool(signature.strip()), "bad-signature", "request is unsigned")
    _require(
        signature is None or isinstance(signature, str), "malformed-request", "signature_b64 must be a string or null"
    )
    return {
        "schema_version": REQUEST_SCHEMA,
        "request_id": _nonempty(request.get("request_id"), "request_id"),
        "node_id": _nonempty(request.get("node_id"), "node_id"),
        "user_id": _nonempty(request.get("user_id"), "user_id"),
        "argv": _argv(request.get("argv")),
        "cwd": _cwd(request.get("cwd")),
        "env": _env(request.get("env")),
        "timeout_seconds": timeout,
        "operator_os": _operator_os(request.get("operator_os")),
        "capabilities": _capabilities(request.get("capabilities")),
        "nonce": _nonempty(request.get("nonce"), "nonce", "bad-nonce"),
        "issued_at": _iso(issued),
        "expires_at": _iso(expires),
        "signature_b64": signature,
    }


def request_message(request: Mapping[str, Any]) -> bytes:
    normalised = validate_request(
        request,
        now=_timestamp(request.get("issued_at"), "issued_at"),
        allow_expired=True,
        require_signature=False,
        require_verified=False,
    )
    return json.dumps(
        {field: normalised.get(field) for field in REQUEST_SIGNED_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        ensure_ascii=False,
    ).encode("utf-8")


def truncate_output(data: bytes, limit: int = MAX_OUTPUT_BYTES) -> tuple[str, bool]:
    _require(isinstance(limit, int) and limit > 0, "bad-output", "limit must be positive")
    limit = min(limit, MAX_OUTPUT_BYTES)
    raw = data if isinstance(data, bytes) else str(data).encode("utf-8", "replace")
    truncated = len(raw) > limit
    return raw[:limit].decode("utf-8", "replace"), truncated


def make_response(
    *,
    request_id: str,
    node_id: str,
    user_id: str,
    exit_code: int,
    stdout: str = "",
    stderr: str = "",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    truncated: bool = False,
    signature_b64: str | None = None,
) -> dict[str, Any]:
    started = started_at or datetime.now(timezone.utc)
    completed = completed_at or started
    bounded_stdout, stdout_cut = truncate_output(str(stdout).encode("utf-8", "replace"), MAX_OUTPUT_BYTES)
    bounded_stderr, stderr_cut = truncate_output(str(stderr).encode("utf-8", "replace"), MAX_OUTPUT_BYTES)
    response = {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": _nonempty(request_id, "request_id"),
        "node_id": _nonempty(node_id, "node_id"),
        "user_id": _nonempty(user_id, "user_id"),
        "exit_code": exit_code,
        "stdout": bounded_stdout,
        "stderr": bounded_stderr,
        "started_at": _iso(started),
        "completed_at": _iso(completed),
        "truncated": bool(truncated or stdout_cut or stderr_cut),
        "signature_b64": signature_b64,
    }
    return validate_response(response)


def validate_response(response: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(response, Mapping), "malformed-response", "response must be an object")
    _require(
        response.get("schema_version") == RESPONSE_SCHEMA, "malformed-response", "unknown execution response schema"
    )
    code = response.get("exit_code")
    _require(isinstance(code, int) and not isinstance(code, bool), "bad-exit-code", "exit_code must be an integer")
    signature = response.get("signature_b64")
    _require(
        signature is None or isinstance(signature, str), "malformed-response", "signature_b64 must be a string or null"
    )
    stdout = str(response.get("stdout") or "")
    stderr = str(response.get("stderr") or "")
    _require(
        len(stdout.encode("utf-8", "replace")) <= MAX_OUTPUT_BYTES
        and len(stderr.encode("utf-8", "replace")) <= MAX_OUTPUT_BYTES,
        "bad-output",
        "response output exceeds the limit",
    )
    return {
        "schema_version": RESPONSE_SCHEMA,
        "request_id": _nonempty(response.get("request_id"), "request_id"),
        "node_id": _nonempty(response.get("node_id"), "node_id"),
        "user_id": _nonempty(response.get("user_id"), "user_id"),
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
        "started_at": _iso(_timestamp(response.get("started_at"), "started_at")),
        "completed_at": _iso(_timestamp(response.get("completed_at"), "completed_at")),
        "truncated": bool(response.get("truncated")),
        "signature_b64": signature,
    }


def response_message(response: Mapping[str, Any]) -> bytes:
    normalised = validate_response(response)
    projected = {key: value for key, value in normalised.items() if key != "signature_b64"}
    return json.dumps(projected, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode(
        "utf-8"
    )


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the node's execution allow-list, fail-closed."""
    _require(isinstance(policy, Mapping), "bad-policy", "policy must be an object")
    _require(policy.get("schema") == POLICY_SCHEMA, "bad-policy", "unknown execution policy schema")
    allowed = policy.get("allowed_argv")
    _require(isinstance(allowed, (list, tuple)), "bad-policy", "allowed_argv must be a list")
    entries = []
    for item in allowed:
        _require(isinstance(item, Mapping), "bad-policy", "allowlist entry must be an object")
        binary = _nonempty(item.get("binary"), "allowlist binary", "bad-policy")
        _require("/" not in binary and "\\" not in binary, "bad-policy", "allowlist binary must be a basename")
        args = item.get("args")
        _require(
            isinstance(args, (list, tuple)) and all(isinstance(arg, str) and "\x00" not in arg for arg in args),
            "bad-policy",
            "allowlist args must be a list of strings",
        )
        entries.append({"binary": binary, "args": list(args)})
    roots = policy.get("cwd_roots")
    _require(isinstance(roots, (list, tuple)), "bad-policy", "cwd_roots must be a list")
    normalised_roots = [_cwd(root) for root in roots]
    env_allow = policy.get("env_allow")
    _require(
        isinstance(env_allow, (list, tuple)) and all(isinstance(key, str) for key in env_allow),
        "bad-policy",
        "env_allow must be a list of strings",
    )
    _require(set(env_allow) <= set(ENV_ALLOW), "bad-policy", "env_allow contains an unknown key")
    max_timeout = policy.get("max_timeout_seconds")
    _require(
        isinstance(max_timeout, int) and not isinstance(max_timeout, bool) and 1 <= max_timeout <= MAX_TIMEOUT_SECONDS,
        "bad-policy",
        "max_timeout_seconds is out of range",
    )
    max_output = policy.get("max_output_bytes")
    _require(
        isinstance(max_output, int) and not isinstance(max_output, bool) and 1 <= max_output <= MAX_OUTPUT_BYTES,
        "bad-policy",
        "max_output_bytes is out of range",
    )
    approval = policy.get("approval_ttl_seconds")
    _require(
        isinstance(approval, int) and not isinstance(approval, bool) and 1 <= approval <= MAX_REQUEST_TTL,
        "bad-policy",
        "approval_ttl_seconds is out of range",
    )
    audit = _nonempty(policy.get("audit_path"), "audit_path", "bad-policy")
    _require(
        ".." not in PurePosixPath(audit).parts and not PurePosixPath(audit).is_absolute(),
        "bad-policy",
        "audit_path must be vault-relative",
    )
    return {
        "schema": POLICY_SCHEMA,
        "allowed_argv": entries,
        "cwd_roots": normalised_roots,
        "env_allow": sorted(set(env_allow)),
        "max_timeout_seconds": max_timeout,
        "max_output_bytes": max_output,
        "approval_ttl_seconds": approval,
        "audit_path": PurePosixPath(audit).as_posix(),
    }


def policy_allows(request: Mapping[str, Any], policy: Mapping[str, Any]) -> tuple[bool, str]:
    """Return (allowed, reason) for one request against a validated policy."""
    normalised = validate_request(request, require_signature=False, require_verified=False)
    argv = normalised["argv"]
    for entry in policy["allowed_argv"]:
        if argv[0] == entry["binary"] and argv[1:] == entry["args"]:
            break
    else:
        return False, "not-allowlisted"
    cwd = normalised["cwd"]
    if not any(cwd == root or cwd.startswith(root + "/") for root in policy["cwd_roots"]):
        return False, "cwd-not-allowlisted"
    requested_env = set(normalised.get("env") or {})
    if "PATH" in requested_env:
        return False, "path-override-refused"
    if requested_env - set(policy["env_allow"]):
        return False, "env-not-allowlisted"
    if normalised["timeout_seconds"] > policy["max_timeout_seconds"]:
        return False, "timeout-exceeds-policy"
    return True, "allowed"

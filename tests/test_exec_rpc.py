"""The execution request is argv-only, bounded and operator-capped."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone

import pytest
from contract_helpers import REPO_ROOT, load

EXEC_PATH = REPO_ROOT / "shared" / "sparknet-exec-rpc.py"


def _load_exec():
    spec = importlib.util.spec_from_file_location("sparknet_exec_rpc", EXEC_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


exec_rpc = _load_exec()
OPERATOR = {"uid": 1000, "euid": 1000, "username": "raxxar", "groups": ["users"], "is_root": False}


def request(**overrides):
    body = {
        "request_id": "req-1",
        "node_id": "sparknet-node-0002",
        "user_id": "user-1",
        "argv": ["git", "status", "--short"],
        "operator_os": OPERATOR,
        "nonce": "nonce-1",
        "cwd": "05_Knowledge",
        "env": {"HOME": "/home/user"},
        "timeout_seconds": 30,
        "capabilities": ["p2p-sync"],
        "signature_b64": "test-signature",
        "verified": True,
    }
    body.update(overrides)
    return exec_rpc.make_request(**body)


def test_contract_vocabularies_match_the_module():
    schema = load("exec-schema.json")
    assert schema["request"]["schema"] == exec_rpc.REQUEST_SCHEMA
    assert schema["response"]["schema"] == exec_rpc.RESPONSE_SCHEMA
    assert tuple(schema["limits"]["env_allow_list"]) == exec_rpc.ENV_ALLOW
    assert schema["limits"]["max_timeout_seconds"] == exec_rpc.MAX_TIMEOUT_SECONDS
    assert schema["limits"]["max_output_bytes"] == exec_rpc.MAX_OUTPUT_BYTES


def test_request_is_normalised_and_canonical():
    first = request(operator_os={**OPERATOR, "groups": ["users", "users"]})
    second = request(request_id="req-1")
    assert first["env"] == {"HOME": "/home/user"}
    assert exec_rpc.request_message(first) == exec_rpc.request_message(second)


def test_argv_is_a_vector_never_a_shell_string():
    built = request(argv=["printf", "%s", "hello world; rm -rf /"])
    assert built["argv"] == ["printf", "%s", "hello world; rm -rf /"]
    with pytest.raises(exec_rpc.ExecError) as refused:
        request(argv=[])
    assert refused.value.code == "bad-argv"
    with pytest.raises(exec_rpc.ExecError):
        request(argv=["ok", 3])


def test_cwd_must_stay_inside_the_vault():
    for cwd in ("/etc", "../peer-user-2", "05_Knowledge/../../secret"):
        with pytest.raises(exec_rpc.ExecError) as refused:
            request(cwd=cwd)
        assert refused.value.code == "bad-cwd"


def test_env_is_an_allow_list():
    with pytest.raises(exec_rpc.ExecError) as refused:
        request(env={"LD_PRELOAD": "/tmp/evil.so"})
    assert refused.value.code == "bad-env"


def test_timeout_and_operator_limits():
    for timeout in (0, 301):
        with pytest.raises(exec_rpc.ExecError) as refused:
            request(timeout_seconds=timeout)
        assert refused.value.code == "bad-timeout"
    with pytest.raises(exec_rpc.ExecError) as refused:
        request(operator_os={"uid": 1000})
    assert refused.value.code == "bad-operator-os"


def test_expired_request_is_refused():
    built = request()
    built["issued_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    built["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(exec_rpc.ExecError) as refused:
        exec_rpc.validate_request(built, verified=True)
    assert refused.value.code == "expired-request"


def test_unsigned_or_unverified_request_is_refused():
    built = request()
    built["signature_b64"] = None
    with pytest.raises(exec_rpc.ExecError) as unsigned:
        exec_rpc.validate_request(built, verified=True)
    assert unsigned.value.code == "bad-signature"
    with pytest.raises(exec_rpc.ExecError) as unverified:
        exec_rpc.validate_request(request())
    assert unverified.value.code == "subject-unverified"


def test_unknown_capability_is_refused():
    with pytest.raises(exec_rpc.ExecError) as refused:
        request(capabilities=["root-everything"])
    assert refused.value.code == "bad-capabilities"


def test_long_lifetime_is_refused():
    built = request()
    built["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
    with pytest.raises(exec_rpc.ExecError) as refused:
        exec_rpc.validate_request(built, verified=True)
    assert refused.value.code == "expired-request"


def test_output_is_bounded_and_marked_truncated():
    text, truncated = exec_rpc.truncate_output(b"x" * 100, limit=8)
    assert text == "xxxxxxxx"
    assert truncated is True
    text, truncated = exec_rpc.truncate_output(b"short", limit=8)
    assert text == "short"
    assert truncated is False
    text, truncated = exec_rpc.truncate_output(
        b"x" * (exec_rpc.MAX_OUTPUT_BYTES + 1), limit=10 * exec_rpc.MAX_OUTPUT_BYTES
    )
    assert len(text) == exec_rpc.MAX_OUTPUT_BYTES
    assert truncated is True


def test_oversized_response_is_refused():
    with pytest.raises(exec_rpc.ExecError) as refused:
        exec_rpc.validate_response(
            {
                "schema_version": exec_rpc.RESPONSE_SCHEMA,
                "request_id": "req-1",
                "node_id": "node",
                "user_id": "user",
                "exit_code": 0,
                "stdout": "x" * (exec_rpc.MAX_OUTPUT_BYTES + 1),
                "stderr": "",
                "started_at": "2026-11-07T00:00:00Z",
                "completed_at": "2026-11-07T00:00:01Z",
                "truncated": False,
            }
        )
    assert refused.value.code == "bad-output"


def test_response_round_trip():
    response = exec_rpc.make_response(
        request_id="req-1",
        node_id="sparknet-node-0002",
        user_id="user-1",
        exit_code=0,
        stdout="ok",
        stderr="",
        truncated=False,
    )
    assert exec_rpc.response_message(response)
    assert response["exit_code"] == 0


def test_policy_allowlist_is_exact_and_fail_closed():
    policy = exec_rpc.validate_policy(
        {
            "schema": "sparknet-exec-policy/1",
            "allowed_argv": [{"binary": "git", "args": ["status", "--short"]}],
            "cwd_roots": ["05_Knowledge"],
            "env_allow": ["HOME"],
            "max_timeout_seconds": 30,
            "max_output_bytes": 65536,
            "approval_ttl_seconds": 300,
            "audit_path": ".state/exec-audit.jsonl",
        }
    )
    allowed, reason = exec_rpc.policy_allows(request(), policy)
    assert allowed is True and reason == "allowed"
    allowed, reason = exec_rpc.policy_allows(request(argv=["git", "push"]), policy)
    assert allowed is False and reason == "not-allowlisted"
    allowed, reason = exec_rpc.policy_allows(request(cwd="06_Projects"), policy)
    assert allowed is False and reason == "cwd-not-allowlisted"
    allowed, reason = exec_rpc.policy_allows(request(env={"HOME": "/home/user", "TERM": "x"}), policy)
    assert allowed is False and reason == "env-not-allowlisted"

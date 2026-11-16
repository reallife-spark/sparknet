"""Federated human identity policy and its two signed envelopes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
authz = load_by_path("authz_sso_test", ROOT / "shared" / "sparknet-authz.py")
sso = load_by_path("sso_identity_test", ROOT / "shared" / "sparknet-sso.py")

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
FINGERPRINT = "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7"


def _assertion(**overrides):
    record = {
        "schema": authz.SSO_ASSERTION_SCHEMA,
        "assertion_id": "assertion-1",
        "master_node_id": "master-1",
        "target_node_id": "peer-fixture-01",
        "target_fingerprint": FINGERPRINT,
        "subject": "human-1",
        "email": "admin@example.test",
        "role": "admin",
        "groups": [sso.ADMIN_GROUP],
        "issued_at": int(NOW.timestamp()) - 5,
        "expires_at": int(NOW.timestamp()) + 60,
        "nonce": "n1",
    }
    record.update(overrides)
    return record


def _repair(**overrides):
    record = {
        "schema": authz.OFFLINE_REPAIR_SCHEMA,
        "repair_id": "repair-1",
        "node_id": "peer-fixture-01",
        "node_fingerprint": FINGERPRINT,
        "created_at": "2026-11-16T11:00:00Z",
        "action": "user-role",
        "target": {"user": "u1"},
        "change": {"role": "user"},
        "authority_effect": "none",
    }
    record.update(overrides)
    return record


def _keypair():
    private_b64, _public = authz.generate_keypair()
    key = authz.private_key_from_b64(private_b64)
    return key, key.public_key()


# --- policy ------------------------------------------------------------------


def test_group_to_role_mapping_is_closed_and_admin_wins() -> None:
    assert sso.role_for_groups([sso.ADMIN_GROUP]) == "admin"
    assert sso.role_for_groups([sso.USER_GROUP]) == "user"
    assert sso.role_for_groups([sso.ADMIN_GROUP, sso.USER_GROUP]) == "admin"
    assert sso.role_for_groups([sso.ADMIN_GROUP]) != "user"
    assert sso.role_for_groups([]) is None
    assert sso.role_for_groups(["other"]) is None


def test_caller_identity_headers_are_stripped_before_injection() -> None:
    headers = {
        "X-User-Email": "attacker@example.test",
        "x-user-role": "admin",
        "X-User-Groups": "sparknet-admins",
        "Authorization": "Bearer session",
        "Host": "node",
    }
    cleaned = sso.strip_identity_headers(headers)
    assert cleaned == {"Authorization": "Bearer session", "Host": "node"}
    injected = sso.injected_headers("admin@example.test", "admin", [sso.ADMIN_GROUP])
    assert injected[sso.TRUSTED_EMAIL_HEADER] == "admin@example.test"
    assert injected[sso.TRUSTED_ROLE_HEADER] == "admin"
    assert injected[sso.TRUSTED_GROUPS_HEADER] == sso.ADMIN_GROUP


def test_injected_headers_refuse_an_unknown_role() -> None:
    with pytest.raises(sso.SSOError):
        sso.injected_headers("x@example.test", "root", [sso.USER_GROUP])


def test_override_validation_and_precedence() -> None:
    override = {
        "role": "user",
        "set_by": "master-1",
        "request_id": "admin-1",
        "set_at": "2026-11-16T12:00:00Z",
        "reason": "demoted for review",
    }
    assert sso.effective_role("admin", override) == ("user", True)
    assert sso.effective_role("user", override) == ("user", False)
    assert sso.effective_role(None, override) == ("user", False)
    assert sso.effective_role("admin", None) == ("admin", False)
    with pytest.raises(sso.SSOError):
        sso.validate_override({**override, "role": "root"})
    with pytest.raises(sso.SSOError):
        sso.validate_override({**override, "request_id": ""})


def test_override_file_round_trip_and_missing_file(tmp_path: Path) -> None:
    assert sso.load_overrides(tmp_path / "missing.json") == {}
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps(
            {
                "admin@example.test": {
                    "role": "user",
                    "set_by": "master-1",
                    "request_id": "admin-1",
                    "set_at": "2026-11-16T12:00:00Z",
                }
            }
        ),
        encoding="utf-8",
    )
    loaded = sso.load_overrides(path)
    assert loaded["admin@example.test"]["role"] == "user"


# --- assertion ----------------------------------------------------------------


def test_assertion_round_trip_and_refusals() -> None:
    key, public = _keypair()
    signed = sso.sign_assertion(_assertion(), key)
    ok, reason = sso.verify_assertion(
        signed,
        public,
        expected_node_id="peer-fixture-01",
        expected_fingerprint=FINGERPRINT,
        now=NOW,
    )
    assert (ok, reason) == (True, "")

    tampered = {**signed, "email": "other@example.test"}
    assert sso.verify_assertion(
        tampered, public, expected_node_id="peer-fixture-01", expected_fingerprint=FINGERPRINT, now=NOW
    ) == (False, sso.REASON_ASSERTION_BAD_SIGNATURE)

    assert sso.verify_assertion(
        signed, public, expected_node_id="peer-fixture-02", expected_fingerprint=FINGERPRINT, now=NOW
    ) == (False, sso.REASON_ASSERTION_WRONG_NODE)

    assert sso.verify_assertion(
        signed, public, expected_node_id="peer-fixture-01", expected_fingerprint="f" * 64, now=NOW
    ) == (False, sso.REASON_ASSERTION_WRONG_NODE)

    expired = sso.sign_assertion(
        _assertion(
            issued_at=int(NOW.timestamp()) - 3660,
            expires_at=int(NOW.timestamp()) - 3600,
        ),
        key,
    )
    assert sso.verify_assertion(
        expired, public, expected_node_id="peer-fixture-01", expected_fingerprint=FINGERPRINT, now=NOW
    ) == (False, sso.REASON_ASSERTION_STALE)

    assert sso.verify_assertion(
        signed,
        public,
        expected_node_id="peer-fixture-01",
        expected_fingerprint=FINGERPRINT,
        now=NOW,
        seen_nonces=["n1"],
    ) == (False, sso.REASON_ASSERTION_REPLAYED)

    mismatch = sso.sign_assertion(_assertion(role="admin", groups=[sso.USER_GROUP]), key)
    assert sso.verify_assertion(
        mismatch, public, expected_node_id="peer-fixture-01", expected_fingerprint=FINGERPRINT, now=NOW
    ) == (False, sso.REASON_ASSERTION_ROLE_MISMATCH)


def test_malformed_assertion_is_refused_not_raised() -> None:
    _key, public = _keypair()
    ok, reason = sso.verify_assertion(
        {"schema": authz.SSO_ASSERTION_SCHEMA},
        public,
        expected_node_id="peer-fixture-01",
        expected_fingerprint=FINGERPRINT,
        now=NOW,
    )
    assert (ok, reason) == (False, sso.REASON_ASSERTION_MALFORMED)


# --- offline repair -----------------------------------------------------------


def test_offline_repair_round_trip_and_refusals() -> None:
    key, public = _keypair()
    signed = sso.sign_offline_repair(_repair(), key)
    ok, reason = sso.verify_offline_repair(
        signed,
        public,
        expected_node_id="peer-fixture-01",
        expected_fingerprint=FINGERPRINT,
        now=NOW,
    )
    assert (ok, reason) == (True, "")

    tampered = {**signed, "change": {"role": "admin"}}
    assert sso.verify_offline_repair(
        tampered, public, expected_node_id="peer-fixture-01", expected_fingerprint=FINGERPRINT, now=NOW
    ) == (False, sso.REASON_REPAIR_BAD_SIGNATURE)

    assert sso.verify_offline_repair(
        signed, public, expected_node_id="peer-fixture-02", expected_fingerprint=FINGERPRINT, now=NOW
    ) == (False, sso.REASON_REPAIR_WRONG_NODE)

    stale = sso.sign_offline_repair(_repair(created_at="2026-08-01T00:00:00Z"), key)
    assert sso.verify_offline_repair(
        stale, public, expected_node_id="peer-fixture-01", expected_fingerprint=FINGERPRINT, now=NOW
    ) == (False, sso.REASON_REPAIR_STALE)


def test_offline_repair_cannot_carry_authority() -> None:
    with pytest.raises(authz.AuthzError, match="authority field"):
        authz.envelope_message("offline-repair", _repair(change={"capabilities": ["guard-apply"]}))
    with pytest.raises(authz.AuthzError, match="authority field"):
        authz.envelope_message("offline-repair", _repair(target={"nested": {"grant": {"id": "g1"}}}))
    with pytest.raises(authz.AuthzError, match="authority_effect"):
        authz.envelope_message("offline-repair", _repair(authority_effect="grant"))
    with pytest.raises(authz.AuthzError, match="unknown offline repair action"):
        authz.envelope_message("offline-repair", _repair(action="registry-publish"))


# --- contract alignment -------------------------------------------------------


def test_contract_names_the_same_groups_ports_and_refusals() -> None:
    ports = json.loads((ROOT / "contracts" / "ports.json").read_text(encoding="utf-8"))["ports"]
    assert ports["8181"]["service"] == "node-webui-ingress"
    assert ports["8182"]["service"] == "node-admin-gateway"
    assert ports["8092"]["service"] == "master-admin-sso"
    assert ports["9443"]["service"] == "identity-provider"
    text = (ROOT / "contracts" / "sso-identity.md").read_text(encoding="utf-8")
    for phrase in (
        sso.ADMIN_GROUP,
        sso.USER_GROUP,
        "8181",
        "8182",
        "8092",
        "9443",
        "idp-unreachable",
        "bad-client-cert",
        "cert-expired",
        "cert-revoked",
        "unapproved",
        "role-override-conflict",
        "assertion-stale",
        "offline-repair-refused",
        "no shared password",
    ):
        assert phrase in text, phrase
    schema = json.loads((ROOT / "contracts" / "identity-schema.json").read_text(encoding="utf-8"))
    assert schema["human_identity"]["groups"][sso.ADMIN_GROUP]
    assert schema["human_identity"]["separate_from_node_identity"] is True


def test_assertion_fields_match_the_contract_shape() -> None:
    assert "target_fingerprint" in authz.SPECS["sso-assertion"].signed_fields
    assert "role" in authz.SPECS["sso-assertion"].signed_fields
    assert "authority_effect" in authz.SPECS["offline-repair"].signed_fields
    assert authz.SPECS["offline-repair"].signed_fields == authz.OFFLINE_REPAIR_FIELDS


def test_assertion_age_is_bounded() -> None:
    key, public = _keypair()
    future = sso.sign_assertion(
        _assertion(
            issued_at=int(NOW.timestamp()) + 3600,
            expires_at=int(NOW.timestamp()) + 3660,
        ),
        key,
    )
    assert sso.verify_assertion(
        future, public, expected_node_id="peer-fixture-01", expected_fingerprint=FINGERPRINT, now=NOW
    ) == (False, sso.REASON_ASSERTION_STALE)
    assert NOW + timedelta(seconds=1) > NOW


def test_sso_overlays_enable_tls_trusted_headers_and_a_loopback_upstream() -> None:
    import yaml

    for path, nginx_service in (
        (ROOT / "peer-node" / "configs" / "ai-stack" / "docker-compose.sso.yml", "admin-nginx"),
        (ROOT / "master-node" / "configs" / "admin-surface" / "docker-compose.sso.yml", "sso-nginx"),
    ):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        webui = data["services"]["open-webui"]["environment"]
        assert webui["WEBUI_AUTH_TRUSTED_EMAIL_HEADER"] == "X-User-Email"
        assert webui["WEBUI_AUTH_TRUSTED_ROLE_HEADER"] == "X-User-Role"
        assert webui["WEBUI_AUTH_TRUSTED_GROUPS_HEADER"] == "X-User-Groups"
        assert webui["ENABLE_LOGIN_FORM"] == "true", "offline users keep a local fallback"
        nginx = data["services"][nginx_service]["environment"]
        assert nginx["SPARKNET_TLS_CERT"] == "/etc/sparknet/identity/tls/server.crt"
        for required in (
            "SPARKNET_BIND",
            "SPARKNET_ADMIN_ALT_BIND",
            "SPARKNET_TLS_CERT",
            "SPARKNET_TLS_KEY",
            "SPARKNET_ADMIN_CA",
        ):
            assert required in nginx
        assert any("/etc/sparknet/identity" in str(volume) for volume in data["services"][nginx_service]["volumes"])
    peer = yaml.safe_load(
        (ROOT / "peer-node" / "configs" / "ai-stack" / "docker-compose.sso.yml").read_text(encoding="utf-8")
    )
    assert "nginx" not in peer["services"], "the existing user ingress on 8181 must stay untouched"

    template = (ROOT / "webui" / "nginx.sso.conf.template").read_text(encoding="utf-8")
    for phrase in (
        "listen ${SPARKNET_BIND} ssl",
        "listen ${SPARKNET_ADMIN_ALT_BIND} ssl",
        "ssl_verify_client optional",
        "ssl_client_certificate ${SPARKNET_ADMIN_CA}",
        "auth_request /_auth",
        "proxy_set_header X-User-Email $sparknet_user_email",
        "proxy_set_header X-User-Role $sparknet_user_role",
        'proxy_set_header X-Auth-Request-Email ""',
        'proxy_set_header X-Auth-Request-Groups ""',
        "proxy_pass http://127.0.0.1:${SPARKNET_WEBUI_PORT}",
        "location /nodes/",
        "proxy_pass http://127.0.0.1:8191",
        "auth_request_set $sparknet_user_role $upstream_http_x_user_role",
    ):
        assert phrase in template, phrase

    base = (ROOT / "peer-node" / "configs" / "ai-stack" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SPARKNET_NGINX_TEMPLATE:-nginx.conf.template" in base

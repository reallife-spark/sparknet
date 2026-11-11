"""One registry-entry acceptance rule for the local node and remote peers."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pytestmark = pytest.mark.unit


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _identity() -> dict:
    return {
        "node_id": "sparknet-node-0002",
        "role": "peer",
        "wireguard_public_key_b64": base64.b64encode(b"k" * 32).decode("ascii"),
        "overlay_ipv4": "10.100.0.2",
        "requested_capabilities": ["telemetry"],
    }


def _entry(authz, key: Ed25519PrivateKey, *, capabilities=("telemetry",), now=NOW, revoked=False):
    return authz.sign_authorization(
        _identity(),
        key,
        list(capabilities),
        ttl_days=365,
        now=now,
        revoked=revoked,
    )


def test_accept_entry_returns_the_facts_a_caller_may_use(authz) -> None:
    key = Ed25519PrivateKey.generate()
    accepted = authz.accept_entry(_entry(authz, key), key.public_key(), now=NOW)
    assert accepted.fingerprint == authz.fingerprint(_identity())
    assert accepted.capabilities == ["telemetry"]
    assert accepted.overlay_ipv4 == "10.100.0.2"
    assert accepted.identity["node_id"] == "sparknet-node-0002"


@pytest.mark.parametrize(
    ("entry_factory", "code"),
    [
        (lambda authz, key: _entry(authz, key, revoked=True), "revoked"),
        (lambda authz, key: _entry(authz, key, now=NOW - timedelta(days=400)), "expired"),
        (lambda authz, key: _entry(authz, key, now=NOW + timedelta(hours=1)), "not_yet_valid"),
    ],
)
def test_accept_entry_refuses_revoked_expired_and_future_entries(authz, entry_factory, code) -> None:
    key = Ed25519PrivateKey.generate()
    with pytest.raises(authz.RegistryEntryError) as refused:
        authz.accept_entry(entry_factory(authz, key), key.public_key(), now=NOW)
    assert refused.value.code == code


def test_accept_entry_refuses_identity_mismatch_and_bad_signature(authz) -> None:
    key = Ed25519PrivateKey.generate()
    mismatched = _entry(authz, key)
    mismatched["identity"]["node_id"] = "sparknet-node-0003"
    with pytest.raises(authz.RegistryEntryError) as identity:
        authz.accept_entry(mismatched, key.public_key(), now=NOW)
    assert identity.value.code == authz.REASON_IDENTITY_MISMATCH

    tampered = _entry(authz, key)
    tampered["capabilities"] = ["guard-apply"]
    with pytest.raises(authz.RegistryEntryError) as signature:
        authz.accept_entry(tampered, key.public_key(), now=NOW)
    assert signature.value.code == authz.REASON_BAD_SIGNATURE


def test_accept_entry_refuses_unknown_and_missing_capabilities(authz) -> None:
    key = Ed25519PrivateKey.generate()
    unknown = _entry(authz, key)
    unknown["capabilities"] = ["invented"]
    unknown["signature_b64"] = base64.b64encode(key.sign(authz.authorization_message(unknown))).decode("ascii")
    with pytest.raises(authz.RegistryEntryError) as refused:
        authz.accept_entry(unknown, key.public_key(), now=NOW)
    assert refused.value.code == authz.REASON_UNKNOWN_CAPABILITY

    with pytest.raises(authz.RegistryEntryError) as missing:
        authz.accept_entry(
            _entry(authz, key),
            key.public_key(),
            now=NOW,
            required_capability="guard-apply",
        )
    assert missing.value.code == "capability_missing"


def test_roster_mode_skips_a_bad_entry_instead_of_raising(authz) -> None:
    key = Ed25519PrivateKey.generate()
    bad = _entry(authz, key)
    bad["capabilities"] = ["guard-apply"]
    assert authz.accept_entry(bad, key.public_key(), now=NOW, mode="roster") is None

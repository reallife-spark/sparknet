"""Pinned, keyless deterministic outputs of the shared signing implementation.

Split out of the contract suite; shares its fixtures and `load` helper via
`tests/contract_helpers.py`.
"""

from __future__ import annotations

from types import ModuleType

import pytest
from contract_helpers import load

pytestmark = pytest.mark.unit


# --- golden vectors -----------------------------------------------------------
#
# The rest of the contract suite checks that the contract and the code agree on
# *which fields* participate. That still passes if both are changed together:
# someone could add a field to identity_fields, serialise it the same careless
# way in both places, and ship a change that alters every node's fingerprint with
# nothing red. Only a pinned expected value catches that, so the exact bytes are
# fixed here.
#
# These cover the keyless deterministic outputs. Signing itself needs a keypair,
# and pinning a private key in a repo is the one thing this file must never do.

#: An identity with deliberate operational noise mixed in.
GOLDEN_IDENTITY = {
    "node_id": "peer-fixture-01",
    "role": "peer",
    "wireguard_public_key_b64": "ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw==",
    "overlay_ipv4": "10.77.0.11/32",
    "requested_capabilities": ["dispatch-bridge", "guard-verify"],
    # Metadata a node's operator might set. None of it may reach the fingerprint,
    # or two otherwise-identical nodes would stop matching.
    "agent_endpoint": "https://peer-fixture-01.invalid:8443",
    "last_seen": "2026-10-04T00:00:00Z",
}

GOLDEN_CANONICAL_BYTES = (
    b'{"node_id":"peer-fixture-01","overlay_ipv4":"10.77.0.11/32",'
    b'"requested_capabilities":["dispatch-bridge","guard-verify"],"role":"peer",'
    b'"wireguard_public_key_b64":"ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw=="}'
)

GOLDEN_FINGERPRINT = "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7"

GOLDEN_AUTHORIZATION_MESSAGE = (
    b'{"capabilities":["dispatch-bridge","guard-verify"],'
    b'"department":null,'
    b'"expires_at":1893456000,'
    b'"fingerprint":"140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",'
    b'"identity":{"node_id":"peer-fixture-01","overlay_ipv4":"10.77.0.11/32",'
    b'"requested_capabilities":["dispatch-bridge","guard-verify"],"role":"peer",'
    b'"wireguard_public_key_b64":"ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw=="},'
    b'"issued_at":1760000000,"node_pubkey_b64":null,'
    b'"overlay_ipv4":"10.77.0.11","revoked":false}'
)

GOLDEN_ADMIN_REQUEST = {
    "request_id": "admin-req-0001",
    "master_node_id": "master-fixture-01",
    "target_node_id": "peer-fixture-01",
    "target_fingerprint": GOLDEN_FINGERPRINT,
    "issued_at": 1760000000,
    "expires_at": 1760000600,
    "nonce": "nonce-0001",
    "action": "set_user_role",
    "user_id": "user-07",
    "user_email": "ana@example.test",
    "role": "user",
    "kb_id": None,
    "chat_id": None,
}

GOLDEN_ADMIN_REQUEST_MESSAGE = (
    b'{"action":"set_user_role","chat_id":null,"conversation_id":null,'
    b'"expires_at":1760000600,"issued_at":1760000000,"kb_id":null,'
    b'"master_node_id":"master-fixture-01","memory_ids":null,"memory_query":null,'
    b'"memory_types":null,"nonce":"nonce-0001","policy":null,"project_id":null,'
    b'"reason":null,"request_id":"admin-req-0001","role":"user",'
    b'"target_fingerprint":"140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",'
    b'"target_node_id":"peer-fixture-01","user_email":"ana@example.test",'
    b'"user_id":"user-07"}'
)


def test_golden_canonical_bytes(authz: ModuleType):
    """Fields sorted, tight separators, UTF-8 — exactly as the schema declares."""
    assert authz.canonical_bytes(GOLDEN_IDENTITY) == GOLDEN_CANONICAL_BYTES, (
        "canonical identity bytes changed. Every node fingerprint changes with "
        "them. If this is intentional it is a contract break, not a refactor: "
        "bump identity-schema.json's schema_version and re-issue the registry."
    )


def test_golden_fingerprint(authz: ModuleType):
    assert authz.fingerprint(GOLDEN_IDENTITY) == GOLDEN_FINGERPRINT, (
        "fingerprint of the golden identity changed — see the canonical-bytes vector for why this is not a small change"
    )


def test_golden_authorization_message(authz: ModuleType):
    """The signature scope, pinned.

    This is what the Master actually signs, so a field added or dropped here
    changes what an existing signature covers. Silently reordering the envelope
    would be a break even though every signature still verifies locally.
    """
    entry = {
        "fingerprint": GOLDEN_FINGERPRINT,
        "identity": GOLDEN_IDENTITY,
        "capabilities": ["guard-verify", "dispatch-bridge"],
        "overlay_ipv4": "10.77.0.11",
        "issued_at": 1760000000,
        "expires_at": 1893456000,
        "revoked": False,
    }
    assert authz.authorization_message(entry) == GOLDEN_AUTHORIZATION_MESSAGE, (
        "the bytes the Master signs changed shape — see above"
    )


def test_golden_admin_request_message(authz: ModuleType):
    """The admin-request signature scope, pinned.

    This is the envelope the Master signs for an admin action and the peer
    re-hashes before verifying; a field added or dropped here changes what an
    existing signature covers without any local test noticing.
    """
    assert authz.admin_request_message(GOLDEN_ADMIN_REQUEST) == GOLDEN_ADMIN_REQUEST_MESSAGE, (
        "the admin-request envelope the Master signs changed shape — this is a contract break, not a refactor"
    )


def test_projection_drops_operational_metadata(authz: ModuleType):
    projected = authz.canonical_identity(GOLDEN_IDENTITY)
    for noise in ("agent_endpoint", "last_seen"):
        assert noise not in projected, (
            f"{noise} leaked into the identity projection, so an operator could "
            f"change a node's fingerprint by editing metadata"
        )
    assert set(projected) == set(load("identity-schema.json")["identity_fields"])


def test_capability_order_asymmetry_is_intentional(authz: ModuleType):
    """Two orderings that behave differently, on purpose.

    `requested_capabilities` (inside the identity) is NOT sorted, so reordering
    it yields a different fingerprint. Granted `capabilities` (inside the signed
    envelope) IS sorted, so reordering it does not. That looks like an oversight
    and is not:

    - the fingerprint must cover what the node *asked for*, or a node could
      re-order its own request to change its identity;
    - the granted set is a set, so the signature should not depend on the order
      the registry happened to be written in.

    The failure mode if someone "tidies" the unsorted list: every existing node
    fingerprint changes, every registry entry stops matching, and no local test
    fails. This test is the guard for that edit.
    """
    reordered = dict(GOLDEN_IDENTITY, requested_capabilities=["guard-verify", "dispatch-bridge"])
    assert authz.fingerprint(reordered) != GOLDEN_FINGERPRINT, (
        "requested_capabilities became order-insensitive. If that was intended, "
        "it invalidates every issued fingerprint and is a contract break."
    )

    base = {
        "fingerprint": GOLDEN_FINGERPRINT,
        "identity": GOLDEN_IDENTITY,
        "issued_at": 1760000000,
        "expires_at": 1893456000,
    }
    a = dict(base, capabilities=["dispatch-bridge", "guard-verify"])
    b = dict(base, capabilities=["guard-verify", "dispatch-bridge"])
    assert authz.authorization_message(a) == authz.authorization_message(b), (
        "granted capabilities became order-sensitive, so rewriting the registry "
        "with the same set in a different order invalidates the Master's signature"
    )


# --- strict base64 ------------------------------------------------------------


def test_decode_b64_strict_rejects_the_cross_version_trap(authz: ModuleType):
    """The malformed inputs a tolerant decoder accepts on one CPython and not another.

    A real Ed25519 public key is 32 bytes -> 44 base64 chars ending in ``=``. A
    43-char body with a stray trailing ``=`` is the shape that historically
    decoded on 3.12 (tolerant) and raised on 3.14 (strict). Routing every decode
    through one strict helper removes the version dependence; this pins it.
    """
    # A valid key decodes to exactly 32 bytes with and without the module.
    good = "xjKK/BeuwLIsxZz53jwHYOoXyZRSqUO1Rv6JafZShx0="
    assert len(authz.decode_b64_strict(good, what="key")) == 32

    # Non-alphabet bytes must be refused, not silently ignored.
    for bad in ("not base64!!", "AAAA AAAA", "a=b=c"):
        with pytest.raises(authz.AuthzError):
            authz.decode_b64_strict(bad, what="signature")


def test_decode_b64_strict_urlsafe_variant(authz: ModuleType):
    import base64

    raw = b"a grant token payload"
    token = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    assert authz.decode_b64_strict(token, what="grant token", urlsafe=True) == raw


def test_verify_signature_is_fail_closed_on_malformed_base64(authz: ModuleType):
    """A garbage signature must return False, never raise, and never pass."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    pub = Ed25519PrivateKey.generate().public_key()
    assert authz.verify_signature(pub, "!!!not base64!!!", b"msg") is False
    assert authz.verify_signature(pub, "", b"msg") is False

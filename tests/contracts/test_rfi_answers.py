"""rfi answers"""

from __future__ import annotations

from types import ModuleType

import pytest


def _rfi_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


def _answer(authz: ModuleType, key, **overrides) -> dict:
    params = {
        "content": b"# the answer\n",
        "item_name": "rfi-2026-10-24-guard.md",
        "peer_fingerprint": "a" * 64,
        "request_id": "RFI-1",
        "master_private_key": key,
    }
    params.update(overrides)
    return authz.sign_rfi_answer(**params)


def test_rfi_envelope_matches_the_contract(authz: ModuleType, rfi_schema: dict) -> None:
    """A new signed envelope gets the same pin the others have.

    Without this the contract's field list and the projection could drift, and an
    answer would verify here while failing on a node — or the reverse, which is the
    version that gets discovered in production.
    """
    answer = rfi_schema["answer"]
    assert tuple(answer["fields"]) == authz.RFI_ANSWER_FIELDS
    assert tuple(answer["signed_fields"]) == authz.RFI_ANSWER_SIGNED_FIELDS
    assert answer["signature_field"] == "signature_b64"
    assert answer["extra_fields"] == "refused"
    assert answer["implementation"].endswith("rfi_answer_message")
    assert answer["verifier"].endswith("verify_rfi_answer")
    # content is bound by digest, so it is in the envelope but not in the signature
    assert "content_b64" in authz.RFI_ANSWER_FIELDS
    assert "content_b64" not in authz.RFI_ANSWER_SIGNED_FIELDS
    assert "content_sha256" in authz.RFI_ANSWER_SIGNED_FIELDS
    # Every refusal the contract names is a reason the verifier can return.
    declared = set(rfi_schema["refusals"])
    produced = {
        value
        for value in vars(authz).values()
        if isinstance(value, str)
        and value.startswith(
            ("malformed", "extra_", "missing_", "bad_sig", "digest_", "wrong_", "unsafe_", "expired", "duplicate_")
        )
    }
    assert declared <= produced | {"off_overlay"}, (
        f"the contract names refusals the verifier cannot produce: {sorted(declared - produced - {'off_overlay'})}"
    )


def test_rfi_answer_round_trips(authz: ModuleType) -> None:
    key = _rfi_key()
    answer = _answer(authz, key)
    ok, reason, content = authz.verify_rfi_answer(answer, master_public_key=key.public_key(), peer_fingerprint="a" * 64)
    assert (ok, reason) == (True, "")
    assert content == b"# the answer\n"


def test_an_empty_answer_is_legitimate(authz: ModuleType) -> None:
    """'Nothing found' is an answer. Refusing it would push a Master to invent content."""
    key = _rfi_key()
    answer = _answer(authz, key, content=b"")
    ok, reason, content = authz.verify_rfi_answer(answer, master_public_key=key.public_key(), peer_fingerprint="a" * 64)
    assert (ok, reason, content) == (True, "", b"")


def test_rfi_tampering_is_refused_with_a_specific_reason(authz: ModuleType) -> None:
    key = _rfi_key()
    good = _answer(authz, key)
    kwargs = {"master_public_key": key.public_key(), "peer_fingerprint": "a" * 64}

    # Content swapped under a valid signature: the digest binds it.
    swapped = {**good, "content_b64": good["content_b64"][:-4] + "AAA="}
    assert authz.verify_rfi_answer(swapped, **kwargs)[1] in (
        authz.REASON_RFI_DIGEST_MISMATCH,
        authz.REASON_RFI_MALFORMED,
    )
    # Destination rewritten: item_name is inside the projection.
    moved = {**good, "item_name": "somewhere-else.md"}
    assert authz.verify_rfi_answer(moved, **kwargs)[1] == authz.REASON_RFI_BAD_SIGNATURE
    # An extra field is unsigned authority-shaped data.
    assert authz.verify_rfi_answer({**good, "escalate": True}, **kwargs)[1] == authz.REASON_RFI_EXTRA_FIELDS
    # Another Master's signature over the same bytes.
    other = _rfi_key()
    assert authz.verify_rfi_answer(good, master_public_key=other.public_key(), peer_fingerprint="a" * 64)[1] == (
        authz.REASON_RFI_BAD_SIGNATURE
    )


def test_rfi_answer_is_bound_to_its_peer(authz: ModuleType) -> None:
    """An answer minted for one node must not install into another's inbox."""
    key = _rfi_key()
    answer = _answer(authz, key, peer_fingerprint="a" * 64)
    ok, reason, content = authz.verify_rfi_answer(answer, master_public_key=key.public_key(), peer_fingerprint="b" * 64)
    assert not ok and reason == authz.REASON_RFI_WRONG_PEER and content == b""


def test_rfi_item_name_cannot_traverse(authz: ModuleType) -> None:
    """The name is a write destination, so this is a traversal guard, not a style rule."""
    key = _rfi_key()
    for name in ("../00_System/user.md", "sub/dir.md", "..", ".", ".hidden", "a/b", "", "back\\slash"):
        with pytest.raises(authz.AuthzError):
            authz.sign_rfi_answer(
                content=b"x",
                item_name=name,
                peer_fingerprint="a" * 64,
                request_id="RFI-1",
                master_private_key=key,
            )
    # And a hand-built artifact is refused at verification too, not only at signing.
    forged = {
        "answered_at": "2026-10-24T00:00:00Z",
        "content_b64": "",
        "content_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "item_name": "../escape.md",
        "peer_fingerprint": "a" * 64,
        "request_id": "RFI-1",
    }
    forged["signature_b64"] = forged.get("signature_b64", "")
    ok, reason, _ = authz.verify_rfi_answer(forged, master_public_key=key.public_key(), peer_fingerprint="a" * 64)
    assert not ok and reason in (authz.REASON_RFI_BAD_SIGNATURE, authz.REASON_RFI_UNSAFE_ITEM_NAME)


def test_rfi_answer_expires_and_cannot_be_replayed(authz: ModuleType) -> None:
    from datetime import datetime, timedelta, timezone

    key = _rfi_key()
    moment = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
    answer = _answer(authz, key, now=moment)
    kwargs = {"master_public_key": key.public_key(), "peer_fingerprint": "a" * 64, "now": moment}

    assert authz.verify_rfi_answer(answer, **kwargs)[0] is True
    late = {**kwargs, "now": moment + timedelta(seconds=3601)}
    assert authz.verify_rfi_answer(answer, **late)[1] == authz.REASON_RFI_EXPIRED
    # A re-delivered answer for an installed request is a duplicate, not new information.
    again = {**kwargs, "installed_request_ids": ["RFI-1"]}
    assert authz.verify_rfi_answer(answer, **again)[1] == authz.REASON_RFI_DUPLICATE


def test_rfi_verification_never_raises(authz: ModuleType) -> None:
    """A refusal is a return value. A caller that must catch to refuse will eventually miss one."""
    key = _rfi_key()
    kwargs = {"master_public_key": key.public_key(), "peer_fingerprint": "a" * 64}
    for junk in (None, "not-a-dict", 42, [], {}, {"answered_at": None}, {"signature_b64": "!!!"}):
        ok, reason, content = authz.verify_rfi_answer(junk, **kwargs)
        assert not ok and content == b""
        assert isinstance(reason, str) and reason


def test_a_naive_rfi_timestamp_is_treated_as_utc(authz: ModuleType) -> None:
    """A timestamp without an offset must not raise a TypeError out of the verifier."""
    from datetime import datetime

    key = _rfi_key()
    answer = _answer(authz, key, now=datetime.now())
    ok, reason, content = authz.verify_rfi_answer(answer, master_public_key=key.public_key(), peer_fingerprint="a" * 64)
    assert ok is True, reason
    assert content == b"# the answer\n"

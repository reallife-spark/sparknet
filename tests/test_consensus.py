"""Consensus: how three nodes agree on who holds the signing key.

Every test here builds real Ed25519 keys and verifies real signatures. A test
that mocks the crypto would pass whether or not the protocol worked, and the whole
point of unanimity is that it cannot be talked out of.

Clocks are injected throughout. No test sleeps for a real window, which is why
the 2 h ratification class of problem is testable at all.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPO_ROOT / "shared"


def _load(name: str, path: Path):
    """Load a shared module by path, registering it before exec.

    The sys.modules registration is not optional: @dataclass resolves its own
    module through sys.modules, and skipping it raises an AttributeError about
    __dict__ that gives no hint what went wrong.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def consensus():
    return _load("sparknet_consensus", SHARED / "sparknet-consensus.py")


@pytest.fixture(scope="module")
def authz():
    return _load("sparknet_authz", SHARED / "sparknet-authz.py")


@pytest.fixture(scope="module")
def cluster():
    """Three members, each with a real cluster keypair.

    Derived deterministically from a seed so a failure is reproducible, but these
    are genuine Ed25519 keys and genuine signatures.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private: dict[str, str] = {}
    members = []
    for name in ("alpha", "beta", "gamma"):
        raw = hashlib.sha256(f"sparknet-test-cluster-{name}".encode()).digest()
        key = Ed25519PrivateKey.from_private_bytes(raw)
        private[name] = base64.b64encode(
            key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
        ).decode()
        members.append(
            {
                "node_id": name,
                "fingerprint": hashlib.sha256(f"fp-{name}".encode()).hexdigest(),
                "wireguard_pubkey": base64.b64encode(
                    key.public_key().public_bytes(
                        serialization.Encoding.Raw, serialization.PublicFormat.Raw
                    )
                ).decode(),
                "cluster_pubkey": base64.b64encode(
                    key.public_key().public_bytes(
                        serialization.Encoding.Raw, serialization.PublicFormat.Raw
                    )
                ).decode(),
            }
        )
    return {"members": members, "private": private}


def _root(members, master: str, nonce: str = "nonce-1", clock=None) -> dict:
    return {
        "version": "1.0",
        "nonce": nonce,
        "formed_at": (clock or _clock)().isoformat(),
        "members": members,
        "master_node_id": master,
        "master_pubkey": next(m["cluster_pubkey"] for m in members if m["node_id"] == master),
    }


def _clock() -> datetime:
    return datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _vote(consensus, cluster, voter: str, candidate: str, election: str, nonce: str, clock=None):
    return consensus.sign_vote(
        {
            "node_id": voter,
            "candidate_node_id": candidate,
            "election_id": election,
            "nonce": nonce,
            "cast_at": (clock or _clock)().isoformat(),
        },
        cluster["private"][voter],
    ).as_dict()


# --- cluster shape ------------------------------------------------------------


def test_a_cluster_is_three_members_and_that_is_not_a_parameter(consensus):
    assert consensus.CLUSTER_SIZE == 3
    assert consensus.UNANIMITY == 3, (
        "unanimity is the whole point; if this drifts to a majority, one bad node "
        "paired with one other can install a master"
    )


def test_root_bytes_do_not_depend_on_member_order(consensus, cluster):
    """Two nodes listing members differently must agree on what they signed."""
    forward = consensus.root_bytes(_root(cluster["members"], "beta"))
    shuffled = consensus.root_bytes(_root(list(reversed(cluster["members"])), "beta"))
    assert forward == shuffled, (
        "member order changed the canonical bytes, so two nodes could compute "
        "different roots for the same agreement"
    )


def test_root_bytes_ignore_operational_metadata(consensus, cluster):
    """Anything outside the agreement fields must not change the root."""
    root = _root(cluster["members"], "beta")
    with_noise = dict(root, hostname="alpha.lan", note="operator comment")
    assert consensus.root_bytes(root) == consensus.root_bytes(with_noise)


# --- the core property: one member cannot elect itself ------------------------


def test_one_member_voting_three_times_has_cast_one_vote(consensus, cluster):
    result = consensus.tally(
        [_vote(consensus, cluster, "alpha", "alpha", "e1", f"n{i}") for i in range(3)],
        cluster["members"],
        "e1",
    )
    assert result["agreed"] is False
    assert result["reason"] == consensus.REASON_NOT_AGREED
    assert result["counts"] == {"alpha": ["alpha"]}, (
        f"three votes from one member must collapse to one, got {result['counts']}"
    )


def test_two_of_three_is_not_enough(consensus, cluster):
    result = consensus.tally(
        [
            _vote(consensus, cluster, "alpha", "gamma", "e1", "n1"),
            _vote(consensus, cluster, "beta", "gamma", "e1", "n2"),
        ],
        cluster["members"],
        "e1",
    )
    assert result["agreed"] is False, (
        "a 2-of-3 majority would let one compromised node pair with any other to "
        "install a hostile master"
    )
    assert result["counts"] == {"gamma": ["alpha", "beta"]}


def test_three_distinct_members_unanimously_elect(consensus, cluster):
    result = consensus.tally(
        [
            _vote(consensus, cluster, "alpha", "gamma", "e1", "n1"),
            _vote(consensus, cluster, "beta", "gamma", "e1", "n2"),
            _vote(consensus, cluster, "gamma", "gamma", "e1", "n3"),
        ],
        cluster["members"],
        "e1",
    )
    assert result["agreed"] is True
    assert result["master_node_id"] == "gamma"
    assert result["voters"] == ["alpha", "beta", "gamma"]


def test_a_member_voting_twice_for_different_candidates_is_rejected(consensus, cluster):
    """Equivocation is not agreement with anyone."""
    result = consensus.tally(
        [
            _vote(consensus, cluster, "alpha", "beta", "e1", "n1"),
            _vote(consensus, cluster, "alpha", "gamma", "e1", "n2"),
            _vote(consensus, cluster, "gamma", "beta", "e1", "n3"),
        ],
        cluster["members"],
        "e1",
    )
    assert result["agreed"] is False
    assert result["reason"] == consensus.REASON_MEMBER_ALREADY_VOTED


def test_a_vote_from_a_non_member_does_not_count(consensus, cluster):
    intruder = {"node_id": "intruder"}
    result = consensus.tally(
        [
            _vote(consensus, cluster, "alpha", "beta", "e1", "n1"),
            _vote(consensus, cluster, "beta", "beta", "e1", "n2"),
            _vote(consensus, cluster, "gamma", "beta", "e1", "n3"),
            {
                "node_id": "intruder",
                "candidate_node_id": "beta",
                "election_id": "e1",
                "nonce": "n4",
                "cast_at": _clock().isoformat(),
                "signature_b64": "AAAA",
            },
        ],
        cluster["members"],
        "e1",
    )
    # The three real members still agree; the intruder is simply not evidence.
    assert result["agreed"] is True
    assert "intruder" not in result["voters"]
    assert intruder  # keeps the fixture honest


def test_votes_from_another_election_are_not_counted(consensus, cluster):
    """Replay guard: an old election's votes must not elect anyone now."""
    result = consensus.tally(
        [
            _vote(consensus, cluster, "alpha", "beta", "old-election", "n1"),
            _vote(consensus, cluster, "beta", "beta", "old-election", "n2"),
            _vote(consensus, cluster, "gamma", "beta", "old-election", "n3"),
        ],
        cluster["members"],
        "new-election",
    )
    assert result["agreed"] is False
    assert "no votes for this election" in result["detail"]


# --- root verification --------------------------------------------------------


def test_a_fully_signed_root_verifies(consensus, cluster):
    signed = consensus.attach_root_signatures(_root(cluster["members"], "beta"), cluster["private"])
    ok, reason = consensus.verify_root(signed)
    assert ok is True, reason


def test_a_root_signed_by_strangers_is_rejected(consensus, cluster):
    """The rule that stops a root naming members while strangers sign it.

    All three signatures are cryptographically valid — they just come from keys
    the root never names. Without checking against the root's own members, a
    root that names anyone it likes would verify.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    strangers: dict[str, str] = {}
    for name in ("alpha", "beta", "gamma"):
        raw = hashlib.sha256(f"stranger-{name}".encode()).digest()
        strangers[name] = base64.b64encode(
            Ed25519PrivateKey.from_private_bytes(raw).private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
        ).decode()

    signed = consensus.attach_root_signatures(_root(cluster["members"], "beta"), strangers)
    ok, reason = consensus.verify_root(signed)
    assert ok is False, "a root co-signed by keys it does not name must not verify"
    assert consensus.REASON_BAD_SIGNATURE in reason


def test_a_root_missing_one_signature_is_rejected(consensus, cluster):
    signed = consensus.attach_root_signatures(_root(cluster["members"], "beta"), cluster["private"])
    del signed["signatures"]["gamma"]
    ok, reason = consensus.verify_root(signed)
    assert ok is False
    assert consensus.REASON_MISSING_SIGNATURE in reason


def test_a_root_signed_by_a_fourth_party_is_rejected(consensus, cluster):
    signed = consensus.attach_root_signatures(_root(cluster["members"], "beta"), cluster["private"])
    signed["signatures"]["delta"] = signed["signatures"]["alpha"]
    ok, reason = consensus.verify_root(signed)
    assert ok is False
    assert consensus.REASON_SIGNER_NOT_A_MEMBER in reason


def test_a_root_with_two_members_is_rejected(consensus, cluster):
    root = _root(cluster["members"][:2], "beta")
    signed = consensus.attach_root_signatures(root, cluster["private"])
    ok, reason = consensus.verify_root(signed)
    assert ok is False
    assert consensus.REASON_WRONG_MEMBER_COUNT in reason


def test_a_root_naming_a_duplicate_member_is_rejected(consensus, cluster):
    members = [dict(m) for m in cluster["members"]]
    members[2]["node_id"] = members[1]["node_id"]
    root = _root(members, "beta")
    signed = consensus.attach_root_signatures(root, cluster["private"])
    ok, reason = consensus.verify_root(signed)
    assert ok is False
    assert consensus.REASON_DUPLICATE_MEMBER in reason


def test_a_master_outside_the_membership_is_rejected(consensus, cluster):
    """A root may not install a master that is not one of its own members."""
    root = dict(_root(cluster["members"], "beta"))
    root["master_node_id"] = "stranger"
    signed = consensus.attach_root_signatures(root, cluster["private"])
    ok, reason = consensus.verify_root(signed)
    assert ok is False
    assert consensus.REASON_SIGNER_NOT_A_MEMBER in reason


def test_tampering_with_the_root_after_signing_is_caught(consensus, cluster):
    """Any change to a signed field invalidates all three signatures."""
    signed = consensus.attach_root_signatures(_root(cluster["members"], "beta"), cluster["private"])
    tampered = dict(signed, master_node_id="gamma")
    ok, reason = consensus.verify_root(tampered)
    assert ok is False
    assert consensus.REASON_BAD_SIGNATURE in reason


def test_swapping_a_member_key_after_signing_is_caught(consensus, cluster):
    """Changing who a member *is* invalidates the agreement about it."""
    members = [dict(m) for m in cluster["members"]]
    root = _root(members, "beta")
    signed = consensus.attach_root_signatures(root, cluster["private"])
    signed["members"] = [dict(m) for m in members]
    signed["members"][0]["cluster_pubkey"] = members[1]["cluster_pubkey"]
    ok, _ = consensus.verify_root(signed)
    assert ok is False, (
        "a member's key swapped after signing must invalidate the root, or a "
        "member could be silently replaced"
    )


# --- re-formation -------------------------------------------------------------


def test_a_new_root_supersedes_the_old_one(consensus, cluster):
    """Changing the master means a new root, and the old key stops counting."""
    first = consensus.attach_root_signatures(
        _root(cluster["members"], "beta", nonce="first"), cluster["private"]
    )
    second = consensus.attach_root_signatures(
        _root(cluster["members"], "gamma", nonce="second"), cluster["private"]
    )
    assert consensus.verify_root(second, trust=first)[0] is True

    authorised = consensus.authorised_master_pubkey(second)
    assert authorised == second["master_pubkey"]
    assert authorised != first["master_pubkey"], (
        "after re-formation the previous master's key must no longer be authorised"
    )


def test_replaying_a_root_is_refused(consensus, cluster):
    signed = consensus.attach_root_signatures(_root(cluster["members"], "beta"), cluster["private"])
    ok, reason = consensus.verify_root(signed, trust=signed)
    assert ok is False
    assert "already the root in force" in reason, (
        "re-presenting the root in force must be refused, so a capture cannot be "
        "replayed to look like a fresh agreement"
    )


def test_an_unverified_root_authorises_nothing(consensus, cluster):
    forged = dict(_root(cluster["members"], "beta"), signatures={"alpha": "AAAA"})
    assert consensus.authorised_master_pubkey(forged) is None


# --- one crypto implementation ------------------------------------------------


def test_consensus_does_not_reimplement_ed25519(consensus):
    """All signing goes through sparknet-authz. Two crypto paths would be a
    second trust boundary that has to agree byte-for-byte."""
    source = (SHARED / "sparknet-consensus.py").read_text()
    for forbidden in ("Ed25519PrivateKey.from_private_bytes(hashlib",
                      "sha512", "nacl", "libsodium"):
        assert forbidden not in source, (
            f"consensus module appears to implement crypto itself: {forbidden}"
        )
    assert "def _load_authz" in source, (
        "consensus must load sparknet-authz by path rather than reimplementing it"
    )
    # And it must refuse to run without it, not silently degrade.
    assert "refuses to reimplement" in source


def test_consensus_never_calls_the_wall_clock(consensus):
    """Every deadline is injected. A consensus test that waits for a real window
    is a test nobody runs, and a missed window is invisible until production."""
    source = (SHARED / "sparknet-consensus.py").read_text()
    for forbidden in ("datetime.now(", "datetime.utcnow(", "time.time("):
        assert forbidden not in source, (
            f"consensus module reads the wall clock ({forbidden}); every deadline "
            f"must be injected"
        )
    assert "clock" in source


def test_a_naive_clock_is_refused(consensus, cluster):
    """Three nodes must not disagree about what time it is."""
    with pytest.raises(consensus.ConsensusError, match="naive datetime"):
        consensus.tally(
            [_vote(consensus, cluster, m["node_id"], "beta", "e1", f"n{m['node_id']}")
             for m in cluster["members"]],
            cluster["members"],
            "e1",
        ) if False else consensus._now(lambda: datetime(2026, 10, 5, 12, 0))


# --- the production signing ceremony is one key at a time ----------------------


def test_a_member_signs_a_root_with_only_its_own_key(consensus, cluster):
    """The live path: one node, one key, one signature map entry."""
    root = _root(cluster["members"], "alpha")
    signatures = consensus.sign_root(root, "beta", cluster["private"]["beta"])
    assert set(signatures) == {"beta"}, (
        "a member must sign for itself only; one process holding three keys could "
        "produce a root alone, which is what 2-of-3 refusal exists to prevent"
    )


def test_a_node_cannot_sign_a_root_it_is_not_a_member_of(consensus, cluster):
    """Otherwise a node could add itself to a root, which is self-election."""
    root = _root(cluster["members"], "alpha")
    with pytest.raises(consensus.ConsensusError, match="not a member"):
        consensus.sign_root(root, "stranger", cluster["private"]["alpha"])


def test_three_single_key_signatures_merge_into_a_valid_root(consensus, cluster):
    """This is the ceremony that replaces attach_root_signatures in production."""
    members = cluster["members"]
    root = _root(members, "alpha")
    maps = [consensus.sign_root(root, m["node_id"], cluster["private"][m["node_id"]])
            for m in members]

    signed = consensus.merge_root_signatures(root, maps)

    ok, reason = consensus.verify_root(signed)
    assert ok, f"the merged root must verify, got {reason!r}"
    alpha_pubkey = next(m["cluster_pubkey"] for m in members if m["node_id"] == "alpha")
    assert consensus.authorised_master_pubkey(signed) == alpha_pubkey


def test_merging_refuses_a_root_that_is_still_incomplete(consensus, cluster):
    """Fail-closed: a root missing one signature is not a root."""
    members = cluster["members"]
    root = _root(members, "alpha")
    maps = [consensus.sign_root(root, m["node_id"], cluster["private"][m["node_id"]])
            for m in members]
    with pytest.raises(consensus.ConsensusError, match="unsigned by"):
        consensus.merge_root_signatures(root, maps[:2])


def test_a_member_signing_twice_is_refused_rather_than_overwritten(consensus, cluster):
    """Equivocation is a fact worth preserving, not a value to replace."""
    members = cluster["members"]
    root = _root(members, "alpha")
    first = consensus.sign_root(root, "beta", cluster["private"]["beta"])
    second = consensus.sign_root(root, "beta", cluster["private"]["beta"])
    with pytest.raises(consensus.ConsensusError, match="already signed"):
        consensus.merge_root_signatures(root, [first, second])


def test_the_merge_refuses_a_signature_from_outside_the_membership(consensus, cluster):
    members = cluster["members"]
    root = _root(members, "alpha")
    maps = [consensus.sign_root(root, m["node_id"], cluster["private"][m["node_id"]])
            for m in members]
    maps.append({"stranger": "AAAA"})
    with pytest.raises(consensus.ConsensusError, match="not a member"):
        consensus.merge_root_signatures(root, maps)


def test_consensus_does_not_touch_cryptography_directly(authz):
    """One crypto implementation, or the count is wrong.

    `sign_vote` and `sign_root` previously loaded `sparknet-authz` and then
    imported `cryptography` anyway, because `authz` had no
    private-key-from-base64 primitive. Ruff caught it as an unused import; this
    test is why it stays fixed.
    """
    source = Path(authz.__file__).with_name("sparknet-consensus.py").read_text()
    assert "from cryptography" not in source and "import cryptography" not in source, (
        "sparknet-consensus.py must delegate all Ed25519 work to sparknet-authz.py; "
        "a second key-parsing path is a second place for a length bug to hide"
    )
    # The delegation must be real, not decorative.
    assert callable(authz.private_key_from_b64)
    assert callable(authz.sign_bytes)
    assert "private_key_from_b64" in source and "sign_bytes" in source


def test_a_private_key_that_is_not_32_bytes_is_refused_by_authz(authz):
    """The shared helper is the only place that checks the length, so check it here."""
    with pytest.raises(Exception, match="32 bytes"):
        authz.private_key_from_b64("aGVsbG8=")  # "hello"


def test_sign_bytes_round_trips_through_verify_signature(authz, cluster):
    """The new helper and the existing verifier must agree, or roots break silently."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(cluster["private"]["alpha"]))
    message = b"canonical bytes"
    signature = authz.sign_bytes(key, message)
    assert authz.verify_signature(key.public_key(), signature, message)
    assert not authz.verify_signature(key.public_key(), signature, b"other bytes")

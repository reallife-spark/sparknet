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
                    key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                ).decode(),
                "cluster_pubkey": base64.b64encode(
                    key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
                ).decode(),
            }
        )
    return {"members": members, "private": private}


def _root(
    members,
    master: str,
    nonce: str = "nonce-1",
    clock=None,
    previous_root_id: str = "",
    version: str = "1.1",
    epoch: int = 0,
) -> dict:
    root = {
        "version": version,
        "nonce": nonce,
        "formed_at": (clock or _clock)().isoformat(),
        "members": members,
        "master_node_id": master,
        "master_pubkey": next(m["cluster_pubkey"] for m in members if m["node_id"] == master),
    }
    if version != "1.0":
        root["previous_root_id"] = previous_root_id
    if version >= "1.2":
        root["epoch"] = epoch
    return root


def _attested_proof(
    consensus,
    cluster,
    removed: str,
    parent_root_id: str,
    survivors,
    nonce: str = "rp-1",
    signers=None,
    clock=None,
) -> dict:
    """A removal proof signed by every survivor with its cluster key.

    ``signers`` overrides the set that actually signs, which is how a test
    forges a proof that omits a survivor.
    """
    proof = {
        "removed_node_id": removed,
        "parent_root_id": parent_root_id,
        "kind": "attested",
        "nonce": nonce,
        "ts": (clock or _clock)().isoformat(),
    }
    for name in signers if signers is not None else survivors:
        proof = consensus.sign_removal_proof(proof, name, cluster["private"][name])
    return proof


def _revocation_proof(consensus, cluster, removed: str, parent_root_id: str, author: str, nonce="rp-1"):
    """A removal proof signed by the parent's elected Master alone."""
    proof = {
        "removed_node_id": removed,
        "parent_root_id": parent_root_id,
        "kind": "revocation",
        "nonce": nonce,
        "ts": _clock().isoformat(),
    }
    return consensus.sign_removal_proof(proof, author, cluster["private"][author])


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


def test_a_cluster_is_a_pair_or_a_trio_and_that_is_not_a_parameter(consensus):
    """Two or three members; unanimity is n-of-n, never a fixed count."""
    assert consensus.MIN_CLUSTER_SIZE == 2
    assert consensus.MAX_CLUSTER_SIZE == 3
    assert not hasattr(consensus, "CLUSTER_SIZE"), (
        "the old fixed-size flag must be gone, or a reader would think three is the only lawful cluster"
    )


def test_root_bytes_do_not_depend_on_member_order(consensus, cluster):
    """Two nodes listing members differently must agree on what they signed."""
    forward = consensus.root_bytes(_root(cluster["members"], "beta"))
    shuffled = consensus.root_bytes(_root(list(reversed(cluster["members"])), "beta"))
    assert forward == shuffled, (
        "member order changed the canonical bytes, so two nodes could compute different roots for the same agreement"
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
        "a 2-of-3 majority would let one compromised node pair with any other to install a hostile master"
    )
    assert result["counts"] == {"gamma": ["alpha", "beta"]}


def test_a_pair_needs_both_members_to_agree(consensus, cluster):
    """2-of-2 unanimity: neither member can install a master on its own."""
    pair_members = [m for m in cluster["members"] if m["node_id"] in ("alpha", "beta")]

    lone = consensus.tally(
        [_vote(consensus, cluster, "alpha", "alpha", "e1", "n1")],
        pair_members,
        "e1",
    )
    assert lone["agreed"] is False
    assert lone["reason"] == consensus.REASON_NOT_AGREED
    assert lone["detail"].endswith("best had 1"), "one member's self-vote must not reach a 2-of-2 threshold"

    both = consensus.tally(
        [
            _vote(consensus, cluster, "alpha", "alpha", "e1", "n1"),
            _vote(consensus, cluster, "beta", "alpha", "e1", "n2"),
        ],
        pair_members,
        "e1",
    )
    assert both["agreed"] is True
    assert both["master_node_id"] == "alpha"
    assert both["voters"] == ["alpha", "beta"]


def test_a_pair_root_verifies_when_both_sign_and_refuses_a_lone_signature(consensus, cluster):
    pair_members = [m for m in cluster["members"] if m["node_id"] in ("alpha", "beta")]
    pair_private = {k: v for k, v in cluster["private"].items() if k in ("alpha", "beta")}

    lone_signed = {k: consensus.sign_root(_root(pair_members, "alpha"), k, v) for k, v in pair_private.items()}
    root = dict(_root(pair_members, "alpha"))
    root["signatures"] = {"alpha": lone_signed["alpha"]["alpha"]}
    ok, reason = consensus.verify_root(root)
    assert ok is False and consensus.REASON_MISSING_SIGNATURE in reason, (
        "a root co-signed by only one member of a pair must be refused"
    )

    both_signed = {k: consensus.sign_root(_root(pair_members, "alpha"), k, v) for k, v in pair_private.items()}
    root = dict(_root(pair_members, "alpha"))
    root["signatures"] = {k: both_signed[k][k] for k in pair_private}
    ok, reason = consensus.verify_root(root)
    assert ok is True, reason


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


def test_a_root_outside_the_pair_or_trio_bounds_is_rejected(consensus, cluster):
    """A cluster is 2 or 3 members; 1 is not a cluster, 4 is a different protocol."""
    base = cluster["members"]
    extra = [
        {
            "node_id": f"overflow-{i}",
            "fingerprint": hashlib.sha256(f"fp-{i}".encode()).hexdigest(),
            "wireguard_pubkey": "bHlwdG8tZ2FwdC1maWxsZXItMDk9PT0=",  # filler, not a secret
            "cluster_pubkey": base[0]["cluster_pubkey"],
        }
        for i in range(2)
    ]
    overflow_members = base + extra
    signed_by = {**cluster["private"], **{e["node_id"]: cluster["private"]["alpha"] for e in extra}}
    for count, members in ((1, base[:1]), (4, overflow_members), (5, overflow_members)):
        sliced = members[:count] if count == 1 else overflow_members[:count]
        root = _root(sliced, sliced[0]["node_id"])
        signed = consensus.attach_root_signatures(root, signed_by)
        ok, reason = consensus.verify_root(signed)
        assert ok is False, f"a {count}-member root must be rejected"
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
        "a member's key swapped after signing must invalidate the root, or a member could be silently replaced"
    )


# --- re-formation -------------------------------------------------------------


def test_a_new_root_supersedes_the_old_one(consensus, cluster):
    """Changing the master means a new root, and the old key stops counting.

    Policy B makes supersession a chain: the new root names the held root as
    `previous_root_id`, and only that parented root may replace it. A second
    root with a new nonce but no lineage is a stranger, not a successor.
    """
    first = consensus.attach_root_signatures(_root(cluster["members"], "beta", nonce="first"), cluster["private"])
    chained = consensus.attach_root_signatures(
        _root(cluster["members"], "gamma", nonce="second", previous_root_id=consensus.root_id(first)),
        cluster["private"],
    )
    assert consensus.verify_root(chained, trust=first)[0] is True

    authorised = consensus.authorised_master_pubkey(chained)
    assert authorised == chained["master_pubkey"]
    assert authorised != first["master_pubkey"], (
        "after re-formation the previous master's key must no longer be authorised"
    )


def test_a_new_nonce_without_the_chain_is_refused(consensus, cluster):
    """The F1 gap, closed: a well-signed root that does not descend from the
    held root is refused on the trust path, even with a fresh nonce."""
    first = consensus.attach_root_signatures(_root(cluster["members"], "beta", nonce="first"), cluster["private"])
    stranger = consensus.attach_root_signatures(_root(cluster["members"], "gamma", nonce="second"), cluster["private"])
    ok, reason = consensus.verify_root(stranger, trust=first)
    assert ok is False
    assert consensus.REASON_UNCHAINED in reason
    assert "previous_root_id" in reason, reason


def test_a_legacy_1_0_root_still_verifies_with_its_original_id(consensus, cluster):
    """The schema bump must not invalidate a root already in force.

    A 1.0 root signed six fields and had no `previous_root_id`. The canonical
    form is version-aware so that root keeps verifying against its original
    bytes and keeps its id — the migration seam the Step 16 deploy depends on.
    """
    legacy = {
        "version": "1.0",
        "nonce": "legacy-1",
        "formed_at": _clock().isoformat(),
        "members": cluster["members"],
        "master_node_id": "beta",
        "master_pubkey": next(m["cluster_pubkey"] for m in cluster["members"] if m["node_id"] == "beta"),
    }
    signed = consensus.attach_root_signatures(legacy, cluster["private"])
    assert consensus.verify_root(signed) == (True, consensus.REASON_OK)
    assert "previous_root_id" not in consensus.canonical_root(signed), (
        "a 1.0 root must not gain previous_root_id: it was not signed, and adding "
        "it would change the bytes and void every co-signature"
    )


def test_a_1_1_root_chains_to_a_1_0_parent_by_its_legacy_id(consensus, cluster):
    """A chained re-formation can name a 1.0 root as its predecessor.

    The parent's id is computed the 1.0 way, so the child's `previous_root_id`
    is the *live* root id the cluster already holds. This is what makes the
    upgrade to 1.1 a forward step rather than a fresh election.
    """
    legacy = consensus.attach_root_signatures(
        {
            "version": "1.0",
            "nonce": "legacy-1",
            "formed_at": _clock().isoformat(),
            "members": cluster["members"],
            "master_node_id": "beta",
            "master_pubkey": next(m["cluster_pubkey"] for m in cluster["members"] if m["node_id"] == "beta"),
        },
        cluster["private"],
    )
    parent_id = consensus.root_id(legacy)
    child = consensus.attach_root_signatures(
        _root(cluster["members"], "gamma", nonce="child-1", previous_root_id=parent_id),
        cluster["private"],
    )
    assert consensus.verify_root(child, trust=legacy) == (True, consensus.REASON_OK)

    orphan = consensus.attach_root_signatures(
        _root(cluster["members"], "gamma", nonce="child-2", previous_root_id="0" * 64),
        cluster["private"],
    )
    ok, reason = consensus.verify_root(orphan, trust=legacy)
    assert ok is False
    assert consensus.REASON_UNCHAINED in reason


def test_a_chained_root_may_not_add_a_member(consensus, cluster):
    """Re-formation may replace the master or shrink membership; a chained root
    that ADDS a member is the join ceremony, which is a different contract."""

    def _new_member(name: str) -> tuple[dict, str]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        raw = hashlib.sha256(f"sparknet-test-cluster-{name}".encode()).digest()
        key = Ed25519PrivateKey.from_private_bytes(raw)
        private_b64 = base64.b64encode(
            key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
        ).decode()
        public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return (
            {
                "node_id": name,
                "fingerprint": hashlib.sha256(f"fp-{name}".encode()).hexdigest(),
                "wireguard_pubkey": base64.b64encode(public).decode(),
                "cluster_pubkey": base64.b64encode(public).decode(),
            },
            private_b64,
        )

    first = consensus.attach_root_signatures(_root(cluster["members"], "beta", nonce="first"), cluster["private"])
    delta, delta_priv = _new_member("delta")
    joined = consensus.attach_root_signatures(
        _root(
            [*cluster["members"], delta],
            "gamma",
            nonce="second",
            previous_root_id=consensus.root_id(first),
        ),
        {**cluster["private"], "delta": delta_priv},
    )
    ok, reason = consensus.verify_root(joined, trust=first)
    assert ok is False
    assert consensus.REASON_UNCHAINED in reason
    assert "ADDS a member" in reason, reason


def test_a_chained_root_may_not_shrink_below_the_minimum(consensus, cluster):
    """A lone survivor holds a removal proof, not a cluster."""
    first = consensus.attach_root_signatures(_root(cluster["members"], "beta", nonce="first"), cluster["private"])
    lone = consensus.attach_root_signatures(
        _root(
            [cluster["members"][0]],
            cluster["members"][0]["node_id"],
            nonce="second",
            previous_root_id=consensus.root_id(first),
        ),
        {cluster["members"][0]["node_id"]: cluster["private"][cluster["members"][0]["node_id"]]},
    )
    ok, reason = consensus.verify_root(lone, trust=first)
    assert ok is False
    assert consensus.REASON_UNCHAINED in reason, reason


# --- reduced membership (1.2 removal proofs) ---------------------------------


def _genesis_12(consensus, cluster, master: str = "beta", nonce: str = "genesis"):
    return consensus.attach_root_signatures(
        _root(cluster["members"], master, nonce=nonce, version="1.2", epoch=0),
        cluster["private"],
    )


def _reduced(
    consensus,
    cluster,
    genesis,
    survivors,
    master: str,
    removal_proofs,
    nonce: str = "reduced",
    epoch: int = 1,
    signers=None,
):
    child = _root(
        survivors,
        master,
        nonce=nonce,
        previous_root_id=consensus.root_id(genesis),
        version="1.2",
        epoch=epoch,
    )
    if removal_proofs is not None:
        child["removal_proofs"] = removal_proofs
    names = signers if signers is not None else [m["node_id"] for m in survivors]
    return consensus.attach_root_signatures(child, {name: cluster["private"][name] for name in names})


def test_a_1_2_reduced_root_with_an_attested_proof_verifies(consensus, cluster):
    """F2: N -> N-1 with every survivor attesting the drop.

    The survivors form a chained child naming only themselves; the dropped
    member is evidenced by a statement every survivor signed. Both the trust
    path and the whole-chain path must accept it, and the child must name only
    survivors.
    """
    genesis = _genesis_12(consensus, cluster)
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    proof = _attested_proof(consensus, cluster, "gamma", consensus.root_id(genesis), ["alpha", "beta"])
    signed = _reduced(consensus, cluster, genesis, survivors, "beta", [proof])
    assert consensus.verify_root(signed, trust=genesis) == (True, consensus.REASON_OK)
    assert consensus.verify_chain([signed, genesis]) == (True, consensus.REASON_OK)
    assert {m["node_id"] for m in signed["members"]} == {"alpha", "beta"}
    assert signed["epoch"] == 1


def test_a_1_2_reduced_root_with_a_revocation_proof_verifies(consensus, cluster):
    """F2: the parent's Master may revoke instead, and that suffices.

    The contract already lets the elected Master revoke a node unilaterally; a
    `revocation` proof is that act made durable across the chain, signed with
    the operational key the parent root authorises.
    """
    genesis = _genesis_12(consensus, cluster, master="beta")
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    proof = _revocation_proof(consensus, cluster, "gamma", consensus.root_id(genesis), "beta")
    signed = _reduced(consensus, cluster, genesis, survivors, "beta", [proof])
    assert consensus.verify_root(signed, trust=genesis) == (True, consensus.REASON_OK)
    assert consensus.verify_chain([signed, genesis]) == (True, consensus.REASON_OK)


def test_a_1_2_reduced_root_chains_to_a_1_1_parent(consensus, cluster):
    """The migration seam: a legacy 1.1 parent is epoch 0, so the first 1.2
    re-formation needs no re-election to be its child."""
    parent = consensus.attach_root_signatures(
        _root(cluster["members"], "beta", nonce="legacy-parent", version="1.1"),
        cluster["private"],
    )
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    proof = _attested_proof(consensus, cluster, "gamma", consensus.root_id(parent), ["alpha", "beta"])
    signed = _reduced(consensus, cluster, parent, survivors, "beta", [proof], epoch=1)
    assert consensus.verify_root(signed, trust=parent) == (True, consensus.REASON_OK)


def test_a_reduced_root_without_a_removal_proof_is_refused(consensus, cluster):
    genesis = _genesis_12(consensus, cluster)
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    signed = _reduced(consensus, cluster, genesis, survivors, "beta", None)
    ok, reason = consensus.verify_root(signed, trust=genesis)
    assert ok is False
    assert consensus.REASON_MISSING_REMOVAL_PROOF in reason, reason


def test_a_reduced_root_naming_the_removed_member_is_refused(consensus, cluster):
    """The child still names gamma but only the survivors signed: a knock-out
    that keeps the member's name is not a lawful reduction."""
    genesis = _genesis_12(consensus, cluster)
    child = _root(
        cluster["members"],
        "beta",
        nonce="reduced",
        previous_root_id=consensus.root_id(genesis),
        version="1.2",
        epoch=1,
    )
    signatures = {name: consensus.sign_root(child, name, cluster["private"][name])[name] for name in ("alpha", "beta")}
    signed = dict(child, signatures=signatures)
    ok, reason = consensus.verify_root(signed, trust=genesis)
    assert ok is False
    assert consensus.REASON_MISSING_SIGNATURE in reason, reason
    assert "gamma" in reason, reason


def test_a_proof_for_a_member_who_stays_is_refused(consensus, cluster):
    """The dropped set must equal the evidenced set exactly: a proof for a
    survivor is a forged drop record."""
    genesis = _genesis_12(consensus, cluster)
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    good = _attested_proof(consensus, cluster, "gamma", consensus.root_id(genesis), ["alpha", "beta"])
    extra = _attested_proof(
        consensus,
        cluster,
        "beta",
        consensus.root_id(genesis),
        ["alpha", "beta"],
        nonce="rp-2",
    )
    signed = _reduced(consensus, cluster, genesis, survivors, "beta", [good, extra])
    ok, reason = consensus.verify_root(signed, trust=genesis)
    assert ok is False
    assert consensus.REASON_UNEXPECTED_REMOVAL_PROOF in reason, reason
    assert "beta" in reason, reason


def test_an_attested_proof_missing_a_survivor_is_refused(consensus, cluster):
    genesis = _genesis_12(consensus, cluster)
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    forged = _attested_proof(
        consensus,
        cluster,
        "gamma",
        consensus.root_id(genesis),
        ["alpha", "beta"],
        signers=["alpha"],
    )
    signed = _reduced(consensus, cluster, genesis, survivors, "beta", [forged])
    ok, reason = consensus.verify_root(signed, trust=genesis)
    assert ok is False
    assert consensus.REASON_BAD_REMOVAL_PROOF in reason, reason
    assert "beta" in reason, reason


def test_a_proof_naming_the_wrong_parent_is_refused(consensus, cluster):
    genesis = _genesis_12(consensus, cluster)
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    proof = _attested_proof(consensus, cluster, "gamma", "0" * 64, ["alpha", "beta"])
    signed = _reduced(consensus, cluster, genesis, survivors, "beta", [proof])
    ok, reason = consensus.verify_root(signed, trust=genesis)
    assert ok is False
    assert consensus.REASON_BAD_REMOVAL_PROOF in reason, reason
    assert "root in force" in reason, reason


def test_a_reduced_root_with_the_wrong_epoch_is_refused(consensus, cluster):
    genesis = _genesis_12(consensus, cluster)
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    proof = _attested_proof(consensus, cluster, "gamma", consensus.root_id(genesis), ["alpha", "beta"])
    signed = _reduced(consensus, cluster, genesis, survivors, "beta", [proof], epoch=5)
    ok, reason = consensus.verify_root(signed, trust=genesis)
    assert ok is False
    assert consensus.REASON_UNCHAINED in reason, reason
    assert "epoch" in reason, reason


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
    for forbidden in ("Ed25519PrivateKey.from_private_bytes(hashlib", "sha512", "nacl", "libsodium"):
        assert forbidden not in source, f"consensus module appears to implement crypto itself: {forbidden}"
    assert "def _load_authz" in source, "consensus must load sparknet-authz by path rather than reimplementing it"
    # And it must refuse to run without it, not silently degrade.
    assert "refuses to reimplement" in source


def test_consensus_never_calls_the_wall_clock(consensus):
    """Every deadline is injected. A consensus test that waits for a real window
    is a test nobody runs, and a missed window is invisible until production."""
    source = (SHARED / "sparknet-consensus.py").read_text()
    for forbidden in ("datetime.now(", "datetime.utcnow(", "time.time("):
        assert forbidden not in source, (
            f"consensus module reads the wall clock ({forbidden}); every deadline must be injected"
        )
    assert "clock" in source


def test_a_naive_clock_is_refused(consensus, cluster):
    """Three nodes must not disagree about what time it is."""
    with pytest.raises(consensus.ConsensusError, match="naive datetime"):
        consensus.tally(
            [_vote(consensus, cluster, m["node_id"], "beta", "e1", f"n{m['node_id']}") for m in cluster["members"]],
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
    maps = [consensus.sign_root(root, m["node_id"], cluster["private"][m["node_id"]]) for m in members]

    signed = consensus.merge_root_signatures(root, maps)

    ok, reason = consensus.verify_root(signed)
    assert ok, f"the merged root must verify, got {reason!r}"
    alpha_pubkey = next(m["cluster_pubkey"] for m in members if m["node_id"] == "alpha")
    assert consensus.authorised_master_pubkey(signed) == alpha_pubkey


def test_merging_refuses_a_root_that_is_still_incomplete(consensus, cluster):
    """Fail-closed: a root missing one signature is not a root."""
    members = cluster["members"]
    root = _root(members, "alpha")
    maps = [consensus.sign_root(root, m["node_id"], cluster["private"][m["node_id"]]) for m in members]
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
    maps = [consensus.sign_root(root, m["node_id"], cluster["private"][m["node_id"]]) for m in members]
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

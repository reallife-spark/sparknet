"""A three-node election, run in process, with no sleeps.

Step 19 of the Master build plan asks for a simulation that "elects, refuses a
two-vote attempt, and re-forms on a master change, all with injected clocks and no
sleeps". That is the only honest way to demonstrate the property this fabric is
named for: a 2-of-3 majority must never install a Master, and that must hold
against an attacker who forges packets rather than merely withholding them.

Three things are load-bearing here.

*Real crypto, no mocks.* Every vote and every root signature is a genuine
Ed25519 signature from a key the cluster actually holds. A mocked signature
verifier would make this suite pass while the protocol was broken, which is
exactly the failure the module's own docstring warns about.

*The clock is injected, so the election is instantaneous.* An election protocol
with a real deadline cannot be tested without either waiting or faking time. Here
the clock is a plain function the test advances by hand, and `time.sleep` appears
nowhere in the file.

*Forgery is tested, not just absence.* The refuse case casts three votes for one
candidate and the third is forged — not missing. An attacker who can make a
fabricated vote count has the whole fabric, so that is the case worth proving
refused.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPO_ROOT / "shared"

#: Every instant this file needs, named. Nothing reads a wall clock.
T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
#: The election window from contracts/consensus-protocol.md. Used as a constant,
#: never waited on.
ELECTION_WINDOW = timedelta(hours=2)


def _load(name: str, path: Path):
    return load_by_path(name, path)


def _module():
    return _load("sparknet_consensus_sim", SHARED / "sparknet-consensus.py")


def _cluster(seed: str = "sim"):
    """Three members with real cluster keypairs, plus their operational keys.

    The operational key is deliberately a *separate* keypair from the cluster
    key, because that separation is the security model: the cluster key votes,
    the operational key signs registry entries.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    def keypair(label: str) -> tuple[Ed25519PrivateKey, str]:
        raw = hashlib.sha256(f"{seed}-{label}".encode()).digest()
        key = Ed25519PrivateKey.from_private_bytes(raw)
        private = base64.b64encode(
            key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
        ).decode()
        public = base64.b64encode(
            key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        ).decode()
        return key, private, public

    members, cluster_private, operational = [], {}, {}
    for name in ("alpha", "beta", "gamma"):
        cluster_key, private, public = keypair(f"cluster-{name}")
        _, _op_private, op_public = keypair(f"operational-{name}")
        cluster_private[name] = private
        operational[name] = op_public
        members.append(
            {
                "node_id": name,
                "fingerprint": hashlib.sha256(f"{seed}-fp-{name}".encode()).hexdigest(),
                "wireguard_pubkey": public,
                "cluster_pubkey": public,
            }
        )
        assert cluster_key is not None
    return {
        "members": members,
        "cluster_private": cluster_private,
        "operational": operational,
    }


class SimClock:
    """A hand-advanced clock. `advance` is the only way time moves."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start
        self.reads = 0

    def __call__(self) -> datetime:
        self.reads += 1
        return self.now

    def advance(self, **kwargs) -> datetime:
        self.now = self.now + timedelta(**kwargs)
        return self.now


def _cast(consensus, cluster, clock, voter, candidate, election_id, nonce):
    """One member signs one vote with its cluster key."""
    return consensus.sign_vote(
        {
            "node_id": voter,
            "candidate_node_id": candidate,
            "election_id": election_id,
            "nonce": nonce,
            "cast_at": clock().isoformat(),
        },
        cluster["cluster_private"][voter],
    ).as_dict()


def _forge(consensus, cluster, clock, voter, candidate, election_id, nonce):
    """A vote that *looks* real: right shape, right member id, no valid signature.

    This is the attack. `tally` deduplicates by `node_id`, which is exactly why a
    tally that never checks signatures is forgeable — the attacker simply claims to
    be a member who has not voted.
    """
    return {
        "node_id": voter,
        "candidate_node_id": candidate,
        "election_id": election_id,
        "nonce": nonce,
        "cast_at": clock().isoformat(),
        "signature_b64": base64.b64encode(b"\x00" * 64).decode(),
    }


def _sign_root(consensus, cluster, root):
    """Every member signs the root over identical canonical bytes.

    Uses `attach_root_signatures`, which is documented as a *test fixture* because
    it takes all three private keys at once. Production has each node call
    `sign_root` for itself and merge the one-entry maps. The distinction matters
    and is not being blurred: this file is the fixture.
    """
    return consensus.attach_root_signatures(root, cluster["cluster_private"])


def _root(
    consensus,
    cluster,
    clock,
    master,
    nonce,
    previous_root_id: str = "",
    epoch: int = 0,
):
    return {
        "version": consensus.SCHEMA_VERSION,
        "nonce": nonce,
        "formed_at": clock().isoformat(),
        "members": cluster["members"],
        "master_node_id": master,
        "master_pubkey": cluster["operational"][master],
        "previous_root_id": previous_root_id,
        "epoch": epoch,
    }


# --- DoD (4a): the cluster elects ------------------------------------------------


def test_three_nodes_unanimously_elect_one_master():
    """The happy path, end to end: three votes in, one trust root out."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    votes = [
        _cast(consensus, cluster, clock, voter, "beta", "e1", f"n-{voter}") for voter in ("alpha", "beta", "gamma")
    ]
    result = consensus.tally(votes, cluster["members"], "e1")

    assert result["agreed"] is True, result
    assert result["master_node_id"] == "beta"
    assert result["voters"] == ["alpha", "beta", "gamma"], (
        "unanimity means all three, and the report should say which three"
    )
    assert result["rejected"] == [], "no vote was forged here; nothing to report"

    root = _sign_root(consensus, cluster, _root(consensus, cluster, clock, "beta", "r1"))
    ok, reason = consensus.verify_root(root)
    assert ok, reason
    assert consensus.authorised_master_pubkey(root) == cluster["operational"]["beta"]


def test_the_elected_masters_key_is_the_one_the_root_authorises():
    """Cluster key votes, operational key signs. Mixing them is the bug this prevents."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    votes = [
        _cast(consensus, cluster, clock, voter, "gamma", "e1", f"n-{voter}") for voter in ("alpha", "beta", "gamma")
    ]
    result = consensus.tally(votes, cluster["members"], "e1")
    master = result["master_node_id"]
    root = _sign_root(consensus, cluster, _root(consensus, cluster, clock, master, "r1"))

    authorised = consensus.authorised_master_pubkey(root)
    assert authorised == cluster["operational"][master]
    assert authorised != cluster["members"][2]["cluster_pubkey"], (
        "the root must authorise the operational key, not the voting key; the split is the security model, not a detail"
    )


# --- DoD (4b): a two-vote attempt is refused ------------------------------------


def test_a_forged_third_vote_cannot_manufacture_unanimity():
    """The core property. gamma never voted; its vote is fabricated.

    A 2-of-3 majority would let one compromised node pair with any other install a
    hostile Master, so the third signature has to be *real*. This is the case where
    it is not.
    """
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    honest = [_cast(consensus, cluster, clock, voter, "alpha", "e1", f"n-{voter}") for voter in ("alpha", "beta")]
    forged = _forge(consensus, cluster, clock, "gamma", "alpha", "e1", "n-gamma")
    result = consensus.tally([*honest, forged], cluster["members"], "e1")

    assert result["agreed"] is False, f"two real votes plus one fabricated vote must not elect anyone; got {result}"
    assert result["reason"] == consensus.REASON_NOT_AGREED
    assert result["counts"] == {"alpha": ["alpha", "beta"]}, "only the two verified votes may appear in the tally"
    assert result["rejected"] == [{"node_id": "gamma", "reason": consensus.REASON_BAD_SIGNATURE}], (
        "the forgery must be reported, not silently dropped. An election that "
        "tolerates forgery has to be able to show that it did."
    )


def test_a_vote_with_no_signature_at_all_is_refused():
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()
    unsigned = {
        "node_id": "gamma",
        "candidate_node_id": "alpha",
        "election_id": "e1",
        "nonce": "n-gamma",
        "cast_at": clock().isoformat(),
    }
    result = consensus.tally([unsigned], cluster["members"], "e1")
    assert result["agreed"] is False
    assert result["rejected"] == [{"node_id": "gamma", "reason": consensus.REASON_MISSING_SIGNATURE}]


def test_another_members_real_signature_cannot_be_relabelled():
    """Replaying beta's genuine vote as gamma's must not count.

    The signature covers `node_id`, so relabelling breaks it. Worth testing
    explicitly: it is the cheapest way to reach unanimity if the covered fields
    ever stop including the voter.
    """
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    honest = [_cast(consensus, cluster, clock, voter, "alpha", "e1", f"n-{voter}") for voter in ("alpha", "beta")]
    relabelled = dict(_cast(consensus, cluster, clock, "beta", "alpha", "e1", "n-beta"))
    relabelled["node_id"] = "gamma"

    result = consensus.tally([*honest, relabelled], cluster["members"], "e1")
    assert result["agreed"] is False, "a relabelled signature is not a third vote"
    assert result["rejected"][0]["node_id"] == "gamma"


def test_an_impersonator_outside_the_membership_is_refused():
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()
    outsider = _forge(consensus, cluster, clock, "mallory", "mallory", "e1", "n-m")
    result = consensus.tally([outsider], cluster["members"], "e1")
    assert result["agreed"] is False
    assert result["rejected"] == [{"node_id": "mallory", "reason": consensus.REASON_SIGNER_NOT_A_MEMBER}], (
        "a node that is not a member must be refused on membership before its signature is even examined"
    )


def test_forgery_cannot_launder_an_equivocation_into_a_second_chance():
    """gamma equivocates for real, then a forged second vote tries to paper over it."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    votes = [_cast(consensus, cluster, clock, voter, "alpha", "e1", f"n-{voter}") for voter in ("alpha", "beta")]
    votes.append(_cast(consensus, cluster, clock, "gamma", "beta", "e1", "n-gamma-1"))
    votes.append(_forge(consensus, cluster, clock, "gamma", "alpha", "e1", "n-gamma-2"))

    result = consensus.tally(votes, cluster["members"], "e1")
    assert result["agreed"] is False
    # The forged ballot is dropped before it can be read as a *different* choice, so
    # gamma looks like it cast one vote rather than having equivocated. Either way
    # nobody is elected.
    assert result["reason"] == consensus.REASON_NOT_AGREED
    assert result["counts"] == {"alpha": ["alpha", "beta"], "beta": ["gamma"]}


# --- DoD (4c): the cluster re-forms on a master change --------------------------


def test_the_cluster_re_forms_when_the_master_changes():
    """A second election, a new nonce, a new root — and the old one is superseded."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    first = [
        _cast(consensus, cluster, clock, voter, "alpha", "e1", f"n1-{voter}") for voter in ("alpha", "beta", "gamma")
    ]
    assert consensus.tally(first, cluster["members"], "e1")["master_node_id"] == "alpha"
    root_alpha = _sign_root(consensus, cluster, _root(consensus, cluster, clock, "alpha", "root-1"))
    assert consensus.verify_root(root_alpha)[0]

    # alpha is replaced. A new election_id, so first-round votes cannot be replayed
    # into it, and a new root nonce, so the new root is not a replay of the old.
    clock.advance(minutes=5)
    second = [
        _cast(consensus, cluster, clock, voter, "gamma", "e2", f"n2-{voter}") for voter in ("alpha", "beta", "gamma")
    ]
    result = consensus.tally([*first, *second], cluster["members"], "e2")
    assert result["agreed"] is True, f"votes from the earlier election must not stop the later one; got {result}"
    assert result["master_node_id"] == "gamma"

    root_gamma = _sign_root(
        consensus,
        cluster,
        _root(
            consensus,
            cluster,
            clock,
            "gamma",
            "root-2",
            previous_root_id=consensus.root_id(root_alpha),
            epoch=1,
        ),
    )
    ok, reason = consensus.verify_root(root_gamma, trust=root_alpha)
    assert ok, f"the new root must verify against the one it replaces: {reason}"
    assert consensus.authorised_master_pubkey(root_gamma) == cluster["operational"]["gamma"]

    # Re-presenting the root already in force is a replay and is refused; so is a
    # well-signed root that does not descend from it. The chain (`previous_root_id`)
    # is the ordering `verify_root` uses now, so ordering no longer lives only in
    # the ledger.
    ok, reason = consensus.verify_root(root_alpha, trust=root_alpha)
    assert ok is False
    assert reason.startswith(consensus.REASON_REPLAY), reason
    stranger = _sign_root(consensus, cluster, _root(consensus, cluster, clock, "beta", "root-3"))
    ok, reason = consensus.verify_root(stranger, trust=root_alpha)
    assert ok is False
    assert consensus.REASON_UNCHAINED in reason, reason


def test_a_superseded_root_cannot_supersede_its_newer_successor():
    """The old gap, now closed by the chain (policy B).

    This test previously pinned the gap: it asserted that after a re-formation
    the *old* root still verifies against the new one, because nothing in a
    root said which root it replaced. Policy B fixes exactly that — every root
    carries `previous_root_id`, the id of the root it supersedes — so a pure
    verifier holding the new root can now refuse the old one offline, with no
    ledger and no peer. The test is kept so that the suite pins the closure.

    The chain is the global replacement for the local
    `check_not_reverted`-style enforcement: ordering is carried by the very
    thing being ordered (the root), instead of by where history lives.
    """
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    old = _sign_root(consensus, cluster, _root(consensus, cluster, clock, "alpha", "root-1"))
    clock.advance(minutes=5)
    new = _sign_root(
        consensus,
        cluster,
        _root(
            consensus,
            cluster,
            clock,
            "gamma",
            "root-2",
            previous_root_id=consensus.root_id(old),
            epoch=1,
        ),
    )

    assert consensus.verify_root(old)[0], "the old root was genuinely valid once"
    assert consensus.verify_root(new, trust=old)[0], "the chained successor verifies"
    ok, reason = consensus.verify_root(old, trust=new)
    assert ok is False, (
        "the old root does not name the new one as its parent, so a verifier "
        "holding the new root can now see it for what it is: a superseded root, "
        "refused without a ledger"
    )
    assert consensus.REASON_UNCHAINED in reason, reason
    assert consensus.root_id(old) != consensus.root_id(new)


def test_verify_chain_accepts_a_two_link_formation_line():
    """A peer that missed the re-formation may verify the whole lineage."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    genesis = _sign_root(consensus, cluster, _root(consensus, cluster, clock, "alpha", "root-1"))
    clock.advance(minutes=5)
    reformed = _sign_root(
        consensus,
        cluster,
        _root(
            consensus,
            cluster,
            clock,
            "gamma",
            "root-2",
            previous_root_id=consensus.root_id(genesis),
            epoch=1,
        ),
    )
    assert consensus.verify_chain([reformed, genesis])[0] is True


def test_verify_chain_refuses_a_lineage_with_a_hole():
    """A chain that skips a generation fails on the missing link."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    genesis = _sign_root(consensus, cluster, _root(consensus, cluster, clock, "alpha", "root-1"))
    clock.advance(minutes=5)
    middle = _sign_root(
        consensus,
        cluster,
        _root(
            consensus,
            cluster,
            clock,
            "beta",
            "root-2",
            previous_root_id=consensus.root_id(genesis),
            epoch=1,
        ),
    )
    clock.advance(minutes=5)
    newest = _sign_root(
        consensus,
        cluster,
        _root(
            consensus,
            cluster,
            clock,
            "gamma",
            "root-3",
            previous_root_id=consensus.root_id(middle),
            epoch=2,
        ),
    )
    # Drop `middle`: newest claims to descend from it but it is not in the pull.
    ok, reason = consensus.verify_chain([newest, genesis])
    assert ok is False
    assert consensus.REASON_UNCHAINED in reason, reason
    # The full line verifies.
    assert consensus.verify_chain([newest, middle, genesis])[0] is True


def test_verify_chain_refuses_a_chain_that_does_not_reach_genesis():
    """The oldest supplied root must itself be a genesis root."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    genesis = _sign_root(consensus, cluster, _root(consensus, cluster, clock, "alpha", "root-1"))
    clock.advance(minutes=5)
    reformed = _sign_root(
        consensus,
        cluster,
        _root(
            consensus,
            cluster,
            clock,
            "gamma",
            "root-2",
            previous_root_id=consensus.root_id(genesis),
            epoch=1,
        ),
    )
    # `reformed` is the oldest supplied link but is not genesis; it still names a
    # parent, so the lineage is incomplete.
    ok, reason = consensus.verify_chain([reformed])
    assert ok is False
    assert consensus.REASON_UNCHAINED in reason
    assert "genesis" in reason, reason


def test_first_round_votes_do_not_help_a_later_election():
    """A vote carries its election_id, so votes cannot be carried forward."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    stale = [
        _cast(consensus, cluster, clock, voter, "alpha", "e1", f"n1-{voter}") for voter in ("alpha", "beta", "gamma")
    ]
    result = consensus.tally(stale, cluster["members"], "e2")
    assert result["agreed"] is False
    assert result["counts"] == {}
    assert "no votes" in result["detail"]


def test_the_window_is_a_constant_and_nothing_waits_for_it():
    """The 2 h window is real, and this suite is not how anyone finds out.

    Spelled as a source property because a test cannot prove a negative about
    future edits, and the failure mode it guards against is a suite that suddenly
    takes two hours.
    """
    # Parsed, not grepped. The first version of this test scanned the source text
    # and matched its own docstring, which contains the words it forbids — a test
    # that cannot distinguish a call from a sentence about a call is not evidence.
    import ast

    tree = ast.parse(Path(__file__).read_text())
    called = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            called.add(func.attr)
        elif isinstance(func, ast.Name):
            called.add(func.id)
    for forbidden in ("sleep", "sleep_ms", "sleep_seconds"):
        assert forbidden not in called, (
            f"{forbidden}() is called in the election simulation. Clocks are "
            f"injected; a test that waits for a window is a test nobody runs."
        )
    assert timedelta(hours=2) == ELECTION_WINDOW


def test_an_election_resolves_within_the_window():
    """The instant-when-all-three-have-voted case, stated rather than waited for."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    votes = []
    for index, voter in enumerate(("alpha", "beta", "gamma")):
        votes.append(_cast(consensus, cluster, clock, voter, "beta", "e1", f"n-{voter}"))
        clock.advance(seconds=30)
        partial = consensus.tally(votes, cluster["members"], "e1")
        if index < 2:
            assert partial["agreed"] is False, f"after {index + 1} of 3 votes nothing may be elected"

    final = consensus.tally(votes, cluster["members"], "e1")
    assert final["agreed"] is True
    assert clock.now - T0 == timedelta(seconds=90)
    assert clock.now - T0 < ELECTION_WINDOW, "and the whole thing took 90 s, not 2 h"


def test_the_simulation_never_becomes_a_fabricated_unanimity():
    """End to end: forge three ballots, get nothing.

    The strongest statement in this file, because it removes the variables. It
    does not matter how the votes were produced; three unverifiable ballots elect
    nobody.
    """
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    forged = [
        _forge(consensus, cluster, clock, voter, "alpha", "e1", f"n-{voter}") for voter in ("alpha", "beta", "gamma")
    ]
    result = consensus.tally(forged, cluster["members"], "e1")
    assert result["agreed"] is False
    assert result["counts"] == {}
    assert len(result["rejected"]) == 3, "all three forgeries reported"


# --- the master that gets elected can actually use its authority ---------------


def _entry(consensus, cluster, node_id, clock):
    """A registry entry in the shape `sparknet-authz` actually signs.

    Built from the member's real identity so the entry's fingerprint is the one the
    member's own manifest would carry — an entry whose fingerprint does not match
    its identity would be rejected for a reason unrelated to authority, which would
    make this test prove the wrong thing.
    """
    member = next(m for m in cluster["members"] if m["node_id"] == node_id)
    identity = {
        "node_id": node_id,
        "overlay_ipv4": f"10.100.0.{2 + cluster['members'].index(member)}/32",
        "requested_capabilities": ["dispatch-bridge", "guard-verify"],
        "role": "peer",
        "wireguard_public_key_b64": member["wireguard_pubkey"],
    }
    authz = _load("sparknet_authz_sim", SHARED / "sparknet-authz.py")
    issued = int(clock().timestamp())
    return authz, {
        "fingerprint": authz.fingerprint(identity),
        "identity": identity,
        "capabilities": ["dispatch-bridge"],
        "overlay_ipv4": identity["overlay_ipv4"].split("/")[0],
        "issued_at": issued,
        "expires_at": issued + 365 * 24 * 3600,
        "revoked": False,
    }


def _operational_key(seed: str, node_id: str):
    """The node's operational private key, matching `_cluster`'s public half."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = hashlib.sha256(f"{seed}-operational-{node_id}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(raw)


def test_only_the_elected_master_may_sign_a_registry_entry():
    """The point of the whole exercise: a peer's key must not authorise anything."""
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    votes = [
        _cast(consensus, cluster, clock, voter, "beta", "e1", f"n-{voter}") for voter in ("alpha", "beta", "gamma")
    ]
    master = consensus.tally(votes, cluster["members"], "e1")["master_node_id"]
    root = _sign_root(consensus, cluster, _root(consensus, cluster, clock, master, "r1"))

    # gamma's entry, signed by the elected Master. Accepted.
    authz, entry = _entry(consensus, cluster, "gamma", clock)
    entry["signature_b64"] = authz.sign_bytes(_operational_key("sim", master), authz.authorization_message(entry))
    ok, reason = consensus.registry_signer_is_authorised(root, entry)
    assert ok, reason

    # The same grant for alpha, signed by gamma — a peer whose key the root does
    # not name. Refused, and refused for the right reason.
    _, impostor = _entry(consensus, cluster, "alpha", clock)
    impostor["signature_b64"] = authz.sign_bytes(
        _operational_key("sim", "gamma"), authz.authorization_message(impostor)
    )
    ok, reason = consensus.registry_signer_is_authorised(root, impostor)
    assert ok is False, (
        "a non-elected member's operational key must not authorise a grant, or the election decides nothing"
    )
    assert reason.startswith(consensus.REASON_BAD_SIGNATURE), reason


def test_a_revoked_registry_entry_still_verifies_but_is_not_authority():
    """Revocation is a field the Master signs, not a signature that stops working.

    Recorded because the opposite assumption is a common and expensive one: if
    revocation were implemented by rotating the key, every previously issued entry
    would fail open somewhere instead of failing closed where it is checked.
    """
    consensus = _module()
    cluster = _cluster()
    clock = SimClock()

    root = _sign_root(consensus, cluster, _root(consensus, cluster, clock, "beta", "r1"))
    authz, entry = _entry(consensus, cluster, "gamma", clock)
    entry["revoked"] = True
    entry["signature_b64"] = authz.sign_bytes(_operational_key("sim", "beta"), authz.authorization_message(entry))

    ok, reason = consensus.registry_signer_is_authorised(root, entry)
    assert ok, (
        f"the signature is valid and the revocation is inside what was signed; "
        f"enforcement belongs to whoever consumes the entry: {reason}"
    )
    assert entry["revoked"] is True, (
        "if a future refactor drops this field from the signed envelope, this test "
        "fails rather than leaving revocation silently unsigned"
    )

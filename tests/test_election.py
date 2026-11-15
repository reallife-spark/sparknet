"""The election: how a conversation between three nodes becomes a trust root.

`shared/sparknet-consensus.py` was already tested to death — what this file
tests is everything around it: the exchange that collects the conversation, the
client that refuses to sign what it did not vote for, the install that flips a
node from peer to master without losing anything, and the scripts that are how
a human actually runs any of it.

Three rules shape the suite:

1. **Real keys, real signatures.** A mocked signature would pass whether or not
   the ceremony works. Keys are generated per-test; nothing reads a real node's.
2. **The crypto lives in one place.** `sparknet-election.py` may not contain
   any — one test proves it by source inspection, another by behaviour.
3. **The cross-process tests run the actual artifacts** — the CLI, the
   exchange, the role scripts — not a reimplementation of them. If the wiring
   is broken, a unit test over the library would still pass.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPO_ROOT / "shared"
ELECTION_SCRIPT = SHARED / "sparknet-election.py"
PEER_SCRIPT = REPO_ROOT / "peer-node" / "scripts" / "sparknet-election-request.sh"
MASTER_SCRIPT = REPO_ROOT / "master-node" / "scripts" / "sparknet-election-approve.sh"
PEER_IDENTITY = REPO_ROOT / "peer-node" / "manifests" / "node-identity.json"
MASTER_IDENTITY = REPO_ROOT / "master-node" / "manifests" / "master-identity.json"
TRUST_DOC = REPO_ROOT / "master-node" / "manifests" / "cluster-trust-root.json"
PY = REPO_ROOT / ".venv" / "bin" / "python"

FIXED = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
MEMBERS = ("alpha", "beta", "gamma")
WINNER = "gamma"


def _clock() -> datetime:
    return FIXED


def _load(name: str, path: Path):
    return load_by_path(name, path)


@pytest.fixture(scope="module")
def election():
    return _load("sparknet_election", ELECTION_SCRIPT)


@pytest.fixture(scope="module")
def consensus():
    return _load("sparknet_consensus", SHARED / "sparknet-consensus.py")


@pytest.fixture(scope="module")
def authz():
    return _load("sparknet_authz", SHARED / "sparknet-authz.py")


@pytest.fixture(scope="module")
def cluster(consensus, authz):
    """Three members with real, per-test Ed25519 cluster keys."""
    members = []
    private: dict[str, str] = {}
    for _index, name in enumerate(MEMBERS):
        priv, pub = authz.generate_keypair()
        private[name] = priv
        members.append(
            {
                "node_id": name,
                "fingerprint": hashlib.sha256(f"election-test-{name}".encode()).hexdigest(),
                "wireguard_pubkey": base64.b64encode(hashlib.sha256(f"wg-{name}".encode()).digest()).decode(),
                "cluster_pubkey": pub,
            }
        )
    # Two halves, deliberately not interchangeable: a bid carries the public
    # half (the exchange would reject a bid naming anything else), and the
    # signer holds the private half. Storing one list for both is how a test
    # ends up filing a private key where a public key belongs.
    operational: dict[str, str] = {}
    operational_private: dict[str, str] = {}
    for name in MEMBERS:
        priv, pub = authz.generate_keypair()
        operational[name] = pub
        operational_private[name] = priv
    return {
        "members": members,
        "private": private,
        "operational": operational,
        "operational_private": operational_private,
    }


@pytest.fixture
def exchange(election, cluster):
    """A fresh exchange per test: state is the point of nearly every test here."""
    return election.ElectionExchange(cluster["members"], clock=_clock)


def _bid(election, cluster, node_id: str, nonce: str = "bid-1", signer: str | None = None):
    """A member's bid, signed with its cluster key unless a test says otherwise."""
    priv = cluster["private"][signer or node_id]
    request = {
        "node_id": node_id,
        "operational_pubkey_b64": cluster["operational"][node_id],
        "nonce": nonce,
        "ts": "2026-10-06T12:00:00+00:00",
    }
    return election.sign_request(request, priv)


def _vote(consensus, cluster, node_id: str, candidate: str, nonce: str = "vote-1"):
    vote = {
        "node_id": node_id,
        "candidate_node_id": candidate,
        "election_id": "cluster-election-1",
        "nonce": nonce,
        "cast_at": "2026-10-06T12:00:00+00:00",
    }
    return consensus.sign_vote(vote, cluster["private"][node_id]).as_dict()


def _all_bids(exchange, election, cluster):
    for name in MEMBERS:
        exchange.submit_request(_bid(election, cluster, name))


def _all_votes(exchange, consensus, cluster, candidate: str = WINNER):
    for name in MEMBERS:
        exchange.submit_vote(_vote(consensus, cluster, name, candidate))


def _formed(
    election,
    consensus,
    cluster,
    candidate: str = WINNER,
    previous_root_id: str = "",
    epoch: int = 0,
    members=None,
    removal_proofs=None,
):
    """Run the whole ceremony in-process; returns (exchange, signed root).

    `previous_root_id` links the formed root to the root it supersedes; a
    re-formation also advances `epoch` (parent + 1). Policy B refuses any
    supersession that does not name the root in force, and a reduced-membership
    child must carry a removal proof per dropped member.
    """
    roster = members if members is not None else cluster["members"]
    names = [m["node_id"] for m in roster]
    exchange = election.ElectionExchange(
        roster,
        clock=_clock,
        previous_root_id=previous_root_id,
        epoch=epoch,
        removal_proofs=removal_proofs,
    )
    for name in names:
        exchange.submit_request(_bid(election, cluster, name))
    for name in names:
        exchange.submit_vote(_vote(consensus, cluster, name, candidate))
    root = exchange.status()["root"]
    for name in names:
        exchange.submit_signature(name, consensus.sign_root(root, name, cluster["private"][name])[name])
    status = exchange.status()
    assert status["state"] == "formed"
    return exchange, status["root"]


def _attested(consensus, cluster, removed: str, parent_root_id: str, survivors, nonce="rp-1"):
    """A removal proof signed by every survivor, the F2 evidence for a drop."""
    proof = {
        "removed_node_id": removed,
        "parent_root_id": parent_root_id,
        "kind": "attested",
        "nonce": nonce,
        "ts": "2026-10-06T12:00:00+00:00",
    }
    for name in survivors:
        proof = consensus.sign_removal_proof(proof, name, cluster["private"][name])
    return proof


def _identity(node_id: str, path: Path) -> Path:
    """A live copy of the shipped peer identity, initialised to a real node."""
    document = json.loads(PEER_IDENTITY.read_text())
    document["node_id"] = node_id
    path.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n")
    return path


def _cluster_key_dir(tmp_path: Path, name: str, cluster) -> Path:
    key_dir = tmp_path / f"adopt-keys-{name}"
    key_dir.mkdir(exist_ok=True)
    private = key_dir / "cluster.ed25519"
    private.write_text(cluster["private"][name] + "\n")
    private.chmod(0o600)
    return key_dir


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _raise_reason(pytest, exc_info, reason: str) -> None:
    assert exc_info.value.reason == reason, (
        f"expected refusal {reason!r}, got {exc_info.value.reason!r}: {exc_info.value.detail}"
    )


# --- the exchange: state machine and refusals ---------------------------------


def test_nothing_forms_before_three_members_have_voted(exchange, election, cluster):
    exchange.submit_request(_bid(election, cluster, "alpha"))
    status = exchange.status()
    assert status["state"] == "collecting" and status["root"] is None


def test_a_bid_from_a_non_member_is_refused(exchange, election, cluster):
    # A stranger's bid wearing a member's signature is still a stranger's bid:
    # membership is checked before the signature, never after.
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_request({**_bid(election, cluster, "alpha"), "node_id": "stranger"})
    _raise_reason(pytest, exc, "signer_not_a_member")


def test_a_bid_signed_by_the_wrong_key_is_refused(exchange, election, cluster):
    # Right node id, right shape — signed by another member's cluster key.
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_request(_bid(election, cluster, "alpha", signer="beta"))
    _raise_reason(pytest, exc, "bad_signature")


def test_re_filing_the_same_bid_is_idempotent_but_a_different_one_is_refused(exchange, election, cluster):
    bid = _bid(election, cluster, "alpha")
    exchange.submit_request(bid)
    again = exchange.submit_request(json.loads(json.dumps(bid)))
    assert again["ok"] is True, "identical re-file must be idempotent"
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_request(_bid(election, cluster, "alpha", nonce="bid-2"))
    _raise_reason(pytest, exc, "bid_already_filed")


def test_a_vote_from_another_election_is_refused(exchange, election, consensus, cluster):
    vote = _vote(consensus, cluster, "alpha", WINNER)
    vote["election_id"] = "old-election"
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_vote(vote)
    _raise_reason(pytest, exc, "wrong_election_id")


def test_equivocation_is_refused_but_the_same_choice_is_idempotent(exchange, election, consensus, cluster):
    exchange.submit_vote(_vote(consensus, cluster, "alpha", WINNER, nonce="v1"))
    exchange.submit_vote(_vote(consensus, cluster, "alpha", WINNER, nonce="v2"))
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_vote(_vote(consensus, cluster, "alpha", "beta", nonce="v3"))
    _raise_reason(pytest, exc, "already_signed")


def test_a_forged_vote_never_enters_the_tally(exchange, election, consensus, cluster):
    vote = _vote(consensus, cluster, "alpha", WINNER)
    vote["signature_b64"] = base64.b64encode(b"not a signature").decode()
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_vote(vote)
    _raise_reason(pytest, exc, "bad_signature")
    assert exchange.status()["votes"] == []


def test_two_votes_leave_the_conversation_incomplete(exchange, election, consensus, cluster):
    for name in ("alpha", "beta"):
        exchange.submit_request(_bid(election, cluster, name))
        exchange.submit_vote(_vote(consensus, cluster, name, name))
    status = exchange.status()
    assert status["root"] is None, "two votes are not a partial root, they are none"
    assert status["state"] == "collecting"


def test_a_split_vote_forms_nothing_even_with_every_bid_in(exchange, election, consensus, cluster):
    """Three votes for three candidates: unanimity failed, and the state says so.

    `no_agreement` rather than `awaiting_operational_key`, because the second
    would tell a reader that filing a bid could still rescue this election. It
    cannot — the tally already ran and nobody agreed.
    """
    _all_bids(exchange, election, cluster)
    for name in MEMBERS:
        exchange.submit_vote(_vote(consensus, cluster, name, name))
    status = exchange.status()
    assert status["root"] is None
    assert status["state"] == "no_agreement"


def test_a_tally_that_agreed_but_has_no_bid_waits_for_the_operational_key(exchange, election, consensus, cluster):
    # Votes can arrive before the winner has bid; the root waits for the key.
    for name in MEMBERS:
        if name != WINNER:
            exchange.submit_request(_bid(election, cluster, name))
    _all_votes(exchange, consensus, cluster)
    status = exchange.status()
    assert status["state"] == "awaiting_operational_key"
    assert status["root"] is None, "no root before the winner publishes its key"
    exchange.submit_request(_bid(election, cluster, WINNER))
    status = exchange.status()
    assert status["state"] == "awaiting_signatures"
    assert status["root"]["master_node_id"] == WINNER
    assert status["root"]["master_pubkey"] == cluster["operational"][WINNER]


def test_a_root_forms_only_at_three_signatures(exchange, election, consensus, cluster):
    _all_bids(exchange, election, cluster)
    _all_votes(exchange, consensus, cluster)
    root = exchange.status()["root"]
    for count, name in enumerate(MEMBERS, start=1):
        signature = consensus.sign_root(root, name, cluster["private"][name])[name]
        exchange.submit_signature(name, signature)
        status = exchange.status()
        if count < 3:
            assert status["state"] == "awaiting_signatures", f"{count} signatures must not form a root"
        else:
            assert status["state"] == "formed" and status["root"]["formed_at"]


def test_the_exchange_forms_a_schema_1_3_admission_root(election, consensus, cluster):
    """The exchange can form a 2 -> 3 admission when it is given the parent.

    Without the held root it is just a three-member election that happens to
    name a new member; with it, the seal checks the admission rule before the
    root is reported formed.
    """
    _, parent = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        members=cluster["members"][:2],
    )
    exchange = election.ElectionExchange(
        cluster["members"],
        clock=_clock,
        previous_root_id=consensus.root_id(parent),
        epoch=1,
        held_root=parent,
        admission=True,
    )
    _all_bids(exchange, election, cluster)
    _all_votes(exchange, consensus, cluster, candidate="beta")
    root = exchange.status()["root"]
    for name in MEMBERS:
        exchange.submit_signature(name, consensus.sign_root(root, name, cluster["private"][name])[name])
    status = exchange.status()
    assert status["state"] == "formed"
    assert status["root"]["version"] == "1.3"
    assert consensus.verify_root(status["root"], trust=parent) == (True, consensus.REASON_OK)


def test_the_exchange_refuses_an_admission_that_changes_the_master(election, consensus, cluster):
    """The seal, not only the later accept, refuses a combined join + takeover."""
    _, parent = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        members=cluster["members"][:2],
    )
    exchange = election.ElectionExchange(
        cluster["members"],
        clock=_clock,
        previous_root_id=consensus.root_id(parent),
        epoch=1,
        held_root=parent,
        admission=True,
    )
    _all_bids(exchange, election, cluster)
    _all_votes(exchange, consensus, cluster, candidate="gamma")
    root = exchange.status()["root"]
    signatures = {name: consensus.sign_root(root, name, cluster["private"][name])[name] for name in ("alpha", "beta")}
    for name, signature in signatures.items():
        exchange.submit_signature(name, signature)
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_signature(
            "gamma",
            consensus.sign_root(root, "gamma", cluster["private"]["gamma"])["gamma"],
        )
    assert exc.value.reason == election.REASON_ROOT_UNUSABLE
    assert consensus.REASON_ADMISSION_MASTER_CHANGE in exc.value.detail


def test_a_bad_c_signature_is_refused_immediately_not_at_three(exchange, election, consensus, cluster):
    """The regression this test exists for.

    `verify_root` checks missing signers before it checks signature validity, so
    a exchange that validated only through it would accept garbage at signature
    one — "missing signatures" — and discover the lie only after three honest
    members had watched a root form. The exchange must verify each signature
    before storing it.
    """
    _all_bids(exchange, election, cluster)
    _all_votes(exchange, consensus, cluster)
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_signature("alpha", base64.b64encode(b"garbage").decode())
    _raise_reason(pytest, exc, "bad_signature")
    assert exchange.status()["signatures"] == [], "the bad signature must not be stored"


def test_c_signing_before_a_root_exists_is_refused(exchange, election, cluster):
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_signature("alpha", "c2ln")
    _raise_reason(pytest, exc, "no_root_yet")


def test_a_second_different_signature_from_the_same_member_is_refused(exchange, election, consensus, cluster):
    _all_bids(exchange, election, cluster)
    _all_votes(exchange, consensus, cluster)
    root = exchange.status()["root"]
    first = consensus.sign_root(root, "alpha", cluster["private"]["alpha"])["alpha"]
    exchange.submit_signature("alpha", first)
    exchange.submit_signature("alpha", first)  # identical: idempotent
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_signature("alpha", base64.b64encode(b"second").decode())
    _raise_reason(pytest, exc, "already_signed")


def test_a_non_member_cannot_sign_a_root(exchange, election, consensus, cluster):
    _all_bids(exchange, election, cluster)
    _all_votes(exchange, consensus, cluster)
    with pytest.raises(election.ElectionError) as exc:
        exchange.submit_signature("stranger", "c2ln")
    _raise_reason(pytest, exc, "signer_not_a_member")


def test_the_root_names_the_members_and_the_winners_operational_key(election, consensus, cluster):
    formed_exchange, root = _formed(election, consensus, cluster)
    assert root["master_node_id"] == WINNER
    assert root["master_pubkey"] == cluster["operational"][WINNER]
    assert sorted(m["node_id"] for m in root["members"]) == sorted(MEMBERS)
    ok, reason = consensus.verify_root(root)
    assert ok, reason
    # The root the status reports carries the signatures; its id ignores them.
    assert set(root["signatures"]) == set(MEMBERS)
    assert consensus.root_id(root) == formed_exchange.status()["root_id"]


# --- the crypto lives in one place --------------------------------------------


def test_the_election_module_contains_no_crypto_of_its_own(election):
    """A second Ed25519 inside the file that decides who may hold the key
    would be the worst possible place for one.

    Checked by source, because the absence of an import cannot be observed by
    behaviour — a wrapper that happens not to be called today would pass.
    """
    source = ELECTION_SCRIPT.read_text()
    for forbidden in (
        "from cryptography",
        "import hashlib",
        "private_bytes",
        "public_bytes",
        "b64decode",
    ):
        # Textual, then symbolical: prose may name the algorithm this file
        # decides who wields, but no *identifier* in it may refer to it.
        assert forbidden not in source, (
            f"sparknet-election.py contains {forbidden!r}: it must delegate all "
            f"cryptographic work to sparknet-authz and sparknet-consensus"
        )
    _tree = ast.parse(source)
    for _node in ast.walk(_tree):
        if isinstance(_node, ast.Name):
            assert "Ed25519" not in _node.id, (
                f"sparknet-election.py refers to Ed25519 as a symbol at line "
                f"{_node.lineno}; every primitive comes from authz and consensus"
            )
        if isinstance(_node, (ast.Import, ast.ImportFrom)):
            _module = _node.module if isinstance(_node, ast.ImportFrom) else _node.names[0].name
            assert _module.split(".")[0] not in {"hashlib", "cryptography", "nacl"}, (
                f"sparknet-election.py imports {_module}; the crypto must come from authz"
            )
    # No primitive is re-exported under its own name either.
    for name in ("sign_bytes", "verify_signature", "public_key_from_b64", "private_key_from_b64"):
        assert not hasattr(election, name), f"sparknet-election.py defines {name} itself instead of calling authz"


def test_every_signature_check_runs_through_the_shared_implementations(
    exchange, election, consensus, cluster, monkeypatch
):
    """Behavioural half of the rule: bids are verified by authz, root bytes
    come from consensus — proven by counting the calls, not by reading them."""
    authz_calls: list[int] = []
    real_authz_loader = election.load_authz

    def spy_authz(shared_dir=None):
        authz_calls.append(1)
        return real_authz_loader(shared_dir)

    monkeypatch.setattr(election, "load_authz", spy_authz)
    exchange.submit_request(_bid(election, cluster, "alpha"))
    assert authz_calls, "the bid was verified without going through sparknet-authz"

    for name in MEMBERS:
        if name not in exchange.status()["bids"]:
            exchange.submit_request(_bid(election, cluster, name))
    assert exchange.status()["root"] is None, "bids alone must not form a root"
    for name in MEMBERS:
        exchange.submit_vote(_vote(consensus, cluster, name, WINNER))
    assert exchange.status()["root"] is not None, "the tally agreed; the root must exist"

    root_calls: list[int] = []
    real_root_bytes = consensus.root_bytes

    def spy_root_bytes(root):
        root_calls.append(1)
        return real_root_bytes(root)

    monkeypatch.setattr(consensus, "root_bytes", spy_root_bytes)
    root = exchange.status()["root"]
    # The signature is built here, outside the exchange — so any root_bytes
    # call counted after this point is the exchange's own verification, not
    # this test's construction of the thing being verified.
    signature = consensus.sign_root(root, "alpha", cluster["private"]["alpha"])["alpha"]
    root_calls.clear()
    exchange.submit_signature("alpha", signature)
    assert root_calls, "the exchange verified a signature over bytes it built itself"
    # And the consensus in use is the one module, not a private copy.
    assert exchange.consensus is sys.modules["sparknet_consensus"]


# --- the client: a member refuses to sign what it did not vote for ------------


@pytest.fixture
def keydirs(tmp_path, cluster):
    """One key directory per member holding that member's real cluster key."""
    dirs = {}
    for name in MEMBERS:
        key_dir = tmp_path / f"keys-{name}"
        key_dir.mkdir()
        private = key_dir / "cluster.ed25519"
        private.write_text(cluster["private"][name] + "\n")
        private.chmod(0o600)
        dirs[name] = key_dir
    return dirs


@pytest.fixture
def live(election, cluster, tmp_path):
    """A real exchange, on a real loopback socket, for the client tests."""
    members_path = tmp_path / "cluster-members.json"
    members_path.write_text(json.dumps({"schema_version": "1.0", "members": cluster["members"]}, indent=2))
    port = _free_port()
    ready = threading.Event()
    # Daemon thread: the server stops when the test process does. Deliberate —
    # serve() blocks, and a per-test shutdown handshake would test the handshake.
    threading.Thread(
        target=election.serve,
        kwargs={
            "members_path": members_path,
            "bind": "127.0.0.1",
            "port": port,
            "ready": ready.set,
        },
        daemon=True,
    ).start()
    assert ready.wait(5), "the exchange never came up"
    return f"http://127.0.0.1:{port}"


def _client_ceremony(election, consensus, cluster, keydirs, base: str, candidate: str = WINNER):
    for name in MEMBERS:
        election.cast_request(base, name, keydirs[name])
    for name in MEMBERS:
        election.cast_vote(base, name, candidate, election.DEFAULT_ELECTION_ID, keydirs[name])
    status = election.status_of(base)
    assert status["root"] is not None, "three bids and three votes must produce a root"
    return status


def test_a_member_refuses_to_co_sign_a_root_it_did_not_vote_for(election, consensus, cluster, keydirs, live):
    _client_ceremony(election, consensus, cluster, keydirs, live)
    with pytest.raises(election.ElectionError) as exc:
        election.sign_root(
            live,
            "alpha",
            candidate="beta",  # alpha voted for gamma
            election_id=election.DEFAULT_ELECTION_ID,
            key_dir=keydirs["alpha"],
        )
    _raise_reason(pytest, exc, "unexpected_master")
    status = election.status_of(live)
    assert status["signatures"] == [], "a refusal must not leave a signature behind"


def test_the_honest_client_path_co_signs_and_forms(election, consensus, cluster, keydirs, live):
    _client_ceremony(election, consensus, cluster, keydirs, live)
    for index, name in enumerate(MEMBERS, start=1):
        status = election.sign_root(
            live,
            name,
            candidate=WINNER,
            election_id=election.DEFAULT_ELECTION_ID,
            key_dir=keydirs[name],
        )
        assert len(status["signatures"]) == index, "one more signature per member"
        # Re-running the same sign must not add a second signature for anyone.
        again = election.sign_root(
            live,
            name,
            candidate=WINNER,
            election_id=election.DEFAULT_ELECTION_ID,
            key_dir=keydirs[name],
        )
        assert again["signatures"] == status["signatures"]
    final = election.status_of(live)
    assert final["state"] == "formed"
    ok, reason = consensus.verify_root(final["root"])
    assert ok, reason


def test_the_client_rejects_an_unreachable_exchange_as_unreachable(election, tmp_path):
    with pytest.raises(election.ElectionError) as exc:
        election.status_of(f"http://127.0.0.1:{_free_port()}", timeout=0.5)
    _raise_reason(pytest, exc, "exchange_unreachable")


# --- install: the flip, its refusals, and what must not move -------------------


def test_accept_flips_exactly_the_permitted_fields(election, consensus, cluster, tmp_path):
    _, root = _formed(election, consensus, cluster)
    identity_path = _identity(WINNER, tmp_path / "identity.json")
    before = json.loads(identity_path.read_text())
    out = election.accept_root(root, identity_path)
    assert out["accepted"] is True and out["role"] == "master"
    after = json.loads(identity_path.read_text())
    assert after["role"] == "master"
    assert after["operational_key"]["held"] is True
    assert after["operational_key"]["root_id"] == out["root_id"]
    assert after["trust_root"] == {
        "root_id": out["root_id"],
        "master_node_id": WINNER,
        "master_pubkey": root["master_pubkey"],
        "formed_at": root["formed_at"],
    }
    assert out["root_id"] in after["role_note"], "the flip must record which root made it"
    allowed = {"role", "role_note", "operational_key", "trust_root"}
    for key, value in before.items():
        if key in allowed:
            continue
        assert after.get(key) == value, f"field {key!r} changed under accept"
    assert set(after) - set(before) <= allowed, "accept invented a field"
    assert not identity_path.with_name(identity_path.name + ".tmp").exists()


def test_accept_writes_nothing_but_the_identity_and_the_root_document(election, consensus, cluster, tmp_path):
    _, root = _formed(election, consensus, cluster)
    identity_path = _identity(WINNER, tmp_path / "identity.json")
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    (key_dir / "cluster.ed25519").write_text(cluster["private"][WINNER] + "\n")
    (key_dir / "operational.ed25519").write_text(cluster["operational_private"][WINNER] + "\n")

    def tree_hashes() -> dict[str, str]:
        return {
            str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(tmp_path.rglob("*"))
            if path.is_file() and path != identity_path
        }

    before = tree_hashes()
    election.accept_root(root, identity_path, root_out=tmp_path / "trust-root.json")
    after = tree_hashes()
    changed = {name for name in before if before[name] != after.get(name)}
    assert not changed, f"accept touched files it has no business touching: {changed}"
    written = json.loads((tmp_path / "trust-root.json").read_text())
    assert written["root"]["master_node_id"] == WINNER
    assert set(written["root"]["signatures"]) == set(MEMBERS)
    assert written["root_id"] == election.load_consensus().root_id(root)


def test_the_two_members_that_stay_peers_have_their_files_left_alone(election, consensus, cluster, tmp_path):
    _, root = _formed(election, consensus, cluster)
    for name in ("alpha", "beta"):
        identity_path = _identity(name, tmp_path / f"identity-{name}.json")
        before = identity_path.read_bytes()
        out = election.accept_root(root, identity_path)
        assert out["accepted"] is False and out["reason"] == "not_elected"
        assert out["role"] == "peer"
        assert identity_path.read_bytes() == before, f"{name} did not win; accept must not have touched its identity"


def test_a_new_member_adopts_the_admission_root_without_becoming_master(election, consensus, cluster, tmp_path):
    """A peer named by an admission root must persist it, but stay a peer.

    The election-loser path deliberately writes nothing. Admission is different:
    the new member has no older root to hold, and the existing peer must move
    from the pair root to the trio root or it cannot verify what the cluster
    signs next. This is the member-adoption half of the join ceremony.
    """
    parent_members = cluster["members"][:2]
    _, parent = _formed(election, consensus, cluster, candidate="beta", members=parent_members)
    _, child = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        previous_root_id=consensus.root_id(parent),
        epoch=1,
    )
    identity_path = _identity("gamma", tmp_path / "identity.json")
    before = json.loads(identity_path.read_text())
    root_out = tmp_path / "trust-root.json"

    out = election.accept_root(
        child,
        identity_path,
        trust_root=parent,
        root_out=root_out,
        install_as_member=True,
        expected_members=cluster["members"],
        key_dir=_cluster_key_dir(tmp_path, "gamma", cluster),
    )
    assert out["accepted"] is True
    assert out["adopted_as_member"] is True
    after = json.loads(identity_path.read_text())
    assert after["role"] == "peer", "admission must not hand the new member the operational role"
    assert after.get("operational_key") == before.get("operational_key")
    assert after["trust_root"]["root_id"] == consensus.root_id(child)
    assert json.loads(root_out.read_text())["root_id"] == consensus.root_id(child)


def _pair_and_admission(election, consensus, cluster):
    _, parent = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        members=cluster["members"][:2],
    )
    _, child = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        previous_root_id=consensus.root_id(parent),
        epoch=1,
    )
    return parent, child


def test_member_adoption_refuses_a_substituted_new_member(election, consensus, cluster, authz, tmp_path):
    """The out-of-band roster must bind the new member, not just the parent.

    A lying exchange can keep the same parent and Master while swapping the new
    member for a fresh-key phantom. The expected roster is the only source that
    says which new member the pair actually admitted.
    """
    _, parent = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        members=cluster["members"][:2],
    )
    delta_private, delta_public = authz.generate_keypair()
    delta = {
        "node_id": "delta",
        "fingerprint": hashlib.sha256(b"delta-fingerprint").hexdigest(),
        "wireguard_pubkey": base64.b64encode(hashlib.sha256(b"delta-wg").digest()).decode(),
        "cluster_pubkey": delta_public,
    }
    child = {
        "version": "1.3",
        "nonce": "phantom-child",
        "formed_at": "2026-10-06T12:00:00+00:00",
        "members": [*cluster["members"][:2], delta],
        "master_node_id": "beta",
        "master_pubkey": cluster["operational"]["beta"],
        "previous_root_id": consensus.root_id(parent),
        "epoch": 1,
    }
    child = consensus.attach_root_signatures(
        child,
        {
            "alpha": cluster["private"]["alpha"],
            "beta": cluster["private"]["beta"],
            "delta": delta_private,
        },
    )
    identity_path = _identity("delta", tmp_path / "identity.json")
    delta_dir = tmp_path / "keys-delta"
    delta_dir.mkdir()
    (delta_dir / "cluster.ed25519").write_text(delta_private + "\n")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(
            child,
            identity_path,
            trust_root=parent,
            install_as_member=True,
            expected_members=cluster["members"],
            key_dir=delta_dir,
        )
    _raise_reason(pytest, exc, "root_unusable")
    assert "out-of-band roster" in exc.value.detail

    # The Master path is not exempt: a child chained to the parent with an
    # unbound new member is refused before an identity flips.
    master_identity = _identity("beta", tmp_path / "beta-identity.json")
    with pytest.raises(election.ElectionError) as master_exc:
        election.accept_root(
            child,
            master_identity,
            trust_root=parent,
            key_dir=_cluster_key_dir(tmp_path, "beta", cluster),
        )
    _raise_reason(pytest, master_exc, "root_unusable")
    assert "out-of-band roster" in master_exc.value.detail


def test_the_member_client_checks_the_roster_before_signing(election, consensus, cluster, authz, keydirs, tmp_path):
    """The member process refuses a substituted roster before it co-signs.

    This is the exchange-substitution attack at the client seam: the exchange
    roster says delta, the out-of-band roster says gamma. Alpha must not add its
    signature to the phantom root.
    """
    beta_private, beta_public = authz.generate_keypair()
    (keydirs["beta"] / "operational.ed25519").write_text(beta_private + "\n")
    (keydirs["beta"] / "operational.pub.b64").write_text(beta_public + "\n")
    delta_private, delta_public = authz.generate_keypair()
    delta_dir = tmp_path / "keys-delta"
    delta_dir.mkdir()
    (delta_dir / "cluster.ed25519").write_text(delta_private + "\n")
    (delta_dir / "cluster.ed25519").chmod(0o600)

    parent_members = cluster["members"][:2]
    parent = consensus.attach_root_signatures(
        {
            "version": "1.2",
            "nonce": "pair-parent",
            "formed_at": "2026-10-06T12:00:00+00:00",
            "members": parent_members,
            "master_node_id": "beta",
            "master_pubkey": beta_public,
            "previous_root_id": "",
            "epoch": 0,
        },
        {"alpha": cluster["private"]["alpha"], "beta": cluster["private"]["beta"]},
    )
    parent_doc = _write_root_doc(tmp_path / "parent.json", parent)
    delta = {
        "node_id": "delta",
        "fingerprint": hashlib.sha256(b"delta-fingerprint").hexdigest(),
        "wireguard_pubkey": base64.b64encode(hashlib.sha256(b"delta-wg").digest()).decode(),
        "cluster_pubkey": delta_public,
    }
    malicious_members = [*parent_members, delta]
    malicious_path = tmp_path / "malicious-members.json"
    malicious_path.write_text(json.dumps({"schema_version": "1.0", "members": malicious_members}, indent=2))

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    ready = threading.Event()
    threading.Thread(
        target=election.serve,
        kwargs={
            "members_path": malicious_path,
            "bind": "127.0.0.1",
            "port": port,
            "trust_root": parent_doc,
            "admission": True,
            "ready": ready.set,
        },
        daemon=True,
    ).start()
    assert ready.wait(5), "the exchange never came up"

    election.cast_request(base, "beta", keydirs["beta"])
    election.cast_vote(base, "beta", "beta", election.DEFAULT_ELECTION_ID, keydirs["beta"])
    election.cast_request(base, "delta", delta_dir)
    election.cast_vote(base, "delta", "beta", election.DEFAULT_ELECTION_ID, delta_dir)

    identity_path = _identity("alpha", tmp_path / "alpha-identity.json")
    with pytest.raises(election.ElectionError) as exc:
        election.run_member(
            base,
            "alpha",
            "beta",
            keydirs["alpha"],
            identity_path=identity_path,
            trust_root=parent,
            install_as_member=True,
            expected_members=cluster["members"],
            admission=True,
            root_out=tmp_path / "alpha-root.json",
        )
    _raise_reason(pytest, exc, "root_unusable")
    assert "out-of-band roster" in exc.value.detail
    assert election.status_of(base)["signatures"] == [], "alpha signed a root with an unbound roster"

    # Omitting --admission/--members must not bypass the root-shape check.
    with pytest.raises(election.ElectionError) as unflagged:
        election.run_member(
            base,
            "alpha",
            "beta",
            keydirs["alpha"],
            identity_path=identity_path,
            trust_root=parent,
            install_as_member=True,
        )
    _raise_reason(pytest, unflagged, "malformed")
    assert "out-of-band roster" in unflagged.value.detail
    assert election.status_of(base)["signatures"] == [], "unflagged client signed a substituted root"


def test_member_adoption_requires_a_verified_parent(election, consensus, cluster, tmp_path):
    """A new member must not adopt a 1.3 root without the parent that authorises the join."""
    _, child = _pair_and_admission(election, consensus, cluster)
    identity_path = _identity("gamma", tmp_path / "identity.json")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(
            child,
            identity_path,
            install_as_member=True,
            expected_members=cluster["members"],
            key_dir=_cluster_key_dir(tmp_path, "gamma", cluster),
        )
    _raise_reason(pytest, exc, "root_unusable")
    assert "parent root" in exc.value.detail


def test_member_adoption_refuses_a_forged_parent(election, consensus, cluster, tmp_path):
    """A parent with no valid signatures is not evidence of a prior root."""
    parent, child = _pair_and_admission(election, consensus, cluster)
    forged = {key: value for key, value in parent.items() if key != "signatures"}
    identity_path = _identity("gamma", tmp_path / "identity.json")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(
            child,
            identity_path,
            trust_root=forged,
            install_as_member=True,
            expected_members=cluster["members"],
            key_dir=_cluster_key_dir(tmp_path, "gamma", cluster),
        )
    _raise_reason(pytest, exc, "root_unusable")
    assert "parent root" in exc.value.detail


def test_member_adoption_refuses_a_sibling_parent(election, consensus, cluster, tmp_path):
    """An identity already holding T may not adopt a child chained to a different P."""
    parent, child = _pair_and_admission(election, consensus, cluster)
    other = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        members=cluster["members"][:2],
    )[1]
    assert consensus.root_id(other) != consensus.root_id(parent)
    identity_path = _identity("alpha", tmp_path / "identity.json")
    identity = json.loads(identity_path.read_text())
    identity["trust_root"] = {"root_id": consensus.root_id(other)}
    identity_path.write_text(json.dumps(identity, indent=2) + "\n")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(
            child,
            identity_path,
            trust_root=parent,
            install_as_member=True,
            expected_members=cluster["members"],
            key_dir=_cluster_key_dir(tmp_path, "alpha", cluster),
        )
    _raise_reason(pytest, exc, "unchained_root")


def test_member_adoption_checks_the_local_cluster_key(election, consensus, cluster, tmp_path):
    """A node may not adopt a seat whose cluster key it does not hold."""
    parent, child = _pair_and_admission(election, consensus, cluster)
    identity_path = _identity("gamma", tmp_path / "identity.json")
    key_dir = tmp_path / "keys-gamma"
    key_dir.mkdir()
    (key_dir / "cluster.ed25519").write_text(cluster["private"]["alpha"] + "\n")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(
            child,
            identity_path,
            trust_root=parent,
            key_dir=key_dir,
            install_as_member=True,
            expected_members=cluster["members"],
        )
    _raise_reason(pytest, exc, "root_unusable")
    assert "different cluster key" in exc.value.detail


def test_member_adoption_accepts_a_chained_3_to_3_reformation(election, consensus, cluster, tmp_path):
    """A peer can adopt a lawful 3 -> 3 re-formation, not only a 2 -> 3 join.

    The chained-root verifier decides whether the membership change is lawful;
    `--as-member` only decides that this non-master node persists `trust_root`
    instead of taking the operational role.
    """
    _, parent = _formed(election, consensus, cluster, candidate="alpha")
    _, child = _formed(
        election,
        consensus,
        cluster,
        candidate="alpha",
        previous_root_id=consensus.root_id(parent),
        epoch=1,
    )
    identity_path = _identity("beta", tmp_path / "identity.json")
    out = election.accept_root(
        child,
        identity_path,
        trust_root=parent,
        install_as_member=True,
        expected_members=cluster["members"],
        key_dir=_cluster_key_dir(tmp_path, "beta", cluster),
    )
    assert out["accepted"] is True and out["adopted_as_member"] is True
    after = json.loads(identity_path.read_text())
    assert after["role"] == "peer"
    assert after["trust_root"]["root_id"] == consensus.root_id(child)


def test_member_adoption_accepts_changed_identity_fields_in_a_3_to_3(election, consensus, cluster, tmp_path):
    """The live key-rotation shape: same nodes, new WG/fingerprint fields."""
    _, parent = _formed(election, consensus, cluster, candidate="alpha")
    reformed = [dict(member) for member in cluster["members"]]
    for member in reformed:
        member["fingerprint"] = hashlib.sha256(f"rotated-fp-{member['node_id']}".encode()).hexdigest()
        member["wireguard_pubkey"] = base64.b64encode(
            hashlib.sha256(f"rotated-wg-{member['node_id']}".encode()).digest()
        ).decode()
    _, child = _formed(
        election,
        consensus,
        cluster,
        candidate="alpha",
        previous_root_id=consensus.root_id(parent),
        epoch=1,
        members=reformed,
    )
    identity_path = _identity("beta", tmp_path / "identity.json")
    out = election.accept_root(
        child,
        identity_path,
        trust_root=parent,
        install_as_member=True,
        expected_members=reformed,
        key_dir=_cluster_key_dir(tmp_path, "beta", cluster),
    )
    assert out["accepted"] is True
    assert json.loads(identity_path.read_text())["trust_root"]["root_id"] == consensus.root_id(child)


def test_member_adoption_refuses_a_master_identity(election, consensus, cluster, tmp_path):
    """A member adoption must not leave a master role or held key behind."""
    parent, child = _pair_and_admission(election, consensus, cluster)
    identity_path = _identity("gamma", tmp_path / "identity.json")
    identity = json.loads(identity_path.read_text())
    identity["role"] = "master"
    identity["operational_key"] = {"held": True}
    identity_path.write_text(json.dumps(identity, indent=2) + "\n")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(
            child,
            identity_path,
            trust_root=parent,
            install_as_member=True,
            expected_members=cluster["members"],
        )
    _raise_reason(pytest, exc, "root_unusable")


def test_the_exchange_refuses_an_unverified_parent(election, consensus, cluster):
    """The exchange does not build on a signature-less parent."""
    _, parent = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        members=cluster["members"][:2],
    )
    forged = {key: value for key, value in parent.items() if key != "signatures"}
    with pytest.raises(election.ElectionError) as exc:
        election.ElectionExchange(
            cluster["members"],
            clock=_clock,
            held_root=forged,
            admission=True,
        )
    _raise_reason(pytest, exc, "root_unusable")


def test_the_exchange_requires_the_admission_flag(election, consensus, cluster):
    """A 2 -> 3 roster without --admission is an accidental join, not a re-formation."""
    _, parent = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        members=cluster["members"][:2],
    )
    with pytest.raises(election.ElectionError) as exc:
        election.ElectionExchange(
            cluster["members"],
            clock=_clock,
            held_root=parent,
            previous_root_id=consensus.root_id(parent),
            epoch=1,
        )
    _raise_reason(pytest, exc, "admission_not_allowed")


def test_accept_refuses_a_root_that_does_not_verify(election, consensus, cluster, tmp_path):
    _, root = _formed(election, consensus, cluster)
    identity_path = _identity(WINNER, tmp_path / "identity.json")
    unsigned = {key: value for key, value in root.items() if key != "signatures"}
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(unsigned, identity_path)
    _raise_reason(pytest, exc, "root_unusable")

    tampered = json.loads(json.dumps(root))
    tampered["signatures"]["alpha"] = base64.b64encode(b"garbage").decode()
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(tampered, identity_path)
    _raise_reason(pytest, exc, "root_unusable")


def test_accept_refuses_a_root_the_identity_is_not_named_by(election, consensus, cluster, tmp_path):
    _, root = _formed(election, consensus, cluster)
    identity_path = _identity("stranger", tmp_path / "identity.json")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(root, identity_path)
    _raise_reason(pytest, exc, "signer_not_a_member")


def test_re_presenting_the_root_already_in_force_is_refused(election, consensus, cluster, tmp_path):
    """`verify_root(trust=held)` with the held nonce: root_replayed, wrapped.

    This is the contract's "re-presenting the root already in force is refused"
    — and why `member` only passes a held root when the nonce differs, so an
    honest re-run of the ceremony stays idempotent while a replay is caught.
    """
    _, root = _formed(election, consensus, cluster)
    identity_path = _identity(WINNER, tmp_path / "identity.json")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(root, identity_path, trust_root=root)
    _raise_reason(pytest, exc, "root_unusable")
    assert "root_replayed" in exc.value.detail


def test_a_new_nonce_supersedes_the_held_root(election, consensus, cluster, tmp_path):
    """Re-formation: a later, chained root replaces the held one."""
    _, first = _formed(election, consensus, cluster, candidate="alpha")
    _, second = _formed(
        election,
        consensus,
        cluster,
        candidate=WINNER,
        previous_root_id=consensus.root_id(first),
        epoch=1,
    )
    assert first["nonce"] != second["nonce"]
    assert second["previous_root_id"] == consensus.root_id(first), (
        "the re-formation root must name the held root to be its successor"
    )
    identity_path = _identity(WINNER, tmp_path / "identity.json")
    out = election.accept_root(second, identity_path, trust_root=first)
    assert out["accepted"] and out["root_id"] != consensus.root_id(first)
    after = json.loads(identity_path.read_text())
    assert after["trust_root"]["root_id"] == consensus.root_id(second)


def test_the_exchange_can_form_a_role_swap_re_formation(election, consensus, cluster):
    """A role inversion re-describes the same node ids with new fingerprints.

    This is the Step 88 path: the members keep their node ids and cluster keys,
    but their role, overlay address, WireGuard key and node identity key change.
    The exchange must form a chained root over the new member records, and the
    old root must remain the parent.
    """
    _, first = _formed(election, consensus, cluster, candidate="alpha")
    reformed = [dict(member) for member in cluster["members"]]
    for member in reformed:
        member["fingerprint"] = hashlib.sha256(f"exchange-role-swap-fp-{member['node_id']}".encode()).hexdigest()
        member["wireguard_pubkey"] = base64.b64encode(
            hashlib.sha256(f"exchange-role-swap-wg-{member['node_id']}".encode()).digest()
        ).decode()

    _, second = _formed(
        election,
        consensus,
        cluster,
        candidate=WINNER,
        previous_root_id=consensus.root_id(first),
        epoch=1,
        members=reformed,
    )
    assert second["previous_root_id"] == consensus.root_id(first)
    assert second["epoch"] == 1
    assert {m["node_id"] for m in second["members"]} == {m["node_id"] for m in first["members"]}
    assert second["members"][0]["fingerprint"] != first["members"][0]["fingerprint"]
    assert consensus.verify_root(second, trust=first) == (True, consensus.REASON_OK)
    assert consensus.verify_chain([second, first]) == (True, consensus.REASON_OK)


def test_an_unchained_new_root_is_refused_in_accept(election, consensus, cluster, tmp_path):
    """The trust flip refuses a well-signed root with no lineage to the held one."""
    _, first = _formed(election, consensus, cluster, candidate="alpha")
    _, stranger = _formed(election, consensus, cluster, candidate=WINNER)
    identity_path = _identity(WINNER, tmp_path / "identity.json")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(stranger, identity_path, trust_root=first)
    assert consensus.REASON_UNCHAINED in exc.value.detail, exc.value.detail


def test_a_reduced_membership_re_formation_through_the_exchange(election, consensus, cluster, tmp_path):
    """F2: 3 -> 2 driven through the exchange, then accepted.

    A real re-formation, not a hand-built root: the exchange takes the reduced
    roster, the survivors co-sign, the dropped member is evidenced, and the
    accept path installs the reduced root while leaving the departing member's
    files alone.
    """
    _, genesis = _formed(election, consensus, cluster, candidate="beta")
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    proof = _attested(consensus, cluster, "gamma", consensus.root_id(genesis), ["alpha", "beta"])
    _, reformed = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        previous_root_id=consensus.root_id(genesis),
        epoch=1,
        members=survivors,
        removal_proofs=[proof],
    )
    assert reformed["previous_root_id"] == consensus.root_id(genesis)
    assert reformed["epoch"] == 1
    assert {m["node_id"] for m in reformed["members"]} == {"alpha", "beta"}
    assert set(reformed["signatures"]) == {"alpha", "beta"}, "only the survivors may co-sign a reduced root"
    assert consensus.verify_root(reformed, trust=genesis) == (True, consensus.REASON_OK)
    assert consensus.verify_chain([reformed, genesis]) == (True, consensus.REASON_OK)

    identity_path = _identity("beta", tmp_path / "identity.json")
    out = election.accept_root(reformed, identity_path, trust_root=genesis)
    assert out["accepted"] and out["root_id"] == consensus.root_id(reformed)
    after = json.loads(identity_path.read_text())
    assert after["trust_root"]["root_id"] == consensus.root_id(reformed)


def test_a_reduced_root_without_evidence_is_refused_in_accept(election, consensus, cluster, tmp_path):
    """The accept path carries the same removal-proof requirement as
    `verify_root`: a reduced root with no evidence never flips an identity."""
    _, genesis = _formed(election, consensus, cluster, candidate="beta")
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    _, reformed = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        previous_root_id=consensus.root_id(genesis),
        epoch=1,
        members=survivors,
        removal_proofs=None,
    )
    identity_path = _identity("beta", tmp_path / "identity.json")
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(reformed, identity_path, trust_root=genesis)
    assert consensus.REASON_MISSING_REMOVAL_PROOF in exc.value.detail, exc.value.detail
    after = json.loads(identity_path.read_text())
    assert "trust_root" not in after or after.get("trust_root") is None


# --- F3: live cross-node sync, a real second process --------------------------


def _write_root_doc(path: Path, root: dict) -> Path:
    path.write_text(json.dumps({"root": root}, indent=2, sort_keys=True))
    return path


def test_the_reformed_root_reaches_the_peer_process_and_is_adopted(election, consensus, cluster, tmp_path):
    """F3: the F2 output is delivered to a real peer process.

    The shipped ``accept`` subcommand runs in its own interpreter and loads its
    own ``shared/sparknet-consensus.py`` from ``--shared-dir``. Handed the
    re-formed root and the parent it descends from, it verifies the chain and
    installs the reduced root as the node's held trust root.
    """
    _, genesis = _formed(election, consensus, cluster, candidate="beta")
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    proof = _attested(consensus, cluster, "gamma", consensus.root_id(genesis), ["alpha", "beta"])
    _, reformed = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        previous_root_id=consensus.root_id(genesis),
        epoch=1,
        members=survivors,
        removal_proofs=[proof],
    )
    genesis_doc = _write_root_doc(tmp_path / "genesis.json", genesis)
    reformed_doc = _write_root_doc(tmp_path / "reformed.json", reformed)
    identity_path = _identity("beta", tmp_path / "identity.json")

    result = _cli(
        [
            "accept",
            "--root",
            str(reformed_doc),
            "--trust",
            str(genesis_doc),
            "--identity",
            str(identity_path),
        ]
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["accepted"] is True
    assert payload["root_id"] == consensus.root_id(reformed)
    after = json.loads(identity_path.read_text())
    assert after["trust_root"]["root_id"] == consensus.root_id(reformed)


def test_the_peer_process_refuses_a_rollback_and_a_stranger_fork(election, consensus, cluster, tmp_path):
    """F3: once the peer holds the re-formed root, its own process refuses both
    a rollback to the parent and a well-signed root with no lineage to it."""
    _, genesis = _formed(election, consensus, cluster, candidate="beta")
    survivors = [m for m in cluster["members"] if m["node_id"] != "gamma"]
    proof = _attested(consensus, cluster, "gamma", consensus.root_id(genesis), ["alpha", "beta"])
    _, reformed = _formed(
        election,
        consensus,
        cluster,
        candidate="beta",
        previous_root_id=consensus.root_id(genesis),
        epoch=1,
        members=survivors,
        removal_proofs=[proof],
    )
    _, stranger = _formed(election, consensus, cluster, candidate="beta")
    genesis_doc = _write_root_doc(tmp_path / "genesis.json", genesis)
    reformed_doc = _write_root_doc(tmp_path / "reformed.json", reformed)
    stranger_doc = _write_root_doc(tmp_path / "stranger.json", stranger)
    identity_path = _identity("beta", tmp_path / "identity.json")

    adopted = _cli(
        [
            "accept",
            "--root",
            str(reformed_doc),
            "--trust",
            str(genesis_doc),
            "--identity",
            str(identity_path),
        ]
    )
    assert adopted.returncode == 0, adopted.stderr or adopted.stdout

    rollback = _cli(
        [
            "accept",
            "--root",
            str(genesis_doc),
            "--trust",
            str(reformed_doc),
            "--identity",
            str(identity_path),
        ]
    )
    assert rollback.returncode != 0, "the peer process adopted a rollback to the parent"
    assert consensus.REASON_UNCHAINED in rollback.stdout, rollback.stdout

    fork = _cli(
        [
            "accept",
            "--root",
            str(stranger_doc),
            "--trust",
            str(reformed_doc),
            "--identity",
            str(identity_path),
        ]
    )
    assert fork.returncode != 0, "the peer process adopted a stranger fork"
    assert consensus.REASON_UNCHAINED in fork.stdout, fork.stdout

    after = json.loads(identity_path.read_text())
    assert after["trust_root"]["root_id"] == consensus.root_id(reformed), (
        "a refused root must not move the held trust root"
    )


def test_re_running_accept_is_idempotent(election, consensus, cluster, tmp_path):
    _, root = _formed(election, consensus, cluster)
    identity_path = _identity(WINNER, tmp_path / "identity.json")
    election.accept_root(root, identity_path, root_out=tmp_path / "trust-root.json")
    first_bytes = identity_path.read_bytes()
    out = election.accept_root(root, identity_path, root_out=tmp_path / "trust-root.json")
    assert out["accepted"]
    assert identity_path.read_bytes() == first_bytes


# --- the artifacts: real processes, the scripts, the signer -------------------


@pytest.fixture(scope="module")
def signer_module():
    """The Step 17 signer, loaded under its own name so its SignerError and
    its refusals are this suite's to assert against."""
    return _load(
        "sparknet_signer_for_election_test",
        REPO_ROOT / "master-node" / "services" / "sparknet-signer.py",
    )


def _cli(args: list[str], env: dict | None = None, timeout: float = 60):
    """Run the shipped CLI exactly as an operator would."""
    return subprocess.run(
        [str(PY), str(ELECTION_SCRIPT), "--shared-dir", str(SHARED), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _keygen_dirs(tmp_path: Path) -> dict[str, Path]:
    """Three key directories, keys minted by the CLI's own keygen."""
    dirs: dict[str, Path] = {}
    for name in MEMBERS:
        key_dir = tmp_path / f"keys-{name}"
        result = _cli(["keygen", "--key-dir", str(key_dir)])
        assert result.returncode == 0, f"keygen failed: {result.stderr}"
        private = key_dir / "cluster.ed25519"
        assert private.is_file() and private.stat().st_mode & 0o777 == 0o600
        assert (key_dir / "cluster.pub.b64").is_file()
        dirs[name] = key_dir
    return dirs


def _members_doc(key_dirs: dict[str, Path], path: Path) -> Path:
    members = []
    for name in MEMBERS:
        members.append(
            {
                "node_id": name,
                "fingerprint": hashlib.sha256(f"election-test-{name}".encode()).hexdigest(),
                "wireguard_pubkey": base64.b64encode(hashlib.sha256(f"wg-{name}".encode()).digest()).decode(),
                "cluster_pubkey": (key_dirs[name] / "cluster.pub.b64").read_text().strip(),
            }
        )
    path.write_text(json.dumps({"schema_version": "1.0", "members": members}, indent=2))
    return path


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"nothing listened on 127.0.0.1:{port} within {timeout}s")


def _serve_process(members_path: Path, port: int, extra: list[str] | None = None) -> subprocess.Popen:
    return subprocess.Popen(
        [
            str(PY),
            str(ELECTION_SCRIPT),
            "--shared-dir",
            str(SHARED),
            "serve",
            "--members",
            str(members_path),
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            *(extra or []),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _member_cmd(
    base: str,
    candidate: str,
    identity: Path,
    key_dir: Path,
    *,
    trust: Path | None = None,
    as_member: bool = False,
    root_out: Path | None = None,
    root_doc: Path | None = None,
    members: Path | None = None,
) -> list[str]:
    command = [
        str(PY),
        str(ELECTION_SCRIPT),
        "--shared-dir",
        str(SHARED),
        "member",
        "--url",
        base,
        "--candidate",
        candidate,
        "--identity",
        str(identity),
        "--key-dir",
        str(key_dir),
        "--wait-seconds",
        "20",
    ]
    if trust is not None:
        command += ["--trust", str(trust)]
    if as_member:
        command += ["--as-member"]
    if root_out is not None:
        command += ["--root-out", str(root_out)]
    if root_doc is not None:
        command += ["--root-doc", str(root_doc)]
    if members is not None:
        command += ["--members", str(members)]
    return command


def test_three_real_member_processes_form_the_root_and_flip_one_identity(tmp_path, consensus, election):
    """The CLI end to end: three processes, one socket, one root, one flip.

    Every piece of this is a shipped artifact — keygen, serve, member — because
    the unit tests above prove the pieces agree with each other, and this proves
    they agree with *each other across a process boundary*, which is where the
    wiring (paths, flags, JSON on the wire) actually lives.
    """
    key_dirs = _keygen_dirs(tmp_path)
    members_path = _members_doc(key_dirs, tmp_path / "cluster-members.json")
    # One directory per node: on a real deployment each node has its own
    # filesystem, and three accept processes writing one trust-root.json in one
    # directory would be a test artifact of co-location, not a property.
    identities = {}
    for name in MEMBERS:
        node_dir = tmp_path / name
        node_dir.mkdir()
        identities[name] = _identity(name, node_dir / "identity.json")
    losers_before = {name: identities[name].read_bytes() for name in ("alpha", "beta")}

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    server = _serve_process(members_path, port)
    try:
        try:
            _wait_for_port(port)
        except AssertionError:
            if server.poll() is not None:
                _, err = server.communicate(timeout=5)
                raise AssertionError(f"exchange exited at startup:\n{err}") from None
            raise
        outputs = {}
        procs = [
            subprocess.Popen(
                _member_cmd(base, WINNER, identities[name], key_dirs[name]),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for name in MEMBERS
        ]
        for name, proc in zip(MEMBERS, procs, strict=True):
            out, err = proc.communicate(timeout=60)
            assert proc.returncode == 0, f"{name} failed ({proc.returncode}):\n{out}\n{err}"
            outputs[name] = json.loads(out)

        # Resume, not restart: a second run of the winner's ceremony finds its
        # bid and ballot in, adds nothing, and leaves the flipped identity
        # byte-identical.
        before_resume = identities[WINNER].read_bytes()
        resumed_proc = subprocess.run(
            _member_cmd(base, WINNER, identities[WINNER], key_dirs[WINNER]),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert resumed_proc.returncode == 0, resumed_proc.stderr
        resumed = json.loads(resumed_proc.stdout)
        assert resumed["request"] == {"already_filed": True}
        assert resumed["vote"] == {"already_cast": True}
        assert resumed["accept"]["accepted"] is True
        assert identities[WINNER].read_bytes() == before_resume

        # The exchange's own view, while it is still up.
        status = election.status_of(base)
        assert status["state"] == "formed"
    finally:
        _stop(server)

    # The winner flipped; the two that stayed peers did not move a byte.
    winner_doc = json.loads(identities[WINNER].read_text())
    assert winner_doc["role"] == "master"
    assert winner_doc["operational_key"]["held"] is True
    for name in ("alpha", "beta"):
        assert identities[name].read_bytes() == losers_before[name], (
            f"{name} did not win; the ceremony touched its identity"
        )
        assert outputs[name]["accept"]["accepted"] is False
        assert outputs[name]["accept"]["reason"] == "not_elected"

    # The winner recorded the formed root; the two that stayed peers recorded
    # nothing at all — a losing member's accept "verifies and reports, changes
    # nothing", so its directory holds exactly what it held before the run.
    winner_document = json.loads((tmp_path / WINNER / "trust-root.json").read_text())
    root = winner_document["root"]
    ok, reason = consensus.verify_root(root)
    assert ok, f"the winner's copy does not verify: {reason}"
    assert set(root["signatures"]) == set(MEMBERS)
    assert winner_document["root_id"] == consensus.root_id(root)
    assert winner_doc["trust_root"]["root_id"] == winner_document["root_id"]
    for name in ("alpha", "beta"):
        assert not (tmp_path / name / "trust-root.json").exists(), (
            f"{name} lost the election but still wrote a trust-root.json"
        )
    # And the exchange's view of which root formed agrees with what was installed.
    assert status["root_id"] == winner_document["root_id"]


def test_two_real_member_processes_form_a_pair_root_and_flip_one_identity(tmp_path, consensus, election):
    """A 2-of-2 pair election: two processes, one socket, one root, one flip.

    The pair is the smallest lawful cluster. Both members must bid and vote for
    the same candidate and both must co-sign — a single member can never reach
    the threshold on its own — and the losing member's identity stays untouched.
    """
    pair = ("alpha", "beta")
    key_dirs = {name: _keygen_dirs(tmp_path)[name] for name in pair}
    members_path = tmp_path / "cluster-members.json"
    members = [
        {
            "node_id": name,
            "fingerprint": hashlib.sha256(f"election-test-{name}".encode()).hexdigest(),
            "wireguard_pubkey": base64.b64encode(hashlib.sha256(f"wg-{name}".encode()).digest()).decode(),
            "cluster_pubkey": (key_dirs[name] / "cluster.pub.b64").read_text().strip(),
        }
        for name in pair
    ]
    members_path.write_text(json.dumps({"schema_version": "1.0", "members": members}, indent=2))

    identities = {}
    for name in pair:
        node_dir = tmp_path / f"pair-{name}"
        node_dir.mkdir()
        identities[name] = _identity(name, node_dir / "identity.json")
    loser_before = identities["beta"].read_bytes()

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    server = _serve_process(members_path, port)
    try:
        _wait_for_port(port)
        procs = [
            subprocess.Popen(
                _member_cmd(base, "alpha", identities[name], key_dirs[name]),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for name in pair
        ]
        outputs = {}
        for name, proc in zip(pair, procs, strict=True):
            out, err = proc.communicate(timeout=60)
            assert proc.returncode == 0, f"{name} failed ({proc.returncode}):\n{out}\n{err}"
            outputs[name] = json.loads(out)
        assert election.status_of(base)["state"] == "formed"
    finally:
        _stop(server)

    winner_doc = json.loads(identities["alpha"].read_text())
    assert winner_doc["role"] == "master"
    assert winner_doc["operational_key"]["held"] is True
    assert identities["beta"].read_bytes() == loser_before, "the losing member of a pair must not be touched"
    assert outputs["beta"]["accept"]["accepted"] is False
    assert outputs["beta"]["accept"]["reason"] == "not_elected"

    document = json.loads((tmp_path / "pair-alpha" / "trust-root.json").read_text())
    root = document["root"]
    ok, reason = consensus.verify_root(root)
    assert ok, f"the pair root does not verify: {reason}"
    assert set(root["signatures"]) == set(pair)
    assert not (tmp_path / "pair-beta" / "trust-root.json").exists()


def test_three_real_member_processes_form_an_admission_root(tmp_path, consensus, election):
    """The full join ceremony across process boundaries.

    A pair root is formed, then a third member joins without changing the
    Master. The existing peer and the new member must both persist the trio
    root as members — only the elected Master may flip to role master.
    """
    key_dirs = _keygen_dirs(tmp_path)
    # The parent's master_pubkey must be the operational key the child's
    # candidate process will use. Mint it first; cast_request reuses it.
    operational = _cli(["keygen", "--key-dir", str(key_dirs["beta"]), "--name", "operational"])
    assert operational.returncode == 0, operational.stderr
    beta_operational = (key_dirs["beta"] / "operational.pub.b64").read_text().strip()

    members_path = _members_doc(key_dirs, tmp_path / "cluster-members.json")
    member_document = json.loads(members_path.read_text())
    parent_members = [m for m in member_document["members"] if m["node_id"] in ("alpha", "beta")]
    parent = consensus.attach_root_signatures(
        {
            "version": "1.2",
            "nonce": "pair-parent",
            "formed_at": "2026-10-06T12:00:00+00:00",
            "members": parent_members,
            "master_node_id": "beta",
            "master_pubkey": beta_operational,
            "previous_root_id": "",
            "epoch": 0,
        },
        {name: (key_dirs[name] / "cluster.ed25519").read_text().strip() for name in ("alpha", "beta")},
    )
    parent_doc = tmp_path / "parent.json"
    parent_doc.write_text(json.dumps({"root": parent, "root_id": consensus.root_id(parent)}, indent=2))
    alpha_root = tmp_path / "alpha-root.json"
    beta_root = tmp_path / "beta-root.json"
    gamma_root = tmp_path / "gamma-root.json"
    alpha_root.write_bytes(parent_doc.read_bytes())
    beta_root.write_bytes(parent_doc.read_bytes())

    identities = {}
    for name in MEMBERS:
        node_dir = tmp_path / name
        node_dir.mkdir()
        identities[name] = _identity(name, node_dir / "identity.json")

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    server = _serve_process(members_path, port, ["--trust", str(parent_doc), "--admission"])
    try:
        _wait_for_port(port)
        commands = {
            "alpha": _member_cmd(
                base,
                "beta",
                identities["alpha"],
                key_dirs["alpha"],
                root_doc=alpha_root,
                as_member=True,
                members=members_path,
            ),
            "beta": _member_cmd(
                base,
                "beta",
                identities["beta"],
                key_dirs["beta"],
                root_doc=beta_root,
                members=members_path,
            ),
            "gamma": _member_cmd(
                base,
                "beta",
                identities["gamma"],
                key_dirs["gamma"],
                trust=parent_doc,
                as_member=True,
                root_out=gamma_root,
                members=members_path,
            ),
        }
        outputs = {}
        processes = {
            name: subprocess.Popen(
                commands[name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for name in MEMBERS
        }
        for name, process in processes.items():
            stdout, stderr = process.communicate(timeout=60)
            assert process.returncode == 0, f"{name} failed: {stdout}\n{stderr}"
            outputs[name] = json.loads(stdout)
        status = election.status_of(base)
        assert status["state"] == "formed"
    finally:
        _stop(server)

    child_documents = [json.loads(path.read_text()) for path in (alpha_root, beta_root, gamma_root)]
    child_ids = {document["root_id"] for document in child_documents}
    assert len(child_ids) == 1, "every member must hold the same child root"
    child = child_documents[0]["root"]
    assert child["version"] == "1.3"
    assert child["master_node_id"] == "beta"
    assert set(child["signatures"]) == set(MEMBERS)
    assert consensus.verify_root(child, trust=parent) == (True, consensus.REASON_OK)
    assert consensus.verify_chain([child, parent]) == (True, consensus.REASON_OK)

    alpha_doc = json.loads(identities["alpha"].read_text())
    beta_doc = json.loads(identities["beta"].read_text())
    gamma_doc = json.loads(identities["gamma"].read_text())
    assert alpha_doc["role"] == "peer"
    assert beta_doc["role"] == "master"
    assert gamma_doc["role"] == "peer"
    assert alpha_doc["trust_root"]["root_id"] == child_documents[0]["root_id"]
    assert gamma_doc["trust_root"]["root_id"] == child_documents[0]["root_id"]
    assert outputs["alpha"]["accept"]["adopted_as_member"] is True
    assert outputs["beta"]["accept"]["adopted_as_member"] is False
    assert outputs["gamma"]["accept"]["adopted_as_member"] is True


def test_the_role_scripts_run_the_ceremony_and_refuse_a_wrong_expectation(tmp_path, consensus):
    """The scripts are how a human runs the election; they are the artifact.

    Two peer nodes and the master node, three scripts in parallel against one
    exchange, then the refusals that only exist at this level: what a script
    does when it is asked to install a root it was told not to expect.
    """
    key_dirs = _keygen_dirs(tmp_path)
    members_path = _members_doc(key_dirs, tmp_path / "cluster-members.json")
    identities = {}
    for name in MEMBERS:
        node_dir = tmp_path / name
        node_dir.mkdir()
        identities[name] = _identity(name, node_dir / "identity.json")
    master_identity = tmp_path / "master-identity.json"
    master_doc = json.loads(MASTER_IDENTITY.read_text())
    master_doc["node_id"] = WINNER
    master_identity.write_text(json.dumps(master_doc, indent=2, sort_keys=False) + "\n")
    root_doc = tmp_path / "cluster-trust-root.json"
    root_doc.write_text(TRUST_DOC.read_text())
    root_doc_metadata = {
        key: value for key, value in json.loads(root_doc.read_text()).items() if key not in ("root", "root_id")
    }
    losers_before = {name: identities[name].read_bytes() for name in ("alpha", "beta")}

    script_env = {
        **os.environ,
        "SPARKNET_STATE_DIR": str(tmp_path / "state"),
        "PY": str(PY),
    }
    master_cmd = [
        "bash",
        str(MASTER_SCRIPT),
        "--expect-master",
        WINNER,
        "--identity",
        str(master_identity),
        "--root-doc",
        str(root_doc),
        "--members",
        str(members_path),
        "--key-dir",
        str(key_dirs[WINNER]),
        "--wait-seconds",
        "20",
    ]

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    server = _serve_process(members_path, port)
    try:
        try:
            _wait_for_port(port)
        except AssertionError:
            if server.poll() is not None:
                _, err = server.communicate(timeout=5)
                raise AssertionError(f"exchange exited at startup:\n{err}") from None
            raise

        def peer_cmd(name: str, *extra: str) -> list[str]:
            return [
                "bash",
                str(PEER_SCRIPT),
                "--candidate",
                WINNER,
                "--identity",
                str(identities[name]),
                "--key-dir",
                str(key_dirs[name]),
                "--wait-seconds",
                "20",
                "--url",
                base,
                "--members",
                str(members_path),
                *extra,
            ]

        commands = [
            peer_cmd("alpha"),
            peer_cmd("beta"),
            [*master_cmd, "--url", base],
        ]
        procs = [
            subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=script_env)
            for cmd in commands
        ]
        for name, cmd, proc in zip(MEMBERS, commands, procs, strict=True):
            out, err = proc.communicate(timeout=60)
            assert proc.returncode == 0, (
                f"script for {name} failed ({proc.returncode}):\ncmd: {' '.join(cmd)}\n{out}\n{err}"
            )

        # The master node's own manifest flipped; its metadata survived.
        installed = json.loads(root_doc.read_text())
        for key, value in root_doc_metadata.items():
            assert installed.get(key) == value, f"root-doc key {key!r} lost in install"
        root = installed["root"]
        ok, reason = consensus.verify_root(root)
        assert ok, reason
        assert installed["root_id"] == consensus.root_id(root)

        master_after_ceremony = master_identity.read_bytes()
        master_now = json.loads(master_after_ceremony)
        assert master_now["role"] == "master"
        assert master_now["node_id"] == WINNER
        for name in ("alpha", "beta"):
            assert identities[name].read_bytes() == losers_before[name], (
                f"{name} ran its script and did not win; its identity moved"
            )

        # The refusals that only exist at the script level.
        # 1. A peer told to expect a different master: its vote is already in,
        #    the root is formed, and the member's loyalty check must still fire
        #    before anything is installed.
        wrong_peer = subprocess.run(
            peer_cmd("alpha", "--candidate", "beta"),
            capture_output=True,
            text=True,
            timeout=60,
            env=script_env,
        )
        assert wrong_peer.returncode != 0, "the peer installed a root it was told not to expect"
        assert "unexpected_master" in wrong_peer.stdout
        assert identities["alpha"].read_bytes() == losers_before["alpha"]
        # 2. The master script asked to expect someone else — even now, with
        #    the ceremony already done and the root already signed, the answer
        #    is refusal rather than a silent install.
        wrong_master = subprocess.run(
            [*master_cmd, "--url", base, "--expect-master", "alpha"],
            capture_output=True,
            text=True,
            timeout=60,
            env=script_env,
        )
        assert wrong_master.returncode != 0, "the master script accepted an --expect-master it never voted for"
        assert "unexpected_master" in wrong_master.stdout
        assert master_identity.read_bytes() == master_after_ceremony, (
            "a refused master script still touched its identity"
        )
    finally:
        _stop(server)


def test_the_formed_root_is_a_working_signer_start(signer_module, election, consensus, authz, cluster, tmp_path):
    """The join between this step and Step 17: the root the election produced
    is the only input the isolated signer takes, and it starts on it."""
    _, root = _formed(election, consensus, cluster)
    key_path = tmp_path / "operational.ed25519"
    key_path.write_text(cluster["operational_private"][WINNER] + "\n")
    key_path.chmod(0o600)
    signer = signer_module.Signer(
        WINNER,
        key_path,
        root,
        authz,
        consensus,
        tmp_path / "ledger.json",
        clock=_clock,
    )
    assert signer.root_id == consensus.root_id(root)

    identity = {
        "node_id": "peer-1",
        "role": "peer",
        "wireguard_public_key_b64": authz.generate_keypair()[1],
        "overlay_ipv4": "10.100.0.11/32",
        "requested_capabilities": ["telemetry"],
    }
    entry = {
        "fingerprint": authz.fingerprint(identity),
        "identity": identity,
        "capabilities": ["telemetry"],
        "issued_at": FIXED.isoformat(),
        "expires_at": (FIXED + timedelta(days=30)).isoformat(),
        "revoked": False,
    }
    response = signer.handle({"op": "sign-registry-entry", "root_id": signer.root_id, "entry": entry})
    assert response["ok"], response
    signed = response["entry"]
    unsigned = {k: v for k, v in signed.items() if k != "signature_b64"}
    assert authz.verify_signature(
        authz.public_key_from_b64(signer.public_key_b64),
        signed["signature_b64"],
        authz.authorization_message(unsigned),
    )
    assert (tmp_path / "ledger.json").is_file()


def test_nothing_but_the_elected_key_and_the_exact_root_can_start_that_signer(
    signer_module, election, consensus, authz, cluster, tmp_path
):
    """The three refusals that make the election's output meaningful: any other
    key, any other Master, any other root — all refused at construction."""
    _, root = _formed(election, consensus, cluster)

    def keyfile(private_b64: str, name: str) -> Path:
        path = tmp_path / name
        path.write_text(private_b64 + "\n")
        path.chmod(0o600)
        return path

    winner_key = keyfile(cluster["operational_private"][WINNER], "winner.ed25519")
    loser_key = keyfile(cluster["operational_private"]["alpha"], "loser.ed25519")

    with pytest.raises(signer_module.SignerError) as exc:
        signer_module.Signer(WINNER, loser_key, root, authz, consensus, tmp_path / "ledger.json")
    assert "not the key" in str(exc.value)

    _, alpha_root = _formed(election, consensus, cluster, candidate="alpha")
    with pytest.raises(signer_module.SignerError) as exc:
        signer_module.Signer(WINNER, winner_key, alpha_root, authz, consensus, tmp_path / "ledger.json")
    assert "refusing to sign" in str(exc.value)

    tampered = json.loads(json.dumps(root))
    tampered["nonce"] = "tampered"
    with pytest.raises(signer_module.SignerError) as exc:
        signer_module.Signer(WINNER, winner_key, tampered, authz, consensus, tmp_path / "ledger.json")
    assert "not valid" in str(exc.value)


def test_the_root_authorises_exactly_one_key_and_it_is_the_winners(election, consensus, authz, cluster):
    """The admin surface's whole security claim in one assertion: the key that
    can sign under the root is the winner's operational key, and no other
    member's key derives to it."""
    _, root = _formed(election, consensus, cluster)
    assert root["master_pubkey"] == authz.public_key_b64(
        authz.private_key_from_b64(cluster["operational_private"][WINNER]).public_key()
    )
    derived = {
        name: authz.public_key_b64(authz.private_key_from_b64(cluster["operational_private"][name]).public_key())
        for name in MEMBERS
    }
    assert len(set(derived.values())) == len(MEMBERS), "members share an operational key"
    for loser in ("alpha", "beta"):
        assert derived[loser] != root["master_pubkey"]
    # And the root names exactly the member set the membership declares.
    assert {m["node_id"] for m in root["members"]} == set(MEMBERS)


# --- timeouts -------------------------------------------------------------------


def test_slow_client_is_dropped_and_the_exchange_keeps_serving(election, live, monkeypatch) -> None:
    """F4: the exchange's listener must drop an idle trickle connection.

    A client that stops mid-request-line must not hold one of the exchange's
    threads open. The ``live`` fixture serves the real ``_Handler``; patching
    its ``timeout`` class attribute applies to the *next* connection, because
    ``StreamRequestHandler.setup`` reads it per connection. monkeypatch
    restores it afterwards.
    """
    monkeypatch.setattr(election._Handler, "timeout", 0.4)
    port = int(live.rsplit(":", 1)[1])
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(b"GET /election/status HTTP/1.1")  # deliberately no CRLF: the read blocks
    sock.settimeout(3)
    assert sock.recv(4096) == b"", "the exchange must close an idle trickle connection"
    sock.close()

    # A fresh, complete request on a new connection is still answered.
    status = election.status_of(live)
    assert status["root"] is None, "the exchange must still serve a status call"


def test_internal_errors_do_not_leak_internals(election, live, monkeypatch, capsys) -> None:
    """F10: the exchange's 500s must name a stable reason, never the exception.

    The exception text can name files or membership internals that have no
    business crossing the bus; it is logged to stderr for an operator instead.
    """

    def _boom(body, consensus):
        raise RuntimeError("SECRET_ELECTION_DETAIL")

    monkeypatch.setattr(election.ElectionExchange, "submit_request", _boom)

    import urllib.error
    import urllib.request

    body = json.dumps({"member": "alpha", "bid": {"op_key": "x"}}).encode()
    req = urllib.request.Request(live + "/election/request", data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            payload = json.loads(response.read())
            status = response.status
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read())
        status = exc.code
    assert status == 500
    assert payload["ok"] is False
    assert "SECRET_ELECTION_DETAIL" not in str(payload)
    assert "SECRET_ELECTION_DETAIL" in capsys.readouterr().err


def test_sign_root_refuses_a_substituted_operational_key(election, cluster, keydirs, monkeypatch):
    """The elected node's co-signature must bind its own operational key, not just its id."""
    root = {
        "version": "1.1",
        "nonce": "substitution",
        "formed_at": "2026-11-08T00:00:00Z",
        "members": cluster["members"],
        "master_node_id": WINNER,
        "master_pubkey": cluster["operational"]["alpha"],
        "previous_root_id": "",
        "signatures": {},
    }
    monkeypatch.setattr(election, "status_of", lambda *_args, **_kwargs: {"root": root})
    monkeypatch.setattr(election, "_call", lambda *_args, **_kwargs: {"ok": True})
    (keydirs[WINNER] / "operational.ed25519").write_text(cluster["operational_private"][WINNER] + "\n")
    with pytest.raises(election.ElectionError) as exc:
        election.sign_root("http://unused", WINNER, WINNER, election.DEFAULT_ELECTION_ID, keydirs[WINNER])
    _raise_reason(pytest, exc, "root_unusable")
    assert "operational public key" in str(exc.value)


def test_accept_root_refuses_a_rollback_without_trust_evidence(election, consensus, cluster, keydirs, tmp_path):
    first, _ = _formed(election, consensus, cluster)
    identity = (
        json.loads((tmp_path / "node-identity.json").read_text())
        if (tmp_path / "node-identity.json").is_file()
        else {
            "node_id": WINNER,
            "trust_root": {"root_id": "root-held"},
        }
    )
    identity["trust_root"] = {"root_id": "root-held"}
    path = tmp_path / "identity.json"
    path.write_text(json.dumps(identity))
    with pytest.raises(election.ElectionError) as exc:
        election.accept_root(first.status()["root"], path)
    _raise_reason(pytest, exc, "unchained_root")

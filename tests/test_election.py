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
import importlib.util
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
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves its own module through
    # sys.modules, and a late registration raises an AttributeError that names
    # neither the cause nor the file. See sparknet-consensus._load_authz.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
    for index, name in enumerate(MEMBERS):
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


def _formed(election, consensus, cluster, candidate: str = WINNER):
    """Run the whole ceremony in-process; returns (exchange, signed root)."""
    exchange = election.ElectionExchange(cluster["members"], clock=_clock)
    _all_bids(exchange, election, cluster)
    _all_votes(exchange, consensus, cluster, candidate)
    root = exchange.status()["root"]
    for name in MEMBERS:
        exchange.submit_signature(name, consensus.sign_root(root, name, cluster["private"][name])[name])
    status = exchange.status()
    assert status["state"] == "formed"
    return exchange, status["root"]


def _identity(node_id: str, path: Path) -> Path:
    """A live copy of the shipped peer identity, initialised to a real node."""
    document = json.loads(PEER_IDENTITY.read_text())
    document["node_id"] = node_id
    path.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n")
    return path


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
    """Re-formation: a later root with new signatures replaces the held one."""
    _, first = _formed(election, consensus, cluster, candidate="alpha")
    _, second = _formed(election, consensus, cluster, candidate=WINNER)
    assert first["nonce"] != second["nonce"]
    identity_path = _identity(WINNER, tmp_path / "identity.json")
    out = election.accept_root(second, identity_path, trust_root=first)
    assert out["accepted"] and out["root_id"] != consensus.root_id(first)
    after = json.loads(identity_path.read_text())
    assert after["trust_root"]["root_id"] == consensus.root_id(second)


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


def _serve_process(members_path: Path, port: int) -> subprocess.Popen:
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


def _member_cmd(base: str, candidate: str, identity: Path, key_dir: Path) -> list[str]:
    return [
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

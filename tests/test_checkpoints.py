"""Signed checkpoints and cross-node head anchoring — PLAN Step 31.

`shared/sparknet-provenance.py` appends a `checkpoint` ledger block (size +
head hash + RFC 6962 root of every block hash, signed like every block) and
`anchor`/`verify_checkpoint` exchange it between nodes, refusing a rollback
(an anchored size that shrinks) and a fork (the same height with a different
root), with `shared/sparknet-merkle.py` supplying `verify_consistency` for
honest growth.

These tests drive two in-process nodes: separate vaults, separate state dirs,
separate node keys. The checkpoint state lives in each receiver's
`$SPARKNET_STATE_DIR/anchored-checkpoints.json`; the environment is swapped
per node the same way a process would carry it.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent
PROVENANCE_PATH = REPO_ROOT / "shared" / "sparknet-provenance.py"
CONTRACT = json.loads((REPO_ROOT / "contracts" / "tracking-schema.json").read_text())

OWNER_ID = "U-10421"


@pytest.fixture(scope="module")
def provenance() -> ModuleType:
    return load_by_path("sparknet_provenance_under_test", PROVENANCE_PATH)


@pytest.fixture(scope="module")
def merkle(provenance: ModuleType) -> ModuleType:
    return provenance._load_merkle()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def user_record_template() -> str:
    return (
        "---\n"
        "type: user-record\n"
        "schema: sparknet-user/1\n"
        "status: unfilled\n"
        'owner_id: ""\n'
        'owner_node: ""\n'
        "role: owner\n"
        "immutable: true\n"
        "key:\n"
        "  alg: ed25519\n"
        '  public_key_b64: ""\n'
        '  fingerprint: ""\n'
        '  key_ref: "$SPARKNET_STATE_DIR/keys/user.ed25519"\n'
        '  created: ""\n'
        "---\n\n"
        "# user record\n"
    )


def use_state(monkeypatch: pytest.MonkeyPatch, state: Path) -> None:
    """Point SPARKNET_STATE_DIR at one node's state, as its process would."""
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(state))


def install_node_key(state: Path, private_b64: str) -> None:
    key = state / "keys" / "ed25519-node.key.b64"
    key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key.write_text(private_b64 + "\n")
    key.chmod(0o600)


def make_node(tmp_path: Path, provenance: ModuleType, monkeypatch: pytest.MonkeyPatch, name: str):
    """A full node: filled user record + a fresh node key, in its own state dir."""
    vault = tmp_path / name
    state = tmp_path / f".state-{name}"
    write(vault / "00_System" / "user.md", user_record_template())
    (vault / "01_Inbox").mkdir()
    (vault / "blockchain").mkdir()
    use_state(monkeypatch, state)
    provenance.user_init(vault, owner_id=OWNER_ID)
    authz = provenance._load_authz()
    private_b64, _ = authz.generate_keypair()
    install_node_key(state, private_b64)
    return vault, state, private_b64


def make_node_with_key(tmp_path: Path, provenance: ModuleType, name: str, private_b64: str):
    """An adversarial or derivative node: an existing node's key, its own state."""
    vault = tmp_path / name
    state = tmp_path / f".state-{name}"
    (vault / "blockchain").mkdir(parents=True)
    install_node_key(state, private_b64)
    return vault, state


def push_approval(provenance: ModuleType, vault: Path, monkeypatch: pytest.MonkeyPatch, state: Path, tag: str) -> None:
    use_state(monkeypatch, state)
    record = provenance.parse_user_record(vault)
    data = provenance.build_approval_data(
        vault=vault,
        question=tag,
        decision="approved",
        note_refs=[],
        agent="tester",
        model="none",
        record=record,
    )
    provenance.append_block(vault, data)


def push_plain(provenance: ModuleType, vault: Path, monkeypatch: pytest.MonkeyPatch, state: Path, tag: str) -> None:
    """A block with no record payload — enough to grow an adversarial chain."""
    use_state(monkeypatch, state)
    provenance.append_block(vault, {"event": "probe", "seq": tag})


def ledger_hashes(provenance: ModuleType, vault: Path) -> list[str]:
    ledger = provenance.load_ledger(vault / "blockchain" / "ledger.json")
    return [str(block.get("hash")) for block in ledger["blocks"]]


# --- the checkpoint block: shape, signature, semantics ---------------------------


def test_checkpoint_data_names_the_head_and_matches_the_contract(
    provenance: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault, state, _ = make_node(tmp_path, provenance, monkeypatch, "a")
    push_approval(provenance, vault, monkeypatch, state, "q1")
    push_approval(provenance, vault, monkeypatch, state, "q2")
    push_approval(provenance, vault, monkeypatch, state, "q3")

    data = provenance.build_checkpoint_data(vault=vault)
    assert set(data) == set(CONTRACT["checkpoint"]["data_fields"]), (
        "the checkpoint payload no longer matches contracts/tracking-schema.json"
    )
    assert data["event"] == "checkpoint"
    assert data["size"] == 3
    hashes = ledger_hashes(provenance, vault)
    assert data["head_hash"] == hashes[-1]
    assert data["root"] == provenance._load_merkle().merkle_root(hashes)


def test_a_checkpoint_block_appends_signed_like_any_block(
    provenance: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault, state, _ = make_node(tmp_path, provenance, monkeypatch, "a")
    push_approval(provenance, vault, monkeypatch, state, "q1")
    push_approval(provenance, vault, monkeypatch, state, "q2")
    push_approval(provenance, vault, monkeypatch, state, "q3")

    block = provenance.checkpoint(vault)
    assert block["data"]["size"] == 3, (
        "a checkpoint snapshots the chain before it is appended, so the block "
        "joins the next snapshot instead of hashing its own root"
    )
    ledger = provenance.load_ledger(vault / "blockchain" / "ledger.json")
    assert ledger["blocks"][-1] == block and block["block_id"] == "00000003"

    ok, detail = provenance.verify_chain(ledger)
    assert ok, detail
    authz = provenance._load_authz()
    node_pub = authz.public_key_from_b64(block["node_pubkey_b64"])
    assert authz.verify_signature(node_pub, block["signature"], provenance.block_header_signable(block)), (
        "the checkpoint header signature must verify against the block's own node key"
    )
    assert "signatures" not in block["data"], (
        "a checkpoint carries no data.signatures: the header signature is the whole commitment"
    )
    assert provenance.verify_approval_blocks(vault) == [], (
        "checkpoint blocks must not confuse the record-level approval check"
    )


def test_an_empty_chain_cannot_be_checkpointed(provenance: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault, state, _ = make_node(tmp_path, provenance, monkeypatch, "a")
    push_approval(provenance, vault, monkeypatch, state, "q0")
    provenance.append_block(vault, {"event": "probe", "seq": "x"})
    ledger = provenance.load_ledger(vault / "blockchain" / "ledger.json")
    ledger["blocks"] = []
    (vault / "blockchain" / "ledger.json").write_text(json.dumps(ledger))
    with pytest.raises(provenance.ProvenanceError, match="empty chain"):
        provenance.build_checkpoint_data(vault=vault)


def test_checkpoint_is_a_peer_event_disjoint_from_master(provenance: ModuleType):
    peer = set(CONTRACT["approval"]["event_vocabulary"]["peer"])
    master = set(CONTRACT["approval"]["event_vocabulary"]["master"])
    assert "checkpoint" in peer
    assert "checkpoint" not in master, "a checkpoint is a statement about a peer chain; only the owning peer signs it"
    assert not (peer & master)


# --- anchoring: honest growth ----------------------------------------------------


def test_an_honest_growth_chain_anchors(
    provenance: ModuleType, merkle: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault_a, state_a, _ = make_node(tmp_path, provenance, monkeypatch, "a")
    vault_b, state_b, _ = make_node(tmp_path, provenance, monkeypatch, "b")

    push_approval(provenance, vault_a, monkeypatch, state_a, "q1")
    push_approval(provenance, vault_a, monkeypatch, state_a, "q2")
    push_approval(provenance, vault_a, monkeypatch, state_a, "q3")
    c1 = provenance.checkpoint(vault_a)

    use_state(monkeypatch, state_b)
    ok, detail, record = provenance.anchor(vault_b, c1)
    assert ok, detail
    assert record["size"] == 3

    _push_two_more(provenance, vault_a, monkeypatch, state_a)
    use_state(monkeypatch, state_a)
    hashes = ledger_hashes(provenance, vault_a)
    proof = merkle.consistency_proof(3, hashes)
    c2 = provenance.checkpoint(vault_a)
    assert c2["data"]["size"] == 6

    assert merkle.verify_consistency(3, 6, c1["data"]["root"], c2["data"]["root"], proof), (
        "the sender's own proof must verify before it is worth sending"
    )

    use_state(monkeypatch, state_b)
    ok, detail, record = provenance.anchor(vault_b, c2, proof=proof)
    assert ok, detail
    assert record["size"] == 6
    assert record["root"] == c2["data"]["root"]
    assert provenance.load_anchored(vault_b)[c1["data"]["node_pubkey_b64"]]["size"] == 6


def _push_two_more(provenance: ModuleType, vault: Path, monkeypatch: pytest.MonkeyPatch, state: Path) -> None:
    push_approval(provenance, vault, monkeypatch, state, "q4")
    push_approval(provenance, vault, monkeypatch, state, "q5")


def test_checkpoint_growth_is_recorded_per_node(
    provenance: ModuleType, merkle: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Anchors are keyed by the signing node, so two nodes do not interfere."""
    vault_a, state_a, _ = make_node(tmp_path, provenance, monkeypatch, "a")
    vault_b, state_b, _ = make_node(tmp_path, provenance, monkeypatch, "b")
    vault_c, state_c, _ = make_node(tmp_path, provenance, monkeypatch, "c")

    push_approval(provenance, vault_a, monkeypatch, state_a, "q1")
    push_approval(provenance, vault_a, monkeypatch, state_a, "q2")
    ca1 = provenance.checkpoint(vault_a)

    push_approval(provenance, vault_c, monkeypatch, state_c, "r1")
    cc1 = provenance.checkpoint(vault_c)

    use_state(monkeypatch, state_b)
    ok, detail, _ = provenance.anchor(vault_b, ca1)
    assert ok, detail
    ok2, detail2, _ = provenance.anchor(vault_b, cc1)
    assert ok2, detail2
    store = provenance.load_anchored(vault_b)
    assert store[ca1["data"]["node_pubkey_b64"]]["size"] == 2
    assert store[cc1["data"]["node_pubkey_b64"]]["size"] == 1

    use_state(monkeypatch, state_b)
    ok, detail, _ = provenance.anchor(vault_b, ca1)
    assert ok and "no change" in detail, "re-anchoring the same head is idempotent, not a second fork"


# --- anchoring: refusals ---------------------------------------------------------


def _anchor_a_at_size_6(
    provenance: ModuleType,
    merkle: ModuleType,
    vault_a: Path,
    state_a: Path,
    vault_b: Path,
    state_b: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Anchors A at size 6 (via a first anchor at 3 and an honest growth), so the
    rollback and fork refusals have a baseline to be measured against."""
    push_approval(provenance, vault_a, monkeypatch, state_a, "q1")
    push_approval(provenance, vault_a, monkeypatch, state_a, "q2")
    push_approval(provenance, vault_a, monkeypatch, state_a, "q3")
    c1 = provenance.checkpoint(vault_a)
    use_state(monkeypatch, state_b)
    ok, detail, _ = provenance.anchor(vault_b, c1)
    assert ok, detail
    _push_two_more(provenance, vault_a, monkeypatch, state_a)
    proof = merkle.consistency_proof(3, ledger_hashes(provenance, vault_a))
    c2 = provenance.checkpoint(vault_a)
    use_state(monkeypatch, state_b)
    ok, detail, _ = provenance.anchor(vault_b, c2, proof=proof)
    assert ok, detail
    return c2


def test_a_truncated_tail_is_refused_as_a_rollback(
    provenance: ModuleType, merkle: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault_a, state_a, priv_a = make_node(tmp_path, provenance, monkeypatch, "a")
    vault_b, state_b, _ = make_node(tmp_path, provenance, monkeypatch, "b")

    _anchor_a_at_size_6(provenance, merkle, vault_a, state_a, vault_b, state_b, monkeypatch)

    # The same node cuts its own history back to 4 blocks (three approvals +
    # its first checkpoint) and sign a checkpoint over the shorter chain.
    # B already anchors size 6, so this must be refused as a rollback — even
    # with a consistency proof attached, because it shrinks the anchor.
    vault_t, state_t = make_node_with_key(tmp_path, provenance, "atrunc", priv_a)
    use_state(monkeypatch, state_t)
    ledger = provenance.load_ledger(vault_a / "blockchain" / "ledger.json")
    truncated = dict(ledger, blocks=ledger["blocks"][:4])
    (vault_t / "blockchain" / "ledger.json").write_text(json.dumps(truncated, indent=2) + "\n")
    c_t = provenance.checkpoint(vault_t)
    assert c_t["data"]["size"] == 4

    use_state(monkeypatch, state_b)
    ok, detail, _ = provenance.anchor(vault_b, c_t)
    assert not ok and "rollback" in detail
    ok, detail, _ = provenance.anchor(
        vault_b, c_t, proof=merkle.consistency_proof(4, ledger_hashes(provenance, vault_t))
    )
    assert not ok and "rollback" in detail, "a proof cannot excuse a size that sinks below what this node anchors"
    assert provenance.load_anchored(vault_b)[c_t["data"]["node_pubkey_b64"]]["size"] == 6, (
        "a refused checkpoint must not move the anchor"
    )


def test_a_same_height_fork_is_refused(
    provenance: ModuleType, merkle: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault_a, state_a, priv_a = make_node(tmp_path, provenance, monkeypatch, "a")
    vault_b, state_b, _ = make_node(tmp_path, provenance, monkeypatch, "b")

    _anchor_a_at_size_6(provenance, merkle, vault_a, state_a, vault_b, state_b, monkeypatch)

    # The same node presents a *different* six-block history at the same height.
    vault_f, state_f = make_node_with_key(tmp_path, provenance, "afork", priv_a)
    for i in range(1, 7):
        push_plain(provenance, vault_f, monkeypatch, state_f, f"f-{i}")
    c_f = provenance.checkpoint(vault_f)
    assert c_f["data"]["size"] == 6

    use_state(monkeypatch, state_b)
    ok, detail, _ = provenance.anchor(
        vault_b, c_f, proof=merkle.consistency_proof(6, ledger_hashes(provenance, vault_f))
    )
    assert not ok and "fork" in detail, "a same-height history with a different root is a fork and must be refused"
    assert provenance.load_anchored(vault_b)[c_f["data"]["node_pubkey_b64"]]["root"] != c_f["data"]["root"], (
        "the refused fork must not become the anchor"
    )


def test_consistency_proof_is_required_and_must_be_honest(
    provenance: ModuleType, merkle: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault_a, state_a, _ = make_node(tmp_path, provenance, monkeypatch, "a")
    vault_b, state_b, _ = make_node(tmp_path, provenance, monkeypatch, "b")

    push_approval(provenance, vault_a, monkeypatch, state_a, "q1")
    push_approval(provenance, vault_a, monkeypatch, state_a, "q2")
    push_approval(provenance, vault_a, monkeypatch, state_a, "q3")
    c1 = provenance.checkpoint(vault_a)

    use_state(monkeypatch, state_b)
    ok, detail, _ = provenance.anchor(vault_b, c1)
    assert ok, detail

    _push_two_more(provenance, vault_a, monkeypatch, state_a)
    hashes = ledger_hashes(provenance, vault_a)
    honest = merkle.consistency_proof(3, hashes)
    c2 = provenance.checkpoint(vault_a)

    use_state(monkeypatch, state_b)
    ok, detail, _ = provenance.anchor(vault_b, c2)
    assert not ok and "consistency proof" in detail, "growth without a proof is not evidence of anything"
    forged = [("ab" * 32) if i == 0 else h for i, h in enumerate(honest)]
    ok, detail, _ = provenance.anchor(vault_b, c2, proof=forged)
    assert not ok and "consistency" in detail, "a proof that does not reduce to the anchored root must be refused"
    ok, detail, _ = provenance.anchor(vault_b, c2, proof=honest)
    assert ok, detail


def test_a_tampered_checkpoint_block_is_refused_even_as_a_first_anchor(
    provenance: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault_a, state_a, _ = make_node(tmp_path, provenance, monkeypatch, "a")
    vault_b, state_b, _ = make_node(tmp_path, provenance, monkeypatch, "b")

    push_approval(provenance, vault_a, monkeypatch, state_a, "q1")
    block = provenance.checkpoint(vault_a)

    tampered = json.loads(json.dumps(block))
    tampered["data"]["root"] = "ab" * 32  # edits the signed payload
    use_state(monkeypatch, state_b)
    ok, detail, _ = provenance.anchor(vault_b, tampered)
    assert not ok and "signature" in detail, (
        "a checkpoint whose signed payload was edited must not anchor, even for a node this receiver has never seen"
    )
    ok2, detail2, _ = provenance.anchor(vault_b, {"not": "a block"})
    assert not ok2 and "malformed" in detail2


def test_a_corrupt_anchor_store_is_a_refusal_not_a_reset(
    provenance: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, state_b, _ = make_node(tmp_path, provenance, monkeypatch, "b")
    anchor_path = state_b / "anchored-checkpoints.json"
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_path.write_text("not json")
    with pytest.raises(provenance.ProvenanceError, match="not valid JSON"):
        provenance.load_anchored(tmp_path / "b")


# --- the CLI carries the offline exchange ----------------------------------------


def test_the_cli_appends_and_exchanges_checkpoints(
    provenance: ModuleType, merkle: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault_a, state_a, _ = make_node(tmp_path, provenance, monkeypatch, "a")
    vault_b, state_b, _ = make_node(tmp_path, provenance, monkeypatch, "b")

    push_approval(provenance, vault_a, monkeypatch, state_a, "q1")
    push_approval(provenance, vault_a, monkeypatch, state_a, "q2")

    use_state(monkeypatch, state_a)
    rc = provenance.main(["--vault", str(vault_a), "append-checkpoint"])
    assert rc == 0
    block = provenance.load_ledger(vault_a / "blockchain" / "ledger.json")["blocks"][-1]
    assert block["data"]["event"] == "checkpoint"

    exchange_dir = tmp_path / "exchange"
    exchange_dir.mkdir()
    block_file = exchange_dir / "a-block.json"
    block_file.write_text(json.dumps(block))

    use_state(monkeypatch, state_b)
    rc = provenance.main(["--vault", str(vault_b), "anchor-checkpoint", "--block", str(block_file)])
    assert rc == 0

    # A rolled-back checkpoint through the CLI is refused with exit 1.
    block["data"]["size"] = 1
    rolled = exchange_dir / "a-rolled.json"
    rolled.write_text(json.dumps(block))
    use_state(monkeypatch, state_b)
    rc = provenance.main(["--vault", str(vault_b), "anchor-checkpoint", "--block", str(rolled)])
    assert rc == 1

#!/usr/bin/env python3
"""Sparknet provenance ledger: approvals, checkpoints, inbox acceptance and vault-wide verification.

This lifecycle module loads base and note. It owns the only ledger block
builder/verifier, the approval envelope, checkpoints and anchoring, the
``inbox_acceptance`` builder and the vault-wide accountability check. It does
not know about grants.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

_base = load_shared(
    "sparknet-provenance-base.py",
    "sparknet_provenance_base",
    error=ImportError,
    message=(
        "cannot find shared/sparknet-provenance-base.py; the provenance "
        "ledger lifecycle does not carry a fallback. Set SPARKNET_SHARED_DIR."
    ),
)
_note = load_shared(
    "sparknet-provenance-note.py",
    "sparknet_provenance_note",
    error=_base.ProvenanceError,
    message=(
        "cannot find shared/sparknet-provenance-note.py; the provenance "
        "ledger lifecycle does not carry a fallback. Set SPARKNET_SHARED_DIR."
    ),
)
ProvenanceError = _base.ProvenanceError
_now = _base._now
_iso = _base._iso
_load_authz = _base._load_authz
_load_merkle = _base._load_merkle
_node_key_path = _base._node_key_path
_user_key_path = _base._user_key_path
_refuse_loose_key = _base._refuse_loose_key
_state_dir = _base._state_dir
_node_id = _base._node_id
contract = _base.contract
canonical_json = _base.canonical_json
parse_user_record = _note.parse_user_record
user_is_filled = _note.user_is_filled
user_public_b64 = _note.user_public_b64
user_record_path = _note.user_record_path
_verify_lock = _note._verify_lock
check_user_record = _note.check_user_record
verify_note = _note.verify_note
split_note = _note.split_note

INBOX_SOURCES = ("master-node", "peer-node", "email")

INBOX_UNTRUSTED_SOURCES = ("peer-node", "email")


def block_hash(block: dict[str, Any]) -> str:
    """The chain hash of a block: sha256 over everything except the hash itself.

    Delegates to the one implementation in shared/sparknet-authz.py so the peer,
    the Master's ledger verifier and the signer all hash identically. A second
    copy is how the two ledger shapes diverged once already.
    """
    return _load_authz().ledger_block_hash(block)


def block_header_signable(block: dict[str, Any]) -> bytes:
    """The bytes the appending node key signs: the whole block header.

    `data`, `prev_hash`, `timestamp`, `block_id` and `node_pubkey_b64` are all
    covered. A block whose header was edited, or which was moved to another
    position, fails this signature even if `hash` is recomputed — which is what
    makes a deleted `grant_use` block (and its spent nonce) detectable.
    """
    return _load_authz().ledger_block_signable(block)


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProvenanceError(f"ledger not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"ledger is not valid JSON: {exc}") from exc


def verify_chain(ledger: dict[str, Any]) -> tuple[bool, str]:
    """Walk the chain and check every link. Returns (ok, detail).

    v2 checks, in order, each fail-closed: the required fields are present, the
    block's `block_id` is its own zero-padded index, a non-empty signature is
    present, `prev_hash` links to the previous block's hash (the ledger's
    `genesis_hash` for the first block), the header signature verifies against
    the block's own `node_pubkey_b64`, and the block re-hashes. An unsigned or
    header-edited block therefore cannot pass, and a deleted or reordered block
    breaks the link.
    """
    authz = _load_authz()
    required = contract()["ledger_block"]["required"]
    blocks = ledger.get("blocks")
    if not isinstance(blocks, list):
        return False, "ledger has no blocks array"
    previous = str(ledger.get("genesis_hash", ""))
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            return False, f"block {index} is not an object"
        missing = [f for f in required if f not in block]
        if missing:
            return False, f"block {index} missing {', '.join(missing)}"
        expected_id = f"{index:08d}"
        if block["block_id"] != expected_id:
            return False, (
                f"block {index} has block_id {block['block_id']!r}, expected "
                f"{expected_id!r}: the chain has been reordered or a block removed"
            )
        if not str(block["signature"] or ""):
            return False, f"block {index} ({block['block_id']}) carries no signature"
        if block["prev_hash"] != previous:
            return False, (
                f"block {index} ({block['block_id']}) links to {block['prev_hash']!r}, expected {previous!r}"
            )
        try:
            node_pub = authz.public_key_from_b64(str(block["node_pubkey_b64"] or ""))
        except Exception as exc:
            return False, f"block {index} ({block['block_id']}) has an unusable node_pubkey_b64: {exc}"
        if not authz.verify_signature(node_pub, str(block["signature"]), block_header_signable(block)):
            return False, (
                f"block {index} ({block['block_id']}) header signature does not verify: "
                f"the block was edited, reordered or forged"
            )
        if "hash" in block and block["hash"] != block_hash(block):
            return False, (
                f"block {index} ({block['block_id']}) has been altered: it does not re-hash to its recorded hash"
            )
        previous = block["hash"] if "hash" in block else block_hash(block)
    return True, f"{len(blocks)} block(s), chain intact"


def approval_signable(data: dict[str, Any]) -> bytes:
    """The bytes both approval signatures cover: the payload without signatures."""
    return canonical_json({k: v for k, v in data.items() if k != "signatures"})


def _node_public_b64(vault: Path) -> str:
    """This vault's node public key, inline so an offline verifier needs no keys."""
    authz = _load_authz()
    node_path = _node_key_path(vault)
    if not node_path.is_file():
        raise ProvenanceError(f"{node_path} not found (run `make keys`)")
    _refuse_loose_key(node_path)
    return authz.public_key_b64(authz.load_private_key(node_path).public_key())


def _dual_sign(vault: Path, record: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Attach the two signatures every peer-written block carries.

    User key = consent / attribution, node key = attestation this node recorded
    it. Separate keys, separate meanings, exactly as an approval block carries —
    a `grant_use` block is not a new signature scheme, it is the same dual
    control over a different event.
    """
    authz = _load_authz()
    if not user_is_filled(record):
        raise ProvenanceError("user record is unfilled; run `make user-init` first")
    user_path = _user_key_path(vault)
    node_path = _node_key_path(vault)
    for path, hint in ((user_path, "run `make user-init`"), (node_path, "run `make keys`")):
        if not path.is_file():
            raise ProvenanceError(f"{path} not found ({hint})")
        _refuse_loose_key(path)
    user_key = authz.load_private_key(user_path)
    node_key = authz.load_private_key(node_path)
    message = approval_signable(data)
    return {
        "user": authz.sign_bytes(user_key, message),
        "node": authz.sign_bytes(node_key, message),
    }


def dual_sign(vault: Path, record: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Public entry point for the one dual-control signing path.

    A proposal/review/decision carries the same two signatures an approval does
    (shared/sparknet-proposal.py consumes this), so the envelope is defined once.
    """
    return _dual_sign(vault, record, data)


def node_id(vault: Path) -> str:
    """This vault's node id, 'unknown' when manifests/node-identity.json is absent."""
    return _node_id(vault)


def node_public_b64(vault: Path) -> str:
    """This vault's node identity public key, inline for a self-contained record."""
    return _node_public_b64(vault)


def now():
    """The one clock (UTC) so a proposal record and an approval share a format."""
    return _now()


def iso(moment) -> str:
    """The one timestamp formatter (`...+00:00` → `...Z`)."""
    return _iso(moment)


def build_approval_data(
    *,
    vault: Path,
    question: str,
    decision: str,
    note_refs: list[str],
    agent: str,
    model: str,
    record: dict[str, Any],
    clock=None,
) -> dict[str, Any]:
    """Assemble an approval payload and sign it with the user key and the node key.

    Two keys, two meanings: the user's signature is consent, the node's is
    attestation that this node recorded it, both over the payload. Neither alone
    places a block: `append_block` adds a *second*, independent node signature
    over the whole block header, and `hash` binds that signed block into the
    chain.
    """
    if decision not in ("approved", "rejected", "clarified"):
        raise ProvenanceError(f"decision must be approved|rejected|clarified, got {decision!r}")
    moment = (clock or _now)()
    try:
        blocks = load_ledger(vault / "blockchain" / "ledger.json").get("blocks", [])
    except ProvenanceError:
        blocks = []
    approvals = sum(
        1 for block in blocks if isinstance(block, dict) and (block.get("data") or {}).get("event") == "approval"
    )
    data: dict[str, Any] = {
        "event": "approval",
        "approval_id": f"APL-{moment.date().isoformat()}-{approvals + 1:03d}",
        "owner_id": str(record.get("owner_id")),
        "owner_node": _node_id(vault),
        "question": question,
        "decision": decision,
        "agent": agent,
        "model": model,
        "note_refs": sorted(note_refs),
        "node_pubkey_b64": _node_public_b64(vault),
        "recorded_at": _iso(moment),
    }
    data["signatures"] = _dual_sign(vault, record, data)
    return data


def _adopt_vault_owner(path: Path, vault: Path) -> None:
    """A root-run service writing into a user's vault must not leave root-owned files."""
    try:
        st = vault.stat()
        os.chown(path, st.st_uid, st.st_gid)
    except OSError:
        pass


def append_block(vault: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Append one signed, hash-chained block to this vault's ledger.

    The block header — every field except `hash` and `signature` — is signed by
    this node's identity key, and the node's public key travels inline in the
    block so an offline verifier needs no local key material. `data.signatures`
    (for approvals, `grant_use` and `inbox_acceptance`) still bind the record
    separately; the header signature binds the block's position and payload, so a
    deleted, reordered or edited block is detectable.

    The whole read-modify-write runs under an exclusive lock on a sibling lock
    file, and the replacement uses a unique temp file. Without both, two
    appenders can read the same head and each report success while only one block
    reaches disk — a lost `grant_use` block is a replayable grant.
    """
    ledger_path = vault / "blockchain" / "ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ledger_path.with_name(ledger_path.name + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            ledger = (
                load_ledger(ledger_path)
                if ledger_path.is_file()
                else {"version": "2.0", "genesis_hash": "", "blocks": []}
            )
            blocks = ledger.setdefault("blocks", [])
            previous = blocks[-1]["hash"] if blocks else str(ledger.get("genesis_hash", ""))
            index = len(blocks)
            authz = _load_authz()
            node_path = _node_key_path(vault)
            if not node_path.is_file():
                raise ProvenanceError(f"{node_path} not found (run `make keys`)")
            _refuse_loose_key(node_path)
            node_key = authz.load_private_key(node_path)
            block: dict[str, Any] = {
                "block_id": f"{index:08d}",
                "prev_hash": previous,
                "timestamp": _iso(_now()),
                "node_pubkey_b64": _node_public_b64(vault),
                "data": data,
            }
            block["signature"] = authz.sign_bytes(node_key, block_header_signable(block))
            block["hash"] = block_hash(block)
            blocks.append(block)

            fd, temp_name = tempfile.mkstemp(dir=str(ledger_path.parent), prefix=f".{ledger_path.name}.", suffix=".tmp")
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w") as handle:
                    handle.write(json.dumps(ledger, indent=2) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, ledger_path)
            except Exception:
                with contextlib.suppress(OSError):
                    os.unlink(temp_name)
                raise
            _adopt_vault_owner(ledger_path, vault)
            _adopt_vault_owner(lock_path, vault)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    ok, detail = verify_chain(ledger)
    if not ok:
        raise ProvenanceError(f"appended a block that does not verify: {detail}")
    return block


def verify_approval_blocks(vault: Path, record: dict[str, Any] | None = None) -> list[str]:
    """Every peer-written block: dual signatures, block signature, note_refs on disk."""
    problems: list[str] = []
    ledger_path = vault / "blockchain" / "ledger.json"
    if not ledger_path.is_file():
        return problems
    ledger = load_ledger(ledger_path)
    ok, detail = verify_chain(ledger)
    if not ok:
        problems.append(f"chain: {detail}")
    authz = _load_authz()
    try:
        record = record if record is not None else parse_user_record(vault)
        user_pub = authz.public_key_from_b64(user_public_b64(record))
    except ProvenanceError as exc:
        return [*problems, f"user record: {exc}"]

    peer_events = set(contract()["approval"]["event_vocabulary"]["peer"])
    for block in ledger.get("blocks", []):
        if not isinstance(block, dict):
            continue
        data = block.get("data") or {}
        if data.get("event") not in peer_events:
            continue
        if data.get("event") == "checkpoint":
            # Header-signed only: there is no data.signatures to reproduce, and
            # verify_chain above already checked the header signature and the
            # re-hash. The checkpoint payload is a statement about the chain,
            # not a record of consent.
            continue
        approval_id = data.get("approval_id") or data.get("event")
        signatures = data.get("signatures")
        if not isinstance(signatures, dict):
            problems.append(f"{approval_id}: no signatures block")
            continue
        message = approval_signable(data)
        if not authz.verify_signature(user_pub, str(signatures.get("user") or ""), message):
            problems.append(f"{approval_id}: user consent signature does not verify")
        try:
            node_pub = authz.public_key_from_b64(str(data.get("node_pubkey_b64") or ""))
        except Exception as exc:
            problems.append(f"{approval_id}: node_pubkey_b64 unusable: {exc}")
            continue
        if not authz.verify_signature(node_pub, str(signatures.get("node") or ""), message):
            problems.append(f"{approval_id}: node countersignature does not verify")
        # The block-level signature now covers the whole header and is checked by
        # verify_chain above; it is no longer a restatement of the node
        # countersignature. The record's own dual signatures are still checked
        # here so a block stays self-contained if copied out of the ledger.
        for ref in data.get("note_refs", []):
            if not (vault / str(ref)).is_file():
                problems.append(f"{approval_id}: note_refs points at a missing note: {ref}")
    return problems


def approval_ids_in_ledger(vault: Path) -> set[str]:
    path = vault / "blockchain" / "ledger.json"
    if not path.is_file():
        return set()
    ledger = load_ledger(path)
    return {
        str(block["data"].get("approval_id"))
        for block in ledger.get("blocks", [])
        if isinstance(block, dict) and isinstance(block.get("data"), dict) and block["data"].get("approval_id")
    }


def build_checkpoint_data(*, vault: Path, clock=None) -> dict[str, Any]:
    """A checkpoint payload over this ledger's current head.

    Three numbers name the head: ``size`` (the number of blocks in the chain),
    ``head_hash`` (the newest block's ``hash``) and ``root`` (the RFC 6962
    Merkle root, via ``shared/sparknet-merkle.py``, of every block hash in the
    chain). The tree is the ledger *before* this checkpoint is appended, so
    ``size`` is what the root covers, and nothing is self-referential: the
    block hashes its own payload only through the next snapshot, never its own
    root.
    """
    ledger_path = vault / "blockchain" / "ledger.json"
    if not ledger_path.is_file():
        raise ProvenanceError("cannot checkpoint a ledger that does not exist")
    ledger = load_ledger(ledger_path)
    blocks = ledger.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ProvenanceError("cannot checkpoint an empty chain: append a block first")
    moment = (clock or _now)()
    hashes = [str(block.get("hash")) for block in blocks]
    return {
        "event": "checkpoint",
        "size": len(hashes),
        "head_hash": hashes[-1],
        "root": _load_merkle().merkle_root(hashes),
        "node_pubkey_b64": _node_public_b64(vault),
        "recorded_at": _iso(moment),
    }


def checkpoint(vault: Path, clock=None) -> dict[str, Any]:
    """Append a signed checkpoint block to this vault's ledger.

    Signed by the node key like every block — the header signature is the whole
    commitment. Once appended, the checkpoint block becomes a leaf of the next
    checkpoint's tree, which is why ``size`` counts the chain it snapshots, not
    the chain it joins.
    """
    return append_block(vault, build_checkpoint_data(vault=vault, clock=clock))


def _anchored_checkpoints_path(vault: Path) -> Path:
    """This node's view of other nodes' heads: runtime state, never the vault."""
    return _state_dir(vault) / "anchored-checkpoints.json"


def load_anchored(vault: Path) -> dict[str, dict[str, Any]]:
    """The per-node anchored heads, keyed by the signing node's public key.

    A corrupt store is a refusal, not a reset: silently forgetting the anchors
    would quietly convert every incoming rollback or fork into "first anchor".
    """
    path = _anchored_checkpoints_path(vault)
    if not path.is_file():
        return {}
    try:
        store = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(store, dict):
        raise ProvenanceError(f"{path} is not a mapping of anchored nodes")
    return {k: v for k, v in store.items() if isinstance(v, dict)}


def save_anchored(vault: Path, store: dict[str, dict[str, Any]]) -> None:
    path = _anchored_checkpoints_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n")
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _checkpoint_block_problems(block: Any) -> str | None:
    """The block-level checks every checkpoint must pass before any anchor.

    Returns a refusal reason, or None when the block itself is sound: it is a
    well-formed checkpoint whose header signature verifies against its own
    ``node_pubkey_b64`` and whose ``hash`` re-hashes when present.
    """
    if not isinstance(block, dict):
        return "checkpoint is not an object"
    data = block.get("data")
    if not isinstance(data, dict) or data.get("event") != "checkpoint":
        return "not a checkpoint block (data.event != 'checkpoint')"
    for field in ("size", "head_hash", "root"):
        if field not in data:
            return f"checkpoint data missing {field!r}"
    size = data["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        return "checkpoint size must be a positive integer"
    for field in ("head_hash", "root"):
        value = data[field]
        if not isinstance(value, str) or len(value) != 64:
            return f"checkpoint {field} must be a 64-hex hash"
        try:
            bytes.fromhex(value)
        except ValueError:
            return f"checkpoint {field} must be a 64-hex hash"
    authz = _load_authz()
    try:
        node_pub = authz.public_key_from_b64(str(block.get("node_pubkey_b64") or ""))
    except Exception as exc:
        return f"unusable node_pubkey_b64: {exc}"
    if not authz.verify_signature(node_pub, str(block.get("signature") or ""), block_header_signable(block)):
        return "checkpoint header signature does not verify"
    if "hash" in block and block["hash"] != block_hash(block):
        return "checkpoint does not re-hash to its recorded hash"
    return None


def verify_checkpoint(
    block: dict[str, Any],
    anchored: dict[str, Any] | None = None,
    proof: list[str] | None = None,
) -> tuple[bool, str]:
    """Does this signed checkpoint advance what this node already anchors?

    Checks, in order, fail-closed:

    - the block itself: a well-formed checkpoint whose header signature
      verifies (the "signed like every block" commitment) and that re-hashes;
    - against a prior anchor for the same node: a size *below* the anchored
      size is a rollback and refused; the same size must carry the same root
      (a different root is a fork and refused); a size *above* must carry an
      RFC 6962 consistency proof — ``sparknet-merkle.verify_consistency`` from
      the anchored root to the new root — and an advanced head.

    A checkpoint from an unknown node (``anchored`` is None) is accepted on
    the signature alone: the first anchor establishes the baseline every later
    one is measured against.
    """
    err = _checkpoint_block_problems(block)
    if err:
        return False, err
    data = block["data"]
    size = int(data["size"])
    root = data["root"]
    if anchored is None:
        return True, "first anchor for this node"
    anchored_size = int(anchored["size"])
    if size < anchored_size:
        return False, (
            f"rollback: this node already anchors size {anchored_size}, but the incoming checkpoint claims {size}"
        )
    if size == anchored_size:
        if root == anchored.get("root"):
            return True, "same head re-anchored (no change)"
        return False, (
            "fork: same size but a different root — this node already anchors "
            f"root {anchored['root'][:16]}... for size {size}"
        )
    if not proof:
        return False, (
            "a growing checkpoint needs an RFC 6962 consistency proof from the anchored root to the new root"
        )
    if data["head_hash"] == anchored.get("head_hash"):
        return False, "growth claimed, but the head did not advance"
    if not _load_merkle().verify_consistency(anchored_size, size, anchored.get("root"), root, proof):
        return False, ("consistency: the new root does not prove a pure extension of the anchored root")
    return True, f"anchored growth from size {anchored_size} to {size}"


def anchor(
    vault: Path,
    block: dict[str, Any],
    proof: list[str] | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Verify a signed checkpoint from another node and record the high-water mark.

    The store is keyed by the checkpoint's ``node_pubkey_b64`` — the node that
    signed it — so each node's head is anchored independently. A refused
    checkpoint changes nothing.
    """
    store = load_anchored(vault)
    if not isinstance(block, dict) or not isinstance(block.get("data"), dict):
        return False, "malformed checkpoint block", None
    header_key = str(block.get("node_pubkey_b64") or "")
    data_key = str(block["data"].get("node_pubkey_b64") or "")
    if not header_key:
        return False, "no node_pubkey_b64 in checkpoint header", None
    if data_key != header_key:
        return False, "checkpoint data names a different node key than its signed header", None
    key = header_key
    anchored = store.get(key)
    ok, detail = verify_checkpoint(block, anchored=anchored, proof=proof)
    if not ok:
        return ok, detail, anchored
    data = block["data"]
    record = {
        "size": int(data["size"]),
        "head_hash": data["head_hash"],
        "root": data["root"],
        "node_pubkey_b64": key,
        "recorded_at": data.get("recorded_at", ""),
        "last_anchored_at": _iso(_now()),
    }
    store[key] = record
    save_anchored(vault, store)
    return True, detail, record


def build_inbox_acceptance(
    vault: Path,
    *,
    item: str,
    source: str,
    decision: str,
    reviewer: str = "",
    sanitized: bool = False,
    sender: str = "",
    note_refs: list[str] | None = None,
    record: dict[str, Any],
    clock=None,
) -> dict[str, Any]:
    """Assemble an `inbox_acceptance` block, and enforce the dispatch policy.

    The contract already stated this event (`tracking-schema.json`
    `inbox_dispatch`, `provenance-protocol.md`), and both roles' agent charters
    told agents that acceptance *is* recorded as an `inbox_acceptance` block — but
    nothing could produce one. A charter asserting a record that no code writes is
    worse than silence: an agent reading it trusts an audit trail that does not
    exist. This is the builder that makes the claim true.

    Dual-signed over one payload, like an approval and a `grant_use`: the user
    consents and the node countersigns, so neither half can be produced alone.

    The policy is enforced here rather than left to callers, because the callers
    are agents and the point of the policy is to constrain them:

    * the item must live under `01_Inbox/` — that directory is read-only for agents
      until accepted, so an acceptance recorded against a path outside it would be
      laundering something that never went through intake;
    * an `email` source must name a sender on `00_System/user.md`'s
      `authorised_senders`, and an empty list refuses everything, which is the
      fail-closed default the record ships with;
    * accepting from an untrusted source requires a named reviewer, since the
      contract's rule is that such an item is reviewed and sanitized before
      anything downstream reads it.

    A rejection is always recordable: the trail of what was refused is as much the
    point as the trail of what was let in.
    """
    if source not in INBOX_SOURCES:
        raise ProvenanceError(f"source must be one of {INBOX_SOURCES}, got {source!r}")
    if decision not in ("accepted", "rejected"):
        raise ProvenanceError(f"decision must be accepted|rejected, got {decision!r}")
    if not isinstance(item, str) or not item:
        raise ProvenanceError("item is required: the vault-relative path of the inbox item")
    parts = Path(item).parts
    if not parts or parts[0] != "01_Inbox":
        raise ProvenanceError(f"item must be under 01_Inbox/, got {item!r}")
    if ".." in parts:
        raise ProvenanceError(f"item must not traverse out of the vault: {item!r}")

    if source == "email":
        allowed = list(parse_user_record(vault).get("authorised_senders") or [])
        if not sender:
            raise ProvenanceError("an email source must name its sender")
        if sender not in allowed:
            raise ProvenanceError(
                f"sender {sender!r} is not on 00_System/user.md authorised_senders; "
                "the inbox policy fails closed, so nothing may push work onto this node"
            )

    if decision == "accepted" and source in INBOX_UNTRUSTED_SOURCES and not reviewer:
        raise ProvenanceError(
            f"accepting from {source} requires a reviewer: untrusted material is reviewed "
            "and sanitized before anything downstream reads it"
        )

    moment = (clock or _now)()
    try:
        blocks = load_ledger(vault / "blockchain" / "ledger.json").get("blocks", [])
    except ProvenanceError:
        blocks = []
    prior = sum(
        1
        for block in blocks
        if isinstance(block, dict) and (block.get("data") or {}).get("event") == "inbox_acceptance"
    )
    data: dict[str, Any] = {
        "event": "inbox_acceptance",
        "acceptance_id": f"INB-{moment.date().isoformat()}-{prior + 1:03d}",
        "item": str(item),
        "source": source,
        "sender": str(sender),
        "decision": decision,
        "reviewer": str(reviewer),
        "sanitized": bool(sanitized),
        # The validity state the note carries afterwards. `sanitized` is the
        # contract's own word for material that ingressed from an untrusted source
        # and was reviewed before use; recording it here is what makes the state on
        # the note checkable against the trail that justified it.
        "validity": "sanitized" if sanitized else ("signed" if decision == "accepted" else "unsigned"),
        "note_refs": sorted(note_refs or []),
        "owner_id": str(record.get("owner_id")),
        "owner_node": _node_id(vault),
        "node_pubkey_b64": _node_public_b64(vault),
        "recorded_at": _iso(moment),
    }
    data["signatures"] = _dual_sign(vault, record, data)
    return data


def note_paths(vault: Path) -> list[Path]:
    """Every markdown note in 01_Inbox..07_Archives, per the contract's layout."""
    dirs = sorted(name for name in contract()["layout"]["dirs"] if name >= "01_" and (vault / name).is_dir())
    skip = {"__pycache__", ".git", ".state", ".cache", "_staging"}
    paths: list[Path] = []
    for name in dirs:
        base = vault / name
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            directory = Path(dirpath)
            dirnames[:] = sorted(child for child in dirnames if not (directory / child).is_symlink())
            for filename in sorted(filenames):
                if not filename.endswith(".md"):
                    continue
                path = directory / filename
                if path.is_symlink() or skip & set(path.parts) or path.name == ".gitkeep":
                    continue
                paths.append(path)
    return paths


def verify_vault(vault: Path, strict: bool = False) -> tuple[int, str]:
    """The whole state machine: notes, the ledger, and approvals↔notes both ways.

    Exit codes follow the contract: 1 is a hard failure (invalid, tamper, lock
    mismatch), 2 is stale:content awaiting a re-sign, 0 is clean. `--strict`
    promotes the soft failure to hard, which is what a pre-commit hook wants.
    """
    lines: list[str] = [f"provenance-verify: {vault}"]
    hard = False
    soft = False

    try:
        record = parse_user_record(vault)
    except ProvenanceError as exc:
        return 1, f"provenance-verify: {exc}"

    if user_is_filled(record):
        lock_ok = _verify_lock(vault, user_record_path(vault))
        lines.append(f"user record: filled, {record.get('owner_id')}, {('lock ok' if lock_ok else 'LOCK MISMATCH')}")
        if lock_ok is False:
            hard = True
    else:
        lines.append("user record: UNFILLED — every signature check below will fail")
        hard = True

    for problem in check_user_record(vault):
        lines.append(f"  ✗ {problem}")
        hard = True

    counts = {"valid": 0, "stale:metadata": 0, "stale:content": 0, "invalid": 0, "pending": 0}
    paths = note_paths(vault)
    for path in paths:
        outcome, detail = verify_note(path, record, vault)
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome not in ("valid", "pending"):
            lines.append(f"  {outcome}: {path.relative_to(vault)} — {detail}")
        if outcome == "invalid":
            hard = True
        elif outcome == "stale:content":
            hard = hard or strict
            soft = True
    lines.append(f"notes: {len(paths)} checked — " + ", ".join(f"{counts[k]} {k}" for k in counts))

    ledger_path = vault / "blockchain" / "ledger.json"
    if ledger_path.is_file():
        ledger = load_ledger(ledger_path)
        ok, detail = verify_chain(ledger)
        lines.append(f"ledger: {detail}")
        if not ok:
            hard = True
        for problem in verify_approval_blocks(vault, record):
            lines.append(f"  ✗ {problem}")
            hard = True
    else:
        lines.append("ledger: absent (no approvals recorded)")

    # Checked even when the ledger is absent: a note claiming an approval that
    # no ledger can produce is unverifiable either way, and silently passing it
    # because the file is missing is how a fabricated citation survives.
    known = approval_ids_in_ledger(vault) if ledger_path.is_file() else set()
    missing: set[str] = set()
    for path in paths:
        frontmatter = _safe_frontmatter(path)
        if frontmatter is None:
            continue
        tracking = frontmatter.get("tracking")
        if not isinstance(tracking, dict):
            continue
        for approval in tracking.get("approvals") or []:
            if str(approval) not in known:
                missing.add(str(approval))
    if missing:
        lines.append(f"  ✗ notes claim approvals that are not in the ledger: {sorted(missing)}")
        hard = True
    else:
        lines.append("approvals: every tracking.approvals[] id resolves to a ledger block")

    exit_code = 1 if hard else (2 if soft else 0)
    lines.append(f"result: {'ok' if exit_code == 0 else 'FAILED'} (exit {exit_code})")
    return exit_code, "\n".join(lines)


def _safe_frontmatter(path: Path) -> dict[str, Any] | None:
    try:
        return split_note(path.read_bytes())[0]
    except (ProvenanceError, OSError, UnicodeDecodeError):
        return None


__all__ = [
    "INBOX_SOURCES",
    "INBOX_UNTRUSTED_SOURCES",
    "_adopt_vault_owner",
    "_anchored_checkpoints_path",
    "_checkpoint_block_problems",
    "_dual_sign",
    "_node_public_b64",
    "_safe_frontmatter",
    "anchor",
    "append_block",
    "approval_ids_in_ledger",
    "approval_signable",
    "block_hash",
    "block_header_signable",
    "build_approval_data",
    "build_checkpoint_data",
    "build_inbox_acceptance",
    "checkpoint",
    "dual_sign",
    "iso",
    "load_anchored",
    "load_ledger",
    "node_id",
    "node_public_b64",
    "note_paths",
    "now",
    "save_anchored",
    "verify_approval_blocks",
    "verify_chain",
    "verify_checkpoint",
    "verify_vault",
]

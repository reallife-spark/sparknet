#!/usr/bin/env python3
"""Sparknet RFC 6962 Merkle transparency primitives.

This module is the integrity math the ledger checkpoint (``contracts/
provenance-protocol.md`` Arc A) and the conversation commitment (Arc B) are
built on: the RFC 6962 Merkle Tree Hash, inclusion proofs and consistency
proofs, plus a signed tree head for external anchoring.

The hashing and proof definitions are implemented **verbatim** from
RFC 6962 section 2.1.1-2.1.4 (the same definitions reappear in RFC 9162
section 2.1.1-2.1.4; RFC 9162 carries no sample vectors, RFC 6962 none either),
and the ``VECTORS`` block is the canonical published vector set from
``transparency-dev/merkle`` (``testonly/constants.go`` and
``testonly/reference_test.go``), reused by Chromium, ct-merkle and sigstore:
eight leaves whose roots for tree sizes 0..8 and the reference inclusion and
consistency proofs are all pinned below. A module that only agreed with
itself would prove nothing; the cross-implementation vectors are what make a
wrong split rule or a swapped hash order fail loudly in the test suite.

Verification implements the RFC 9162 verifier algorithms (2.1.3.2 and
2.1.4.2) statement by statement, so a proof that is not minimal — wrong
length, extra garbage, a crafted element — is rejected rather than
normalised. Generators are the RFC 6962 reference algorithms; they raise
``MerkleError`` on any argument a generator cannot honestly satisfy, and the
verifiers return ``False`` for the same class of input rather than raising,
because a verifier is often fed untrusted data.

Only one hash function and no signature primitive live here. The optional
tree-head signing helpers delegate to ``sparknet-authz.py`` (loaded by path,
like every other module), so the fabric keeps exactly one crypto
implementation — the same rule ``sparknet-provenance.py`` follows.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

DEFAULT_SHARED_DIR = Path(__file__).resolve().parent

#: Domain tag for a signed tree head. Versioned like the note domain: a future
#: change to the signable form cannot silently verify against old signatures.
TREE_HEAD_DOMAIN = b"sparknet-tree-head/1"

#: SHA-256 of the empty string — MTH({}) per RFC 6962 section 2.1.1. Exposed
#: by transparency-dev/merkle as ``EmptyRootHash`` with exactly this value.
EMPTY_TREE_ROOT = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

#: The canonical published RFC 6962 vectors (transparency-dev/merkle
#: ``testonly/constants.go``): eight leaf inputs as hex-encoded bytes. The
#: tree built from them is the one every cross-implementation proof vector
#: below is read against.
LEAF_INPUTS = [
    "",
    "00",
    "10",
    "2021",
    "3031",
    "40414243",
    "5051525354555657",
    "606162636465666768696a6b6c6d6e6f",
]

#: Roots of the trees built from the first ``size`` of LEAF_INPUTS, indexed by
#: size 0..8. Literals from transparency-dev/merkle ``RootHashes()``.
ROOT_VECTORS = {
    0: EMPTY_TREE_ROOT,
    1: "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    2: "fac54203e7cc696cf0dfcb42c92a1d9dbaf70ad9e621f4bd8d98662f00e3c125",
    3: "aeb6bcfe274b70a14fb067a5e5578264db0fa9b51af5e0ba159158f329e06e77",
    4: "d37ee418976dd95753c1c73862b9398fa2a2cf9b4ff0fdfe8b30cd95209614b7",
    5: "4e3bbb1f7b478dcfe71fb631631519a3bca12c9aefca1612bfce4c13a86264d4",
    6: "76e67dadbcdf1e10e1b74ddc608abd2f98dfb16fbce75277b5232a127f2087ef",
    7: "ddb89be403809e325750d3d263cd78929c2942b7942a34b77e122c9594a74c8c",
    8: "5dc9da79a70659a9ad559cb701ded9a2ab9d823aad2f4960cfe370eff4604328",
}

#: Reference inclusion proofs from ``reference_test.go`` (transparency-dev/
#: merkle), each ``(index, size) -> [proof node hex, ...]``. The proof is
#: right-to-left in the order the RFC's PATH definition yields it.
INCLUSION_VECTORS = {
    (0, 1): [],
    (0, 2): ["96a296d224f285c67bee93c30f8a309157f0daa35dc5b87e410b78630a09cfc7"],
    (1, 2): ["6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d"],
    (2, 3): ["fac54203e7cc696cf0dfcb42c92a1d9dbaf70ad9e621f4bd8d98662f00e3c125"],
    (1, 5): [
        "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
        "5f083f0a1a33ca076a95279832580db3e0ef4584bdff1f54c8a360f50de3031e",
        "bc1a0643b12e4d2d7c77918f44e0f4f79a838b6cf9ec5b5c283e1f4d88599e6b",
    ],
    (0, 8): [
        "96a296d224f285c67bee93c30f8a309157f0daa35dc5b87e410b78630a09cfc7",
        "5f083f0a1a33ca076a95279832580db3e0ef4584bdff1f54c8a360f50de3031e",
        "6b47aaf29ee3c2af9af889bc1fb9254dabd31177f16232dd6aab035ca39bf6e4",
    ],
    (5, 8): [
        "bc1a0643b12e4d2d7c77918f44e0f4f79a838b6cf9ec5b5c283e1f4d88599e6b",
        "ca854ea128ed050b41b35ffc1b87b8eb2bde461e9e3b5596ece6b9d5975a0ae0",
        "d37ee418976dd95753c1c73862b9398fa2a2cf9b4ff0fdfe8b30cd95209614b7",
    ],
}

#: Reference consistency proofs ``(first_size, second_size) -> proof``.
CONSISTENCY_VECTORS = {
    (1, 1): [],
    (1, 8): [
        "96a296d224f285c67bee93c30f8a309157f0daa35dc5b87e410b78630a09cfc7",
        "5f083f0a1a33ca076a95279832580db3e0ef4584bdff1f54c8a360f50de3031e",
        "6b47aaf29ee3c2af9af889bc1fb9254dabd31177f16232dd6aab035ca39bf6e4",
    ],
    (2, 5): [
        "5f083f0a1a33ca076a95279832580db3e0ef4584bdff1f54c8a360f50de3031e",
        "bc1a0643b12e4d2d7c77918f44e0f4f79a838b6cf9ec5b5c283e1f4d88599e6b",
    ],
    (6, 8): [
        "0ebc5d3437fbe2db158b9f126a1d118e308181031d0a949f8dededebc558ef6a",
        "ca854ea128ed050b41b35ffc1b87b8eb2bde461e9e3b5596ece6b9d5975a0ae0",
        "d37ee418976dd95753c1c73862b9398fa2a2cf9b4ff0fdfe8b30cd95209614b7",
    ],
}


class MerkleError(Exception):
    """A generator refusal with a message the caller can act on."""


def _load_authz() -> Any:
    """Load sparknet-authz.py by path, never by import.

    The same loader and the same reason as ``sparknet-provenance.py``: one
    crypto implementation in the fabric, and a test that fails if this module
    ever starts carrying its own. The resolve-and-cache mechanics live once in
    ``shared/sparknet_loader.py``.
    """
    return load_shared(
        "sparknet-authz.py",
        "sparknet_authz",
        error=MerkleError,
        message=(
            "cannot find shared/sparknet-authz.py; set SPARKNET_SHARED_DIR. "
            "There is exactly one signing implementation and this tool does not "
            "carry a fallback."
        ),
    )


def _hash(prefix: bytes, data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(prefix)
    digest.update(data)
    return digest.hexdigest()


def _coerce_leaf(entry: Any) -> bytes:
    """Normalise one leaf input to its content bytes.

    A ``bytes`` entry is used as-is (the empty tree's leaf is empty bytes).
    A ``str`` entry is decoded as hex — any even-length hex string, which is
    the spelling the published vectors use for short leaves ("00", "2021"…)
    and the natural spelling a 64-hex ledger block hash arrives in. A string
    that is not hex is refused rather than hashed as UTF-8 text: hashing a
    string's bytes and hashing its hex bytes yield two different trees, and
    guessing which one was meant would silently build the wrong root.
    """
    if isinstance(entry, bytes):
        return entry
    if isinstance(entry, str):
        compact = entry.strip()
        if len(compact) % 2 or any(c not in "0123456789abcdefABCDEF" for c in compact):
            raise MerkleError("a string leaf must be hex, even-length")
        return bytes.fromhex(compact)
    raise MerkleError("leaf entries must be bytes or a hex string")


def leaf_hash(entry: Any) -> str:
    """MTH({d}) = SHA-256(0x00 || d), RFC 6962 section 2.1.1."""
    return _hash(b"\x00", _coerce_leaf(entry))


def node_hash(left: str, right: str) -> str:
    """SHA-256(0x01 || left || right) over two 32-byte hashes."""
    return _hash(b"\x01", _expect_hash(left) + _expect_hash(right))


def _expect_hash(value: Any) -> bytes:
    if not isinstance(value, str) or len(value) != 64:
        raise MerkleError("a hash must be a 64-char hex string")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise MerkleError("a hash must be a 64-char hex string") from exc


def _expect_proof(proof: Any) -> list[str]:
    """A proof must be a sequence of 64-char hex hashes — anything else is a
    different shape and refused, which is what makes a wrong-length or crafted
    proof fail rather than verify."""
    if not isinstance(proof, (list, tuple)):
        raise MerkleError("proof must be a list of 32-byte hashes")
    out: list[str] = []
    for element in proof:
        _expect_hash(element)
        out.append(element.lower())
    return out


def down_to_power_of_two(n: int) -> int:
    """The largest power of two strictly below ``n``, RFC 6962 section 2.1.1.

    The split point k for an n-leaf tree. Requires n >= 2; the reference
    panics below that, so a generator must never call it there.
    """
    if n < 2:
        raise MerkleError("split point is only defined for trees of at least 2 leaves")
    return 1 << ((n - 1).bit_length() - 1)


def merkle_root(entries: Iterable[Any]) -> str:
    """MTH(D[n]) per RFC 6962 section 2.1.1: MTH({}) is the hash of the empty
    string, MTH({d}) is the leaf hash, and a larger tree splits at the largest
    power of two below n with MTH(D[0:k]) on the left."""
    leaves = [_coerce_leaf(e) for e in entries]
    n = len(leaves)
    if n == 0:
        return EMPTY_TREE_ROOT
    return _root_of(leaves, 0, n)


def _root_of(leaves: list[bytes], start: int, end: int) -> str:
    """MTH of leaves[start:end] without slicing — the generators hold the full
    tree and recurse on index ranges, so an ``inclusion_proof`` request does
    not copy the list per level."""
    size = end - start
    if size == 0:
        return EMPTY_TREE_ROOT
    if size == 1:
        return _hash(b"\x00", leaves[start])
    k = down_to_power_of_two(size)
    return node_hash(
        _root_of(leaves, start, start + k),
        _root_of(leaves, start + k, end),
    )


def inclusion_proof(index: int, entries: Iterable[Any]) -> list[str]:
    """PATH(m, D[n]) for leaf ``index`` in the tree of all ``entries``.

    Raises ``MerkleError`` for an out-of-range index or an empty tree; a
    single-leaf tree has an empty proof by definition (the leaf is the root).
    """
    leaves = [_coerce_leaf(e) for e in entries]
    n = len(leaves)
    if index < 0 or index >= n:
        raise MerkleError(f"index {index} is out of range for a {n}-leaf tree")
    if n == 1:
        return []
    return _path_of(leaves, index, 0, n)


def _path_of(leaves: list[bytes], index: int, start: int, end: int) -> list[str]:
    size = end - start
    if size == 1:
        return []
    k = down_to_power_of_two(size)
    mid = start + k
    if index < mid:
        return [*_path_of(leaves, index, start, mid), _root_of(leaves, mid, end)]
    return [*_path_of(leaves, index, mid, end), _root_of(leaves, start, mid)]


def verify_inclusion(entry: Any, index: int, size: int, proof: Any, root: Any) -> bool:
    """RFC 9162 section 2.1.3.2 verbatim: does ``entry`` sit at ``index`` in
    the tree whose root is ``root``?

    Returns ``False`` — never raises — for anything an honest tree would not
    produce: an index at or above ``size``, a non-hex or wrong-length proof
    element, or a proof that does not reduce to the root.
    """
    try:
        leaf = _hash(b"\x00", _coerce_leaf(entry))
        elements = _expect_proof(proof)
        root_hex = _expect_hash(root).hex()
    except MerkleError:
        return False
    if index < 0 or index >= size or size < 1:
        return False
    fn = index
    sn = size - 1
    r = leaf
    for p in elements:
        if sn == 0:
            return False
        if (fn & 1) or fn == sn:
            r = node_hash(p, r)
            if not (fn & 1):
                while not (fn & 1) and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            r = node_hash(r, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root_hex


def consistency_proof(first_size: int, entries: Iterable[Any]) -> list[str]:
    """PROOF(m, D[n]) = SUBPROOF(m, D[n], true), RFC 6962 section 2.1.2.

    Proves the tree of the first ``first_size`` leaves is a prefix of the tree
    of all ``entries``. Raises ``MerkleError`` for ``first_size`` outside
    1..len(entries); equal sizes yield the empty proof.
    """
    leaves = [_coerce_leaf(e) for e in entries]
    n = len(leaves)
    if n == 0:
        raise MerkleError("a consistency proof needs a non-empty tree")
    if first_size < 1 or first_size > n:
        raise MerkleError(f"first_size {first_size} is out of range for a {n}-leaf tree")
    if first_size == n:
        return []
    return _subproof_of(leaves, first_size, 0, n, True)


def _subproof_of(leaves: list[bytes], m: int, start: int, end: int, complete: bool) -> list[str]:
    size = end - start
    if m == size:
        if complete:
            return []
        return [_root_of(leaves, start, end)]
    k = down_to_power_of_two(size)
    mid = start + k
    if m <= k:
        return [*_subproof_of(leaves, m, start, mid, complete), _root_of(leaves, mid, end)]
    return [*_subproof_of(leaves, m - k, mid, end, False), _root_of(leaves, start, mid)]


def verify_consistency(first_size: int, second_size: int, first_root: Any, second_root: Any, proof: Any) -> bool:
    """RFC 9162 section 2.1.4.2 verbatim: is the tree of ``first_size`` leaves
    a prefix of the tree of ``second_size`` leaves?

    Returns ``False`` for an empty proof where one is required, malformed
    elements, out-of-range sizes, equal sizes with unequal roots, or a proof
    that reduces to mismatched roots.
    """
    try:
        fr_hex = _expect_hash(first_root).hex()
        sr_hex = _expect_hash(second_root).hex()
        elements = _expect_proof(proof)
    except MerkleError:
        return False
    if first_size < 1 or first_size > second_size:
        return False
    if first_size == second_size:
        return not elements and fr_hex == sr_hex
    if not elements:
        return False
    # Step 2: an exact-power-of-two first tree's own root is the proof's seed.
    if first_size == 1 << ((first_size - 1).bit_length()):
        elements = [fr_hex, *elements]
    fn = first_size - 1
    sn = second_size - 1
    # Step 4: shift the frame up until fn is even.
    while (fn & 1) and fn != 0:
        fn >>= 1
        sn >>= 1
    fr = elements[0]
    sr = elements[0]
    for c in elements[1:]:
        if sn == 0:
            return False
        if (fn & 1) or fn == sn:
            fr = node_hash(c, fr)
            sr = node_hash(c, sr)
            if not (fn & 1):
                while not (fn & 1) and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            sr = node_hash(sr, c)
        fn >>= 1
        sn >>= 1
    return fr == fr_hex and sr == sr_hex and sn == 0


# --- signed tree head ---------------------------------------------------------


def tree_head_signable(size: int, root: str) -> bytes:
    """The canonical signable form of a tree head: the domain tag, the size and
    the root, hash-then-sign like the ledger's header signature. The domain tag
    keeps a tree-head signature from ever verifying against some other payload
    that happens to be 40 bytes of numbers."""
    _expect_hash(root)
    return TREE_HEAD_DOMAIN + json.dumps({"size": size, "root": root}, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sign_tree_head(private_key: Any, node_pubkey_b64: str, size: int, root: str) -> dict[str, Any]:
    """A signed tree head: ``{"size", "root", "node_pubkey_b64", "signature"}``.

    Delegates to sparknet-authz (``sign_bytes``) so this module carries no
    Ed25519 of its own. ``node_pubkey_b64`` is recorded next to the signature
    exactly like a ledger block, so a verifier knows which key to check against
    an anchored head.
    """
    authz = _load_authz()
    signature = authz.sign_bytes(private_key, tree_head_signable(size, root))
    return {
        "size": size,
        "root": root,
        "node_pubkey_b64": node_pubkey_b64,
        "signature": signature,
    }


def verify_tree_head(public_key_b64: str, tree_head: dict[str, Any]) -> bool:
    """Verify a signed tree head against the public key it names. Returns
    ``False`` for malformed heads and bad signatures; never raises."""
    try:
        size = int(tree_head["size"])
        root = tree_head["root"]
        node_pubkey_b64 = tree_head["node_pubkey_b64"]
        signature = tree_head["signature"]
        _expect_hash(root)
    except (KeyError, TypeError, ValueError, MerkleError):
        return False
    if isinstance(size, bool) or size < 0 or not isinstance(node_pubkey_b64, str) or not isinstance(signature, str):
        return False
    authz = _load_authz()
    try:
        public_key = authz.public_key_from_b64(public_key_b64)
    except Exception:
        return False
    try:
        return authz.verify_signature(public_key, signature, tree_head_signable(size, root))
    except Exception:
        return False

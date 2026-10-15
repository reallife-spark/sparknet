"""RFC 6962 Merkle primitive tests (Step 32, Arc C).

Pins ``shared/sparknet-merkle.py`` to the published transparency-dev/merkle
vectors so the module is not merely self-consistent, then walks every proof
accept/refuse leg the log-verifier corpus names.

Vector provenance:
* ``testonly/constants.go`` — LeafInputs, NodeHashes, RootHashes (hex).
* ``testonly/reference_test.go`` — reference inclusion + consistency proofs.
* ``testdata/inclusion/3/*.json`` and ``testdata/consistency/2/*.json`` —
  the negative legs (wrong-root, modified-proof, preceding/trailing garbage,
  size mutation), whose ``wantValid``/``wantErr`` the verifiers must match.
* RFC 9162 section 2.1.5 — the worked 7-leaf example tree.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MERKLE_PATH = REPO_ROOT / "shared" / "sparknet-merkle.py"

#: The published leaf inputs, as raw bytes.
LEAVES = [
    bytes.fromhex(h)
    for h in (
        "",
        "00",
        "10",
        "2021",
        "3031",
        "40414243",
        "5051525354555657",
        "606162636465666768696a6b6c6d6e6f",
    )
]


@pytest.fixture(scope="module")
def mk() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sparknet_merkle_under_test", MERKLE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


class TestHashing:
    def test_empty_tree_root_is_sha256_of_empty_string(self, mk: ModuleType) -> None:
        assert mk.EMPTY_TREE_ROOT == mk.merkle_root([])
        assert mk.merkle_root([]) == mk.merkle_root(())
        assert len(mk.merkle_root([])) == 64

    def test_published_roots_for_sizes_0_through_8(self, mk: ModuleType) -> None:
        # transparency-dev/merkle RootHashes(), indexed by tree size.
        for size, expected in mk.ROOT_VECTORS.items():
            entries = LEAVES[:size] if size else []
            assert mk.merkle_root(entries) == expected, f"size {size}"

    def test_published_leaf_hashes(self, mk: ModuleType) -> None:
        # transparency-dev/merkle NodeHashes()[0]: one leaf hash per input.
        expected = [
            "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
            "96a296d224f285c67bee93c30f8a309157f0daa35dc5b87e410b78630a09cfc7",
            "0298d122906dcfc10892cb53a73992fc5b9f493ea4c9badb27b791b4127a7fe7",
            "07506a85fd9dd2f120eb694f86011e5bb4662e5c415a62917033d4a9624487e7",
            "bc1a0643b12e4d2d7c77918f44e0f4f79a838b6cf9ec5b5c283e1f4d88599e6b",
            "4271a26be0d8a84f0bd54c8c302e7cb3a3b5d1fa6780a40bcce2873477dab658",
            "b08693ec2e721597130641e8211e7eedccb4c26413963eee6c1e2ed16ffb1a5f",
            "46f6ffadd3d06a09ff3c5860d2755c8b9819db7df44251788c7d8e3180de8eb1",
        ]
        for index, leaf in enumerate(LEAVES):
            assert mk.leaf_hash(leaf) == expected[index], f"leaf {index}"

    def test_published_interior_hashes(self, mk: ModuleType) -> None:
        # NodeHashes()[1]: the four level-1 nodes of the 8-leaf tree.
        pairs = [
            (
                "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
                "96a296d224f285c67bee93c30f8a309157f0daa35dc5b87e410b78630a09cfc7",
                "fac54203e7cc696cf0dfcb42c92a1d9dbaf70ad9e621f4bd8d98662f00e3c125",
            ),
            (
                "0298d122906dcfc10892cb53a73992fc5b9f493ea4c9badb27b791b4127a7fe7",
                "07506a85fd9dd2f120eb694f86011e5bb4662e5c415a62917033d4a9624487e7",
                "5f083f0a1a33ca076a95279832580db3e0ef4584bdff1f54c8a360f50de3031e",
            ),
            (
                "bc1a0643b12e4d2d7c77918f44e0f4f79a838b6cf9ec5b5c283e1f4d88599e6b",
                "4271a26be0d8a84f0bd54c8c302e7cb3a3b5d1fa6780a40bcce2873477dab658",
                "0ebc5d3437fbe2db158b9f126a1d118e308181031d0a949f8dededebc558ef6a",
            ),
            (
                "b08693ec2e721597130641e8211e7eedccb4c26413963eee6c1e2ed16ffb1a5f",
                "46f6ffadd3d06a09ff3c5860d2755c8b9819db7df44251788c7d8e3180de8eb1",
                "ca854ea128ed050b41b35ffc1b87b8eb2bde461e9e3b5596ece6b9d5975a0ae0",
            ),
        ]
        for left, right, joined in pairs:
            assert mk.node_hash(left, right) == joined

    def test_hex_string_leaves_are_their_decoded_bytes(self, mk: ModuleType) -> None:
        # A hex-string leaf means the bytes those hex digits name — the tree
        # of block hashes uses this, and it must equal the bytes tree.
        assert mk.merkle_root(["00", "10"]) == mk.merkle_root([b"\x00", b"\x10"])
        assert mk.merkle_root(["00"]) == mk.leaf_hash(b"\x00")
        assert mk.leaf_hash("00") == mk.leaf_hash(b"\x00")


class TestInclusionVectors:
    def test_published_generation(self, mk: ModuleType) -> None:
        # reference_test.go: PATH(m, D[n]) for the published (index, size) set.
        for (index, size), expected in mk.INCLUSION_VECTORS.items():
            assert mk.inclusion_proof(index, LEAVES[:size]) == expected, f"({index}, {size})"

    def test_published_verification(self, mk: ModuleType) -> None:
        for index, size in mk.INCLUSION_VECTORS:
            proof = mk.INCLUSION_VECTORS[(index, size)]
            assert mk.verify_inclusion(LEAVES[index], index, size, proof, mk.ROOT_VECTORS[size]), f"({index}, {size})"

    def test_every_leaf_of_the_8_leaf_tree(self, mk: ModuleType) -> None:
        # Generate-and-verify agreement across the full tree, pinned only by
        # the published ROOT_VECTORS literal for size 8.
        root = mk.ROOT_VECTORS[8]
        entries = LEAVES[:8]
        for index in range(8):
            proof = mk.inclusion_proof(index, entries)
            assert mk.verify_inclusion(entries[index], index, 8, proof, root), f"leaf {index}"
        assert len(mk.inclusion_proof(0, entries)) == 3  # ceil(log2(8)) well-formed

    def test_rfc_9162_seven_leaf_example(self, mk: ModuleType) -> None:
        # RFC 9162 section 2.1.5: inclusion for d0=[b,h,l], d3=[c,g,l],
        # d4=[f,j,k], d6=[i,k]. The example tree IS LEAVES[:7].
        b = "96a296d224f285c67bee93c30f8a309157f0daa35dc5b87e410b78630a09cfc7"
        c = "0298d122906dcfc10892cb53a73992fc5b9f493ea4c9badb27b791b4127a7fe7"
        f = "4271a26be0d8a84f0bd54c8c302e7cb3a3b5d1fa6780a40bcce2873477dab658"
        g = "fac54203e7cc696cf0dfcb42c92a1d9dbaf70ad9e621f4bd8d98662f00e3c125"
        h = "5f083f0a1a33ca076a95279832580db3e0ef4584bdff1f54c8a360f50de3031e"
        i = "0ebc5d3437fbe2db158b9f126a1d118e308181031d0a949f8dededebc558ef6a"
        j = "b08693ec2e721597130641e8211e7eedccb4c26413963eee6c1e2ed16ffb1a5f"
        k = "d37ee418976dd95753c1c73862b9398fa2a2cf9b4ff0fdfe8b30cd95209614b7"
        L = mk.node_hash(i, j)
        entries = LEAVES[:7]
        assert mk.inclusion_proof(0, entries) == [b, h, L]
        assert mk.inclusion_proof(3, entries) == [c, g, L]
        assert mk.inclusion_proof(4, entries) == [f, j, k]
        assert mk.inclusion_proof(6, entries) == [i, k]
        root = mk.ROOT_VECTORS[7]
        for index, expected in ((0, [b, h, L]), (3, [c, g, L]), (4, [f, j, k]), (6, [i, k])):
            assert mk.verify_inclusion(entries[index], index, 7, expected, root)
        # the seven-leaf tree is the odd-count leg: size 7 is not a power of two.
        assert mk.merkle_root(entries) == root  # ddb89be4…, the published 7-leaf root

    def test_uppercase_proofs_and_roots_verify(self, mk: ModuleType) -> None:
        index, size = 5, 8
        proof = [p.upper() for p in mk.INCLUSION_VECTORS[(5, 8)]]
        assert mk.verify_inclusion(LEAVES[5], index, size, proof, mk.ROOT_VECTORS[8].upper())


class TestInclusionRefusals:
    """Each leg mirrors a published wantErr case in testdata/inclusion/3."""

    def proof_for(self, mk: ModuleType, size: int = 3, index: int = 2) -> list[str]:
        return mk.inclusion_proof(index, LEAVES[:size])

    def test_wrong_root(self, mk: ModuleType) -> None:
        # wrong-root.json / empty-root.json / random-root.json
        root = mk.ROOT_VECTORS[3]
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, self.proof_for(mk), root[::-1])
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, self.proof_for(mk), mk.EMPTY_TREE_ROOT)
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, self.proof_for(mk), "ab" * 32)

    def test_wrong_leaf(self, mk: ModuleType) -> None:
        # wrong-leaf.json (entry semantics: any entry other than the proven one fails)
        root = mk.ROOT_VECTORS[3]
        for other in (b"\xff", LEAVES[0], LEAVES[1]):
            assert not mk.verify_inclusion(other, 2, 3, self.proof_for(mk), root)

    def test_modified_proof_element(self, mk: ModuleType) -> None:
        # modified-proof[0]-bit-@3.json
        root = mk.ROOT_VECTORS[3]
        tampered = list(self.proof_for(mk))
        tampered[0] = tampered[0][:-1] + ("0" if tampered[0][-1] != "0" else "1")
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, tampered, root)

    def test_removed_component(self, mk: ModuleType) -> None:
        # removed-component.json
        root = mk.ROOT_VECTORS[3]
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, self.proof_for(mk)[:-1], root)

    def test_inserted_component(self, mk: ModuleType) -> None:
        # inserted-component.json
        root = mk.ROOT_VECTORS[3]
        longer = ["00" * 32] + self.proof_for(mk)
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, longer, root)

    def test_preceding_garbage(self, mk: ModuleType) -> None:
        # preceding-garbage.json
        root = mk.ROOT_VECTORS[3]
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, ["00" * 32] + self.proof_for(mk), root)

    def test_trailing_garbage(self, mk: ModuleType) -> None:
        # trailing-garbage.json
        root = mk.ROOT_VECTORS[3]
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, self.proof_for(mk) + ["00" * 32], root)

    def test_preceding_root(self, mk: ModuleType) -> None:
        # preceding-root.json
        root = mk.ROOT_VECTORS[3]
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, [root] + self.proof_for(mk), root)

    def test_index_mutations(self, mk: ModuleType) -> None:
        # leafIdx-XOR/@plus/@sub: an honest tree rejects index, not value.
        root = mk.ROOT_VECTORS[3]
        assert not mk.verify_inclusion(LEAVES[2], 0, 3, self.proof_for(mk), root)
        assert not mk.verify_inclusion(LEAVES[2], 1, 3, self.proof_for(mk), root)
        assert not mk.verify_inclusion(LEAVES[2], 3, 3, self.proof_for(mk), root)
        assert not mk.verify_inclusion(LEAVES[2], -1, 3, self.proof_for(mk), root)

    def test_size_mutations(self, mk: ModuleType) -> None:
        # treeSize-div-@2 / treeSize-mul-@2
        root = mk.ROOT_VECTORS[3]
        assert not mk.verify_inclusion(LEAVES[2], 2, 1, self.proof_for(mk), root)
        assert not mk.verify_inclusion(LEAVES[2], 2, 6, self.proof_for(mk), root)
        assert not mk.verify_inclusion(LEAVES[2], 2, 0, self.proof_for(mk), root)

    def test_single_leaf_tree_proof_must_be_empty(self, mk: ModuleType) -> None:
        assert mk.inclusion_proof(0, LEAVES[:1]) == []
        assert mk.verify_inclusion(LEAVES[0], 0, 1, [], mk.ROOT_VECTORS[1])
        assert not mk.verify_inclusion(LEAVES[0], 0, 1, ["ab" * 32], mk.ROOT_VECTORS[1])
        assert not mk.verify_inclusion(LEAVES[1], 0, 1, [], mk.ROOT_VECTORS[1])

    def test_malformed_arguments_are_false_not_raised(self, mk: ModuleType) -> None:
        root = mk.ROOT_VECTORS[3]
        assert mk.verify_inclusion(LEAVES[2], 2, 3, self.proof_for(mk), root)  # sanity
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, self.proof_for(mk), "not-hex-root")
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, "not-a-list", root)
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, ["xyz"], root)
        assert not mk.verify_inclusion(LEAVES[2], 2, 3, ["ab" * 33], root)
        assert not mk.verify_inclusion("", 2, 3, self.proof_for(mk), root)  # empty str is not hex

    def test_public_8leaf_wrong_leaf_across_proofs(self, mk: ModuleType) -> None:
        root = mk.ROOT_VECTORS[8]
        entries = LEAVES[:8]
        for index in range(8):
            proof = mk.inclusion_proof(index, entries)
            assert not mk.verify_inclusion(entries[(index + 1) % 8], index, 8, proof, root)


class TestConsistencyVectors:
    def test_published_generation(self, mk: ModuleType) -> None:
        for (first, second), expected in mk.CONSISTENCY_VECTORS.items():
            assert mk.consistency_proof(first, LEAVES[:second]) == expected, f"{first}->{second}"

    def test_published_verification(self, mk: ModuleType) -> None:
        for first, second in mk.CONSISTENCY_VECTORS:
            proof = mk.CONSISTENCY_VECTORS[(first, second)]
            assert mk.verify_consistency(first, second, mk.ROOT_VECTORS[first], mk.ROOT_VECTORS[second], proof), (
                f"{first}->{second}"
            )

    def test_all_prefix_pairs_verify(self, mk: ModuleType) -> None:
        # For every 1 <= first <= second <= 8, the generated proof must vvalidate.
        for second in range(1, 9):
            for first in range(1, second + 1):
                proof = mk.consistency_proof(first, LEAVES[:second])
                assert mk.verify_consistency(first, second, mk.ROOT_VECTORS[first], mk.ROOT_VECTORS[second], proof), (
                    f"{first}->{second}"
                )
                # equal sizes have the empty proof and equal roots
                if first == second:
                    assert proof == []

    def test_power_of_two_first_size(self, mk: ModuleType) -> None:
        # 1->8, 2->8, 4->8 must all verify (the prepend-first-root path).
        for first in (1, 2, 4):
            proof = mk.consistency_proof(first, LEAVES[:8])
            assert mk.verify_consistency(first, 8, mk.ROOT_VECTORS[first], mk.ROOT_VECTORS[8], proof)


class TestConsistencyRefusals:
    """Each leg mirrors a published wantErr case in testdata/consistency/2."""

    def base(self, mk: ModuleType) -> tuple[int, int, str, str, list[str]]:
        proof = mk.CONSISTENCY_VECTORS[(6, 8)]
        return 6, 8, mk.ROOT_VECTORS[6], mk.ROOT_VECTORS[8], proof

    def test_empty_proof(self, mk: ModuleType) -> None:
        # empty-proof.json — size1 < size2 with no proof can never verify.
        first, second, root1, root2, _ = self.base(mk)
        assert not mk.verify_consistency(first, second, root1, root2, [])
        # but equal sizes legitimately carry the empty proof
        assert mk.verify_consistency(8, 8, mk.ROOT_VECTORS[8], mk.ROOT_VECTORS[8], [])

    def test_truncated_proof(self, mk: ModuleType) -> None:
        # truncated-proof.json
        first, second, root1, root2, proof = self.base(mk)
        assert not mk.verify_consistency(first, second, root1, root2, proof[:-1])

    def test_trailing_garbage(self, mk: ModuleType) -> None:
        # trailing-garbage.json / trailing-root1/2.json / preceding-garbage.json
        first, second, root1, root2, proof = self.base(mk)
        assert not mk.verify_consistency(first, second, root1, root2, proof + ["ab" * 32])
        assert not mk.verify_consistency(first, second, root1, root2, ["ab" * 32] + proof)
        assert not mk.verify_consistency(first, second, root1, root2, proof + [root1])
        assert not mk.verify_consistency(first, second, root1, root2, [root2] + proof)

    def test_preceding_garbage(self, mk: ModuleType) -> None:
        # preceding-garbage.json / preceding-root1.json / preceding-root2.json
        first, second, root1, root2, proof = self.base(mk)
        assert not mk.verify_consistency(first, second, root1, root2, ["cd" * 32] + proof)

    def test_modified_proof_element(self, mk: ModuleType) -> None:
        # modified-proof@0-bit-@4.json
        first, second, root1, root2, proof = self.base(mk)
        tampered = list(proof)
        tampered[0] = tampered[0][:-1] + ("0" if tampered[0][-1] != "0" else "1")
        assert not mk.verify_consistency(first, second, root1, root2, tampered)

    def test_wrong_roots(self, mk: ModuleType) -> None:
        # wrong-root1.json / wrong-root2.json / swapped-roots.json
        first, second, root1, root2, proof = self.base(mk)
        assert not mk.verify_consistency(first, second, mk.ROOT_VECTORS[4], root2, proof)
        assert not mk.verify_consistency(first, second, root1, mk.ROOT_VECTORS[7], proof)
        assert not mk.verify_consistency(first, second, root2, root1, proof)

    def test_size_mutations(self, mk: ModuleType) -> None:
        # size1-plus/sub, size2-div/mul
        first, second, root1, root2, proof = self.base(mk)
        assert not mk.verify_consistency(first + 1, second, root1, root2, proof)
        assert not mk.verify_consistency(first - 1, second, root1, root2, proof)
        assert not mk.verify_consistency(first, second - 2, root1, root2, proof)
        assert not mk.verify_consistency(first, second * 2, root1, root2, proof)

    def test_size_order(self, mk: ModuleType) -> None:
        first, second, root1, root2, proof = self.base(mk)
        assert not mk.verify_consistency(0, second, root1, root2, proof)
        assert not mk.verify_consistency(second, first, root1, root2, proof)
        assert not mk.verify_consistency(-1, second, root1, root2, proof)

    def test_equal_sizes_require_equal_roots(self, mk: ModuleType) -> None:
        assert not mk.verify_consistency(8, 8, mk.ROOT_VECTORS[8], mk.ROOT_VECTORS[7], [])
        assert not mk.verify_consistency(8, 8, mk.ROOT_VECTORS[8], mk.ROOT_VECTORS[8], ["ab" * 32])

    def test_malformed_arguments_are_false_not_raised(self, mk: ModuleType) -> None:
        first, second, root1, root2, proof = self.base(mk)
        assert not mk.verify_consistency(first, second, "zz", root2, proof)
        assert not mk.verify_consistency(first, second, root1, "zz", proof)
        assert not mk.verify_consistency(first, second, root1, root2, ["xyz"])
        assert not mk.verify_consistency(first, second, root1, root2, "not-a-list")
        assert not mk.verify_consistency(first, second, root1, root2, ["ab" * 33])


class TestGeneratorsRefuse:
    def test_inclusion_out_of_range(self, mk: ModuleType) -> None:
        for bad_index in (-1, 8, 99):
            with pytest.raises(mk.MerkleError):
                mk.inclusion_proof(bad_index, LEAVES[:8])

    def test_inclusion_empty_tree(self, mk: ModuleType) -> None:
        with pytest.raises(mk.MerkleError):
            mk.inclusion_proof(0, [])
            mk.inclusion_proof(0, [])

    def test_consistency_size_out_of_range(self, mk: ModuleType) -> None:
        for bad in (0, -1, 9, 100):
            with pytest.raises(mk.MerkleError):
                mk.consistency_proof(bad, LEAVES[:8])

    def test_consistency_empty_tree(self, mk: ModuleType) -> None:
        with pytest.raises(mk.MerkleError):
            mk.consistency_proof(1, [])

    def test_leaf_entry_must_be_bytes_or_hex(self, mk: ModuleType) -> None:
        with pytest.raises(mk.MerkleError):
            mk.leaf_hash(123)
        with pytest.raises(mk.MerkleError):
            mk.leaf_hash("not-hex")
        with pytest.raises(mk.MerkleError):
            mk.leaf_hash("abc")  # odd length is not a byte string
        with pytest.raises(mk.MerkleError):
            mk.leaf_hash("00 11")  # a stray space is not content
        assert mk.leaf_hash("abcd") == mk.leaf_hash(b"\xab\xcd")  # short hex is valid

    def test_node_hash_must_be_hex(self, mk: ModuleType) -> None:
        with pytest.raises(mk.MerkleError):
            mk.node_hash("00", "not-hex")
        with pytest.raises(mk.MerkleError):
            mk.node_hash("ab" * 32, "cd" * 40)


class TestSignedTreeHead:
    def test_round_trip(self, mk: ModuleType) -> None:
        authz = mk._load_authz()
        private_b64, public_b64 = authz.generate_keypair()
        private_key = authz.private_key_from_b64(private_b64)
        head = mk.sign_tree_head(private_key, public_b64, size=8, root=mk.ROOT_VECTORS[8])
        assert head["size"] == 8
        assert head["root"] == mk.ROOT_VECTORS[8]
        assert head["node_pubkey_b64"] == public_b64
        assert mk.verify_tree_head(public_b64, head)

    def test_tampered_head_is_rejected(self, mk: ModuleType) -> None:
        authz = mk._load_authz()
        private_b64, public_b64 = authz.generate_keypair()
        private_key = authz.private_key_from_b64(private_b64)
        head = mk.sign_tree_head(private_key, public_b64, size=8, root=mk.ROOT_VECTORS[8])
        assert not mk.verify_tree_head(public_b64, {**head, "size": 7})
        assert not mk.verify_tree_head(public_b64, {**head, "root": mk.ROOT_VECTORS[7]})
        tampered = dict(head)
        tampered["signature"] = tampered["signature"][:-1] + ("A" if tampered["signature"][-1] != "A" else "B")
        assert not mk.verify_tree_head(public_b64, tampered)

    def test_wrong_key_and_malformed(self, mk: ModuleType) -> None:
        authz = mk._load_authz()
        private_b64, public_b64 = authz.generate_keypair()
        other_private_b64, other_public_b64 = authz.generate_keypair()
        private_key = authz.private_key_from_b64(private_b64)
        head = mk.sign_tree_head(private_key, public_b64, size=8, root=mk.ROOT_VECTORS[8])
        assert not mk.verify_tree_head(other_public_b64, head)
        assert mk.verify_tree_head(public_b64, head)  # sanity
        assert not mk.verify_tree_head(public_b64, {})
        assert not mk.verify_tree_head(public_b64, {**head, "root": "zz"})
        assert not mk.verify_tree_head(public_b64, {**head, "size": -1})
        assert not mk.verify_tree_head(public_b64, {**head, "signature": "not-b64!!!"})

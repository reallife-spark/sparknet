#!/usr/bin/env python3
"""Sparknet consensus: how the members of a cluster agree on who holds the key.

The fabric elects its Master rather than being told where one is. A cluster is a
pair (two members) or the full cluster (three); of them, one is elected, and the
election requires unanimity because any n-1-of-n majority would let one
compromised node paired with another install a hostile Master.

The result is a **cluster trust root**: n ordinary Ed25519 signatures over
identical canonical bytes, from n distinct members, binding the elected Master's
operational public key. This is *not* threshold cryptography and is not MPC —
unanimity protects *who may hold* the operational key, not each individual
signature.

Ed25519 is not reimplemented here. Every signing and verification operation goes
through `sparknet-authz.py`, loaded by path from the same directory, so the
fabric has one crypto implementation rather than two that must agree.

Every deadline is evaluated against an **injected clock**. This module reads no
wall clock of its own, because a consensus test that waits for a real window is a
test nobody runs.

The normative contract is ``contracts/consensus-protocol.md``.
"""

from __future__ import annotations

import hashlib
import json
import sys

try:  # Python 3.9+
    from collections.abc import Callable
except ImportError:  # pragma: no cover - Python 3.8
    from typing import Callable  # noqa: UP035

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

SCHEMA_VERSION = "1.2"

#: A cluster is two (a pair) or three (the full cluster) members. This is a
#: protocol decision, not a tunable: a fourth member changes the agreement
#: threshold and needs its own design.
MIN_CLUSTER_SIZE = 2
MAX_CLUSTER_SIZE = 3


#: Unanimity. See contracts/consensus-protocol.md for why not a majority.
#: Computed from the roster at tallied size, so a pair requires 2 of 2 and the
#: full cluster requires 3 of 3 — never a fixed count.
def _unanimity(member_ids: frozenset[str]) -> int:
    return len(member_ids)


DEFAULT_SHARED_DIR = Path(__file__).resolve().parent


def _load_authz(shared_dir: Path | None = None) -> Any:
    """Load sparknet-authz.py by path, never by import.

    Loading by path is what proves there is one implementation. An import would
    let a role quietly end up with a private copy, and two crypto
    implementations that must agree byte-for-byte is a second trust boundary.
    The resolve-and-cache mechanics live once in ``shared/sparknet_loader.py``.
    """
    dirs = [Path(shared_dir)] if shared_dir else None
    return load_shared(
        "sparknet-authz.py",
        "sparknet_authz",
        dirs=dirs,
        error=ConsensusError,
        message=(
            "cannot locate sparknet-authz.py; this module refuses to reimplement "
            "Ed25519, so it cannot proceed without the shared implementation"
        ),
    )


class ConsensusError(Exception):
    """Raised for input that cannot be interpreted at all."""


# Reasons are stable strings so a caller can branch on them without parsing prose.
REASON_OK = "ok"
REASON_MALFORMED = "malformed_root"
REASON_WRONG_MEMBER_COUNT = "wrong_member_count"
REASON_DUPLICATE_MEMBER = "duplicate_member"
REASON_MISSING_SIGNATURE = "missing_signature"
REASON_SIGNER_NOT_A_MEMBER = "signer_not_a_member"
REASON_BAD_SIGNATURE = "bad_signature"
REASON_REPLACED = "root_superseded"
REASON_UNCHAINED = "unchained_root"
REASON_REPLAY = "root_replayed"
REASON_NOT_AGREED = "no_unanimous_agreement"
REASON_VOTE_REPLAY = "vote_replayed"
REASON_MEMBER_ALREADY_VOTED = "member_already_voted"
# F2 (reduced-membership re-formation): a chained root that drops a member must
# carry a valid removal proof for exactly the members it drops — no more, no
# fewer. These reasons are stable strings like the rest.
REASON_MISSING_REMOVAL_PROOF = "missing_removal_proof"
REASON_BAD_REMOVAL_PROOF = "bad_removal_proof"
REASON_UNEXPECTED_REMOVAL_PROOF = "unexpected_removal_proof"

#: Member fields covered by a member's signature over the root.
ROOT_MEMBER_FIELDS = ("node_id", "fingerprint", "wireguard_pubkey", "cluster_pubkey")

#: Root fields covered by the signatures. `nonce` is included so a later root can
#: never verify against an earlier one's signatures; `previous_root_id` is
#: included so a later root is bound to the root it supersedes — supersession is
#: a chain (policy B in the re-formation design), never a free replacement. The
#: first root of a cluster records the empty string: it has no predecessor.
#:
#: `epoch` entered the signed fields in schema 1.2 — the reduced-membership work.
#: It is a monotonic counter (0 for a genesis root, parent + 1 for every
#: re-formation), signed so no root can lie about where it sits in the lineage,
#: and independent of the wall clock so two nodes never disagree about ordering.
ROOT_SIGNED_FIELDS = (
    "version",
    "nonce",
    "formed_at",
    "members",
    "master_node_id",
    "master_pubkey",
    "previous_root_id",
    "epoch",
)

#: The schema before chained supersession. A 1.0 root signed the same fields
#: **without** `previous_root_id`. Those roots are still in force somewhere (the
#: live pair formed one on 2026-10-07), so the signed-field set is version-aware:
#: a 1.0 root must keep verifying against its original bytes, and keep its id, or
#: the schema bump would be a silent key-rotation event that no peer can follow.
LEGACY_SCHEMA_VERSION = "1.0"
ROOT_SIGNED_FIELDS_V1 = (
    "version",
    "nonce",
    "formed_at",
    "members",
    "master_node_id",
    "master_pubkey",
)

#: The schema that added the chain (policy B) but not yet the epoch: a 1.1 root
#: signed `previous_root_id` and nothing else new. Kept so a root already in
#: force on the live pair keeps its original bytes and id across the 1.2 bump —
#: the same migration discipline that carried 1.0 into 1.1.
CHAINED_SCHEMA_VERSION = "1.1"
ROOT_SIGNED_FIELDS_V11 = (
    "version",
    "nonce",
    "formed_at",
    "members",
    "master_node_id",
    "master_pubkey",
    "previous_root_id",
)


def _root_signed_fields(root: dict[str, Any]) -> tuple[str, ...]:
    """The signed-field set a root's schema version binds to.

    This is the migration seam. Each new signed field would otherwise change
    every co-signature. `previous_root_id` is part of the signed bytes from 1.1
    on and `epoch` from 1.2 on, so an older root is projected with its own
    version's field set — reproducing its original id — and a newer root chains
    to it by naming that id as its `previous_root_id`.
    """
    version = root.get("version")
    if version == LEGACY_SCHEMA_VERSION:
        return ROOT_SIGNED_FIELDS_V1
    if version == CHAINED_SCHEMA_VERSION:
        return ROOT_SIGNED_FIELDS_V11
    return ROOT_SIGNED_FIELDS


# --- canonicalisation ---------------------------------------------------------


def canonical_root(root: dict[str, Any]) -> dict[str, Any]:
    """Project a root down to its agreement-bearing fields, sorted.

    Anything not in ROOT_SIGNED_FIELDS is dropped, so operational metadata cannot
    change what the members agreed to.
    """
    if not isinstance(root, dict):
        raise ConsensusError("root must be a mapping")
    fields = _root_signed_fields(root)
    missing = [f for f in fields if f not in root]
    if missing:
        raise ConsensusError(f"root missing required field(s): {', '.join(missing)}")
    members = root["members"]
    if not isinstance(members, list):
        raise ConsensusError("members must be a list")
    projected_members = []
    for member in members:
        if not isinstance(member, dict):
            raise ConsensusError("each member must be a mapping")
        absent = [f for f in ROOT_MEMBER_FIELDS if f not in member]
        if absent:
            raise ConsensusError(f"member missing required field(s): {', '.join(absent)}")
        projected_members.append({f: member[f] for f in sorted(ROOT_MEMBER_FIELDS)})
    # Member order must not affect the bytes, or two nodes listing members
    # differently would compute different roots for the same agreement.
    projected_members.sort(key=lambda m: m["node_id"])
    projected = {
        "version": root["version"],
        "nonce": root["nonce"],
        "formed_at": root["formed_at"],
        "members": projected_members,
        "master_node_id": root["master_node_id"],
        "master_pubkey": root["master_pubkey"],
    }
    if "previous_root_id" in fields:
        previous = root["previous_root_id"]
        if not isinstance(previous, str):
            raise ConsensusError("previous_root_id must be a string")
        projected["previous_root_id"] = previous
    if "epoch" in fields:
        epoch = root["epoch"]
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
            raise ConsensusError("epoch must be a non-negative integer")
        projected["epoch"] = epoch
    return projected


def root_bytes(root: dict[str, Any]) -> bytes:
    """Deterministic serialisation of the root the members sign.

    Same rule as the identity canonical form: sort_keys and tight separators, so
    the bytes do not depend on dict insertion order or Python formatting.
    """
    return json.dumps(canonical_root(root), sort_keys=True, separators=(",", ":")).encode("utf-8")


def root_id(root: dict[str, Any]) -> str:
    """Stable handle for a root: sha256 of its canonical bytes, hex."""
    return hashlib.sha256(root_bytes(root)).hexdigest()


# --- election -----------------------------------------------------------------


def _now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None:
        raise ConsensusError(
            "clock returned a naive datetime; consensus requires an aware clock so "
            "that members cannot disagree about what time it is"
        )
    return value


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class Vote:
    """One member's signed vote for one candidate."""

    node_id: str
    candidate_node_id: str
    election_id: str
    nonce: str
    cast_at: str
    signature_b64: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "candidate_node_id": self.candidate_node_id,
            "election_id": self.election_id,
            "nonce": self.nonce,
            "cast_at": self.cast_at,
            "signature_b64": self.signature_b64,
        }


def vote_message(vote: dict[str, Any]) -> bytes:
    """Bytes a member signs when voting.

    `election_id` and `nonce` are inside, so a vote cannot be replayed into a
    later election or a second attempt within the same one.
    """
    for field_name in ("node_id", "candidate_node_id", "election_id", "nonce", "cast_at"):
        if field_name not in vote:
            raise ConsensusError(f"vote missing required field: {field_name}")
    envelope = {k: vote[k] for k in sorted(("node_id", "candidate_node_id", "election_id", "nonce", "cast_at"))}
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_vote(vote: dict[str, Any], cluster_private_key_b64: str, shared_dir: Path | None = None) -> Vote:
    """Sign a vote with a member's cluster key.

    The Ed25519 work is delegated to `sparknet-authz` in full. This module's job is
    consensus, and a second key-parsing path in it would put key handling in the
    one module that is trusted about keys for no gain.
    """
    authz = _load_authz(shared_dir)
    try:
        key = authz.private_key_from_b64(cluster_private_key_b64)
        signature_b64 = authz.sign_bytes(key, vote_message(vote))
    except Exception as exc:
        raise ConsensusError(f"cannot sign vote: {exc}") from exc
    return Vote(
        node_id=vote["node_id"],
        candidate_node_id=vote["candidate_node_id"],
        election_id=vote["election_id"],
        nonce=vote["nonce"],
        cast_at=vote["cast_at"],
        signature_b64=signature_b64,
    )


def tally(
    votes: list[dict[str, Any]],
    members: list[dict[str, Any]],
    election_id: str,
    shared_dir: Path | None = None,
) -> dict[str, Any]:
    """Count distinct members agreeing on one candidate.

    Votes are deduplicated by `node_id`, so one member voting three times has cast
    one vote. A member may vote for exactly one candidate per election, and a
    second vote from the same member for a different candidate is rejected rather
    than counted, because a member that equivocates is not agreeing with anyone.

    **Every vote's signature is verified before it is counted.** A vote is a
    network packet, and a tally that counts packets without checking who sent them
    counts anything anyone claims. A forged vote — correct `node_id`, garbage
    signature — would otherwise be indistinguishable from a real one and could
    fabricate unanimity outright, which is the one thing this whole module exists
    to prevent. An unverifiable vote is dropped and *reported* in `rejected`,
    never silently ignored: an election must tolerate forgery without being able
    to hide it.

    Returns a plain dict so the result is serialisable into the ledger without a
    custom encoder.
    """
    member_ids = {m["node_id"] for m in members}
    if len(member_ids) != len(members):
        raise ConsensusError("membership contains a duplicate node_id")
    needed = _unanimity(frozenset(member_ids))

    seen: dict[str, str] = {}
    candidates: dict[str, set[str]] = {}
    rejected: list[dict[str, str]] = []
    considered = 0
    for raw in votes:
        vote = raw.as_dict() if isinstance(raw, Vote) else raw
        if vote.get("election_id") != election_id:
            # A vote from a different election is not evidence here. It is not an
            # error: elections are long-lived and votes accumulate.
            continue
        considered += 1
        voter = vote.get("node_id")
        if voter not in member_ids:
            rejected.append({"node_id": str(voter), "reason": REASON_SIGNER_NOT_A_MEMBER})
            continue
        # Verify before counting. Not after: once a forged vote is in `seen` or
        # `candidates` it is already influencing the outcome.
        ok, why = verify_vote(vote, members, shared_dir)
        if not ok:
            rejected.append({"node_id": voter, "reason": why})
            continue
        previous = seen.get(voter)
        if previous is not None:
            if previous == vote.get("candidate_node_id"):
                continue  # duplicate of the same choice: still one vote
            return {
                "agreed": False,
                "reason": REASON_MEMBER_ALREADY_VOTED,
                "detail": f"{voter} voted for more than one candidate",
                "counts": {c: sorted(v) for c, v in candidates.items()},
                "rejected": rejected,
            }
        seen[voter] = vote["candidate_node_id"]
        candidates.setdefault(vote["candidate_node_id"], set()).add(voter)

    agreed_candidates = {c: v for c, v in candidates.items() if len(v) == needed}
    if not agreed_candidates:
        best = max((len(v) for v in candidates.values()), default=0)
        return {
            "agreed": False,
            "reason": REASON_NOT_AGREED,
            "detail": (
                f"no candidate has all {needed} members; best had {best}"
                if considered
                else "no votes for this election"
            ),
            "counts": {c: sorted(v) for c, v in candidates.items()},
            "rejected": rejected,
        }
    if len(agreed_candidates) > 1:
        # Two candidates each holding every vote is only possible if membership is
        # malformed, because a member casts one choice.
        return {
            "agreed": False,
            "reason": REASON_MALFORMED,
            "detail": "more than one candidate holds unanimity",
            "counts": {c: sorted(v) for c, v in candidates.items()},
            "rejected": rejected,
        }
    winner = next(iter(agreed_candidates))
    return {
        "agreed": True,
        "reason": REASON_OK,
        "master_node_id": winner,
        "voters": sorted(agreed_candidates[winner]),
        "counts": {c: sorted(v) for c, v in candidates.items()},
        "rejected": rejected,
    }


def verify_vote(
    vote: dict[str, Any],
    members: list[dict[str, Any]],
    shared_dir: Path | None = None,
) -> tuple[bool, str]:
    """Check one vote's signature against the member's cluster key."""
    authz = _load_authz(shared_dir)
    by_id = {m["node_id"]: m for m in members}
    member = by_id.get(vote.get("node_id"))
    if member is None:
        return False, REASON_SIGNER_NOT_A_MEMBER
    if not vote.get("signature_b64"):
        return False, REASON_MISSING_SIGNATURE
    try:
        public_key = authz.public_key_from_b64(member["cluster_pubkey"])
        public_key.verify(authz.decode_b64_strict(vote["signature_b64"], what="vote signature"), vote_message(vote))
    except ConsensusError:
        return False, REASON_MALFORMED
    except Exception:
        return False, REASON_BAD_SIGNATURE
    return True, REASON_OK


# --- the trust root -----------------------------------------------------------


def sign_root(
    root: dict[str, Any],
    node_id: str,
    cluster_private_key_b64: str,
    shared_dir: Path | None = None,
) -> dict[str, str]:
    """Sign a root with **one** member's cluster key. This is the production ceremony.

    Each member runs this on its own node and sends the resulting one-entry map to
    the others; when every member's map arrives they are merged into `root["signatures"]`.
    No process ever holds more than one cluster key, which is the property that
    makes unanimity meaningful: `attach_root_signatures` can take every key, but
    only as a fixture, and the live path never uses it.

    Merging is deliberately dumb — `merge_root_signatures` just refuses duplicates
    and counts — because a merge that made policy decisions would be a second
    place for the agreement rule to live.
    """
    member_ids = {m["node_id"] for m in root["members"]}
    if node_id not in member_ids:
        raise ConsensusError(f"{node_id} is not a member of this root; it may not sign it")
    authz = _load_authz(shared_dir)
    try:
        key = authz.private_key_from_b64(cluster_private_key_b64)
        signature = authz.sign_bytes(key, root_bytes(root))
    except Exception as exc:
        raise ConsensusError(f"cannot sign root: {exc}") from exc
    return {node_id: signature}


def merge_root_signatures(root: dict[str, Any], signature_maps: list[dict[str, str]]) -> dict[str, Any]:
    """Combine per-member signature maps into a root, once every member has signed.

    Refuses to overwrite an existing signature for a node. A later signature from
    the same member is either a replay or equivocation, and silently keeping the
    later one would let a member rewrite what it previously attested to.
    """
    member_ids = {m["node_id"] for m in root["members"]}
    merged: dict[str, str] = dict(root.get("signatures") or {})
    for signatures in signature_maps:
        for node_id, signature in signatures.items():
            if node_id not in member_ids:
                raise ConsensusError(f"{node_id} signed a root it is not a member of")
            if node_id in merged:
                raise ConsensusError(
                    f"{node_id} has already signed this root; a second signature "
                    f"from the same member is equivocation, not agreement"
                )
            merged[node_id] = signature
    missing = member_ids - set(merged)
    if missing:
        raise ConsensusError(
            f"root is unsigned by: {', '.join(sorted(missing))}; a root needs all {len(member_ids)} members to sign"
        )
    signed = dict(root)
    signed["signatures"] = merged
    return signed


def attach_root_signatures(
    root: dict[str, Any], cluster_keys_b64: dict[str, str], shared_dir: Path | None = None
) -> dict[str, Any]:
    """Co-sign a root with every member's cluster key.

    `cluster_keys_b64` maps node_id -> base64 private key.

    Read the docstring on this function before using it in anger: it takes every
    member's private key at once, so it is a *convenience and a test fixture*, not the
    production ceremony. A live cluster co-signs one root with each member signing
    only its own copy, then merges the signature maps off the WireGuard interface.
    Handing this function every key hands one process the ability to produce a
    root on its own, which is exactly what `tally`'s unanimity refusal exists to
    prevent. Production uses `sign_root` per member instead.
    """
    authz = _load_authz(shared_dir)

    member_ids = {m["node_id"] for m in root["members"]}
    missing = member_ids - set(cluster_keys_b64)
    if missing:
        raise ConsensusError(
            f"no cluster key supplied for: {', '.join(sorted(missing))}; a root "
            f"needs all {len(member_ids)} members to sign"
        )
    signatures: dict[str, str] = {}
    message = root_bytes(root)
    for node_id in sorted(member_ids):
        key = authz.private_key_from_b64(cluster_keys_b64[node_id])
        signatures[node_id] = authz.sign_bytes(key, message)
    signed = dict(root)
    signed["signatures"] = signatures
    return signed


# --- removal proofs (reduced-membership re-formation) -------------------------
#
# A re-formation may *shrink* the cluster: the survivors form a chained child
# root that names only themselves. Dropping a member is a denial — it removes
# reach and cannot add any — but it must still be *evidenced*, or a colluding
# majority could silently vanish an honest node and a pure verifier would have
# no way to tell a lawful reduction from a forgery. So a child root that drops a
# member carries a **removal proof** per dropped member, and `verify_root`'s
# trust path refuses a child unless its dropped set is *exactly* the set the
# proofs evidence.
#
# Two kinds of proof are accepted:
#   - "revocation": signed by the PARENT root's elected Master with its
#     *operational* key. This is the contract's existing 1-signature revoke made
#     durable as evidence the chain can check — the operator who may already
#     unilaterally revoke a node can hand the survivors the proof of it.
#   - "attested": signed by EVERY surviving member with its *cluster* key. This
#     is majority-to-reduce (n-1 survivors consent), the design's
#     "survivor-signed statement that the member is unreachable-and-departed".
#
# A lone survivor has no cluster to form (below MIN_CLUSTER_SIZE); it holds only
# the proof — a tombstone — and must re-witness a new member before a root can
# exist again. The floor is not relaxed here.

#: Fields covered by a removal proof's signature(s).
REMOVAL_PROOF_FIELDS = ("removed_node_id", "parent_root_id", "kind", "nonce", "ts")
REMOVAL_PROOF_KINDS = ("revocation", "attested")


def canonical_removal_proof(proof: dict[str, Any]) -> dict[str, Any]:
    """Project a removal proof to its signed fields, sorted."""
    if not isinstance(proof, dict):
        raise ConsensusError("removal proof must be a mapping")
    missing = [f for f in REMOVAL_PROOF_FIELDS if f not in proof]
    if missing:
        raise ConsensusError(f"removal proof missing field(s): {', '.join(missing)}")
    if proof["kind"] not in REMOVAL_PROOF_KINDS:
        raise ConsensusError(f"removal proof kind must be one of {REMOVAL_PROOF_KINDS}, got {proof['kind']!r}")
    return {f: proof[f] for f in sorted(REMOVAL_PROOF_FIELDS)}


def removal_proof_bytes(proof: dict[str, Any]) -> bytes:
    return json.dumps(canonical_removal_proof(proof), sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_removal_proof(
    proof: dict[str, Any],
    signer_node_id: str,
    private_key_b64: str,
    shared_dir: Path | None = None,
) -> dict[str, Any]:
    """Add one signer's signature to a removal proof (its `signatures` map)."""
    authz = _load_authz(shared_dir)
    try:
        key = authz.private_key_from_b64(private_key_b64)
        signature = authz.sign_bytes(key, removal_proof_bytes(proof))
    except Exception as exc:
        raise ConsensusError(f"cannot sign removal proof: {exc}") from exc
    signed = dict(proof)
    signatures = dict(signed.get("signatures") or {})
    if signer_node_id in signatures:
        raise ConsensusError(f"{signer_node_id} has already signed this removal proof")
    signatures[signer_node_id] = signature
    signed["signatures"] = signatures
    return signed


def verify_removal_proof(
    proof: dict[str, Any],
    previous: dict[str, Any],
    survivors: list[str],
    shared_dir: Path | None = None,
) -> tuple[bool, str]:
    """Check one removal proof against the parent root it names.

    `survivors` is the child root's membership (the members that stay). For an
    `attested` proof every survivor must have signed; for a `revocation` the
    parent's Master must have signed with its operational key. A proof signed by
    anyone else, or missing a required signer, is refused.
    """
    authz = _load_authz(shared_dir)
    try:
        projected = canonical_removal_proof(proof)
        prev = canonical_root(previous)
    except ConsensusError as exc:
        return False, f"{REASON_BAD_REMOVAL_PROOF}: {exc}"

    signatures = proof.get("signatures")
    if not isinstance(signatures, dict) or not signatures:
        return False, f"{REASON_MISSING_SIGNATURE}: removal proof carries no signatures"

    if projected["kind"] == "revocation":
        required = {prev["master_node_id"]: prev["master_pubkey"]}
    else:  # attested
        by_id = {m["node_id"]: m for m in prev["members"]}
        strangers = [s for s in survivors if s not in by_id]
        if strangers:
            return False, (
                f"{REASON_BAD_REMOVAL_PROOF}: survivors {', '.join(sorted(strangers))} "
                f"are not members of the parent root"
            )
        required = {s: by_id[s]["cluster_pubkey"] for s in survivors}

    extra = set(signatures) - set(required)
    if extra:
        return False, (f"{REASON_BAD_REMOVAL_PROOF}: signed by non-required {', '.join(sorted(extra))}")
    absent = set(required) - set(signatures)
    if absent:
        return False, (f"{REASON_MISSING_SIGNATURE}: removal proof unsigned by {', '.join(sorted(absent))}")

    message = removal_proof_bytes(projected)
    for node_id, public_key_b64 in required.items():
        try:
            public_key = authz.public_key_from_b64(public_key_b64)
            public_key.verify(authz.decode_b64_strict(signatures[node_id], what="removal-proof signature"), message)
        except Exception:
            return False, (f"{REASON_BAD_REMOVAL_PROOF}: {node_id}'s signature does not verify")
    return True, REASON_OK


def _removal_proofs_by_member(root: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map a chained root's `removal_proofs` list by removed member id.

    `removal_proofs` is carried alongside the root but is **not** one of the
    signed fields: each proof is independently signed by its authority, so it
    authenticates itself, and the signed root stays small. A duplicate proof for
    one member is refused — two different evidences for the same drop would make
    "exactly the dropped set" ambiguous.
    """
    proofs = root.get("removal_proofs") or []
    if not isinstance(proofs, list):
        raise ConsensusError("removal_proofs must be a list")
    by_member: dict[str, dict[str, Any]] = {}
    for proof in proofs:
        if not isinstance(proof, dict):
            raise ConsensusError("each removal proof must be a mapping")
        removed = proof.get("removed_node_id")
        if not isinstance(removed, str) or not removed:
            raise ConsensusError("removal proof missing removed_node_id")
        if removed in by_member:
            raise ConsensusError(f"more than one removal proof for {removed}")
        by_member[removed] = proof
    return by_member


def verify_root(
    root: dict[str, Any],
    trust: dict[str, Any] | None = None,
    shared_dir: Path | None = None,
) -> tuple[bool, str]:
    """Verify a cluster trust root.

    Checks, in order, cheapest first: shape, then member count and distinctness,
    then that every named member signed, then each signature against the
    `cluster_pubkey` the root itself states.

    The last check is the one that carries weight. Without it a root could name
    members and be signed by strangers. With `trust` supplied (the
    root already held), a root with a different nonce is rejected as superseded,
    which is what makes re-formation actually replace anything.
    """
    authz = _load_authz(shared_dir)
    try:
        projected = canonical_root(root)
    except ConsensusError as exc:
        return False, f"{REASON_MALFORMED}: {exc}"

    if trust is not None:
        try:
            previous = canonical_root(trust)
        except ConsensusError as exc:
            return False, f"{REASON_MALFORMED}: held root unusable: {exc}"
        if previous["nonce"] == projected["nonce"]:
            return False, (f"{REASON_REPLAY}: this nonce is already the root in force; a new root needs a new nonce")
        chained = projected.get("previous_root_id", "") == root_id(previous)
        if not chained:
            return False, (
                f"{REASON_UNCHAINED}: this root does not descend from the root in "
                f"force. Supersession is a chain: a new root must name the held "
                f"root as previous_root_id, or it is a stranger, not a successor, "
                f"however well it is signed"
            )
        # The epoch is the signed, clock-free height of the root in its lineage.
        # A 1.2+ root must sit exactly one above the root it descends from, so a
        # root cannot claim a height it has not earned (a stale root replayed as
        # a fresh one, or a forged forward jump). Roots older than 1.2 predate the
        # field and are treated as height 0, so a live 1.1 root can be the parent
        # of the first 1.2 re-formation without a re-election.
        if "epoch" in projected:
            parent_epoch = canonical_root(previous).get("epoch", 0)
            if projected["epoch"] != parent_epoch + 1:
                return False, (
                    f"{REASON_UNCHAINED}: epoch must be exactly {parent_epoch + 1} "
                    f"(one above the root in force), got {projected['epoch']}"
                )
        held_ids = {m["node_id"] for m in previous["members"]}
        new_ids = {m["node_id"] for m in projected["members"]}
        if not new_ids.issubset(held_ids):
            return False, (
                f"{REASON_UNCHAINED}: re-formation may only replace the master "
                f"or shrink membership (evidence for the drop lives in the "
                f"registry); a chained root that ADDS a member is the join "
                f"ceremony, which is a different contract"
            )
        if len(new_ids) < MIN_CLUSTER_SIZE:
            return False, (
                f"{REASON_UNCHAINED}: a chained root may not fall below "
                f"{MIN_CLUSTER_SIZE} members; a lone survivor holds a removal "
                f"proof, not a cluster"
            )
        # A reduction must be *evidenced*. The dropped set is held minus new; the
        # proofs must cover exactly that set — no missing proof (a silent
        # eviction) and no proof for a member that stays (a forged drop record).
        dropped = held_ids - new_ids
        try:
            proofs = _removal_proofs_by_member(root)
        except ConsensusError as exc:
            return False, f"{REASON_BAD_REMOVAL_PROOF}: {exc}"
        unexpected = set(proofs) - dropped
        if unexpected:
            return False, (
                f"{REASON_UNEXPECTED_REMOVAL_PROOF}: a removal proof was supplied "
                f"for {', '.join(sorted(unexpected))}, which the child root still "
                f"names; the dropped set must equal the evidenced set exactly"
            )
        missing = dropped - set(proofs)
        if missing:
            return False, (
                f"{REASON_MISSING_REMOVAL_PROOF}: the child root drops "
                f"{', '.join(sorted(missing))} with no removal proof; a reduction "
                f"must be evidenced by a revocation (parent Master, operational "
                f"key) or an attested statement (every survivor, cluster key)"
            )
        parent_id = root_id(previous)
        for removed_id in sorted(dropped):
            proof = proofs[removed_id]
            if proof.get("parent_root_id") != parent_id:
                return False, (
                    f"{REASON_BAD_REMOVAL_PROOF}: {removed_id}'s removal proof names "
                    f"{proof.get('parent_root_id')!r}, not the root in force "
                    f"{parent_id!r}"
                )
            ok, why = verify_removal_proof(proof, previous, sorted(new_ids), shared_dir)
            if not ok:
                return False, f"{REASON_BAD_REMOVAL_PROOF}: {why}"

    members = projected["members"]
    if len(members) < MIN_CLUSTER_SIZE or len(members) > MAX_CLUSTER_SIZE:
        return False, (
            f"{REASON_WRONG_MEMBER_COUNT}: expected {MIN_CLUSTER_SIZE} or {MAX_CLUSTER_SIZE}, got {len(members)}"
        )
    ids = [m["node_id"] for m in members]
    if len(set(ids)) != len(ids):
        return False, f"{REASON_DUPLICATE_MEMBER}: {ids}"

    signatures = root.get("signatures")
    if not isinstance(signatures, dict) or not signatures:
        return False, f"{REASON_MISSING_SIGNATURE}: root carries no signatures"

    by_id = {m["node_id"]: m for m in members}
    extra = set(signatures) - set(by_id)
    if extra:
        return False, (f"{REASON_SIGNER_NOT_A_MEMBER}: signed by non-members {', '.join(sorted(extra))}")
    absent = set(by_id) - set(signatures)
    if absent:
        return False, (f"{REASON_MISSING_SIGNATURE}: no signature from {', '.join(sorted(absent))}")

    message = root_bytes(projected)
    for node_id in sorted(by_id):
        try:
            public_key = authz.public_key_from_b64(by_id[node_id]["cluster_pubkey"])
            public_key.verify(authz.decode_b64_strict(signatures[node_id], what="root signature"), message)
        except Exception:
            return False, (
                f"{REASON_BAD_SIGNATURE}: {node_id}'s signature does not verify "
                f"against the cluster_pubkey the root itself names"
            )

    if projected["master_node_id"] not in by_id:
        return False, (
            f"{REASON_SIGNER_NOT_A_MEMBER}: the elected master "
            f"{projected['master_node_id']} is not a member of the root"
        )
    return True, REASON_OK


def verify_chain(roots: list[dict[str, Any]]) -> tuple[bool, str]:
    """Verify a pull-chain of roots, newest first.

    Policy B makes supersession a chain: every root after the first must name the
    root it descends from as `previous_root_id`. A peer that has been offline
    while the cluster re-formed once (or twice) does not hold the intermediate
    roots and cannot use the single-hop `verify_root(root, trust=held)` check on
    the newest root; it must verify the whole line. `roots[0]` is the newest, and
    `roots[-1]` must be a genesis root (`previous_root_id == ""`).

    Each step uses `verify_root` with `trust` set to the next-older root, which
    carries the whole re-formation discipline forward: a step that breaks the
    chain, adds a member, or drops below the minimum is refused with the same
    reasons as an exchange against a single held root.
    """
    if not roots:
        return False, f"{REASON_UNCHAINED}: an empty chain verifies nothing"
    try:
        terminal = canonical_root(roots[-1]).get("previous_root_id", "")
    except ConsensusError as exc:
        return False, f"{REASON_UNCHAINED}: terminal root unusable: {exc}"
    if terminal != "":
        return False, (
            f"{REASON_UNCHAINED}: the chain does not terminate at a genesis root; "
            f"the oldest supplied root still names a parent, so the lineage is "
            f"incomplete"
        )
    for index, root in enumerate(roots):
        trust = roots[index + 1] if index + 1 < len(roots) else None
        ok, reason = verify_root(root, trust=trust)
        if not ok:
            return False, (f"{REASON_UNCHAINED}: link {index} of the chain fails: {reason}")
    return True, REASON_OK


def authorised_master_pubkey(root: dict[str, Any]) -> str | None:
    """The operational key a verified root authorises, or None if unusable."""
    ok, _ = verify_root(root)
    if not ok:
        return None
    return canonical_root(root)["master_pubkey"]


def registry_signer_is_authorised(root: dict[str, Any], registry_entry: dict[str, Any]) -> tuple[bool, str]:
    """Check a registry entry was signed by the master this root names.

    This is the join between consensus and the existing authorization scheme: the
    root decides *whose* key counts, and `sparknet-authz` then does what it always
    did.
    """
    authz = _load_authz()
    ok, reason = verify_root(root)
    if not ok:
        return False, reason
    expected = canonical_root(root)["master_pubkey"]
    try:
        public_key = authz.public_key_from_b64(expected)
        entry = dict(registry_entry)
        public_key.verify(
            authz.decode_b64_strict(entry["signature_b64"], what="registry entry signature"),
            authz.authorization_message(entry),
        )
    except Exception:
        return False, (
            f"{REASON_BAD_SIGNATURE}: the registry entry is not signed under the operational key this root authorises"
        )
    return True, REASON_OK

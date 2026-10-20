#!/usr/bin/env python3
"""Sparknet node authorization: SHA-256 identity fingerprints, Ed25519-signed by the Master.

Why this exists
---------------
WireGuard itself has no SHA-256 anywhere in its protocol (Noise IK: X25519 key
exchange, BLAKE2s hashing, ChaCha20-Poly1305 transport). So "p2p privileges
authenticated by sha256" cannot be a property of the tunnel. Instead this module
provides the *authorization layer beside* the tunnel:

    canonical identity JSON
      -> SHA-256 fingerprint
      -> Master signs the canonical bytes with Ed25519
      -> a node verifies signature + expiry + revocation before it will
         accept p2p duties for itself

The WireGuard handshake proves "this peer holds that private key". This layer
proves "the Master authorized this peer's identity for these capabilities".

Trust model
-----------
* A peer never holds the Master private key. It only holds the Master
  *public* key, which is safe to track in the vault.
* Revocation is the Master's prerogative: it signs a record with
  ``revoked: true``. A peer cannot forge that, so a compromised peer cannot
  reinstate itself.
* "Unremovable" in Sparknet means the node's own ``wg0.conf`` is immutable
  (``chattr +i``), so the node cannot quietly drop its Master Anchor. It does
  *not* mean membership is irrevocable — the Master may revoke.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except ImportError as exc:  # pragma: no cover - environment guard
    print(
        f"[authz] FATAL: the 'cryptography' package is required ({exc}).\n"
        f"[authz] Install it with:  make devtools   (or: pip install 'cryptography>=42')",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

SCHEMA_VERSION = "1.0"

#: Capability a node may hold. Anything not listed here is rejected.
KNOWN_CAPABILITIES = frozenset(
    {
        "telemetry",
        "p2p-sync",
        "push-receive",
        "guard-apply",
        "cluster-vote",
        "cluster-dispatch",
        "cluster-serve",
        "admin-supervise",
    }
)

# Identity fields that participate in the fingerprint. Deliberately excludes
# hostname, vault path and timestamps: those change without changing identity,
# and including them would make every node re-sign after a routine rename.
IDENTITY_FIELDS = ("node_id", "role", "wireguard_public_key_b64", "overlay_ipv4", "requested_capabilities")

REASON_OK = "ok"
REASON_UNKNOWN = "unknown_fingerprint"
REASON_REVOKED = "revoked"
REASON_EXPIRED = "expired"
REASON_BAD_SIGNATURE = "bad_signature"
REASON_MALFORMED = "malformed_record"
REASON_IDENTITY_MISMATCH = "identity_mismatch"
REASON_UNKNOWN_CAPABILITY = "unknown_capability"
REASON_NOT_YET_VALID = "not_yet_valid"


class AuthzError(Exception):
    """Raised for malformed input that cannot be interpreted at all."""


# --- canonicalisation + fingerprint ------------------------------------------


def canonical_identity(identity: dict[str, Any]) -> dict[str, Any]:
    """Project a record down to the identity-bearing fields, sorted.

    Anything outside IDENTITY_FIELDS is ignored so that operational metadata
    cannot change a node's fingerprint.
    """
    missing = [f for f in IDENTITY_FIELDS if f not in identity]
    if missing:
        raise AuthzError(f"identity missing required field(s): {', '.join(missing)}")
    projected = {field: identity[field] for field in sorted(IDENTITY_FIELDS)}
    if not isinstance(projected["requested_capabilities"], list):
        raise AuthzError("requested_capabilities must be a list")
    return projected


def canonical_bytes(identity: dict[str, Any]) -> bytes:
    """Deterministic serialisation of the identity alone.

    sort_keys + tight separators means the bytes do not depend on dict
    insertion order or Python version formatting. This is what the SHA-256
    fingerprint is taken over.
    """
    return json.dumps(canonical_identity(identity), sort_keys=True, separators=(",", ":")).encode("utf-8")


#: Fields of a registry entry covered by the Master's signature. `revoked` is
#: included deliberately: it means only the Master (holding the private key) can
#: flip it, so an attacker with registry write access can revoke a node (a safe
#: false denial) but cannot reinstate one (which would need a fresh signature).
SIGNED_FIELDS = ("fingerprint", "identity", "capabilities", "overlay_ipv4", "issued_at", "expires_at", "revoked")


def authorization_message(entry: dict[str, Any]) -> bytes:
    """Bytes the Master actually signs: identity *and* the privileges it grants.

    Signing only the identity would leave `capabilities` and `overlay_ipv4`
    mutable by anyone who can edit the registry file, which would let them
    escalate a node to guard-apply without the Master ever approving it.
    """
    try:
        envelope = {
            "fingerprint": entry["fingerprint"],
            "identity": canonical_identity(entry["identity"]),
            "capabilities": sorted(entry["capabilities"]),
            "overlay_ipv4": entry.get("overlay_ipv4"),
            "issued_at": entry["issued_at"],
            "expires_at": entry["expires_at"],
            "revoked": bool(entry.get("revoked", False)),
        }
    except (KeyError, AuthzError, TypeError) as exc:
        raise AuthzError(f"authorization entry is malformed: {exc}") from exc
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fingerprint(identity: dict[str, Any]) -> str:
    """SHA-256 of the canonical identity bytes, hex encoded."""
    return hashlib.sha256(canonical_bytes(identity)).hexdigest()


# --- keys --------------------------------------------------------------------


def public_key_b64(public_key: Ed25519PublicKey) -> str:
    from cryptography.hazmat.primitives import serialization

    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def decode_b64_strict(text: str, *, what: str = "value", urlsafe: bool = False) -> bytes:
    """Decode base64 *strictly*, rejecting non-alphabet bytes and bad padding.

    This is the one decoding entry point for signatures, keys and wire bodies.
    Every call passes ``validate=True`` so a string that is not canonical base64
    is rejected with an explicit error rather than silently truncated to a shorter
    prefix that still happens to verify-or-not.

    Why it exists: CPython's tolerant decoder accepts some malformed input (for
    example a 43-character body with a stray padding ``=``) on 3.12 but raises on
    3.14 with ``validate=True``. Sprinkling ``validate=True`` by hand left a few
    call sites tolerant, so a signature could be interpreted differently depending
    on the interpreter that happened to run — a portability trap in the one layer
    whose job is to be trusted about signatures. One helper, one interpretation.

    ``urlsafe`` selects the URL-safe alphabet (used for grant bearer tokens).
    The padding is normalised first, since URL-safe tokens are commonly emitted
    unpadded while ``b64decode`` wants a multiple of four.
    """
    try:
        if urlsafe:
            padded = text + "=" * (-len(text) % 4)
            return base64.urlsafe_b64decode(padded.encode("ascii"))
        return base64.b64decode(text, validate=True)
    except Exception as exc:
        raise AuthzError(f"{what} is not valid base64") from exc


def public_key_from_b64(raw_b64: str) -> Ed25519PublicKey:
    """Build a public key from a base64 string rather than a file.

    Lives here rather than in the caller so that key parsing is part of the one
    crypto implementation. A module that loaded keys its own way would be a second
    place for a length or encoding mistake to hide.
    """
    raw = decode_b64_strict(raw_b64, what="public key")
    if len(raw) != 32:
        raise AuthzError(f"Ed25519 public key must be 32 bytes, got {len(raw)}")
    return Ed25519PublicKey.from_public_bytes(raw)


def private_key_from_b64(raw_b64: str) -> Ed25519PrivateKey:
    """Build a private key from a base64 string rather than a file.

    The counterpart to `public_key_from_b64`, added because `sparknet-consensus.py`
    needs one and was reaching for `cryptography` directly to get it. That was a
    second place for key parsing to go wrong, in the one module whose entire job
    is to be trusted about keys — and it showed up as an unused `authz` import,
    the lint failure being the only thing that noticed.

    Deliberately *not* tolerant the way `load_private_key` is: a path can be raw,
    base64 or hex because a human typed it, but a value that reached this function
    has already been through a machine-readable channel. One encoding, one
    interpretation, one place to be wrong.
    """
    raw = decode_b64_strict(raw_b64, what="private key")
    if len(raw) != 32:
        raise AuthzError(f"Ed25519 private key must be 32 bytes, got {len(raw)}")
    return Ed25519PrivateKey.from_private_bytes(raw)


def sign_bytes(private_key: Ed25519PrivateKey, message: bytes) -> str:
    """Sign a message and return base64.

    The signing counterpart to `verify_signature`. Both the registry authorizer and
    the consensus signer need "sign these canonical bytes, base64 the result", and
    that phrasing should be defined once.
    """
    return base64.b64encode(private_key.sign(message)).decode("ascii")


def generate_keypair() -> tuple[str, str]:
    """Generate an Ed25519 keypair as (private_b64, public_b64).

    Lives here so that "how does a node get a key" has one answer in the fabric.
    `peer-node/scripts/sparknet-keygen.sh` and `master-node/scripts/` both need
    it, and a per-role script that reached for `cryptography` itself would be the
    second place a length or encoding mistake could hide.

    Returns base64 text rather than objects because every consumer is a shell
    script writing a `.b64` file.
    """
    from cryptography.hazmat.primitives import serialization

    key = Ed25519PrivateKey.generate()
    private_raw = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return (
        base64.b64encode(private_raw).decode("ascii"),
        base64.b64encode(public_raw).decode("ascii"),
    )


def load_public_key(path: Path) -> Ed25519PublicKey:
    """Load a raw 32-byte Ed25519 public key from a file (base64 or hex)."""
    text = Path(path).read_text().strip()
    if not text:
        raise AuthzError(f"master public key file is empty: {path}")
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception:
        try:
            raw = bytes.fromhex(text)
        except ValueError as exc:
            raise AuthzError(f"master public key in {path} is neither base64 nor hex") from exc
    if len(raw) != 32:
        raise AuthzError(f"Ed25519 public key must be 32 bytes, got {len(raw)} in {path}")
    return Ed25519PublicKey.from_public_bytes(raw)


def load_private_key(path: Path) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from a file.

    Accepts either the raw 32-byte seed or base64 text. Both encodings are in
    circulation — `openssl genpkey` emits PEM, `wg`-style tooling and
    scripts/sparknet-keygen.sh emit base64, and a raw seed is what an operator
    may have copied off disk — so refuse only when neither interpretation yields
    exactly 32 bytes. Guessing wrong is worse than accepting both.
    """
    blob = Path(path).read_bytes()
    candidates: list[bytes] = []

    stripped = blob.strip()
    if stripped and len(stripped) == 32:
        candidates.append(stripped)
    if stripped:
        with contextlib.suppress(Exception):
            candidates.append(base64.b64decode(stripped, validate=True))
        with contextlib.suppress(ValueError, UnicodeDecodeError):
            candidates.append(bytes.fromhex(stripped.decode("ascii")))
    if len(blob) == 32:
        candidates.append(blob)

    for raw in candidates:
        if len(raw) == 32:
            return Ed25519PrivateKey.from_private_bytes(raw)
    raise AuthzError(f"Ed25519 private key in {path} is not 32 raw bytes, base64, or hex")


def verify_signature(public_key: Ed25519PublicKey, signature_b64: str, message: bytes) -> bool:
    try:
        signature = decode_b64_strict(signature_b64, what="signature")
    except AuthzError:
        return False
    try:
        public_key.verify(signature, message)
    except InvalidSignature:
        return False
    return True


# --- registry ----------------------------------------------------------------


@dataclass
class Decision:
    """Outcome of an authorization check. Never raises for a denied node."""

    allowed: bool
    reason: str
    fingerprint: str
    capabilities: list[str] = field(default_factory=list)
    overlay_ipv4: str | None = None
    identity: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "fingerprint": self.fingerprint,
            "capabilities": self.capabilities,
            "overlay_ipv4": self.overlay_ipv4,
        }


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate(
    identity: dict[str, Any],
    registry: dict[str, Any],
    master_public_key: Ed25519PublicKey,
    now: datetime | None = None,
) -> Decision:
    """Decide whether this node may act, and with which capabilities.

    Checks are ordered cheapest-and-most-decisive first so a revoked node is
    rejected before any signature work.
    """
    now = now or datetime.now(timezone.utc)
    try:
        local_fp = fingerprint(identity)
    except AuthzError:
        return Decision(False, REASON_MALFORMED, "", identity=None)

    entries = registry.get("authorizations")
    if not isinstance(entries, list):
        return Decision(False, REASON_MALFORMED, local_fp)

    entry = next((e for e in entries if isinstance(e, dict) and e.get("fingerprint") == local_fp), None)
    if entry is None:
        return Decision(False, REASON_UNKNOWN, local_fp)

    if entry.get("revoked"):
        return Decision(False, REASON_REVOKED, local_fp)

    expires = _parse_ts(entry.get("expires_at"))
    if expires is not None and now > expires:
        return Decision(False, REASON_EXPIRED, local_fp)
    issued = _parse_ts(entry.get("issued_at"))
    if issued is not None and now < issued - timedelta(minutes=5):
        return Decision(False, REASON_NOT_YET_VALID, local_fp)

    # The registry must not be able to carry an identity that hashes to
    # something other than the fingerprint it is filed under.
    stored_identity = entry.get("identity")
    if not isinstance(stored_identity, dict):
        return Decision(False, REASON_MALFORMED, local_fp)
    try:
        if fingerprint(stored_identity) != local_fp:
            return Decision(False, REASON_IDENTITY_MISMATCH, local_fp)
    except AuthzError:
        return Decision(False, REASON_MALFORMED, local_fp)

    if not verify_signature(master_public_key, str(entry.get("signature_b64", "")), authorization_message(entry)):
        return Decision(False, REASON_BAD_SIGNATURE, local_fp)

    granted = entry.get("capabilities")
    if not isinstance(granted, list) or not granted:
        return Decision(False, REASON_MALFORMED, local_fp)
    unknown = [c for c in granted if c not in KNOWN_CAPABILITIES]
    if unknown:
        return Decision(False, REASON_UNKNOWN_CAPABILITY, local_fp)

    return Decision(
        True,
        REASON_OK,
        local_fp,
        capabilities=sorted(granted),
        overlay_ipv4=entry.get("overlay_ipv4") or stored_identity.get("overlay_ipv4"),
        identity=stored_identity,
    )


def sign_authorization(
    identity: dict[str, Any],
    master_private_key: Ed25519PrivateKey,
    capabilities: list[str],
    ttl_days: int = 365,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a signed registry entry. MASTER-SIDE ONLY — needs the Master private key.

    Peers never call this. It exists so the Master has a reference
    implementation and so tests can mint fixtures without hand-rolling JSON.
    """
    now = now or datetime.now(timezone.utc)
    unknown = [c for c in capabilities if c not in KNOWN_CAPABILITIES]
    if unknown:
        raise AuthzError(f"unknown capability/capabilities: {', '.join(unknown)}")

    stamp = now.isoformat().replace("+00:00", "Z")
    entry: dict[str, Any] = {
        "fingerprint": fingerprint(identity),
        "identity": canonical_identity(identity),
        "capabilities": sorted(capabilities),
        "overlay_ipv4": identity.get("overlay_ipv4"),
        "issued_at": stamp,
        "expires_at": (now + timedelta(days=ttl_days)).isoformat().replace("+00:00", "Z"),
        "revoked": False,
    }
    entry["signature_b64"] = base64.b64encode(master_private_key.sign(authorization_message(entry))).decode("ascii")
    return entry


# --- cluster jobs ------------------------------------------------------------


#: The ways a cluster job may divide a prompt. A closed set: a job naming any
#: other mode is refused rather than guessed at, so a new mode cannot be
#: introduced by a caller that skips the contract.
CLUSTER_JOB_MODES = ("decompose", "shard", "best_of_n", "mixture")

#: Fields of a cluster job covered by the initiator's (or the ratifying Master's)
#: signature. `subtasks` is inside the signature for the same reason a registry
#: entry's `capabilities` is: signing a job id alone would let anyone replay one
#: job's signature over a different partition, prompt or recipient set.
CLUSTER_JOB_FIELDS = (
    "job_id",
    "conversation_id",
    "initiator_node_id",
    "created_at",
    "expires_at",
    "mode",
    "prompt",
    "running_summary",
    "context",
    "budget",
    "subtasks",
)

#: Fields a job must carry and fill before it can be canonicalised. The remaining
#: CLUSTER_JOB_FIELDS (`running_summary`, `context`, `budget`) may legitimately be
#: empty on a first turn, so they are projected as null rather than required.
#: `subtasks` is validated separately, where its shape (a non-empty list) is known.
CLUSTER_JOB_REQUIRED = (
    "job_id",
    "conversation_id",
    "initiator_node_id",
    "created_at",
    "expires_at",
    "mode",
    "prompt",
)


def is_expired(value: Any, now: datetime) -> bool:
    """True when an ISO-8601 timestamp is unparseable or in the past.

    Fail-closed on purpose: a malformed expiry is treated as expired, so a bad
    timestamp cannot become an unlimited-validity job. Uses the same parser as
    registry expiry, so the two cannot disagree about what a valid stamp is.
    """
    parsed = _parse_ts(value)
    return parsed is None or now > parsed


# --- ledger blocks (provenance) -----------------------------------------------


#: Block fields the node signature does *not* cover: the block's own
#: self-references. Everything else — `block_id`, `prev_hash`, `timestamp`,
#: `node_pubkey_b64` and `data` — is signed, so editing any of them (or moving
#: the block in the chain) invalidates the header signature even if `hash` is
#: recomputed to match.
LEDGER_SIGNATURE_EXCLUDED = ("hash", "signature")


def ledger_block_signable(block: dict[str, Any]) -> bytes:
    """Canonical bytes the appending node key signs for one ledger block.

    The signed unit is the whole *header*, not just `data`. That is the fix for
    the gap where the block-level signature only restated `data.signatures.node`:
    with the header unsigned, a `grant_use` block could be deleted and its nonce
    replayed, because nothing bound the block's position or its payload to a key.
    One implementation, imported by the writer and every verifier, so the three
    copies cannot drift the way the earlier unsigned shape did.
    """
    if not isinstance(block, dict):
        raise AuthzError("ledger block must be an object")
    header = {k: v for k, v in block.items() if k not in LEDGER_SIGNATURE_EXCLUDED}
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")


def ledger_block_hash(block: dict[str, Any]) -> str:
    """The chain hash of a ledger block: SHA-256 over the block minus `hash`.

    Includes the header signature, so the chain links on signed bytes: a block
    cannot be swapped for one with the same data and a different timestamp, and
    the next block's `prev_hash` commits to the whole signed predecessor.
    """
    if not isinstance(block, dict):
        raise AuthzError("ledger block must be an object")
    payload = {k: v for k, v in block.items() if k != "hash"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def cluster_job_message(job: dict[str, Any]) -> bytes:
    """Canonical bytes signed for a cluster job, projected to CLUSTER_JOB_FIELDS.

    One projection rule, shared by the signer and every verifier. A second copy of
    this rule is how `sign-guard-approval` and the guard diverged; the fix here is
    to have the single implementation live where both sides must import it.

    The projection is a fixed field list, so operational metadata added later
    cannot silently join the signature, and it is serialised with sort_keys and
    tight separators so the bytes do not depend on dict insertion order.
    """
    if not isinstance(job, dict):
        raise AuthzError("cluster job must be an object")
    missing = [f for f in CLUSTER_JOB_REQUIRED if not job.get(f)]
    if missing:
        raise AuthzError(f"cluster job missing required field(s): {', '.join(missing)}")
    if job["mode"] not in CLUSTER_JOB_MODES:
        raise AuthzError(f"unknown cluster job mode {job['mode']!r}; expected one of {', '.join(CLUSTER_JOB_MODES)}")
    subtasks = job["subtasks"]
    if not isinstance(subtasks, list) or not subtasks:
        raise AuthzError("cluster job subtasks must be a non-empty list")
    projected = {field: job.get(field) for field in sorted(CLUSTER_JOB_FIELDS)}
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


# --- admin requests (admin-supervise) -----------------------------------------


#: The closed set of administrative actions a Master may ask a peer to perform
#: against the peer's own Open WebUI — plus `list_events`, which reads the node's
#: own auth-event spool (the same 0600 file the node admin agent writes) so the
#: Master's console can show a live, de-duplicated feed of signups and successful
#: logins without reading any peer's database. A request naming any other action
#: is refused rather than guessed at, exactly like CLUSTER_JOB_MODES.
ADMIN_REQUEST_ACTIONS = (
    "list_users",
    "get_user",
    "approve_user",
    "set_user_role",
    "list_knowledge",
    "get_user_chats",
    "list_events",
)

#: Fields of an admin-request covered by the Master's signature. `request_id` and
#: `target_fingerprint` are inside the signature for the same reason a registry
#: entry's `capabilities` is: signing an id alone would let anyone replay one
#: request's signature against a different node, action or entity. The entity
#: fields (`user_id`, `user_email`, `role`, `kb_id`, `chat_id`) are projected
#: too, so altering who/what an approved action targets invalidates the signature.
ADMIN_REQUEST_FIELDS = (
    "request_id",
    "conversation_id",
    "master_node_id",
    "target_node_id",
    "target_fingerprint",
    "issued_at",
    "expires_at",
    "nonce",
    "action",
    "user_id",
    "user_email",
    "role",
    "kb_id",
    "chat_id",
)

#: Fields a request must carry and fill before it can be canonicalised. The
#: remaining ADMIN_REQUEST_FIELDS (`conversation_id`, and the entity fields) may
#: legitimately be absent depending on the action, so they are projected as
#: null/empty rather than required — the per-action entity requirement is the
#: peer's to enforce with its execution whitelist.
ADMIN_REQUEST_REQUIRED = (
    "request_id",
    "master_node_id",
    "target_node_id",
    "target_fingerprint",
    "issued_at",
    "expires_at",
    "nonce",
    "action",
)


def admin_request_message(request: dict[str, Any]) -> bytes:
    """Canonical bytes signed for an admin-request, projected to ADMIN_REQUEST_FIELDS.

    One projection rule, shared by the signer and every peer that executes the
    request — the same anti-drift pattern as ``cluster_job_message``: a second
    copy of this rule is exactly how signing and verifying diverged before.
    """
    if not isinstance(request, dict):
        raise AuthzError("admin request must be an object")
    missing = [f for f in ADMIN_REQUEST_REQUIRED if not request.get(f)]
    if missing:
        raise AuthzError(f"admin request missing required field(s): {', '.join(missing)}")
    if request["action"] not in ADMIN_REQUEST_ACTIONS:
        raise AuthzError(
            f"unknown admin action {request['action']!r}; expected one of {', '.join(ADMIN_REQUEST_ACTIONS)}"
        )
    projected = {field: request.get(field) for field in sorted(ADMIN_REQUEST_FIELDS)}
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


# --- session grants ------------------------------------------------------------


#: Fields of a signed session grant (contracts/identity-schema.json `grant`).
#: The projection is a fixed field list, exactly like a registry entry's
#: SIGNED_FIELDS: signing an id alone would let anyone replay one grant's
#: signature over a different scope, user or conversation.
GRANT_FIELDS = (
    "grant_id",
    "node_id",
    "node_fingerprint",
    "overlay_ipv4",
    "capabilities",
    "user_identity",
    "conversation_key",
    "vault_scope",
    "issued_at",
    "expires_at",
    "nonce",
    "parent_grant_id",
)

#: Fields a grant must carry non-empty before it can be canonicalised. The
#: remaining GRANT_FIELDS (`overlay_ipv4`, `vault_scope`, `parent_grant_id`)
#: may legitimately be empty, so they are projected as null/empty rather than
#: required — empty `vault_scope` is the meaningful "node-level config only".
GRANT_REQUIRED = (
    "grant_id",
    "node_id",
    "node_fingerprint",
    "capabilities",
    "user_identity",
    "conversation_key",
    "issued_at",
    "expires_at",
    "nonce",
)

REASON_GRANT_UNKNOWN_NODE = "grant_unknown_node"
REASON_GRANT_REVOKED = "grant_revoked"
REASON_GRANT_CAPABILITY_WIDEN = "grant_would_widen_node"
REASON_GRANT_EXPIRED = "grant_expired"
REASON_GRANT_NOT_YET_VALID = "grant_not_yet_valid"
REASON_GRANT_NONCE_REUSED = "grant_nonce_reused"
REASON_GRANT_NODE_MISMATCH = "grant_node_mismatch"
REASON_GRANT_MALFORMED = "grant_malformed"


def grant_message(grant: dict[str, Any]) -> bytes:
    """Canonical bytes a grant's signature covers, projected to GRANT_FIELDS.

    One projection rule, shared by the signer and every verifier — the
    ``sign-guard-approval``/guard divergence happened because that rule had two
    copies, so a grant deliberately has the single implementation both sides
    import. Serialised with sort_keys and tight separators so the bytes do not
    depend on dict insertion order.
    """
    if not isinstance(grant, dict):
        raise AuthzError("grant must be an object")
    missing = [f for f in GRANT_REQUIRED if not grant.get(f)]
    if missing:
        raise AuthzError(f"grant missing required field(s): {', '.join(missing)}")
    if not isinstance(grant["capabilities"], list) or not grant["capabilities"]:
        raise AuthzError("grant capabilities must be a non-empty list")
    if not isinstance(grant.get("vault_scope", []), list):
        raise AuthzError("grant vault_scope must be a list")
    parent = grant.get("parent_grant_id")
    if parent is not None and not isinstance(parent, str):
        raise AuthzError("grant parent_grant_id must be a string or null")
    projected = {field: grant.get(field) for field in GRANT_FIELDS}
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


def mint_grant(
    *,
    node_identity: dict[str, Any],
    grant_id: str,
    user_identity: str,
    conversation_key: str,
    capabilities: list[str],
    vault_scope: list[str],
    ttl_minutes: int,
    nonce: str,
    master_private_key: Ed25519PrivateKey,
    parent_grant_id: str | None = None,
    registry: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mint a signed session grant. MASTER-SIDE OR OFFLINE OPERATOR ONLY.

    Never called by a peer with operational intent: like `sign_authorization`,
    this needs the private key. While the Master is unbuilt it is exactly what
    `sparknet-authz.py grant-mint --master-key` runs, offline, with no Master
    present.

    The node fingerprint and overlay address come from the node's projected
    identity, so a grant cannot be replayed onto a re-keyed node or moved to a
    different overlay face. When `registry` is given, minting refuses to widen
    the node (a grant cannot mint a node that is not in it); without it, only
    unknown capabilities are refused and the verifier still enforces the
    registry ceiling.
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(capabilities, list) or not capabilities:
        raise AuthzError("grant must carry at least one capability")
    unknown = [c for c in capabilities if c not in KNOWN_CAPABILITIES]
    if unknown:
        raise AuthzError(f"unknown capability/capabilities: {', '.join(unknown)}")
    for value, name in (
        (grant_id, "grant_id"),
        (user_identity, "user_identity"),
        (conversation_key, "conversation_key"),
        (nonce, "nonce"),
    ):
        if not isinstance(value, str) or not value:
            raise AuthzError(f"grant {name} must be a non-empty string")
    local_fp = fingerprint(node_identity)
    if registry is not None:
        entries = registry.get("authorizations")
        if not isinstance(entries, list):
            raise AuthzError("registry has no authorizations list")
        entry = next((e for e in entries if isinstance(e, dict) and e.get("fingerprint") == local_fp), None)
        if entry is None:
            raise AuthzError("grant node is not in the registry — a grant cannot mint a node")
        if entry.get("revoked"):
            raise AuthzError("grant node is revoked in the registry")
        granted = entry.get("capabilities")
        if not isinstance(granted, list) or not granted:
            raise AuthzError("registry entry has no capabilities")
        widen = [c for c in capabilities if c not in granted]
        if widen:
            raise AuthzError(f"grant would widen the node: {', '.join(widen)}")

    stamp = now.isoformat().replace("+00:00", "Z")
    grant: dict[str, Any] = {
        "grant_id": grant_id,
        "node_id": str(node_identity.get("node_id")),
        "node_fingerprint": local_fp,
        "overlay_ipv4": node_identity.get("overlay_ipv4"),
        "capabilities": sorted(set(capabilities)),
        "user_identity": user_identity,
        "conversation_key": conversation_key,
        "vault_scope": sorted(set(vault_scope)) if vault_scope else [],
        "issued_at": stamp,
        "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat().replace("+00:00", "Z"),
        "nonce": nonce,
        "parent_grant_id": parent_grant_id,
    }
    grant["signature_b64"] = sign_bytes(master_private_key, grant_message(grant))
    return grant


def verify_grant(
    grant: dict[str, Any],
    *,
    master_public_key: Ed25519PublicKey,
    registry: dict[str, Any],
    node_identity: dict[str, Any] | None,
    consumed_nonces: set[str] | frozenset[str],
    now: datetime | None = None,
) -> Decision:
    """Decide whether a session grant may be exercised, fail-closed.

    The ordered checks are contracts/identity-schema.json `grant.
    verification_order`, which restates guard-protocol.md's check order
    unchanged — there is exactly one ordered verification path, not a second
    crypto implementation:
      signature first, then the registry is the ceiling (fingerprint, not
      revoked, capabilities a subset), then expiry and nonce, then the name the
      grant carries vs the identity presenting it.
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(grant, dict):
        return Decision(False, REASON_GRANT_MALFORMED, "")
    node_fp = str(grant.get("node_fingerprint") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", node_fp):
        return Decision(False, REASON_GRANT_MALFORMED, node_fp)

    # 1. Signature (cheapest decisive disqualifier after shape).
    try:
        message = grant_message(grant)
    except AuthzError:
        return Decision(False, REASON_GRANT_MALFORMED, node_fp)
    if not verify_signature(master_public_key, str(grant.get("signature_b64") or ""), message):
        return Decision(False, REASON_BAD_SIGNATURE, node_fp)

    # 2. The node the grant names must be in the Master-signed registry, and live.
    entries = registry.get("authorizations")
    if not isinstance(entries, list):
        return Decision(False, REASON_GRANT_MALFORMED, node_fp)
    entry = next((e for e in entries if isinstance(e, dict) and e.get("fingerprint") == node_fp), None)
    if entry is None:
        return Decision(False, REASON_GRANT_UNKNOWN_NODE, node_fp)
    if entry.get("revoked"):
        return Decision(False, REASON_GRANT_REVOKED, node_fp)
    stored = entry.get("identity")
    if not isinstance(stored, dict):
        return Decision(False, REASON_GRANT_MALFORMED, node_fp)
    try:
        stored_match = fingerprint(stored) == node_fp
    except AuthzError:
        stored_match = False
    if not stored_match:
        return Decision(False, REASON_IDENTITY_MISMATCH, node_fp)
    # The registry entry itself must be signed under the same key the grant is.
    if not verify_signature(master_public_key, str(entry.get("signature_b64", "")), authorization_message(entry)):
        return Decision(False, REASON_BAD_SIGNATURE, node_fp)

    # 3. A grant cannot widen the node: registry capabilities are the ceiling.
    granted = entry.get("capabilities")
    if not isinstance(granted, list) or not granted:
        return Decision(False, REASON_GRANT_MALFORMED, node_fp)
    want = grant.get("capabilities")
    if not isinstance(want, list) or not want:
        return Decision(False, REASON_GRANT_MALFORMED, node_fp)
    unknown = [c for c in want if c not in KNOWN_CAPABILITIES]
    if unknown:
        return Decision(False, REASON_UNKNOWN_CAPABILITY, node_fp)
    widen = [c for c in want if c not in granted]
    if widen:
        return Decision(False, REASON_GRANT_CAPABILITY_WIDEN, node_fp)

    # 4. Validity window, enforced locally — an unreachable issuer cannot
    #    extend a grant, per identity-schema.json `expires_at.local_enforcement`.
    expires = _parse_ts(grant.get("expires_at"))
    issued = _parse_ts(grant.get("issued_at"))
    if expires is None or now > expires:
        return Decision(False, REASON_GRANT_EXPIRED, node_fp)
    if issued is None or now < issued - timedelta(minutes=5):
        return Decision(False, REASON_GRANT_NOT_YET_VALID, node_fp)

    # 5. Nonce never seen on this node (the ledger is the retention store).
    if str(grant.get("nonce") or "") in consumed_nonces:
        return Decision(False, REASON_GRANT_NONCE_REUSED, node_fp)

    # 6. The peer presenting the grant is the peer named in it.
    if node_identity is not None:
        try:
            presenter_fp = fingerprint(node_identity)
        except AuthzError:
            return Decision(False, REASON_GRANT_MALFORMED, node_fp)
        if presenter_fp != node_fp or str(node_identity.get("node_id")) != str(grant.get("node_id")):
            return Decision(False, REASON_GRANT_NODE_MISMATCH, node_fp)

    return Decision(
        True,
        REASON_OK,
        node_fp,
        capabilities=sorted(want),
        overlay_ipv4=grant.get("overlay_ipv4") or stored.get("overlay_ipv4"),
        identity=stored,
    )


# --- CLI ---------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sparknet node authorization (SHA-256 + Ed25519)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    fp = sub.add_parser("fingerprint", help="Print the SHA-256 fingerprint of an identity file")
    fp.add_argument("identity", type=Path)

    # No local binding: nothing is added to this parser after creation, and an
    # unused variable here is a lint error that would eventually get someone to
    # delete the call by accident.
    sub.add_parser(
        "generate-keypair",
        help=(
            "Generate one Ed25519 keypair; prints private_b64 then public_b64 on "
            "two lines. Both halves come from a single invocation: an earlier "
            "version had a --field flag, and calling it twice produced two "
            "different keypairs whose public half did not match the private one"
        ),
    )

    ver = sub.add_parser("verify", help="Verify this node against a registry and master public key")
    ver.add_argument("identity", type=Path)
    ver.add_argument("--registry", type=Path, required=True)
    ver.add_argument("--master-pubkey", type=Path, required=True)

    sgn = sub.add_parser("sign", help="MASTER-SIDE: sign an identity into a registry entry")
    sgn.add_argument("identity", type=Path)
    sgn.add_argument(
        "--master-key",
        type=Path,
        required=True,
        help="Ed25519 private key: raw 32 bytes or base64 text (see load_private_key)",
    )
    sgn.add_argument("--capabilities", required=True, help="comma-separated")
    sgn.add_argument("--ttl-days", type=int, default=365)
    sgn.add_argument("--out", type=Path, required=True)

    gm = sub.add_parser(
        "grant-mint",
        help="MASTER-SIDE: mint a signed session grant offline; no Master needs to be running",
    )
    gm.add_argument("--node-identity", type=Path, required=True)
    gm.add_argument("--master-key", type=Path, required=True)
    gm.add_argument("--grant-id", required=True)
    gm.add_argument("--user-identity", required=True)
    gm.add_argument("--conversation-key", required=True)
    gm.add_argument("--capabilities", required=True, help="comma-separated subset of what the registry grants the node")
    gm.add_argument(
        "--vault-scope",
        default="",
        help="comma-separated vault-relative path prefixes; empty means node-level config only, no knowledge access",
    )
    gm.add_argument("--ttl-minutes", type=int, default=480)
    gm.add_argument("--nonce", required=True)
    gm.add_argument("--parent-grant-id", help="the grant a subagent inherits, when delegating")
    gm.add_argument(
        "--registry",
        type=Path,
        help="when given, mint refuses to mint a grant that would widen the node",
    )
    gm.add_argument("--out", type=Path, required=True)

    gv = sub.add_parser("grant-verify", help="verify a signed session grant fail-closed")
    gv.add_argument("--grant", type=Path, required=True)
    gv.add_argument(
        "--master-pubkey",
        type=Path,
        help="the Master public key file; omitted, the key is read from the registry's master_public_key_b64",
    )
    gv.add_argument("--registry", type=Path, required=True)
    gv.add_argument(
        "--node-identity",
        type=Path,
        help="the presenting node's identity; enforces the presenter check (step 6)",
    )
    gv.add_argument(
        "--used-nonces",
        type=Path,
        help="file of already-consumed grant nonces, one per line",
    )

    args = parser.parse_args(argv)

    if args.cmd == "generate-keypair":
        private_b64, public_b64 = generate_keypair()
        print(private_b64)
        print(public_b64)
        return 0

    if args.cmd == "fingerprint":
        identity = json.loads(args.identity.read_text())
        print(fingerprint(identity))
        return 0

    if args.cmd == "verify":
        identity = json.loads(args.identity.read_text())
        registry = json.loads(args.registry.read_text())
        decision = evaluate(identity, registry, load_public_key(args.master_pubkey))
        print(json.dumps(decision.as_dict(), indent=2))
        return 0 if decision.allowed else 1

    if args.cmd == "sign":
        identity = json.loads(args.identity.read_text())
        entry = sign_authorization(
            identity, load_private_key(args.master_key), args.capabilities.split(","), ttl_days=args.ttl_days
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(entry, indent=2) + "\n")
        print(f"wrote {args.out} (fingerprint {entry['fingerprint']})")
        return 0

    if args.cmd == "grant-mint":
        identity = json.loads(args.node_identity.read_text())
        grant = mint_grant(
            node_identity=identity,
            grant_id=args.grant_id,
            user_identity=args.user_identity,
            conversation_key=args.conversation_key,
            capabilities=[c for c in args.capabilities.split(",") if c],
            vault_scope=[s for s in args.vault_scope.split(",") if s],
            ttl_minutes=args.ttl_minutes,
            nonce=args.nonce,
            parent_grant_id=args.parent_grant_id,
            registry=json.loads(args.registry.read_text()) if args.registry else None,
            master_private_key=load_private_key(args.master_key),
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(grant, indent=2) + "\n")
        print(
            f"wrote grant {args.grant_id} for {grant['node_id']} "
            f"(fingerprint {grant['node_fingerprint'][:16]}..., expires {grant['expires_at']})"
        )
        return 0

    if args.cmd == "grant-verify":
        grant = json.loads(args.grant.read_text())
        registry = json.loads(args.registry.read_text())
        if args.master_pubkey:
            master_pubkey = load_public_key(args.master_pubkey)
        else:
            raw_b64 = str(registry.get("master_public_key_b64") or "")
            if not raw_b64:
                raise AuthzError("registry carries no master_public_key_b64 and no --master-pubkey was given")
            master_pubkey = public_key_from_b64(raw_b64)
        consumed: set[str] = set()
        if args.used_nonces and args.used_nonces.is_file():
            consumed = {line.strip() for line in args.used_nonces.read_text().splitlines() if line.strip()}
        identity = json.loads(args.node_identity.read_text()) if args.node_identity else None
        decision = verify_grant(
            grant,
            master_public_key=master_pubkey,
            registry=registry,
            node_identity=identity,
            consumed_nonces=consumed,
        )
        print(json.dumps(decision.as_dict(), indent=2))
        return 0 if decision.allowed else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(_main())

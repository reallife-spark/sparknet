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
import secrets
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
        "cross-department-share",
        "model-uplift",
        "memory-supervise",
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
#: `department` is included for the same reason: it decides who may share with
#: whom, so an unsigned one is a privilege boundary anyone able to edit the
#: registry file could move.
SIGNED_FIELDS = (
    "fingerprint",
    "identity",
    "capabilities",
    "overlay_ipv4",
    "issued_at",
    "expires_at",
    "revoked",
    "department",
)


def authorization_message(entry: dict[str, Any]) -> bytes:
    """Bytes the Master actually signs: identity *and* the privileges it grants.

    Signing only the identity would leave `capabilities` and `overlay_ipv4`
    mutable by anyone who can edit the registry file, which would let them
    escalate a node to guard-apply without the Master ever approving it.

    `department` is always present in the envelope, as null when the Master has
    attested none. One message shape rather than one-per-optional-field: two
    canonical forms for the same logical entry is exactly the ambiguity the
    byte-for-byte agreement rule exists to prevent, and a verifier should never
    have to guess which form it is looking at.
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
            "department": entry.get("department"),
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
    revoked: bool = False,
    department: str | None = None,
) -> dict[str, Any]:
    """Build a signed registry entry. MASTER-SIDE ONLY — needs the Master private key.

    Peers never call this. It exists so the Master has a reference
    implementation and so tests can mint fixtures without hand-rolling JSON.

    ``revoked`` is a parameter rather than a field a caller may set afterwards
    because ``revoked`` is *inside* the signed envelope: flipping it after
    signing produces an entry whose signature no longer verifies. Revoking is
    an act of the key, so it happens here, under the signature.

    ``department`` is a parameter for exactly the same reason. It is inside the
    envelope because it decides who may share with whom, so an entry's department
    cannot be edited afterwards without invalidating the signature — attesting one
    is an act of the Master's key, never a field a registry editor fills in. It is
    always emitted, as null when the Master attests none, so there is one entry
    shape rather than two for a verifier to distinguish.
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
        "revoked": bool(revoked),
        "department": department,
    }
    entry["signature_b64"] = base64.b64encode(master_private_key.sign(authorization_message(entry))).decode("ascii")
    return entry


# --- guard approvals (guard-apply) --------------------------------------------


#: The whole guard-approval envelope. An approval names one peer, one protected
#: path and one piece of content, and nothing else.
#:
#: `peer_fingerprint` binds the approval to the peer that may apply it. Without
#: it an approval minted for one peer is a valid approval *any* peer could
#: apply, as long as it protects the same path — the signature would still
#: verify, because it says nothing about who it is for.
#:
#: The content is inside the envelope (`content_b64`), not beside it: signing a
#: digest alone would let anything on the path substitute the bytes and still
#: match.
#:
#: This list lives here, once, because the Master signs it and the peer verifies
#: it. Two copies of this rule is exactly how the two sides drift apart, each
#: keeping "working" against its own assumption — which is what happened before
#: the rule was lifted out of the signer and the guard into this module.
#:
#: Sorted, because it is a projection and not a sequence: the canonical bytes
#: sort the keys anyway, so the order here is only about the contract and this
#: module being able to state the same list in the same words. The reading
#: order — what an approval means, field by field — is the contract's
#: `field_semantics` map, which keeps it.
GUARD_APPROVAL_FIELDS = (
    "content_b64",
    "content_sha256",
    "expires_at",
    "file_path",
    "issued_at",
    "nonce",
    "operator_os",
    "peer_fingerprint",
    "request_id",
)

#: Fields that must be present and non-empty before an approval can be
#: canonicalised. `content_b64` is deliberately not here: an empty file is a
#: legitimate target, so the key must be present but its value may be empty.
GUARD_APPROVAL_REQUIRED = (
    "content_sha256",
    "expires_at",
    "file_path",
    "issued_at",
    "nonce",
    "peer_fingerprint",
    "request_id",
)


def guard_approval_message(approval: dict[str, Any]) -> bytes:
    """Canonical bytes a guard-approval signature covers.

    One projection rule, shared by the signer and by every peer that verifies
    an approval — the same anti-drift pattern as ``cluster_job_message``,
    ``admin_request_message`` and ``grant_message``.

    The rule is strict in both directions:

    * a missing field is refused, because an approval naming no path or no
      nonce would authorise an unbounded change;
    * an *extra* field is refused too. The signature covers exactly this
      projection, so anything outside it is unsigned — and an unsigned field in
      an envelope that carries authority is how a second, unchecked channel
      into the guard would appear later.

    Serialised with sort_keys and tight separators, so the bytes depend on the
    values alone and not on how the sender happened to serialise them.
    """
    if not isinstance(approval, dict):
        raise AuthzError("guard approval must be an object")
    missing = [f for f in GUARD_APPROVAL_REQUIRED if not approval.get(f)]
    if missing:
        raise AuthzError(f"guard approval missing required field(s): {', '.join(missing)}")
    absent = [f for f in GUARD_APPROVAL_FIELDS if f not in approval]
    if absent:
        raise AuthzError(f"guard approval missing field(s): {', '.join(absent)}")
    extra = sorted(set(approval) - set(GUARD_APPROVAL_FIELDS))
    if extra:
        raise AuthzError(f"guard approval carries field(s) outside the canonical envelope: {', '.join(extra)}")
    projected = {name: approval[name] for name in sorted(GUARD_APPROVAL_FIELDS)}
    for name, value in projected.items():
        if not isinstance(value, str):
            raise AuthzError(f"guard approval field {name!r} must be a string")
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


# --- registry publications (distribution) ------------------------------------


#: The unsigned content of a registry publication. A publication is how a signed
#: registry reaches a peer: the Master wraps the document, stamps it with a
#: monotonic sequence and a publication time, and signs a digest of the document
#: rather than the document itself.
#:
#: Why the digest and not the document: the entries are already signed, and the
#: registry's canonical *byte* form is deliberately not an authority-bearing
#: thing (only its shape is contracted, in contracts/registry-schema.json). The
#: digest binds exactly the bytes the Master published without redefining the
#: document's serialisation as a signature input.
#:
#: Why a sequence at all: signatures do not expire on their own, so an attacker
#: who can write to the channel could replay an older, still-valid registry in
#: which a peer was not yet revoked. The sequence turns that replay into a
#: refusal: a peer remembers the highest sequence it has installed and refuses
#: anything not strictly greater. The sequence is inside the signed projection,
#: so it cannot be raised or lowered without the Master's key.
REGISTRY_PUBLICATION_FIELDS = (
    "published_at",
    "registry",
    "registry_sha256",
    "sequence",
)

#: What the Master's signature over a publication covers. `registry` is bound by
#: `registry_sha256`; it is not projected directly.
REGISTRY_PUBLICATION_SIGNED_FIELDS = (
    "published_at",
    "registry_sha256",
    "sequence",
)


def canonical_registry_bytes(registry: dict[str, Any]) -> bytes:
    """The one serialisation a registry digest is computed over."""
    if not isinstance(registry, dict):
        raise AuthzError("a registry must be an object")
    return json.dumps(registry, sort_keys=True, separators=(",", ":")).encode("utf-8")


def registry_digest(registry: dict[str, Any]) -> str:
    """SHA-256 of the canonical registry bytes, hex."""
    return hashlib.sha256(canonical_registry_bytes(registry)).hexdigest()


def registry_publication_message(publication: dict[str, Any]) -> bytes:
    """Canonical bytes a registry-publication signature covers.

    Like ``guard_approval_message`` this is one rule, imported by the signer and
    by every peer that installs a registry, so the two cannot drift apart while
    each keeps working against its own assumption.

    The artifact carries exactly ``REGISTRY_PUBLICATION_FIELDS``. A missing field
    is refused, an extra one is refused, and ``registry_sha256`` must equal the
    digest of the ``registry`` it travels with: a publication whose digest and
    document disagree is refused here, before either side has to remember to
    check it.
    """
    if not isinstance(publication, dict):
        raise AuthzError("a registry publication must be an object")
    missing = [f for f in REGISTRY_PUBLICATION_FIELDS if f not in publication]
    if missing:
        raise AuthzError(f"registry publication missing field(s): {', '.join(missing)}")
    extra = sorted(set(publication) - set(REGISTRY_PUBLICATION_FIELDS))
    if extra:
        raise AuthzError(f"registry publication carries field(s) outside the envelope: {', '.join(extra)}")

    sequence = publication["sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise AuthzError("registry publication 'sequence' must be an integer >= 1")
    published_at = publication["published_at"]
    if not isinstance(published_at, str) or not published_at:
        raise AuthzError("registry publication 'published_at' must be a non-empty string")
    registry = publication["registry"]
    if not isinstance(registry, dict):
        raise AuthzError("registry publication 'registry' must be an object")
    digest = publication["registry_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise AuthzError("registry publication 'registry_sha256' must be 64 lowercase hex characters")
    actual = registry_digest(registry)
    if actual != digest:
        raise AuthzError(
            f"registry publication digest {digest[:16]}... does not match the registry it carries ({actual[:16]}...)"
        )

    projected = {name: publication[name] for name in REGISTRY_PUBLICATION_SIGNED_FIELDS}
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_registry_publication(publication: dict[str, Any], public_key: Ed25519PublicKey) -> str:
    """Verify a publication under the pinned Master key; return its digest.

    Checks the envelope, the signature over the canonical projection, and that
    the registry names the same Master key this node has pinned. That last
    check is not redundant: a document signed by a *different* key would fail
    every entry check anyway, but it would fail with "bad signature", which
    looks like corruption rather than "someone handed me another fabric's
    registry".
    """
    if not isinstance(publication, dict):
        raise AuthzError("a registry publication must be an object")
    signature = publication.get("signature_b64")
    if not isinstance(signature, str) or not signature:
        raise AuthzError("registry publication has no signature")
    # The signature travels beside the envelope; the canonical rule takes the
    # envelope only, so strip it here rather than making every caller do it.
    unsigned = {k: v for k, v in publication.items() if k != "signature_b64"}
    message = registry_publication_message(unsigned)
    if not verify_signature(public_key, signature, message):
        raise AuthzError("registry publication signature does not verify under the pinned Master key")
    claimed = publication["registry"].get("master_public_key_b64")
    if claimed != public_key_b64(public_key):
        raise AuthzError("the registry names a different Master key than the one pinned here")
    return str(publication["registry_sha256"])


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
    "memory_status",
    "memory_policy_set",
    "memory_read",
    "memory_purge",
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
    "memory_query",
    "memory_types",
    "memory_ids",
    "project_id",
    "policy",
    "reason",
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


# --- distillation runs --------------------------------------------------------


#: Fields of a signed same-family distillation run. The run record binds the
#: dataset, teacher/student identities, hyperparameters, evaluation and artifact
#: digest, so a later model card cannot claim a run that did not happen.
DISTILLATION_RUN_FIELDS = (
    "run_id",
    "dataset_id",
    "teacher_model_id",
    "teacher_sha256",
    "student_base_model",
    "student_base_sha256",
    "hyperparameters",
    "eval_metrics",
    "artifact_sha256",
    "decided_by",
    "decided_at",
    "approved",
)

DISTILLATION_RUN_REQUIRED = (
    "run_id",
    "dataset_id",
    "teacher_model_id",
    "student_base_model",
    "artifact_sha256",
    "decided_by",
    "decided_at",
)


def distillation_run_message(run: dict[str, Any]) -> bytes:
    """Canonical bytes signed for a distillation run record."""
    if not isinstance(run, dict):
        raise AuthzError("distillation run must be an object")
    missing = [field for field in DISTILLATION_RUN_REQUIRED if not run.get(field)]
    if missing:
        raise AuthzError(f"distillation run missing required field(s): {', '.join(missing)}")
    projected = {field: run.get(field) for field in DISTILLATION_RUN_FIELDS}
    body = json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return b"sparknet-distillation-run/1\n" + body


def sign_distillation_run(run: dict[str, Any], private_key: Any, *, signed_at: str | None = None) -> dict[str, Any]:
    if not isinstance(run, dict):
        raise AuthzError("distillation run must be an object")
    signed = dict(run)
    signed["signature_b64"] = sign_bytes(private_key, distillation_run_message(run))
    signed["signed_at"] = signed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return signed


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
    "operator_os",
)

#: The OS identity of the human operating the session, attested when the grant is
#: minted. Inside the signed projection because it *caps* what the agent may do:
#: an unsigned one could be widened by whoever presents the grant, which is
#: precisely the privilege the field exists to deny. It is deliberately not the
#: uid of the daemon serving the request — a bridge running as root would then
#: hand every session root, and the cap would be a property of how the node was
#: started rather than of who is driving it.
OPERATOR_OS_FIELDS = ("uid", "euid", "username", "groups", "is_root")


def normalise_operator_os(value: Any) -> dict[str, Any] | None:
    """Canonicalise an attested OS identity, or None when none was attested.

    Strict rather than coercive: the canonical bytes a signature covers must not
    depend on how a caller happened to shape the input, so a wrong type is refused
    instead of silently converted. ``groups`` is sorted and de-duplicated for the
    same reason a grant's capabilities are — two orderings of one set must not
    produce two signatures.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AuthzError("operator_os must be an object or null")
    unknown = sorted(set(value) - set(OPERATOR_OS_FIELDS))
    if unknown:
        raise AuthzError(f"operator_os has undeclared field(s): {', '.join(unknown)}")
    missing = [name for name in OPERATOR_OS_FIELDS if name not in value]
    if missing:
        raise AuthzError(f"operator_os missing field(s): {', '.join(missing)}")
    for name in ("uid", "euid"):
        # bool is an int subclass in Python, so True would otherwise pass as uid 1.
        if isinstance(value[name], bool) or not isinstance(value[name], int):
            raise AuthzError(f"operator_os.{name} must be an integer")
        if value[name] < 0:
            raise AuthzError(f"operator_os.{name} must not be negative")
    if not isinstance(value["username"], str) or not value["username"]:
        raise AuthzError("operator_os.username must be a non-empty string")
    groups = value["groups"]
    if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
        raise AuthzError("operator_os.groups must be a list of strings")
    if not isinstance(value["is_root"], bool):
        raise AuthzError("operator_os.is_root must be a boolean")
    return {
        "uid": value["uid"],
        "euid": value["euid"],
        "username": value["username"],
        "groups": sorted(set(groups)),
        "is_root": value["is_root"],
    }


#: Fields a grant must carry non-empty before it can be canonicalised. The
#: remaining GRANT_FIELDS (`overlay_ipv4`, `vault_scope`, `parent_grant_id`,
#: `operator_os`) may legitimately be empty, so they are projected as null/empty
#: rather than required — empty `vault_scope` is the meaningful "node-level config
#: only", and a null `operator_os` is the meaningful "no OS identity attested",
#: which caps the session at nothing rather than pretending to know it.
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

#: Refusal reasons for the operator-OS ceiling. Kept beside the grant reasons
#: because the check reads a grant field, and a caller that maps reasons to HTTP
#: statuses should not have to import them from two places.
REASON_OPERATOR_UNATTESTED = "operator_unattested"
REASON_OPERATOR_INSUFFICIENT = "operator_insufficient"
REASON_OPERATOR_MALFORMED = "operator_malformed"


def operator_os_authorises(grant: dict[str, Any], *, requires_root: bool) -> tuple[bool, str]:
    """Whether the grant's attested operator identity permits a privileged mutation.

    Returns ``(allowed, reason)``; ``reason`` is empty when allowed. Never raises,
    so a caller cannot turn a missing attestation into an unhandled error and
    thereby into a fail-open path.

    **The attestation authorises.** A grant minter is trusted — minting is
    master-side or an offline operator act, and `operator_os` is inside the
    signature — so an attested ``is_root: true`` permits what root may do even when
    the process serving the request runs as somebody else. That is the whole point
    of putting the ceiling in the grant: it travels with the human rather than with
    the daemon, so how the node happened to be started cannot widen a session.

    Two things this deliberately does not do:

    - It never reads the serving process's own uid. Doing so would let a bridge or
      WebUI container started as root hand every session root.
    - It never treats an absent attestation as permissive. ``operator_os: null``
      means nobody vouched for this session's OS identity, so a privileged mutation
      is refused rather than allowed on the strength of silence.

    A non-privileged operation is always allowed: the ceiling binds what needs
    privilege, and requiring an attestation for an ordinary vault write would make
    the field a precondition of using the node at all.
    """
    if not requires_root:
        return True, ""
    if not isinstance(grant, dict):
        return False, REASON_GRANT_MALFORMED
    attested = grant.get("operator_os")
    if not isinstance(attested, dict):
        return False, REASON_OPERATOR_UNATTESTED
    # is_root is a recorded boolean, never inferred from uid == 0: the two can
    # disagree, and a disagreement is exactly what an enforcement check must not
    # guess about.
    if attested.get("is_root") is True:
        return True, ""
    return False, REASON_OPERATOR_INSUFFICIENT


def encode_operator_os(attested: dict[str, Any] | None) -> str:
    """Canonical-JSON encoding of an OS attestation, for a string-only envelope.

    ``guard_approval_message`` requires every projected field to be a string, so
    the attestation rides a guard approval *encoded* rather than nested. That is a
    feature rather than a workaround: a nested object would need its own
    canonicalisation, and the all-strings rule exists so no caller has to think
    about one.

    Empty means unattested, and that is a **value** here rather than an omission —
    the field must be present in the envelope, and present-but-empty is how this
    envelope already says "legitimately none" for ``content_b64``.
    """
    normalised = normalise_operator_os(attested)
    if normalised is None:
        return ""
    return json.dumps(normalised, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def decode_operator_os(value: Any) -> dict[str, Any] | None:
    """The inverse of :func:`encode_operator_os`. Strict, because it feeds a decision.

    A malformed encoding is refused rather than read as "no attestation". Both
    directions fail closed here — unattested already refuses a privileged mutation
    — but a corrupt encoding that quietly became "none" would be indistinguishable
    in an audit from an approval that never carried one, and the difference is
    whether the Master attested a root operator and the record was lost.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise AuthzError("operator_os must be a canonical-JSON string or empty")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AuthzError(f"operator_os is not valid JSON: {exc}") from exc
    return normalise_operator_os(parsed)


def guard_approval_operator_allows(approval: Any, *, requires_root: bool) -> tuple[bool, str]:
    """The operator-OS ceiling for one guard approval.

    One call for the guard's apply path, so the enforcement point cannot invent a
    second rule: this decodes the envelope's attestation and delegates the decision
    to :func:`operator_os_authorises`, which is the same rule a grant-presenting
    path uses. Two rules for one ceiling would eventually disagree, and the
    disagreement would be visible only as a mutation that one path allowed.
    """
    if not requires_root:
        return True, ""
    if not isinstance(approval, dict):
        return False, REASON_OPERATOR_MALFORMED
    try:
        attested = decode_operator_os(approval.get("operator_os"))
    except AuthzError:
        return False, REASON_OPERATOR_MALFORMED
    return operator_os_authorises({"operator_os": attested}, requires_root=True)


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
    operator_os: dict[str, Any] | None = None,
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
        "operator_os": normalise_operator_os(operator_os),
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


# --- share ratification (Master arbitrates a share) ---------------------------

#: The signed share-ratification artifact. It is deliberately narrow: it records
#: the Master's answer to one accepted share, not a permission and not a trust
#: level. The flag is retained on both approval and refusal because the fact that
#: unapproved data crossed nodes does not disappear when the share is approved.
SHARE_RATIFICATION_FIELDS = (
    "schema_version",
    "share_id",
    "node_id",
    "node_fingerprint",
    "grant_id",
    "decision",
    "reason",
    "accepted_at",
    "deadline",
    "ratified_at",
    "flag_retained",
)
SHARE_RATIFICATION_SCHEMA = "1.0"
SHARE_RATIFICATION_DECISIONS = ("ratified", "refused")


def share_ratification_message(ratification: dict[str, Any]) -> bytes:
    """Canonical bytes the Master's signature over a share ratification covers.

    Closed like the guard approval: an extra field is refused rather than left
    outside the signature. The field list is the contract; a second copy in the
    signer or the peer would be the divergence class this module exists to stop.
    """
    if not isinstance(ratification, dict):
        raise AuthzError("share ratification must be an object")
    extra = set(ratification) - set(SHARE_RATIFICATION_FIELDS) - {"signature_b64"}
    if extra:
        raise AuthzError(f"share ratification carries unsigned field(s): {', '.join(sorted(extra))}")
    missing = [f for f in SHARE_RATIFICATION_FIELDS if f not in ratification]
    if missing:
        raise AuthzError(f"share ratification missing required field(s): {', '.join(missing)}")
    if ratification["schema_version"] != SHARE_RATIFICATION_SCHEMA:
        raise AuthzError(f"share ratification schema_version must be {SHARE_RATIFICATION_SCHEMA}")
    for name in ("share_id", "node_id", "grant_id", "accepted_at", "deadline", "ratified_at"):
        value = ratification.get(name)
        if not isinstance(value, str) or not value.strip():
            raise AuthzError(f"share ratification {name} must be a non-empty string")
    fingerprint_hex = ratification.get("node_fingerprint")
    if not isinstance(fingerprint_hex, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint_hex):
        raise AuthzError("share ratification node_fingerprint must be 64 lowercase hex characters")
    if ratification.get("decision") not in SHARE_RATIFICATION_DECISIONS:
        raise AuthzError(f"share ratification decision must be one of {SHARE_RATIFICATION_DECISIONS}")
    if not isinstance(ratification.get("reason"), str):
        raise AuthzError("share ratification reason must be a string")
    if ratification.get("flag_retained") is not True:
        raise AuthzError("share ratification must retain the flag")
    projected = {field: ratification[field] for field in SHARE_RATIFICATION_FIELDS}
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_share_ratification(ratification: dict[str, Any], master_private_key: Ed25519PrivateKey) -> dict[str, Any]:
    """Sign one share ratification. MASTER-SIDE ONLY."""
    unsigned = {key: value for key, value in ratification.items() if key != "signature_b64"}
    message = share_ratification_message(unsigned)
    return {**unsigned, "signature_b64": sign_bytes(master_private_key, message)}


def verify_share_ratification(ratification: dict[str, Any], master_public_key: Ed25519PublicKey) -> bool:
    """Verify the Master's ratification signature; refuse on any shape error."""
    if not isinstance(ratification, dict):
        return False
    signature = ratification.get("signature_b64")
    if not isinstance(signature, str) or not signature:
        return False
    try:
        message = share_ratification_message(ratification)
    except AuthzError:
        return False
    return verify_signature(master_public_key, signature, message)


# --- trust transitions (a belief, never a permission) -------------------------

#: Trust levels are beliefs, not grants. This signed artifact records a Master
#: decision about one node; it does not move a capability or a registry entry.
TRUST_LEVELS = ("authenticated", "unauthenticated", "flagged")
TRUST_TRANSITION_FIELDS = (
    "schema_version",
    "node_id",
    "level",
    "previous_level",
    "reason",
    "decided_at",
    "reversible",
    "flag_preserved",
)
TRUST_TRANSITION_SCHEMA = "1.0"


def trust_transition_message(transition: dict[str, Any]) -> bytes:
    """Canonical bytes a Master trust-transition signature covers."""
    if not isinstance(transition, dict):
        raise AuthzError("trust transition must be an object")
    extra = set(transition) - set(TRUST_TRANSITION_FIELDS) - {"signature_b64"}
    if extra:
        raise AuthzError(f"trust transition carries unsigned field(s): {', '.join(sorted(extra))}")
    missing = [f for f in TRUST_TRANSITION_FIELDS if f not in transition]
    if missing:
        raise AuthzError(f"trust transition missing required field(s): {', '.join(missing)}")
    if transition["schema_version"] != TRUST_TRANSITION_SCHEMA:
        raise AuthzError(f"trust transition schema_version must be {TRUST_TRANSITION_SCHEMA}")
    if transition.get("level") not in TRUST_LEVELS:
        raise AuthzError(f"trust transition level must be one of {TRUST_LEVELS}")
    previous = transition.get("previous_level")
    if previous is not None and previous not in TRUST_LEVELS:
        raise AuthzError(f"trust transition previous_level must be one of {TRUST_LEVELS} or null")
    for name in ("node_id", "reason", "decided_at"):
        value = transition.get(name)
        if not isinstance(value, str) or not value.strip():
            raise AuthzError(f"trust transition {name} must be a non-empty string")
    if transition.get("reversible") is not True:
        raise AuthzError("trust transition must be reversible")
    if transition.get("flag_preserved") is not True:
        raise AuthzError("trust transition must preserve the flag")
    projected = {field: transition[field] for field in TRUST_TRANSITION_FIELDS}
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_trust_transition(transition: dict[str, Any], master_private_key: Ed25519PrivateKey) -> dict[str, Any]:
    """Sign one trust transition. MASTER-SIDE ONLY."""
    unsigned = {key: value for key, value in transition.items() if key != "signature_b64"}
    message = trust_transition_message(unsigned)
    return {**unsigned, "signature_b64": sign_bytes(master_private_key, message)}


def verify_trust_transition(transition: dict[str, Any], master_public_key: Ed25519PublicKey) -> bool:
    """Verify a Master trust-transition signature; refuse on any shape error."""
    if not isinstance(transition, dict):
        return False
    signature = transition.get("signature_b64")
    if not isinstance(signature, str) or not signature:
        return False
    try:
        message = trust_transition_message(transition)
    except AuthzError:
        return False
    return verify_signature(master_public_key, signature, message)


# --- RFI answers (request for information) ------------------------------------

#: The whole RFI answer artifact. `content_b64` is in the field list but not in the
#: signed projection: the content is bound by `content_sha256` instead, so an answer
#: can be large without the projection having to carry it.
RFI_ANSWER_FIELDS = (
    "answered_at",
    "content_b64",
    "content_sha256",
    "item_name",
    "peer_fingerprint",
    "request_id",
)

#: What the Master's signature covers.
RFI_ANSWER_SIGNED_FIELDS = (
    "answered_at",
    "content_sha256",
    "item_name",
    "peer_fingerprint",
    "request_id",
)

#: Fields that must be present and non-empty. `content_b64` is deliberately absent:
#: an empty answer is a legitimate one ("nothing found"), and refusing it would push
#: a Master toward inventing content to fill the field.
RFI_ANSWER_REQUIRED = (
    "answered_at",
    "content_sha256",
    "item_name",
    "peer_fingerprint",
    "request_id",
)

#: Refusal reasons, named by contracts/rfi-schema.json `refusals`. Fixed strings:
#: a caller maps them to an HTTP status and an operator greps a ledger for them, so
#: neither may vary with the artifact that was refused.
REASON_RFI_MALFORMED = "malformed"
REASON_RFI_EXTRA_FIELDS = "extra_fields"
REASON_RFI_MISSING_FIELDS = "missing_fields"
REASON_RFI_BAD_SIGNATURE = "bad_signature"
REASON_RFI_DIGEST_MISMATCH = "digest_mismatch"
REASON_RFI_WRONG_PEER = "wrong_peer"
REASON_RFI_UNSAFE_ITEM_NAME = "unsafe_item_name"
REASON_RFI_EXPIRED = "expired"
REASON_RFI_DUPLICATE = "duplicate_answer"


def check_rfi_item_name(name: Any) -> str:
    """A single safe path component under ``01_Inbox/``, or a refusal.

    The answer is *written* to this name, so the check is a path-traversal guard
    and not a style preference. A separator, a parent reference or a leading dot
    would let the destination be chosen by whoever composed the name — which is why
    `item_name` is inside the signed projection rather than beside it.
    """
    if not isinstance(name, str) or not name:
        raise AuthzError("item_name must be a non-empty string")
    if "/" in name or "\\" in name or name in (".", "..") or ".." in name or name.startswith("."):
        raise AuthzError(f"item_name must be a single safe path component, got {name!r}")
    return name


def rfi_answer_message(answer: dict[str, Any]) -> bytes:
    """Canonical bytes an RFI answer's signature covers.

    The same anti-drift rule as every other envelope here: one projection function,
    imported by the signer and by every verifier, strict in both directions. A
    missing field would authorise an answer with no named destination; an extra one
    would be unsigned data riding inside an artifact that a peer treats as
    authoritative.

    `signature_b64` travels beside the projection in the same artifact, so it is
    permitted on the dict without being part of what is signed.
    """
    if not isinstance(answer, dict):
        raise AuthzError("rfi answer must be an object")
    missing = [f for f in RFI_ANSWER_REQUIRED if not answer.get(f)]
    if missing:
        raise AuthzError(f"rfi answer missing required field(s): {', '.join(missing)}")
    absent = [f for f in RFI_ANSWER_FIELDS if f not in answer]
    if absent:
        raise AuthzError(f"rfi answer missing field(s): {', '.join(absent)}")
    extra = sorted(set(answer) - set(RFI_ANSWER_FIELDS) - {"signature_b64"})
    if extra:
        raise AuthzError(f"rfi answer carries field(s) outside the canonical envelope: {', '.join(extra)}")
    check_rfi_item_name(answer["item_name"])
    projected = {name: answer[name] for name in sorted(RFI_ANSWER_SIGNED_FIELDS)}
    for name, value in projected.items():
        if not isinstance(value, str):
            raise AuthzError(f"rfi answer field {name!r} must be a string")
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_rfi_answer(
    *,
    content: bytes,
    item_name: str,
    peer_fingerprint: str,
    request_id: str,
    master_private_key: Ed25519PrivateKey,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a signed RFI answer. MASTER-SIDE ONLY — needs the Master private key.

    The peer never calls this, and a peer that could would be able to write
    attributed material into its own inbox, which is the one thing the channel
    exists to prevent.
    """
    if not isinstance(content, bytes):
        raise AuthzError("content must be bytes")
    if not peer_fingerprint or not request_id:
        raise AuthzError("peer_fingerprint and request_id are both required")
    check_rfi_item_name(item_name)
    moment = now or datetime.now(timezone.utc)
    answer: dict[str, Any] = {
        "answered_at": moment.isoformat().replace("+00:00", "Z"),
        "content_b64": base64.b64encode(content).decode("ascii"),
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "item_name": item_name,
        "peer_fingerprint": peer_fingerprint,
        "request_id": request_id,
    }
    answer["signature_b64"] = base64.b64encode(master_private_key.sign(rfi_answer_message(answer))).decode("ascii")
    return answer


def verify_rfi_answer(
    answer: Any,
    *,
    master_public_key: Ed25519PublicKey,
    peer_fingerprint: str,
    now: datetime | None = None,
    ttl_seconds: int = 3600,
    installed_request_ids: Any = (),
) -> tuple[bool, str, bytes]:
    """Verify one RFI answer. Returns ``(ok, reason, content)``.

    Never raises for a refused answer: a caller that had to catch exceptions to
    refuse would eventually catch one too few, and the refusal vocabulary is the
    point of the check. ``content`` is empty unless ``ok``.

    The order matters and is the one `contracts/rfi-schema.json` states. The
    signature is checked before the digest because a digest mismatch on an unsigned
    artifact is not a fact about the Master; the peer is checked before the item
    name because an answer addressed to another node should be refused as such
    rather than as badly named.
    """
    if not isinstance(answer, dict):
        return False, REASON_RFI_MALFORMED, b""
    extra = sorted(set(answer) - set(RFI_ANSWER_FIELDS) - {"signature_b64"})
    if extra:
        return False, REASON_RFI_EXTRA_FIELDS, b""
    absent = [f for f in RFI_ANSWER_FIELDS if f not in answer]
    if absent:
        return False, REASON_RFI_MISSING_FIELDS, b""

    signature_b64 = answer.get("signature_b64")
    if not isinstance(signature_b64, str) or not signature_b64:
        return False, REASON_RFI_BAD_SIGNATURE, b""
    try:
        message = rfi_answer_message(answer)
    except AuthzError:
        return False, REASON_RFI_MALFORMED, b""
    try:
        if not verify_signature(master_public_key, signature_b64, message):
            return False, REASON_RFI_BAD_SIGNATURE, b""
    except AuthzError:
        return False, REASON_RFI_BAD_SIGNATURE, b""

    try:
        content = decode_b64_strict(str(answer.get("content_b64") or ""), what="rfi answer content")
    except AuthzError:
        return False, REASON_RFI_MALFORMED, b""
    if hashlib.sha256(content).hexdigest() != answer["content_sha256"]:
        return False, REASON_RFI_DIGEST_MISMATCH, b""

    if answer["peer_fingerprint"] != peer_fingerprint:
        return False, REASON_RFI_WRONG_PEER, b""
    try:
        check_rfi_item_name(answer["item_name"])
    except AuthzError:
        return False, REASON_RFI_UNSAFE_ITEM_NAME, b""

    try:
        answered = datetime.fromisoformat(str(answer["answered_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False, REASON_RFI_EXPIRED, b""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    age = (moment - answered).total_seconds()
    if age > ttl_seconds or age < -ttl_seconds:
        return False, REASON_RFI_EXPIRED, b""

    if answer["request_id"] in set(installed_request_ids or ()):
        return False, REASON_RFI_DUPLICATE, b""
    return True, "", content


# --- RFI requests (peer -> Master, overlay-attributed) --------------------------
#
# A request is NOT signed, unlike every other envelope here. See
# RFI_REQUEST_DESIGN.md (fabric Step 68A): nothing in the fabric binds a peer
# fingerprint to a node *signing* public key (the identity carries a Curve25519
# WireGuard key, which cannot verify an Ed25519 signature), so the Master has no
# attested key to check a request signature against. Attribution rides the
# authenticated overlay instead — the Master derives the sender's fingerprint from
# the WireGuard source address via its own registry and refuses a body whose
# `peer_fingerprint` disagrees. A signature it could not verify would be theatre.

#: The whole RFI request body. `scope` may be empty (a request that may draw on
#: nothing still parses; the Master answers "nothing found"), so it is type-checked
#: rather than required non-empty.
RFI_REQUEST_FIELDS = (
    "expires_at",
    "issued_at",
    "nonce",
    "peer_fingerprint",
    "question",
    "request_id",
    "scope",
)

#: Fields that must be present and non-empty strings.
RFI_REQUEST_REQUIRED = (
    "expires_at",
    "issued_at",
    "nonce",
    "peer_fingerprint",
    "question",
    "request_id",
)

#: Refusal reasons for a request. Fixed strings, like the answer's: a caller maps
#: them to an HTTP status and an operator greps a log for them, so neither may vary
#: with the artifact that was refused.
REASON_RFI_REQ_MALFORMED = "malformed"
REASON_RFI_REQ_WRONG_PEER = "wrong_peer"
REASON_RFI_REQ_EXPIRED = "expired"
REASON_RFI_REQ_NOT_YET_VALID = "not_yet_valid"
REASON_RFI_REQ_REPLAYED = "replayed_nonce"


def build_rfi_request(
    *,
    request_id: str,
    peer_fingerprint: str,
    question: str,
    scope: list[str] | None = None,
    now: datetime | None = None,
    ttl_seconds: int = 300,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Build an RFI request body (unsigned — see the section note above).

    The peer sends this to the Master's overlay-only request listener. ``nonce``
    plus ``expires_at`` are the replay guard that a signed envelope's freshness
    fields would otherwise provide; ``scope`` is sorted+deduplicated so two
    orderings of one allow-list cannot produce two different requests.
    """
    if not request_id or not peer_fingerprint:
        raise AuthzError("request_id and peer_fingerprint are both required")
    if not isinstance(question, str) or not question.strip():
        raise AuthzError("question must be a non-empty string")
    if scope is not None and (not isinstance(scope, list) or any(not isinstance(s, str) for s in scope)):
        raise AuthzError("scope must be a list of vault-category strings")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return {
        "request_id": str(request_id),
        "peer_fingerprint": str(peer_fingerprint),
        "question": question,
        "scope": sorted(set(scope or [])),
        "issued_at": moment.isoformat().replace("+00:00", "Z"),
        "expires_at": (moment + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z"),
        "nonce": nonce or secrets.token_hex(16),
    }


def verify_rfi_request(
    request: Any,
    *,
    expected_fingerprint: str,
    now: datetime | None = None,
    seen_nonces: Any = (),
    max_skew_seconds: int = 300,
) -> tuple[bool, str]:
    """Validate one RFI request and match it to the overlay-derived fingerprint.

    Returns ``(ok, reason)`` and never raises — a caller that had to catch to refuse
    would eventually catch one too few. This is **not** a signature check; there is
    no signature. ``expected_fingerprint`` is the fingerprint the Master derived
    from the WireGuard-authenticated source address (its registry maps
    ``overlay_ipv4 -> fingerprint``); a request whose ``peer_fingerprint`` field
    disagrees is refused as ``wrong_peer``, so a peer cannot ask as another peer.

    The order is the contract's: shape, then attribution, then freshness, then
    replay. Attribution precedes expiry because *who* is asking is the more
    specific fact, and a stale request from the right peer is a different refusal
    than a fresh one from an impostor.
    """
    if not isinstance(request, dict):
        return False, REASON_RFI_REQ_MALFORMED
    if set(request) != set(RFI_REQUEST_FIELDS):
        return False, REASON_RFI_REQ_MALFORMED
    for field_name in RFI_REQUEST_REQUIRED:
        value = request.get(field_name)
        if not isinstance(value, str) or not value:
            return False, REASON_RFI_REQ_MALFORMED
    scope = request.get("scope")
    if not isinstance(scope, list) or any(not isinstance(s, str) for s in scope):
        return False, REASON_RFI_REQ_MALFORMED

    if request["peer_fingerprint"] != expected_fingerprint:
        return False, REASON_RFI_REQ_WRONG_PEER

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        issued = datetime.fromisoformat(str(request["issued_at"]).replace("Z", "+00:00"))
        expires = datetime.fromisoformat(str(request["expires_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False, REASON_RFI_REQ_EXPIRED
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= moment:
        return False, REASON_RFI_REQ_EXPIRED
    if (issued - moment).total_seconds() > max_skew_seconds:
        return False, REASON_RFI_REQ_NOT_YET_VALID

    if request["nonce"] in set(seen_nonces or ()):
        return False, REASON_RFI_REQ_REPLAYED
    return True, ""


# --- telemetry reports (peer -> Master observability, overlay-attributed) -------
#
# Phase 4 is Master observability WITHOUT touching the data path: peers push signed
# evidence, the Master never intercepts. A report is attributed by the authenticated
# overlay exactly like an RFI request (see MASTER_OBSERVABILITY_DESIGN.md and
# RFI_REQUEST_DESIGN.md, Step 68A) — the Master derives the sender's fingerprint from
# the WireGuard source via its registry, so there is no node-key signature and no
# sign_telemetry_report. Telemetry carries NO authority: it informs, records, surfaces
# and flags; it never grants, revokes, escalates, widens or approves.

#: The whole telemetry report body.
TELEMETRY_REPORT_FIELDS = (
    "expires_at",
    "issued_at",
    "kind",
    "nonce",
    "payload",
    "peer_fingerprint",
)

#: Fields that must be present and non-empty strings. `payload` is checked separately
#: (it is an object, and an empty object is legitimate).
TELEMETRY_REPORT_REQUIRED = (
    "expires_at",
    "issued_at",
    "kind",
    "nonce",
    "peer_fingerprint",
)

#: A closed vocabulary. `kind` routes the report to what records it; the per-kind
#: payload's meaning is the consumer sub-step's contract, not the envelope's, so a new
#: kind's internals never reshape the envelope.
TELEMETRY_KINDS = ("status", "metrics", "liveness", "checkpoint_anchor", "inbox_alert")

#: Refusal reasons, named by contracts/telemetry-schema.json `refusals`. Fixed strings,
#: like every other envelope's: a caller maps them to an HTTP status and an operator
#: greps a log for them. `off_overlay` is the listener's source gate, not a return here.
REASON_TELEMETRY_MALFORMED = "malformed"
REASON_TELEMETRY_WRONG_PEER = "wrong_peer"
REASON_TELEMETRY_EXPIRED = "expired"
REASON_TELEMETRY_NOT_YET_VALID = "not_yet_valid"
REASON_TELEMETRY_REPLAYED = "replayed_nonce"


def build_telemetry_report(
    *,
    kind: str,
    peer_fingerprint: str,
    payload: dict[str, Any] | None = None,
    now: datetime | None = None,
    ttl_seconds: int = 120,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Build a telemetry report body (unsigned — see the section note above).

    The peer pushes this to the Master's intake listener. ``payload`` is opaque to the
    envelope (any JSON object; empty is legitimate — a heartbeat says "alive" with no
    content). ``nonce`` plus ``expires_at`` are the replay/freshness guard.
    """
    if kind not in TELEMETRY_KINDS:
        raise AuthzError(f"kind must be one of {TELEMETRY_KINDS}, got {kind!r}")
    if not peer_fingerprint:
        raise AuthzError("peer_fingerprint is required")
    if payload is not None and not isinstance(payload, dict):
        raise AuthzError("payload must be a JSON object")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return {
        "kind": str(kind),
        "peer_fingerprint": str(peer_fingerprint),
        "payload": dict(payload or {}),
        "issued_at": moment.isoformat().replace("+00:00", "Z"),
        "expires_at": (moment + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z"),
        "nonce": nonce or secrets.token_hex(16),
    }


def verify_telemetry_report(
    report: Any,
    *,
    expected_fingerprint: str,
    now: datetime | None = None,
    seen_nonces: Any = (),
    max_skew_seconds: int = 300,
) -> tuple[bool, str]:
    """Validate one telemetry report and match it to the overlay-derived fingerprint.

    Returns ``(ok, reason)`` and never raises. This is **not** a signature check; there
    is no signature. ``expected_fingerprint`` is the fingerprint the Master derived from
    the WireGuard-authenticated source address; a report whose ``peer_fingerprint``
    disagrees is refused as ``wrong_peer``, so a peer cannot report as another peer.
    The order is shape, then attribution, then freshness, then replay — the same order
    the RFI request uses, so *who* is asking is answered before *whether it is stale*.
    """
    if not isinstance(report, dict):
        return False, REASON_TELEMETRY_MALFORMED
    if set(report) != set(TELEMETRY_REPORT_FIELDS):
        return False, REASON_TELEMETRY_MALFORMED
    for field_name in TELEMETRY_REPORT_REQUIRED:
        value = report.get(field_name)
        if not isinstance(value, str) or not value:
            return False, REASON_TELEMETRY_MALFORMED
    if report["kind"] not in TELEMETRY_KINDS:
        return False, REASON_TELEMETRY_MALFORMED
    if not isinstance(report.get("payload"), dict):
        return False, REASON_TELEMETRY_MALFORMED

    if report["peer_fingerprint"] != expected_fingerprint:
        return False, REASON_TELEMETRY_WRONG_PEER

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        issued = datetime.fromisoformat(str(report["issued_at"]).replace("Z", "+00:00"))
        expires = datetime.fromisoformat(str(report["expires_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False, REASON_TELEMETRY_EXPIRED
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= moment:
        return False, REASON_TELEMETRY_EXPIRED
    if (issued - moment).total_seconds() > max_skew_seconds:
        return False, REASON_TELEMETRY_NOT_YET_VALID

    if report["nonce"] in set(seen_nonces or ()):
        return False, REASON_TELEMETRY_REPLAYED
    return True, ""


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

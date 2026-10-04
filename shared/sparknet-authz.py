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
import hashlib
import json
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
KNOWN_CAPABILITIES = frozenset({"telemetry", "p2p-sync", "push-receive", "guard-apply"})

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
        try:
            candidates.append(base64.b64decode(stripped, validate=True))
        except Exception:
            pass
        try:
            candidates.append(bytes.fromhex(stripped.decode("ascii")))
        except (ValueError, UnicodeDecodeError):
            pass
    if len(blob) == 32:
        candidates.append(blob)

    for raw in candidates:
        if len(raw) == 32:
            return Ed25519PrivateKey.from_private_bytes(raw)
    raise AuthzError(f"Ed25519 private key in {path} is not 32 raw bytes, base64, or hex")


def verify_signature(public_key: Ed25519PublicKey, signature_b64: str, message: bytes) -> bool:
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception:
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


# --- CLI ---------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sparknet node authorization (SHA-256 + Ed25519)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    fp = sub.add_parser("fingerprint", help="Print the SHA-256 fingerprint of an identity file")
    fp.add_argument("identity", type=Path)

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

    args = parser.parse_args(argv)

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

    return 2


if __name__ == "__main__":
    raise SystemExit(_main())

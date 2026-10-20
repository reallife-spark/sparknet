#!/usr/bin/env python3
"""Optional out-of-band bootstrap for one share stanza — the EAP-NOOB scaffold.

Why this exists.  NVIDIA PAIR pairs its nodes with EAP-NOOB (RFC 9140): the two
ends share a short code over an out-of-band channel and derive ephemeral keys
from it, bootstrapping a trust between nodes that have never spoken.  Sparknet
does not need that for *authority* — the roster/election are the trust root, and
authority comes from key possession — but a share-stanza (ports 4201-4203) is
data-plane, and a node that wants to hold a time-boxed stanza secret without
going through a full grant ceremony can seed one by sharing a code OOB.

What this module is, and is not.  It is a **scaffold**: it provides the OOB
value, the HKDF derivation and the validity envelope, and nothing else.  It
never touches the registry, an approval, an election, or the operational key.
The envelope carries ``scope: share-stanza`` and ``not_authority: true`` so
nothing downstream can mistake it for a grant.  The roster/election remain the
only way to acquire any authority.

One security note must be stated, not implied.  A 6-digit code (RFC 9140's
size) is an *authentication signal*, not secret entropy: EAP-NOOB's security
premise is that the code travelled over an out-of-band channel an attacker
cannot both read and write.  The HKDF below mixes the code into a key, but it
does not and cannot add entropy.  In production this scaffold is only meant to
seed a continuation from a *longer* hand-carried secret, or to ride on the
roster — that is precisely why it is optional and time-boxed, and why it is
never an authority credential.

Everything here is clock-injected, like the election and transport modules, so
a test can expire a stanza without sleeping.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
except ImportError as exc:  # pragma: no cover - environment guard
    import sys

    print(
        f"[oob] FATAL: the 'cryptography' package is required ({exc}).\n"
        f"[oob] Install it with:  make devtools   (or: pip install 'cryptography>=42')",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

OOB_PREFIX = b"sparknet-oob/1"
SCOPE_STANZA = "share-stanza"
OOB_DIGITS = 6
STANZA_TTL_SECONDS = 3600
KEY_BYTES = 32

#: Stable reasons, mirroring the transport's refusal convention.
REASON_OK = "ok"
REASON_UNKNOWN = "unknown_stanza"
REASON_MALFORMED = "malformed_envelope"
REASON_EXPIRED = "stanza_expired"
REASON_CONTEXT = "context_mismatch"
REASON_BAD_SCOPE = "not_a_stanza_credential"


class StanzaBootstrapError(Exception):
    """Raised for a malformed or refusable second hand of a stanza bootstrap.

    Carries a stable ``reason`` so a caller can map it to a refusal without
    parsing prose.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_oob() -> str:
    """A hand-carried RFC 9140-style code: fixed digits, cryptographic RNG."""
    return f"{secrets.randbelow(10**OOB_DIGITS):0{OOB_DIGITS}d}"


def _context_digest(context: bytes) -> str:
    return hashlib.sha256(context).hexdigest()


def derive_stanza_key(
    oob: str,
    context: bytes,
    *,
    now: datetime | None = None,
    ttl_seconds: int = STANZA_TTL_SECONDS,
) -> dict[str, Any]:
    """Derive a time-boxed, scope-locked stanza secret from the OOB code.

    ``context`` binds the derivation to one exchange — the two peer
    fingerprints, or the share offer id — so a code reused across contexts
    yields different keys.  The output envelope is deliberately self-describing
    and carries no authority: ``scope`` is ``share-stanza`` and ``not_authority``
    is ``true``.
    """
    if len(oob) != OOB_DIGITS or not oob.isdigit():
        raise StanzaBootstrapError(REASON_MALFORMED, f"OOB code must be {OOB_DIGITS} digits")
    stamp = now or _utc_now()
    if stamp.tzinfo is None:
        raise StanzaBootstrapError(REASON_MALFORMED, "now must be timezone-aware")

    valid_until = stamp + timedelta(seconds=ttl_seconds)
    salt = hashlib.sha256(context).digest()
    info = OOB_PREFIX + b"/" + SCOPE_STANZA.encode("ascii")
    hkdf = HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, info=info)
    key_bytes = hkdf.derive(oob.encode("ascii"))

    return {
        "scope": SCOPE_STANZA,
        "oob_sha256": hashlib.sha256(oob.encode("ascii")).hexdigest(),
        "context_sha256": _context_digest(context),
        "valid_from": stamp.isoformat(),
        "valid_until": valid_until.isoformat(),
        "ttl_seconds": ttl_seconds,
        "key_b64": base64.b64encode(key_bytes).decode("ascii"),
        "not_authority": True,
    }


def verify_stanza(
    envelope: dict[str, Any],
    context: bytes,
    *,
    now: datetime | None = None,
) -> str:
    """Is this envelope usable *now* for that context? Returns a stable reason.

    ``REASON_OK`` means: it is a stanza credential (not an authority claim), it
    belongs to the given context, and it has not expired.  A refusal reason
    means the envelope must be tossed, never half-used.
    """
    stamp = now or _utc_now()
    try:
        scope = envelope["scope"]
        context_sha = envelope["context_sha256"]
        valid_until = envelope["valid_until"]
        not_authority = envelope["not_authority"]
    except (KeyError, TypeError):
        return REASON_MALFORMED

    if scope != SCOPE_STANZA or not_authority is not True:
        return REASON_BAD_SCOPE
    if context_sha != _context_digest(context):
        return REASON_CONTEXT
    parsed = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
    if parsed < stamp:
        return REASON_EXPIRED
    return REASON_OK


def make_handoff(envelope: dict[str, Any]) -> bytes:
    """The wire bytes to send: the envelope without the containing secret echoed
    in plaintext besides its hash.  The OOB code itself is never carried.

    The key is decoded strictly (``validate=True``): this is the one secret the
    handoff carries, and a tolerant decode would let a malformed ``key_b64``
    produce a shorter key that quietly weakens the derived shared secret. An
    invalid encoding must fail here, not downstream.
    """
    return base64.b64decode(envelope["key_b64"], validate=True)


if __name__ == "__main__":
    import sys

    if "-h" in sys.argv or "--help" in sys.argv:
        # Exit 0 on stdout: a usage request is a success, not a failure. The
        # fallback below stays exit 1 because it means "you passed something
        # this tool does not understand".
        print(
            "usage: sparknet-oob.py --self-test | --help\n"
            "\n"
            "--self-test  derive a stanza key from a fixed code+context and\n"
            "             verify it (prints reason=ok and the handoff key length)\n"
            "--help       print this text and exit\n"
            "\n"
            "Library: generate_oob, derive_stanza_key, verify_stanza, make_handoff."
        )
        sys.exit(0)
    if "--self-test" in sys.argv:
        code = generate_oob()
        ctx = b"peer-a\x00peer-b\x00offer-123"
        env = derive_stanza_key(code, ctx)
        print(f"self-test: oob={code} reason={verify_stanza(env, ctx)} key_len={len(make_handoff(env))}")
        sys.exit(0)
    print(f"usage: {sys.argv[0]} --self-test", file=sys.stderr)
    sys.exit(1)

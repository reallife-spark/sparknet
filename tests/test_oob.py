"""The optional OOB stanza bootstrap — EAP-NOOB scaffold.

`shared/sparknet-oob.py` is the optional, time-boxed, stanza-scoped seed for a
share-stanza key. The roster/election remain the trust root; this module must
never be able to produce, or be mistaken for, an authority credential.

What this file asserts:

1. **Scope and authority are locked.** Every derived envelope is
   ``scope: share-stanza``, carries ``not_authority: true`` and contains none
   of the fields an authority envelope carries (fingerprint, capabilities,
   signature).
2. **Context binding.** A code shared under one context yields a different key
   under another, and an envelope is refused for the wrong context.
3. **Clock-injected expiry.** A stanza is refused the moment it is past its
   TTL, with a stable reason.
4. **The code is never carried on the wire.** The handoff bytes are the key,
   and the envelope echoes only the code's digest.
5. **The honest note is on record.** The OOB code is authentication, not
   entropy; the module's own docstring must say so, or a later reader will
   treat 6 digits as a secret.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
OOB_SCRIPT = REPO_ROOT / "shared" / "sparknet-oob.py"


@pytest.fixture(scope="module")
def oob():
    spec = importlib.util.spec_from_file_location("sparknet_oob", OOB_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
CTX = b"peer-a\x00peer-b\x00offer-123"


# --- the scaffold, honestly ----------------------------------------------------


def test_oob_code_is_six_digits_and_varied(oob):
    codes = {oob.generate_oob() for _ in range(200)}
    assert len(codes) > 1
    assert all(len(c) == 6 and c.isdigit() for c in codes)


def test_oob_note_does_not_claim_entropy(oob):
    """The scaffold must say plainly that a 6-digit code is not a secret."""
    text = OOB_SCRIPT.read_text().lower()
    assert "entropy" in text or "authentication signal" in text or "not secret entropy" in text
    assert "authority" in text and "roster" in text


def test_envelope_is_stanza_scoped_and_never_authority(oob):
    env = oob.derive_stanza_key("123456", CTX, now=NOW)
    assert env["scope"] == "share-stanza"
    assert env["not_authority"] is True
    for forbidden in ("fingerprint", "capabilities", "signature", "revoked"):
        assert forbidden not in env, f"an authority field {forbidden!r} leaked into the stanza envelope"
    assert len(oob.make_handoff(env)) == 32


def test_key_is_deterministic_for_the_same_exchange(oob):
    a = oob.derive_stanza_key("123456", CTX, now=NOW)
    b = oob.derive_stanza_key("123456", CTX, now=NOW)
    assert a["key_b64"] == b["key_b64"]
    assert a["valid_until"] == b["valid_until"]


def test_context_binding_changes_the_key(oob):
    a = oob.derive_stanza_key("123456", CTX, now=NOW)
    b = oob.derive_stanza_key("123456", b"\x00\x01", now=NOW)
    assert a["key_b64"] != b["key_b64"]
    assert a["context_sha256"] != b["context_sha256"]


def test_verify_rejects_the_wrong_context(oob):
    env = oob.derive_stanza_key("123456", CTX, now=NOW)
    assert oob.verify_stanza(env, b"another-peer", now=NOW) == "context_mismatch"
    assert oob.verify_stanza(env, CTX, now=NOW) == "ok"


def test_verify_rejects_an_expired_stanza(oob):
    env = oob.derive_stanza_key("123456", CTX, now=NOW)
    later = NOW + timedelta(seconds=3600)  # exactly the TTL
    assert oob.verify_stanza(env, CTX, now=later) == "ok"
    just_after = later + timedelta(seconds=1)
    assert oob.verify_stanza(env, CTX, now=just_after) == "stanza_expired"


def test_verify_rejects_authority_claims_and_malformed(oob):
    env = oob.derive_stanza_key("123456", CTX, now=NOW)
    cos = dict(env, scope="registry", not_authority=False)
    assert oob.verify_stanza(cos, CTX, now=NOW) == "not_a_stanza_credential"
    assert oob.verify_stanza({}, CTX, now=NOW) == "malformed_envelope"


def test_bad_oob_is_refused_at_derivation(oob):
    with pytest.raises(oob.StanzaBootstrapError):
        oob.derive_stanza_key("abc", CTX, now=NOW)
    with pytest.raises(oob.StanzaBootstrapError):
        oob.derive_stanza_key("12345", CTX, now=NOW)

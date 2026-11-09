#!/usr/bin/env python3
"""Sparknet provenance notes: the note envelope, co-signatures, user record, shims and inbox intake.

This lifecycle module loads only ``sparknet-provenance-base.py``. It owns the
one note message and note signature implementation, the user-record lifecycle,
co-signatures, layout shims and inbox intake. It does not know about the ledger
or grants; callers reach it through the facade.
"""

from __future__ import annotations

import json
import os
import re
import sys
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
        "note lifecycle does not carry a fallback. Set SPARKNET_SHARED_DIR."
    ),
)
ProvenanceError = _base.ProvenanceError
FrontmatterError = _base.FrontmatterError
parse_yaml_subset = _base.parse_yaml_subset
emit_yaml = _base.emit_yaml
_split_frontmatter = _base._split_frontmatter
FINGERPRINT_RE = _base.FINGERPRINT_RE
OWNER_ID_RE = _base.OWNER_ID_RE
USER_RECORD_REF = _base.USER_RECORD_REF
_PATTERNS = _base._PATTERNS
_find_vault_from_cwd = _base._find_vault_from_cwd
_iso = _base._iso
_load_abac = _base._load_abac
_load_authz = _base._load_authz
_load_merkle = _base._load_merkle
_node_id = _base._node_id
_now = _base._now
_refuse_loose_key = _base._refuse_loose_key
_state_dir = _base._state_dir
_user_key_path = _base._user_key_path
canonical_json = _base.canonical_json
contract = _base.contract
fingerprint_label_of_public_b64 = _base.fingerprint_label_of_public_b64
fingerprint_of_public_b64 = _base.fingerprint_of_public_b64
sha256_hex = _base.sha256_hex

NOTE_VERSION = "sparknet-note/2"

NOTE_DOMAIN = NOTE_VERSION.encode("ascii")

USER_RECORD_KEYS = frozenset(
    {
        "type",
        "schema",
        "status",
        "owner_id",
        "owner_node",
        "role",
        "immutable",
        "key",
        "authorised_senders",
    }
)

USER_KEY_FIELDS = frozenset({"alg", "public_key_b64", "fingerprint", "key_ref", "created"})

CO_SIGNATURE_FIELDS = (
    "alg",
    "owner_id",
    "owner_node",
    "public_key_b64",
    "key_fingerprint",
    "sig",
    "signed_at",
)

_RECORDED_HASH_FIELDS = ("body", "meta", "tracking", "conversation")

INGEST_SOURCES = ("master-node", "peer-node", "email")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def split_note(raw: bytes) -> tuple[dict[str, Any], bytes]:
    """Parse a note into (frontmatter mapping, body bytes)."""
    fm_bytes, body = _split_frontmatter(raw)
    return parse_yaml_subset(fm_bytes.decode("utf-8")), body


def emit_note(frontmatter: dict[str, Any], body: bytes) -> bytes:
    return b"---\n" + emit_yaml(frontmatter).encode("utf-8") + b"---\n" + body


def meta_of(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """Everything in the frontmatter except tracking — the compiler's own field zone."""
    return {k: v for k, v in frontmatter.items() if k != "tracking"}


def tracking_of(frontmatter: dict[str, Any]) -> dict[str, Any]:
    tracking = frontmatter.get("tracking")
    if not isinstance(tracking, dict):
        raise FrontmatterError("note has no `tracking` block (contracts/tracking-schema.json)")
    return tracking


def unsigned_tracking(tracking: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in tracking.items() if k != "signature"}


def build_conversation_root(conversation: Any) -> str:
    """The RFC 6962 root of the canonical `tracking.conversation` entries.

    One leaf per entry, the entry's canonical JSON bytes, so the root commits to
    the who/when/which-model trail the same way a checkpoint commits to the
    ledger. An empty (or absent) conversation is the empty tree's root, not an
    error: a note written before any turn is still signable.
    """
    entries = conversation if isinstance(conversation, list) else []
    return _load_merkle().merkle_root([canonical_json(entry) for entry in entries])


def note_hashes(meta: dict[str, Any], tracking: dict[str, Any], body: bytes) -> dict[str, str]:
    return {
        "body": sha256_hex(body),
        "meta": sha256_hex(canonical_json(meta)),
        "tracking": sha256_hex(canonical_json(unsigned_tracking(tracking))),
        "conversation": build_conversation_root(tracking.get("conversation")),
    }


def note_message(hashes: dict[str, str]) -> bytes:
    """What the user key signs over: domain, then the four hashes, LF-joined."""
    return (
        NOTE_DOMAIN
        + b"\n"
        + hashes["body"].encode("ascii")
        + b"\n"
        + hashes["meta"].encode("ascii")
        + b"\n"
        + hashes["tracking"].encode("ascii")
        + b"\n"
        + hashes["conversation"].encode("ascii")
    )


def user_record_path(vault: Path) -> Path:
    return vault / "00_System" / "user.md"


def parse_user_record(vault: Path) -> dict[str, Any]:
    path = user_record_path(vault)
    if not path.is_file():
        raise ProvenanceError(f"missing {path}; the vault has no user record")
    frontmatter, _ = split_note(path.read_bytes())
    return frontmatter


def user_is_filled(record: dict[str, Any]) -> bool:
    """Filled means: the number, the key and the fingerprint are all real.

    Strict on purpose — `user_init` and every verification depend on this one
    predicate, so a half-filled record (status set, key still a placeholder) must
    read as unfilled rather than as verified.
    """
    if record.get("status") != "filled":
        return False
    if not OWNER_ID_RE.match(str(record.get("owner_id") or "")):
        return False
    key = record.get("key")
    if not isinstance(key, dict):
        return False
    if not FINGERPRINT_RE.match(str(key.get("fingerprint") or "")):
        return False
    try:
        expected = fingerprint_label_of_public_b64(str(key.get("public_key_b64") or ""))
    except ProvenanceError:
        return False
    # The fingerprint must be the digest of *this* key, not a well-formed
    # digest of some other one — otherwise the record can be self-consistent
    # and still misattribute every signature it vouches for.
    return str(key.get("fingerprint")) == expected


def user_fingerprint(record: dict[str, Any]) -> str:
    key = record.get("key")
    if not isinstance(key, dict):
        raise ProvenanceError("user record has no `key` block")
    fingerprint = str(key.get("fingerprint") or "")
    if not fingerprint:
        raise ProvenanceError("user record has no key fingerprint — run `make user-init`")
    return fingerprint


def user_public_b64(record: dict[str, Any]) -> str:
    key = record.get("key")
    if not isinstance(key, dict) or not key.get("public_key_b64"):
        raise ProvenanceError("user record has no public key — run `make user-init`")
    return str(key["public_key_b64"])


def sign_note(raw: bytes, vault: Path, agent: str | None = None, model: str | None = None) -> bytes:
    """Compute and attach the signature envelope for a note's current bytes."""
    authz = _load_authz()
    record = parse_user_record(vault)
    if not user_is_filled(record):
        raise ProvenanceError("user record is unfilled; run `make user-init` first")
    owner_id = str(record.get("owner_id"))

    frontmatter, body = split_note(raw)
    tracking = tracking_of(frontmatter)
    existing_owner = str(tracking.get("owner_id") or "")
    if existing_owner and existing_owner != owner_id:
        raise ProvenanceError(
            f"note claims owner_id {existing_owner!r} but the user record says "
            f"{owner_id!r}; signing would silently re-attribute it"
        )
    tracking["owner_id"] = owner_id
    if not tracking.get("owner_node"):
        tracking["owner_node"] = record.get("owner_node")
    tracking.setdefault("owner_ref", USER_RECORD_REF)
    if agent:
        tracking["agent"] = agent
    if model:
        tracking["model"] = model
    # Set before hashing: the tracking hash must cover the block as it will be
    # written. `sanitized`/`disputed`/`expired` survive a re-sign — only the
    # states that mean "unproven yet" are promoted.
    validity = tracking.get("validity")
    if not isinstance(validity, dict):
        validity = {}
    if validity.get("state") in (None, "unsigned"):
        validity["state"] = "signed"
    tracking["validity"] = validity
    meta = meta_of(frontmatter)
    hashes = note_hashes(meta, tracking, body)

    key_path = _user_key_path(vault)
    if not key_path.is_file():
        raise ProvenanceError(f"user private key not found at {key_path}; run `make user-init`")
    _refuse_loose_key(key_path)
    private_key = authz.load_private_key(key_path)
    public_b64 = authz.public_key_b64(private_key.public_key())

    signature = {
        "alg": "ed25519",
        "note_version": NOTE_VERSION,
        "sig": authz.sign_bytes(private_key, note_message(hashes)),
        "key_id": owner_id,
        "key_fingerprint": fingerprint_label_of_public_b64(public_b64),
        "signed_body_sha256": hashes["body"],
        "signed_meta_sha256": hashes["meta"],
        "signed_tracking_sha256": hashes["tracking"],
        "signed_conversation_root": hashes["conversation"],
        # The metadata itself, not just its hash: when only allowlisted fields
        # changed, a verifier must be able to say *which* keys moved. An
        # aggregate hash can tell that the metadata changed and nothing more.
        "signed_meta": meta,
        "signed_at": _iso(_now()),
    }
    tracking["signature"] = signature
    frontmatter["tracking"] = tracking
    return emit_note(frontmatter, body)


def verify_note(path: Path, record: dict[str, Any] | None = None, vault: Path | None = None) -> tuple[str, str]:
    """Return (outcome, detail) for one note.

    Two independent questions, in this order:

    1. **Authenticity** — does the signature verify over the hashes the envelope
       itself recorded? A no here is a forgery, a wrong key, or an edited
       envelope, and nothing downstream can rehabilitate it.
    2. **Freshness** — does the file still match what was signed? A mismatch is
       an edit; classify it as stale:metadata (allowlisted compiler fields) or
       stale:content (everything else, re-sign to clear).
    """
    root = vault or _find_vault_from_cwd()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return "invalid", f"unreadable: {exc}"
    try:
        frontmatter, body = split_note(raw)
    except (FrontmatterError, UnicodeDecodeError) as exc:
        if path.parent.name == "01_Inbox" and not raw.startswith(b"---"):
            return "pending", "raw inbox item awaiting acceptance"
        return "invalid", f"unparseable: {exc}"
    try:
        tracking = tracking_of(frontmatter)
    except FrontmatterError as exc:
        return "invalid", str(exc)

    signature = tracking.get("signature")
    validity = tracking.get("validity")
    state = validity.get("state") if isinstance(validity, dict) else None

    if not isinstance(signature, dict):
        try:
            relative = path.resolve().relative_to(root.resolve())
        except ValueError:
            relative = Path()
        if relative.parts and relative.parts[0].startswith("01_") and state in (None, "unsigned"):
            return "pending", "inbox item awaiting acceptance"
        return "invalid", "required signature is missing"

    try:
        record = record or parse_user_record(root)
        expected_fingerprint = user_fingerprint(record)
        public_key = _load_authz().public_key_from_b64(user_public_b64(record))
    except ProvenanceError as exc:
        return "invalid", str(exc)

    owner_id = str(tracking.get("owner_id") or "")
    if record.get("owner_id") != owner_id:
        return "invalid", (f"owner_id {owner_id!r} is not the user record's {record.get('owner_id')!r}")
    if signature.get("key_id") != owner_id:
        return "invalid", f"signature key_id {signature.get('key_id')!r} does not match owner_id"
    if signature.get("key_fingerprint") != expected_fingerprint:
        return "invalid", "signed under a different key than user.md holds"

    signed_body = str(signature.get("signed_body_sha256") or "")
    signed_meta = str(signature.get("signed_meta_sha256") or "")
    signed_tracking = str(signature.get("signed_tracking_sha256") or "")
    signed_conversation = str(signature.get("signed_conversation_root") or "")
    recorded = {
        "body": signed_body,
        "meta": signed_meta,
        "tracking": signed_tracking,
        "conversation": signed_conversation,
    }
    if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in recorded.values()):
        return "invalid", "envelope does not record four 64-hex hashes"
    if signature.get("note_version") != NOTE_VERSION:
        return "invalid", (
            f"envelope carries note_version {signature.get('note_version')!r}, this verifier knows {NOTE_VERSION!r}"
        )

    authz = _load_authz()
    # 1. authenticity: the signature covers the recorded inputs, so it stays
    #    verifiable even after the file is edited — which is what lets step 2
    #    report 'stale' instead of 'invalid'.
    if not authz.verify_signature(public_key, str(signature.get("sig") or ""), note_message(recorded)):
        return "invalid", "signature does not verify against user.md"
    signed_meta_obj = signature.get("signed_meta")
    if not isinstance(signed_meta_obj, dict) or sha256_hex(canonical_json(signed_meta_obj)) != signed_meta:
        return "invalid", "envelope's signed_meta does not hash to its recorded hash"

    # 2. freshness: what the file says now versus what was signed.
    current = note_hashes(meta_of(frontmatter), tracking, body)
    if current == recorded:
        if state in (None, "unsigned"):
            return "invalid", "signed envelope present but validity.state is not signed"
        return "valid", f"signed {signature.get('signed_at')} by {owner_id}"

    if current["body"] != recorded["body"]:
        return "stale:content", "body changed since signing — re-sign to clear"
    if current["conversation"] != recorded["conversation"]:
        return "stale:content", "conversation changed since signing — re-sign to clear"
    if current["tracking"] != recorded["tracking"]:
        return "stale:content", "tracking block changed since signing — re-sign to clear"

    allowlist = set(contract()["signature"]["compiler_allowlist"])
    changed = changed_meta_keys(meta_of(frontmatter), signed_meta_obj)
    unexpected = changed - allowlist
    if unexpected:
        return "stale:content", f"metadata changed outside the compiler allowlist: {sorted(unexpected)}"
    if changed:
        return "stale:metadata", f"allowlisted metadata changed: {sorted(changed)}"
    return "invalid", "hashes disagree with the envelope in a way the mapping cannot explain"


def changed_meta_keys(current: dict[str, Any], signed: dict[str, Any]) -> set[str]:
    """Which top-level metadata keys differ between the file and the envelope."""
    return {key for key in set(current) | set(signed) if current.get(key) != signed.get(key)}


def _recorded_from_signature(signature: dict[str, Any]) -> dict[str, str] | None:
    """The primary envelope's four recorded hashes, or None if it is malformed.

    A co-signature commits to the *identical* bytes the primary signature
    recorded, so it is built over these hashes — not over the note's current
    bytes — which is what keeps the two signatures over one message.
    """
    recorded = {
        "body": str(signature.get("signed_body_sha256") or ""),
        "meta": str(signature.get("signed_meta_sha256") or ""),
        "tracking": str(signature.get("signed_tracking_sha256") or ""),
        "conversation": str(signature.get("signed_conversation_root") or ""),
    }
    if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in recorded.values()):
        return None
    return recorded


def _user_record_matches(entry: dict[str, Any], record: dict[str, Any]) -> bool:
    """Does a co-signature entry resolve to this user record (user.md snapshot)?

    The record is the user-key half of a node's ``00_System/user.md`` — the
    offline fallback the trust rule names. The record's fingerprint may be
    spelled at the top level (``key_fingerprint``) or under ``key.fingerprint``
    as user.md carries it.
    """
    key = record.get("key") if isinstance(record.get("key"), dict) else {}
    record_fingerprint = str(record.get("key_fingerprint") or key.get("fingerprint") or "")
    return (
        str(entry.get("owner_id")) == str(record.get("owner_id"))
        and str(entry.get("owner_node")) == str(record.get("owner_node"))
        and bool(record_fingerprint)
        and str(entry.get("key_fingerprint")) == record_fingerprint
    )


def _registry_admits_node(registry: dict[str, Any], owner_node: str) -> tuple[bool, str]:
    """Does the Master-signed registry name this node as a live member?

    The online half of the trust rule. The entry's signature is checked with the
    one canonicalisation (`sparknet-authz.py authorization_message`) under the
    registry's own master key, so a forged or edited entry does not admit a node.
    """
    authz = _load_authz()
    master_b64 = str((registry or {}).get("master_public_key_b64") or "")
    if not master_b64:
        return False, "registry carries no master_public_key_b64"
    try:
        master = authz.public_key_from_b64(master_b64)
    except Exception as exc:
        return False, f"registry master key unusable: {exc}"
    entries = registry.get("authorizations")
    if not isinstance(entries, list):
        return False, "registry has no authorizations list"
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identity = entry.get("identity")
        if not isinstance(identity, dict) or str(identity.get("node_id") or "") != owner_node:
            continue
        if entry.get("revoked"):
            return False, f"node {owner_node!r} is revoked in the registry"
        try:
            message = authz.authorization_message(entry)
        except Exception as exc:
            return False, f"registry entry for {owner_node!r} is malformed: {exc}"
        if not authz.verify_signature(master, str(entry.get("signature_b64") or ""), message):
            return False, f"registry entry for {owner_node!r} is not signed by the master key"
        return True, "registry names the node"
    return False, f"node {owner_node!r} is not in the registry"


def add_co_signature(raw: bytes, vault: Path) -> bytes:
    """Append this vault user's co-signature to a note, leaving the primary intact.

    Signs the *primary envelope's* four recorded hashes with this vault's user
    key, so the co-signature commits to the identical bytes. The primary
    ``signature`` — its ``sig``, ``key_id`` and recorded hashes — is never
    touched, and ``tracking.owner_id`` is untouched, so the note still verifies
    `valid` under its original author. A co-signature from the same key replaces
    the existing entry (idempotent re-sign) rather than piling up.
    """
    authz = _load_authz()
    record = parse_user_record(vault)
    if not user_is_filled(record):
        raise ProvenanceError("user record is unfilled; run `make user-init` first")
    frontmatter, body = split_note(raw)
    tracking = tracking_of(frontmatter)
    signature = tracking.get("signature")
    if not isinstance(signature, dict):
        raise ProvenanceError("cannot co-sign a note with no primary signature to attest")
    recorded = _recorded_from_signature(signature)
    if recorded is None:
        raise ProvenanceError("the primary envelope does not record four 64-hex hashes")

    key_path = _user_key_path(vault)
    if not key_path.is_file():
        raise ProvenanceError(f"user private key not found at {key_path}; run `make user-init`")
    _refuse_loose_key(key_path)
    private_key = authz.load_private_key(key_path)
    public_b64 = authz.public_key_b64(private_key.public_key())
    fingerprint = fingerprint_label_of_public_b64(public_b64)

    entry = {
        "alg": "ed25519",
        "owner_id": str(record.get("owner_id")),
        "owner_node": str(record.get("owner_node") or _node_id(vault)),
        "public_key_b64": public_b64,
        "key_fingerprint": fingerprint,
        "sig": authz.sign_bytes(private_key, note_message(recorded)),
        "signed_at": _iso(_now()),
    }
    existing = signature.get("co_signatures")
    cosignatures = [e for e in existing if isinstance(e, dict)] if isinstance(existing, list) else []
    cosignatures = [e for e in cosignatures if str(e.get("key_fingerprint")) != fingerprint]
    cosignatures.append(entry)
    signature["co_signatures"] = cosignatures
    tracking["signature"] = signature
    frontmatter["tracking"] = tracking
    return emit_note(frontmatter, body)


def verify_co_signatures(
    frontmatter: dict[str, Any],
    *,
    trusted_users: Any = (),
    registry: dict[str, Any] | None = None,
) -> list[str]:
    """Problems, one per co-signature that is not both byte-intact and trusted.

    Each entry is checked in three steps: it must be well-formed, its
    ``key_fingerprint`` must be the fingerprint of its own ``public_key_b64`` (a
    swapped key fails), and its ``sig`` must verify over the primary envelope's
    four recorded hashes with that key (a co-signature over different bytes
    fails). A byte-intact entry is then *trusted* when it resolves through either
    resolver: the Master-signed ``registry`` naming its node, or a ``trusted_users``
    record (the origin ``user.md`` snapshot) matching its owner_id, owner_node and
    fingerprint. An intact entry that resolves through neither is reported
    ``untrusted`` — the bytes are genuine, the signer is simply unknown here.
    """
    authz = _load_authz()
    problems: list[str] = []
    tracking = tracking_of(frontmatter)
    signature = tracking.get("signature")
    if not isinstance(signature, dict):
        return problems
    entries = signature.get("co_signatures")
    if not isinstance(entries, list) or not entries:
        return problems
    recorded = _recorded_from_signature(signature)
    if recorded is None:
        return ["co-signatures exist but the primary envelope records no four hashes"]

    for index, entry in enumerate(entries):
        label = f"co-signature[{index}]"
        if not isinstance(entry, dict):
            problems.append(f"{label}: not a mapping")
            continue
        owner_id = str(entry.get("owner_id") or "")
        owner_node = str(entry.get("owner_node") or "")
        fingerprint = str(entry.get("key_fingerprint") or "")
        public_b64 = str(entry.get("public_key_b64") or "")
        if entry.get("alg") != "ed25519":
            problems.append(f"{label} ({owner_id or '?'}): alg is not ed25519")
            continue
        if not OWNER_ID_RE.fullmatch(owner_id):
            problems.append(f"{label}: owner_id {owner_id!r} is not a U-##### number")
            continue
        if not FINGERPRINT_RE.fullmatch(fingerprint):
            problems.append(f"{label} ({owner_id}): key_fingerprint is not sha256:<64 hex>")
            continue
        try:
            public_key = authz.public_key_from_b64(public_b64)
        except Exception as exc:
            problems.append(f"{label} ({owner_id}): public_key_b64 unusable: {exc}")
            continue
        if fingerprint != fingerprint_label_of_public_b64(public_b64):
            problems.append(f"{label} ({owner_id}): key_fingerprint does not match public_key_b64")
            continue
        if not authz.verify_signature(public_key, str(entry.get("sig") or ""), note_message(recorded)):
            problems.append(f"{label} ({owner_id}): signature does not verify over the recorded hashes")
            continue
        if any(_user_record_matches(entry, rec) for rec in trusted_users if isinstance(rec, dict)):
            continue
        if registry is not None:
            admitted, detail = _registry_admits_node(registry, owner_node)
            if admitted:
                continue
            problems.append(f"{label} ({owner_id}): untrusted — {detail}")
            continue
        problems.append(f"{label} ({owner_id}): untrusted — no registry and no matching user.md snapshot")
    return problems


def user_init(vault: Path, owner_id: str | None = None, force: bool = False, clock=None) -> dict[str, Any]:
    """Generate the user keypair and fill the record once.

    The private half goes to the state dir at 0600; the record gets the public
    key, the fingerprint and the number every tracking block will carry. The
    receipt (`.user.lock`) is what later tests compare against, so an edited
    record fails rather than quietly re-attributing history.

    Re-keying is refused by default because the public key in this file is what
    every existing note signature verifies against — a silent re-key invalidates
    all of them at once. `force` exists for the deliberate case (a lost key on a
    vault whose signatures will all be redone) and says so in its output.
    """
    authz = _load_authz()
    path = user_record_path(vault)
    if not path.is_file():
        raise ProvenanceError(f"missing {path}")
    record, body = split_note(path.read_bytes())
    if user_is_filled(record) and not force:
        lock_state = _verify_lock(vault, path)
        if lock_state is None:
            raise ProvenanceError(
                "user record is already filled; refusing to re-key it. The public key "
                "in user.md is what every existing note signature verifies against — "
                "re-keying would invalidate all of them at once. Pass --force if that "
                "is genuinely what you mean, then re-sign every note."
            )
        if not lock_state:
            raise ProvenanceError(
                "user record is filled but 00_System/.user.lock does not match it; "
                "the record has been edited since it was filled. Restore it, or "
                "--force to re-key deliberately."
            )
        return record

    state = _state_dir(vault)
    # The state dir holds the private key, so it gets the key store's mode even
    # when it already existed (umask would otherwise leave .state at 0775).
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    keys = state / "keys"
    keys.mkdir(parents=True, exist_ok=True, mode=0o700)
    keys.chmod(0o700)
    private_path = keys / "user.ed25519"
    if private_path.exists() and not force:
        raise ProvenanceError(
            f"{private_path} already exists but user.md is unfilled — resolve that "
            f"before generating a second key over the first (--force to replace)."
        )

    private_b64, public_b64 = authz.generate_keypair()
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(private_b64 + "\n")
    except Exception:
        os.close(descriptor)
        raise

    number = owner_id or f"U-{10000 + (_now().microsecond % 90000):05d}"
    if not OWNER_ID_RE.match(number):
        raise ProvenanceError(f"owner id {number!r} must look like U-10421")
    record["type"] = "user-record"
    record["schema"] = "sparknet-user/1"
    record["status"] = "filled"
    record["owner_id"] = number
    record["owner_node"] = _node_id(vault)
    record["role"] = "owner"
    record["immutable"] = True
    record["key"] = {
        "alg": "ed25519",
        "public_key_b64": public_b64,
        "fingerprint": "sha256:" + fingerprint_of_public_b64(public_b64),
        "key_ref": "$SPARKNET_STATE_DIR/keys/user.ed25519",
        "created": _iso((clock or _now)()),
    }
    filled = emit_note(record, body)
    path.write_bytes(filled)
    lock = {
        "owner_id": number,
        "sha256": sha256_hex(filled),
        "filled_at": _iso((clock or _now)()),
    }
    (vault / "00_System" / ".user.lock").write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    return record


def _verify_lock(vault: Path, path: Path) -> bool | None:
    """True when the lock matches, False when it does not, None when absent."""
    lock_path = vault / "00_System" / ".user.lock"
    if not lock_path.is_file():
        return None
    try:
        lock = json.loads(lock_path.read_text())
    except json.JSONDecodeError:
        return False
    return lock.get("sha256") == sha256_hex(path.read_bytes())


def check_user_record(vault: Path) -> list[str]:
    """Allowlist check: public key, fingerprint and identity tags — nothing else."""
    problems: list[str] = []
    try:
        record = parse_user_record(vault)
    except (ProvenanceError, FrontmatterError) as exc:
        return [str(exc)]
    extra = set(record) - USER_RECORD_KEYS
    if extra:
        problems.append(f"user record has keys outside the allowlist: {sorted(extra)}")
    key = record.get("key")
    if isinstance(key, dict):
        extra_key = set(key) - USER_KEY_FIELDS
        if extra_key:
            problems.append(f"user record key block has unexpected fields: {sorted(extra_key)}")
        public_b64 = str(key.get("public_key_b64") or "")
        if public_b64:
            # An empty key is the shipped template, not a defect — deriving a
            # fingerprint from zero bytes would report "not 32 bytes" on every
            # fresh clone. A *filled* record with an empty key is caught below.
            try:
                expected = fingerprint_label_of_public_b64(public_b64)
            except ProvenanceError as exc:
                problems.append(str(exc))
            else:
                if str(key.get("fingerprint") or "") != expected:
                    problems.append("user record fingerprint is not the digest of its own public key")
        if record.get("status") == "filled" and not user_is_filled(record):
            problems.append("user record claims `filled` but is not — run make user-init")
    raw = user_record_path(vault).read_text()
    for label, pattern in _PATTERNS:
        if pattern.search(raw):
            problems.append(f"user record contains a {label}")
    if user_is_filled(record) and _verify_lock(vault, user_record_path(vault)) is False:
        problems.append("user record does not match 00_System/.user.lock (edited after fill)")
    return problems


def check_shims(vault: Path) -> tuple[int, str]:
    """Every legacy name must be a symlink to its numbered home — and nothing else.

    The vendored wiki suite reads the legacy names, so a shim that has become a
    real directory would silently hold a *second* copy of a page, and the
    filesystem that could not create symlinks at all would show up here first.
    """
    legacy: dict[str, str] = contract()["layout"]["legacy_map"]
    problems: list[str] = []
    for name in sorted(legacy):
        expected = legacy[name]
        path = vault / name
        if not path.exists() and not path.is_symlink():
            problems.append(f"{name}: missing — expected a symlink to {expected}")
            continue
        if not path.is_symlink():
            kind = "directory" if path.is_dir() else "file"
            problems.append(f"{name}: a real {kind}, not a symlink to {expected}")
            continue
        actual = os.readlink(path)
        if actual != expected:
            problems.append(f"{name}: points at {actual!r}, expected {expected!r}")
        elif not (vault / expected).exists():
            problems.append(f"{name}: its target {expected} does not exist")
    if problems:
        return 1, "shims-check: FAILED\n  " + "\n  ".join(problems)
    return 0, f"shims-check: {len(legacy)} shims OK (legacy name → numbered path)"


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")[:60] or "item"


def authorised_senders(record: dict[str, Any]) -> list[str]:
    senders = record.get("authorised_senders")
    return [str(s) for s in senders] if isinstance(senders, list) else []


def ingest_note(
    vault: Path,
    body: bytes,
    *,
    source: str,
    sender: str | None = None,
    title: str | None = None,
    classification: str | None = None,
    department: str | None = None,
    agent: str = "ingest",
    model: str = "local",
    clock=None,
    target_name: str | None = None,
) -> Path:
    """Land one item in `01_Inbox/` as an unsigned, therefore pending, note.

    The note is written with `validity.state: unsigned` and no signature, so
    `verify` reports `pending` (exit 0) rather than `invalid` — acceptance is
    what promotes it, and acceptance is recorded in the ledger, not here.

    Email-origin items fail closed: the sender must already be on
    `authorised_senders` in the user record, because an empty list means
    nobody may push work onto this node.
    """
    if source not in INGEST_SOURCES:
        raise ProvenanceError(f"source must be one of {', '.join(INGEST_SOURCES)}")
    abac = _load_abac()
    selected = classification or abac.INGEST_DEFAULTS[source]
    if selected not in abac.CLASSIFICATIONS:
        raise ProvenanceError(f"classification must be one of {', '.join(abac.CLASSIFICATIONS)}")
    minimum = abac.INGEST_MINIMUM.get(source)
    if minimum is not None and abac.CLASSIFICATIONS.index(selected) < abac.CLASSIFICATIONS.index(minimum):
        raise ProvenanceError(f"source {source!r} cannot be classified below {minimum!r}")
    selected_department = None
    if department is not None:
        selected_department = department.strip()
        if not selected_department or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", selected_department):
            raise ProvenanceError("department must be 1-64 characters of letters, digits, dot, underscore or dash")
    record = parse_user_record(vault)
    if source == "email":
        address = (sender or "").strip()
        if not address:
            raise ProvenanceError("--sender is required for a source of email")
        if address not in authorised_senders(record):
            raise ProvenanceError(
                f"sender {address!r} is not on authorised_senders in {USER_RECORD_REF} — the inbox policy fails closed"
            )

    text = body.decode("utf-8", "replace")
    heading = next(
        (line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#")),
        "",
    )
    label = title or heading or source
    slug = slugify(label)
    if target_name is not None:
        if not target_name or "/" in target_name or "\\" in target_name or target_name.startswith("."):
            raise ProvenanceError("target_name must be a single safe filename")
        filename = target_name
    else:
        filename = f"{slug}.md"
    target = vault / "01_Inbox" / filename
    if target.exists():
        raise ProvenanceError(f"{target} already exists — refusing to overwrite an inbox item")

    now = (clock or _now)()
    meta: dict[str, Any] = {
        "title": label,
        "type": "inbox-item",
        "source": source,
        "captured": now.date().isoformat(),
        "classification": selected,
    }
    if selected_department:
        meta["department"] = selected_department
    if source == "email":
        meta["sender"] = str(sender)
    tracking: dict[str, Any] = {
        "schema": "sparknet-tracking/1",
        "owner_id": str(record.get("owner_id") or ""),
        "owner_node": str(record.get("owner_node") or _node_id(vault)),
        "owner_ref": USER_RECORD_REF,
        "validity": {"state": "unsigned"},
        "conversation": [],
        "shares": [],
        "agent": agent,
        "model": model,
        "approvals": [],
    }
    if not body.endswith(b"\n"):
        body += b"\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(emit_note({**meta, "tracking": tracking}, body))
    return target


__all__ = [
    "CO_SIGNATURE_FIELDS",
    "INGEST_SOURCES",
    "NOTE_DOMAIN",
    "NOTE_VERSION",
    "USER_KEY_FIELDS",
    "USER_RECORD_KEYS",
    "_RECORDED_HASH_FIELDS",
    "_SLUG_RE",
    "_recorded_from_signature",
    "_registry_admits_node",
    "_user_record_matches",
    "_verify_lock",
    "add_co_signature",
    "authorised_senders",
    "build_conversation_root",
    "changed_meta_keys",
    "check_shims",
    "check_user_record",
    "emit_note",
    "ingest_note",
    "meta_of",
    "note_hashes",
    "note_message",
    "parse_user_record",
    "sign_note",
    "slugify",
    "split_note",
    "tracking_of",
    "unsigned_tracking",
    "user_fingerprint",
    "user_init",
    "user_is_filled",
    "user_public_b64",
    "user_record_path",
    "verify_co_signatures",
    "verify_note",
]

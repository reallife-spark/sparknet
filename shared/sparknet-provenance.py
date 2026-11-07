#!/usr/bin/env python3
"""Sparknet provenance: note signatures, ledger approvals, the user record, secret scanning.

This is the one implementation of the accountability chain described in
``contracts/provenance-protocol.md`` and machine-read from
``contracts/tracking-schema.json``:

* **Notes** in ``01_Inbox``..``07_Archives`` carry a ``tracking`` block whose
  signature envelope records what was signed — the body hash, the metadata hash
  with the metadata itself, the tracking hash, and the RFC 6962 root of the
  conversation entries (so the who/when/which-model trail cannot be edited
  without invalidating the note). Recording the inputs is what lets a verifier
  separate three things that would otherwise look identical: a routine compiler
  rewrite (``stale:metadata``), an edit nobody re-signed (``stale:content``),
  and a forgery (``invalid``).
* **Approvals** live only in ``blockchain/ledger.json``, as hash-chained blocks
  carrying two signatures over one payload: user consent and node
  countersignature. There is no approvals.md and nothing may be coded to one.
* **The user record** (``00_System/user.md``) holds the public key every note
  signature is checked against. It is filled once per node; the private half
  lives at ``$SPARKNET_STATE_DIR/keys/user.ed25519`` at mode 0600 and never
  enters the vault, git or a bundle.
* **Secrets** are tracked as metadata in ``00_System/secrets-index.json`` and
  stored outside the vault; ``scan`` fails if a registered value or a
  key-shaped literal appears in a tracked file.

Ed25519 is not reimplemented here. Every signing and verification operation
loads ``sparknet-authz.py`` by path from this directory, so the fabric still has
exactly one crypto implementation — the same rule ``sparknet-consensus.py``
follows, and the same test failure if this module starts doing its own.

The normative contract is ``contracts/tracking-schema.json``. Constants that
must not drift — the compiler allowlist, the ledger's required fields, the
event vocabulary, the note layout — are read from the contract at runtime
rather than restated here, so a contract change cannot leave this tool stale.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

DEFAULT_SHARED_DIR = Path(__file__).resolve().parent

#: Domain separator for note signatures. Versioned so a future envelope change
#: cannot silently verify against old signatures — they would simply not match.
#: `sparknet-note/2` appends the conversation root as a fourth hashed line, so
#: the who/when/which-model trail is bound to the note's own bytes.
NOTE_VERSION = "sparknet-note/2"
NOTE_DOMAIN = NOTE_VERSION.encode("ascii")

#: A node-scoped user number: U- plus five digits.
OWNER_ID_RE = re.compile(r"^U-[0-9]{5}$")

#: The fingerprint form a filled record must carry: sha256 of the raw key bytes.
FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: Where every tracking block points to find the record that defines owner_id.
#: A constant because it is a contract value (`tracking_block.required_fields.
#: owner_ref.const`), and a note whose pointer drifts resolves to nothing.
USER_RECORD_REF = "00_System/user.md"

#: Frontmatter keys allowed in a filled user record. An allowlist, not a
#: blocklist: a new key is a schema change that belongs in the contract first,
#: so anything unlisted fails rather than being quietly committed.
#: Pinned against `user_record.fields` in tests/test_contracts.py.
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

#: Fields the secret index may contain. There is deliberately no field a value
#: could hide in.
SECRET_INDEX_ENTRY_KEYS = frozenset(
    {
        "id",
        "kind",
        "holder_agent",
        "ref",
        "fingerprint",
        "scopes",
        "created",
        "last_rotated",
        "status",
        "notes",
    }
)
SECRET_INDEX_FORBIDDEN = frozenset({"value", "secret", "token", "password", "private_key"})

#: Key-shaped literals the scanner refuses to see in a tracked file. Built from
#: fragments so the patterns themselves do not match their own source.
_PATTERNS = (
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("api key literal", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "assigned secret",
        re.compile(r"\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']", re.I),
    ),
)

#: Files exempt from the literal scan: the detector itself (its patterns would
#: match its own source) and the test suite (whose fixtures are subjects under
#: test). Everything else is scanned, including docs and configs.
_SCAN_EXEMPT = frozenset({"shared/sparknet-provenance.py"})


# --- the one frontmatter implementation (loaded by path, D10/Step 40) ---------
# The YAML-subset parser and emitter live in sparknet-yaml.py so the note format
# is one loadable unit. ProvenanceError and FrontmatterError are defined there
# too — FrontmatterError subclasses ProvenanceError, and the many handlers below
# that catch ProvenanceError must keep catching a malformed note — and are
# re-exported here so `provenance.ProvenanceError` still names the same class.
# Loading by path is the same one-copy rule the crypto modules follow.
_yaml = load_shared(
    "sparknet-yaml.py",
    "sparknet_yaml",
    error=ImportError,
    message=(
        "cannot find shared/sparknet-yaml.py; the fabric carries exactly one "
        "frontmatter implementation and this tool does not carry a fallback. "
        "Set SPARKNET_SHARED_DIR."
    ),
)

ProvenanceError = _yaml.ProvenanceError
FrontmatterError = _yaml.FrontmatterError
parse_yaml_subset = _yaml.parse_yaml_subset
emit_yaml = _yaml.emit_yaml
_split_frontmatter = _yaml._split_frontmatter


# --- loading the one crypto implementation -----------------------------------


def _load_authz() -> Any:
    """Load sparknet-authz.py by path, never by import.

    Loading by path is what proves there is one implementation. An import would
    let a role quietly end up with a private copy, and two crypto
    implementations that must agree byte-for-byte is a second trust boundary.
    The resolve-and-cache mechanics live once in ``shared/sparknet_loader.py``.
    """
    return load_shared(
        "sparknet-authz.py",
        "sparknet_authz",
        error=ProvenanceError,
        message=(
            "cannot find shared/sparknet-authz.py; set SPARKNET_SHARED_DIR. "
            "There is exactly one signing implementation and this tool does not "
            "carry a fallback."
        ),
    )


def _load_merkle() -> Any:
    """Load sparknet-merkle.py by path, never by import.

    Same loader and same reasoning as ``_load_authz``: the RFC 6962 integrity
    math (the checkpoint root and the conversation root both rest on it) lives
    in its own shared module so there is exactly one implementation, and a test
    fails if this tool ever starts carrying a private copy. The
    resolve-and-cache mechanics live once in ``shared/sparknet_loader.py``.
    """
    return load_shared(
        "sparknet-merkle.py",
        "sparknet_merkle",
        error=ProvenanceError,
        message=(
            "cannot find shared/sparknet-merkle.py; set SPARKNET_SHARED_DIR. "
            "The checkpoint and note roots come from the one integrity module; "
            "this tool does not carry a fallback."
        ),
    )


def _load_abac() -> Any:
    """Load the ABAC vocabulary by path; ingestion must not restate it."""
    return load_shared(
        "sparknet-abac.py",
        "sparknet_abac",
        error=ProvenanceError,
        message="cannot find shared/sparknet-abac.py; set SPARKNET_SHARED_DIR.",
    )


_contract_cache: dict[str, Any] | None = None


def contract() -> dict[str, Any]:
    """The tracking contract, loaded once. Rules are read from it, not restated."""
    global _contract_cache
    if _contract_cache is None:
        env = os.environ.get("SPARKNET_CONTRACTS_DIR")
        path = (Path(env) if env else DEFAULT_SHARED_DIR.parent / "contracts") / "tracking-schema.json"
        if not path.is_file():
            raise ProvenanceError(
                f"cannot find {path}; this tool refuses to guess its own rules. Set SPARKNET_CONTRACTS_DIR."
            )
        try:
            _contract_cache = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ProvenanceError(f"{path} is not valid JSON: {exc}") from exc
    return _contract_cache


# --- canonical form -----------------------------------------------------------


def canonical_json(obj: Any) -> bytes:
    """The house canonical form: sorted keys, tight separators, ASCII-escaped, UTF-8.

    Identical to ``sparknet-authz.authorization_message`` and to the block hash
    the ledger already uses. A second canonicalisation rule would be a signature
    that verifies in one place and not another.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_of_public_b64(public_key_b64: str) -> str:
    """sha256 of the raw 32-byte public key, hex — the key fingerprint."""
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except Exception as exc:
        raise ProvenanceError("public key is not valid base64") from exc
    if len(raw) != 32:
        raise ProvenanceError(f"Ed25519 public key must be 32 bytes, got {len(raw)}")
    return hashlib.sha256(raw).hexdigest()


def fingerprint_label_of_public_b64(public_key_b64: str) -> str:
    """The stored form: `sha256:` + the raw key's hex digest.

    user.md and the note envelope both spell it this way, and `FINGERPRINT_RE`
    accepts nothing else — a bare hex digest in either place is unreadable as a
    fingerprint by anything checking the pattern.
    """
    return "sha256:" + fingerprint_of_public_b64(public_key_b64)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


# --- frontmatter: the documented YAML subset lives in sparknet-yaml.py --------
# The subset parser and emitter are re-exported above from the one shared copy;
# `split_note`/`emit_note` are the note-level wrappers the rest of this module uses.


def split_note(raw: bytes) -> tuple[dict[str, Any], bytes]:
    """Parse a note into (frontmatter mapping, body bytes)."""
    fm_bytes, body = _split_frontmatter(raw)
    return parse_yaml_subset(fm_bytes.decode("utf-8")), body


def emit_note(frontmatter: dict[str, Any], body: bytes) -> bytes:
    return b"---\n" + emit_yaml(frontmatter).encode("utf-8") + b"---\n" + body


# --- the note envelope --------------------------------------------------------


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


def _state_dir(vault: Path | None = None) -> Path:
    env = os.environ.get("SPARKNET_STATE_DIR")
    if env:
        return Path(env)
    return (vault or _find_vault_from_cwd()) / ".state"


def _user_key_path(vault: Path | None = None) -> Path:
    return _state_dir(vault) / "keys" / "user.ed25519"


def _node_key_path(vault: Path | None = None) -> Path:
    return _state_dir(vault) / "keys" / "ed25519-node.key.b64"


def _find_vault_from_cwd() -> Path:
    """Walk up for a filled-or-template user record — the numbered layout's marker."""
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "00_System" / "user.md").is_file():
            return candidate
    raise ProvenanceError("no vault with 00_System/user.md found from the current directory")


def _refuse_loose_key(path: Path) -> None:
    """Refuse a private key anyone but the owner can read.

    Not a style check: a 0644 key is readable by any process on the node, which
    makes every signature it produced attributable to nobody.
    """
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ProvenanceError(
            f"private key {path} is mode {mode:04o}; it must not be readable by "
            f"group or other. Fix with: chmod 600 {path}"
        )


def _node_id(vault: Path) -> str:
    identity = vault / "manifests" / "node-identity.json"
    if identity.is_file():
        try:
            return str(json.loads(identity.read_text()).get("node_id") or "unknown")
        except json.JSONDecodeError:
            return "unknown"
    return "unknown"


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


# --- co-signatures ------------------------------------------------------------
#
# A second user attests a note's bytes without rewriting the original author.
# `sign_note` refuses a note whose owner_id differs, so a reviewer could never
# countersign (the G3 gap). A co-signature is appended under
# `tracking.signature.co_signatures[]`, a sibling of the primary `sig`. The
# primary tracking hash is taken with the whole `signature` key removed, so
# appending a co-signature never invalidates the primary signature: the note
# keeps its owner_id and still verifies `valid`.

#: The fields every co-signature entry carries. `alg`/`signed_at` are bookkeeping
#: the primary envelope also keeps; the five the contract names are the ones a
#: verifier resolves on.
CO_SIGNATURE_FIELDS = (
    "alg",
    "owner_id",
    "owner_node",
    "public_key_b64",
    "key_fingerprint",
    "sig",
    "signed_at",
)

#: The four recorded-hash fields the primary envelope carries; a co-signature
#: signs the same message, rebuilt from exactly these.
_RECORDED_HASH_FIELDS = ("body", "meta", "tracking", "conversation")


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


# --- the user record ----------------------------------------------------------


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
    private_path.write_text(private_b64 + "\n")
    private_path.chmod(0o600)

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


# --- layout shims -------------------------------------------------------------


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


# --- inbox intake -------------------------------------------------------------

#: What may be written into 01_Inbox/ by an agent, per the contract's dispatch
#: policy. The transport that would deliver these items does not exist yet;
#: this is the local half of it (stdin or a file).
INGEST_SOURCES = ("master-node", "peer-node", "email")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


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


# --- the ledger ---------------------------------------------------------------


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
    separately; the header
    signature binds the block's position and payload, so a deleted, reordered or
    edited block is detectable.
    """
    ledger_path = vault / "blockchain" / "ledger.json"
    ledger = load_ledger(ledger_path) if ledger_path.is_file() else {"version": "2.0", "genesis_hash": "", "blocks": []}
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

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger_path.with_name(f".{ledger_path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(ledger, indent=2) + "\n")
    tmp.chmod(0o600)
    os.replace(tmp, ledger_path)
    _adopt_vault_owner(ledger_path, vault)
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


# --- signed checkpoints and cross-node head anchoring ---------------------------


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
    key = str(block["data"].get("node_pubkey_b64") or "")
    if not key:
        return False, "no node_pubkey_b64 in checkpoint data", None
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


# --- signed session grants -----------------------------------------------------


def _safe_rel(raw: str) -> PurePosixPath:
    """Normalise a vault-relative path, refusing anything that climbs out."""
    path = PurePosixPath(str(raw).strip())
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ProvenanceError(f"not a vault-relative path: {raw!r}")
    return path


def grant_scope_allows(scope: list[str], target_rel: str) -> bool:
    """Is this vault-relative write inside the grant's scope?

    Containment is a prefix of *path parts*, not a string prefix, so
    `05_Knowledge/con` does not cover `05_Knowledge/configs`. An empty scope
    allows nothing: contracts/identity-schema.json `vault_scope` says empty
    means node-level config only, no knowledge access — so a scope-less grant
    cannot reach any note.
    """
    target = _safe_rel(target_rel)
    for raw in scope:
        if not str(raw).strip():
            continue
        prefix = _safe_rel(str(raw))
        if target.parts[: len(prefix.parts)] == prefix.parts:
            return True
    return False


def quarantine_rel(vault: Path, grant_id: str, name: str) -> str:
    """Where an out-of-scope write lands: under `_raw/`, never at its target.

    The numbered path is derived from the contract's own legacy map, so this
    writes `03_Sources/grant-quarantine/...` on a role vault — which is the
    same file the `_raw/` shim names, and leaves the shim itself untouched.
    The material is kept (the vault does not delete what it was given) while
    authority is never widened by a signature.
    """
    legacy = contract()["layout"]["legacy_map"]
    raw_dir = legacy.get("_raw", "_raw")
    return str(PurePosixPath(raw_dir, "grant-quarantine", grant_id, name))


def consumed_grant_nonces(vault: Path) -> set[str]:
    """Grant nonces this node has already recorded.

    The ledger is the retention store contracts/identity-schema.json requires
    (`nonce.retention`): a nonce in any grant_use block is spent, so replaying
    that grant fails for as long as the chain exists.
    """
    path = vault / "blockchain" / "ledger.json"
    if not path.is_file():
        return set()
    ledger = load_ledger(path)
    return {
        str(block["data"].get("nonce"))
        for block in ledger.get("blocks", [])
        if isinstance(block, dict)
        and isinstance(block.get("data"), dict)
        and block["data"].get("event") == "grant_use"
        and block["data"].get("nonce")
    }


def _consumed_except(vault: Path, grant: dict[str, Any], allow_reused_nonce: bool) -> set[str]:
    """The spent-nonce set, optionally yielding the presenting grant's own nonce.

    The one-shot rule is ``allow_reused_nonce=False``. The session-level
    ``vault_access: all`` toggle passes ``True`` so a grant the operator made
    reusable keeps working after its first mutation; no *other* grant's nonce is
    ever discounted.
    """
    consumed = consumed_grant_nonces(vault)
    if allow_reused_nonce:
        consumed.discard(str(grant.get("nonce") or ""))
    return consumed


def build_grant_use_data(
    *,
    vault: Path,
    grant: dict[str, Any],
    decision: str,
    session: str,
    note_refs: list[str],
    agent: str,
    model: str,
    record: dict[str, Any],
    clock=None,
) -> dict[str, Any]:
    """Assemble a `grant_use` record over the same dual-control envelope as an
    approval: user consent plus node countersignature over one payload.

    `session` is required because it is the whole point of the record — the
    grant says what was permitted, the acting session says who used it, and the
    two differ whenever a subagent inherited a parent grant.
    """
    if decision not in ("granted", "quarantined"):
        raise ProvenanceError(f"decision must be granted|quarantined, got {decision!r}")
    if not isinstance(session, str) or not session:
        raise ProvenanceError("session is required: audit trails to the acting session, not the grant")
    if not isinstance(grant, dict) or not grant.get("grant_id"):
        raise ProvenanceError("grant must carry a grant_id")
    moment = (clock or _now)()
    try:
        blocks = load_ledger(vault / "blockchain" / "ledger.json").get("blocks", [])
    except ProvenanceError:
        blocks = []
    uses = sum(
        1 for block in blocks if isinstance(block, dict) and (block.get("data") or {}).get("event") == "grant_use"
    )
    data: dict[str, Any] = {
        "event": "grant_use",
        "grant_use_id": f"GUSE-{moment.date().isoformat()}-{uses + 1:03d}",
        "grant_id": str(grant.get("grant_id")),
        "parent_grant_id": grant.get("parent_grant_id"),
        "conversation_key": str(grant.get("conversation_key") or ""),
        "nonce": str(grant.get("nonce") or ""),
        "user_identity": str(grant.get("user_identity") or ""),
        "session": session,
        "decision": decision,
        "vault_scope": list(grant.get("vault_scope") or []),
        "agent": agent,
        "model": model,
        "note_refs": sorted(note_refs),
        "owner_id": str(record.get("owner_id")),
        "owner_node": _node_id(vault),
        "node_pubkey_b64": _node_public_b64(vault),
        "recorded_at": _iso(moment),
    }
    data["signatures"] = _dual_sign(vault, record, data)
    return data


#: Where an inbox item may have come from. Closed, because the dispatch policy in
#: `contracts/tracking-schema.json::inbox_dispatch` keys off it: a source outside
#: this set has no defined trust treatment, and inventing one at the call site is
#: how an unreviewed item ends up executed.
INBOX_SOURCES = ("master-node", "peer-node", "email")

#: Sources whose material is untrusted until a reviewer agent has been over it.
#: `master-node` is absent on purpose — the Master is the signing role, so its
#: items may be executed on notice.
INBOX_UNTRUSTED_SOURCES = ("peer-node", "email")


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


def write_granted_note(
    vault: Path,
    grant: dict[str, Any],
    *,
    target: str,
    body: bytes,
    session: str,
    registry: dict[str, Any],
    node_identity: dict[str, Any],
    agent: str = "grant",
    model: str = "local",
    clock=None,
    allow_reused_nonce: bool = False,
) -> tuple[Path, str, dict[str, Any]]:
    """Write one note under a signed session grant. Fail-closed, in this order.

    Returns ``(note_path, decision, ledger_block)``.

    1. The grant is verified against the Master-signed registry and the node
       identity presenting it. A forged, expired, replayed, nonce-reused or
       out-of-node grant raises here and touches nothing — that is
       contracts/identity-schema.json `grant.verification_order`, the guard's
       check order, executed by shared/sparknet-authz.py: the one crypto
       implementation, not a second one.
    2. The target is checked against `vault_scope`. Out of scope never lands at
       the target: the material is quarantined under `_raw/` and the ledger
       records `decision: quarantined`, so nothing is silently lost and nothing
       silently lands outside the grant.
    3. The note is written with provenance frontmatter — owner, the grant, and
       the acting session — and signed with the user key.
    4. A `grant_use` block is appended, dual-signed and hash-chained, carrying
       the grant id, its parent when delegated, and the acting session. Audit
       is therefore finer than authority: authority traces to the parent grant,
       audit traces to the child session that used it.
    """
    authz = _load_authz()
    record = parse_user_record(vault)
    if not user_is_filled(record):
        raise ProvenanceError("user record is unfilled; run `make user-init` first")
    if not isinstance(session, str) or not session:
        raise ProvenanceError("session is required: audit trails to the acting session")
    if not body.strip():
        raise ProvenanceError("refusing to write an empty note")
    master_b64 = str((registry or {}).get("master_public_key_b64") or "")
    if not master_b64:
        raise ProvenanceError("registry carries no master_public_key_b64 — refusing to verify")
    # Fail fast on missing keys, before any file is written.
    _node_public_b64(vault)

    decision = authz.verify_grant(
        grant,
        master_public_key=authz.public_key_from_b64(master_b64),
        registry=registry,
        node_identity=node_identity,
        consumed_nonces=_consumed_except(vault, grant, allow_reused_nonce),
        now=(clock or _now)(),
    )
    if not decision.allowed:
        raise ProvenanceError(f"grant refused ({decision.reason}): {grant.get('grant_id', '?')}")

    now = (clock or _now)()
    rel = _safe_rel(target)
    if grant_scope_allows(list(grant.get("vault_scope") or []), str(rel)):
        outcome = "granted"
        note_rel = str(rel)
    else:
        outcome = "quarantined"
        note_rel = quarantine_rel(vault, str(grant["grant_id"]), rel.name)

    note_path = vault / note_rel
    if note_path.exists():
        raise ProvenanceError(f"{note_rel} already exists — refusing to overwrite a vault note")

    heading = next(
        (line.lstrip("#").strip() for line in body.decode("utf-8", "replace").splitlines() if line.startswith("#")),
        "",
    )
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
        "grant": {
            "grant_id": str(grant.get("grant_id")),
            "parent_grant_id": grant.get("parent_grant_id"),
            "conversation_key": str(grant.get("conversation_key") or ""),
            "session": session,
            "scope": list(grant.get("vault_scope") or []),
        },
    }
    meta = {"title": heading or PurePosixPath(note_rel).stem, "type": "vault-page", "captured": now.date().isoformat()}
    if not body.endswith(b"\n"):
        body += b"\n"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_bytes(sign_note(emit_note({**meta, "tracking": tracking}, body), vault, agent=agent, model=model))

    block = append_block(
        vault,
        build_grant_use_data(
            vault=vault,
            grant=grant,
            decision=outcome,
            session=session,
            note_refs=[note_rel],
            agent=agent,
            model=model,
            record=record,
            clock=clock,
        ),
    )
    return note_path, outcome, block


def _verified_grant(
    vault: Path,
    grant: dict[str, Any],
    *,
    registry: dict[str, Any],
    node_identity: dict[str, Any],
    session: str,
    clock=None,
    allow_reused_nonce: bool = False,
) -> tuple[dict[str, Any], Any]:
    """The one fail-closed grant ladder every grant-scoped mutation shares.

    write/promote/patch are three entry points, not three policies: each calls
    this and only this to establish that the presenting vault holds the node
    key, that the Master-signed registry names a verifier, and that the grant
    walks identity-schema.json `grant.verification_order` with this node's
    ledger as the nonce store. A mutation that skipped one step of this ladder
    would be the second authority the fabric forbids.

    ``allow_reused_nonce`` is the session-level "all vault tools" toggle
    (``vault_access: all``): the *presenting* grant's own nonce is dropped from
    the consumed set so a grant the operator explicitly made reusable for a
    session keeps working after its first mutation. Every other grant's nonce
    stays spent, the signature, registry, expiry, node identity and per-target
    scope are still checked, and every mutation still appends a grant_use block.
    The default (``False``) is the one-shot rule; only the bridge's session
    toggle turns it on, and only for the grant that enabled it.
    """
    authz = _load_authz()
    if not isinstance(session, str) or not session:
        raise ProvenanceError("session is required: audit trails to the acting session")
    master_b64 = str((registry or {}).get("master_public_key_b64") or "")
    if not master_b64:
        raise ProvenanceError("registry carries no master_public_key_b64 — refusing to verify")
    _node_public_b64(vault)
    record = parse_user_record(vault)
    if not user_is_filled(record):
        raise ProvenanceError("user record is unfilled; run `make user-init` first")
    consumed = _consumed_except(vault, grant, allow_reused_nonce)
    decision = authz.verify_grant(
        grant,
        master_public_key=authz.public_key_from_b64(master_b64),
        registry=registry,
        node_identity=node_identity,
        consumed_nonces=consumed,
        now=(clock or _now)(),
    )
    if not decision.allowed:
        raise ProvenanceError(f"grant refused ({decision.reason}): {grant.get('grant_id', '?')}")
    return record, decision


def _target_within_scope(rel: PurePosixPath, grant: dict[str, Any], verb: str) -> None:
    if rel.suffix != ".md":
        raise ProvenanceError(f"{verb} refuses a non-note target: {rel!s}")
    if rel.parts[0] in ("blockchain", ".state"):
        raise ProvenanceError(f"{verb} refuses to touch {rel.parts[0]!r}: {rel!s}")
    if not grant_scope_allows(list(grant.get("vault_scope") or []), str(rel)):
        raise ProvenanceError(
            f"{verb} target {rel!s} is outside grant vault_scope {list(grant.get('vault_scope') or [])}"
        )


def promote_granted_note(
    vault: Path,
    grant: dict[str, Any],
    *,
    source: str,
    target: str,
    session: str,
    registry: dict[str, Any],
    node_identity: dict[str, Any],
    agent: str = "grant",
    model: str = "local",
    clock=None,
    allow_reused_nonce: bool = False,
) -> tuple[Path, str, dict[str, Any]]:
    """Move one note to its final place under a signed session grant.

    Returns ``(note_path, decision, ledger_block)``. Fail-closed like
    ``write_granted_note``: the grant verifies before anything moves, both the
    source and the destination must be inside ``vault_scope``, the destination
    must be free, and only a **pending raw/staged draft** — an unsigned note
    sitting in ``_raw``/``03_Sources`` or ``_staging`` — may be promoted. A
    signed note is somebody's attributed work; a grant that did not create it
    must not relocate it. Content is unchanged, so the draft's provenance stays
    as it was; the move is recorded as a new dual-signed ``grant_use`` block
    naming the final place.
    """
    record, _ = _verified_grant(
        vault,
        grant,
        registry=registry,
        node_identity=node_identity,
        session=session,
        clock=clock,
        allow_reused_nonce=allow_reused_nonce,
    )
    src = _safe_rel(source)
    dst = _safe_rel(target)
    _target_within_scope(src, grant, "promote")
    _target_within_scope(dst, grant, "promote")
    src_path = vault / src
    dst_path = vault / dst
    if not src_path.is_file():
        raise ProvenanceError(f"promote source does not exist: {src!s}")
    if dst_path.exists():
        raise ProvenanceError(f"promote destination already exists: {dst!s}")

    try:
        frontmatter, _body = split_note(src_path.read_bytes())
        tracking = tracking_of(frontmatter)
    except (FrontmatterError, UnicodeDecodeError):
        # A raw capture with no frontmatter fence is the *definition* of a
        # pending draft — nothing to parse means nothing to misattribute.
        tracking = {}
    validity = tracking.get("validity")
    pending = not isinstance(validity, dict) or validity.get("state") in (None, "unsigned")
    if not pending or src.parts[0] not in ("03_Sources", "_staging"):
        raise ProvenanceError(f"promote refuses {src!s}: only pending raw/staged drafts may be promoted")

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    src_path.replace(dst_path)
    block = append_block(
        vault,
        build_grant_use_data(
            vault=vault,
            grant=grant,
            decision="granted",
            session=session,
            note_refs=[str(dst)],
            agent=agent,
            model=model,
            record=record,
            clock=clock,
        ),
    )
    return dst_path, "granted", block


def patch_granted_note(
    vault: Path,
    grant: dict[str, Any],
    *,
    target: str,
    patch: dict[str, Any],
    session: str,
    registry: dict[str, Any],
    node_identity: dict[str, Any],
    agent: str = "grant",
    model: str = "local",
    clock=None,
    allow_reused_nonce: bool = False,
) -> tuple[Path, str, dict[str, Any]]:
    """Edit one note under a signed session grant, re-signing it.

    Returns ``(note_path, decision, ledger_block)``. The patch is a single
    ``old`` → ``new`` replacement applied to the note body — the frontmatter is
    never part of the search space — and ``old`` must appear exactly once. The
    patched body is re-signed with the user key so the note returns to ``valid``
    instead of drifting to ``stale:content``, and the mutation lands as a
    dual-signed ``grant_use`` block, the same envelope as a capture.
    """
    record, _ = _verified_grant(
        vault,
        grant,
        registry=registry,
        node_identity=node_identity,
        session=session,
        clock=clock,
        allow_reused_nonce=allow_reused_nonce,
    )
    rel = _safe_rel(target)
    _target_within_scope(rel, grant, "patch")
    note_path = vault / rel
    if not note_path.is_file():
        raise ProvenanceError(f"patch target does not exist: {rel!s}")
    if not isinstance(patch, dict) or not isinstance(patch.get("old"), str) or not isinstance(patch.get("new"), str):
        raise ProvenanceError("patch must be an object with string `old` and `new`")
    old = patch["old"]
    if not old.strip():
        raise ProvenanceError("patch `old` cannot be empty")

    frontmatter, body = split_note(note_path.read_bytes())
    if body.count(old.encode("utf-8")) != 1:
        raise ProvenanceError("patch `old` must match exactly one occurrence in the note body")
    patched = body.replace(old.encode("utf-8"), patch["new"].encode("utf-8"), 1)
    if not patched.strip():
        raise ProvenanceError("refusing a patch that would empty the note")
    note_path.write_bytes(sign_note(emit_note(frontmatter, patched), vault, agent=agent, model=model))
    block = append_block(
        vault,
        build_grant_use_data(
            vault=vault,
            grant=grant,
            decision="granted",
            session=session,
            note_refs=[str(rel)],
            agent=agent,
            model=model,
            record=record,
            clock=clock,
        ),
    )
    return note_path, "granted", block


# --- vault-wide verification ---------------------------------------------------


def note_paths(vault: Path) -> list[Path]:
    """Every markdown note in 01_Inbox..07_Archives, per the contract's layout."""
    dirs = sorted(name for name in contract()["layout"]["dirs"] if name >= "01_" and (vault / name).is_dir())
    skip = {"__pycache__", ".git", ".state", ".cache", "_staging"}
    paths: list[Path] = []
    for name in dirs:
        for path in sorted((vault / name).rglob("*.md")):
            if skip & set(path.parts) or path.name == ".gitkeep":
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


# --- secret scanning -----------------------------------------------------------


def _tracked_files(vault: Path) -> list[Path]:
    """Tracked files, or a walk when this tree has no git (an extracted bundle)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(vault), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        names = [name for name in out.stdout.decode("utf-8", "replace").split("\0") if name]
        return [vault / name for name in names]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    skip = {".git", ".state", ".cache", "__pycache__", ".venv", "dist", "node_modules"}
    suffixes = {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".template", ".conf", ".txt"}
    return [
        path for path in vault.rglob("*") if path.is_file() and not skip & set(path.parts) and path.suffix in suffixes
    ]


def _resolve_secret_ref(ref: str, store: Path) -> bytes | None:
    """The value a ref names, read only to prove it appears nowhere else.

    `ref` is a path under the state dir, an absolute path, or the name of an
    environment variable — never a value. The index schema has no field one
    could put a value in; this is the only place a value is ever read.
    """
    if ref.startswith("$"):
        raw = os.environ.get(ref[1:])
        return raw.encode("utf-8") if raw else None
    path = Path(ref) if ref.startswith("/") else store / ref
    if path.is_file():
        return path.read_bytes().strip()
    return None


def scan(vault: Path) -> tuple[int, str]:
    """Fail if a secret or key-shaped literal is reachable in a tracked file."""
    findings: list[str] = []

    index_path = vault / "00_System" / "secrets-index.json"
    registered: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text())
        except json.JSONDecodeError as exc:
            return 1, f"scan: {index_path.name} is not valid JSON: {exc}"
        entries = index.get("secrets") if isinstance(index, dict) else index
        for entry in entries or []:
            if not isinstance(entry, dict):
                findings.append(f"{index_path.name}: entry is not an object")
                continue
            extra = set(entry) - SECRET_INDEX_ENTRY_KEYS
            if extra:
                findings.append(
                    f"{index_path.name}: entry {entry.get('id')} has keys outside the schema: {sorted(extra)}"
                )
            registered.append(entry)

    store = _state_dir(vault) / "secrets"
    values: dict[str, bytes] = {}
    for entry in registered:
        value = _resolve_secret_ref(str(entry.get("ref") or ""), store)
        if value:
            values[str(entry.get("id"))] = value

    files = [path for path in _tracked_files(vault) if path.is_file()]
    for path in files:
        if not path.is_relative_to(vault):
            continue
        rel = str(path.relative_to(vault))
        if rel in _SCAN_EXEMPT or "tests" in path.parts:
            continue
        # Vendored role-local skills are third-party content with upstream
        # examples that can contain key-shaped strings. Their integrity is
        # covered by the role-skill manifest; the authored-vault scan skips
        # them so an upstream detection example is not reported as our secret.
        if rel.startswith(".opencode/skills/") or "/.opencode/skills/" in rel:
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in _PATTERNS:
            match = pattern.search(text)
            if match:
                line = text[: match.start()].count("\n") + 1
                findings.append(f"{rel}:{line}: {label}")
        for secret_id, value in values.items():
            if value and value in raw:
                findings.append(f"{rel}: contains the value of registered secret {secret_id!r}")

    if findings:
        return 1, "scan: FAILED\n  " + "\n  ".join(findings)
    return (
        0,
        f"scan: clean ({len(files)} tracked files, {len(registered)} registered secret(s), no values in the vault)",
    )


# --- CLI -----------------------------------------------------------------------


def _resolve_vault(args: argparse.Namespace) -> Path:
    for candidate in (args.vault, os.environ.get("SPARKNET_VAULT_ROOT"), os.environ.get("VAULT_PATH")):
        if candidate:
            return Path(candidate).resolve()
    return _find_vault_from_cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sparknet provenance — notes, approvals, user record, secrets")
    parser.add_argument(
        "--vault",
        help="role vault root (default: $SPARKNET_VAULT_ROOT, else walk up from cwd)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sign = sub.add_parser("sign-note", help="sign a note's current bytes with the user key")
    p_sign.add_argument("note", type=Path)
    p_sign.add_argument("--agent")
    p_sign.add_argument("--model")

    p_verify = sub.add_parser("verify-note", help="verify one note against the user record")
    p_verify.add_argument("note", type=Path)

    p_cosign = sub.add_parser(
        "co-sign",
        help="append this vault user's co-signature to a note, leaving the primary intact",
    )
    p_cosign.add_argument("note", type=Path)

    p_cosign_verify = sub.add_parser(
        "verify-co-signatures",
        help="verify a note's co-signatures against a registry and/or user.md snapshots",
    )
    p_cosign_verify.add_argument("note", type=Path)
    p_cosign_verify.add_argument(
        "--registry",
        type=Path,
        help="Master-signed node registry; default: <vault>/manifests/node-authorizations.json",
    )
    p_cosign_verify.add_argument(
        "--trusted-user",
        type=Path,
        action="append",
        default=[],
        dest="trusted_users",
        help="a user.md snapshot to trust offline (repeatable)",
    )

    p_vault = sub.add_parser("verify", help="verify notes, the ledger and approvals for a vault")
    p_vault.add_argument("--strict", action="store_true", help="treat stale:content as failure")

    p_init = sub.add_parser("user-init", help="generate the user key and fill 00_System/user.md once")
    p_init.add_argument("--owner-id", help="use this U-##### instead of assigning one")
    p_init.add_argument(
        "--force",
        action="store_true",
        help="re-key deliberately (invalidates every existing note signature)",
    )

    p_append = sub.add_parser("append-approval", help="record a dual-signed approval in the ledger")
    p_append.add_argument("--question", required=True)
    p_append.add_argument("--decision", required=True, choices=("approved", "rejected", "clarified"))
    p_append.add_argument(
        "--note",
        action="append",
        default=[],
        dest="notes",
        help="vault-relative note path (repeatable)",
    )
    p_append.add_argument("--agent", required=True)
    p_append.add_argument("--model", required=True)

    sub.add_parser(
        "append-checkpoint",
        help="append a signed checkpoint block (chain size, head hash, RFC 6962 root)",
    )

    p_anchor = sub.add_parser(
        "anchor-checkpoint",
        help="verify a signed checkpoint from another node and record the anchor",
    )
    p_anchor.add_argument(
        "--block",
        type=Path,
        required=True,
        help="the checkpoint block JSON, exactly as the other node sent it",
    )
    p_anchor.add_argument(
        "--proof",
        type=Path,
        help="consistency-proof JSON (a list of hash hex) for a growing checkpoint",
    )

    p_grant = sub.add_parser(
        "grant-write",
        help="write a vault note under a signed session grant (fail-closed; offline)",
    )
    p_grant.add_argument(
        "--grant",
        type=Path,
        required=True,
        help="the signed grant artifact (sparknet-authz.py grant-mint)",
    )
    p_grant.add_argument("--target", required=True, help="vault-relative write path, e.g. 05_Knowledge/concepts/foo.md")
    p_grant.add_argument("--body", help="note body text (one of --body / --body-file / stdin)")
    p_grant.add_argument("--body-file", type=Path, help="note body from a file")
    p_grant.add_argument("--session", required=True, help="the acting session id; a subagent passes its own child id")
    p_grant.add_argument("--agent", default="grant")
    p_grant.add_argument("--model", default="local")
    p_grant.add_argument(
        "--registry",
        type=Path,
        help="default: <vault>/manifests/node-authorizations.json",
    )
    p_grant.add_argument(
        "--node-identity",
        type=Path,
        help="default: <vault>/manifests/node-identity.json",
    )

    p_ingest = sub.add_parser("ingest", help="land one item in 01_Inbox/ as a pending note")
    p_ingest.add_argument(
        "path",
        nargs="?",
        default="-",
        help="file to read, or - for stdin (default)",
    )
    p_ingest.add_argument("--source", required=True, choices=INGEST_SOURCES)
    p_ingest.add_argument("--sender", help="the sender address; required for --source email")
    p_ingest.add_argument("--title", help="title and slug; defaults to the first heading")
    p_ingest.add_argument(
        "--classification",
        choices=_load_abac().CLASSIFICATIONS,
        help="classification recorded at O1; source defaults apply when omitted",
    )
    p_ingest.add_argument("--department", help="department attribute recorded at O1")
    p_ingest.add_argument("--agent", default="ingest")
    p_ingest.add_argument("--model", default="local")

    p_accept = sub.add_parser(
        "accept-inbox",
        help="record an inbox acceptance in the ledger (the item itself is not moved)",
    )
    p_accept.add_argument("item", help="vault-relative path under 01_Inbox/")
    p_accept.add_argument("--source", required=True, choices=INBOX_SOURCES)
    p_accept.add_argument("--decision", default="accepted", choices=("accepted", "rejected"))
    p_accept.add_argument("--reviewer", default="", help="named reviewer; required for untrusted ingress")
    p_accept.add_argument(
        "--sanitized",
        action="store_true",
        help="record that the reviewer sanitizes this untrusted item (sets validity=sanitized)",
    )
    p_accept.add_argument("--sender", default="", help="authorised sender for an email source")
    p_accept.add_argument("--note", action="append", default=[], dest="notes", help="related note path (repeatable)")
    p_accept.add_argument("--agent", default="inbox")
    p_accept.add_argument("--model", default="local")

    sub.add_parser("shims", help="prove every legacy name is a symlink to its numbered home")

    sub.add_parser("scan", help="fail on registered secrets or key-shaped literals in tracked files")

    args = parser.parse_args(argv)
    vault = _resolve_vault(args)

    try:
        if args.command == "sign-note":
            note = args.note if args.note.is_absolute() else Path.cwd() / args.note
            signed = sign_note(note.read_bytes(), vault, agent=args.agent, model=args.model)
            note.write_bytes(signed)
            print(f"signed: {note}")
            return 0
        if args.command == "verify-note":
            note = args.note if args.note.is_absolute() else Path.cwd() / args.note
            outcome, detail = verify_note(note, vault=vault)
            print(f"{outcome}: {detail}")
            return {"valid": 0, "pending": 0, "stale:metadata": 0, "stale:content": 2, "invalid": 1}[outcome]
        if args.command == "co-sign":
            note = args.note if args.note.is_absolute() else Path.cwd() / args.note
            signed = add_co_signature(note.read_bytes(), vault)
            note.write_bytes(signed)
            print(f"co-signed: {note}")
            return 0
        if args.command == "verify-co-signatures":
            note = args.note if args.note.is_absolute() else Path.cwd() / args.note
            frontmatter, _ = split_note(note.read_bytes())
            registry = None
            registry_path = args.registry or (vault / "manifests" / "node-authorizations.json")
            if registry_path.is_file():
                registry = json.loads(registry_path.read_text())
            elif args.registry is not None:
                raise ProvenanceError(f"registry not found: {registry_path}")
            trusted_users = []
            for path in args.trusted_users:
                raw_path = path if path.is_absolute() else Path.cwd() / path
                record_fm, _ = split_note(raw_path.read_bytes())
                trusted_users.append(record_fm)
            problems = verify_co_signatures(frontmatter, trusted_users=trusted_users, registry=registry)
            if not problems:
                print(f"co-signatures ok: {note}")
                return 0
            for problem in problems:
                print(f"  {problem}")
            return 1
        if args.command == "verify":
            code, text = verify_vault(vault, strict=args.strict)
            print(text)
            return code
        if args.command == "user-init":
            try:
                was_filled = user_is_filled(parse_user_record(vault))
            except ProvenanceError:
                was_filled = False
            record = user_init(vault, owner_id=args.owner_id, force=args.force)
            if was_filled and not args.force:
                print(f"already filled: {record['owner_id']} ({user_record_path(vault)}) — nothing changed")
                return 0
            print(f"filled user record: {record['owner_id']} ({user_record_path(vault)})")
            print(f"private key: {_user_key_path(vault)} (0600, never committed)")
            if args.force:
                print("re-keyed: every existing note signature is now stale — re-sign them")
            return 0
        if args.command == "ingest":
            if args.path == "-" or args.path is None:
                body = sys.stdin.buffer.read()
            else:
                source_path = Path(args.path)
                if not source_path.is_absolute():
                    source_path = Path.cwd() / source_path
                if not source_path.is_file():
                    raise ProvenanceError(f"no such file: {source_path}")
                body = source_path.read_bytes()
            if not body.strip():
                raise ProvenanceError("refusing to ingest an empty item")
            target = ingest_note(
                vault,
                body,
                source=args.source,
                sender=args.sender,
                title=args.title,
                classification=args.classification,
                department=args.department,
                agent=args.agent,
                model=args.model,
            )
            print(f"ingested: {target}")
            print("state: unsigned (pending) — acceptance and signature come later")
            return 0
        if args.command == "accept-inbox":
            record = parse_user_record(vault)
            data = build_inbox_acceptance(
                vault,
                item=args.item,
                source=args.source,
                decision=args.decision,
                reviewer=args.reviewer,
                sanitized=args.sanitized,
                sender=args.sender,
                note_refs=args.notes,
                record=record,
            )
            block = append_block(vault, data)
            print(
                f"recorded {data['acceptance_id']} as block {block['block_id']} "
                f"({data['decision']}, validity={data['validity']})"
            )
            return 0
        if args.command == "append-approval":
            record = parse_user_record(vault)
            data = build_approval_data(
                vault=vault,
                question=args.question,
                decision=args.decision,
                note_refs=args.notes,
                agent=args.agent,
                model=args.model,
                record=record,
            )
            block = append_block(vault, data)
            print(f"appended {data['approval_id']} as block {block['block_id']} (hash {block['hash'][:16]}...)")
            return 0
        if args.command == "append-checkpoint":
            block = checkpoint(vault)
            data = block["data"]
            print(
                f"appended checkpoint as block {block['block_id']}: "
                f"size {data['size']} head {data['head_hash'][:16]}... "
                f"root {data['root'][:16]}..."
            )
            return 0
        if args.command == "anchor-checkpoint":
            block = json.loads(args.block.read_text())
            proof = json.loads(args.proof.read_text()) if args.proof else None
            if proof is not None and not isinstance(proof, list):
                raise ProvenanceError("--proof must name a JSON list of hashes")
            ok, detail, _ = anchor(vault, block, proof=proof)
            print(f"{'anchored' if ok else 'refused'}: {detail}")
            return 0 if ok else 1
        if args.command == "grant-write":
            if not args.grant.is_file():
                raise ProvenanceError(f"no such grant file: {args.grant}")
            grant = json.loads(args.grant.read_text())
            if args.body_file:
                body = args.body_file.read_bytes()
            elif args.body is not None:
                body = args.body.encode("utf-8")
            else:
                body = sys.stdin.buffer.read()
            registry_path = args.registry or vault / "manifests" / "node-authorizations.json"
            identity_path = args.node_identity or vault / "manifests" / "node-identity.json"
            registry = json.loads(registry_path.read_text())
            identity = json.loads(identity_path.read_text())
            note_path, outcome, block = write_granted_note(
                vault,
                grant,
                target=args.target,
                body=body,
                session=args.session,
                registry=registry,
                node_identity=identity,
                agent=args.agent,
                model=args.model,
            )
            print(
                f"{outcome}: {note_path.relative_to(vault)} "
                f"(grant {grant['grant_id']}, session {args.session}, "
                f"block {block['block_id']} hash {block['hash'][:16]}...)"
            )
            return 0
        if args.command == "shims":
            code, text = check_shims(vault)
            print(text)
            return code
        if args.command == "scan":
            code, text = scan(vault)
            print(text)
            return code
    except ProvenanceError as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sparknet provenance primitives shared by the lifecycle modules.

This module owns the one loader shim, the canonical form, the authz/merkle/abac
loaders, the tracking contract reader, the prose-independent time and key-path
helpers, and the key-shaped patterns used by both the user-record check and the
secret scanner. It carries no note, ledger, grant or scan policy: those live in
the lifecycle modules behind ``shared/sparknet-provenance.py``.

The facade re-exports every name in ``__all__``; callers keep using
``provenance.<name>``. The module is loaded by path like every other shared
implementation, so a role cannot quietly carry a private copy.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

DEFAULT_SHARED_DIR = Path(__file__).resolve().parent

#: A node-scoped user number: U- plus five digits.
OWNER_ID_RE = re.compile(r"^U-[0-9]{5}$")

#: The fingerprint form a filled record must carry: sha256 of the raw key bytes.
FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: Where every tracking block points to find the record that defines owner_id.
#: A constant because it is a contract value (`tracking_block.required_fields.
#: owner_ref.const`), and a note whose pointer drifts resolves to nothing.
USER_RECORD_REF = "00_System/user.md"

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


__all__ = [
    "DEFAULT_SHARED_DIR",
    "FINGERPRINT_RE",
    "OWNER_ID_RE",
    "USER_RECORD_REF",
    "_PATTERNS",
    "FrontmatterError",
    "ProvenanceError",
    "_find_vault_from_cwd",
    "_iso",
    "_load_abac",
    "_load_authz",
    "_load_merkle",
    "_node_id",
    "_node_key_path",
    "_now",
    "_refuse_loose_key",
    "_split_frontmatter",
    "_state_dir",
    "_user_key_path",
    "canonical_json",
    "contract",
    "emit_yaml",
    "fingerprint_label_of_public_b64",
    "fingerprint_of_public_b64",
    "parse_yaml_subset",
    "sha256_hex",
]

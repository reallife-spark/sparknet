#!/usr/bin/env python3
"""Sparknet provenance: note signatures, ledger approvals, the user record, secret scanning.

This is the one implementation of the accountability chain described in
``contracts/provenance-protocol.md`` and machine-read from
``contracts/tracking-schema.json``:

* **Notes** in ``01_Inbox``..``07_Archives`` carry a ``tracking`` block whose
  signature envelope records what was signed — the body hash, the metadata hash
  with the metadata itself, and the tracking hash. Recording the inputs is what
  lets a verifier separate three things that would otherwise look identical:
  a routine compiler rewrite (``stale:metadata``), an edit nobody re-signed
  (``stale:content``), and a forgery (``invalid``).
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
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_SHARED_DIR = Path(__file__).resolve().parent

#: Domain separator for note signatures. Versioned so a future envelope change
#: cannot silently verify against old signatures — they would simply not match.
NOTE_DOMAIN = b"sparknet-note/1"

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
USER_RECORD_KEYS = frozenset({
    "type", "schema", "status", "owner_id", "owner_node", "role", "immutable",
    "key", "authorised_senders",
})
USER_KEY_FIELDS = frozenset({"alg", "public_key_b64", "fingerprint", "key_ref", "created"})

#: Fields the secret index may contain. There is deliberately no field a value
#: could hide in.
SECRET_INDEX_ENTRY_KEYS = frozenset({
    "id", "kind", "holder_agent", "ref", "fingerprint", "scopes", "created",
    "last_rotated", "status", "notes",
})
SECRET_INDEX_FORBIDDEN = frozenset({"value", "secret", "token", "password", "private_key"})

#: Key-shaped literals the scanner refuses to see in a tracked file. Built from
#: fragments so the patterns themselves do not match their own source.
_PATTERNS = (
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("api key literal", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "assigned secret",
        re.compile(
            r"\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']", re.I
        ),
    ),
)

#: Files exempt from the literal scan: the detector itself (its patterns would
#: match its own source) and the test suite (whose fixtures are subjects under
#: test). Everything else is scanned, including docs and configs.
_SCAN_EXEMPT = frozenset({"shared/sparknet-provenance.py"})


class ProvenanceError(Exception):
    """A refusal with a message the caller can act on."""


class FrontmatterError(ProvenanceError):
    """The note is not in the frontmatter subset this tool can parse."""


# --- loading the one crypto implementation -----------------------------------


def _load_authz() -> Any:
    """Load sparknet-authz.py by path, never by import.

    Loading by path is what proves there is one implementation. An import would
    let a role quietly end up with a private copy, and two crypto
    implementations that must agree byte-for-byte is a second trust boundary.
    """
    if "sparknet_authz" in sys.modules:
        return sys.modules["sparknet_authz"]
    candidates = [DEFAULT_SHARED_DIR / "sparknet-authz.py"]
    for env in ("SPARKNET_SHARED_DIR", "VAULT_PATH"):
        raw = os.environ.get(env)
        if raw:
            candidates.append(Path(raw) / "shared" / "sparknet-authz.py")
            candidates.append(Path(raw).parent / "shared" / "sparknet-authz.py")
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("sparknet_authz", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        # Register before exec_module: dataclasses resolves its own module via
        # sys.modules, so skipping this raises an AttributeError that names
        # neither the cause nor the file.
        sys.modules["sparknet_authz"] = module
        spec.loader.exec_module(module)
        return module
    raise ProvenanceError(
        "cannot find shared/sparknet-authz.py; set SPARKNET_SHARED_DIR. "
        "There is exactly one signing implementation and this tool does not "
        "carry a fallback."
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
                f"cannot find {path}; this tool refuses to guess its own rules. "
                f"Set SPARKNET_CONTRACTS_DIR."
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


# --- frontmatter: a documented YAML subset ------------------------------------
#
# There is no YAML library in this fabric (third-party imports are
# `cryptography` only — peer-node/tests/test_services.py enforces it), and a
# signature must be reproducible, so the parser cannot be a guess. This is a
# deliberately small subset: nested mappings, sequences, quoted and plain
# scalars, flow lists of scalars. Block scalars (`|`, `>`) and tabs are refused
# with a message rather than approximated. `sign-note` always writes through the
# emitter below, so anything it signs parses back to the same mapping.


class _Line:
    __slots__ = ("indent", "text")

    def __init__(self, indent: int, text: str) -> None:
        self.indent = indent
        self.text = text


def _split_frontmatter(raw: bytes) -> tuple[bytes, bytes]:
    """Split a note into (frontmatter_bytes, body_bytes)."""
    if not raw.startswith(b"---\n"):
        raise FrontmatterError("note does not start with a '---' frontmatter fence")
    end = raw.find(b"\n---\n", 3)
    if end == -1:
        raise FrontmatterError("frontmatter is not closed by a '---' fence")
    return raw[4:end], raw[end + 5:]


#: `key: |`, `key: >-`, … — a block scalar. Expanded *before* the line filter
#: runs, because inside a block scalar a blank line is a blank line and a `#`
#: is content: the filter that drops both would otherwise silently change the
#: bytes every signature hashes.
_BLOCK_SCALAR = re.compile(r"^(?P<key>[^:#]+?):[ \t]*(?P<ind>[|>][+-]?)[ \t]*$")


def _fold_block(content: list[str], indicator: str) -> str:
    """Turn collected block-scalar lines into the scalar's string value."""
    style, chomp = indicator[0], indicator[1:]
    if style == "|":
        text = "\n".join(content)
    else:
        parts: list[str] = []
        for index, line in enumerate(content):
            if index == 0:
                parts.append(line)
            elif not line:
                parts.append("\n")
            elif not content[index - 1]:
                parts.append(line)
            else:
                parts.append(" " + line)
        text = "".join(parts)
    if chomp == "-":
        return text.rstrip("\n")
    if chomp == "+":
        return text
    return text.rstrip("\n") + ("\n" if text.strip() else "")


def _expand_block_scalars(text: str) -> str:
    """Replace `key: >-`/`|` blocks with one quoted line each.

    The rest of the parser only ever sees `key: "…"`, so a block scalar cannot
    smuggle in an indent the subset would reject. Content keeps its relative
    indentation (deeper lines stay deeper), which is what makes a literal
    block round-trip.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        match = _BLOCK_SCALAR.match(lines[i])
        if match is None:
            out.append(lines[i])
            i += 1
            continue
        key_indent = len(lines[i]) - len(lines[i].lstrip())
        content: list[str] = []
        pending_blanks: list[str] = []
        content_indent: int | None = None
        j = i + 1
        while j < len(lines):
            line = lines[j]
            if not line.strip():
                pending_blanks.append("")
                j += 1
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= key_indent:
                break
            if content_indent is None:
                content_indent = indent
            content.extend(pending_blanks)
            pending_blanks = []
            content.append(
                line[content_indent:] if indent >= content_indent else line.lstrip()
            )
            j += 1
        # Trailing blank lines belong to the block under `+` chomping; under
        # the default clip and under `-` they are stripped off again below.
        content.extend(pending_blanks)
        value = _fold_block(content, match.group("ind"))
        out.append(f"{match.group('key')}: {json.dumps(value, ensure_ascii=False)}")
        i = j
    return "\n".join(out)


def parse_yaml_subset(text: str) -> dict[str, Any]:
    lines: list[_Line] = []
    text = _expand_block_scalars(text)
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent_text = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in indent_text:
            raise FrontmatterError(f"line {number}: tabs are not allowed in frontmatter")
        stripped = raw.strip()
        if stripped[:1] in ("|", ">") and stripped[:2] not in ("|-", ">-", "|+", ">+"):
            raise FrontmatterError(
                f"line {number}: block scalars are outside the frontmatter subset; "
                f"use a quoted single-line string"
            )
        lines.append(_Line(len(indent_text), stripped))
    if not lines:
        return {}
    value, next_index = _parse_block(lines, 0, lines[0].indent)
    if next_index != len(lines):
        raise FrontmatterError(f"unparsed frontmatter at {lines[next_index].text!r}")
    if not isinstance(value, dict):
        raise FrontmatterError("frontmatter must be a mapping at the top level")
    return value


def _is_seq_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _split_entry(text: str) -> tuple[str, str] | None:
    """Split `key: value` / `key:` on the first colon YAML treats as an entry."""
    if text.startswith(('"', "'")):
        return None
    match = re.match(r"^([^:]+?):(\s.*|\s*)$", text)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _parse_block(lines: list[_Line], start: int, indent: int) -> tuple[Any, int]:
    if start >= len(lines):
        return None, start
    if lines[start].indent != indent:
        raise FrontmatterError(f"unexpected indent at {lines[start].text!r}")
    if _is_seq_item(lines[start].text):
        return _parse_seq(lines, start, indent)
    return _parse_map(lines, start, indent)


def _parse_seq(lines: list[_Line], start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    i = start
    while i < len(lines) and lines[i].indent == indent and _is_seq_item(lines[i].text):
        content = lines[i].text[1:].lstrip()
        if not content:
            if i + 1 < len(lines) and lines[i + 1].indent > indent:
                value, i = _parse_block(lines, i + 1, lines[i + 1].indent)
                items.append(value)
            else:
                items.append(None)
                i += 1
            continue
        if _split_entry(content) is None:
            items.append(_scalar(content))
            i += 1
            continue
        # The item is itself a mapping: rewrite this line at the item's content
        # column, then parse the item as a map. Lines still indented deeper than
        # the sequence belong to this item and no further.
        item_lines = [_Line(indent + 2, content)]
        j = i + 1
        while j < len(lines) and lines[j].indent > indent:
            item_lines.append(lines[j])
            j += 1
        value, consumed = _parse_block(item_lines, 0, item_lines[0].indent)
        if consumed != len(item_lines):
            raise FrontmatterError(
                f"unparsed content in sequence item: {item_lines[consumed].text!r}"
            )
        items.append(value)
        i = j
    return items, i


def _parse_map(lines: list[_Line], start: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    i = start
    while i < len(lines) and lines[i].indent == indent:
        if _is_seq_item(lines[i].text):
            break
        entry = _split_entry(lines[i].text)
        if entry is None:
            raise FrontmatterError(f"expected 'key: value', got {lines[i].text!r}")
        key, rest = entry
        if rest:
            out[key] = _scalar(rest)
            i += 1
        elif i + 1 < len(lines) and lines[i + 1].indent > indent:
            value, i = _parse_block(lines, i + 1, lines[i + 1].indent)
            out[key] = value
        elif (
            i + 1 < len(lines)
            and lines[i + 1].indent == indent
            and _is_seq_item(lines[i + 1].text)
        ):
            # YAML allows a sequence at the same indent as its key.
            value, i = _parse_seq(lines, i + 1, indent)
            out[key] = value
        else:
            out[key] = None
            i += 1
    if i < len(lines) and lines[i].indent > indent:
        raise FrontmatterError(f"unexpected indent at {lines[i].text!r}")
    return out, i


def _scalar(text: str) -> Any:
    if text.startswith('"'):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise FrontmatterError(f"unterminated quoted string: {text!r}") from exc
    if text.startswith("'"):
        if not text.endswith("'") or len(text) < 2:
            raise FrontmatterError(f"unterminated quoted string: {text!r}")
        return text[1:-1].replace("''", "'")
    if text == "{}":
        return {}
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        parts: list[str] = []
        depth = 0
        quote = ""
        current = ""
        for char in inner:
            if quote:
                current += char
                if char == quote:
                    quote = ""
                continue
            if char in "\"'":
                quote = char
                current += char
                continue
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
            if char == "," and depth == 0:
                parts.append(current.strip())
                current = ""
                continue
            current += char
        if current.strip():
            parts.append(current.strip())
        return [_scalar(part) for part in parts]
    lowered = text.lower()
    if lowered in ("null", "~"):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


#: Words the parser reads as something other than the string they spell.
_PLAIN_UNSAFE_WORDS = frozenset({"null", "~", "true", "false", "yes", "no", "on", "off"})

#: A scalar the parser would hand back as a number rather than as the string.
_PLAIN_UNSAFE_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

#: Leading characters YAML reserves for indicators; a plain scalar may not start
#: with one without being read as a sequence item, a comment, a tag and so on.
_PLAIN_UNSAFE_LEAD = frozenset("-?:,[]{}#&*!|>'\"%@`")

#: Patterns that make a plain value ambiguous to a reader outside this subset:
#: a `key: value` pair hiding in a value, a trailing comment, or a stray quote.
_PLAIN_UNSAFE_INNER = (": ", " #", '"', "'", "\n", "\t")


def _fmt_str(value: str) -> str:
    """Quote only what needs quoting.

    Quoting everything would be safe and unreadable — these files are knowledge
    pages a human opens, and `title: "the vault"` in every frontmatter is noise.
    The rule is therefore narrow: emit plain when re-parsing the plain form
    yields exactly this string and no YAML reader could take it otherwise.
    """
    needs_quotes = (
        value == ""
        or value.strip() != value
        or value.lower() in _PLAIN_UNSAFE_WORDS
        or _PLAIN_UNSAFE_NUMBER.fullmatch(value) is not None
        or value[0] in _PLAIN_UNSAFE_LEAD
        or any(pattern in value for pattern in _PLAIN_UNSAFE_INNER)
    )
    if needs_quotes:
        return json.dumps(value, ensure_ascii=False)
    return value


def _fmt_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return _fmt_str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_fmt_scalar(item) for item in value) + "]"
    raise FrontmatterError(f"cannot emit value of type {type(value).__name__}")


def emit_yaml(data: dict[str, Any]) -> str:
    """Serialize back through the subset, so what is signed is what parses."""
    return "\n".join(_emit_map(data, 0)) + "\n"


def _emit_map(data: dict[str, Any], indent: int) -> list[str]:
    pad = "  " * indent
    out: list[str] = []
    for key, value in data.items():
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", str(key)):
            raise FrontmatterError(f"frontmatter key {key!r} is outside the subset")
        if isinstance(value, dict):
            if not value:
                out.append(f"{pad}{key}: {{}}")
            else:
                out.append(f"{pad}{key}:")
                out.extend(_emit_map(value, indent + 1))
        elif isinstance(value, list):
            if not value:
                out.append(f"{pad}{key}: []")
            elif any(isinstance(item, dict | list) for item in value):
                out.append(f"{pad}{key}:")
                for item in value:
                    if not isinstance(item, dict):
                        raise FrontmatterError(
                            "nested sequences are outside the frontmatter subset"
                        )
                    sub = _emit_map(item, indent + 1)
                    item_pad = "  " * (indent + 1)
                    out.append(f"{pad}  - {sub[0][len(item_pad):]}")
                    out.extend(sub[1:])
            else:
                out.append(f"{pad}{key}: " + _fmt_scalar(value))
        else:
            out.append(f"{pad}{key}: {_fmt_scalar(value)}")
    return out


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


def note_hashes(meta: dict[str, Any], tracking: dict[str, Any], body: bytes) -> dict[str, str]:
    return {
        "body": sha256_hex(body),
        "meta": sha256_hex(canonical_json(meta)),
        "tracking": sha256_hex(canonical_json(unsigned_tracking(tracking))),
    }


def note_message(hashes: dict[str, str]) -> bytes:
    """What the user key signs over: domain, then the three hashes, LF-joined."""
    return (
        NOTE_DOMAIN + b"\n"
        + hashes["body"].encode("ascii") + b"\n"
        + hashes["meta"].encode("ascii") + b"\n"
        + hashes["tracking"].encode("ascii")
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
        "sig": authz.sign_bytes(private_key, note_message(hashes)),
        "key_id": owner_id,
        "key_fingerprint": fingerprint_label_of_public_b64(public_b64),
        "signed_body_sha256": hashes["body"],
        "signed_meta_sha256": hashes["meta"],
        "signed_tracking_sha256": hashes["tracking"],
        # The metadata itself, not just its hash: when only allowlisted fields
        # changed, a verifier must be able to say *which* keys moved. An
        # aggregate hash can tell that the metadata changed and nothing more.
        "signed_meta": meta,
        "signed_at": _iso(_now()),
    }
    tracking["signature"] = signature
    frontmatter["tracking"] = tracking
    return emit_note(frontmatter, body)


def verify_note(
    path: Path, record: dict[str, Any] | None = None, vault: Path | None = None
) -> tuple[str, str]:
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
        return "invalid", (
            f"owner_id {owner_id!r} is not the user record's {record.get('owner_id')!r}"
        )
    if signature.get("key_id") != owner_id:
        return "invalid", f"signature key_id {signature.get('key_id')!r} does not match owner_id"
    if signature.get("key_fingerprint") != expected_fingerprint:
        return "invalid", "signed under a different key than user.md holds"

    signed_body = str(signature.get("signed_body_sha256") or "")
    signed_meta = str(signature.get("signed_meta_sha256") or "")
    signed_tracking = str(signature.get("signed_tracking_sha256") or "")
    recorded = {"body": signed_body, "meta": signed_meta, "tracking": signed_tracking}
    if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in recorded.values()):
        return "invalid", "envelope does not record three 64-hex hashes"

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
    return {
        key
        for key in set(current) | set(signed)
        if current.get(key) != signed.get(key)
    }


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
                    problems.append(
                        "user record fingerprint is not the digest of its own public key"
                    )
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
    agent: str = "ingest",
    model: str = "local",
    clock=None,
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
    record = parse_user_record(vault)
    if source == "email":
        address = (sender or "").strip()
        if not address:
            raise ProvenanceError("--sender is required for a source of email")
        if address not in authorised_senders(record):
            raise ProvenanceError(
                f"sender {address!r} is not on authorised_senders in "
                f"{USER_RECORD_REF} — the inbox policy fails closed"
            )

    text = body.decode("utf-8", "replace")
    heading = next(
        (line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#")),
        "",
    )
    label = title or heading or source
    slug = slugify(label)
    target = vault / "01_Inbox" / f"{slug}.md"
    if target.exists():
        raise ProvenanceError(f"{target} already exists — refusing to overwrite an inbox item")

    now = (clock or _now)()
    meta: dict[str, Any] = {
        "title": label,
        "type": "inbox-item",
        "source": source,
        "captured": now.date().isoformat(),
    }
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
    """sha256 over the block minus its own `hash`.

    Identical to master-node's `block_hash`, on purpose: writer and verifier must
    agree byte-for-byte or the chain verifies nowhere. Excluding nothing else
    matters — a field not covered by the hash is freely editable, which would
    make the chain decorative.
    """
    payload = {k: v for k, v in block.items() if k != "hash"}
    return sha256_hex(canonical_json(payload))


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProvenanceError(f"ledger not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"ledger is not valid JSON: {exc}") from exc


def verify_chain(ledger: dict[str, Any]) -> tuple[bool, str]:
    """Walk the chain and check every link. Returns (ok, detail)."""
    required = contract()["ledger_block"]["required"]
    blocks = ledger.get("blocks")
    if not isinstance(blocks, list):
        return False, "ledger has no blocks array"
    previous = ""
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            return False, f"block {index} is not an object"
        missing = [f for f in required if f not in block]
        if missing:
            return False, f"block {index} missing {', '.join(missing)}"
        if block["prev_hash"] != previous:
            return False, (
                f"block {index} ({block['block_id']}) links to {block['prev_hash']!r}, "
                f"expected {previous!r}"
            )
        if "hash" in block and block["hash"] != block_hash(block):
            return False, (
                f"block {index} ({block['block_id']}) has been altered: it does not "
                f"re-hash to its recorded hash"
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
    attestation that this node recorded it. Neither alone places a block — the
    block-level signature restates the node's countersignature over the same
    payload, and `hash` binds the whole block into the chain.
    """
    if decision not in ("approved", "rejected", "clarified"):
        raise ProvenanceError(f"decision must be approved|rejected|clarified, got {decision!r}")
    moment = (clock or _now)()
    try:
        blocks = load_ledger(vault / "blockchain" / "ledger.json").get("blocks", [])
    except ProvenanceError:
        blocks = []
    approvals = sum(
        1
        for block in blocks
        if isinstance(block, dict) and (block.get("data") or {}).get("event") == "approval"
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


def append_block(vault: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Append one canonical block to this vault's ledger and write it atomically."""
    ledger_path = vault / "blockchain" / "ledger.json"
    if ledger_path.is_file():
        ledger = load_ledger(ledger_path)
    else:
        ledger = {"version": "1.0", "genesis_hash": "", "blocks": []}
    blocks = ledger.setdefault("blocks", [])
    previous = blocks[-1]["hash"] if blocks else ledger.get("genesis_hash", "")
    index = len(blocks)
    block: dict[str, Any] = {
        "block_id": f"{index:08d}",
        "prev_hash": previous,
        "timestamp": _iso(_now()),
        "data": data,
        "signature": data.get("signatures", {}).get("node", ""),
    }
    block["hash"] = block_hash(block)
    blocks.append(block)

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger_path.with_name(f".{ledger_path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(ledger, indent=2) + "\n")
    tmp.chmod(0o600)
    os.replace(tmp, ledger_path)
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
        return problems + [f"user record: {exc}"]

    peer_events = set(contract()["approval"]["event_vocabulary"]["peer"])
    for block in ledger.get("blocks", []):
        if not isinstance(block, dict):
            continue
        data = block.get("data") or {}
        if data.get("event") not in peer_events:
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
        if block.get("signature") != signatures.get("node"):
            problems.append(f"{approval_id}: block signature does not restate the node countersignature")
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
        if isinstance(block, dict) and isinstance(block.get("data"), dict)
        and block["data"].get("approval_id")
    }


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
        1
        for block in blocks
        if isinstance(block, dict) and (block.get("data") or {}).get("event") == "grant_use"
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
        (
            line.lstrip("#").strip()
            for line in body.decode("utf-8", "replace").splitlines()
            if line.startswith("#")
        ),
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
    dirs = sorted(
        name
        for name in contract()["layout"]["dirs"]
        if name >= "01_" and (vault / name).is_dir()
    )
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
        lines.append(
            f"user record: filled, {record.get('owner_id')}, "
            f"{('lock ok' if lock_ok else 'LOCK MISMATCH')}"
        )
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
    lines.append(
        f"notes: {len(paths)} checked — "
        + ", ".join(f"{counts[k]} {k}" for k in counts)
    )

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
        lines.append(
            f"  ✗ notes claim approvals that are not in the ledger: {sorted(missing)}"
        )
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
        path
        for path in vault.rglob("*")
        if path.is_file() and not skip & set(path.parts) and path.suffix in suffixes
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
                    f"{index_path.name}: entry {entry.get('id')} has keys outside the "
                    f"schema: {sorted(extra)}"
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
        f"scan: clean ({len(files)} tracked files, {len(registered)} registered secret(s), "
        f"no values in the vault)",
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
        "--note", action="append", default=[], dest="notes",
        help="vault-relative note path (repeatable)",
    )
    p_append.add_argument("--agent", required=True)
    p_append.add_argument("--model", required=True)

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
        "path", nargs="?", default="-",
        help="file to read, or - for stdin (default)",
    )
    p_ingest.add_argument("--source", required=True, choices=INGEST_SOURCES)
    p_ingest.add_argument("--sender", help="the sender address; required for --source email")
    p_ingest.add_argument("--title", help="title and slug; defaults to the first heading")
    p_ingest.add_argument("--agent", default="ingest")
    p_ingest.add_argument("--model", default="local")

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
            return {"valid": 0, "pending": 0, "stale:metadata": 0, "stale:content": 2, "invalid": 1}[
                outcome
            ]
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
                agent=args.agent,
                model=args.model,
            )
            print(f"ingested: {target}")
            print("state: unsigned (pending) — acceptance and signature come later")
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
            print(
                f"appended {data['approval_id']} as block {block['block_id']} "
                f"(hash {block['hash'][:16]}...)"
            )
            return 0
        if args.command == "grant-write":
            assert args.grant.is_file(), f"no such grant file: {args.grant}"
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

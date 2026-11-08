#!/usr/bin/env python3
"""Check a node-authorization registry against ``contracts/registry-schema.json``.

Why this exists
~~~~~~~~~~~~~~~
A registry is the one document the Master signs and a peer verifies.
If the two disagree about its shape, the peer rejects what the Master signed -
and the failure looks like a signature problem, not a shape problem, which is
the worst place to debug it. The draft schema this replaces described a shape
nothing produced: a ``role`` field no document carries, a ``schema_version`` of
``1.0.0`` while the shipped registry says ``1.0``, and an entry signature field
named ``signature`` while the one implementation emits and verifies
``signature_b64``. A schema nobody produces is decoration.

So the shape is stated once, in ``contracts/registry-schema.json``, and this
checks a document against it. The canonical shape is the one
``shared/sparknet-authz.py`` actually signs and evaluates; where the contract
and that module could disagree, the module is what runs and this module fails
the build when they do.

What it checks
~~~~~~~~~~~~~~

- every required field present, no undeclared field present;
- every field has its declared type, and its declared const/pattern/format hold;
- the identity carries exactly the identity fields, and the entry's
  ``fingerprint`` equals ``authz.fingerprint(identity)``;
- the granted capabilities are a subset of the closed vocabulary;
- each entry's signature verifies under the ``master_public_key_b64`` the
  document names;
- the contract's field lists still equal the implementation's constants.

Deliberately standard library only
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The fabric's runtime dependency allow-list is ``cryptography`` alone, and the
CI gate installs exactly that plus pytest and ruff. A validator that needed
``jsonschema`` would pass here and fail on a node, so this one reads the
standard library only and interprets the small schema vocabulary the contract
declares. A keyword the checker does not implement is **refused**, not ignored:
a schema rule nobody enforces is a rule that silently stops being true.

Usage::

    shared/sparknet-registry-schema.py --registry <path>
    shared/sparknet-registry-schema.py --registry <path> --no-verify-signatures

Exit codes: 0 conforms, 1 the document does not conform, 2 usage or I/O error.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

DEFAULT_SHARED_DIR = Path(__file__).resolve().parent

#: The contract this checker implements. One file, one shape.
SCHEMA_FILE = "registry-schema.json"

#: The keywords a field specification may use. Anything else is refused.
FIELD_KEYWORDS = frozenset(
    {
        "type",
        "required",
        "const",
        "pattern",
        "items",
        "fields",
        "nonempty",
        "format",
    }
)

#: Keywords that document a field without constraining it. They are read by
#: humans, never by the checker - so an annotation can never be mistaken for a
#: rule that is enforced.
ANNOTATION_KEYWORDS = frozenset({"purpose", "description"})

#: The value formats a field may declare.
FORMATS = frozenset({"base64", "base64_32", "base64_64", "timestamp", "ipv4", "ipv4_host"})

#: The JSON types a field may declare.
TYPES = frozenset({"string", "boolean", "object", "array", "null"})

_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


class RegistrySchemaError(Exception):
    """Raised when the schema itself cannot be read or is not understood."""


# --- locating the contract -----------------------------------------------------


def contracts_dir() -> Path:
    """The contracts directory, resolved from this module's own location.

    ``shared/`` sits next to ``contracts/`` in a checkout and in a node bundle,
    so the parent of this file is the only place the contract can be.
    """
    return DEFAULT_SHARED_DIR.parent / "contracts"


def schema_path() -> Path:
    return contracts_dir() / SCHEMA_FILE


def load_schema(path: Path | None = None) -> dict:
    """Read the contract. Raises :class:`RegistrySchemaError` if it cannot be read."""
    target = path or schema_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistrySchemaError(f"registry schema not found: {target}") from exc
    except json.JSONDecodeError as exc:
        raise RegistrySchemaError(f"{target}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RegistrySchemaError(f"{target}: the schema must be a JSON object")
    for section in ("document_fields", "entry_fields", "identity_fields"):
        if not isinstance(data.get(section), dict):
            raise RegistrySchemaError(f"{target}: missing the {section!r} table")
    return data


def load_authz():
    """The one signed-authorization implementation, loaded by path.

    By path, not by import: an import would let a role carry a private copy,
    and two copies that must agree byte-for-byte are a second trust boundary.
    """
    return load_shared(
        "sparknet-authz.py",
        "authz",
        dirs=[DEFAULT_SHARED_DIR],
        error=RegistrySchemaError,
        message="cannot locate sparknet-authz.py; the fabric carries exactly one implementation",
    )


# --- the schema vocabulary -----------------------------------------------------


def _type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _check_format(value: str, fmt: str, where: str, problems: list[str]) -> None:
    if fmt == "base64":
        try:
            base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            problems.append(f"{where}: {value!r} is not valid base64")
        return
    if fmt in {"base64_32", "base64_64"}:
        want = 32 if fmt == "base64_32" else 64
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            problems.append(f"{where}: {value!r} is not valid base64")
            return
        if len(raw) != want:
            problems.append(f"{where}: expected {want} bytes of {fmt}, got {len(raw)}")
        return
    if fmt == "timestamp":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            problems.append(f"{where}: {value!r} is not an ISO-8601 timestamp")
        return
    if fmt == "ipv4":
        match = _IPV4.match(value)
        if not match or any(int(part) > 255 for part in match.groups()):
            problems.append(f"{where}: {value!r} is not an IPv4 address")
        return
    if fmt == "ipv4_host":
        address, _, prefix = value.partition("/")
        match = _IPV4.match(address)
        if not match or any(int(part) > 255 for part in match.groups()) or (prefix and prefix != "32"):
            problems.append(f"{where}: {value!r} is not an IPv4 host address or /32")
        return
    problems.append(f"{where}: unknown format {fmt!r}")


def _check_value(value: Any, spec: dict, where: str, problems: list[str], schema: dict) -> None:
    """Check one value against one field specification."""
    unknown = set(spec) - FIELD_KEYWORDS - ANNOTATION_KEYWORDS
    if unknown:
        problems.append(f"{where}: the schema uses unknown keyword(s) {sorted(unknown)}; the checker refuses them")

    declared = spec.get("type")
    if declared is not None:
        types = declared if isinstance(declared, list) else [declared]
        for name in types:
            if name not in TYPES:
                problems.append(f"{where}: unknown type {name!r}")
        actual = _type_of(value)
        if actual not in types:
            problems.append(f"{where}: expected {'/'.join(types)}, got {actual}")
            return

    if "const" in spec and value != spec["const"]:
        problems.append(f"{where}: expected {spec['const']!r}, got {value!r}")

    pattern = spec.get("pattern")
    if pattern is not None and isinstance(value, str) and not re.search(pattern, value):
        problems.append(f"{where}: {value!r} does not match {pattern}")

    fmt = spec.get("format")
    if fmt is not None:
        if fmt not in FORMATS:
            problems.append(f"{where}: unknown format {fmt!r}")
        elif isinstance(value, str):
            _check_format(value, fmt, where, problems)

    if spec.get("nonempty") and isinstance(value, list) and not value:
        problems.append(f"{where}: must not be empty")

    # A field may point at another table: an identity is checked against
    # identity_fields rather than being taken on trust as "an object".
    nested = spec.get("fields")
    if nested is not None and isinstance(value, dict):
        table = schema.get(nested)
        if not isinstance(table, dict):
            problems.append(f"{where}: the schema points at unknown field table {nested!r}")
        else:
            _check_fields(value, table, where, problems, schema)


def _check_fields(value: dict, table: dict, where: str, problems: list[str], schema: dict) -> None:
    """Check an object's fields against a field table."""
    for name, spec in table.items():
        if name in value:
            _check_value(value[name], spec, f"{where}.{name}", problems, schema)
        elif spec.get("required"):
            problems.append(f"{where}: missing required field {name!r}")

    allowed = set(table)
    for name in value:
        if name not in allowed:
            problems.append(f"{where}: undeclared field {name!r}")


def _check_array_items(
    value: list,
    spec: dict,
    where: str,
    problems: list[str],
    schema: dict,
) -> None:
    """Check an array's elements against its ``items`` keyword."""
    items = spec.get("items")
    if items is None:
        return
    if items == "entry":
        table = schema["entry_fields"]
    elif items == "string":
        table = None
    else:
        problems.append(f"{where}: unknown items kind {items!r}")
        return
    for index, element in enumerate(value):
        if items == "string":
            _check_value(element, {"type": "string"}, f"{where}[{index}]", problems, schema)
            continue
        if not isinstance(element, dict):
            problems.append(f"{where}[{index}]: expected an object, got {_type_of(element)}")
            continue
        _check_fields(element, table, f"{where}[{index}]", problems, schema)


# --- the semantic checks -------------------------------------------------------


def check_contract(schema: dict, authz) -> list[str]:
    """The contract must still say what the implementation does.

    This is the drift gate: the shape is written down in the contract, but the
    implementation is what runs, so the two are compared rather than trusted.
    """
    problems: list[str] = []
    contract_identity = tuple(schema.get("identity_fields", {}))
    if contract_identity != tuple(authz.IDENTITY_FIELDS):
        problems.append(
            f"the contract's identity_fields {list(contract_identity)} drifted from the "
            f"implementation's {list(authz.IDENTITY_FIELDS)}"
        )
    contract_signed = tuple(schema.get("signed_envelope_fields", ()))
    if contract_signed != tuple(authz.SIGNED_FIELDS):
        problems.append(
            f"the contract's signed_envelope_fields {list(contract_signed)} drifted from the "
            f"implementation's {list(authz.SIGNED_FIELDS)}"
        )
    if schema.get("signature_field") != "signature_b64":
        problems.append(
            f"the contract's signature_field is {schema.get('signature_field')!r}; the "
            "implementation reads and writes 'signature_b64'"
        )
    if "signature_b64" not in schema.get("entry_fields", {}):
        problems.append("the contract's entry_fields do not declare 'signature_b64'")
    return problems


def check_entry_semantics(entry: dict, index: int, authz, capabilities: set[str]) -> list[str]:
    """The checks that only the implementation can make."""
    problems: list[str] = []
    where = f"authorizations[{index}]"

    identity = entry.get("identity")
    if isinstance(identity, dict):
        unknown = set(identity) - set(authz.IDENTITY_FIELDS)
        if unknown:
            problems.append(f"{where}.identity: undeclared field(s) {sorted(unknown)}")
        try:
            expected = authz.fingerprint(identity)
        except Exception as exc:  # the implementation's own refusal
            problems.append(f"{where}.identity: {exc}")
        else:
            if entry.get("fingerprint") != expected:
                problems.append(
                    f"{where}.fingerprint: {entry.get('fingerprint')!r} is not the fingerprint of "
                    f"the identity it carries ({expected})"
                )

    granted = entry.get("capabilities")
    if isinstance(granted, list):
        outside = sorted(c for c in granted if c not in capabilities)
        if outside:
            problems.append(f"{where}.capabilities: {outside} are not in the closed vocabulary")
        # An authorizing entry that grants nothing is a mistake; a *revoked*
        # entry grants nothing on purpose, and that is how the Master's revoke
        # path expresses it. Requiring a non-empty list here would make the
        # document peers must install to learn about a revocation un-installable.
        if not granted and not entry.get("revoked"):
            problems.append(f"{where}.capabilities: an authorizing entry must grant at least one capability")
        if granted and entry.get("revoked"):
            problems.append(f"{where}.capabilities: a revoked entry must carry an empty capability list")

    return problems


def check_signatures(document: dict, authz) -> list[str]:
    """Verify every entry's signature under the key the document names.

    A registry that conforms in shape but carries a bad signature is not a
    registry; checking the shape alone would let that pass.
    """
    problems: list[str] = []
    raw = document.get("master_public_key_b64")
    if not isinstance(raw, str):
        problems.append("master_public_key_b64: missing or not a string; no signature can be checked")
        return problems
    try:
        public_key = authz.public_key_from_b64(raw)
    except Exception as exc:  # the implementation's own refusal
        problems.append(f"master_public_key_b64: {exc}")
        return problems

    entries = document.get("authorizations")
    if not isinstance(entries, list):
        return problems
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        signature = entry.get("signature_b64")
        if not isinstance(signature, str):
            problems.append(f"authorizations[{index}]: no signature_b64 to verify")
            continue
        try:
            message = authz.authorization_message(entry)
        except Exception as exc:  # the implementation's own refusal
            problems.append(f"authorizations[{index}]: {exc}")
            continue
        if not authz.verify_signature(public_key, signature, message):
            problems.append(
                f"authorizations[{index}]: the signature does not verify under the "
                "master_public_key_b64 this document names"
            )
    return problems


# --- the entry point -----------------------------------------------------------


def validate_document(
    document: Any,
    schema: dict,
    authz,
    *,
    verify_signatures: bool = True,
) -> list[str]:
    """Return the problems in ``document``; an empty list means it conforms."""
    problems: list[str] = []
    if not isinstance(document, dict):
        return [f"the registry must be a JSON object, got {_type_of(document)}"]

    _check_fields(document, schema["document_fields"], "registry", problems, schema)

    entries = document.get("authorizations")
    if isinstance(entries, list):
        _check_array_items(entries, {"items": "entry"}, "registry.authorizations", problems, schema)
        capabilities = set(getattr(authz, "KNOWN_CAPABILITIES", ()))
        seen_ids: set[str] = set()
        seen_fps: set[str] = set()
        for index, entry in enumerate(entries):
            if isinstance(entry, dict):
                node_id = (
                    (entry.get("identity") or {}).get("node_id") if isinstance(entry.get("identity"), dict) else None
                )
                if isinstance(node_id, str):
                    if node_id in seen_ids:
                        problems.append(f"authorizations[{index}].identity.node_id: duplicate node id {node_id!r}")
                    seen_ids.add(node_id)
                fp = entry.get("fingerprint")
                if isinstance(fp, str):
                    if fp in seen_fps:
                        problems.append(f"authorizations[{index}].fingerprint: duplicate fingerprint {fp!r}")
                    seen_fps.add(fp)
                problems.extend(check_entry_semantics(entry, index, authz, capabilities))

    if verify_signatures and isinstance(entries, list):
        problems.extend(check_signatures(document, authz))

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="check a node-authorization registry against contracts/registry-schema.json",
    )
    parser.add_argument(
        "--registry",
        help="the registry document to check (default: the peer's shipped registry)",
    )
    parser.add_argument(
        "--schema",
        help=f"the contract to check against (default: <fabric>/contracts/{SCHEMA_FILE})",
    )
    parser.add_argument(
        "--no-verify-signatures",
        action="store_true",
        help="check the shape only; do not verify entry signatures",
    )
    args = parser.parse_args(argv)

    default_registry = DEFAULT_SHARED_DIR.parent / "peer-node" / "manifests" / "node-authorizations.json"
    registry_path = Path(args.registry) if args.registry else default_registry
    if not registry_path.is_file():
        print(f"sparknet-registry-schema: registry not found: {registry_path}", file=sys.stderr)
        return 2

    try:
        schema = load_schema(Path(args.schema) if args.schema else None)
    except RegistrySchemaError as exc:
        print(f"sparknet-registry-schema: {exc}", file=sys.stderr)
        return 2

    try:
        authz = load_authz()
    except RegistrySchemaError as exc:
        print(f"sparknet-registry-schema: {exc}", file=sys.stderr)
        return 2

    problems = check_contract(schema, authz)
    try:
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"sparknet-registry-schema: {registry_path}: invalid JSON: {exc}", file=sys.stderr)
        return 2

    problems.extend(validate_document(document, schema, authz, verify_signatures=not args.no_verify_signatures))

    if problems:
        print(f"sparknet-registry-schema: {registry_path} does not conform:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    entries = document.get("authorizations") if isinstance(document, dict) else None
    count = len(entries) if isinstance(entries, list) else 0
    print(f"sparknet-registry-schema: {registry_path} conforms to {SCHEMA_FILE} ({count} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

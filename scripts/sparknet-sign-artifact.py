#!/usr/bin/env python3
"""Detached signatures for bundles and staged release trees.

A checksum inside an archive proves only that the archive is internally
consistent. This tool signs the archive/tree digest separately; verification
requires a pinned public key, so executing an extracted tree has an independent
trust anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from sparknet_loader import load_shared

AUTHZ = load_shared("sparknet-authz.py", "sparknet_artifact_authz")
SCHEMA = "sparknet-artifact-signature/1"


def _artifact_name(path: Path) -> str:
    """A stable identity for a directory tree; the temp path must never leak."""
    return "SHA256SUMS" if path.is_dir() else path.name


def _digest(path: Path) -> str:
    if path.is_dir():
        sums = path / "SHA256SUMS"
        if not sums.is_file():
            raise SystemExit(f"artifact directory has no SHA256SUMS: {path}")
        path = sums
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _message(digest: str, name: str) -> bytes:
    return f"sparknet-artifact/1\n{name}\n{digest}\n".encode()


def sign(path: Path, key_path: Path, out: Path) -> int:
    key = AUTHZ.load_private_key(key_path)
    digest = _digest(path)
    name = _artifact_name(path)
    signature = AUTHZ.sign_bytes(key, _message(digest, name))
    document = {
        "schema": SCHEMA,
        "file": name,
        "sha256": digest,
        "public_key_b64": AUTHZ.public_key_b64(key.public_key()),
        "signature_b64": signature,
    }
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out.chmod(0o644)
    return 0


def verify(path: Path, signature_path: Path, pubkey_path: Path) -> int:
    document = json.loads(signature_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise SystemExit("artifact signature has an unknown schema")
    name = _artifact_name(path)
    if document.get("file") != name:
        raise SystemExit("artifact signature names a different file")
    digest = _digest(path)
    if document.get("sha256") != digest:
        raise SystemExit("artifact digest does not match the signature")
    public = AUTHZ.load_public_key(pubkey_path)
    if not AUTHZ.verify_signature(public, str(document.get("signature_b64") or ""), _message(digest, name)):
        raise SystemExit("artifact signature does not verify under the pinned public key")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sparknet-sign-artifact")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sign")
    s.add_argument("--file", type=Path, required=True)
    s.add_argument("--key", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--file", type=Path, required=True)
    v.add_argument("--signature", type=Path, required=True)
    v.add_argument("--pubkey", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.command == "sign":
            return sign(args.file, args.key, args.out)
        return verify(args.file, args.signature, args.pubkey)
    except (OSError, ValueError, AUTHZ.AuthzError) as exc:
        print(f"sparknet-sign-artifact: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

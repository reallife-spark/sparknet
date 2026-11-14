#!/usr/bin/env python3
"""Canonical resource-directory document and verifier.

The directory is metadata only: node/model/memory endpoints and health. It is
signed by the Master's operational key through the isolated signer; it never
carries a vault page, prompt, memory record, secret or capability grant.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIELDS = ("directory_id", "issued_at", "expires_at", "nodes")


def canonical(document: dict[str, Any]) -> bytes:
    missing = [field for field in FIELDS if field not in document]
    if missing:
        raise ValueError(f"resource directory missing {', '.join(missing)}")
    return json.dumps({field: document[field] for field in FIELDS}, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def verify(document: dict[str, Any], master_pubkey_b64: str, authz: Any) -> bool:
    signature = str(document.get("signature_b64") or "")
    if not signature:
        return False
    key = authz.public_key_from_b64(master_pubkey_b64)
    return bool(authz.verify_signature(key, signature, canonical(document)))


def load_and_verify(path: Path, master_pubkey_b64: str, authz: Any) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not verify(document, master_pubkey_b64, authz):
        raise ValueError("resource directory signature does not verify")
    return document

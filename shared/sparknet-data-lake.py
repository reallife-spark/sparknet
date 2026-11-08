#!/usr/bin/env python3
"""Consented Master data-lake metadata records.

The lake holds training/backup evidence, never an answer corpus. This module
validates and signs metadata only; it never stores artifact payloads or grants
a peer access to the lake.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

DATA_LAKE_SCHEMA = "sparknet-data-lake/1"
KINDS = ("inventory", "qdrant-snapshot", "teacher-trace", "raw-kv-manifest")
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class DataLakeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise DataLakeError(code, message)


def validate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(record, Mapping), "malformed-record", "record must be an object")
    _require(record.get("schema_version") == DATA_LAKE_SCHEMA, "malformed-record", "unknown data-lake schema")
    for field in ("record_id", "node_id", "user_id", "created_at"):
        _require(
            isinstance(record.get(field), str) and bool(record[field].strip()),
            "malformed-record",
            f"{field} is required",
        )
    _require(record.get("consent") is True, "consent-missing", "lake records require consent=true")
    _require(record.get("kind") in KINDS, "unknown-kind", "kind is not in the closed vocabulary")
    _require(record.get("classification") in CLASSIFICATIONS, "unknown-classification", "classification is unknown")
    department = record.get("department")
    _require(
        department is None or isinstance(department, str), "malformed-record", "department must be a string or null"
    )
    digest = record.get("digest")
    _require(
        isinstance(digest, str) and bool(DIGEST_RE.fullmatch(digest)), "bad-digest", "digest must be 64 lowercase hex"
    )
    size = record.get("size")
    _require(
        isinstance(size, int) and not isinstance(size, bool) and size >= 0, "bad-size", "size must be non-negative"
    )
    retention = record.get("retention_days")
    _require(
        isinstance(retention, int) and not isinstance(retention, bool) and 1 <= retention <= 3650,
        "retention-too-long",
        "retention_days must be 1..3650",
    )
    signature = record.get("signature_b64")
    _require(signature is None or isinstance(signature, str), "bad-signature", "signature_b64 must be a string or null")
    return {
        "schema_version": DATA_LAKE_SCHEMA,
        "record_id": record["record_id"].strip(),
        "node_id": record["node_id"].strip(),
        "user_id": record["user_id"].strip(),
        "consent": True,
        "kind": record["kind"],
        "classification": record["classification"],
        "department": department.strip() if isinstance(department, str) and department.strip() else None,
        "digest": digest,
        "size": size,
        "retention_days": retention,
        "created_at": record["created_at"],
        "signature_b64": signature,
    }


def record_message(record: Mapping[str, Any]) -> bytes:
    normalised = validate_record(record)
    projected = {key: value for key, value in normalised.items() if key != "signature_b64"}
    return json.dumps(projected, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode(
        "utf-8"
    )


def _authz() -> Any:
    return load_shared("sparknet-authz.py", "sparknet_authz_data_lake")


def sign_record(record: Mapping[str, Any], private_key: Any) -> dict[str, Any]:
    normalised = validate_record(record)
    normalised["signature_b64"] = _authz().sign_bytes(private_key, record_message(normalised))
    return normalised


def verify_record(record: Mapping[str, Any], public_key: Any) -> bool:
    try:
        normalised = validate_record(record)
        signature = normalised.get("signature_b64")
        return bool(
            isinstance(signature, str)
            and signature
            and _authz().verify_signature(public_key, signature, record_message(normalised))
        )
    except (DataLakeError, ValueError, TypeError):
        return False

#!/usr/bin/env python3
"""The one signed peer→Master eval-audit report.

A report carries bounded ``sparknet-skill-eval/1`` records as audit evidence.
It is never authority and never knowledge: it cannot grant, approve, widen a
scope, write a vault page or become an answer. The Master stores it append-only;
``/api/evals`` is a read-only projection.

The envelope is signed by the peer node key over the raw request body; the
transport in ``shared/sparknet-http.py`` does the signing and verification. This
module owns only the canonical report shape, digest and freshness/replay rules.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA = "sparknet-eval-report/1"
MAX_RECORDS = 100
MAX_BODY_BYTES = 262144
MAX_SKEW_SECONDS = 300

FIELDS = frozenset(
    {
        "schema",
        "report_id",
        "node_id",
        "peer_fingerprint",
        "records",
        "records_sha256",
        "generated_at",
        "issued_at",
        "expires_at",
        "nonce",
    }
)


def _utcnow(now: datetime | None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _stamp(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def canonical_records(records: list[dict[str, Any]]) -> bytes:
    return json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def records_digest(records: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_records(records)).hexdigest()


def report_id(node_id: str, records_digest_hex: str) -> str:
    return hashlib.sha256(f"{node_id}\x00{records_digest_hex}".encode()).hexdigest()


def build_report(
    *,
    node_id: str,
    peer_fingerprint: str,
    records: list[dict[str, Any]],
    now: datetime | None = None,
    ttl_seconds: int = 300,
    nonce: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build one report body; signing is the transport's job."""
    if not str(node_id or "").strip():
        raise ValueError("node_id is required")
    if not str(peer_fingerprint or "").strip():
        raise ValueError("peer_fingerprint is required")
    if not isinstance(records, list) or not records or len(records) > MAX_RECORDS:
        raise ValueError(f"records must be a non-empty list of at most {MAX_RECORDS} items")
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("every record must be an object")
    digest = records_digest(records)
    if len(canonical_records(records)) > MAX_BODY_BYTES:
        raise ValueError(f"records exceed {MAX_BODY_BYTES} bytes")
    moment = _utcnow(now)
    return {
        "schema": SCHEMA,
        "report_id": report_id(str(node_id), digest),
        "node_id": str(node_id),
        "peer_fingerprint": str(peer_fingerprint),
        "records": records,
        "records_sha256": digest,
        "generated_at": generated_at or _stamp(moment),
        "issued_at": _stamp(moment),
        "expires_at": _stamp(moment + timedelta(seconds=ttl_seconds)),
        "nonce": nonce or secrets.token_hex(16),
    }


def validate_report(
    report: Any,
    *,
    expected_fingerprint: str,
    now: datetime | None = None,
    seen_nonces: Any = (),
    max_skew_seconds: int = MAX_SKEW_SECONDS,
) -> tuple[bool, str]:
    """Validate the envelope and bindings; return ``(ok, reason)``."""
    if not isinstance(report, dict) or set(report) != FIELDS:
        return False, "malformed"
    for field in (
        "schema",
        "report_id",
        "node_id",
        "peer_fingerprint",
        "records_sha256",
        "generated_at",
        "issued_at",
        "expires_at",
        "nonce",
    ):
        if not isinstance(report.get(field), str) or not report[field]:
            return False, "malformed"
    if report["schema"] != SCHEMA:
        return False, "malformed"
    if not isinstance(report.get("records"), list) or not report["records"] or len(report["records"]) > MAX_RECORDS:
        return False, "malformed"
    if any(not isinstance(record, dict) for record in report["records"]):
        return False, "malformed"
    try:
        raw = canonical_records(report["records"])
    except (TypeError, ValueError):
        return False, "malformed"
    if len(raw) > MAX_BODY_BYTES:
        return False, "malformed"
    digest = hashlib.sha256(raw).hexdigest()
    if digest != report["records_sha256"]:
        return False, "digest_mismatch"
    if report_id(report["node_id"], digest) != report["report_id"]:
        return False, "digest_mismatch"
    if report["peer_fingerprint"] != expected_fingerprint:
        return False, "wrong_peer"
    moment = _utcnow(now)
    try:
        generated = datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00"))
        issued = datetime.fromisoformat(report["issued_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(report["expires_at"].replace("Z", "+00:00"))
    except ValueError:
        return False, "stale"
    for value in (generated, issued, expires):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
    if expires <= moment or (issued - moment).total_seconds() > max_skew_seconds:
        return False, "stale"
    if report["nonce"] in set(seen_nonces or ()):
        return False, "replayed"
    return True, ""

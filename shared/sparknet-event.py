#!/usr/bin/env python3
"""Canonical event envelope for the sparknet control bus.

An event is data. It can describe work, telemetry or a collaboration message;
it cannot grant, revoke or widen a capability. A signature is provenance, not
authority. The module validates and canonicalises the envelope; it never signs,
publishes or executes anything.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

EVENT_SCHEMA = "sparknet-event/1"
TOPIC_PREFIXES = (
    "sparknet.task",
    "sparknet.result",
    "sparknet.health",
    "sparknet.event",
    "sparknet.collab",
)
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
EVENT_ID_RE = re.compile(r"^evt_[A-Za-z0-9_-]{8,64}$")
EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z0-9-]+){1,2}$")
TOPIC_RE = re.compile(r"^sparknet\.[a-z0-9-]+\.[a-z0-9-]+$")
MAX_EVENT_TTL = 86400
SIGNED_FIELDS = (
    "schema_version",
    "event_id",
    "event_type",
    "topic",
    "sender_node_id",
    "created_at",
    "expires_at",
    "classification",
    "department",
    "vault_id",
    "scope",
    "payload",
)


class EventError(Exception):
    """A fail-closed event refusal."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise EventError(code, message)


def _nonempty(value: Any, field: str, code: str = "malformed-event") -> str:
    _require(isinstance(value, str) and bool(value.strip()), code, f"{field} must be a non-empty string")
    return value.strip()


def _timestamp(value: Any, field: str) -> datetime:
    _require(isinstance(value, str) and bool(value.strip()), "malformed-event", f"{field} must be an ISO-8601 string")
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventError("malformed-event", f"{field} is not a valid timestamp") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def new_event_id() -> str:
    return "evt_" + uuid.uuid4().hex


def make_event(
    *,
    event_type: str,
    topic: str,
    sender_node_id: str,
    payload: Mapping[str, Any],
    classification: str = "internal",
    department: str | None = None,
    vault_id: str = "",
    scope: Sequence[str] = (),
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    ttl_seconds: int = 900,
    event_id: str | None = None,
    signature_b64: str | None = None,
    allow_expired: bool = False,
) -> dict[str, Any]:
    """Build and validate one envelope. Never publishes or signs."""
    _require(isinstance(payload, Mapping), "bad-payload", "payload must be a JSON object")
    _require(isinstance(scope, (list, tuple)), "bad-scope", "scope must be a list")
    try:
        json.dumps(dict(payload), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise EventError("bad-payload", "payload is not strict JSON") from exc
    now = created_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if expires_at is None:
        _require(
            isinstance(ttl_seconds, int) and not isinstance(ttl_seconds, bool) and 1 <= ttl_seconds <= MAX_EVENT_TTL,
            "malformed-event",
            "ttl_seconds out of range",
        )
        expires_at = now + timedelta(seconds=ttl_seconds)
    event = {
        "schema_version": EVENT_SCHEMA,
        "event_id": event_id or new_event_id(),
        "event_type": event_type,
        "topic": topic,
        "sender_node_id": sender_node_id,
        "created_at": _iso(now),
        "expires_at": _iso(expires_at),
        "classification": classification,
        "department": department,
        "vault_id": vault_id,
        "scope": sorted({_nonempty(item, "scope item", "bad-scope") for item in scope}),
        "payload": dict(payload),
        "signature_b64": signature_b64,
    }
    return validate_event(event, allow_expired=allow_expired)


def validate_event(
    event: Mapping[str, Any], *, now: datetime | None = None, allow_expired: bool = False
) -> dict[str, Any]:
    """Validate one envelope and return a normalised copy, fail-closed."""
    _require(isinstance(event, Mapping), "malformed-event", "event must be an object")
    _require(event.get("schema_version") == EVENT_SCHEMA, "unknown-schema", "unknown event schema")
    event_id = _nonempty(event.get("event_id"), "event_id", "bad-event-id")
    _require(bool(EVENT_ID_RE.fullmatch(event_id)), "bad-event-id", "event_id has the wrong shape")
    event_type = _nonempty(event.get("event_type"), "event_type", "bad-event-type")
    _require(bool(EVENT_TYPE_RE.fullmatch(event_type)), "bad-event-type", "event_type has the wrong shape")
    topic = _nonempty(event.get("topic"), "topic", "bad-topic")
    _require(bool(TOPIC_RE.fullmatch(topic)), "bad-topic", "topic has the wrong shape")
    _require(
        any(topic == prefix or topic.startswith(prefix + ".") for prefix in TOPIC_PREFIXES),
        "unknown-topic-prefix",
        "topic is outside the sparknet namespace",
    )
    sender = _nonempty(event.get("sender_node_id"), "sender_node_id")
    created = _timestamp(event.get("created_at"), "created_at")
    expires = _timestamp(event.get("expires_at"), "expires_at")
    _require(expires >= created, "malformed-event", "expires_at precedes created_at")
    _require(
        (expires - created).total_seconds() <= MAX_EVENT_TTL,
        "malformed-event",
        "event lifetime exceeds the maximum",
    )
    if not allow_expired:
        _require(
            expires > (now or datetime.now(timezone.utc)).astimezone(timezone.utc), "expired-event", "event has expired"
        )
    classification = _nonempty(event.get("classification"), "classification", "unknown-classification")
    _require(
        classification in CLASSIFICATIONS, "unknown-classification", "classification is not in the closed vocabulary"
    )
    department = event.get("department")
    _require(
        department is None or isinstance(department, str), "malformed-event", "department must be a string or null"
    )
    vault_id = event.get("vault_id", "")
    _require(isinstance(vault_id, str), "malformed-event", "vault_id must be a string")
    scope = event.get("scope")
    _require(
        isinstance(scope, (list, tuple)) and all(isinstance(item, str) and item.strip() for item in scope),
        "bad-scope",
        "scope must be a list of non-empty strings",
    )
    payload = event.get("payload")
    _require(isinstance(payload, Mapping), "bad-payload", "payload must be a JSON object")
    try:
        json.dumps(dict(payload), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise EventError("bad-payload", "payload is not strict JSON") from exc
    signature = event.get("signature_b64")
    _require(signature is None or isinstance(signature, str), "bad-signature", "signature_b64 must be a string or null")
    return {
        "schema_version": EVENT_SCHEMA,
        "event_id": event_id,
        "event_type": event_type,
        "topic": topic,
        "sender_node_id": sender,
        "created_at": _iso(created),
        "expires_at": _iso(expires),
        "classification": classification,
        "department": department.strip() if isinstance(department, str) and department.strip() else None,
        "vault_id": vault_id.strip(),
        "scope": sorted({item.strip() for item in scope}),
        "payload": dict(payload),
        "signature_b64": signature,
    }


def event_message(event: Mapping[str, Any]) -> bytes:
    """Canonical bytes an event signature covers, excluding the signature."""
    normalised = validate_event(event, allow_expired=True)
    projected = {field: normalised.get(field) for field in SIGNED_FIELDS}
    return canonical_json(projected).encode("utf-8")


def matches_subscription(event: Mapping[str, Any], subscription: str) -> bool:
    """Match a topic against `topic`, single-segment `*`, or tail `>`."""
    _require(isinstance(subscription, str) and bool(subscription.strip()), "bad-topic", "subscription is empty")
    topic_parts = _nonempty(event.get("topic"), "topic", "bad-topic").split(".")
    pattern_parts = subscription.strip().split(".")
    for index, part in enumerate(pattern_parts):
        if part == ">":
            return index == len(pattern_parts) - 1 and len(topic_parts) > index
        if index >= len(topic_parts):
            return False
        if part != "*" and part != topic_parts[index]:
            return False
    return len(topic_parts) == len(pattern_parts)

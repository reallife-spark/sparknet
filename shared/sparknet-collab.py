#!/usr/bin/env python3
"""Bounded, ABAC-filtered collaboration rooms.

A room is a named set of participants with a classification ceiling and a
department boundary. Messages are data; they never become authority and never
enter a shared corpus by arriving. This module validates the room and message
shapes and decides membership; it does not open a socket or sign anything.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

ROOM_SCHEMA = "sparknet-collab-room/1"
MESSAGE_SCHEMA = "sparknet-collab-message/1"
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
_RANK = {name: index for index, name in enumerate(CLASSIFICATIONS)}
STATUSES = ("open", "closed")


class CollabError(Exception):
    """A fail-closed collaboration refusal."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise CollabError(code, message)


def _nonempty(value: Any, field: str, code: str = "malformed-room") -> str:
    _require(isinstance(value, str) and bool(value.strip()), code, f"{field} must be a non-empty string")
    return value.strip()


def _classification(value: Any) -> str:
    _require(
        isinstance(value, str) and value in CLASSIFICATIONS,
        "unknown-classification",
        "classification is not in the closed vocabulary",
    )
    return value


def _timestamp(value: Any, field: str) -> datetime:
    _require(isinstance(value, str) and bool(value.strip()), "malformed-room", f"{field} must be an ISO-8601 string")
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise CollabError("malformed-room", f"{field} is not a valid timestamp") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _participant(value: Any) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "malformed-participant", "participant must be an object")
    department = value.get("department")
    _require(
        department is None or isinstance(department, str),
        "malformed-participant",
        "participant department must be a string or null",
    )
    return {
        "node_id": _nonempty(value.get("node_id"), "participant.node_id", "malformed-participant"),
        "user_id": _nonempty(value.get("user_id"), "participant.user_id", "malformed-participant"),
        "department": department.strip() if isinstance(department, str) and department.strip() else None,
        "role": str(value.get("role") or "participant"),
    }


def make_room(
    *,
    owner_node_id: str,
    participants: Sequence[Mapping[str, Any]],
    classification: str,
    capabilities: Sequence[str] = (),
    verified: bool = False,
    department: str | None = None,
    room_id: str | None = None,
    ttl_seconds: int = 3600,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    if verified is not True:
        raise CollabError("subject-unverified", "room creation needs verified participant facts")
    now = created_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if expires_at is None:
        _require(
            isinstance(ttl_seconds, int) and not isinstance(ttl_seconds, bool) and 1 <= ttl_seconds <= 86400,
            "malformed-room",
            "ttl_seconds out of range",
        )
        expires_at = now + timedelta(seconds=ttl_seconds)
    _require(department is None or isinstance(department, str), "malformed-room", "department must be a string or null")
    normalised_participants = [_participant(item) for item in participants]
    room_department = department.strip() if isinstance(department, str) and department.strip() else None
    departments = {item["department"] for item in normalised_participants if item["department"]}
    crossing = len(departments) > 1 or bool(
        room_department and any(item["department"] not in (None, room_department) for item in normalised_participants)
    )
    if crossing and "cross-department-share" not in set(capabilities):
        raise CollabError("department-mismatch", "crossing a department needs cross-department-share")
    room = {
        "schema_version": ROOM_SCHEMA,
        "room_id": room_id or "room-" + uuid.uuid4().hex,
        "owner_node_id": _nonempty(owner_node_id, "owner_node_id"),
        "participants": normalised_participants,
        "classification": _classification(classification),
        "department": room_department,
        "created_at": _iso(now),
        "expires_at": _iso(expires_at),
        "status": "open",
        "cross_department_approved": crossing,
    }
    return validate_room(room)


def validate_room(room: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    _require(isinstance(room, Mapping), "malformed-room", "room must be an object")
    _require(room.get("schema_version") == ROOM_SCHEMA, "malformed-room", "unknown room schema")
    participants = room.get("participants")
    _require(
        isinstance(participants, (list, tuple)) and bool(participants), "malformed-room", "room has no participants"
    )
    normalised = [_participant(item) for item in participants]
    node_ids = [item["node_id"] for item in normalised]
    _require(len(node_ids) == len(set(node_ids)), "duplicate-participant", "participant node ids must be unique")
    owner = _nonempty(room.get("owner_node_id"), "owner_node_id")
    _require(owner in node_ids, "owner-not-participant", "owner must be a participant")
    status = room.get("status")
    _require(status in STATUSES, "malformed-room", "room status must be open or closed")
    approved = room.get("cross_department_approved")
    _require(isinstance(approved, bool), "malformed-room", "cross_department_approved must be a boolean")
    created = _timestamp(room.get("created_at"), "created_at")
    expires = _timestamp(room.get("expires_at"), "expires_at")
    _require(expires > created, "malformed-room", "expires_at must be after created_at")
    raw_department = room.get("department")
    _require(
        raw_department is None or isinstance(raw_department, str),
        "malformed-room",
        "department must be a string or null",
    )
    department = raw_department.strip() if isinstance(raw_department, str) and raw_department.strip() else None
    departments = {item["department"] for item in normalised if item["department"]}
    if (
        len(departments) > 1
        or (department and any(item["department"] not in (None, department) for item in normalised))
    ) and not approved:
        raise CollabError("department-mismatch", "cross-department room was not approved")
    return {
        "schema_version": ROOM_SCHEMA,
        "room_id": _nonempty(room.get("room_id"), "room_id"),
        "owner_node_id": owner,
        "participants": normalised,
        "classification": _classification(room.get("classification")),
        "department": department,
        "created_at": _iso(created),
        "expires_at": _iso(expires),
        "status": status,
        "cross_department_approved": approved,
    }


def add_participant(
    room: Mapping[str, Any],
    participant: Mapping[str, Any],
    *,
    capabilities: Sequence[str] = (),
    verified: bool = False,
) -> dict[str, Any]:
    if verified is not True:
        raise CollabError("subject-unverified", "participant facts must be verified")
    normalised = validate_room(room)
    _require(normalised["status"] == "open", "room-closed", "room is closed")
    _require(
        _timestamp(normalised["expires_at"], "expires_at") > datetime.now(timezone.utc),
        "room-expired",
        "room has expired",
    )
    incoming = _participant(participant)
    if any(item["node_id"] == incoming["node_id"] for item in normalised["participants"]):
        raise CollabError("duplicate-participant", "participant is already in the room")
    crossing = bool(
        (
            normalised.get("department")
            and incoming.get("department")
            and normalised["department"] != incoming["department"]
        )
        or (len({item["department"] for item in [*normalised["participants"], incoming] if item["department"]}) > 1)
    )
    if crossing and not normalised["cross_department_approved"]:
        _require(
            "cross-department-share" in set(capabilities),
            "department-mismatch",
            "crossing a department needs cross-department-share",
        )
    return validate_room(
        {
            **normalised,
            "participants": [*normalised["participants"], incoming],
            "cross_department_approved": bool(normalised["cross_department_approved"] or crossing),
        }
    )


def make_message(
    room: Mapping[str, Any],
    *,
    sender_node_id: str,
    sender_user_id: str,
    text: str,
    provenance: Mapping[str, Any],
    classification: str | None = None,
    message_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    normalised = validate_room(room)
    _require(normalised["status"] == "open", "room-closed", "room is closed")
    _require(
        _timestamp(normalised["expires_at"], "expires_at") > datetime.now(timezone.utc),
        "room-expired",
        "room has expired",
    )
    sender_node = _nonempty(sender_node_id, "sender_node_id", "bad-message")
    sender_user = _nonempty(sender_user_id, "sender_user_id", "bad-message")
    _require(
        any(item["node_id"] == sender_node and item["user_id"] == sender_user for item in normalised["participants"]),
        "sender-not-participant",
        "sender is not a participant",
    )
    chosen = classification or normalised["classification"]
    _classification(chosen)
    _require(
        _RANK[chosen] <= _RANK[normalised["classification"]],
        "classification-downgrade",
        "a message cannot exceed the room classification",
    )
    _require(
        isinstance(provenance, Mapping) and isinstance(provenance.get("source"), str) and provenance["source"].strip(),
        "missing-provenance",
        "message requires provenance.source",
    )
    now = created_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    message = {
        "schema_version": MESSAGE_SCHEMA,
        "message_id": message_id or "msg-" + uuid.uuid4().hex,
        "room_id": normalised["room_id"],
        "sender_node_id": sender_node,
        "sender_user_id": sender_user,
        "created_at": _iso(now),
        "text": _nonempty(text, "text", "bad-message"),
        "classification": chosen,
        "department": normalised.get("department"),
        "provenance": {"source": provenance["source"].strip(), "digest": provenance.get("digest")},
    }
    return validate_message(message, normalised)


def validate_message(message: Mapping[str, Any], room: Mapping[str, Any] | None = None) -> dict[str, Any]:
    _require(isinstance(message, Mapping), "bad-message", "message must be an object")
    _require(message.get("schema_version") == MESSAGE_SCHEMA, "bad-message", "unknown message schema")
    provenance = message.get("provenance")
    _require(
        isinstance(provenance, Mapping) and isinstance(provenance.get("source"), str) and provenance["source"].strip(),
        "missing-provenance",
        "message requires provenance.source",
    )
    normalised = {
        "schema_version": MESSAGE_SCHEMA,
        "message_id": _nonempty(message.get("message_id"), "message_id", "bad-message"),
        "room_id": _nonempty(message.get("room_id"), "room_id", "bad-message"),
        "sender_node_id": _nonempty(message.get("sender_node_id"), "sender_node_id", "bad-message"),
        "sender_user_id": _nonempty(message.get("sender_user_id"), "sender_user_id", "bad-message"),
        "created_at": _iso(_timestamp(message.get("created_at"), "created_at")),
        "text": _nonempty(message.get("text"), "text", "bad-message"),
        "classification": _classification(message.get("classification")),
        "department": message.get("department")
        if isinstance(message.get("department"), str) and message.get("department").strip()
        else None,
        "provenance": {"source": provenance["source"].strip(), "digest": provenance.get("digest")},
    }
    if room is not None:
        verified_room = validate_room(room)
        _require(verified_room["status"] == "open", "room-closed", "room is closed")
        _require(
            _timestamp(verified_room["expires_at"], "expires_at") > datetime.now(timezone.utc),
            "room-expired",
            "room has expired",
        )
        _require(normalised["room_id"] == verified_room["room_id"], "bad-message", "message room does not match")
        _require(
            any(
                item["node_id"] == normalised["sender_node_id"] and item["user_id"] == normalised["sender_user_id"]
                for item in verified_room["participants"]
            ),
            "sender-not-participant",
            "sender is not a participant",
        )
        _require(
            _RANK[normalised["classification"]] <= _RANK[verified_room["classification"]],
            "classification-downgrade",
            "a message cannot exceed the room classification",
        )
    return normalised


def visible_to(room: Mapping[str, Any], node_id: str) -> bool:
    normalised = validate_room(room)
    return any(item["node_id"] == node_id for item in normalised["participants"])


def to_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)

"""Collaboration is bounded by membership, classification and department."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone

import pytest
from contract_helpers import REPO_ROOT, load

COLLAB_PATH = REPO_ROOT / "shared" / "sparknet-collab.py"


def _load_collab():
    spec = importlib.util.spec_from_file_location("sparknet_collab", COLLAB_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


collab = _load_collab()

OWNER = {"node_id": "node-1", "user_id": "user-1", "department": "blue", "role": "owner"}
GUEST = {"node_id": "node-2", "user_id": "user-2", "department": "blue", "role": "participant"}
RED = {"node_id": "node-3", "user_id": "user-3", "department": "red", "role": "participant"}


def room(**overrides):
    body = {
        "owner_node_id": "node-1",
        "participants": [OWNER, GUEST],
        "classification": "internal",
        "department": "blue",
        "room_id": "room-1",
        "verified": True,
    }
    body.update(overrides)
    return collab.make_room(**body)


def test_contract_vocabularies_match_the_module():
    schema = load("collab-schema.json")
    assert schema["room"]["schema"] == collab.ROOM_SCHEMA
    assert schema["message"]["schema"] == collab.MESSAGE_SCHEMA
    assert set(schema["refusal_codes"]) >= {"sender-not-participant", "department-mismatch", "room-expired"}


def test_room_requires_owner_membership_and_unique_nodes():
    with pytest.raises(collab.CollabError) as refused:
        room(owner_node_id="node-9")
    assert refused.value.code == "owner-not-participant"
    with pytest.raises(collab.CollabError) as duplicate:
        room(participants=[OWNER, OWNER])
    assert duplicate.value.code == "duplicate-participant"


def test_cross_department_participant_needs_the_capability():
    with pytest.raises(collab.CollabError) as refused:
        collab.add_participant(room(), RED, verified=True)
    assert refused.value.code == "department-mismatch"
    widened = collab.add_participant(room(), RED, capabilities=["cross-department-share"], verified=True)
    assert any(item["node_id"] == "node-3" for item in widened["participants"])
    assert widened["cross_department_approved"] is True


def test_room_creation_requires_verified_facts_and_checks_departments():
    with pytest.raises(collab.CollabError) as refused:
        collab.make_room(
            owner_node_id="node-1",
            participants=[OWNER, GUEST],
            classification="internal",
            department="blue",
        )
    assert refused.value.code == "subject-unverified"
    with pytest.raises(collab.CollabError) as mixed:
        collab.make_room(
            owner_node_id="node-1",
            participants=[OWNER, RED],
            classification="internal",
            department="blue",
            verified=True,
        )
    assert mixed.value.code == "department-mismatch"
    approved = collab.make_room(
        owner_node_id="node-1",
        participants=[OWNER, RED],
        classification="internal",
        department="blue",
        capabilities=["cross-department-share"],
        verified=True,
    )
    assert approved["cross_department_approved"] is True


def test_only_participants_send_and_classification_is_a_ceiling():
    active = room()
    message = collab.make_message(
        active,
        sender_node_id="node-2",
        sender_user_id="user-2",
        text="hello",
        provenance={"source": "share-1"},
    )
    assert message["room_id"] == "room-1"
    with pytest.raises(collab.CollabError) as refused:
        collab.make_message(
            active,
            sender_node_id="node-3",
            sender_user_id="user-3",
            text="intruder",
            provenance={"source": "share-1"},
        )
    assert refused.value.code == "sender-not-participant"
    with pytest.raises(collab.CollabError) as raised:
        collab.make_message(
            active,
            sender_node_id="node-2",
            sender_user_id="user-2",
            text="too high",
            provenance={"source": "share-1"},
            classification="confidential",
        )
    assert raised.value.code == "classification-downgrade"


def test_closed_and_expired_rooms_accept_nothing():
    closed = room()
    closed["status"] = "closed"
    with pytest.raises(collab.CollabError) as refused:
        collab.make_message(
            closed,
            sender_node_id="node-2",
            sender_user_id="user-2",
            text="hello",
            provenance={"source": "share-1"},
        )
    assert refused.value.code == "room-closed"

    expired = room()
    expired["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    expired["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(collab.CollabError) as refused:
        collab.make_message(
            expired,
            sender_node_id="node-2",
            sender_user_id="user-2",
            text="hello",
            provenance={"source": "share-1"},
        )
    assert refused.value.code == "room-expired"


def test_message_requires_provenance():
    with pytest.raises(collab.CollabError) as refused:
        collab.make_message(
            room(),
            sender_node_id="node-2",
            sender_user_id="user-2",
            text="hello",
            provenance={},
        )
    assert refused.value.code == "missing-provenance"


def test_room_aware_message_validation_rechecks_membership_and_ceiling():
    active = room()
    message = collab.make_message(
        active,
        sender_node_id="node-2",
        sender_user_id="user-2",
        text="hello",
        provenance={"source": "share-1"},
    )
    assert collab.validate_message(message, active)["text"] == "hello"
    foreign = dict(message)
    foreign["sender_node_id"] = "node-3"
    foreign["sender_user_id"] = "user-3"
    with pytest.raises(collab.CollabError) as refused:
        collab.validate_message(foreign, active)
    assert refused.value.code == "sender-not-participant"
    high = dict(message)
    high["classification"] = "confidential"
    with pytest.raises(collab.CollabError) as raised:
        collab.validate_message(high, active)
    assert raised.value.code == "classification-downgrade"


def test_visibility_is_membership_only():
    assert collab.visible_to(room(), "node-2") is True
    assert collab.visible_to(room(), "node-3") is False

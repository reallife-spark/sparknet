"""The event envelope is data: no authority, bounded lifetime, closed topics."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone

import pytest
from contract_helpers import REPO_ROOT, load

EVENT_PATH = REPO_ROOT / "shared" / "sparknet-event.py"


def _load_event():
    spec = importlib.util.spec_from_file_location("sparknet_event", EVENT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


event = _load_event()


def sample(**overrides):
    body = {
        "event_type": "task.enqueued",
        "topic": "sparknet.task.blue",
        "sender_node_id": "sparknet-node-0002",
        "payload": {"task_id": "task-1", "operation": "digest"},
        "classification": "internal",
        "scope": ["01_Inbox/"],
    }
    body.update(overrides)
    return event.make_event(**body)


def test_contract_vocabularies_match_the_module():
    schema = load("event-schema.json")
    assert schema["envelope"]["schema"] == event.EVENT_SCHEMA
    assert set(schema["envelope"]["topic_prefixes"]) == set(event.TOPIC_PREFIXES)
    assert tuple(schema["envelope"]["fields"]) == (*event.SIGNED_FIELDS, "signature_b64")
    assert set(schema["refusal_codes"]) >= {"bad-topic", "unknown-topic-prefix", "expired-event"}


def test_make_event_is_normalised_and_canonical():
    first = sample(scope=["06_Projects/", "01_Inbox/", "01_Inbox/"])
    second = sample(scope=["01_Inbox/", "06_Projects/"], event_id=first["event_id"])
    assert first["scope"] == ["01_Inbox/", "06_Projects/"]
    assert event.event_message(first) == event.event_message(second)


def test_bad_topic_and_namespace_are_refused():
    with pytest.raises(event.EventError) as bad:
        sample(topic="sparknet.task")
    assert bad.value.code == "bad-topic"
    with pytest.raises(event.EventError) as outside:
        sample(topic="sparknet.other.blue")
    assert outside.value.code == "unknown-topic-prefix"


def test_payload_must_be_an_object():
    with pytest.raises(event.EventError) as refused:
        sample(payload="not-an-object")
    assert refused.value.code == "bad-payload"


def test_unknown_classification_is_refused():
    with pytest.raises(event.EventError) as refused:
        sample(classification="secret")
    assert refused.value.code == "unknown-classification"


def test_expired_event_is_refused_but_can_be_canonicalised_for_audit():
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    built = event.make_event(
        event_type="health.report",
        topic="sparknet.health.report",
        sender_node_id="sparknet-node-0002",
        payload={"status": "ok"},
        created_at=old,
        expires_at=old + timedelta(seconds=30),
        allow_expired=True,
    )
    with pytest.raises(event.EventError) as refused:
        event.validate_event(built)
    assert refused.value.code == "expired-event"
    assert event.event_message(built)


def test_subscription_wildcards():
    built = sample()
    assert event.matches_subscription(built, "sparknet.task.*") is True
    assert event.matches_subscription(built, "sparknet.>") is True
    assert event.matches_subscription(built, "sparknet.result.>") is False
    assert event.matches_subscription(built, "sparknet.task.blue") is True
    assert event.matches_subscription(built, "sparknet.task.blue.>") is False


def test_scope_must_be_a_list_and_payload_must_be_strict_json():
    with pytest.raises(event.EventError) as refused:
        sample(scope="01_Inbox/")
    assert refused.value.code == "bad-scope"
    with pytest.raises(event.EventError) as payload:
        sample(payload={"bad": object()})
    assert payload.value.code == "bad-payload"


def test_lifetime_is_bounded():
    built = sample()
    built["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
    with pytest.raises(event.EventError) as refused:
        event.validate_event(built)
    assert refused.value.code == "malformed-event"


def test_signature_is_opaque_and_optional():
    built = sample()
    assert built["signature_b64"] is None
    signed = sample(signature_b64="not-a-signature")
    assert signed["signature_b64"] == "not-a-signature"
    with pytest.raises(event.EventError):
        sample(signature_b64=123)


def test_event_has_no_authority_fields():
    built = sample()
    assert "capabilities" not in built
    assert "grant" not in built
    assert built["sender_node_id"] == "sparknet-node-0002"

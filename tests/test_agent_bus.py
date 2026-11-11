"""Agents consume bounded events and publish data, never authority."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from contract_helpers import REPO_ROOT
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


AGENT_BUS = REPO_ROOT / "shared" / "sparknet-agent-bus.py"
EVENT = REPO_ROOT / "shared" / "sparknet-event.py"
ENGINEERING = REPO_ROOT / "peer-node" / "agents" / "engineering" / "agent.py"
CYBER = REPO_ROOT / "peer-node" / "agents" / "cyber" / "agent.py"


def _load(name, path):
    return load_by_path(name, path)


agent_bus = _load("agent_bus_test", AGENT_BUS)
event = _load("agent_bus_event_test", EVENT)
engineering = _load("agent_engineering_test", ENGINEERING)
cyber = _load("agent_cyber_test", CYBER)


def task(topic="sparknet.task.engineering", classification="internal", payload=None):
    return event.make_event(
        event_type="task.enqueued",
        topic=topic,
        sender_node_id="sparknet-node-0001",
        payload=payload or {"prompt": "write a test"},
        classification=classification,
        event_id="evt_0123456789abcdef",
        created_at=datetime.now(timezone.utc),
        ttl_seconds=600,
    )


def policy(**overrides):
    descriptor = {
        "schema_version": "sparknet-agent/1",
        "agent_id": "engineering",
        "role": "engineering",
        "enabled": True,
        "topics": ["sparknet.task.engineering"],
        "max_runtime_seconds": 300,
        "max_concurrency": 2,
        "max_classification": "internal",
        "departments": [],
    }
    descriptor.update(overrides)
    return agent_bus.AgentPolicy.from_descriptor(descriptor)


class FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, subject, value):
        self.published.append((subject, value))


def test_policy_accepts_its_topic_and_refuses_another_family():
    accepted = policy().check(task())
    assert accepted["topic"] == "sparknet.task.engineering"
    with pytest.raises(agent_bus.AgentBusError) as refused:
        policy().check(task(topic="sparknet.task.cyber"))
    assert refused.value.code == "bad-topic"


def test_policy_refuses_high_classification_and_authority_payload():
    with pytest.raises(agent_bus.AgentBusError) as classified:
        policy().check(task(classification="confidential"))
    assert classified.value.code == "classification-downgrade"
    with pytest.raises(agent_bus.AgentBusError) as authority:
        policy().check(task(payload={"prompt": "x", "capabilities": ["cluster-serve"]}))
    assert authority.value.code == "authority-field"


def test_runner_publishes_a_result_and_is_idempotent(tmp_path):
    bus = FakeBus()
    runner = agent_bus.AgentRunner(
        policy(),
        lambda payload, _event: {"summary": payload["prompt"]},
        bus,
        node_id="sparknet-node-0002",
        state_dir=tmp_path,
    )
    first = runner.handle(task())
    assert first["ok"] is True
    subject, result = bus.published[0]
    assert subject == "sparknet.result.engineering"
    assert result["payload"]["task_event_id"] == "evt_0123456789abcdef"
    assert result["payload"]["result"]["summary"] == "write a test"
    second = runner.handle(task())
    assert second["skipped"] == "already-processed"
    assert len(bus.published) == 1


def test_handler_result_cannot_smuggle_authority(tmp_path):
    runner = agent_bus.AgentRunner(
        policy(),
        lambda _payload, _event: {"grant": "all"},
        FakeBus(),
        node_id="sparknet-node-0002",
        state_dir=tmp_path,
    )
    with pytest.raises(agent_bus.AgentBusError) as refused:
        runner.handle(task())
    assert refused.value.code == "authority-field"


def test_engineering_and_cyber_handlers(monkeypatch):
    monkeypatch.setattr(engineering.AGENT, "call_model", lambda **_kwargs: "OK")
    payload = {"prompt": "write a test"}
    assert engineering.handle(payload, task())["summary"] == "OK"
    monkeypatch.setattr(cyber.AGENT, "call_model", lambda **_kwargs: "defended")
    assert cyber.handle({"prompt": "review a log", "mode": "defensive"}, task())["summary"] == "defended"
    with pytest.raises(cyber.AGENT.AgentBusError) as refused:
        cyber.handle({"prompt": "attack", "mode": "offensive"}, task())
    assert refused.value.code == "offensive-out-of-scope"

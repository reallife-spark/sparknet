"""The Master orchestrator routes tasks and cannot add authority."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone

import pytest
from contract_helpers import REPO_ROOT

EVENT = REPO_ROOT / "shared" / "sparknet-event.py"
ORCH = REPO_ROOT / "master-node" / "services" / "sparknet-orchestrator.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


event = _load("orchestrator_event_test", EVENT)
orch = _load("orchestrator_test", ORCH)


def dispatch(payload):
    return event.make_event(
        event_type="task.dispatch",
        topic="sparknet.task.orchestrate",
        sender_node_id="sparknet-node-0001",
        payload=payload,
        event_id="evt_0123456789abcdef",
        created_at=datetime.now(timezone.utc),
        ttl_seconds=600,
    )


def test_routes_to_the_named_role_topic():
    routed = orch.route(dispatch({"role": "engineering", "prompt": "build"}))
    assert routed["topic"] == "sparknet.task.engineering"
    assert routed["payload"]["role"] == "engineering"
    assert routed["payload"]["orchestrator_event_id"] == "evt_0123456789abcdef"


def test_unknown_role_and_wrong_topic_are_refused():
    with pytest.raises(orch.OrchestratorError) as role:
        orch.route(dispatch({"role": "admin"}))
    assert role.value.code == "unknown-role"
    other = event.make_event(
        event_type="task.enqueued",
        topic="sparknet.task.engineering",
        sender_node_id="sparknet-node-0001",
        payload={"role": "engineering"},
        event_id="evt_0123456789abcdef",
        created_at=datetime.now(timezone.utc),
        ttl_seconds=600,
    )
    with pytest.raises(orch.OrchestratorError) as topic:
        orch.route(other)
    assert topic.value.code == "bad-topic"


def test_authority_payload_is_refused():
    with pytest.raises(orch.OrchestratorError) as refused:
        orch.route(dispatch({"role": "engineering", "capabilities": ["cluster-serve"]}))
    assert refused.value.code == "authority-field"

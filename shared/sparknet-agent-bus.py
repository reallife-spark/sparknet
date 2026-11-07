#!/usr/bin/env python3
"""Bounded event-driven agent execution over the sparknet event bus.

An agent receives one validated event, runs a local handler and publishes a
result event. It never grants authority, writes a vault page directly, or
accepts a task whose classification, department or topic exceeds its descriptor.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

_EVENT = load_shared("sparknet-event.py", "sparknet_agent_bus_event")
BUS = load_shared("sparknet-event-bus.py", "sparknet_agent_bus_nats")
EventError = _EVENT.EventError
NatsError = BUS.NatsError

CLASSIFICATIONS = _EVENT.CLASSIFICATIONS
AUTHORITY_KEYS = frozenset(
    {
        "grant",
        "grants",
        "grant_id",
        "capability",
        "capabilities",
        "authority",
        "signature_b64",
        "signer",
        "approved_by",
        "approval",
    }
)


class AgentBusError(Exception):
    """A fail-closed agent refusal."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentPolicy:
    agent_id: str
    role: str
    topics: tuple[str, ...]
    max_classification: str
    departments: tuple[str, ...]
    max_runtime_seconds: int
    max_concurrency: int

    @classmethod
    def from_descriptor(cls, descriptor: Mapping[str, Any]) -> AgentPolicy:
        if not isinstance(descriptor, Mapping):
            raise AgentBusError("malformed-agent", "descriptor must be an object")
        if descriptor.get("schema_version") != "sparknet-agent/1":
            raise AgentBusError("malformed-agent", "unknown agent schema")
        agent_id = str(descriptor.get("agent_id") or "").strip()
        role = str(descriptor.get("role") or "").strip()
        topics = descriptor.get("topics")
        classification = str(descriptor.get("max_classification") or "internal").strip()
        departments = descriptor.get("departments") or []
        runtime = descriptor.get("max_runtime_seconds")
        concurrency = descriptor.get("max_concurrency")
        if not agent_id or not role:
            raise AgentBusError("malformed-agent", "agent_id and role are required")
        if not isinstance(topics, (list, tuple)) or not topics or not all(isinstance(item, str) for item in topics):
            raise AgentBusError("bad-topic", "topics must be a non-empty list of strings")
        if classification not in CLASSIFICATIONS:
            raise AgentBusError("malformed-agent", "max_classification is unknown")
        if not isinstance(departments, (list, tuple)) or not all(isinstance(item, str) for item in departments):
            raise AgentBusError("malformed-agent", "departments must be a list of strings")
        if not isinstance(runtime, int) or isinstance(runtime, bool) or not 1 <= runtime <= 3600:
            raise AgentBusError("malformed-agent", "max_runtime_seconds is out of range")
        if not isinstance(concurrency, int) or isinstance(concurrency, bool) or not 1 <= concurrency <= 16:
            raise AgentBusError("malformed-agent", "max_concurrency is out of range")
        return cls(
            agent_id=agent_id,
            role=role,
            topics=tuple(item.strip() for item in topics),
            max_classification=classification,
            departments=tuple(item.strip() for item in departments if item.strip()),
            max_runtime_seconds=runtime,
            max_concurrency=concurrency,
        )

    def check(self, event: Mapping[str, Any]) -> dict[str, Any]:
        try:
            normalised = _EVENT.validate_event(event)
        except EventError as exc:
            raise AgentBusError(exc.code, exc.message) from exc
        if not any(_EVENT.matches_subscription(normalised, pattern) for pattern in self.topics):
            raise AgentBusError("bad-topic", "event topic is outside this agent's family")
        if CLASSIFICATIONS.index(normalised["classification"]) > CLASSIFICATIONS.index(self.max_classification):
            raise AgentBusError("classification-downgrade", "event classification exceeds this agent's ceiling")
        if self.departments and normalised.get("department") not in (None, *self.departments):
            raise AgentBusError("department-mismatch", "event department is outside this agent's allow-list")
        _refuse_authority(normalised.get("payload") or {})
        return normalised


def _refuse_authority(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if name in AUTHORITY_KEYS:
                raise AgentBusError("authority-field", f"{path}.{name} carries an authority field")
            _refuse_authority(item, f"{path}.{name}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _refuse_authority(item, f"{path}[{index}]")


class IdempotencyStore:
    """A tiny atomic event-id set, kept under the node state directory."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> set[str]:
        if not self.path.is_file():
            return set()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentBusError("state-unreadable", str(exc)) from exc
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise AgentBusError("state-invalid", "idempotency store is malformed")
        return set(value)

    def seen(self, event_id: str) -> bool:
        with self._lock:
            return event_id in self._read()

    def mark(self, event_id: str) -> None:
        with self._lock:
            seen = self._read()
            seen.add(event_id)
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(json.dumps(sorted(seen)) + "\n", encoding="utf-8")
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)


class AgentRunner:
    def __init__(
        self,
        policy: AgentPolicy,
        handler: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
        bus: Any,
        *,
        node_id: str,
        state_dir: Path,
        result_topic: str | None = None,
    ) -> None:
        self.policy = policy
        self.handler = handler
        self.bus = bus
        self.node_id = node_id
        self.result_topic = result_topic or f"sparknet.result.{policy.role}"
        self.store = IdempotencyStore(Path(state_dir) / f"agent-{policy.agent_id}-seen.json")

    def handle(self, event: Mapping[str, Any]) -> dict[str, Any]:
        normalised = self.policy.check(event)
        if self.store.seen(normalised["event_id"]):
            return {"ok": True, "skipped": "already-processed", "event_id": normalised["event_id"]}
        result = self.handler(normalised.get("payload") or {}, normalised)
        if not isinstance(result, Mapping):
            raise AgentBusError("bad-result", "agent handler must return a mapping")
        _refuse_authority(result, "result")
        try:
            json.dumps(dict(result), sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise AgentBusError("bad-result", "agent result is not strict JSON") from exc
        result_event = _EVENT.make_event(
            event_type=f"{self.policy.role}.result",
            topic=self.result_topic,
            sender_node_id=self.node_id,
            payload={
                "task_event_id": normalised["event_id"],
                "agent_id": self.policy.agent_id,
                "result": dict(result),
            },
            classification=normalised["classification"],
            department=normalised.get("department"),
            vault_id=normalised.get("vault_id", ""),
            scope=normalised.get("scope") or [],
        )
        self.store.mark(normalised["event_id"])
        self.bus.publish(self.result_topic, result_event)
        return {"ok": True, "result_event": result_event}

    def run_once(self, subject: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
        event = self.bus.subscribe_once(subject or self.policy.topics[0], timeout=timeout)
        return self.handle(event)


def call_model(
    *,
    prompt: str,
    url: str,
    model: str,
    token: str = "",
    timeout: float = 120.0,
    max_tokens: int = 512,
) -> str:
    """Call an OpenAI-compatible local model. The model is a tool, not authority."""
    if not prompt.strip():
        raise AgentBusError("bad-task", "prompt is empty")
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "stream": False,
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise AgentBusError("model-unavailable", str(exc)) from exc
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise AgentBusError("model-unavailable", "model returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise AgentBusError("model-unavailable", "model returned no content")
    return content.strip()

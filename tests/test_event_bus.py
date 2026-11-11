"""The event bus speaks the small plain-NATS surface the fabric needs."""

from __future__ import annotations

import contextlib
import json
import socket
import threading
from datetime import datetime, timedelta, timezone

import pytest
from contract_helpers import REPO_ROOT
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration


BUS_PATH = REPO_ROOT / "shared" / "sparknet-event-bus.py"
EVENT_PATH = REPO_ROOT / "shared" / "sparknet-event.py"


def _load(name, path):
    return load_by_path(name, path)


event = _load("event_bus_event_test", EVENT_PATH)
bus = _load("event_bus_test", BUS_PATH)


class FakeNats:
    def __init__(self, message: dict):
        self.message = message
        self.published: list[bytes] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        conn, _ = self.sock.accept()
        with conn:
            stream = conn.makefile("rwb", buffering=0)
            stream.write(b'INFO {"server_id":"fake"}\r\n')
            while True:
                line = stream.readline()
                if not line:
                    break
                if line.startswith(b"CONNECT"):
                    continue
                if line.startswith(b"PING"):
                    stream.write(b"PONG\r\n")
                elif line.startswith(b"PUB "):
                    size = int(line.split()[-1])
                    self.published.append(stream.read(size))
                    stream.read(2)
                elif line.startswith(b"SUB "):
                    subject = line.split()[1].decode("ascii")
                    payload = json.dumps(self.message).encode("utf-8")
                    stream.write(f"MSG {subject} 1 {len(payload)}\r\n".encode("ascii") + payload + b"\r\n")

    def close(self):
        with contextlib.suppress(OSError):
            self.sock.close()


def sample_event():
    return event.make_event(
        event_type="task.enqueued",
        topic="sparknet.task.blue",
        sender_node_id="sparknet-node-0002",
        payload={"task_id": "task-1"},
        classification="internal",
        scope=["01_Inbox/"],
        event_id="evt_0123456789abcdef",
        created_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        ttl_seconds=600,
    )


def test_bus_address_parsing():
    assert bus.BusAddress.parse("nats://10.100.0.1:4225") == bus.BusAddress("10.100.0.1", 4225)
    assert bus.BusAddress.parse("127.0.0.1") == bus.BusAddress("127.0.0.1", 4222)
    with pytest.raises(bus.NatsError):
        bus.BusAddress.parse("http://example")


def test_publish_and_subscribe_once():
    message = sample_event()
    server = FakeNats(message)
    try:
        with bus.NatsClient("127.0.0.1", server.port, timeout=2) as client:
            client.publish("sparknet.task.blue", message)
            assert json.loads(server.published[0].decode("utf-8")) == message
            received = client.subscribe_once("sparknet.task.blue", timeout=2)
            assert received["event_id"] == message["event_id"]
            assert received["payload"] == {"task_id": "task-1"}
    finally:
        server.close()


def test_bad_subject_is_refused():
    with pytest.raises(bus.NatsError) as refused:
        bus.NatsClient()._pub_frame("bad subject", b"{}")
    assert refused.value.code == "bad-subject"


def test_subscribe_subject_is_validated_before_framing():
    with pytest.raises(bus.NatsError) as refused:
        bus.NatsClient().subscribe_once("bad\r\nSUB other")
    assert refused.value.code == "bad-subject"


class FakeJetStream:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.request = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        conn, _ = self.sock.accept()
        with conn:
            stream = conn.makefile("rwb", buffering=0)
            stream.write(b'INFO {"server_id":"fake-js"}\r\n')
            while True:
                line = stream.readline()
                if not line:
                    break
                if line.startswith(b"CONNECT"):
                    continue
                if line.startswith(b"PING"):
                    stream.write(b"PONG\r\n")
                elif line.startswith(b"PUB "):
                    parts = line.split()
                    subject = parts[1].decode("ascii")
                    reply = parts[2].decode("ascii")
                    size = int(parts[3])
                    self.request = (subject, stream.read(size))
                    stream.read(2)
                    payload = json.dumps({"config": {"name": "sparknet"}}).encode("utf-8")
                    stream.write(f"MSG {reply} 1 {len(payload)}\r\n".encode("ascii") + payload + b"\r\n")

    def close(self):
        with contextlib.suppress(OSError):
            self.sock.close()


def test_jetstream_stream_creation_is_a_server_request():
    server = FakeJetStream()
    try:
        with bus.NatsClient("127.0.0.1", server.port, timeout=2) as client:
            reply = client.js_create_stream("sparknet", ["sparknet.task.>"], max_age_seconds=600)
        assert reply["config"]["name"] == "sparknet"
        assert server.request[0] == "$JS.API.STREAM.CREATE.sparknet"
        config = json.loads(server.request[1].decode("utf-8"))
        assert config["subjects"] == ["sparknet.task.>"]
        assert config["max_age"] == 600_000_000_000
    finally:
        server.close()


def test_persistent_subscribe_yields_an_event_without_resubscribing():
    message = sample_event()
    server = FakeNats(message)
    try:
        with bus.NatsClient("127.0.0.1", server.port, timeout=2) as client:
            subscription = client.subscribe("sparknet.task.blue", timeout=2)
            received = next(subscription)
            subscription.close()
        assert received["event_id"] == message["event_id"]
    finally:
        server.close()

#!/usr/bin/env python3
"""Minimal NATS client for the sparknet event bus.

The bus carries validated `sparknet-event/1` envelopes. This module implements
the small plain-NATS wire surface the fleet needs: connect, publish and
subscribe-once. It does not implement JetStream consumer state; the server's
stream configuration owns persistence, and this client never grants authority.

The overlay encrypts transport. TLS is deliberately not re-implemented here;
use the overlay or a TLS-terminating sidecar if the bus is ever exposed.
"""

from __future__ import annotations

import contextlib
import json
import socket
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

_EVENT = load_shared("sparknet-event.py", "sparknet_event_bus_event")
EventError = _EVENT.EventError
MAX_MESSAGE_BYTES = 8 << 20
MAX_LINE_BYTES = 64 << 10


class NatsError(RuntimeError):
    """A fail-closed bus refusal."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BusAddress:
    host: str
    port: int

    @classmethod
    def parse(cls, url: str) -> BusAddress:
        parts = urlsplit(url if "://" in url else f"nats://{url}")
        if parts.scheme not in ("nats", "tcp"):
            raise NatsError("bad-url", f"unsupported NATS scheme {parts.scheme!r}")
        if not parts.hostname:
            raise NatsError("bad-url", "NATS URL has no host")
        try:
            port = parts.port or 4222
        except ValueError as exc:
            raise NatsError("bad-url", "NATS URL has an invalid port") from exc
        return cls(parts.hostname, port)


class NatsClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4222,
        *,
        name: str = "sparknet",
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.name = name
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._reader: Any = None
        self._sid = 0

    def __enter__(self) -> NatsClient:
        self.connect()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def connect(self) -> NatsClient:
        if self._socket is not None:
            return self
        try:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._socket.settimeout(self.timeout)
            self._reader = self._socket.makefile("rb")
        except OSError as exc:
            raise NatsError("connect-failed", f"cannot connect to NATS at {self.host}:{self.port}: {exc}") from exc
        info = self._line()
        if not info.startswith(b"INFO "):
            self.close()
            raise NatsError("bad-server", "NATS server did not send INFO")
        connect = {
            "verbose": False,
            "pedantic": False,
            "tls_required": False,
            "name": self.name,
            "lang": "python",
            "version": "1.0",
        }
        self._send(b"CONNECT " + json.dumps(connect, separators=(",", ":")).encode() + b"\r\nPING\r\n")
        self._expect_pong()
        return self

    def close(self) -> None:
        if self._reader is not None:
            with contextlib.suppress(OSError):
                self._reader.close()
            self._reader = None
        if self._socket is not None:
            with contextlib.suppress(OSError):
                self._socket.close()
            self._socket = None

    def publish(self, subject: str, event: Mapping[str, Any], *, flush: bool = True) -> bytes:
        normalised = _EVENT.validate_event(event)
        payload = _EVENT.canonical_json(normalised).encode("utf-8")
        self._send(self._pub_frame(subject, payload))
        if flush:
            self._send(b"PING\r\n")
            self._expect_pong()
        return payload

    def request(self, subject: str, payload: bytes, *, timeout: float | None = None) -> bytes:
        """Send one request/reply message and return the reply payload."""
        self._subject(subject)
        self._sid += 1
        sid = str(self._sid)
        inbox = f"_INBOX.{sid}.{uuid.uuid4().hex}"
        self._send(f"SUB {inbox} {sid}\r\n".encode("ascii"))
        self._send(self._pub_frame(subject, payload, reply=inbox))
        self._socket.settimeout(timeout or self.timeout)  # type: ignore[union-attr]
        try:
            while True:
                line = self._line()
                if line.startswith(b"PING"):
                    self._send(b"PONG\r\n")
                    continue
                if line.startswith(b"-ERR"):
                    raise NatsError("server-error", line.decode("utf-8", "replace"))
                if not line.startswith(b"MSG "):
                    continue
                parts = line.decode("ascii", "replace").split()
                if len(parts) < 4:
                    raise NatsError("bad-message", "malformed MSG line")
                size = int(parts[-1])
                if size < 0 or size > MAX_MESSAGE_BYTES:
                    raise NatsError("bad-message", "MSG size is out of range")
                data = self._reader.read(size)
                if len(data) != size:
                    raise NatsError("bad-message", "MSG payload is truncated")
                self._reader.read(2)
                return data
        finally:
            self._send(f"UNSUB {sid}\r\n".encode("ascii"))

    def js_create_stream(
        self,
        name: str,
        subjects: list[str],
        *,
        max_age_seconds: int = 86400,
        storage: str = "file",
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Create or update one JetStream stream; the server owns persistence."""
        if not name or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in name):
            raise NatsError("bad-stream", "stream name must be non-empty and alphanumeric/underscore/dash")
        if not isinstance(subjects, list) or not subjects or not all(isinstance(item, str) for item in subjects):
            raise NatsError("bad-stream", "stream subjects must be a non-empty list of strings")
        if not isinstance(max_age_seconds, int) or not 1 <= max_age_seconds <= 30 * 86400:
            raise NatsError("bad-stream", "max_age_seconds is out of range")
        if storage not in ("file", "memory"):
            raise NatsError("bad-stream", "storage must be file or memory")
        config = {
            "name": name,
            "subjects": subjects,
            "retention": "limits",
            "max_age": max_age_seconds * 1_000_000_000,
            "storage": storage,
            "discard": "old",
            "num_replicas": 1,
        }
        payload = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        raw = self.request(f"$JS.API.STREAM.CREATE.{name}", payload, timeout=timeout)
        try:
            reply = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NatsError("bad-stream", "JetStream reply is not JSON") from exc
        if not isinstance(reply, dict) or reply.get("error"):
            raise NatsError("bad-stream", f"JetStream refused stream creation: {reply}")
        return reply

    def subscribe(self, subject: str, *, timeout: float | None = None):
        """Yield events on one persistent subscription; no resubscribe gaps."""
        self._subject(subject)
        self._sid += 1
        sid = str(self._sid)
        self._send(f"SUB {subject} {sid}\r\n".encode("ascii"))
        # A persistent subscription blocks; a read timeout would leave the
        # buffered reader in an unusable state and silently drop later events.
        self._socket.settimeout(None)  # type: ignore[union-attr]
        try:
            while True:
                line = self._line()
                if line.startswith(b"PING"):
                    self._send(b"PONG\r\n")
                    continue
                if line.startswith(b"-ERR"):
                    raise NatsError("server-error", line.decode("utf-8", "replace"))
                if not line.startswith(b"MSG "):
                    continue
                parts = line.decode("ascii", "replace").split()
                if len(parts) < 4:
                    raise NatsError("bad-message", "malformed MSG line")
                size = int(parts[-1])
                if size < 0 or size > MAX_MESSAGE_BYTES:
                    raise NatsError("bad-message", "MSG size is out of range")
                payload = self._reader.read(size)
                if len(payload) != size:
                    raise NatsError("bad-message", "MSG payload is truncated")
                self._reader.read(2)
                try:
                    event = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise NatsError("bad-payload", "event payload is not JSON") from exc
                if not isinstance(event, dict):
                    raise NatsError("bad-payload", "event payload is not an object")
                yield _EVENT.validate_event(event)
        finally:
            with contextlib.suppress(OSError):
                self._send(f"UNSUB {sid}\r\n".encode("ascii"))

    def subscribe_once(self, subject: str, *, timeout: float | None = None) -> dict[str, Any]:
        self._subject(subject)
        self._sid += 1
        sid = str(self._sid)
        self._send(f"SUB {subject} {sid}\r\n".encode("ascii"))
        self._socket.settimeout(timeout or self.timeout)  # type: ignore[union-attr]
        try:
            while True:
                line = self._line()
                if line.startswith(b"PING"):
                    self._send(b"PONG\r\n")
                    continue
                if line.startswith(b"-ERR"):
                    raise NatsError("server-error", line.decode("utf-8", "replace"))
                if not line.startswith(b"MSG "):
                    continue
                parts = line.decode("ascii", "replace").split()
                if len(parts) < 4:
                    raise NatsError("bad-message", "malformed MSG line")
                try:
                    size = int(parts[-1])
                except ValueError as exc:
                    raise NatsError("bad-message", "MSG size is not an integer") from exc
                if size < 0 or size > MAX_MESSAGE_BYTES:
                    raise NatsError("bad-message", "MSG size is out of range")
                payload = self._reader.read(size)
                if len(payload) != size:
                    raise NatsError("bad-message", "MSG payload is truncated")
                self._reader.read(2)
                try:
                    event = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise NatsError("bad-payload", "event payload is not JSON") from exc
                if not isinstance(event, dict):
                    raise NatsError("bad-payload", "event payload is not an object")
                return _EVENT.validate_event(event)
        finally:
            self._send(f"UNSUB {sid}\r\n".encode("ascii"))

    @staticmethod
    def _subject(subject: str) -> None:
        if not subject or any(ch.isspace() or ch in "\r\n" for ch in subject):
            raise NatsError("bad-subject", "subject must be non-empty and contain no whitespace")

    def _pub_frame(self, subject: str, payload: bytes, *, reply: str | None = None) -> bytes:
        self._subject(subject)
        if len(payload) > MAX_MESSAGE_BYTES:
            raise NatsError("bad-payload", "payload exceeds the bus limit")
        if reply is not None:
            self._subject(reply)
            return f"PUB {subject} {reply} {len(payload)}\r\n".encode("ascii") + payload + b"\r\n"
        return f"PUB {subject} {len(payload)}\r\n".encode("ascii") + payload + b"\r\n"

    def _line(self) -> bytes:
        if self._reader is None:
            raise NatsError("not-connected", "NATS client is not connected")
        try:
            line = self._reader.readline(MAX_LINE_BYTES + 1)
        except OSError as exc:
            raise NatsError("read-failed", str(exc)) from exc
        if not line:
            raise NatsError("closed", "NATS connection closed")
        if len(line) > MAX_LINE_BYTES:
            raise NatsError("bad-line", "NATS line exceeds the limit")
        return line.rstrip(b"\r\n")

    def _send(self, data: bytes) -> None:
        if self._socket is None:
            raise NatsError("not-connected", "NATS client is not connected")
        try:
            self._socket.sendall(data)
        except OSError as exc:
            raise NatsError("write-failed", str(exc)) from exc

    def _expect_pong(self) -> None:
        while True:
            line = self._line()
            if line == b"PONG":
                return
            if line.startswith(b"PING"):
                self._send(b"PONG\r\n")
                continue
            if line.startswith(b"-ERR"):
                raise NatsError("server-error", line.decode("utf-8", "replace"))


def publish(url: str, event: Mapping[str, Any], *, name: str = "sparknet") -> bytes:
    address = BusAddress.parse(url)
    with NatsClient(address.host, address.port, name=name) as client:
        return client.publish(str(event.get("topic") or ""), event)


def subscribe_once(url: str, subject: str, *, timeout: float = 5.0) -> dict[str, Any]:
    address = BusAddress.parse(url)
    with NatsClient(address.host, address.port, timeout=timeout) as client:
        return client.subscribe_once(subject, timeout=timeout)

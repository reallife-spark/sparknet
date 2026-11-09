#!/usr/bin/env python3
"""Signed JSON HTTP transport — the one implementation both roles dial.

Why there is exactly one copy.  A client that signs a request and a server
that verifies it must agree on the exact canonical form of what the signature
covers.  If each role carried its own thin wrapper they could drift — a changed
separator, a timestamp format that differs by a trailing "Z" — and requests
would verify on the node that produced them and fail everywhere else.  That is
the same failure the authz module exists to prevent, so the transport lives
here once, next to it, and is loaded by path (see ``_load_authz``).

It does not reimplement Ed25519.  Every signing and verification operation
calls into ``sparknet-authz.py``, loaded by path from this directory.  When the
shared file cannot be found, this module raises rather than falling back to a
local implementation.

Request shape
~~~~~~~~~~~~~

Every signed request carries three headers:

- ``X-Sparknet-Identity``  — base64 of the sender's canonical identity JSON
- ``X-Sparknet-Timestamp`` — ISO-8601 UTC timestamp
- ``X-Sparknet-Signature`` — base64 Ed25519 signature over the request message

The request message binds method, path, the SHA-256 of the body and the
timestamp, so a captured request cannot be replayed onto a different path or
replayed wholesale after the timestamp window closes:

::

    sparknet-http/1\\n
    <METHOD>\\n
    <path>\\n
    <sha256-hex of body>\\n
    <timestamp>

The identity is bound by the key itself: the signature is made with the
sender's private half and verified with the matching public half, and the
fingerprint of the canonical identity is what the routes see as the caller.

Time is not read from the wall clock on the happy path.  ``verify_request``
takes an optional ``now`` so tests can push a request outside its freshness
window without sleeping, exactly as the election module does.

Two personalities, one listener
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A single ``serve()`` can answer both the local machine and the overlay by
classifying each caller's source address (``source_kind``).  A route class
listed in ``loopback_only_routes`` is the **local personality** and is refused
with HTTP 403 before the request is read when its caller is not loopback; every
other route is the **peer personality**, reached only over the fabric.  This
is the sparknet analogue of NVIDIA PAIR's dual-personality proxy: one port,
two audiences that must never bleed into each other, decided by the caller's
class rather than by what the caller claims.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time

try:  # Python 3.9+
    from collections.abc import Callable, Mapping, Sequence
except ImportError:  # pragma: no cover - Python 3.8
    from typing import Callable, Mapping, Sequence  # noqa: UP035

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

VERSION_PREFIX = b"sparknet-http/1"
DEFAULT_MAX_AGE_SECONDS = 300
DEFAULT_BIND = "127.0.0.1"

#: How many seconds one request may take before the server drops the
#: connection.  The 2026-10-08 review (finding F4) showed what a missing
#: bound costs: a client that connects and never finishes a request line (or
#: sends a Content-Length and then stops) would hold a listener thread open
#: indefinitely.  Every sparknet listener derives from :class:`TimeoutHandler`
#: so the bound is one number in one file — ``tests/test_service_timeouts.py``
#: fails if a listener stops inheriting it.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0

# Two personalities, one listener.  A route class (``loopback_only_routes``)
# is the local personality: only a loopback source may reach it, and anything
# else is refused with 403 *before* the request is even read.  Everything else
# the server exposes is the peer personality, reached exclusively over the
# overlay.  This is the sparknet analogue of PAIR's dual-personality proxy:
# the personality is chosen by the caller's source address, and a caller from
# the wrong personality class cannot make the server do work.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})

DEFAULT_SHARED_DIR = Path(__file__).resolve().parent


def _load_authz(shared_dir: Path | None = None) -> Any:
    """Load sparknet-authz.py by path, never by import.

    Loading by path is what proves there is one implementation.  An import
    would let a role quietly end up with a private copy, and two crypto
    implementations that must agree byte-for-byte is a second trust boundary.
    The resolve-and-cache mechanics live once in ``shared/sparknet_loader.py``.
    """
    dirs = [Path(shared_dir)] if shared_dir else None
    return load_shared(
        "sparknet-authz.py",
        "sparknet_authz",
        dirs=dirs,
        error=FileNotFoundError,
        message=(
            "cannot locate sparknet-authz.py; this transport refuses to reimplement "
            "Ed25519, so it cannot proceed without the shared implementation"
        ),
    )


# --- request message ---------------------------------------------------------


def request_message(
    method: str, path: str, body: bytes, timestamp: str, *, nonce: str = "", node_id: str = ""
) -> bytes:
    """The canonical bytes a signature covers. See the module docstring.

    ``nonce`` and ``node_id`` are optional so the original transport stays
    byte-compatible. The uplift intake passes both, making its replay nonce part
    of the signed request instead of an unsigned header an attacker can swap.
    """
    body_sha256 = hashlib.sha256(body).hexdigest()
    message = (
        VERSION_PREFIX
        + b"\n"
        + method.upper().encode("ascii")
        + b"\n"
        + path.encode("utf-8")
        + b"\n"
        + body_sha256.encode("ascii")
        + b"\n"
        + timestamp.encode("ascii")
    )
    if nonce or node_id:
        message += b"\n" + nonce.encode("utf-8") + b"\n" + node_id.encode("utf-8")
    return message


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# --- personalities ------------------------------------------------------------


def source_kind(client_address: tuple[str, int]) -> str:
    """Classify a caller into the local or the peer personality.

    Loopback addresses are the local personality; every other source address
    is the peer personality (the overlay).  A server bound to its overlay
    address sees both classes on one socket, so the personality must be
    decided per request from ``client_address``, exactly as PAIR's proxy
    decides on a per-connection basis.
    """
    host, _port = client_address
    return "loopback" if host in LOOPBACK_HOSTS else "overlay"


def check_source_policy(path: str, source: str, loopback_only_routes: tuple[str, ...] = ()) -> str | None:
    """Enforce a route class against a caller's personality.

    Returns ``None`` when the route may be served, or a stable ``reason``
    string when it must be refused.  Matching is a path prefix, so
    ``("/internal",)`` gates ``/internal`` and every sub-path beneath it.
    The refusal is intentional **before** any signature work: a caller from
    the wrong personality class should not be able to make the server parse
    or verify anything (PAIR refuses plaintext on the peer personality before
    reading the request, and this is the same idea with a route class).
    """
    if not loopback_only_routes:
        return None
    if source == "loopback":
        return None
    route = path.split("?", 1)[0]
    if any(route == prefix or route.startswith(prefix.rstrip("/") + "/") for prefix in loopback_only_routes):
        return "not-loopback"
    return None


# --- client ------------------------------------------------------------------


def sign_request(
    private_key: Any,
    method: str,
    path: str,
    body: bytes,
    timestamp: str | None = None,
) -> tuple[str, str]:
    """Sign ``method path``+body+timestamp and return ``(timestamp, sig_b64)``.

    ``private_key`` is an ``Ed25519PrivateKey`` as produced by
    ``sparknet_authz.load_private_key`` — never a raw string.
    """
    authz = _load_authz()
    stamp = timestamp or _utc_now()
    signature = authz.sign_bytes(private_key, request_message(method, path, body, stamp))
    return stamp, signature


def post_json(
    url: str,
    method: str,
    path: str,
    payload: dict[str, Any],
    private_key: Any,
    *,
    timeout: float = 10.0,
    timestamp: str | None = None,
    max_redirects: int = 3,
) -> tuple[int, dict[str, Any]]:
    """POST ``payload`` to ``url + path`` with a signed envelope.

    Returns ``(status_code, parsed_json_or_error_dict)``.  Server-side
    refusals come back as JSON bodies carrying a stable ``reason``, matching
    the election module's convention.
    """
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    stamp = timestamp or _utc_now()
    authz = _load_authz()
    signature = authz.sign_bytes(private_key, request_message(method, path, body, stamp))

    req = urlrequest.Request(
        url + path,
        data=body,
        method=method.upper(),
        headers={
            "Content-Type": "application/json",
            "X-Sparknet-Timestamp": stamp,
            "X-Sparknet-Signature": signature,
            "User-Agent": "sparknet-http/1",
        },
    )
    # This transport is signed and local by design; it must never leak a request
    # (or a failure to verify) through a machine-wide http_proxy.
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
            try:
                parsed: dict[str, Any] = json.loads(text)
            except json.JSONDecodeError:
                parsed = {"ok": False, "reason": "response-not-json", "detail": text[:512]}
            return resp.status, parsed
    except HTTPError as exc:
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed = {"ok": False, "reason": "response-not-json", "detail": str(exc)}
        return exc.code, parsed
    except (URLError, OSError, ConnectionError) as exc:
        return 0, {"ok": False, "reason": "transport-error", "detail": str(exc)}


# --- server ------------------------------------------------------------------


class RequestError(Exception):
    """A refused request, mapped to a stable HTTP status and JSON reason."""

    def __init__(self, status: int, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Route:
    """One listener route: where it answers, who may call it, and how it authenticates.

    ``auth`` is explicit because the wrong default is a security bug: a plain
    route must never become reachable from the overlay just because a caller
    forgot a flag. ``source`` is the personality class; ``allowed_sources`` is
    the narrower address allowlist the guard needs. ``verify`` is for a surface
    whose envelope is not the shared signed transport (the intake nonce
    envelope); it returns an identity dict or raises ``RequestError``.
    """

    path: str
    handler: Callable[[Request], Response | tuple[int, Any]]
    method: str = "*"
    auth: str = "plain"
    source: str = "any"
    allowed_sources: Callable[[], set[str]] | frozenset[str] | None = None
    verify: Callable[[Request], dict[str, Any]] | None = None
    max_body: int = 1_048_576
    parse_json: bool = True
    prefix: bool = False


@dataclass
class Request:
    """Everything a route handler needs; the transport hides the rest."""

    method: str
    path: str
    query: dict[str, list[str]]
    headers: Mapping[str, str]
    body: bytes
    json: Any
    source: str
    client: tuple[str, int]
    identity: dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    """A route result. A plain ``(status, payload)`` tuple also works."""

    status: int = 200
    payload: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes | None = None
    content_type: str = "application/json"


class TimeoutHandler(BaseHTTPRequestHandler):
    """A request handler whose reads are bounded by a socket timeout.

    ``BaseHTTPRequestHandler`` inherits from ``StreamRequestHandler``, whose
    ``setup`` applies ``timeout`` to the connection socket.  A client that
    connects and never finishes a request line or body therefore costs one
    listener thread for at most ``DEFAULT_REQUEST_TIMEOUT_SECONDS`` instead of
    forever: ``handle_one_request`` catches the timeout — ``socket.timeout`` on
    Python ≤3.9, ``TimeoutError`` on ≥3.10 — marks the connection closed and
    the loop moves on.

    Every sparknet listener derives from this class.  A listener that stops
    (a new bare ``BaseHTTPRequestHandler`` subclass, a fresh implementation in
    a new service) silently reverts to unbounded reads, which is exactly the
    defect the 2026-10-08 review found; ``tests/test_service_timeouts.py``
    fails on that mutation.
    """

    timeout = DEFAULT_REQUEST_TIMEOUT_SECONDS


class _Handler(TimeoutHandler):
    """Verifies the signed envelope, then dispatches to the router."""

    server_version = "sparknet-http/1"
    router: Callable[[str, str, dict[str, Any], dict[str, Any]], tuple[int, dict[str, Any]]]

    def _personality_refusal(self) -> RequestError | None:
        """Refuse a caller from the wrong personality class before reading it."""
        source = source_kind(self.client_address)
        loopback_only = getattr(self.server, "loopback_only_routes", ())
        reason = check_source_policy(self.path, source, loopback_only)
        if reason is not None:
            return RequestError(
                403, reason, f"this route is loopback-only; the caller is from the {source} personality"
            )
        return None

    def log_message(self, fmt: str, *args: Any) -> None:
        return  # loopback service; keep the log quiet

    def _read_body(self, *, allow_empty: bool = False, max_body: int = 1_048_576) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise RequestError(400, "malformed", "Content-Length is invalid") from exc
        if length <= 0:
            if allow_empty:
                return b"{}"
            raise RequestError(400, "malformed", "empty or oversized body")
        if length > max_body:
            raise RequestError(400, "malformed", f"body exceeds {max_body} bytes")
        return self.rfile.read(length)

    def _send(
        self,
        code: int,
        payload: dict[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
        body: bool = True,
    ) -> None:
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if not body:
            return
        try:
            self.wfile.write(blob)
        except (BrokenPipeError, ConnectionResetError):
            self.log_error("client closed before response was written")

    def _refuse(self, exc: RequestError) -> None:
        self._send(exc.status, {"ok": False, "reason": exc.reason, "detail": exc.detail})

    def _verify(self, body: bytes) -> dict[str, Any]:
        """Verify the signed envelope.

        The caller's identity is bound by key possession: the signature covers
        method+path+body+timestamp and verifies against the configured public
        key, so a route knows *who* signed without parsing an identity claim.
        The freshness window is the replay defence: a signature is only good
        within ``max_age_seconds`` of the timestamp it names.
        """
        authz = _load_authz()
        timestamp = self.headers.get("X-Sparknet-Timestamp", "")
        signature = self.headers.get("X-Sparknet-Signature", "")
        if not timestamp or not signature:
            raise RequestError(401, "unsigned", "missing X-Sparknet-Timestamp or X-Sparknet-Signature")
        parsed_ts = self._parse_ts(timestamp)
        if parsed_ts is None:
            raise RequestError(401, "bad-timestamp", "timestamp is not ISO-8601 UTC")
        message = request_message(self.command, self.path, body, timestamp)
        keyring = getattr(self.server, "public_keys", None) or {}
        if keyring:
            for key_id, candidate in keyring.items():
                if authz.verify_signature(candidate, signature, message):
                    verified_key_id = key_id
                    break
            else:
                raise RequestError(401, "bad-signature", "signature does not verify against any configured key")
        else:
            key = self.server.public_key  # type: ignore[attr-defined]
            if key is None:
                raise RequestError(503, "no-verifier", "this endpoint has no public key configured")
            if not authz.verify_signature(key, signature, message):
                raise RequestError(401, "bad-signature", "signature does not verify against the configured key")
            verified_key_id = None

        now = self.server.clock() if self.server.clock else datetime.now(timezone.utc)  # type: ignore[attr-defined]
        age = now - parsed_ts
        if age < -timedelta(seconds=5) or age > timedelta(seconds=self.server.max_age_seconds):  # type: ignore[attr-defined]
            raise RequestError(401, "stale", f"request is {age.total_seconds():.0f}s outside the freshness window")

        return {"verified_key_id": verified_key_id}

    @staticmethod
    def _parse_ts(value: str) -> datetime | None:
        text = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def do_GET(self) -> None:
        refusal = self._personality_refusal()
        if refusal is not None:
            self._refuse(refusal)
            return
        raw = self._read_body(allow_empty=True)
        try:
            identity = self._verify(raw)
            identity["source_kind"] = source_kind(self.client_address)
            code, payload = self.server.router("GET", self.path, {}, identity)  # type: ignore[attr-defined]
        except RequestError as exc:
            self._refuse(exc)
            return
        except Exception as exc:
            print(f"[sparknet-http] internal error on {self.command} {self.path}: {exc!r}", file=sys.stderr)
            self._send(500, {"ok": False, "reason": "internal"})
            return
        self._send(code, payload)

    def do_POST(self) -> None:
        refusal = self._personality_refusal()
        if refusal is not None:
            self._refuse(refusal)
            return
        try:
            raw = self._read_body()
            try:
                body = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._refuse(RequestError(400, "malformed", f"body is not JSON: {exc}"))
                return
            if not isinstance(body, dict):
                raise RequestError(400, "malformed", "body is not a JSON object")
        except RequestError as exc:
            self._refuse(exc)
            return
        try:
            identity = self._verify(raw)
        except RequestError as exc:
            self._refuse(exc)
            return
        identity["source_kind"] = source_kind(self.client_address)
        try:
            code, payload = self.server.router("POST", self.path, body, identity)  # type: ignore[attr-defined]
        except RequestError as exc:
            self._refuse(exc)
            return
        except Exception as exc:
            print(f"[sparknet-http] internal error on {self.command} {self.path}: {exc!r}", file=sys.stderr)
            self._send(500, {"ok": False, "reason": "internal"})
            return
        self._send(code, payload)


def serve(
    router: Callable[[str, str, dict[str, Any], dict[str, Any]], tuple[int, dict[str, Any]]],
    *,
    bind: str = DEFAULT_BIND,
    port: int,
    public_key: Any | None = None,
    public_keys: dict[str, Any] | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: Callable[[], datetime] | None = None,
    ready: Callable[[], None] | None = None,
    loopback_only_routes: tuple[str, ...] = (),
) -> ThreadingHTTPServer:
    """Start a signed JSON server on ``(bind, port)``.

    Exactly one of ``public_key`` (one pinned caller) or ``public_keys``
    (``key_id -> key``, e.g. one per registry node) must be supplied. A keyring
    verifies against every candidate and tells the router which key matched in
    ``identity["verified_key_id"]``; the router still decides what that key may
    do. The transport never chooses an authorisation from a key id alone.

    ``router(method, path, body, identity) -> (status, payload)`` answers every
    request. ``ready`` is called once the socket is listening so a test can
    know when to start its clients without sleeping on a guess.

    ``loopback_only_routes`` opens the **local personality**: each prefix names
    a route class that only a loopback source may reach. ``identity`` seen by
    the router carries ``source_kind`` (``"loopback"`` or ``"overlay"``), so a
    router can apply its own per-class policy after the envelope verifies.
    """
    if (public_key is None) == (not public_keys):
        raise ValueError("serve() needs exactly one of public_key or public_keys")
    server = ThreadingHTTPServer((bind, port), _Handler)
    server.router = router  # type: ignore[attr-defined]
    server.public_key = public_key  # type: ignore[attr-defined]
    server.public_keys = dict(public_keys) if public_keys else {}  # type: ignore[attr-defined]
    server.clock = now  # type: ignore[attr-defined]
    server.max_age_seconds = max_age_seconds  # type: ignore[attr-defined]
    server.loopback_only_routes = loopback_only_routes  # type: ignore[attr-defined]
    if ready is not None:
        ready()
    return server


# --- the route-table listener -------------------------------------------------


class _ListenerServer(ThreadingHTTPServer):
    """The one server class every route-table listener uses."""

    daemon_threads = True
    allow_reuse_address = True


def _route_lookup(routes: Sequence[Route], method: str, path: str) -> tuple[Route | None, bool]:
    """Return ``(route, path_matched)``. Exact routes win; prefixes are longest-first."""
    exact = [r for r in routes if not r.prefix and r.path == path]
    for route in exact:
        if route.method in ("*", method.upper()):
            return route, True
    if exact:
        return None, True
    prefixes = [r for r in routes if r.prefix and (path == r.path or path.startswith(r.path.rstrip("/") + "/"))]
    prefixes.sort(key=lambda r: len(r.path), reverse=True)
    for route in prefixes:
        if route.method in ("*", method.upper()):
            return route, True
    return None, bool(prefixes)


class _RouteHandler(_Handler):
    """Dispatch one request through the route table with an explicit policy."""

    server_version = "sparknet-listener/1"

    def log_message(self, fmt: str, *args: Any) -> None:
        name = getattr(self.server, "name", "sparknet")
        print(f"[{name}] {self.address_string()} {fmt % args}", file=sys.stderr)

    def _source(self) -> str:
        return source_kind(self.client_address)

    def _policy_refusal(self, route: Route) -> RequestError | None:
        source = self._source()
        if route.source == "loopback" and source != "loopback":
            return RequestError(403, "not-loopback", "this route is loopback-only")
        if route.source == "overlay" and source == "loopback":
            return RequestError(403, "not-overlay", "this route is overlay-only")
        allowed = route.allowed_sources() if callable(route.allowed_sources) else route.allowed_sources
        if allowed is not None and self.client_address[0] not in allowed:
            return RequestError(403, "source-refused", "the caller is not in this route's source allowlist")
        legacy = getattr(self.server, "loopback_only_routes", ())
        reason = check_source_policy(self.path, source, legacy)
        if reason is not None:
            return RequestError(403, reason, "this route class is loopback-only")
        return None

    def _request(
        self,
        route: Route,
        method: str,
        parsed: Any,
        raw: bytes,
        identity: dict[str, Any],
        body: Any,
    ) -> Request:
        return Request(
            method=method,
            path=parsed.path,
            query=parse_qs(parsed.query),
            headers={key: value for key, value in self.headers.items()},
            body=raw,
            json=body,
            source=self._source(),
            client=self.client_address,
            identity=identity,
        )

    def _parse_body(self, route: Route, raw: bytes) -> Any:
        if not route.parse_json:
            return None
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestError(400, "malformed", f"body is not JSON: {exc}") from exc
        if route.auth == "signed" and not isinstance(body, dict):
            raise RequestError(400, "malformed", "signed body must be a JSON object")
        return body

    def _send_raw(self, status: int, raw: bytes, content_type: str, headers: Mapping[str, str], *, body: bool) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if body:
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                self.log_error("client closed before response was written")

    def _respond(self, result: Response | tuple[int, Any], *, head: bool) -> None:
        if isinstance(result, Response):
            if result.raw is not None:
                self._send_raw(result.status, result.raw, result.content_type, result.headers, body=not head)
                return
            payload = result.payload if isinstance(result.payload, dict) else {"ok": True, "result": result.payload}
            self._send(result.status, payload, headers=result.headers, body=not head)
            return
        if isinstance(result, dict):
            status, payload = 200, result
        elif isinstance(result, tuple) and len(result) == 2:
            status, payload = result
        else:
            status, payload = 200, result
        if isinstance(payload, bytes):
            self._send_raw(status, payload, "application/octet-stream", {}, body=not head)
        elif isinstance(payload, dict):
            self._send(status, payload, body=not head)
        else:
            self._send(status, {"ok": True, "result": payload}, body=not head)

    def _refuse_any(self, exc: BaseException) -> None:
        refusal = getattr(self.server, "refusal", None)
        if refusal is not None:
            status, payload = refusal(exc)
            self._send(status, payload)
            return
        if isinstance(exc, RequestError):
            self._refuse(exc)
            return
        print(f"[sparknet-listener] refused {self.command} {self.path}: {exc!r}", file=sys.stderr)
        self._send(500, {"ok": False, "reason": "internal"})

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        route, path_matched = self.server.lookup(method, parsed.path)  # type: ignore[attr-defined]
        if route is None:
            if path_matched:
                self._send(405, {"ok": False, "reason": "method-not-allowed"})
            else:
                self._send(404, {"ok": False, "reason": "not-found"})
            return
        refusal = self._policy_refusal(route)
        if refusal is not None:
            self._refuse_any(refusal)
            return
        allow_empty = method.upper() in {"GET", "HEAD", "DELETE"}
        try:
            raw = self._read_body(allow_empty=allow_empty, max_body=route.max_body)
        except RequestError as exc:
            self._refuse(exc)
            return
        identity: dict[str, Any] = {}
        try:
            if route.auth == "signed":
                identity = self._verify(raw)
            elif route.auth == "custom":
                if route.verify is None:
                    raise RequestError(500, "no-verifier", "custom route has no verifier")
                identity = route.verify(self._request(route, method, parsed, raw, {}, None)) or {}
            elif route.auth != "plain":
                raise RequestError(500, "bad-auth-policy", f"unknown auth policy: {route.auth}")
            body = self._parse_body(route, raw)
            request = self._request(route, method, parsed, raw, identity, body)
            result = route.handler(request)
        except RequestError as exc:
            self._refuse(exc)
            return
        except getattr(self.server, "refusal_errors", ()) as exc:  # type: ignore[misc]
            self._refuse_any(exc)
            return
        except Exception as exc:
            print(f"[sparknet-listener] internal error on {self.command} {self.path}: {exc!r}", file=sys.stderr)
            self._send(500, {"ok": False, "reason": "internal"})
            return
        self._respond(result, head=method.upper() == "HEAD")

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")

    def do_PUT(self) -> None:
        self._dispatch("PUT")


class Listener:
    """A bound route-table listener with an explicit start/stop lifecycle."""

    def __init__(
        self,
        routes: Sequence[Route],
        *,
        name: str = "sparknet",
        bind: str | Sequence[str] = DEFAULT_BIND,
        port: int,
        public_key: Any | None = None,
        public_keys: dict[str, Any] | None = None,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
        now: Callable[[], datetime] | None = None,
        ready: Callable[[], None] | None = None,
        loopback_only_routes: tuple[str, ...] = (),
        health: bool | Callable[[], Response | tuple[int, Any]] = True,
        refusal: Callable[[BaseException], tuple[int, dict[str, Any]]] | None = None,
        refusal_errors: tuple[type[BaseException], ...] = (RequestError,),
        handler_class: type[_RouteHandler] | None = None,
    ) -> None:
        self.routes = list(routes)
        self.name = name
        self.binds = (bind,) if isinstance(bind, str) else tuple(bind)
        self.port = port
        self.public_key = public_key
        self.public_keys = dict(public_keys) if public_keys else {}
        self.max_age_seconds = max_age_seconds
        self.now = now
        self.ready = ready
        self.loopback_only_routes = loopback_only_routes
        self.refusal = refusal
        self.refusal_errors = refusal_errors
        self.handler_class = handler_class or _RouteHandler
        self.servers: list[_ListenerServer] = []
        self._threads: list[threading.Thread] = []
        self._validate()
        if health and not any(route.path == "/healthz" for route in self.routes):
            handler = health if callable(health) else self._default_health
            self.routes.insert(0, Route("/healthz", handler, auth="plain", source="any", parse_json=False, max_body=0))

    def _validate(self) -> None:
        for route in self.routes:
            if route.auth not in {"plain", "signed", "custom"}:
                raise ValueError(f"unknown route auth policy: {route.auth!r}")
            if route.source not in {"any", "loopback", "overlay"}:
                raise ValueError(f"unknown route source policy: {route.source!r}")
            if route.auth == "custom" and route.verify is None:
                raise ValueError(f"custom route {route.path!r} needs a verifier")
        if any(route.auth == "signed" for route in self.routes) and (self.public_key is None) == (not self.public_keys):
            raise ValueError("signed routes need exactly one of public_key or public_keys")

    def _default_health(self, request: Request | None = None) -> Response:
        return Response(200, {"ok": True, "service": self.name})

    def bind(self) -> Listener:
        for address in self.binds:
            server = _ListenerServer((address, self.port), self.handler_class)
            server.name = self.name  # type: ignore[attr-defined]
            server.routes = self.routes  # type: ignore[attr-defined]
            server.lookup = lambda method, path: _route_lookup(self.routes, method, path)  # type: ignore[attr-defined]
            server.public_key = self.public_key  # type: ignore[attr-defined]
            server.public_keys = self.public_keys  # type: ignore[attr-defined]
            server.clock = self.now  # type: ignore[attr-defined]
            server.max_age_seconds = self.max_age_seconds  # type: ignore[attr-defined]
            server.loopback_only_routes = self.loopback_only_routes  # type: ignore[attr-defined]
            server.refusal = self.refusal  # type: ignore[attr-defined]
            server.refusal_errors = self.refusal_errors  # type: ignore[attr-defined]
            self.servers.append(server)
        if self.ready is not None:
            self.ready()
        return self

    def start(self) -> Listener:
        if not self.servers:
            self.bind()
        for server in self.servers:
            thread = threading.Thread(
                target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True, name=f"{self.name}-listener"
            )
            thread.start()
            self._threads.append(thread)
        return self

    def stop(self) -> None:
        for server in self.servers:
            if self._threads:
                server.shutdown()
            server.server_close()
        for thread in self._threads:
            thread.join(timeout=2.0)
        self.servers.clear()
        self._threads.clear()

    def wait(self) -> None:
        if not self._threads:
            self.start()
        try:
            while any(thread.is_alive() for thread in self._threads):
                time.sleep(0.2)
        except KeyboardInterrupt:
            self.stop()

    # Compatibility names for callers that used the raw ThreadingHTTPServer.
    def shutdown(self) -> None:
        self.stop()

    def server_close(self) -> None:
        return

    def join(self, timeout: float | None = None) -> None:
        for thread in self._threads:
            thread.join(timeout=timeout)

    def __enter__(self) -> Listener:
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()


def listen(
    routes: Sequence[Route],
    *,
    name: str = "sparknet",
    bind: str | Sequence[str] = DEFAULT_BIND,
    port: int,
    public_key: Any | None = None,
    public_keys: dict[str, Any] | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: Callable[[], datetime] | None = None,
    ready: Callable[[], None] | None = None,
    loopback_only_routes: tuple[str, ...] = (),
    health: bool | Callable[[], Response | tuple[int, Any]] = True,
    refusal: Callable[[BaseException], tuple[int, dict[str, Any]]] | None = None,
    refusal_errors: tuple[type[BaseException], ...] = (RequestError,),
    handler_class: type[_RouteHandler] | None = None,
) -> Listener:
    """Bind a route-table listener and return it ready to start.

    Every route declares its auth and source policy. Signed routes reuse the
    same canonical envelope and verifier as ``serve``; plain and custom routes
    skip the signed check but cannot opt into a weaker source policy by
    accident. The caller owns the handlers and their authority checks.
    """
    listener = Listener(
        routes,
        name=name,
        bind=bind,
        port=port,
        public_key=public_key,
        public_keys=public_keys,
        max_age_seconds=max_age_seconds,
        now=now,
        ready=ready,
        loopback_only_routes=loopback_only_routes,
        health=health,
        refusal=refusal,
        refusal_errors=refusal_errors,
        handler_class=handler_class,
    )
    return listener.bind()


# --- helpers -----------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="sparknet-http — signed JSON transport (library, not a service)")
    p.add_argument("--self-test", action="store_true", help="generate a keypair and sign/verify a request message")
    args = p.parse_args(argv)

    if args.self_test:
        authz = _load_authz()
        _, priv_b64 = authz.generate_keypair()
        priv = authz.private_key_from_b64(priv_b64)
        public_key = priv.public_key()
        body = b'{"hello":"world"}'
        stamp = _utc_now()
        sig = authz.sign_bytes(priv, request_message("POST", "/v1/ping", body, stamp))
        ok = authz.verify_signature(public_key, sig, request_message("POST", "/v1/ping", body, stamp))
        print(f"self-test: message={request_message('POST', '/v1/ping', body, stamp)!r}")
        print(f"self-test: signature valid: {ok}")
        return 0 if ok else 1

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(_main())

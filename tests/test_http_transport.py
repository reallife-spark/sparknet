"""The shared signed HTTP transport.

`shared/sparknet-http.py` is the one implementation of the signed JSON
transport both roles dial. Like authz and consensus it has to be loaded by
path, not imported — a role that imports it would be able to drift a copy and
verify requests against its own private idea of what a signature covers.

What this file asserts:

1. **Real keys, real signatures.** Every test generates its own keypair (or
   uses a fresh one) and signs for real; a mocked signature would pass whether
   or not the transport verifies anything.
2. **The crypto lives in one place.** `sparknet-http.py` may not contain any
   Ed25519 logic of its own — it must load `sparknet-authz.py` by path.
3. **The wire path is exercised end to end.** A signed request travels
   loopback from client to a live `serve()` listener and back, exactly as a
   service would use it. Unsigned, stale and wrong-key requests all have to be
   refused with a stable JSON reason.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPO_ROOT / "shared"
HTTP_SCRIPT = SHARED / "sparknet-http.py"
AUTHZ_SCRIPT = SHARED / "sparknet-authz.py"


@pytest.fixture(scope="module")
def http():
    """shared/sparknet-http.py, loaded by path for the reason authz is."""
    spec = importlib.util.spec_from_file_location("sparknet_http", HTTP_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def authz(http):
    return http._load_authz()


@pytest.fixture
def keypair(authz):
    """A fresh (private, public) pair."""
    _, priv_b64 = authz.generate_keypair()
    priv = authz.private_key_from_b64(priv_b64)
    return priv, priv.public_key()


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _Serve:
    """A live server on an ephemeral loopback port, torn down on exit."""

    def __init__(self, http, router, public_key, *, now=None):
        self.http = http
        self.port = _free_port()
        self._server = http.serve(
            router,
            port=self.port,
            public_key=public_key,
            now=now,
        )
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _echo_router(method, path, body, identity):
    return 200, {"ok": True, "echoed": body}


# --- the one implementation --------------------------------------------------


def test_transport_does_not_reimplement_ed25519(http):
    """The crypto stays in sparknet-authz.py, loaded by path."""
    source = HTTP_SCRIPT.read_text()
    assert "cryptography" not in source, "transport must not reach for crypto itself"
    assert "sparknet-authz" in source


def test_transport_loads_authz_by_path(http, authz, keypair):
    """_load_authz finds the shared file even from a fresh cwd."""
    priv, _ = keypair
    stamp = "2026-10-08T00:00:00Z"
    message = http.request_message("POST", "/v1/status", b"{}", stamp)
    sig = authz.sign_bytes(priv, message)
    assert authz.verify_signature(priv.public_key(), sig, message) is True


# --- personalities -----------------------------------------------------------


def test_source_kind_classifies_loopback_and_overlay(http):
    """A caller belongs to exactly one personality, decided by source address."""
    assert http.source_kind(("127.0.0.1", 12345)) == "loopback"
    assert http.source_kind(("::1", 12345)) == "loopback"
    assert http.source_kind(("10.100.0.1", 12345)) == "overlay"
    assert http.source_kind(("10.100.0.9", 12345)) == "overlay"
    assert http.source_kind(("192.168.178.42", 12345)) == "overlay"


def test_source_policy_allows_loopback_everywhere(http):
    """The local personality may reach a loopback-only route class."""
    assert http.check_source_policy("/internal", "loopback", ("/internal",)) is None
    assert http.check_source_policy("/internal/deep", "loopback", ("/internal",)) is None
    assert http.check_source_policy("/v1/status", "loopback", ("/internal",)) is None


def test_source_policy_refuses_overlay_before_read(http):
    """The peer personality is frozen out of a loopback-only route class.

    The refusal is a directive to the server to do no work at all: it must be
    enforceable before the request is parsed or verified, so it is expressed
    as a stable reason string that the handler maps to HTTP 403.
    """
    assert http.check_source_policy("/internal", "overlay", ("/internal",)) == "not-loopback"
    assert http.check_source_policy("/internal/deep", "overlay", ("/internal",)) == "not-loopback"
    assert http.check_source_policy("/v1/status", "overlay", ("/internal",)) is None


def test_no_loopback_routes_means_no_personality_gate(http):
    assert http.check_source_policy("/anything", "overlay", ()) is None


# --- request message --------------------------------------------------------


def test_request_message_is_stable_json(http):
    """The signed scope is deterministic: method, path, body sha256, timestamp."""
    body = b'{"a": "b"}'
    a = http.request_message("POST", "/v1/status", body, "2026-10-08T00:00:00Z")
    b = http.request_message("post", "/v1/status", body, "2026-10-08T00:00:00Z")
    assert a == b, "method must be case-normalised to uppercase"
    assert a != http.request_message("GET", "/v1/status", body, "2026-10-08T00:00:00Z")
    assert a != http.request_message("POST", "/v1/other", body, "2026-10-08T00:00:00Z")
    assert a != http.request_message("POST", "/v1/status", b'{"a": "c"}', "2026-10-08T00:00:00Z")
    assert a != http.request_message("POST", "/v1/status", body, "2026-10-08T00:00:01Z")
    assert a.startswith(b"sparknet-http/1\n")


# --- signed roundtrip -------------------------------------------------------


def test_signed_request_roundtrip(http, authz, keypair):
    priv, pub = keypair
    server = _Serve(http, _echo_router, pub)
    try:
        code, payload = http.post_json(server.base, "POST", "/v1/status", {"probe": 1}, priv)
        assert code == 200
        assert payload["ok"] is True
        assert payload["echoed"] == {"probe": 1}
    finally:
        server.close()


def test_unsigned_request_is_refused(http, keypair):
    _priv, pub = keypair
    server = _Serve(http, _echo_router, pub)
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(server.base + "/v1/status", data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 401
        import json

        body = json.loads(excinfo.value.read().decode())
        assert body["reason"] == "unsigned"
    finally:
        server.close()


def test_wrong_key_is_refused(http, authz):
    """The server trusts one key; a client signing with any other is refused."""
    priv = authz.private_key_from_b64(authz.generate_keypair()[1])
    pub = priv.public_key()
    server = _Serve(http, _echo_router, pub)
    try:
        other_priv = authz.private_key_from_b64(authz.generate_keypair()[1])
        code, payload = http.post_json(server.base, "POST", "/v1/status", {"probe": 1}, other_priv)
        assert code == 401
        assert payload["reason"] == "bad-signature"
    finally:
        server.close()


def _non_loopback_ipv4() -> str | None:
    """A private source address proving the overlay personality in a real test.

    Connecting a UDP socket to a non-routable multicast address selects a route
    without sending a packet, so this works offline. The ``connect`` never
    transmits; it only makes the kernel choose a source address.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def test_loopback_only_route_refused_from_overlay_socket(http, authz, keypair):
    """The peer personality cannot reach a loopback-only route class, live.

    The listener binds 0.0.0.0 so both personalities share one port. A request
    that arrives from a non-loopback source is refused HTTP 403 ``not-loopback``
    *before* the envelope is verified — even a perfectly signed request from a
    valid peer is frozen out, because the wrong personality class must not make
    the server do work. The same route reached from 127.0.0.1 is served.
    """
    source = _non_loopback_ipv4()
    if source is None:
        pytest.skip("no non-loopback IPv4 address to act as the overlay source")

    priv, pub = keypair
    port = _free_port()

    def router(method, path, body, identity):
        return (200, {"ok": True, "source_kind": identity.get("source_kind"), "path": path})

    server = http.serve(router, bind="0.0.0.0", port=port, public_key=pub, loopback_only_routes=("/internal",))

    import threading

    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()

    def _close():
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    try:
        base_source = f"http://{source}:{port}"
        base_local = f"http://127.0.0.1:{port}"

        code, payload = http.post_json(base_source, "POST", "/internal/secret", {"x": 1}, priv)
        assert code == 403
        assert payload["reason"] == "not-loopback"

        code, payload = http.post_json(base_source, "POST", "/v1/status", {"x": 1}, priv)
        assert code == 200, payload
        assert payload["source_kind"] == "overlay"

        code, payload = http.post_json(base_local, "POST", "/internal/secret", {"x": 1}, priv)
        assert code == 200, payload
        assert payload["source_kind"] == "loopback"
    finally:
        _close()


def test_stale_request_is_refused(http, keypair, authz):
    priv, pub = keypair
    now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
    server = _Serve(http, _echo_router, pub, now=lambda: now)
    try:
        old_stamp = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        body = b'{"probe": 1}'
        message = http.request_message("POST", "/v1/status", body, old_stamp)
        sig = authz.sign_bytes(priv, message)
        import urllib.error
        import urllib.request

        date = old_stamp.replace("+00:00", "Z")
        req = urllib.request.Request(
            server.base + "/v1/status",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "X-Sparknet-Timestamp": date, "X-Sparknet-Signature": sig},
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=5)
        assert excinfo.value.code == 401
        import json

        refusal = json.loads(excinfo.value.read().decode())
        assert refusal["reason"] == "stale"
    finally:
        server.close()


# --- the bridge proof -------------------------------------------------------


def test_dispatch_bridge_serves_signed_status(http, authz):
    """The first real consumer: peer-node's dispatch-bridge on 4096.

    The bridge binds with the node's own key (proving possession of its
    identity) and answers a signed /v1/status. It must reject unsigned traffic
    the same way the library does.
    """
    # Rewire the bridge's _load_keypair to a fresh key so this test never
    # depends on a real node having run user-init.
    keys_dir = REPO_ROOT / "peer-node" / ".state" / "keys"
    priv_path = keys_dir / "user.ed25519"
    if not priv_path.is_file():
        pytest.skip("peer-node has no user key; run `make -C peer-node user-init`")

    priv = authz.load_private_key(priv_path)

    import importlib.util as iu

    bridge_spec = iu.spec_from_file_location(
        "sparknet_dispatch_bridge", REPO_ROOT / "peer-node" / "services" / "sparknet-dispatch-bridge.py"
    )
    assert bridge_spec and bridge_spec.loader
    bridge = iu.module_from_spec(bridge_spec)
    sys.modules[bridge_spec.name] = bridge
    bridge_spec.loader.exec_module(bridge)

    server = _Serve(http, bridge._make_router(bridge.STATES), priv.public_key())
    try:
        code, payload = http.post_json(server.base, "POST", "/v1/status", {"probe": 1}, priv)
        assert code == 200
        assert payload["ok"] is True
        assert payload["states"] == bridge.STATES
        assert "never through this bridge" in payload["note"]
    finally:
        server.close()


# --- timeouts and 500 hygiene -------------------------------------------------


def test_router_exceptions_do_not_leak_internals(http, keypair, capsys):
    """F10: a 500 must name a stable reason, never the exception text.

    The exception can mention file paths, key material or internals the caller
    has no right to see; it goes to stderr instead, where an operator reads it.
    """

    def _boom(method, path, body, identity):
        raise RuntimeError("SECRET_TRANSPORT_DETAIL")

    priv, pub = keypair
    server = _Serve(http, _boom, pub)
    try:
        code, payload = http.post_json(server.base, "POST", "/v1/status", {"probe": 1}, priv)
        assert code == 500
        assert payload["reason"] == "internal"
        assert "SECRET_TRANSPORT_DETAIL" not in str(payload)
        assert "SECRET_TRANSPORT_DETAIL" in capsys.readouterr().err
    finally:
        server.close()


def test_slow_client_is_dropped_then_a_fresh_connection_is_served(http, keypair, monkeypatch):
    """F4: a client that never finishes its request line must not hold the listener.

    The request line is sent without its trailing CRLF, so the server's
    ``readline`` blocks; the socket timeout (patched down to 0.4 s for the
    test) has to make the listener drop the connection, after which a fresh,
    complete request is still answered.
    """
    priv, pub = keypair
    server = _Serve(http, _echo_router, pub)
    try:
        monkeypatch.setattr(http._Handler, "timeout", 0.4)

        sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        sock.sendall(b"GET / HTTP/1.1")  # deliberately incomplete: no CRLF yet
        sock.settimeout(3)
        assert sock.recv(4096) == b"", "the listener must close an idle trickle connection"
        sock.close()

        code, payload = http.post_json(server.base, "POST", "/v1/status", {"probe": 2}, priv)
        assert code == 200
        assert payload["ok"] is True
    finally:
        server.close()


def test_a_keyring_reports_which_peer_key_verified(http, authz, keypair) -> None:
    """4203 has more than one peer; the transport must not pin one key.

    The router receives the matching key id, not a caller-supplied claim. It
    still decides whether that id may do anything.
    """
    seen: list[str | None] = []

    def router(method, path, body, identity):
        seen.append(identity.get("verified_key_id"))
        return 200, {"ok": True}

    _, first = authz.generate_keypair()
    second_priv_b64 = authz.generate_keypair()[1]
    second = authz.private_key_from_b64(second_priv_b64)
    port = _free_port()
    server = http.serve(
        router,
        bind="127.0.0.1",
        port=port,
        public_keys={"peer-a": authz.private_key_from_b64(first).public_key(), "peer-b": second.public_key()},
    )
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        status, body = http.post_json(f"http://127.0.0.1:{port}", "POST", "/v1/x", {"x": 1}, second)
        assert (status, body["ok"]) == (200, True)
        assert seen == ["peer-b"]
        status, body = http.post_json(
            f"http://127.0.0.1:{port}",
            "POST",
            "/v1/x",
            {"x": 1},
            authz.private_key_from_b64(authz.generate_keypair()[1]),
        )
        assert status == 401 and body["reason"] == "bad-signature"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_loopback_policy_ignores_the_query_string(http):
    assert http.check_source_policy("/internal?x=1", "overlay", ("/internal",)) == "not-loopback"

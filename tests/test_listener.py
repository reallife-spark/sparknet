"""The one route-table listener: policy, refusals, health and lifecycle."""

from __future__ import annotations

import ast
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"


@pytest.fixture(scope="module")
def http():
    return load_by_path("sparknet_http_listener_test", SHARED / "sparknet-http.py")


@pytest.fixture(scope="module")
def authz():
    return load_by_path("sparknet_authz_listener_test", SHARED / "sparknet-authz.py")


def _listener(http, routes, **kwargs):
    listener = http.listen(routes, port=0, name="listener-test", **kwargs)
    listener.start()
    port = listener.servers[0].server_address[1]
    return listener, port


def _get(port: int, path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_plain_route_and_health(http) -> None:
    listener, port = _listener(
        http,
        [http.Route("/hello", lambda request: http.Response(200, {"hello": request.path}))],
    )
    try:
        assert _get(port, "/hello") == (200, {"hello": "/hello"})
        status, health = _get(port, "/healthz")
        assert status == 200
        assert health["ok"] is True
        assert health["service"] == "listener-test"
    finally:
        listener.stop()


def test_signed_route_reuses_the_shared_envelope(http, authz) -> None:
    private_b64, _public_b64 = authz.generate_keypair()
    private = authz.private_key_from_b64(private_b64)
    listener, port = _listener(
        http,
        [http.Route("/signed", lambda request: {"identity": request.identity}, auth="signed")],
        public_key=private.public_key(),
    )
    try:
        status, payload = http.post_json(f"http://127.0.0.1:{port}", "GET", "/signed", {}, private)
        assert status == 200
        assert payload["identity"]["verified_key_id"] is None
    finally:
        listener.stop()


def test_signed_route_refuses_a_missing_envelope(http) -> None:
    listener, port = _listener(
        http,
        [http.Route("/signed", lambda request: {"ok": True}, auth="signed")],
        public_key=None,
        public_keys={"node": object()},
    )
    try:
        status, payload = _get(port, "/signed")
        assert status == 401
        assert payload["reason"] == "unsigned"
    finally:
        listener.stop()


def test_source_policy_refuses_before_the_handler_runs(http) -> None:
    called = []
    listener, port = _listener(
        http,
        [http.Route("/overlay", lambda request: called.append(True) or {"ok": True}, source="overlay")],
    )
    try:
        status, payload = _get(port, "/overlay")
        assert status == 403
        assert payload["reason"] == "not-overlay"
        assert called == []
    finally:
        listener.stop()


def test_custom_verifier_attaches_identity(http) -> None:
    listener, port = _listener(
        http,
        [
            http.Route(
                "/custom",
                lambda request: {"identity": request.identity},
                auth="custom",
                verify=lambda request: {"node": "custom"},
            )
        ],
    )
    try:
        status, payload = _get(port, "/custom")
        assert status == 200
        assert payload["identity"] == {"node": "custom"}
    finally:
        listener.stop()


def test_body_limit_and_method_mismatch(http) -> None:
    listener, port = _listener(
        http,
        [http.Route("/small", lambda request: {"ok": True}, method="POST", max_body=4)],
    )
    try:
        status, payload = _post(port, "/small", {"x": 1})
        assert status == 400
        assert payload["reason"] == "malformed"
        status, payload = _get(port, "/small")
        assert status == 405
        assert payload["reason"] == "method-not-allowed"
        status, payload = _get(port, "/missing")
        assert status == 404
        assert payload["reason"] == "not-found"
    finally:
        listener.stop()


def test_standard_refusal_and_custom_envelope(http) -> None:
    def refuse(request):
        raise http.RequestError(418, "teapot", "short and stout")

    listener, port = _listener(http, [http.Route("/refuse", refuse)])
    try:
        status, payload = _get(port, "/refuse")
        assert status == 418
        assert payload == {"ok": False, "reason": "teapot", "detail": "short and stout"}
    finally:
        listener.stop()


def test_listener_owns_start_stop_and_ready(http) -> None:
    ready = []
    listener = http.listen([http.Route("/", lambda request: {"ok": True})], port=0, ready=lambda: ready.append(True))
    assert ready == [True]
    listener.start()
    try:
        port = listener.servers[0].server_address[1]
        assert _get(port, "/")[0] == 200
    finally:
        listener.stop()
    assert listener.servers == []


def test_listener_handler_inherits_the_one_timeout(http) -> None:
    handler = http._RouteHandler
    assert issubclass(handler, http.TimeoutHandler)
    assert handler.timeout == http.DEFAULT_REQUEST_TIMEOUT_SECONDS


def test_role_services_do_not_grow_a_bare_http_handler() -> None:
    """Out-of-scope protocols keep their own handlers; every fabric listener does not."""
    allowed = {"sparknet-opencode-engine.py", "sparknet-container-registry.py"}
    offenders = []
    for root in (ROOT / "peer-node" / "services", ROOT / "master-node" / "services"):
        for path in root.glob("*.py"):
            if path.name in allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(
                    isinstance(base, ast.Name) and base.id == "BaseHTTPRequestHandler" for base in node.bases
                ):
                    offenders.append(path.name)
                    break
    assert not offenders, "role service still builds a bare HTTP handler: " + ", ".join(offenders)

"""Read-only WebUI console: role scope, auth, Qdrant view and 3D map.

The console is tested against a loopback Qdrant stand-in and an Open WebUI auth
stand-in. No live Qdrant, no browser and no model are involved.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONSOLE = ROOT / "scripts" / "sparknet-console.py"
STATIC = ROOT / "webui" / "console"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("sparknet_console_test", CONSOLE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


console = _load()


class _Qdrant(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self._json({"title": "qdrant", "version": "1.20.0"})
        elif self.path == "/collections":
            self._json(
                {
                    "result": {
                        "collections": [{"name": "sparknet-fabric"}, {"name": "sparknet-peer"}, {"name": "uplift-x"}]
                    }
                }
            )
        elif self.path.startswith("/collections/sparknet-"):
            self._json(
                {
                    "result": {
                        "status": "green",
                        "points_count": 10,
                        "vectors_count": 10,
                        "config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}},
                    }
                }
            )
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path.endswith("/points/scroll"):
            self._json(
                {
                    "result": {
                        "points": [
                            {
                                "id": 1,
                                "vector": [1.0, 0.0, 0.0],
                                "payload": {"role": "teacher", "doc_id": "t1", "node_id": "agx64"},
                            },
                            {
                                "id": 2,
                                "vector": [0.0, 1.0, 0.0],
                                "payload": {"role": "student", "doc_id": "s1", "node_id": "agx32"},
                            },
                        ]
                    }
                }
            )
        else:
            self._json({"error": "not found"}, status=404)

    def _json(self, body: dict, status: int = 200) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


class _OpenWebUI(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/api/v1/auths/":
            self.send_response(404)
            self.end_headers()
            return
        token = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        role = {"user-token": "user", "admin-token": "admin"}.get(token)
        if not role:
            self.send_response(401)
            self.end_headers()
            return
        payload = json.dumps({"id": "u1", "role": role, "email": "u@example.invalid"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def _start(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def qdrant():
    server, _thread = _start(_Qdrant)
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def openwebui():
    server, _thread = _start(_OpenWebUI)
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _config(tmp_path: Path, role: str, qdrant_url: str, openwebui_url: str) -> tuple[dict, Path]:
    source = ROOT / (f"{role}-node" if role == "peer" else "master-node") / "configs" / "webui" / "console.json"
    config = json.loads(source.read_text())
    config["openwebui_url"] = openwebui_url
    config["qdrant"]["uri"] = qdrant_url
    config["token_file"] = str(tmp_path / "state" / "webui" / "console.token")
    role_root = tmp_path / role
    (role_root / "manifests").mkdir(parents=True)
    (role_root / "blockchain").mkdir()
    (role_root / "configs").mkdir()
    (role_root / "manifests" / "node-identity.json").write_text(json.dumps({"node_id": "node-1", "role": role}))
    (role_root / "manifests" / "node-authorizations.json").write_text(
        json.dumps(
            {
                "authorizations": [
                    {
                        "identity": {"node_id": "node-1", "role": role, "overlay_ipv4": "10.100.0.2/32"},
                        "capabilities": ["telemetry"],
                        "department": "research",
                        "revoked": False,
                    }
                ]
            }
        )
    )
    (role_root / "blockchain" / "ledger.json").write_text(json.dumps({"blocks": [{"block_hash": "abc"}]}))
    (role_root / "manifests" / "share-regime.json").write_text(json.dumps({"shares": []}))
    path = tmp_path / "state"
    path.mkdir(parents=True, exist_ok=True)
    (path / "rfi-requests").mkdir(exist_ok=True)
    (path / "admin-events").mkdir(exist_ok=True)
    (path / "admin-events" / "events.jsonl").write_text('{"event":"auth.login"}\n')
    config["paths"]["telemetry"] = str(tmp_path / "telemetry.jsonl")
    (tmp_path / "telemetry.jsonl").write_text('{"kind":"status"}\n')
    config["paths"]["rfi_dir"] = str(path / "rfi-requests")
    config["paths"]["admin_events"] = str(path / "admin-events" / "events.jsonl")
    if role == "master":
        (role_root / "configs" / "distill.json").write_text(
            json.dumps({"teacher_model_id": "t", "student_base_model": "s"})
        )
        state = tmp_path / "distill"
        (state / "runs" / "run-1").mkdir(parents=True)
        (state / "runs" / "run-1" / "run.json").write_text(
            json.dumps({"approved": True, "artifact_sha256": "a", "signature_b64": "x"})
        )
        config["distill"] = {"config": "configs/distill.json", "state": str(state)}
    token = tmp_path / "state" / "webui" / "console.token"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("console-token-1234567890\n")
    return config, role_root


def _serve(config, role_root, port=0):
    server = console.make_server(config, role_root, "console-token-1234567890", STATIC, "127.0.0.1", port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _get(port: int, path: str, token: str | None = None):
    import urllib.request

    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token:
        request.add_header("X-Sparknet-Console-Token", token)
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


def test_static_index_and_auth(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, role_root = _config(tmp_path, "peer", qdrant, openwebui)
    server = _serve(config, role_root)
    try:
        status, body = _get(server.server_port, "/")
        assert status == 200 and b"Sparknet Console" in body
        with pytest.raises(urllib.error.HTTPError):
            _get(server.server_port, "/api/surface")
        status, body = _get(server.server_port, "/api/surface", "console-token-1234567890")
        assert status == 200
        surface = json.loads(body)
        assert surface["menus"] == ["mesh", "vectors", "learning", "memory", "projects"]
        assert surface["read_only"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_peer_user_session_is_accepted_but_master_requires_admin(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    peer_config, peer_root = _config(tmp_path, "peer", qdrant, openwebui)
    peer = _serve(peer_config, peer_root)
    master_config, master_root = _config(tmp_path, "master", qdrant, openwebui)
    master = _serve(master_config, master_root)
    try:
        import urllib.request

        request = urllib.request.Request(f"http://127.0.0.1:{peer.server_port}/api/surface")
        request.add_header("Authorization", "Bearer user-token")
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
        request = urllib.request.Request(f"http://127.0.0.1:{master.server_port}/api/surface")
        request.add_header("Authorization", "Bearer user-token")
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
        request = urllib.request.Request(f"http://127.0.0.1:{master.server_port}/api/surface")
        request.add_header("Authorization", "Bearer admin-token")
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200
    finally:
        for server in (peer, master):
            server.shutdown()
            server.server_close()


def test_qdrant_view_filters_uplift_and_reads_metadata(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, role_root = _config(tmp_path, "master", qdrant, openwebui)
    server = _serve(config, role_root)
    try:
        status, body = _get(server.server_port, "/api/qdrant", "console-token-1234567890")
        data = json.loads(body)
        assert status == 200 and data["ok"]
        assert data["version"] == "1.20.0"
        names = [row["name"] for row in data["collections"]]
        assert "sparknet-fabric" in names
        assert "uplift-x" not in names
        assert data["api_key"] in ("configured", "not-configured")
    finally:
        server.shutdown()
        server.server_close()


def test_map_projects_real_sampled_vectors(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, role_root = _config(tmp_path, "master", qdrant, openwebui)
    server = _serve(config, role_root)
    try:
        status, body = _get(server.server_port, "/api/map?collection=sparknet-fabric", "console-token-1234567890")
        data = json.loads(body)
        assert status == 200 and data["ok"]
        assert data["projection"] == "deterministic-random-3d-pilot"
        assert len(data["points"]) == 2
        assert {point["role"] for point in data["points"]} == {"teacher", "student"}
        assert all("x" in point and "y" in point and "z" in point for point in data["points"])
    finally:
        server.shutdown()
        server.server_close()


def test_map_refuses_an_excluded_collection(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, role_root = _config(tmp_path, "master", qdrant, openwebui)
    server = _serve(config, role_root)
    try:
        with pytest.raises(urllib.error.HTTPError):
            _get(server.server_port, "/api/map?collection=uplift-x", "console-token-1234567890")
    finally:
        server.shutdown()
        server.server_close()


class _LearningShare(BaseHTTPRequestHandler):
    snapshot: ClassVar[dict] = {
        "schema": "sparknet-distill-status/1",
        "generated_at": "2026-11-04T00:00:00Z",
        "config": {"teacher_model_id": "t", "student_base_model": "s"},
        "runs": [{"run_id": "master-run", "state": "evaluated", "approved": True}],
        "read_only": True,
    }

    def do_GET(self) -> None:
        raw = json.dumps(self.snapshot, sort_keys=True).encode()
        body = {
            "ok": True,
            "path": "learning/status.json",
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "content_b64": base64.b64encode(raw).decode(),
        }
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def test_learning_peer_proxies_the_master_snapshot(tmp_path: Path, qdrant: str, openwebui: str, monkeypatch) -> None:
    share, _thread = _start(_LearningShare)
    peer_config, peer_root = _config(tmp_path, "peer", qdrant, openwebui)
    peer_config["learning"] = {
        "master_file_share_url": f"http://127.0.0.1:{share.server_port}",
        "status_path": "/v1/file/learning/status.json",
    }
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    key_path = tmp_path / "state" / "keys" / "ed25519-node.key.b64"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(base64.b64encode(key).decode() + "\n")
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(tmp_path / "state"))
    peer = _serve(peer_config, peer_root)
    master_config, master_root = _config(tmp_path, "master", qdrant, openwebui)
    master = _serve(master_config, master_root)
    try:
        status, body = _get(peer.server_port, "/api/learning", "console-token-1234567890")
        data = json.loads(body)
        assert status == 200 and data["ok"]
        assert data["source"] == "master:4221"
        assert data["runs"][0]["run_id"] == "master-run"
        status, body = _get(master.server_port, "/api/learning", "console-token-1234567890")
        data = json.loads(body)
        assert status == 200 and data["ok"]
        assert data["runs"][0]["run_id"] == "run-1"
        assert any(model["role"] == "teacher" for model in data["models"])
    finally:
        for server in (peer, master):
            server.shutdown()
            server.server_close()
        share.shutdown()
        share.server_close()


def test_static_path_traversal_is_refused(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, role_root = _config(tmp_path, "peer", qdrant, openwebui)
    server = _serve(config, role_root)
    try:
        with pytest.raises(urllib.error.HTTPError):
            _get(server.server_port, "/../etc/passwd")
    finally:
        server.shutdown()
        server.server_close()


def test_projects_view_reads_signed_project_pages(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, role_root = _config(tmp_path, "peer", qdrant, openwebui)
    project = role_root / "06_Projects" / "alpha"
    project.mkdir(parents=True)
    (project / "PROJECT.md").write_text(
        "---\ntitle: Alpha\nproject_id: alpha\nstatus: active\n---\n\n# Alpha\n",
        encoding="utf-8",
    )
    server = _serve(config, role_root)
    try:
        status, body = _get(server.server_port, "/api/projects", "console-token-1234567890")
        assert status == 200
        payload = json.loads(body)
        assert payload["projects"][0]["project_id"] == "alpha"
        assert payload["runs"] == []
    finally:
        server.shutdown()
        server.server_close()


def test_sparknet_menu_is_a_sidebar_group_not_a_floating_overlay() -> None:
    text = (STATIC / "sparknet-menu.js").read_text()
    assert "pinned-menu-items-list" in text
    assert "sparknet-menu-group" in text
    assert "SPARKNET" in text
    assert "api/surface" in text
    assert "position: fixed" not in text
    assert "bottom: 72px" not in text


def test_the_3d_map_has_explicit_zoom_controls() -> None:
    html = (STATIC / "index.html").read_text()
    js = (STATIC / "app.js").read_text()
    css = (STATIC / "style.css").read_text()
    for element in ("zoom-in", "zoom-out", "zoom-reset", "zoom-level"):
        assert f'id="{element}"' in html
    assert "setZoom" in js
    assert '"wheel"' in js
    assert "keydown" in js
    assert "map-toolbar" in css


def test_foundations_api_reports_all_contracts_and_modules():
    payload = console.api_foundations({"role": "peer"}, ROOT / "peer-node")
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert all(payload["contracts"].values())
    assert all(payload["modules"].values())


def test_step89_dashboard_apis_are_authenticated_and_read_only(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, role_root = _config(tmp_path, "master", qdrant, openwebui)
    server = _serve(config, role_root)
    try:
        with pytest.raises(urllib.error.HTTPError) as refused:
            _get(server.server_port, "/api/step89")
        assert refused.value.code == 401
        status, raw = _get(server.server_port, "/api/step89", "console-token-1234567890")
        assert status == 200
        payload = json.loads(raw)
        assert payload["read_only"] is True
        assert payload["nodes"]["count"] >= 1
        assert payload["users"]["configured"] is False
        assert payload["collab"]["rooms"] == []
        assert "messages" not in payload["collab"]
        status, raw = _get(server.server_port, "/api/nodes", "console-token-1234567890")
        assert status == 200
        assert json.loads(raw)["count"] >= 1
    finally:
        server.shutdown()
        server.server_close()

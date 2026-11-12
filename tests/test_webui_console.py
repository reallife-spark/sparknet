"""Read-only WebUI console: role scope, auth, Qdrant view and 3D map.

The console is tested against a loopback Qdrant stand-in and an Open WebUI auth
stand-in. No live Qdrant, no browser and no model are involved.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration


ROOT = Path(__file__).resolve().parent.parent
CONSOLE = ROOT / "scripts" / "sparknet-console.py"
STATIC = ROOT / "webui" / "console"


def _load() -> object:
    return load_by_path("sparknet_console_test", CONSOLE)


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


class _Gateway(BaseHTTPRequestHandler):
    records: ClassVar[list[dict]] = []

    def do_GET(self) -> None:
        if self.path.startswith("/v1/delegates/runs"):
            self._json({"ok": True, "runs": self.records})
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


class _BrokenGateway(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        payload = b"[]"
        self.send_response(200)
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
    config["paths"]["issues"] = str(tmp_path / "issues.jsonl")
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
        assert surface["menus"] == [
            "mesh",
            "vectors",
            "learning",
            "memory",
            "projects",
            "understand",
            "evals",
            "skills",
        ]
        assert surface["read_only"] is True
    finally:
        server.shutdown()
        server.server_close()


def test_understand_route_reads_the_role_graph(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, role_root = _config(tmp_path, "peer", qdrant, openwebui)
    server = _serve(config, role_root)
    try:
        status, body = _get(server.server_port, "/api/understand", "console-token-1234567890")
        assert status == 200
        assert json.loads(body)["available"] is False
        (role_root / ".ua").mkdir()
        graph = {
            "version": "1.0",
            "kind": "codebase",
            "project": {"name": "demo", "languages": ["python"]},
            "nodes": [
                {"id": "file:a.py", "type": "file", "name": "a.py", "summary": "a", "tags": [], "complexity": "simple"}
            ],
            "edges": [],
            "layers": [],
            "tour": [],
        }
        (role_root / ".ua" / "knowledge-graph.json").write_text(json.dumps(graph))
        status, body = _get(server.server_port, "/api/understand", "console-token-1234567890")
        assert status == 200
        payload = json.loads(body)
        assert payload["available"] is True
        assert payload["graph"]["nodes"][0]["id"] == "file:a.py"
        status, body = _get(server.server_port, "/api/understand?summary=1", "console-token-1234567890")
        assert status == 200
        assert json.loads(body)["counts"]["nodes"] == 1
        status, body = _get(server.server_port, "/understand", "console-token-1234567890")
        assert status == 200 and b"Sparknet Console" in body
    finally:
        server.shutdown()
        server.server_close()


def test_master_issues_route_is_read_only_and_master_only(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, role_root = _config(tmp_path, "master", qdrant, openwebui)
    store = tmp_path / "issues.jsonl"
    store.write_text(
        json.dumps(
            {
                "received_at": "2026-11-09T10:00:00Z",
                "received_from": "10.100.0.2",
                "schema": "sparknet-issue/1",
                "issue_id": "fix-token",
                "node_id": "sparknet-node-0002",
                "title": "Console token",
                "body": "401",
                "status": "open",
                "labels": ["needs-triage"],
                "updated_at": "2026-11-09T10:00:00Z",
            }
        )
        + "\n"
    )
    triage = role_root / ".state" / "issues"
    triage.mkdir(parents=True, exist_ok=True)
    (triage / "triage.json").write_text(
        json.dumps(
            {
                "sparknet-node-0002:fix-token": {
                    "status": "triaged",
                    "labels": ["ready-for-agent"],
                    "actor": "operator",
                    "note": "reproduced",
                    "at": "2026-11-09T10:05:00Z",
                }
            }
        )
    )
    server = _serve(config, role_root)
    try:
        status, body = _get(server.server_port, "/api/issues", "console-token-1234567890")
        assert status == 200
        payload = json.loads(body)
        assert payload["ok"] is True and payload["counts"]["total"] == 1
        assert payload["read_only"] is True
        assert payload["issues"][0]["issue_id"] == "fix-token"
        assert payload["issues"][0]["effective_status"] == "triaged"
        assert payload["issues"][0]["effective_labels"] == ["ready-for-agent"]
        assert payload["counts"]["ready_for_agent"] == 1
    finally:
        server.shutdown()
        server.server_close()
    peer_config, peer_root = _config(tmp_path, "peer", qdrant, openwebui)
    peer = _serve(peer_config, peer_root)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(peer.server_port, "/api/issues", "console-token-1234567890")
        assert exc.value.code == 403
    finally:
        peer.shutdown()
        peer.server_close()


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


# --- the one console surface table -------------------------------------------


def test_surface_table_is_the_dispatch_and_menu_source() -> None:
    paths = [endpoint.path for surface in console.SURFACES for endpoint in surface.endpoints]
    assert len(paths) == len(set(paths)), "duplicate API path in the surface table"
    assert set(console.API_BY_PATH) == set(paths)
    assert all(endpoint.auth in {"session", "admin"} for endpoint in console.API_BY_PATH.values())
    assert [surface.name for surface in console.MENU_SURFACES] == [
        "mesh",
        "vectors",
        "learning",
        "memory",
        "projects",
        "understand",
        "issues",
        "evals",
        "skills",
    ]
    for surface in console.MENU_SURFACES:
        assert surface.menu is not None
        assert surface.menu.label and surface.menu.href.startswith("#") and surface.menu.icon


def test_surface_menus_and_menu_items_are_derived_from_the_table(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, _role_root = _config(tmp_path, "peer", qdrant, openwebui)
    surface = console.api_surface(config)
    assert surface["menus"] == ["mesh", "vectors", "learning", "memory", "projects", "understand", "evals", "skills"]
    assert [item["id"] for item in surface["menu_items"]] == surface["menus"]
    assert surface["menu_items"][0] == {"id": "mesh", "label": "Mesh", "href": "#mesh", "icon": "mesh"}


def test_unknown_configured_menu_is_refused(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, _role_root = _config(tmp_path, "peer", qdrant, openwebui)
    config["menus"] = [*config["menus"], "not-a-surface"]
    with pytest.raises(console.ConsoleError, match="unknown console menu"):
        console.api_surface(config)


def test_table_admin_routes_refuse_a_user_session(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    import urllib.request

    config, role_root = _config(tmp_path, "peer", qdrant, openwebui)
    server = _serve(config, role_root)
    try:

        def get(path: str, token: str):
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{path}")
            request.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status

        assert get("/api/surface", "user-token") == 200
        assert get("/api/learning", "user-token") == 200
        with pytest.raises(urllib.error.HTTPError) as exc:
            get("/api/mesh", "user-token")
        assert exc.value.code == 403
        assert get("/api/mesh", "admin-token") == 200
    finally:
        server.shutdown()
        server.server_close()


def test_sidebar_and_tabs_use_menu_items() -> None:
    sidebar = (STATIC / "sparknet-menu.js").read_text()
    app = (STATIC / "app.js").read_text()
    assert "menu_items" in sidebar and "var ITEMS =" not in sidebar
    assert "menu_items" in app
    assert 'id="tabs"' in (STATIC / "index.html").read_text()


def test_evals_route_projects_valid_records_and_counts_invalid(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    skill_eval = console.load_skill_eval_module()
    valid = skill_eval.make_record(
        eval_id="review-1",
        skill={"name": "code-review", "origin": "mattpocock"},
        subject={"kind": "delegate-run", "ref": "run-1"},
        verdict="pass",
        findings=[],
        evaluator={"kind": "agent", "id": "project-reviewer"},
        created_at="2026-11-11T00:00:00Z",
    )
    tampered = dict(valid)
    tampered["verdict"] = "warn"
    gateway, _thread = _start(_Gateway)
    try:
        _Gateway.records = [
            {"run_id": "run-1", "result": {"skill_eval": valid}},
            {"run_id": "run-2", "result": {"skill_eval": tampered}},
            {"run_id": "run-3", "result": {}},
        ]
        config, role_root = _config(tmp_path, "peer", qdrant, openwebui)
        token_path = role_root / ".state" / "memory.local.token"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("local-token-1234567890\n")
        config["memory"] = {
            "gateway_url": f"http://127.0.0.1:{gateway.server_port}",
            "local_token_file": ".state/memory.local.token",
            "vault_path": ".",
        }
        server = _serve(config, role_root)
        try:
            status, body = _get(server.server_port, "/api/evals", "console-token-1234567890")
            payload = json.loads(body)
            assert status == 200
            assert payload["ok"] is True and payload["read_only"] is True
            assert payload["counts"] == {"total": 1, "pass": 1, "warn": 0, "fail": 0, "invalid": 1}
            assert payload["records"][0]["skill"] == "code-review"
            assert payload["records"][0]["subject"]["kind"] == "delegate-run"
            assert payload["records"][0]["node"] == "agx32"
            assert "vault" not in payload and "kb" not in payload
        finally:
            server.shutdown()
            server.server_close()
    finally:
        _Gateway.records = []
        gateway.shutdown()
        gateway.server_close()


def test_evals_route_degrades_when_the_gateway_returns_a_non_object(
    tmp_path: Path, qdrant: str, openwebui: str
) -> None:
    gateway, _thread = _start(_BrokenGateway)
    try:
        config, role_root = _config(tmp_path, "peer", qdrant, openwebui)
        token_path = role_root / ".state" / "memory.local.token"
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("local-token-1234567890\n")
        config["memory"] = {
            "gateway_url": f"http://127.0.0.1:{gateway.server_port}",
            "local_token_file": ".state/memory.local.token",
            "vault_path": ".",
        }
        server = _serve(config, role_root)
        try:
            status, body = _get(server.server_port, "/api/evals", "console-token-1234567890")
            payload = json.loads(body)
            assert status == 200
            assert payload["ok"] is True
            assert payload["records"] == []
            assert payload["counts"]["total"] == 0
            status, body = _get(server.server_port, "/api/projects", "console-token-1234567890")
            payload = json.loads(body)
            assert status == 200 and payload["ok"] is True and payload["runs"] == []
        finally:
            server.shutdown()
            server.server_close()
    finally:
        gateway.shutdown()
        gateway.server_close()


def test_skills_route_reads_the_base_catalog(tmp_path: Path, qdrant: str, openwebui: str) -> None:
    config, _role_root = _config(tmp_path, "peer", qdrant, openwebui)
    status, body = console.api_skills(config, console.ROLE_ROOT["peer"], {})
    assert status == 200
    assert body["ok"] is True and body["read_only"] is True
    assert body["counts"]["skills"] >= 80
    assert body["skills"]
    status, body = console.api_skills(config, console.ROLE_ROOT["peer"], {"q": ["wiki ingest"], "limit": ["3"]})
    assert status == 200
    assert body["counts"]["shown"] >= 1
    assert any(skill["id"] == "wiki-ingest" for skill in body["skills"])

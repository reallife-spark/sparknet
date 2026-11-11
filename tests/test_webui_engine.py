"""The Open WebUI engine adapter and its workspace assets, without Docker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = ROOT / "peer-node" / "services" / "sparknet-opencode-engine.py"


def _load_engine():
    return load_by_path("sparknet_opencode_engine_test", ENGINE_PATH)


def test_engine_compiles_and_exposes_three_models():
    engine = _load_engine()
    assert engine.MODEL_AGENTS == {
        "sparknet-chat": "sparknet-chat",
        "sparknet-plan": "sparknet-plan",
        "sparknet-build": "sparknet-build",
    }
    assert engine.MODEL_LABELS["sparknet-chat"].startswith("Sparknet Chat")


def test_user_validation_refuses_path_like_ids():
    engine = _load_engine()
    assert engine._valid_user("user-1_ok") == "user-1_ok"
    for bad in ("", "../root", "a/b", "x" * 65, "space here"):
        with pytest.raises(engine.EngineError):
            engine._valid_user(bad)


def test_last_user_text_handles_text_parts():
    engine = _load_engine()
    text = engine.Engine._last_user_text(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": [{"type": "text", "text": "hello"}, {"type": "image", "url": "x"}]},
        ]
    )
    assert text == "hello"


def test_agent_mapping_refuses_unknown_models():
    engine = _load_engine()
    real = object.__new__(engine.Engine)
    assert engine.Engine._agent(real, "sparknet-plan") == "sparknet-plan"
    with pytest.raises(engine.EngineError):
        engine.Engine._agent(real, "plan")


def test_network_allocator_is_stable_and_unique(tmp_path):
    engine = _load_engine()
    allocator = engine.NetworkAllocator(tmp_path)
    first = allocator.allocate("alice")
    second = allocator.allocate("bob")
    assert first["index"] != second["index"]
    assert first["subnet"].endswith("/29")
    assert allocator.allocate("alice") == first
    reloaded = engine.NetworkAllocator(tmp_path)
    assert reloaded.allocate("bob") == second


def test_vault_for_only_accepts_the_users_peer_vault(tmp_path):
    engine = _load_engine()
    root = tmp_path / "knowledge"
    (root / "peer-alice").mkdir(parents=True)
    (root / "peer-bob").mkdir(parents=True)
    args = engine._parser().parse_args([])
    args.knowledge_root = str(root)
    args.state_root = str(tmp_path / "state")
    args.role = "peer"
    manager = engine.SandboxManager(args)
    assert manager.vault_for("alice").name == "peer-alice"
    with pytest.raises(engine.EngineError):
        manager.vault_for("bob/../alice")


def test_prompt_library_is_bilingual_and_public():
    prompts = json.loads((ROOT / "webui" / "prompts" / "sparknet-prompts.json").read_text())
    assert len(prompts) >= 12
    commands = [item["command"] for item in prompts]
    assert len(commands) == len(set(commands))
    assert {"sparknet-help", "plan", "build", "capture", "rfi", "cite", "memory", "health"} <= set(commands)
    assert {"hilfe", "plan-de", "bauen", "erfassen", "rfi-de", "zitieren", "erinnern", "status"} <= set(commands)
    for item in prompts:
        assert item["access_grants"] == [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


def test_settings_baselines_have_no_literal_secrets():
    peer = json.loads((ROOT / "webui" / "settings.peer.json").read_text())
    master = json.loads((ROOT / "webui" / "settings.master.json").read_text())
    assert peer["ui.enable_signup"] is True
    assert peer["ui.default_user_role"] == "pending"
    assert master["ui.enable_signup"] is False
    assert peer["openai.api_keys"] == ["__ENGINE_TOKEN__"]
    assert master["openai.api_keys"] == ["__ENGINE_TOKEN__"]
    assert peer["tool_server.connections"] == []
    assert master["tool_server.connections"] == []
    assert peer["openai.api_base_urls"] == ["http://127.0.0.1:4204/v1"]


def test_tools_are_self_contained_and_user_scoped():
    tools = sorted((ROOT / "webui" / "tools").glob("*.py"))
    assert {path.stem for path in tools} >= {"sparknet_vault", "sparknet_memory", "sparknet_rfi", "sparknet_status"}
    for path in tools:
        source = path.read_text()
        assert "class Tools" in source
        if path.stem != "sparknet_status":
            assert "X-Sparknet-Webui-Token" in source
            assert "X-Sparknet-User" in source


def test_runtime_assets_exist():
    assert (ROOT / "peer-node" / "configs" / "opencode-runtime" / "Dockerfile").is_file()
    assert (ROOT / "peer-node" / "configs" / "opencode-runtime" / "unix-proxy.py").is_file()
    assert (ROOT / "peer-node" / "configs" / "opencode-engine" / "opencode.json.template").is_file()
    assert (ROOT / "peer-node" / "systemd" / "sparknet-opencode-engine@.service").is_file()


def test_v2_client_uses_the_api_routes(monkeypatch):
    engine = _load_engine()
    client = engine.OpenCodeClient("http://127.0.0.1:1", "server-secret")
    calls = []

    def fake_request(method, path, body=None, timeout=600.0):
        calls.append((method, path, body))
        if path == "/api/info":
            return 200, {"version": "2.2.5"}
        if path == "/api/session":
            return 200, {"data": {"id": "ses_1"}}
        if path.endswith("/prompt"):
            return 200, {"data": {"id": "msg_1"}}
        if "/message" in path:
            return 200, {"data": [{"type": "assistant", "content": [{"type": "text", "text": "ok"}]}]}
        return 200, {}

    monkeypatch.setattr(client, "request", fake_request)
    assert client.health() is True
    session_id = client.create_session(title="chat", agent="sparknet-chat", model_id="qwen")
    assert session_id == "ses_1"
    client.prompt(session_id, "hello")
    assert client.messages(session_id)[0]["content"][0]["text"] == "ok"
    client.answer_permission(session_id, "per_1", "reject")
    client.abort(session_id)
    assert calls == [
        ("GET", "/api/info", None),
        (
            "POST",
            "/api/session",
            {"title": "chat", "agent": "sparknet-chat", "model": {"providerID": "local", "id": "qwen"}},
        ),
        ("POST", "/api/session/ses_1/prompt", {"text": "hello", "delivery": "queue"}),
        ("GET", "/api/session/ses_1/message?order=desc&type=assistant&limit=20", None),
        ("POST", "/api/session/ses_1/permission/per_1/reply", {"decision": "reject"}),
        ("POST", "/api/session/ses_1/interrupt", None),
    ]


def test_v2_client_uses_basic_auth():
    engine = _load_engine()
    client = engine.OpenCodeClient("http://127.0.0.1:1", "server-secret")
    import base64

    assert client._authorization() == "Basic " + base64.b64encode(b"opencode:server-secret").decode("ascii")


def test_sandbox_password_is_stable_and_private(tmp_path):
    engine = _load_engine()
    args = engine._parser().parse_args([])
    args.knowledge_root = str(tmp_path / "knowledge")
    args.state_root = str(tmp_path / "state")
    manager = engine.SandboxManager(args)
    first = manager.password_for("alice")
    second = manager.password_for("alice")
    assert first == second
    assert len(first) >= 32
    path = manager.user_state("alice") / "opencode-password"
    assert path.read_text().strip() == first
    assert path.stat().st_mode & 0o777 == 0o600


def test_session_key_separates_agents():
    engine = _load_engine()
    real = object.__new__(engine.Engine)
    assert engine.Engine._session_key(real, "user", "chat", "sparknet-chat") != engine.Engine._session_key(
        real, "user", "chat", "sparknet-plan"
    )


def test_render_messages_reads_v2_assistant_content():
    engine = _load_engine()
    real = object.__new__(engine.Engine)
    rendered = engine.Engine._render_messages(
        real,
        [{"type": "assistant", "content": [{"type": "text", "text": "hello"}]}],
    )
    assert rendered == "hello"
    newest = engine.Engine._render_messages(
        real,
        [
            {"type": "assistant", "content": [{"type": "text", "text": "newest"}]},
            {"type": "assistant", "content": [{"type": "text", "text": "older"}]},
        ],
    )
    assert newest == "newest"


def test_permission_events_are_routed_to_their_own_session():
    engine = _load_engine()
    real = object.__new__(engine.Engine)

    class FakeClient:
        def __init__(self):
            self.answers = []
            self.aborts = []

        def answer_permission(self, session_id, permission_id, response="reject"):
            self.answers.append((session_id, permission_id, response))

        def abort(self, session_id):
            self.aborts.append(session_id)

    client = FakeClient()
    events = engine.queue.Queue()
    events.put({"type": "permission.asked", "data": {"id": "per_other", "sessionID": "other"}})
    events.put({"type": "permission.asked", "data": {"id": "per_mine", "sessionID": "mine"}})
    events.put({"type": "session.execution.succeeded", "data": {"sessionID": "mine"}})
    engine.Engine._consume_events(real, client, "mine", events, lambda _text: None)
    assert client.answers == [("mine", "per_mine", "reject")]


def test_text_deltas_and_tool_results_are_emitted():
    engine = _load_engine()
    real = object.__new__(engine.Engine)
    emitted = []
    events = engine.queue.Queue()
    events.put(
        {
            "type": "session.text.delta",
            "data": {"sessionID": "mine", "assistantMessageID": "a1", "ordinal": 0, "delta": "hello"},
        }
    )
    events.put(
        {
            "type": "session.tool.called",
            "data": {"sessionID": "mine", "id": "tool-1", "name": "bash", "input": {"cmd": "ls"}},
        }
    )
    events.put(
        {
            "type": "session.tool.success",
            "data": {"sessionID": "mine", "id": "tool-1", "content": [{"type": "text", "text": "listed"}]},
        }
    )
    events.put({"type": "session.execution.succeeded", "data": {"sessionID": "mine"}})
    engine.Engine._consume_events(real, object(), "mine", events, emitted.append)
    assert "hello" in emitted
    assert any('name="bash"' in text and "listed" in text for text in emitted)


def test_engine_passes_the_sandbox_password_by_env_file():
    source = ENGINE_PATH.read_text()
    assert '"--env-file"' in source
    assert "str(password_env)" in source

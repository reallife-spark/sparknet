"""The Open WebUI engine adapter and its workspace assets, without Docker."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = ROOT / "peer-node" / "services" / "sparknet-opencode-engine.py"


def _load_engine():
    spec = importlib.util.spec_from_file_location("sparknet_opencode_engine_test", ENGINE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

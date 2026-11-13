"""The AGX text engine: llama-server argv, precontext, and the proxy contract.

The engine image is not the node image. These tests pin the parts that must
stay stable across the vLLM -> llama.cpp change: the historical `VLLM_*` names
map to llama-server flags, unsupported flags are never passed, the model file
is explicit, and the proxy merges the fabric precontext into chat messages
without touching any other route.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO_ROOT / "sparknet-llm-entrypoint.py"
PROXY = REPO_ROOT / "sparknet-llm-proxy.py"


@pytest.fixture()
def entrypoint(tmp_path: Path, monkeypatch):
    module = load_by_path("sparknet_llm_entrypoint_test", ENTRYPOINT)
    monkeypatch.setattr(module, "CONTEXT_DIR", tmp_path / "context")
    monkeypatch.setattr(module, "NODE_DIR", tmp_path / "peer-node")
    return module


@pytest.fixture()
def proxy(monkeypatch):
    module = load_by_path("sparknet_llm_proxy_test", PROXY)
    return module


def test_llama_args_map_the_historical_env(entrypoint, monkeypatch) -> None:
    monkeypatch.setenv("VLLM_MODEL", "qwen3.6-35b")
    monkeypatch.setenv("VLLM_MAX_MODEL_LEN", "16384")
    monkeypatch.setenv("SPARKNET_LLM_NGL", "99")
    monkeypatch.setenv("SPARKNET_LLM_PARALLEL", "2")
    monkeypatch.setenv("SPARKNET_LLM_METRICS", "1")
    monkeypatch.setenv("VLLM_EXTRA_ARGS", "--batch-size 512")
    help_text = "--parallel --cont-batching --jinja --metrics --n-gpu-layers --ctx-size --alias --threads"
    args = entrypoint._llama_args(help_text, "/models/teacher.gguf")

    assert args[:2] == ["--model", "/models/teacher.gguf"]
    assert args[args.index("--alias") + 1] == "qwen3.6-35b"
    assert args[args.index("--ctx-size") + 1] == "16384"
    assert args[args.index("--n-gpu-layers") + 1] == "99"
    assert args[args.index("--parallel") + 1] == "2"
    assert "--cont-batching" in args
    assert "--jinja" in args
    assert "--metrics" in args
    assert args[-2:] == ["--batch-size", "512"]


def test_unsupported_flags_are_not_passed(entrypoint, monkeypatch) -> None:
    monkeypatch.setenv("VLLM_MODEL", "qwen3.6-0.6b")
    monkeypatch.setenv("SPARKNET_LLM_PARALLEL", "4")
    monkeypatch.setenv("SPARKNET_LLM_METRICS", "1")
    args = entrypoint._llama_args("--model --host --port", "/models/student.gguf")
    assert "--parallel" not in args
    assert "--metrics" not in args
    assert "--jinja" not in args
    assert "--cont-batching" not in args


def test_precontext_merges_the_baked_files(entrypoint, monkeypatch, tmp_path: Path) -> None:
    context = tmp_path / "context"
    context.mkdir()
    (context / "masterspike-system-prompt.md").write_text("MASTERSPIKE", encoding="utf-8")
    (context / "fabric-digest.md").write_text("DIGEST", encoding="utf-8")
    monkeypatch.setenv("SPARKNET_PRECONTEXT", "1")
    monkeypatch.setenv("SPARKNET_LLM_PRECONTEXT_FILE", str(tmp_path / "precontext.md"))
    path = entrypoint.build_precontext()
    text = Path(path).read_text(encoding="utf-8")
    assert text.index("MASTERSPIKE") < text.index("DIGEST")
    assert "---" in text


def test_precontext_cap_is_enforced(entrypoint, monkeypatch, tmp_path: Path) -> None:
    context = tmp_path / "context"
    context.mkdir()
    (context / "masterspike-system-prompt.md").write_text("x" * 100, encoding="utf-8")
    monkeypatch.setenv("SPARKNET_PRECONTEXT", "1")
    monkeypatch.setenv("SPARKNET_PRECONTEXT_MAX_BYTES", "10")
    monkeypatch.setenv("SPARKNET_LLM_PRECONTEXT_FILE", str(tmp_path / "precontext.md"))
    path = entrypoint.build_precontext()
    assert Path(path).read_text(encoding="utf-8") == "x" * 10


def test_model_file_is_required(entrypoint, monkeypatch, capsys) -> None:
    monkeypatch.delenv("SPARKNET_LLM_MODEL_FILE", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    monkeypatch.setattr(entrypoint.shutil, "which", lambda _name: "/usr/bin/llama-server")
    with pytest.raises(SystemExit) as exc:
        entrypoint.cmd_vllm([])
    assert exc.value.code == 1
    assert "SPARKNET_LLM_MODEL_FILE" in capsys.readouterr().err


def test_proxy_prepends_or_merges_the_system_message(proxy) -> None:
    precontext = "PRECONTEXT"
    assert proxy.inject_precontext({"messages": [{"role": "user", "content": "hi"}]}, precontext)["messages"][0] == {
        "role": "system",
        "content": precontext,
    }

    existing = {"messages": [{"role": "system", "content": "caller"}, {"role": "user", "content": "hi"}]}
    merged = proxy.inject_precontext(existing, precontext)
    assert merged["messages"][0]["content"] == precontext + "\n\ncaller"

    parts = {"messages": [{"role": "system", "content": [{"type": "text", "text": "caller"}]}]}
    merged_parts = proxy.inject_precontext(parts, precontext)
    assert merged_parts["messages"][0]["content"][0] == {"type": "text", "text": precontext}
    assert merged_parts["messages"][0]["content"][1] == {"type": "text", "text": "caller"}


def test_proxy_does_not_inject_into_non_chat_payloads(proxy) -> None:
    payload = {"input": "hello"}
    assert proxy.inject_precontext(payload, "PRECONTEXT") == payload
    assert json.dumps(payload) == '{"input": "hello"}'

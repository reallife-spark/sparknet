"""The Python dispatcher behind `spark-entrypoint.sh`.

The wrapper answers `--help`; these tests exercise the argv/env construction and
the boot helpers without executing a real engine.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = REPO_ROOT / "spark-entrypoint.py"


@pytest.fixture()
def entrypoint(tmp_path: Path, monkeypatch):
    module = load_by_path("spark_entrypoint_test", ENTRYPOINT)
    monkeypatch.setattr(module, "FABRIC", tmp_path / "fabric")
    monkeypatch.setattr(module, "NODE_DIR", tmp_path / "peer-node")
    monkeypatch.setattr(module, "STATE_DIR", tmp_path / "state")
    calls: list[tuple[str, list[str]]] = []

    def fake_exec(command, args, *, env=None):
        calls.append((command, list(args)))

    monkeypatch.setattr(module, "_exec", fake_exec)
    return module, calls


def test_help_and_unknown_subcommand(entrypoint, capsys) -> None:
    module, _calls = entrypoint
    assert module.main(["--help"]) == 0
    assert "Subcommands:" in capsys.readouterr().out
    assert module.main(["not-a-command"]) == 2
    assert "unknown subcommand" in capsys.readouterr().err


def test_vllm_uses_the_modern_cli_shape(entrypoint, monkeypatch) -> None:
    module, calls = entrypoint
    monkeypatch.setenv("VLLM_MODEL", "test/model")
    monkeypatch.setenv("VLLM_PORT", "8123")
    monkeypatch.setenv("SPARKNET_PRECONTEXT", "0")
    monkeypatch.delenv("VLLM_CLI", raising=False)
    module.cmd_vllm([])
    command, args = calls[-1]
    assert command == "vllm"
    assert args[:2] == ["serve", "test/model"]
    assert "--host" in args and "0.0.0.0" in args
    assert "--port" in args and "8123" in args
    assert "--enable-prefix-caching" in args


def test_vllm_uses_model_flag_for_an_older_engine(entrypoint, monkeypatch) -> None:
    module, calls = entrypoint
    monkeypatch.setenv("VLLM_MODEL", "test/model")
    monkeypatch.setenv("VLLM_CLI", "python3 -m vllm.entrypoints.openai.api_server")
    monkeypatch.setenv("SPARKNET_PRECONTEXT", "0")
    monkeypatch.setenv("SPARKNET_MULTIMODAL", "1")
    module.cmd_vllm([])
    command, args = calls[-1]
    assert command == "python3"
    assert args[:3] == ["-m", "vllm.entrypoints.openai.api_server", "--model"]
    assert "serve" not in args
    assert "--enable-prefix-caching" not in args
    assert "--limit-mm-per-prompt" not in args


def test_gpu_and_memory_gateway_build_fixed_argv(entrypoint) -> None:
    module, calls = entrypoint
    module.cmd_gpu([])
    assert calls[-1][0] == "sparknet-gpu"
    assert "-watch" in calls[-1][1]

    module.cmd_memory_gateway([])
    command, args = calls[-1]
    assert command == module.sys.executable
    assert args[0].endswith("shared/sparknet-memory-gateway.py")
    assert "--role" in args and "--bind" in args


def test_opencode_refuses_without_a_password(entrypoint, monkeypatch) -> None:
    module, _calls = entrypoint
    monkeypatch.delenv("OPENCODE_SERVER_PASSWORD", raising=False)
    with pytest.raises(SystemExit) as exc:
        module.cmd_opencode([])
    assert exc.value.code == 1


def test_secret_is_generated_once_with_private_mode(entrypoint) -> None:
    module, _calls = entrypoint
    module.ensure_state()
    module.ensure_secret()
    secret = module.STATE_DIR / "sparknet.shared.secret"
    first = secret.read_text()
    assert len(first) == 44
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    module.ensure_secret()
    assert secret.read_text() == first


def test_master_key_fails_closed_when_a_registry_has_no_pinned_key(entrypoint, monkeypatch) -> None:
    module, _calls = entrypoint
    monkeypatch.delenv("SPARKNET_MASTER_PUB", raising=False)
    monkeypatch.setenv("GOSPARK_REGISTRY_FILE", "/tmp/registry.json")
    with pytest.raises(SystemExit) as exc:
        module.master_pub()
    assert exc.value.code == 1

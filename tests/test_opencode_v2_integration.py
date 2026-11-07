"""Certify the pinned OpenCode v2 binary against the engine adapter.

This test is opt-in: it starts a real `opencode serve` process and therefore
needs the pinned binary. Set `OPENCODE_BIN` to that binary, or run
`make -C peer-node opencode-certify`, which downloads the pin, extracts it into
a temporary directory and runs this file.

It proves the route/auth contract the engine depends on, not a model answer:
health, session creation, message listing, the SSE handshake and interruption.
"""

from __future__ import annotations

import base64
import importlib.util
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE_PATH = ROOT / "peer-node" / "services" / "sparknet-opencode-engine.py"
TEMPLATE = ROOT / "peer-node" / "configs" / "opencode-engine" / "opencode.json.template"
PASSWORD = "opencode-certify-password"


def _load_engine():
    spec = importlib.util.spec_from_file_location("sparknet_opencode_engine_integration", ENGINE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _authorization() -> str:
    token = base64.b64encode(f"opencode:{PASSWORD}".encode()).decode("ascii")
    return "Basic " + token


def _wait_for_info(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/info"
    while time.time() < deadline:
        request = urllib.request.Request(url, headers={"Authorization": _authorization()})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    raise AssertionError("the pinned OpenCode v2 server did not answer /api/info")


def test_pinned_opencode_v2_api(tmp_path):
    binary = os.environ.get("OPENCODE_BIN", "").strip()
    if not binary:
        pytest.skip("set OPENCODE_BIN to the pinned opencode binary")
    binary_path = Path(binary)
    if not binary_path.is_file():
        pytest.skip(f"OPENCODE_BIN does not exist: {binary_path}")

    engine = _load_engine()
    home = tmp_path / "home"
    home.mkdir()
    config = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("${MODEL_PROXY_URL}", "http://127.0.0.1:9/v1")
        .replace("${MODEL_ID}", "certify-model")
        .replace("${SMALL_MODEL_ID}", "certify-small")
    )
    config_path = tmp_path / "opencode.json"
    config_path.write_text(config, encoding="utf-8")

    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "OPENCODE_CONFIG": str(config_path),
            "OPENCODE_SERVER_PASSWORD": PASSWORD,
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_PURE": "1",
        }
    )
    process = subprocess.Popen(
        [str(binary_path), "serve", "--hostname", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_info(port)
        client = engine.OpenCodeClient(f"http://127.0.0.1:{port}", PASSWORD)
        assert client.health() is True
        session_id = client.create_session(title="opencode-certify")
        assert session_id.startswith("ses_")
        assert isinstance(client.messages(session_id), list)

        stream = client.event_lines()
        first = next(stream)
        stream.close()
        assert "server.connected" in first

        client.abort(session_id)

        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/info")
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=5)
        assert refused.value.code == 401
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

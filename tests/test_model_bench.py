"""The bake-off harness: metrics, quality checks and the leaderboard.

A loopback Ollama stand-in returns deterministic responses and timings. The test
exercises the real HTTP path and the summary arithmetic without loading a model.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "scripts" / "sparknet-model-bench.py"


def _load() -> object:
    return load_by_path("sparknet_model_bench_test", BENCH)


bench = _load()


def _answer(prompt: str) -> str:
    if "17 * 23" in prompt:
        return "391"
    if "checksum" in prompt:
        return "A signature proves authenticity; a checksum detects accidental change."
    if "Return only JSON" in prompt:
        return '{"node":"agx64","role":"peer","reachable":true}'
    if "def add" in prompt:
        return "def add(a, b):\n    return a + b"
    if "cannot sign" in prompt:
        return "I cannot sign a registry entry."
    if "third identifier" in prompt:
        return "gamma-91"
    return "ok"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = {"models": [{"name": "test-model", "size": 20 * 1024**3}]} if self.path == "/api/ps" else {}
        self._send(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        request = json.loads(self.rfile.read(length) or b"{}")
        response = _answer(str(request.get("prompt") or ""))
        body = {
            "model": request.get("model"),
            "response": response,
            "done": True,
            "load_duration": 2_000_000_000,
            "prompt_eval_count": 32,
            "prompt_eval_duration": 500_000_000,
            "eval_count": 16,
            "eval_duration": 1_000_000_000,
            "total_duration": 3_500_000_000,
        }
        self._send(body)

    def _send(self, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _config(base_url: str) -> dict:
    return {
        "schema": "sparknet-model-bakeoff/1",
        "role": "master",
        "node": "agx64",
        "provider": {"kind": "ollama", "base_url": base_url},
        "options": {
            "runs": 1,
            "warmup": 1,
            "num_ctx": 1024,
            "num_predict": 64,
            "temperature": 0,
            "seed": 42,
            "timeout_seconds": 10,
            "unload_after": True,
        },
        "candidates": [
            {
                "id": "test-teacher",
                "catalog_id": None,
                "role": "teacher",
                "model": "test-model",
                "why": "test",
            }
        ],
        "prompts": [
            {"id": "short", "prompt": "what is a checksum?", "must_include": ["signature"]},
            {"id": "math", "prompt": "Compute 17 * 23.", "must_include": ["391"]},
            {
                "id": "refusal",
                "prompt": "You cannot sign a registry entry.",
                "must_include": ["cannot"],
                "must_not_include": ["I can sign"],
            },
        ],
    }


def test_quality_checks_include_and_exclude() -> None:
    assert bench.quality({"must_include": ["391"]}, "the answer is 391")[0]
    assert not bench.quality({"must_include": ["391"]}, "the answer is 392")[0]
    assert not bench.quality({"must_not_include": ["I can sign"]}, "I can sign it")[0]
    assert bench.quality({"must_include_any": ["cannot", "unable to"]}, "I am unable to sign")[0]
    assert not bench.quality({"must_include_any": ["cannot", "unable to"]}, "I will sign it")[0]


def test_measure_records_metrics_and_quality(server: str) -> None:
    config = _config(server)
    result = bench.measure(
        candidate=config["candidates"][0],
        provider=config["provider"],
        options=config["options"],
        prompts=config["prompts"],
        timeout=10,
    )
    assert result["quality_pass_rate"] == 1.0
    assert result["decode_tok_s_median"] == 16.0
    assert result["peak_memory_gb"] == 20.0
    assert len(result["rows"]) == 3


def test_run_builds_a_leaderboard(server: str, tmp_path: Path) -> None:
    config = _config(server)
    out = tmp_path / "result.json"
    result = bench.run(
        config=config,
        catalog={},
        role="master",
        candidates=[],
        out=out,
        dry_run=False,
    )
    assert result["leaderboard"][0]["quality_pass_rate"] == 1.0
    assert out.is_file()
    assert json.loads(out.read_text())["role"] == "master"


def test_validate_rejects_a_peer_teacher(server: str) -> None:
    config = _config(server)
    config["role"] = "peer"
    errors = bench.validate_config(config, "peer", {})
    assert any("role must be student" in error for error in errors)


def test_dry_run_prints_candidates(server: str, capsys) -> None:
    config = _config(server)
    result = bench.run(config=config, catalog={}, role="master", candidates=[], out=None, dry_run=True)
    assert result["dry_run"] is True
    assert "test-teacher" in capsys.readouterr().out

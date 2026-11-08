"""The model puller: checksums, manifests and the disk guard.

No network is used. A loopback HTTP server stands in for the Hugging Face
resolve endpoint, so the test exercises the real urllib path, the real
checksum, the atomic rename and the manifest writer without downloading a
model.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PULL = ROOT / "scripts" / "sparknet-model-pull.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("sparknet_model_pull_test", PULL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pull = _load()
PAYLOAD = b"sparknet-model-test\n" * 128
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def resolve_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _model() -> dict:
    return {
        "id": "test-model",
        "family": "test",
        "generation": "1",
        "role": "teacher",
        "nodes": ["agx64"],
        "repo": "test/model",
        "revision": "main",
        "include": ["*.gguf"],
        "format": "gguf",
        "runtime": "llama.cpp",
        "license": "Apache-2.0",
        "license_url": "https://example.invalid/license",
        "size_gb": 1,
        "fast_memory_gb": 1,
        "context_tokens": 4096,
        "serving_port": 8100,
        "status": "candidate",
        "why": "test",
    }


def test_download_file_verifies_and_writes_atomically(tmp_path: Path, resolve_server: str) -> None:
    dest = tmp_path / "model.gguf"
    size, digest = pull.download_file(
        repo="test/model",
        revision="abc",
        remote_path="model.gguf",
        dest=dest,
        token=None,
        expected_sha=PAYLOAD_SHA,
        resolve_base=resolve_server,
    )
    assert size == len(PAYLOAD)
    assert digest == PAYLOAD_SHA
    assert dest.read_bytes() == PAYLOAD


def test_download_file_rejects_a_bad_hash(tmp_path: Path, resolve_server: str) -> None:
    with pytest.raises(pull.PullError):
        pull.download_file(
            repo="test/model",
            revision="abc",
            remote_path="model.gguf",
            dest=tmp_path / "model.gguf",
            token=None,
            expected_sha="0" * 64,
            resolve_base=resolve_server,
        )


def test_pull_model_writes_a_pinned_manifest(
    tmp_path: Path, resolve_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pull,
        "resolve_files",
        lambda model, token, api_base: [{"path": "model.gguf", "size": len(PAYLOAD), "sha256": PAYLOAD_SHA}],
    )
    monkeypatch.setattr(pull, "resolve_revision", lambda repo, revision, token, api_base: "abc123")
    manifest = pull.pull_model(
        model=_model(),
        store=tmp_path,
        node="agx64",
        min_free_gb=0,
        token=None,
        api_base="https://api.invalid",
        resolve_base=resolve_server,
        dry_run=False,
        force=False,
    )
    assert manifest["pinned"] is True
    assert manifest["resolved_revision"] == "abc123"
    assert manifest["model_file"] == "model.gguf"
    assert (tmp_path / "test-model" / "model.gguf").read_bytes() == PAYLOAD
    assert pull.verify_model(tmp_path, "test-model") == []


def test_verify_model_detects_tampering(tmp_path: Path) -> None:
    model_dir = tmp_path / "test-model"
    model_dir.mkdir()
    target = model_dir / "model.gguf"
    target.write_bytes(PAYLOAD)
    manifest = {
        "schema": "sparknet-model-manifest/1",
        "id": "test-model",
        "pinned": True,
        "files": [{"path": "model.gguf", "sha256": PAYLOAD_SHA, "size": len(PAYLOAD)}],
        "model_file": "model.gguf",
    }
    path = tmp_path / "manifests" / "test-model.json"
    path.parent.mkdir()
    path.write_text(json.dumps(manifest))
    assert pull.verify_model(tmp_path, "test-model") == []

    target.write_bytes(b"tampered")
    errors = pull.verify_model(tmp_path, "test-model")
    assert any("hash mismatch" in error for error in errors)


def test_disk_guard_refuses_an_impossible_pull(tmp_path: Path) -> None:
    with pytest.raises(pull.PullError):
        pull.disk_guard(tmp_path, 10**9)


def test_validate_catalog_rejects_duplicate_ids() -> None:
    catalog = {
        "schema_version": "1.0",
        "contract": "model-catalog",
        "store": {"root": "/mnt/ai/models", "min_free_gb": 1},
        "models": [_model(), _model()],
    }
    errors = pull.validate_catalog(catalog)
    assert any("duplicate id" in error for error in errors)


def test_model_paths_cannot_escape_the_store():
    for path in ("../escape", "/abs", "a/../../escape", ""):
        with pytest.raises(pull.PullError):
            pull.safe_relpath(path)
    assert pull.safe_relpath("sub/model.gguf") == "sub/model.gguf"

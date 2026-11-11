"""The raw-KV exporter: real file import, honest vLLM refusal."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    return load_by_path(name, path)


kv = _load("sparknet_kv_export", ROOT / "scripts" / "sparknet-kv-export.py")


def _safetensors(path: Path) -> None:
    header = json.dumps({"layers.0.k": {"dtype": "F16", "shape": [2], "data_offsets": [0, 4]}}).encode()
    path.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00" * 4)


def test_a_safetensors_file_becomes_a_manifest(tmp_path: Path):
    source = tmp_path / "kv.safetensors"
    _safetensors(source)
    manifest = kv.export(
        source=source,
        model="teacher",
        architecture="qwen2",
        layers=64,
        kv_heads=8,
        head_dim=128,
        dtype="f16",
        out=tmp_path / "spool",
    )
    assert manifest["tensor_count"] == 1
    assert manifest["sha256"]
    assert (tmp_path / "spool" / manifest["file"]).is_file()
    assert "layers.0.k" not in json.dumps(manifest)


def test_from_vllm_is_refused_until_a_connector_is_proven(capsys):
    code = kv.main(["--from-vllm", "--model", "teacher"])
    assert code == 3
    assert "not implemented" in capsys.readouterr().err

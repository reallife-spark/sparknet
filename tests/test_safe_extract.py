"""Bundle extraction refuses paths that escape the destination."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    path = ROOT / "scripts" / "sparknet-safe-extract.py"
    return load_by_path("safe_extract_test", path)


safe = _load()


def _tar(path: Path, name: str) -> Path:
    with tarfile.open(path, "w:gz") as handle:
        data = b"x"
        info = tarfile.TarInfo(name)
        info.size = len(data)
        handle.addfile(info, io.BytesIO(data))
    return path


def test_safe_extract_accepts_normal_member(tmp_path):
    archive = _tar(tmp_path / "ok.tar.gz", "bundle/file.txt")
    safe.extract(archive, tmp_path / "out")
    assert (tmp_path / "out" / "bundle" / "file.txt").read_bytes() == b"x"


def test_safe_extract_refuses_parent_escape(tmp_path):
    archive = _tar(tmp_path / "bad.tar.gz", "../escape.txt")
    with pytest.raises(SystemExit):
        safe.extract(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()

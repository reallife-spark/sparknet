"""One fixture, two implementations: the Python producer and the Go adapters.

The graph is a derived artifact. The test is a semantic comparison, not a byte
comparison of two independently maintained fixtures.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPO_ROOT / "shared" / "sparknet-understand.py"
GO_BIN = REPO_ROOT / "gospark" / "bin" / "sparknet-understand"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "understand-parity"


def _run(argv: list[str], *, cwd: Path = REPO_ROOT) -> str:
    result = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(argv)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def _json(argv: list[str]) -> dict:
    return json.loads(_run(argv))


def test_python_and_go_scan_match() -> None:
    if not GO_BIN.is_file():
        pytest.fail(f"missing {GO_BIN}; run make understand-check")
    python = _json([sys.executable, str(SHARED), "scan", "--root", str(FIXTURE)])
    go = _json(
        [
            str(GO_BIN),
            "scan",
            "--root",
            str(FIXTURE),
            "--python",
            sys.executable,
            "--shared",
            str(SHARED),
        ]
    )
    assert python["root"] == go["root"]
    assert python["files"] == go["files"]
    assert python["languages"] == go["languages"]
    assert python["errors"] == go["errors"]
    assert "ignored.py" not in {record["path"] for record in go["files"]}


def test_python_and_go_diff_match(tmp_path: Path) -> None:
    if not GO_BIN.is_file():
        pytest.fail(f"missing {GO_BIN}; run make understand-check")
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    shutil.copytree(FIXTURE, old_root)
    shutil.copytree(FIXTURE, new_root)
    with (new_root / "src" / "app.py").open("a", encoding="utf-8") as handle:
        handle.write('\n\ndef farewell(name: str) -> str:\n    return f"bye {name}"\n')

    old_graph = tmp_path / "old.json"
    new_graph = tmp_path / "new.json"
    for root, destination in ((old_root, old_graph), (new_root, new_graph)):
        _run(
            [
                sys.executable,
                str(SHARED),
                "build",
                "--root",
                str(root),
                "--out",
                str(destination),
                "--analyzed-at",
                "2026-11-10T00:00:00Z",
            ]
        )

    python = _json([sys.executable, str(SHARED), "diff", "--old", str(old_graph), "--new", str(new_graph)])
    go = _json(
        [
            str(GO_BIN),
            "diff",
            "--old",
            str(old_graph),
            "--new",
            str(new_graph),
            "--python",
            sys.executable,
            "--shared",
            str(SHARED),
        ]
    )
    assert python == go
    assert go["nodes_added"]

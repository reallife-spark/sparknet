"""The package CLI builds, verifies and plans without executing anything."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-package.py"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_package_cli_help():
    result = _run("--help")
    assert result.returncode == 0, result.stdout + result.stderr
    for command in ("manifest", "index", "sign", "verify", "plan", "install"):
        assert command in result.stdout


def test_package_cli_round_trip(tmp_path):
    app = tmp_path / "app"
    lib = tmp_path / "lib"
    (app / "bin").mkdir(parents=True)
    (lib / "bin").mkdir(parents=True)
    (app / "bin" / "tool").write_text("app", encoding="utf-8")
    (lib / "bin" / "lib").write_text("lib", encoding="utf-8")
    app_manifest = tmp_path / "app.json"
    lib_manifest = tmp_path / "lib.json"
    index = tmp_path / "index.json"

    result = _run(
        "manifest",
        "--root",
        str(app),
        "--package-id",
        "app",
        "--version",
        "1.0.0",
        "--signer",
        "master",
        "--dep",
        "lib@1.0.0",
        "--out",
        str(app_manifest),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    result = _run(
        "manifest",
        "--root",
        str(lib),
        "--package-id",
        "lib",
        "--version",
        "1.0.0",
        "--signer",
        "master",
        "--out",
        str(lib_manifest),
    )
    assert result.returncode == 0, result.stdout + result.stderr

    smaller = json.loads(app_manifest.read_text())
    assert smaller["package_id"] == "app"
    assert smaller["dependencies"] == [{"package_id": "lib", "version": "1.0.0"}]

    result = _run("verify", "--file", str(app_manifest))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["kind"] == "package"

    result = _run("index", "--package", str(app_manifest), "--package", str(lib_manifest), "--out", str(index))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["packages"] == 2

    result = _run("plan", "--index", str(index), "--root", "app@1.0.0")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == [
        {"package_id": "lib", "version": "1.0.0"},
        {"package_id": "app", "version": "1.0.0"},
    ]


def test_package_cli_skips_symlinks_and_secrets(tmp_path):
    root = tmp_path / "root"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tool").write_text("tool", encoding="utf-8")
    (root / ".env").write_text("SECRET=1", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    (root / "bin" / "link").symlink_to(outside)
    out = tmp_path / "package.json"
    result = _run(
        "manifest",
        "--root",
        str(root),
        "--package-id",
        "tool",
        "--version",
        "1.0.0",
        "--signer",
        "master",
        "--out",
        str(out),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    package = json.loads(out.read_text())
    assert [artifact["path"] for artifact in package["artifacts"]] == ["bin/tool"]

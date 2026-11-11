"""The one release export module: staging, checksums and integrity.

The two adapters (`sparknet-bundle.sh`, `sparknet-goagx-publish.sh`) used to
carry the same gitlink/``--from-git``/``SHA256SUMS`` implementation, and the
tests mirrored that policy by reading the shell source. These tests exercise
the module instead: a temporary git repo with real gitlinks proves the
worktree and from-git paths, and the integrity tests prove that a changed byte
is refused.
"""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration


ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / "scripts" / "sparknet-release-export.py"


def _load() -> object:
    return load_by_path("sparknet_release_export_test", EXPORT)


export = _load()


# --- fixtures -----------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def _submodule(tmp_path: Path, root: Path, name: str, files: dict[str, str]) -> None:
    source = tmp_path / f"{name}-source"
    source.mkdir()
    _git(source, "init", "-q", "-b", "main")
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "config", "user.name", "Test")
    for rel, text in files.items():
        _write(source / rel, text)
    _commit(source, "init")
    subprocess.run(
        ["git", "-C", str(root), "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), name],
        check=True,
        capture_output=True,
        text=True,
    )


GOAGX_ROOT_FILES = (
    "spark-entrypoint.sh",
    "spark-entrypoint.py",
    "spark-precontext.py",
    "spark.compose.cpu.yml",
    "torch-dist-l4t-compat.py",
    "spark-vllm-l4t-patch.py",
    "spark-vllm-xformers-gqa-patch.py",
    "sparknet-node-setup.sh",
    "sparknet-node-setup.py",
    "bootstrap-agx.sh",
    "spark.docker",
    "spark.compose.yml",
    ".env.example",
    ".dockerignore",
    ".gitignore",
    "USER_MANUAL.md",
)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")

    _write(root / "contracts/overlay.json", '{"contract": "overlay"}\n')
    _write(root / "shared/sparknet-authz.py", "# shared implementation\n")
    _write(root / "scripts/sparknet", "#!/usr/bin/env bash\n")
    _write(root / "scripts/sparknet-sbom.py", "#!/usr/bin/env python3\nraise SystemExit(0)\n")
    _write(root / "scripts/plugins/plugin.js", "// desktop plugin\n")
    _write(root / ".opencode/skills/base/SKILL.md", "# base skill\n")
    _write(root / ".opencode/agents/agent.md", "# agent\n")
    _write(root / "opencode.json", "{}\n")
    _write(root / "requirements.txt", "cryptography>=42\n")
    _write(root / "VERSION", "0.1.0\n")
    _write(root / "sbom/sparknet.cdx.json", "{}\n")
    for rel in GOAGX_ROOT_FILES:
        _write(root / rel, f"# {rel}\n")
    _commit(root, "main")

    _submodule(tmp_path, root, "peer-node", {"services/peer.py": "# peer\n"})
    _submodule(tmp_path, root, "master-node", {"services/master.py": "# master\n"})
    _submodule(
        tmp_path,
        root,
        "goagx",
        {
            "goagx/sparknet.agx.docker": "FROM scratch\n",
            "goagx/sparknet.agx.compose.yml": "services: {}\n",
            "goagx/GOSPARK_PIN": "GOSPARK_SHA=" + "a" * 40 + "\n",
            "goagx/README.md": "# goagx\n",
            "goagx/USER_MANUAL.md": "# manual\n",
        },
    )
    _commit(root, "submodules")
    return root


def _tree(root: Path) -> dict[str, tuple[str, str]]:
    tree: dict[str, tuple[str, str]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            tree[rel] = ("link", os.readlink(path))
        elif path.is_file():
            tree[rel] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
    return tree


# --- staging ------------------------------------------------------------------


def test_bundle_peer_worktree_stages_the_declared_surface(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    dest = tmp_path / "out"
    result = export.stage("bundle", role="peer", dest=dest, root=repo)

    assert result["dirty"] is False
    assert result["sbom_stale"] is False
    assert result["files"] > 0
    assert (dest / "peer-node/services/peer.py").is_file()
    assert (dest / "contracts/overlay.json").is_file()
    assert (dest / "shared/sparknet-authz.py").is_file()
    assert (dest / "opencode.json").is_file()
    assert (dest / "VERSION").is_file()
    assert (dest / "sbom/sparknet.cdx.json").is_file()
    assert (dest / ".opencode/skills/base/SKILL.md").is_file()
    assert not (dest / "scripts/sparknet").exists(), "fabric-root tool must be pruned"
    assert not (dest / "scripts/sparknet-sbom.py").exists(), "fabric-root tool must be pruned"
    assert not (dest / "scripts/plugins").exists(), "desktop plugin must be pruned"


def test_bundle_master_includes_the_peer_role(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    dest = tmp_path / "out"
    export.stage("bundle", role="master", dest=dest, root=repo)

    assert (dest / "master-node/services/master.py").is_file()
    assert (dest / "peer-node/services/peer.py").is_file(), "master parity loads the peer by path"


def test_goagx_worktree_stages_the_distribution_surface(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    dest = tmp_path / "out"
    result = export.stage("goagx", dest=dest, root=repo)

    assert result["surface"] == "goagx"
    assert result["role"] is None
    assert (dest / "goagx/sparknet.agx.docker").is_file()
    assert (dest / "sbom/sparknet.cdx.json").is_file()
    assert (dest / "VERSION").is_file()
    assert (dest / ".opencode/skills/base/SKILL.md").is_file()
    assert not (dest / "scripts/sparknet").exists()
    assert not (dest / "scripts/sparknet-sbom.py").exists()


def test_bundle_from_git_matches_the_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    worktree = tmp_path / "worktree"
    committed = tmp_path / "committed"
    export.stage("bundle", role="peer", dest=worktree, root=repo)
    export.stage("bundle", role="peer", source="HEAD", dest=committed, root=repo)

    assert _tree(worktree) == _tree(committed)


def test_goagx_from_git_matches_the_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    worktree = tmp_path / "worktree"
    committed = tmp_path / "committed"
    export.stage("goagx", dest=worktree, root=repo)
    export.stage("goagx", source="HEAD", dest=committed, root=repo)

    assert _tree(worktree) == _tree(committed)


def test_bundle_needs_a_role(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(export.ExportError):
        export.stage("bundle", dest=tmp_path / "out", root=repo)


def test_sbom_staleness_is_a_fact_not_a_policy(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo / "scripts/sparknet-sbom.py", "#!/usr/bin/env python3\nraise SystemExit(1)\n")
    result = export.stage("bundle", role="peer", dest=tmp_path / "out", root=repo)
    assert result["sbom_stale"] is True
    assert result["dirty"] is True, "the test changed a tracked file"


# --- integrity ----------------------------------------------------------------


def test_checksums_round_trip_and_refuse_a_changed_byte(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    dest = tmp_path / "out"
    export.stage("bundle", role="peer", dest=dest, root=repo)

    written = export.checksums(dest)
    assert written["files"] > 0
    assert export.verify_integrity(dest)["checksums"] is True

    (dest / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    with pytest.raises(export.ExportError):
        export.verify_integrity(dest)


def test_detached_signature_and_checksums_verify_together(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    dest = tmp_path / "out"
    export.stage("bundle", role="peer", dest=dest, root=repo)
    export.checksums(dest)

    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "release.key"
    pub_path = tmp_path / "release.pub"
    key_path.write_text(
        base64.b64encode(
            key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        ).decode()
        + "\n",
        encoding="utf-8",
    )
    pub_path.write_text(
        base64.b64encode(
            key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        ).decode()
        + "\n",
        encoding="utf-8",
    )
    signature = dest / "SHA256SUMS.sig"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "sparknet-sign-artifact.py"),
            "sign",
            "--file",
            str(dest),
            "--key",
            str(key_path),
            "--out",
            str(signature),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    result = export.verify_integrity(dest, signature=signature, pubkey=pub_path)
    assert result["signature"] is True
    assert result["checksums"] is True

    (dest / "VERSION").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(export.ExportError):
        export.verify_integrity(dest, signature=signature, pubkey=pub_path)

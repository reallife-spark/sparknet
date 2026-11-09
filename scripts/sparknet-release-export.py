#!/usr/bin/env python3
"""Stage a release distribution surface from the worktree or a git ref.

A release surface is a tree a node receives: the role bundle or the goagx
distribution. Both are assembled by a shell adapter, and both used to carry
their own copy of the same implementation — gitlink export, ``--from-git``
staging, ``SHA256SUMS`` and the prune policy. A fix landed in one adapter and
arrived late in the other; the tests then mirrored the policy by reading the
shell source.

This module is the one implementation. The interface is three verbs:

``stage(surface, role, source, dest)``
    Build the tree. ``source`` is ``None`` for the working tree or a git ref
    for release-grade staging. Returns the facts the adapter needs (``dirty``,
    ``sbom_stale``) rather than deciding policy: the bundle fails closed on a
    stale SBOM, the goagx adapter only warns about a dirty tree.

``checksums(dest)``
    Write ``SHA256SUMS`` over the finished tree, after the adapter has added
    its own generated files (bundle manifest, goagx README/VERSIONS).

``verify_integrity(path, signature, pubkey)``
    Verify a detached signature through ``sparknet-sign-artifact.py`` and, for
    a directory, every entry in its ``SHA256SUMS``.

The surface specifications live in ``SURFACES``. The two worktree modes are
deliberately different: a bundle ships the working tree as rsync sees it, while
the goagx distribution ships what git would commit. That difference is real and
is preserved here rather than silently erased.

Signing stays in ``sparknet-sign-artifact.py``. The module verifies signatures
and checksums; it never creates a signature and never grants anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: Working-tree excludes for the bundle surface. These are the same rules the
#: bundle carried inline; the goagx surface uses git's own view instead.
BUNDLE_EXCLUDES = (
    ".git",
    ".venv",
    "dist",
    ".state",
    ".cache",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".opencode/node_modules",
    "*.pyc",
    ".trash",
    ".env",
)

#: Fabric-root tools that must not ship: both assume a root Makefile or VERSION.
PRUNE_FILES = ("sparknet", "sparknet-sbom.py")
#: Desktop-only plugin surface.
PRUNE_DIRS = ("plugins",)

#: The closed surface vocabulary. ``bundle`` is role-scoped; ``goagx`` is not.
SURFACES: dict[str, dict[str, Any]] = {
    "bundle": {
        "role_scoped": True,
        "worktree": "rsync",
        # Role-scoped: _spec() fills the role node, the peer (for master) and
        # the shared subtrees in.
        "subtrees": (),
        "root_files": ("opencode.json", "requirements.txt"),
        "release_data": ("VERSION", "sbom/sparknet.cdx.json"),
        "from_git_root_files": ("opencode.json", "requirements.txt"),
        "from_git_release_data": ("VERSION", "sbom/sparknet.cdx.json"),
        "submodules": ("peer-node", "master-node"),
        "goagx_source": False,
    },
    "goagx": {
        "role_scoped": False,
        "worktree": "git",
        "subtrees": (
            "peer-node",
            "master-node",
            "contracts",
            "shared",
            "scripts",
            ".opencode/skills",
            ".opencode/agents",
            "goagx",
            "sbom",
        ),
        "root_files": (
            "spark-entrypoint.sh",
            "spark-precontext.py",
            "spark.compose.cpu.yml",
            "torch-dist-l4t-compat.py",
            "spark-vllm-l4t-patch.py",
            "spark-vllm-xformers-gqa-patch.py",
            "sparknet-node-setup.sh",
            "bootstrap-agx.sh",
            "spark.docker",
            "spark.compose.yml",
            ".env.example",
            ".dockerignore",
            ".gitignore",
            "opencode.json",
            "requirements.txt",
            "USER_MANUAL.md",
            "VERSION",
        ),
        "release_data": (),
        "from_git_root_files": (
            "spark-entrypoint.sh",
            "spark-precontext.py",
            "spark.compose.cpu.yml",
            "torch-dist-l4t-compat.py",
            "spark-vllm-l4t-patch.py",
            "spark-vllm-xformers-gqa-patch.py",
            "sparknet-node-setup.sh",
            "bootstrap-agx.sh",
            "spark.docker",
            "spark.compose.yml",
            ".env.example",
            ".dockerignore",
            ".gitignore",
            "opencode.json",
            "requirements.txt",
            "USER_MANUAL.md",
            "VERSION",
        ),
        "from_git_release_data": (),
        "submodules": ("peer-node", "master-node"),
        "goagx_source": True,
    },
}


class ExportError(RuntimeError):
    """A refusal the operator can act on."""


# --- small process helpers ----------------------------------------------------


def _run(argv: list[str], *, cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=capture,
        text=True,
    )


def _git(root: Path, *args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(root), *args], capture=capture)


def _git_out(root: Path, *args: str) -> str:
    proc = _git(root, *args)
    if proc.returncode != 0:
        raise ExportError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _git_file(root: Path, ref: str, rel: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{rel}"],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise ExportError(f"{rel} is missing at {ref}")
    return proc.stdout


def _ref_commit(root: Path, ref: str) -> str:
    proc = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ExportError(f"no such commit: {ref}")
    return proc.stdout.strip()


def _is_dirty(root: Path) -> bool:
    proc = _git(root, "status", "--porcelain")
    if proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


def _sbom_stale(root: Path) -> bool | None:
    """``True`` when the checked-in SBOM is stale, ``None`` when not applicable.

    The bundle adapter fails closed on this fact; the goagx adapter does not.
    The check is the existing script, not a second implementation of it.
    """
    script = root / "scripts" / "sparknet-sbom.py"
    if not script.is_file():
        return None
    venv_python = root / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.is_file() and os.access(venv_python, os.X_OK) else sys.executable
    proc = subprocess.run(
        [python, str(script), "--check"],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode != 0


# --- staging ------------------------------------------------------------------


def _copy_file(src: Path, dest: Path) -> None:
    if not src.exists() and not src.is_symlink():
        raise ExportError(f"missing required file: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest, follow_symlinks=False)


def _rsync_subtree(src: Path, dest: Path, excludes: tuple[str, ...]) -> None:
    if not src.is_dir():
        raise ExportError(f"missing required subtree: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    zones = [f"--exclude={pattern}" for pattern in excludes]
    proc = _run(["rsync", "-a", *zones, f"{src}/", f"{dest}/"])
    if proc.returncode != 0:
        raise ExportError(f"rsync failed for {src}: {proc.stderr.strip()}")


def _git_files(src_root: Path, dest_root: Path, prefix: str | None = None) -> None:
    args = ["ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    if prefix:
        args.extend(["--", prefix])
    proc = subprocess.run(
        ["git", "-C", str(src_root), *args],
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise ExportError(f"git ls-files failed in {src_root}: {proc.stderr.decode(errors='replace').strip()}")
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8")
        src = src_root / rel
        if not src.exists() and not src.is_symlink():
            continue
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            target = os.readlink(src)
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            os.symlink(target, dest)
        else:
            shutil.copy2(src, dest, follow_symlinks=False)


def _git_archive(root: Path, ref: str, paths: list[str], dest: Path, *, prefix: str | None = None) -> None:
    argv = ["git", "-C", str(root), "archive", "--format=tar"]
    if prefix:
        argv.append(f"--prefix={prefix}")
    argv.extend([ref, *paths])
    producer = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if producer.stdout is None:  # pragma: no cover - PIPE always provides a stream
        producer.kill()
        raise ExportError("git archive produced no output stream")
    consumer = subprocess.run(["tar", "-xf", "-", "-C", str(dest)], stdin=producer.stdout, check=False)
    producer.stdout.close()
    err = producer.stderr.read().decode(errors="replace") if producer.stderr else ""
    rc = producer.wait()
    if rc != 0 or consumer.returncode != 0:
        raise ExportError(f"git archive failed for {' '.join(paths)} at {ref}: {err.strip()}")


def _export_submodule(root: Path, ref: str, path: str, dest: Path) -> None:
    line = _git_out(root, "ls-tree", ref, path)
    commit = next((part.split()[2] for part in line.splitlines() if part.split()[1:2] == ["commit"]), "")
    if not commit:
        raise ExportError(f"submodule {path} is not a gitlink at {ref}")
    sub = root / path
    if not sub.is_dir():
        raise ExportError(f"submodule {path} is not initialized")
    exists = _git(sub, "cat-file", "-e", f"{commit}^{{commit}}")
    if exists.returncode != 0:
        raise ExportError(f"submodule {path} does not contain pinned commit {commit}")
    _git_archive(sub, commit, [], dest, prefix=f"{path}/")


def _export_goagx_source(root: Path, ref: str, dest: Path) -> None:
    sub = root / "goagx"
    line = _git_out(root, "ls-tree", ref, "goagx")
    commit = next((part.split()[2] for part in line.splitlines() if part.split()[1:2] == ["commit"]), "")
    if not commit:
        raise ExportError(f"goagx is not a gitlink at {ref}")
    if not sub.is_dir():
        raise ExportError("goagx submodule is not initialized")
    exists = _git(sub, "cat-file", "-e", f"{commit}^{{commit}}")
    if exists.returncode != 0:
        raise ExportError(f"goagx does not contain pinned commit {commit}")
    _git_archive(sub, commit, ["goagx"], dest)


def _prune(dest: Path) -> None:
    scripts = dest / "scripts"
    for name in PRUNE_FILES:
        (scripts / name).unlink(missing_ok=True)
    for name in PRUNE_DIRS:
        shutil.rmtree(scripts / name, ignore_errors=True)


def _count_files(dest: Path) -> int:
    return sum(1 for path in dest.rglob("*") if path.is_file() or path.is_symlink())


def _spec(surface: str, role: str | None) -> dict[str, Any]:
    if surface not in SURFACES:
        raise ExportError(f"unknown surface: {surface}")
    base = dict(SURFACES[surface])
    if not base["role_scoped"]:
        return base
    if role not in ("peer", "master"):
        raise ExportError("surface 'bundle' needs --role peer|master")
    subtrees = [f"{role}-node", "contracts", "shared", "scripts", ".opencode/skills", ".opencode/agents"]
    if role == "master":
        # The master parity loader resolves the peer's modules by path, so a
        # master bundle without the peer cannot start.
        subtrees.insert(1, "peer-node")
    base["subtrees"] = tuple(subtrees)
    base["role"] = role
    return base


def _stage_worktree(root: Path, spec: dict[str, Any], dest: Path) -> None:
    if spec["worktree"] == "rsync":
        for subtree in spec["subtrees"]:
            _rsync_subtree(root / subtree, dest / subtree, BUNDLE_EXCLUDES)
            print(f"  copied   {subtree}", file=sys.stderr)
        for rel in (*spec["root_files"], *spec["release_data"]):
            _copy_file(root / rel, dest / rel)
        return

    for subtree in spec["subtrees"]:
        if subtree in spec["submodules"]:
            _git_files(root / subtree, dest / subtree)
        elif subtree == "goagx" and spec["goagx_source"]:
            _git_files(root / "goagx", dest, prefix="goagx")
        else:
            _git_files(root, dest, prefix=subtree)
        print(f"  copied  {subtree}", file=sys.stderr)
    for rel in spec["root_files"]:
        _git_files(root, dest, prefix=rel)


def _stage_from_git(root: Path, commit: str, spec: dict[str, Any], dest: Path) -> None:
    for subtree in spec["subtrees"]:
        if subtree in spec["submodules"]:
            _export_submodule(root, commit, subtree, dest)
        elif subtree == "goagx" and spec["goagx_source"]:
            _export_goagx_source(root, commit, dest)
        else:
            _git_archive(root, commit, [subtree], dest)
        print(f"  from-git {subtree}", file=sys.stderr)

    for rel in spec["from_git_root_files"]:
        if spec["surface"] == "bundle":
            # Preserve the bundle's existing contract: its root config files
            # come from the worktree even in release-grade mode; VERSION and
            # the SBOM come from the ref.
            _copy_file(root / rel, dest / rel)
        else:
            if _git(root, "cat-file", "-e", f"{commit}:{rel}").returncode != 0:
                raise ExportError(f"root file missing at {commit}: {rel}")
            _git_archive(root, commit, [rel], dest)

    for rel in spec["from_git_release_data"]:
        data = _git_file(root, commit, rel)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def stage(
    surface: str,
    *,
    role: str | None = None,
    source: str | None = None,
    dest: str | Path,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Stage ``surface`` into ``dest`` and return the facts an adapter needs."""
    root_path = Path(root or ROOT).resolve()
    dest_path = Path(dest).resolve()
    spec = _spec(surface, role)
    spec["surface"] = surface
    if not root_path.is_dir():
        raise ExportError(f"not a directory: {root_path}")
    dest_path.mkdir(parents=True, exist_ok=True)

    if source:
        commit = _ref_commit(root_path, source)
        _stage_from_git(root_path, commit, spec, dest_path)
        dirty = False
        sbom_stale = None
    else:
        dirty = _is_dirty(root_path)
        sbom_stale = _sbom_stale(root_path)
        _stage_worktree(root_path, spec, dest_path)

    _prune(dest_path)
    return {
        "surface": surface,
        "role": role,
        "source": source or "worktree",
        "dest": str(dest_path),
        "dirty": dirty,
        "sbom_stale": sbom_stale,
        "files": _count_files(dest_path),
    }


# --- integrity ----------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksums(dest: str | Path) -> dict[str, Any]:
    """Write ``SHA256SUMS`` over every regular file but itself and ``.git``."""
    root = Path(dest).resolve()
    if not root.is_dir():
        raise ExportError(f"not a directory: {root}")
    files: list[Path] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if rel == "SHA256SUMS" or rel == ".git" or rel.startswith(".git/"):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        files.append(path)
    files.sort(key=lambda path: path.relative_to(root).as_posix().encode("utf-8"))
    lines = [f"{_sha256(path)}  {path.relative_to(root).as_posix()}\n" for path in files]
    (root / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")
    return {"dest": str(root), "files": len(files)}


def _verify_signature(path: Path, signature: Path, pubkey: Path) -> None:
    signer = Path(ROOT) / "scripts" / "sparknet-sign-artifact.py"
    argv = [
        sys.executable,
        str(signer),
        "verify",
        "--file",
        str(path),
        "--signature",
        str(signature),
        "--pubkey",
        str(pubkey),
    ]
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise ExportError(f"signature does not verify: {detail}")


def _verify_checksums(root: Path) -> int:
    sums = root / "SHA256SUMS"
    if not sums.is_file():
        raise ExportError(f"SHA256SUMS missing in {root}")
    root_resolved = root.resolve()
    checked = 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            digest, rel = line.split("  ", 1)
        except ValueError as exc:
            raise ExportError(f"malformed SHA256SUMS line: {line!r}") from exc
        target = (root / rel).resolve()
        if not target.is_relative_to(root_resolved):
            raise ExportError(f"SHA256SUMS path escapes the tree: {rel}")
        if not target.is_file():
            raise ExportError(f"SHA256SUMS names a missing file: {rel}")
        actual = _sha256(target)
        if actual != digest:
            raise ExportError(f"SHA256SUMS mismatch: {rel}")
        checked += 1
    return checked


def verify_integrity(
    path: str | Path,
    *,
    signature: str | Path | None = None,
    pubkey: str | Path | None = None,
) -> dict[str, Any]:
    """Verify a detached signature and, for a directory, its ``SHA256SUMS``."""
    target = Path(path).resolve()
    if not target.exists():
        raise ExportError(f"no such path: {target}")
    if (signature is None) != (pubkey is None):
        raise ExportError("--signature and --pubkey must be given together")
    result: dict[str, Any] = {"path": str(target), "signature": False, "checksums": None, "files": 0}
    if signature is not None and pubkey is not None:
        _verify_signature(target, Path(signature).resolve(), Path(pubkey).resolve())
        result["signature"] = True
    if target.is_dir():
        result["files"] = _verify_checksums(target)
        result["checksums"] = True
    elif signature is None:
        raise ExportError("verify-integrity needs a directory or a detached signature")
    return result


# --- CLI ----------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sparknet-release-export")
    sub = parser.add_subparsers(dest="command", required=True)

    stage_cmd = sub.add_parser("stage", help="stage a distribution surface")
    stage_cmd.add_argument("--surface", choices=sorted(SURFACES), required=True)
    stage_cmd.add_argument("--role", choices=("peer", "master"))
    stage_cmd.add_argument("--source", help="git ref; omit to stage the working tree")
    stage_cmd.add_argument("--dest", type=Path, required=True)
    stage_cmd.add_argument("--root", type=Path, help="repository root (default: the fabric root)")

    sums_cmd = sub.add_parser("checksums", help="write SHA256SUMS over a staged tree")
    sums_cmd.add_argument("--dest", type=Path, required=True)

    verify_cmd = sub.add_parser("verify-integrity", help="verify a signature and SHA256SUMS")
    verify_cmd.add_argument("--path", type=Path, required=True)
    verify_cmd.add_argument("--signature", type=Path)
    verify_cmd.add_argument("--pubkey", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "stage":
            result = stage(args.surface, role=args.role, source=args.source, dest=args.dest, root=args.root)
        elif args.command == "checksums":
            result = checksums(args.dest)
        else:
            result = verify_integrity(args.path, signature=args.signature, pubkey=args.pubkey)
    except (ExportError, OSError, subprocess.CalledProcessError) as exc:
        print(f"sparknet-release-export: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

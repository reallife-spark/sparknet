#!/usr/bin/env python3
"""Snapshot, verify, rehearse and restore a sparknet filesystem root.

Phase 9 is a *destructive* restore exercise. This tool keeps the mechanical
parts small and auditable:

- ``snapshot`` writes a tar.gz plus a JSON manifest of every regular file's
  SHA-256, at mode 0600, from one root;
- ``verify`` opens the archive without extracting, rejects absolute/``..``
  members, and checks every hash against the manifest;
- ``rehearse`` extracts to a temporary target, deletes one file, restores it
  from the archive and verifies again — the destructive step is simulated;
- ``restore`` is the live path, requires the exact confirmation phrase, and
  refuses outside the operator-moved 2026-11-01 04:00-07:00 CET window unless
  ``--now`` is supplied for a test.

The archive can contain keys (``.state/keys``). Store it on encrypted/root-only
media; the tool creates it 0600 but does not encrypt it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

PHRASE = "I ACCEPT PHASE 9 DESTRUCTIVE RESTORE ON AGX64 AGX32"
WINDOW_START = datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)  # 04:00 CET
WINDOW_END = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)  # 07:00 CET
DEFAULT_EXCLUDES = (".state/chroma", ".git", "__pycache__", ".pytest_cache", ".ruff_cache")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strip_dot(value: str) -> str:
    return value[2:] if value.startswith("./") else value


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def snapshot(root: Path, archive: Path, *, excludes: tuple[str, ...] = DEFAULT_EXCLUDES) -> Path:
    root = root.resolve()
    if not root.is_dir():
        raise SystemExit(f"snapshot: root is not a directory: {root}")
    archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive.parent.chmod(0o700)
    files: dict[str, str] = {}
    excluded = tuple(excludes)

    def _filter(info: tarfile.TarInfo):
        relative = _strip_dot(info.name)
        if any(relative == item or relative.startswith(item.rstrip("/") + "/") for item in excluded):
            return None
        return info

    fd, temporary = tempfile.mkstemp(prefix=".recovery.", dir=archive.parent, suffix=".tar.gz")
    os.close(fd)
    try:
        with tarfile.open(temporary, "w:gz") as tar:
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root).as_posix()
                if any(relative == item or relative.startswith(item.rstrip("/") + "/") for item in excluded):
                    continue
                if path.is_file() and not path.is_symlink():
                    files[relative] = _sha256(path)
                tar.add(path, arcname=relative, recursive=False, filter=_filter)
            # Add empty directories too, without hashing them.
            for path in sorted(root.rglob("*")):
                if path.is_dir():
                    relative = path.relative_to(root).as_posix()
                    if not any(relative == item or relative.startswith(item.rstrip("/") + "/") for item in excluded):
                        tar.add(path, arcname=relative, recursive=False, filter=_filter)
        os.chmod(temporary, 0o600)
        os.replace(temporary, archive)
    finally:
        leftover = Path(temporary)
        if leftover.exists():
            leftover.unlink()
    manifest = {
        "schema": "sparknet-recovery/1",
        "created_at": _utcnow().isoformat().replace("+00:00", "Z"),
        "root": str(root),
        "archive": archive.name,
        "archive_sha256": _sha256(archive),
        "files": dict(sorted(files.items())),
    }
    manifest_path = archive.with_suffix(archive.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path.chmod(0o600)
    return manifest_path


def _manifest_for(archive: Path) -> dict[str, Any]:
    path = archive.with_suffix(archive.suffix + ".json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"verify: cannot read manifest {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != "sparknet-recovery/1":
        raise SystemExit(f"verify: {path} is not a recovery manifest")
    return data


def verify(archive: Path) -> dict[str, Any]:
    manifest = _manifest_for(archive)
    if not archive.is_file():
        raise SystemExit(f"verify: archive missing: {archive}")
    digest = _sha256(archive)
    if digest != manifest.get("archive_sha256"):
        raise SystemExit("verify: archive digest does not match the manifest")
    expected = manifest.get("files") or {}
    found: dict[str, str] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not _safe_member(member.name):
                raise SystemExit(f"verify: unsafe archive member: {member.name}")
            if member.isfile():
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise SystemExit(f"verify: cannot read {member.name}")
                hasher = hashlib.sha256()
                while True:
                    chunk = extracted.read(1024 * 1024)
                    if not chunk:
                        break
                    hasher.update(chunk)
                found[_strip_dot(member.name)] = hasher.hexdigest()
    if found != expected:
        missing = sorted(set(expected) - set(found))
        extra = sorted(set(found) - set(expected))
        bad = sorted(name for name in set(expected) & set(found) if expected[name] != found[name])
        raise SystemExit(f"verify: file set mismatch (missing={missing[:3]} extra={extra[:3]} bad={bad[:3]})")
    return manifest


def _safe_link(member: tarfile.TarInfo) -> bool:
    if not (member.issym() or member.islnk()):
        return True
    parent = posixpath.dirname(member.name)
    resolved = posixpath.normpath(posixpath.join(parent, member.linkname))
    return resolved != ".." and not resolved.startswith("../") and not resolved.startswith("/")


def _extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not _safe_member(member.name):
                raise SystemExit(f"restore: unsafe archive member: {member.name}")
            if not _safe_link(member):
                raise SystemExit(f"restore: unsafe link {member.name} -> {member.linkname}")
            tar.extract(member, target)


def rehearse(archive: Path, work: Path) -> dict[str, Any]:
    manifest = verify(archive)
    if work.exists():
        shutil.rmtree(work)
    target = work / "restored"
    _extract(archive, target)
    sample = next(iter(manifest.get("files") or {}), None)
    if sample is None:
        raise SystemExit("rehearse: archive has no regular files")
    missing = target / sample
    original = missing.read_bytes()
    missing.unlink()
    _extract(archive, target)
    restored = missing.read_bytes()
    if restored != original:
        raise SystemExit(f"rehearse: {sample} did not restore byte-for-byte")
    verify(archive)
    return {"ok": True, "archive": str(archive), "sample": sample, "work": str(work)}


def _window_open(now: datetime) -> bool:
    return WINDOW_START <= now <= WINDOW_END


def restore(archive: Path, target: Path, *, confirm: str, live: bool, now: datetime | None = None) -> None:
    if confirm != PHRASE:
        raise SystemExit("restore: exact confirmation phrase required")
    if target.resolve() in (Path("/"), Path.home().resolve()):
        raise SystemExit(f"restore: refusing unsafe target {target}")
    if live and not _window_open(now or _utcnow()):
        raise SystemExit("restore: outside the approved window 2026-11-08 02:00-05:00 CET")
    verify(archive)
    _extract(archive, target)
    receipt = {
        "schema": "sparknet-recovery/1",
        "restored_at": (now or _utcnow()).isoformat().replace("+00:00", "Z"),
        "archive": str(archive),
        "target": str(target.resolve()),
        "live": live,
    }
    (target / ".sparknet-restore-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--root", type=Path, required=True)
    snap.add_argument("--out", type=Path, required=True)
    snap.add_argument("--exclude", action="append", default=list(DEFAULT_EXCLUDES))
    ver = sub.add_parser("verify")
    ver.add_argument("archive", type=Path)
    rehearse_p = sub.add_parser("rehearse")
    rehearse_p.add_argument("archive", type=Path)
    rehearse_p.add_argument("--work", type=Path, default=Path("/tmp/opencode/recovery-rehearsal"))  # noqa: S108
    rest = sub.add_parser("restore")
    rest.add_argument("archive", type=Path)
    rest.add_argument("--target", type=Path, required=True)
    rest.add_argument("--confirm", default="")
    rest.add_argument("--live", action="store_true")
    rest.add_argument("--now", help="ISO timestamp for a test; never for a live run")
    args = parser.parse_args(argv)
    if args.command == "snapshot":
        manifest = snapshot(args.root, args.out, excludes=tuple(args.exclude))
        print(json.dumps({"ok": True, "manifest": str(manifest)}, sort_keys=True))
        return 0
    if args.command == "verify":
        manifest = verify(args.archive)
        print(json.dumps({"ok": True, "files": len(manifest.get("files") or {})}, sort_keys=True))
        return 0
    if args.command == "rehearse":
        print(json.dumps(rehearse(args.archive, args.work), sort_keys=True))
        return 0
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    restore(args.archive, args.target, confirm=args.confirm, live=args.live, now=now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

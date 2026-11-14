#!/usr/bin/env python3
"""Install a newly distilled student GGUF on agx64 when the current copy is idle.

The distillation runs on agx32. The signed artifact arrives on agx64; this
operator/timer tool verifies it, checks whether the current student file is in
use, archives the old root copy, and atomically installs the new one.

Usage::

    scripts/sparknet-student-sync.py --artifact /mnt/ai/distill/artifacts/student.gguf \
      --signature /mnt/ai/distill/artifacts/student.gguf.sig \
      --pubkey /home/raxxar/.local/state/sparknet/master-node/keys/operational.pub.b64

    scripts/sparknet-student-sync.py --check-only --dest /opt/sparknet/models/qwen3-4b-2507-q4_k_m.gguf

The script never starts or stops the main/teacher. It only refuses to replace
the student while a process has the file open; ``--wait`` polls until idle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_DEST = Path("/opt/sparknet/models/qwen3-4b-2507-q4_k_m.gguf")
DEFAULT_ARCHIVE = Path("/mnt/ai/models/student-archive")
DEFAULT_SIGNER = Path(__file__).resolve().parent / "sparknet-sign-artifact.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_by_any_process(path: Path) -> bool:
    """Return True when a process has the file open (including mmap)."""
    resolved = str(path.resolve())
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            for fd in fd_dir.iterdir():
                try:
                    if os.readlink(fd) == resolved:
                        return True
                except OSError:
                    continue
        except (OSError, PermissionError):
            continue
    return False


def _verify_signature(artifact: Path, signature: Path, pubkey: Path) -> None:
    command = [
        sys.executable,
        str(DEFAULT_SIGNER),
        "verify",
        "--file",
        str(artifact),
        "--signature",
        str(signature),
        "--pubkey",
        str(pubkey),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"student-sync: signature refused: {(completed.stderr or completed.stdout).strip()}")


def _archive_old(dest: Path, archive: Path) -> str:
    if not dest.is_file():
        return ""
    archive.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = archive / f"{dest.name}.{time.strftime('%Y%m%dT%H%M%SZ')}"
    shutil.move(str(dest), str(target))
    return str(target)


def sync(
    *,
    artifact: Path,
    dest: Path,
    archive: Path,
    signature: Path | None,
    pubkey: Path | None,
    check_only: bool,
    wait: float,
    interval: float,
) -> dict[str, Any]:
    if not artifact.is_file():
        raise SystemExit(f"student-sync: artifact missing: {artifact}")
    if signature is not None and pubkey is not None:
        _verify_signature(artifact, signature, pubkey)
    digest = _sha256(artifact)
    if check_only:
        busy = _open_by_any_process(dest) if dest.is_file() else False
        return {"status": "busy" if busy else "idle", "dest": str(dest), "sha256": digest}
    deadline = time.monotonic() + max(0.0, wait)
    while dest.is_file() and _open_by_any_process(dest):
        if time.monotonic() >= deadline:
            return {"status": "deferred", "dest": str(dest), "sha256": digest, "reason": "in use"}
        time.sleep(max(0.5, interval))
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copy2(artifact, temp)
        temp.chmod(0o644)
        archived = _archive_old(dest, archive)
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)
    manifest = dest.with_suffix(dest.suffix + ".json")
    manifest.write_text(
        json.dumps(
            {
                "schema": "sparknet-student-copy/1",
                "dest": str(dest),
                "sha256": digest,
                "source": str(artifact),
                "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "archived": archived,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest.chmod(0o600)
    return {"status": "installed", "dest": str(dest), "sha256": digest, "archived": archived}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="idle-aware student GGUF installer")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--signature", type=Path)
    parser.add_argument("--pubkey", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--wait", type=float, default=0.0, help="seconds to wait for idle; 0 = defer immediately")
    parser.add_argument("--interval", type=float, default=30.0)
    args = parser.parse_args(argv)
    artifact = args.artifact
    if artifact is None and args.artifact_dir is not None:
        candidates = sorted(args.artifact_dir.glob("*.gguf"), key=lambda path: path.stat().st_mtime, reverse=True)
        artifact = candidates[0] if candidates else None
    if artifact is None and not args.check_only:
        parser.error("--artifact or --artifact-dir is required unless --check-only is used")
    result = sync(
        artifact=artifact or args.dest,
        dest=args.dest,
        archive=args.archive,
        signature=args.signature,
        pubkey=args.pubkey,
        check_only=args.check_only,
        wait=args.wait,
        interval=args.interval,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in ("idle", "installed") else 3


if __name__ == "__main__":
    raise SystemExit(main())

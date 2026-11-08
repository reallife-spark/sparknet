#!/usr/bin/env python3
"""Extract a tar archive after refusing absolute or parent-escaping members."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path, PurePosixPath


def _safe_name(name: str) -> bool:
    path = Path(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _inside(path: PurePosixPath) -> bool:
    if path.is_absolute():
        return False
    parts: list[str] = []
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return False
            parts.pop()
        else:
            parts.append(part)
    return bool(parts)


def _safe_link(member: tarfile.TarInfo) -> bool:
    if member.issym():
        return _inside(PurePosixPath(member.name).parent / PurePosixPath(member.linkname))
    return _inside(PurePosixPath(member.linkname))


def extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as handle:
        for member in handle.getmembers():
            if not _safe_name(member.name):
                raise SystemExit(f"unsafe archive member: {member.name}")
            if (member.issym() or member.islnk()) and not _safe_link(member):
                raise SystemExit(f"unsafe archive link: {member.name} -> {member.linkname}")
        handle.extractall(dest, filter="data")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="safely extract a tar archive")
    parser.add_argument("archive", type=Path)
    parser.add_argument("dest", type=Path)
    args = parser.parse_args(argv)
    extract(args.archive, args.dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

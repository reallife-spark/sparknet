"""Shared build-time mechanics for every skill family.

This module is not a runtime service and opens no network socket. It copies
files, computes the digests the manifests record, writes and reads those
manifests, and refuses host-bound paths in shipped skill content.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path

DEFAULT_IGNORED_NAMES = frozenset({"__pycache__", ".DS_Store", ".pytest_cache"})
DEFAULT_IGNORED_SUFFIXES = frozenset({".pyc", ".pyo"})

#: A host path under /home or /Users. The look-behind avoids treating a path
#: segment such as ``Application/Users/GetUserQuery.cs`` as a home directory.
HOME_PATH_RE = re.compile(r"(?<![\w.])/(?:home|Users)/([^/\s\"'`)]+)")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path | str) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _ignored(name: str, suffix: str, ignored_names: Iterable[str], ignored_suffixes: Iterable[str]) -> bool:
    return name in ignored_names or suffix in ignored_suffixes


def tree_digest(
    path: Path | str,
    *,
    ignored_names: Iterable[str] = DEFAULT_IGNORED_NAMES,
    ignored_suffixes: Iterable[str] = DEFAULT_IGNORED_SUFFIXES,
) -> tuple[str, dict[str, str]]:
    """Hash a tree and return its digest plus per-file digests.

    The hash covers ``relative-path NUL bytes NUL`` for each file, so moving or
    renaming a file changes the family digest even when its content is stable.
    """
    root = Path(path)
    names = set(ignored_names)
    suffixes = set(ignored_suffixes)
    hasher = hashlib.sha256()
    files: dict[str, str] = {}
    for file in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if _ignored(file.name, file.suffix, names, suffixes):
            continue
        rel = file.relative_to(root).as_posix()
        data = file.read_bytes()
        files[rel] = sha256_bytes(data)
        hasher.update(rel.encode())
        hasher.update(b"\0")
        hasher.update(data)
        hasher.update(b"\0")
    return hasher.hexdigest(), files


def source_digest(
    path: Path | str,
    *,
    ignored_names: Iterable[str] = DEFAULT_IGNORED_NAMES,
    ignored_suffixes: Iterable[str] = DEFAULT_IGNORED_SUFFIXES,
) -> str:
    """Hash source content by path and file digest, skipping symlinks."""
    root = Path(path)
    names = set(ignored_names)
    suffixes = set(ignored_suffixes)
    parts: list[str] = []
    for file in sorted(root.rglob("*")):
        if file.is_dir() or file.is_symlink():
            continue
        if _ignored(file.name, file.suffix, names, suffixes):
            continue
        parts.append(f"{file.relative_to(root).as_posix()}:{file_digest(file)}")
    return sha256_bytes("\n".join(parts).encode())


def source_available(path: Path | str) -> bool:
    """A source that is absent on this node is unverifiable, not drifted."""
    return Path(path).is_dir()


def read_manifest(path: Path | str, *, default: dict | None = None) -> dict | None:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value if isinstance(value, dict) else default


def write_manifest(path: Path | str, value: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prune_symlinks(root: Path | str) -> None:
    for path in sorted(Path(root).rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            path.unlink()


def copy_tree(
    src: Path | str,
    dest: Path | str,
    *,
    ignored_names: Iterable[str] = DEFAULT_IGNORED_NAMES,
    ignored_suffixes: Iterable[str] = DEFAULT_IGNORED_SUFFIXES,
    symlinks: bool = True,
    prune: bool = False,
    skip_symlinks: bool = False,
    keep: Callable[[Path, Path], bool] | None = None,
) -> tuple[int, list[str]]:
    """Copy one tree into ``dest``.

    Returns ``(files_copied, skipped_relative_paths)``. Family adapters supply
    the keep predicate; the engine owns the walk, overwrite and symlink rules.
    """
    source_root = Path(src)
    target_root = Path(dest)
    names = set(ignored_names)
    suffixes = set(ignored_suffixes)
    if target_root.exists():
        shutil.rmtree(target_root)
    files = 0
    skipped: list[str] = []
    for dirpath, dirnames, filenames in os.walk(source_root, followlinks=False):
        current = Path(dirpath)
        rel_dir = current.relative_to(source_root)
        dirnames[:] = [name for name in sorted(dirnames) if name not in names]
        if skip_symlinks:
            for name in list(dirnames):
                if (current / name).is_symlink():
                    skipped.append(str(rel_dir / name))
                    dirnames.remove(name)
        for filename in sorted(filenames):
            source = current / filename
            relative = (rel_dir / filename) if rel_dir.parts else Path(filename)
            if _ignored(filename, source.suffix, names, suffixes):
                continue
            if source.is_symlink() and skip_symlinks:
                skipped.append(str(relative))
                continue
            if keep is not None and not keep(relative, source):
                skipped.append(str(relative))
                continue
            target = target_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink() and symlinks:
                os.symlink(os.readlink(source), target)
            else:
                shutil.copy2(source, target)
            files += 1
    if prune:
        prune_symlinks(target_root)
    return files, skipped


def host_path_hits(
    root: Path | str,
    *,
    markers: Iterable[str],
    home_placeholders: Iterable[str] | None = None,
    ignored_names: Iterable[str] = DEFAULT_IGNORED_NAMES,
    ignored_suffixes: Iterable[str] = DEFAULT_IGNORED_SUFFIXES,
    include_names: Iterable[str] | None = None,
    skip_dirs: Iterable[str] = (),
    skip_parts: Iterable[str] = (),
) -> list[tuple[Path, str]]:
    """Return ``(file, matched_text)`` for host-bound content under ``root``.

    ``home_placeholders=None`` disables the home-directory regex; callers that
    list ``/home/`` or ``/Users/`` in ``markers`` do not need it. Every caller
    supplies its own marker policy; the walk and refusal shape are shared.
    """
    base = Path(root)
    names = set(ignored_names)
    suffixes = set(ignored_suffixes)
    wanted = set(include_names) if include_names is not None else None
    skipped_dirs = set(skip_dirs)
    skipped_parts = set(skip_parts)
    placeholders = {str(item).lower() for item in home_placeholders} if home_placeholders is not None else None
    hits: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(base):
        current = Path(dirpath)
        dirnames[:] = [name for name in sorted(dirnames) if name not in skipped_dirs]
        for filename in sorted(filenames):
            if wanted is not None and filename not in wanted:
                continue
            path = current / filename
            rel = path.relative_to(base)
            if skipped_parts and set(rel.parts) & skipped_parts:
                continue
            if _ignored(filename, path.suffix, names, suffixes):
                continue
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for marker in markers:
                if marker in text:
                    hits.append((path, marker))
            if placeholders is not None:
                for match in HOME_PATH_RE.finditer(text):
                    if match.group(1).lower() not in placeholders:
                        hits.append((path, match.group(0)))
    return hits

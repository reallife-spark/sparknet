#!/usr/bin/env python3
"""Sparknet secret scanning: the one portable secret detector.

This lifecycle module owns the secret-index schema constants, the tracked-file
walk, the secret-reference reader and ``scan``. The key-shaped patterns live in
``sparknet-provenance-base.py`` because the user-record check uses the same
detector; this module must not carry a second copy.

The scanner excludes its own source and the primitives source from the literal
scan: their pattern definitions would otherwise match themselves.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

_base = load_shared(
    "sparknet-provenance-base.py",
    "sparknet_provenance_base",
    error=ImportError,
    message=(
        "cannot find shared/sparknet-provenance-base.py; the provenance "
        "facade carries exactly one implementation and this scanner does not "
        "carry a fallback. Set SPARKNET_SHARED_DIR."
    ),
)
_PATTERNS = _base._PATTERNS
_state_dir = _base._state_dir

#: Fields the secret index may contain. There is deliberately no field a value
#: could hide in.
SECRET_INDEX_ENTRY_KEYS = frozenset(
    {
        "id",
        "kind",
        "holder_agent",
        "ref",
        "fingerprint",
        "scopes",
        "created",
        "last_rotated",
        "status",
        "notes",
    }
)
SECRET_INDEX_FORBIDDEN = frozenset({"value", "secret", "token", "password", "private_key"})

#: Files exempt from the literal scan: the detector itself and the primitives
#: module whose patterns it uses (their own source would match the patterns).
#: The test suite is exempt by path in ``scan``. Everything else is scanned,
#: including docs and configs.
_SCAN_EXEMPT = frozenset(
    {
        "shared/sparknet-provenance.py",
        "shared/sparknet-provenance-base.py",
        "shared/sparknet-provenance-scan.py",
    }
)


# --- secret scanning -----------------------------------------------------------


def _tracked_files(vault: Path) -> list[Path]:
    """Tracked files, or a walk when this tree has no git (an extracted bundle)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(vault), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        names = [name for name in out.stdout.decode("utf-8", "replace").split("\0") if name]
        return [vault / name for name in names]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    skip = {".git", ".state", ".cache", "__pycache__", ".venv", "dist", "node_modules"}
    suffixes = {".md", ".py", ".sh", ".json", ".yaml", ".yml", ".template", ".conf", ".txt"}
    return [
        path for path in vault.rglob("*") if path.is_file() and not skip & set(path.parts) and path.suffix in suffixes
    ]


def _resolve_secret_ref(ref: str, store: Path) -> bytes | None:
    """The value a ref names, read only to prove it appears nowhere else.

    `ref` is a path under the state dir, an absolute path, or the name of an
    environment variable — never a value. The index schema has no field one
    could put a value in; this is the only place a value is ever read.
    """
    if ref.startswith("$"):
        raw = os.environ.get(ref[1:])
        return raw.encode("utf-8") if raw else None
    path = Path(ref) if ref.startswith("/") else store / ref
    if path.is_file():
        return path.read_bytes().strip()
    return None


def scan(vault: Path) -> tuple[int, str]:
    """Fail if a secret or key-shaped literal is reachable in a tracked file."""
    findings: list[str] = []

    index_path = vault / "00_System" / "secrets-index.json"
    registered: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text())
        except json.JSONDecodeError as exc:
            return 1, f"scan: {index_path.name} is not valid JSON: {exc}"
        entries = index.get("secrets") if isinstance(index, dict) else index
        for entry in entries or []:
            if not isinstance(entry, dict):
                findings.append(f"{index_path.name}: entry is not an object")
                continue
            extra = set(entry) - SECRET_INDEX_ENTRY_KEYS
            if extra:
                findings.append(
                    f"{index_path.name}: entry {entry.get('id')} has keys outside the schema: {sorted(extra)}"
                )
            registered.append(entry)

    store = _state_dir(vault) / "secrets"
    values: dict[str, bytes] = {}
    for entry in registered:
        value = _resolve_secret_ref(str(entry.get("ref") or ""), store)
        if value:
            values[str(entry.get("id"))] = value

    files = [path for path in _tracked_files(vault) if path.is_file()]
    for path in files:
        if not path.is_relative_to(vault):
            continue
        rel = str(path.relative_to(vault))
        if rel in _SCAN_EXEMPT or "tests" in path.parts:
            continue
        # Vendored role-local skills are third-party content with upstream
        # examples that can contain key-shaped strings. Their integrity is
        # covered by the role-skill manifest; the authored-vault scan skips
        # them so an upstream detection example is not reported as our secret.
        if rel.startswith(".opencode/skills/") or "/.opencode/skills/" in rel:
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in _PATTERNS:
            match = pattern.search(text)
            if match:
                line = text[: match.start()].count("\n") + 1
                findings.append(f"{rel}:{line}: {label}")
        for secret_id, value in values.items():
            if value and value in raw:
                findings.append(f"{rel}: contains the value of registered secret {secret_id!r}")

    if findings:
        return 1, "scan: FAILED\n  " + "\n  ".join(findings)
    return (
        0,
        f"scan: clean ({len(files)} tracked files, {len(registered)} registered secret(s), no values in the vault)",
    )


__all__ = [
    "SECRET_INDEX_ENTRY_KEYS",
    "SECRET_INDEX_FORBIDDEN",
    "_SCAN_EXEMPT",
    "_resolve_secret_ref",
    "_tracked_files",
    "scan",
]

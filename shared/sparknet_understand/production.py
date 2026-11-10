#!/usr/bin/env python3
"""Scan policy and project metadata for the graph producer.

This module owns the file walk, ignore rules, language/test-path maps, binary
detection, project metadata and framework detection. It does not own graph
algebra or the wire contract.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

IGNORE_FILE = ".understandignore"


MAX_FILE_BYTES = 2_000_000


DEFAULT_EXCLUDES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".ua",
        ".understand-anything",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".state",
        ".cache",
        ".obsidian",
        "dist",
        "build",
        "target",
        "coverage",
        "htmlcov",
        "vendor",
        "third_party",
        "_staging",
        "_archives",
        "references",
    }
)


LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".go": "go",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".jsonc": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".cs": "csharp",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".scala": "scala",
    ".dart": "dart",
    ".lua": "lua",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".csv": "csv",
    ".txt": "plaintext",
}


LANGUAGE_BY_NAME: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "dockerfile": "dockerfile",
    "Makefile": "makefile",
    "makefile": "makefile",
    "GNUmakefile": "makefile",
    "Jenkinsfile": "jenkinsfile",
}


TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)|(^|/)test_[^/]+$|_test\.[A-Za-z0-9]+$|\.test\.[A-Za-z0-9]+$|\.spec\.[A-Za-z0-9]+$"
)


def is_test_path(rel_path: str) -> bool:
    return bool(TEST_PATH_RE.search(rel_path))


def language_for(rel_path: str) -> str | None:
    name = PurePosixPath(rel_path).name
    if name in LANGUAGE_BY_NAME:
        return LANGUAGE_BY_NAME[name]
    if name.startswith(".env"):
        return "env"
    if "/.github/workflows/" in f"/{rel_path}" and name.endswith((".yml", ".yaml")):
        return "github-actions"
    if name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
        return "docker-compose"
    return LANGUAGE_BY_SUFFIX.get(PurePosixPath(rel_path).suffix.lower())


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class FileRecord:
    path: str
    language: str
    sha256: str
    size: int
    mtime_ns: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "sha256": self.sha256,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
        }


@dataclass
class ScanResult:
    root: str
    files: list[FileRecord] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def languages(self) -> list[str]:
        return sorted({record.language for record in self.files})

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": [record.as_dict() for record in self.files],
            "languages": self.languages,
            "errors": self.errors,
        }


def read_ignore(root: Path) -> list[str]:
    path = root / IGNORE_FILE
    if not path.is_file():
        return []
    patterns: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _matches_any(rel_path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        candidate = pattern.lstrip("/")
        if fnmatch.fnmatch(rel_path, candidate) or fnmatch.fnmatch(PurePosixPath(rel_path).name, candidate):
            return True
        if candidate.endswith("/") and rel_path.startswith(candidate.rstrip("/") + "/"):
            return True
    return False


def is_ignored(rel_path: str, patterns: Iterable[str]) -> bool:
    """Apply gitignore-style positive/negative patterns; last match wins."""
    if not patterns:
        return False
    ignored = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        candidate = pattern[1:] if negated else pattern
        if _matches_any(rel_path, [candidate]):
            ignored = not negated
    return ignored


def scan(
    root: str | Path,
    *,
    excludes: Iterable[str] = (),
    max_bytes: int = MAX_FILE_BYTES,
) -> ScanResult:
    """Walk a tree deterministically and fingerprint every supported file."""
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(f"not a directory: {root_path}")
    ignore = [*DEFAULT_EXCLUDES, *read_ignore(root_path), *excludes]
    result = ScanResult(root=str(root_path))
    for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
        current = Path(dirpath)
        rel_dir = current.relative_to(root_path).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in DEFAULT_EXCLUDES and not is_ignored(f"{rel_dir}/{name}".lstrip("/"), ignore)
        )
        for filename in sorted(filenames):
            rel = f"{rel_dir}/{filename}".lstrip("/")
            if is_ignored(rel, ignore):
                continue
            language = language_for(rel)
            if language is None:
                continue
            path = current / filename
            try:
                stat = path.stat()
                if stat.st_size > max_bytes:
                    result.errors.append({"path": rel, "reason": "too-large"})
                    continue
                data = path.read_bytes()
            except OSError as exc:
                result.errors.append({"path": rel, "reason": f"unreadable: {exc.__class__.__name__}"})
                continue
            if _is_binary(data[:4096]):
                result.errors.append({"path": rel, "reason": "binary"})
                continue
            result.files.append(
                FileRecord(
                    path=rel,
                    language=language,
                    sha256=_sha256(data),
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                )
            )
    result.files.sort(key=lambda record: record.path)
    return result


def git_commit(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    commit = proc.stdout.strip()
    return commit if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{7,64}", commit) else ""


def _git_time(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cI"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and value else ""


def default_analyzed_at(root: str | Path) -> str:
    """Prefer a stable timestamp so an unchanged tree yields the same graph."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), tz=UTC).isoformat().replace("+00:00", "Z")
    commit_time = _git_time(Path(root))
    if commit_time:
        return commit_time
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


FRAMEWORK_SIGNALS: dict[str, tuple[str, ...]] = {
    "django": ("django", "manage.py"),
    "fastapi": ("fastapi",),
    "flask": ("flask",),
    "express": ("express",),
    "gin": ("gin-gonic/gin",),
    "nextjs": ("next",),
    "rails": ("rails",),
    "react": ("react",),
    "spring": ("spring",),
    "vue": ("vue",),
}


def detect_frameworks(root: Path, records: Iterable[FileRecord]) -> list[str]:
    """Detect frameworks from manifest files, not from guesses about code."""
    found: set[str] = set()
    paths = {record.path for record in records}
    if "manage.py" in paths:
        found.add("django")
    for manifest in ("requirements.txt", "pyproject.toml", "package.json", "go.mod", "Gemfile"):
        if manifest not in paths:
            continue
        try:
            text = (root / manifest).read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        for framework, signals in FRAMEWORK_SIGNALS.items():
            if any(signal in text for signal in signals):
                found.add(framework)
    return sorted(found)


def project_meta(
    root: Path,
    records: Iterable[FileRecord],
    *,
    analyzed_at: str | None = None,
    description: str = "",
) -> dict[str, Any]:
    records = list(records)
    return {
        "name": root.name or "project",
        "languages": sorted({record.language for record in records}),
        "frameworks": detect_frameworks(root, records),
        "description": description or f"Code-understanding graph for {root.name or 'this project'}",
        "analyzedAt": analyzed_at or default_analyzed_at(root),
        "gitCommitHash": git_commit(root),
    }

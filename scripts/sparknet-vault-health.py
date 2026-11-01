#!/usr/bin/env python3
"""Diagnose a vault, and repair only what is derived and safe.

The vault is useful when it stays organized. This tool is the conservative half
of that promise: it checks structure, shims, identity files, generated context,
provenance and obvious duplicates, writes a small health report, and repairs
only the skeleton and the generated context. It never forces a signature, moves
a user page, edits the ledger or writes a protected file. Those issues are
reported for a human or for Plan → Permission → Execute.

Usage::

    scripts/sparknet-vault-health.py --root peer-node
    scripts/sparknet-vault-health.py --root peer-node --repair
    scripts/sparknet-vault-health.py --root peer-node --json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
NUMBERED = (
    "00_System",
    "01_Inbox",
    "02_Daily",
    "03_Sources",
    "04_Evergreen",
    "05_Knowledge",
    "06_Projects",
    "07_Archives",
)
LEGACY = {
    "concepts": "05_Knowledge/concepts",
    "entities": "05_Knowledge/entities",
    "skills": "05_Knowledge/skills",
    "synthesis": "05_Knowledge/synthesis",
    "journal": "02_Daily",
    "sessions": "02_Daily",
    "references": "03_Sources",
    "_raw": "03_Sources",
    "projects": "06_Projects",
    "_archives": "07_Archives",
    "index.md": "00_System/index.md",
    "log.md": "00_System/log.md",
}
IDENTITY = ("AGENTS.md", "CONTEXT.md", "MISSION.md", "INTENT.md", "MEMORY.md", "PLAN.md")


def _run(command: list[str], cwd: Path | None = None) -> tuple[int, str]:
    completed = subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def role_of(root: Path) -> str:
    if root.name == "peer-node":
        return "peer"
    if root.name == "master-node":
        return "master"
    return "fabric"


ROLE_TREES = {
    ".git",
    ".opencode",
    ".pytest_cache",
    ".state",
    "__pycache__",
    "agents",
    "blockchain",
    "configs",
    "container",
    "deployment",
    "dist",
    "docs",
    "evidence-repo",
    "manifests",
    "plans",
    "scripts",
    "services",
    "systemd",
    "tests",
}


def page_paths(root: Path) -> list[Path]:
    pages: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if path.is_symlink() or any(part in ROLE_TREES for part in rel.parts):
            continue
        if any(part in {"_staging", "_archives"} for part in rel.parts):
            continue
        pages.append(path)
    return pages


def diagnose(root: Path) -> dict[str, Any]:
    role = role_of(root)
    issues: list[str] = []
    warnings: list[str] = []

    for name in NUMBERED:
        if not (root / name).is_dir():
            issues.append(f"missing directory {name}/")
    for name in ("concepts", "entities", "skills", "synthesis"):
        if not (root / "05_Knowledge" / name).is_dir():
            issues.append(f"missing directory 05_Knowledge/{name}/")

    for legacy, target in LEGACY.items():
        path = root / legacy
        if not path.is_symlink():
            issues.append(f"{legacy} is not a symlink to {target}")
        elif os.readlink(path) != target:
            issues.append(f"{legacy} points at {os.readlink(path)}, expected {target}")

    for name in IDENTITY:
        if not (root / name).is_file():
            issues.append(f"missing identity file {name}")

    context_rc, _context_out = _run(
        [
            sys.executable,
            str(ROOT_DIR / "scripts" / "sparknet-context-pack.py"),
            "--root",
            str(root),
            "--role",
            role,
            "--check",
        ]
    )
    if context_rc != 0:
        issues.append("CONTEXT.md is stale or missing")

    prov_rc, prov_out = _run(
        [sys.executable, str(ROOT_DIR / "shared" / "sparknet-provenance.py"), "--vault", str(root), "verify"]
    )
    if prov_rc != 0:
        issues.append("provenance verification failed")
        if prov_out:
            warnings.append(prov_out.splitlines()[-1])

    shim_rc, _ = _run(
        [sys.executable, str(ROOT_DIR / "shared" / "sparknet-provenance.py"), "--vault", str(root), "shims"]
    )
    if shim_rc != 0:
        issues.append("legacy shim verification failed")

    pages = page_paths(root)
    curated = [
        path
        for path in pages
        if len(path.relative_to(root).parts) == 1
        or path.relative_to(root).parts[0] in {"00_System", "02_Daily", "04_Evergreen", "05_Knowledge", "06_Projects"}
    ]
    basenames = Counter(path.name for path in curated)
    duplicates = sorted(name for name, count in basenames.items() if count > 1)
    if duplicates:
        warnings.append("duplicate page basenames: " + ", ".join(duplicates[:10]))

    allowed_root = set(IDENTITY) | {"README.md", "USER_MANUAL.md", "CONTEXT.md"}
    for path in pages:
        rel = path.relative_to(root)
        if len(rel.parts) == 1 and rel.name not in allowed_root:
            warnings.append(f"root page outside the governance set: {rel.name}")

    hot = root / "hot.md"
    if hot.is_file():
        try:
            text = hot.read_text(encoding="utf-8", errors="replace")[:400]
            line = next((ln for ln in text.splitlines() if ln.startswith("updated:")), "")
            updated = line.split(":", 1)[1].strip() if line else ""
            if updated:
                age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(updated).date()).days
                if age > 7:
                    warnings.append(f"hot.md is {age} days old")
        except (OSError, ValueError):
            warnings.append("hot.md has no parseable updated date")

    return {
        "role": role,
        "root": str(root),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "pages": len(pages),
        "issues": issues,
        "warnings": warnings,
        "status": "healthy" if not issues else "needs-attention",
    }


def repair(root: Path) -> list[str]:
    """Run only the safe repairs: skeleton/shims and the generated context."""
    actions: list[str] = []
    env_init = ROOT_DIR / "scripts" / "sparknet-env-init.sh"
    rc, out = _run(["bash", str(env_init), str(root)])
    if rc == 0:
        actions.append("env-init: skeleton and shims")
    else:
        actions.append(f"env-init failed: {out.splitlines()[-1] if out else 'unknown'}")
    rc, out = _run(
        [
            sys.executable,
            str(ROOT_DIR / "scripts" / "sparknet-context-pack.py"),
            "--root",
            str(root),
            "--role",
            role_of(root),
        ]
    )
    if rc == 0:
        actions.append("context-pack: CONTEXT.md regenerated")
    else:
        actions.append(f"context-pack failed: {out.splitlines()[-1] if out else 'unknown'}")
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose and safely repair a sparknet vault")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit 1 when issues remain")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"sparknet-vault-health: not a directory: {root}", file=sys.stderr)
        return 1
    actions = repair(root) if args.repair else []
    report = diagnose(root)
    report["repairs"] = actions
    report["status"] = "healthy" if not report["issues"] else "needs-attention"

    out = root / "00_System" / "vault-health.json"
    try:
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"sparknet-vault-health: cannot write {out}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{report['role']}: {report['status']} ({report['pages']} pages)")
        for issue in report["issues"]:
            print(f"  issue:   {issue}")
        for warning in report["warnings"]:
            print(f"  warning: {warning}")
        for action in actions:
            print(f"  repaired: {action}")
    if args.strict and report["issues"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Enforce the shape of the governance set so it cannot silently regrow.

The five files have one job each. This gate checks that they exist, stay inside
their line budget, keep the required sections, and do not leak deployment state
back into a template. It also checks that the generated context is current and
that the role templates have not drifted apart.

Usage::

    scripts/sparknet-governance-check.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALL_SCOPES = {
    "fabric": ROOT,
    "peer": ROOT / "peer-node",
    "master": ROOT / "master-node",
}
# A standalone role bundle carries one role, not the fabric root. The gate must
# run there too, so it checks the scopes that actually exist and never invents
# a missing role as a failure.
SCOPES = {
    name: path
    for name, path in ALL_SCOPES.items()
    if path.is_dir() and (path / "MISSION.md").is_file() and (path / "AGENTS.md").is_file()
}
BUDGETS = {
    "fabric": {"MISSION.md": 60, "INTENT.md": 90, "AGENTS.md": 150, "MEMORY.md": 60, "PLAN.md": 600},
    "peer": {"MISSION.md": 60, "INTENT.md": 90, "AGENTS.md": 150, "MEMORY.md": 60, "PLAN.md": 600},
    "master": {"MISSION.md": 60, "INTENT.md": 90, "AGENTS.md": 180, "MEMORY.md": 60, "PLAN.md": 600},
}
REQUIRED = {
    "MISSION.md": ("## Scope", "## Success", "## Non-goals"),
    "INTENT.md": ("## Invariants",),
    "AGENTS.md": ("## Memory Protocol", "## Plan Protocol"),
    "MEMORY.md": ("## Durable facts",),
}
STATUS_IN_PROSE = re.compile(r"\b(partially-built|not yet running|spec-only status)\b", re.I)


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def check_scope(role: str, root: Path) -> list[str]:
    failures: list[str] = []
    for name, budget in BUDGETS[role].items():
        path = root / name
        if not path.is_file():
            failures.append(f"{path.relative_to(ROOT)} is missing")
            continue
        text = path.read_text(encoding="utf-8")
        lines = len(text.splitlines())
        if lines > budget:
            failures.append(f"{path.relative_to(ROOT)} is {lines} lines; budget is {budget}")
        if name in REQUIRED:
            for heading in REQUIRED[name]:
                if heading not in text:
                    failures.append(f"{path.relative_to(ROOT)} is missing section {heading!r}")
        if name in {"MISSION.md", "AGENTS.md"}:
            body = text.split("\n---", 1)[-1] if text.startswith("---\n") else text
            if STATUS_IN_PROSE.search(body):
                failures.append(f"{path.relative_to(ROOT)} carries live status in prose")
        if "/mnt/knowledge" in text:
            failures.append(f"{path.relative_to(ROOT)} hard-codes the development path")
    return failures


def check_master_plan() -> list[str]:
    failures: list[str] = []
    if "master" not in SCOPES:
        return failures
    if not (SCOPES["master"] / "PLAN.md").is_file():
        failures.append("master-node/PLAN.md is missing")
    legacy = SCOPES["master"] / "plans" / "MASTER_BUILD_PLAN.md"
    if not legacy.is_symlink():
        failures.append("master-node/plans/MASTER_BUILD_PLAN.md is not a compatibility symlink")
    return failures


def check_context() -> list[str]:
    failures: list[str] = []
    for role, root in SCOPES.items():
        command = [
            sys.executable,
            str(ROOT / "scripts" / "sparknet-context-pack.py"),
            "--root",
            str(root),
            "--role",
            role,
            "--check",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            failures.append(f"{role} CONTEXT.md is stale")
    return failures


def check_templates() -> list[str]:
    failures: list[str] = []
    if "peer" not in SCOPES or "master" not in SCOPES:
        return failures
    peer = ROOT / "peer-node" / "deployment" / "vault-template"
    master = ROOT / "master-node" / "deployment" / "vault-template"
    for rel in (
        "00_System/index.md",
        "00_System/log.md",
        "00_System/schema.yaml",
        "00_System/secrets-index.json",
        "00_System/user.md",
        "README.md",
    ):
        a, b = peer / rel, master / rel
        if not a.is_file() or not b.is_file():
            failures.append(f"vault template is missing {rel}")
            continue
        if a.read_bytes() != b.read_bytes():
            failures.append(f"vault-template drift: {rel}")
    if not (peer / "00_System" / "platform.md").is_file() or not (master / "00_System" / "platform.md").is_file():
        failures.append("both vault templates must ship platform.md")
    return failures


def main() -> int:
    failures: list[str] = []
    if not SCOPES:
        print("sparknet-governance-check: no role scope found", file=sys.stderr)
        return 1
    for role, root in SCOPES.items():
        failures.extend(check_scope(role, root))
    failures.extend(check_master_plan())
    failures.extend(check_context())
    failures.extend(check_templates())
    if failures:
        print("sparknet-governance-check: FAILED", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("sparknet-governance-check: governance set is within budget and current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

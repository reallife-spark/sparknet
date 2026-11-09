#!/usr/bin/env python3
"""Verify the authored Understand-Anything skill family.

The nine `/understand*` skills are a Sparknet translation of the upstream
Understand-Anything workflows. They call the fabric's Python/Go graph tool
instead of the upstream TypeScript packages, so they are authored here rather
than copied verbatim. This script pins their bytes, records the upstream
provenance and refuses a host absolute path or a missing skill.

Usage:
    scripts/sync-understand-skills.py --apply   record the current bytes
    scripts/sync-understand-skills.py --check   fail if the family drifted
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEST = REPO_ROOT / ".opencode" / "skills"
STATE = DEST / ".understand.json"

UPSTREAM = "https://github.com/Egonex-AI/Understand-Anything"
UPSTREAM_COMMIT = "a6ea4024767df85ce4f99140d4f12ecfc5a81eb6"
UPSTREAM_VERSION = "2.9.8"
LICENSE = "MIT"

SKILLS = (
    "understand",
    "understand-knowledge",
    "understand-dashboard",
    "understand-chat",
    "understand-diff",
    "understand-domain",
    "understand-explain",
    "understand-figma",
    "understand-onboard",
)

HOST_MARKERS = ("/mnt/", "/home/", "/Users/", "/opt/raxxar", "/srv/raxxar")


def digest_tree(path: Path) -> tuple[str, dict[str, str]]:
    hasher = hashlib.sha256()
    files: dict[str, str] = {}
    for file in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        rel = file.relative_to(path).as_posix()
        data = file.read_bytes()
        files[rel] = hashlib.sha256(data).hexdigest()
        hasher.update(rel.encode())
        hasher.update(b"\0")
        hasher.update(data)
        hasher.update(b"\0")
    return hasher.hexdigest(), files


def apply_mode() -> int:
    state: dict[str, object] = {
        "schema": "sparknet-skill-family/1",
        "upstream": UPSTREAM,
        "upstream_commit": UPSTREAM_COMMIT,
        "upstream_version": UPSTREAM_VERSION,
        "license": LICENSE,
        "note": (
            "Authored translation of the upstream workflows; helper commands call "
            "shared/sparknet-understand.py and the Go service."
        ),
        "skills": {},
    }
    skills: dict[str, object] = {}
    for name in SKILLS:
        skill_dir = DEST / name
        if not (skill_dir / "SKILL.md").is_file():
            sys.exit(f"understand skill missing: {skill_dir.relative_to(REPO_ROOT)}")
        digest, files = digest_tree(skill_dir)
        skills[name] = {"sha256": digest, "files": files}
        print(f"  pinned {name}")
    state["skills"] = skills
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {STATE.relative_to(REPO_ROOT)}")
    return 0


def check_mode() -> int:
    if not STATE.is_file():
        print("no .understand.json — run --apply first", file=sys.stderr)
        return 1
    state = json.loads(STATE.read_text(encoding="utf-8"))
    recorded = state.get("skills", {})
    problems: list[str] = []
    if state.get("upstream_commit") != UPSTREAM_COMMIT:
        problems.append("upstream commit changed; review the translation before re-pinning")
    if state.get("license") != LICENSE:
        problems.append("license changed; review the provenance")
    present = {path.name for path in DEST.iterdir() if path.is_dir()}
    for missing in sorted(set(SKILLS) - present):
        problems.append(f"{missing}: skill directory is gone")
    for extra in sorted(
        {name for name in present if name == "understand" or name.startswith("understand-")} - set(SKILLS)
    ):
        problems.append(f"{extra}: unregistered understand-* skill (add it to SKILLS or remove it)")
    for name in SKILLS:
        meta = recorded.get(name)
        if not isinstance(meta, dict):
            problems.append(f"{name}: not recorded in .understand.json")
            continue
        digest, files = digest_tree(DEST / name)
        if digest != meta.get("sha256"):
            problems.append(f"{name}: bytes drifted from .understand.json")
        if files != meta.get("files"):
            problems.append(f"{name}: file set changed")
        for file in sorted(candidate for candidate in (DEST / name).rglob("*") if candidate.is_file()):
            try:
                text = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for marker in HOST_MARKERS:
                if marker in text:
                    problems.append(f"{file.relative_to(REPO_ROOT)}: host absolute path {marker}")
    if problems:
        print("understand skill family is stale:", file=sys.stderr)
        for problem in problems:
            print(f"  ✗ {problem}", file=sys.stderr)
        print("\nRun scripts/sync-understand-skills.py --apply after reviewing the change.", file=sys.stderr)
        return 1
    print(f"understand skills match .understand.json ({len(SKILLS)} skills)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="record the current skill bytes")
    group.add_argument("--check", action="store_true", help="verify the recorded bytes")
    args = parser.parse_args()
    return apply_mode() if args.apply else check_mode()


if __name__ == "__main__":
    raise SystemExit(main())

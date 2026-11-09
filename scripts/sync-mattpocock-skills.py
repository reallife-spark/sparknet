#!/usr/bin/env python3
"""Vendor and pin the Matt Pocock engineering skill family.

The family lives in `.opencode/skills/` beside the wiki suite so every workspace
loads one portable tree. `sync-role-skills.py` then propagates the same names to
the peer and master role catalogs. The source is the local `skillx` checkout
(the repo's logical name is `skills`); a node without the farm can still use the
committed copy, and `--check` verifies the committed bytes.

Usage:
    scripts/sync-mattpocock-skills.py --apply
    scripts/sync-mattpocock-skills.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEST = REPO_ROOT / ".opencode" / "skills"
STATE = DEST / ".mattpocock.json"
DEFAULT_SOURCE = Path(os.environ.get("SPARKNET_MATTPOCOCK_SOURCE", "/mnt/nvme/github/skillx/skills"))
FALLBACK_SOURCE = REPO_ROOT / "master-node" / ".opencode" / "skills"

UPSTREAM = "https://github.com/mattpocock/skills"
LICENSE = "MIT"

SKILLS = (
    "ask-matt",
    "chief-of-staff",
    "claude-handoff",
    "code-review",
    "codebase-design",
    "diagnosing-bugs",
    "domain-modeling",
    "git-guardrails-claude-code",
    "grill-me",
    "grill-with-docs",
    "grilling",
    "handoff",
    "implement",
    "implement-spec",
    "improve-codebase-architecture",
    "loop-me",
    "migrate-to-shoehorn",
    "pr",
    "prototype",
    "research",
    "retro",
    "scaffold-exercises",
    "setup-matt-pocock-skills",
    "setup-pre-commit",
    "setup-ts-deep-modules",
    "tdd",
    "teach",
    "to-questionnaire",
    "to-spec",
    "to-tickets",
    "triage",
    "wait-what",
    "wayfinder",
    "wizard",
    "writing-beats",
    "writing-for-agents",
    "writing-fragments",
    "writing-shape",
)

HOST_MARKERS = ("/mnt/", "/home/", "/Users/", "/opt/raxxar", "/srv/raxxar")
DESCRIPTION_OVERRIDES = {
    # Upstream is a one-liner (29 chars); the opencode loader needs a description
    # that says what the skill does and when to use it.
    "pr": "Draft, review and open a pull request with a scoped diff, a test note and linked issues.",
}
IGNORED = {"__pycache__", ".DS_Store", ".pytest_cache"}


def digest_tree(path: Path) -> tuple[str, dict[str, str]]:
    hasher = hashlib.sha256()
    files: dict[str, str] = {}
    for file in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        if file.name in IGNORED or file.suffix in {".pyc", ".pyo"}:
            continue
        rel = file.relative_to(path).as_posix()
        data = file.read_bytes()
        files[rel] = hashlib.sha256(data).hexdigest()
        hasher.update(rel.encode())
        hasher.update(b"\0")
        hasher.update(data)
        hasher.update(b"\0")
    return hasher.hexdigest(), files


def source_for(name: str) -> Path | None:
    if DEFAULT_SOURCE.is_dir():
        matches = sorted(DEFAULT_SOURCE.rglob(f"{name}/SKILL.md"))
        if matches:
            return matches[0].parent
    fallback = FALLBACK_SOURCE / name
    return fallback if (fallback / "SKILL.md").is_file() else None


def upstream_commit() -> str:
    if not DEFAULT_SOURCE.is_dir():
        return ""
    try:
        proc = subprocess.run(
            ["git", "-C", str(DEFAULT_SOURCE.parent), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def copy_skill(name: str, source: Path) -> None:
    target = DEST / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*IGNORED, "*.pyc", "*.pyo"), symlinks=False)


def apply_mode() -> int:
    state: dict[str, object] = {
        "schema": "sparknet-skill-family/1",
        "upstream": UPSTREAM,
        "upstream_commit": upstream_commit(),
        "license": LICENSE,
        "source": str(DEFAULT_SOURCE) if DEFAULT_SOURCE.is_dir() else "master-node/.opencode/skills",
        "skills": {},
    }
    skills: dict[str, object] = {}
    for name in SKILLS:
        source = source_for(name)
        if source is None:
            sys.exit(f"mattpocock skill missing: {name}")
        copy_skill(name, source)
        if name in DESCRIPTION_OVERRIDES:
            skill_md = DEST / name / "SKILL.md"
            text = skill_md.read_text(encoding="utf-8")
            text = re.sub(r"(?m)^description:.*$", f'description: "{DESCRIPTION_OVERRIDES[name]}"', text, count=1)
            skill_md.write_text(text, encoding="utf-8")
        digest, files = digest_tree(DEST / name)
        skills[name] = {
            "sha256": digest,
            "files": files,
            "source": str(source.relative_to(REPO_ROOT)) if source.is_relative_to(REPO_ROOT) else str(source),
            "license": LICENSE,
        }
        print(f"  vendored {name}")
    state["skills"] = skills
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {STATE.relative_to(REPO_ROOT)}")
    return 0


def check_mode() -> int:
    if not STATE.is_file():
        print("no .mattpocock.json — run --apply first", file=sys.stderr)
        return 1
    state = json.loads(STATE.read_text(encoding="utf-8"))
    recorded = state.get("skills", {})
    problems: list[str] = []
    if set(recorded) != set(SKILLS):
        problems.append("manifest does not name exactly the vendored mattpocock family")
    present = {path.name for path in DEST.iterdir() if path.is_dir()}
    for missing in sorted(set(SKILLS) - present):
        problems.append(f"{missing}: skill directory is gone")
    for name in SKILLS:
        meta = recorded.get(name)
        if not isinstance(meta, dict):
            problems.append(f"{name}: not recorded")
            continue
        digest, files = digest_tree(DEST / name)
        if digest != meta.get("sha256"):
            problems.append(f"{name}: bytes drifted from .mattpocock.json")
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
        if not (DEST / name / "SKILL.md").is_file():
            problems.append(f"{name}: SKILL.md missing")
    if problems:
        print("mattpocock skill family is stale:", file=sys.stderr)
        for problem in problems:
            print(f"  ✗ {problem}", file=sys.stderr)
        print("\nRun scripts/sync-mattpocock-skills.py --apply after reviewing the change.", file=sys.stderr)
        return 1
    print(f"mattpocock skills match .mattpocock.json ({len(SKILLS)} skills)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="vendor the family and record its bytes")
    group.add_argument("--check", action="store_true", help="verify the recorded bytes")
    args = parser.parse_args()
    return apply_mode() if args.apply else check_mode()


if __name__ == "__main__":
    raise SystemExit(main())

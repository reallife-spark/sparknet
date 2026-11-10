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
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_catalog import engine

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
    engine.copy_tree(
        source,
        DEST / name,
        ignored_names=IGNORED,
        ignored_suffixes={".pyc", ".pyo"},
        symlinks=False,
    )


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
        digest, files = engine.tree_digest(DEST / name, ignored_names=IGNORED, ignored_suffixes={".pyc", ".pyo"})
        skills[name] = {
            "sha256": digest,
            "files": files,
            "source": str(source.relative_to(REPO_ROOT)) if source.is_relative_to(REPO_ROOT) else str(source),
            "license": LICENSE,
        }
        print(f"  vendored {name}")
    state["skills"] = skills
    engine.write_manifest(STATE, state)
    print(f"wrote {STATE.relative_to(REPO_ROOT)}")
    return 0


def check_mode() -> int:
    state = engine.read_manifest(STATE)
    if state is None:
        print("no .mattpocock.json — run --apply first", file=sys.stderr)
        return 1
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
        digest, files = engine.tree_digest(DEST / name, ignored_names=IGNORED, ignored_suffixes={".pyc", ".pyo"})
        if digest != meta.get("sha256"):
            problems.append(f"{name}: bytes drifted from .mattpocock.json")
        if files != meta.get("files"):
            problems.append(f"{name}: file set changed")
        for file, marker in engine.host_path_hits(
            DEST / name,
            markers=HOST_MARKERS,
            ignored_names=IGNORED,
            ignored_suffixes={".pyc", ".pyo"},
            home_placeholders=None,
        ):
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

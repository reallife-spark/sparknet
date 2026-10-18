#!/usr/bin/env python3
"""Vendor the wiki skill suite into this repository.

Why vendor at all: the suite lives in a machine-global skill farm that a DGX
Spark node does not have. A node must be able to run `/wiki-status`,
`/wiki-ingest`, `/wiki-query` and the rest from a bare clone, so the skills
travel *with* the vault rather than being discovered from outside it.

Layout: `<repo>/.opencode/skills/<name>/SKILL.md` — opencode's project-skill
location. Deliberately NOT `<repo>/skills/`, which is a vault category for
how-to pages, a different thing entirely.

Usage:
    scripts/sync-wiki-skills.py --apply    copy + patch, prune stale skills
    scripts/sync-wiki-skills.py --check    fail if dest drifted from source

The exclusion list below is the deliberate decision about what does NOT ship.
It is data, not policy buried in a loop: adding a host-bound skill to a node
means deleting one line here, deliberately, with the reason on record.

Local modifications to upstream files live in
`scripts/wiki-skill-patches/*.patch` and are applied after copying, so the
difference from upstream is reviewable in git rather than invisible.
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
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEST = REPO_ROOT / ".opencode" / "skills"
PATCH_DIR = REPO_ROOT / "scripts" / "wiki-skill-patches"
SYNC_STATE = DEST / ".sync.json"

DEFAULT_SOURCE = "/mnt/nvme/skills/wiki"
UPSTREAM_REPO = "https://github.com/Ar9av/obsidian-wiki"
UPSTREAM_COMMIT = "ec2b6bc"
UPSTREAM_LICENSE = "MIT"

# Skills that must not ship to a node, each for a stated reason. All four read
# state that only exists on the development cluster; shipping them would give a
# node commands that can only ever fail, and their presence would imply the
# node has agent histories to mine.
EXCLUSIONS: dict[str, str] = {
    "rlspark-sourcewatch": (
        "raxxar-local (not upstream); hard-codes /mnt/knowledge/raxxar and "
        "drives the RLSpark dossier workflow, which is this cluster's project"
    ),
    "memory-bridge": (
        "reads per-tool agent histories (~/.codex, ~/.claude, ...); a node running opencode has none of those sources"
    ),
    "wiki-agent": ("targeted search over per-tool agent histories; same missing sources as memory-bridge"),
    "wiki-history-ingest": ("ingests per-tool agent histories; same missing sources as memory-bridge"),
}

# Skills read from git rather than from a working tree. `skill-creator` is the
# case that forces this: both the farm copy AND the upstream checkout have 29+
# sibling skills symlinked inside it, forming a 40-deep self-symlink chain that
# is *untracked* (`??` in git status) — local damage, not upstream content. Only
# 18 files are actually tracked there. Reading from git gets those 18 and
# nothing else, which is the only reliable way to copy that skill.
GIT_SOURCES: dict[str, tuple[str, str]] = {
    "skill-creator": ("/mnt/nvme/github/obsidian-wiki", ".skills/skill-creator"),
}

# Skills authored in this repository, not vendored from the farm or upstream.
# A local skill has no source to copy and no upstream to drift against, so
# `--apply` must never prune it, `--check` must accept it at face value, and
# opencode bundles it from the same `.opencode/skills/` tree as the vendored
# suite. The dir lives here in the repo: `.opencode/skills/<name>/SKILL.md`.
LOCAL_SKILLS: set[str] = {
    "wiki-audit",
}

# Farm directory names that are vendored under a *different* dest name. Used
# when sparknet renames an upstream skill rather than patching its content.
# Key: farm source dir. Value: name recorded in .sync.json and on disk.
RENAMES: dict[str, str] = {
    "obsidian-bases": "orchestrator-bases",
    "obsidian-cli": "orchestrator-cli",
    "obsidian-markdown": "orchestrator-markdown",
}

IGNORED_NAMES = {"__pycache__", ".DS_Store", ".pytest_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}

# Paths that must never appear in a vendored skill: a skill that names a host
# path silently breaks on a node. Deliberately specific — a generic "/Users/" or
# "/home/" rule would fire on the documentation's own placeholder examples
# (`/Users/me/.claude/...`), which are correct and must stay.
HOST_PATH_MARKERS = (
    "/mnt/knowledge/",
    "/mnt/nvme/",
    "/opt/raxxar",
    "/home/raxxar",
    "/srv/raxxar",
)
# `/home/x` and `/Users/x` are host paths only when x is not a placeholder.
HOME_PLACEHOLDERS = {
    "me",
    "name",
    "you",
    "your",
    "user",
    "username",
    "someone",
    "somebody",
    "u",
    "x",
    "example",
    "test",
    "default",
    "nobody",
}
HOME_PATH_RE = re.compile(r"/(?:home|Users)/([^/\s\"'`]+)")


def skill_dirs() -> list[str]:
    """Names of the farm's skills, ignoring symlink farms and non-skill dirs."""
    if not SOURCE.is_dir():
        sys.exit(f"skill source not found: {SOURCE}")
    return sorted(p.name for p in SOURCE.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def copy_skill(name: str, src: Path, dest: Path) -> None:
    """Copy one skill, skipping symlinks and build noise.

    `symlinks=True` copies a symlink as a symlink instead of traversing it,
    which is what keeps a polluted source (see GIT_SOURCES) from being followed
    into a 40-deep loop. Any symlink that does land in the copy is then unlinked,
    because a vendored skill must be self-contained.
    """
    target = dest / name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        src,
        target,
        ignore=shutil.ignore_patterns(*IGNORED_NAMES, "*.pyc", "*.pyo"),
        symlinks=True,
    )
    prune_symlinks(target)


def prune_symlinks(root: Path) -> None:
    """Remove every symlink under `root`, deepest first."""
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink():
            path.unlink()


def copy_skill_from_git(name: str, repo: Path, relpath: str, dest: Path) -> None:
    """Copy a skill using only git-tracked files.

    `git archive` reads the committed tree, so untracked local damage in the
    checkout cannot leak into the vendored copy.
    """
    if not (repo / ".git").exists():
        sys.exit(f"not a git repository: {repo}")
    target = dest / name
    if target.exists():
        shutil.rmtree(target)
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            ["git", "-C", str(repo), "archive", "--format=tar", "HEAD", relpath],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            sys.exit(f"git archive failed for {name}: {proc.stderr.decode(errors='replace')}")
        tar_path = Path(tmp) / "skill.tar"
        tar_path.write_bytes(proc.stdout)
        extract = subprocess.run(
            ["tar", "-xf", str(tar_path), "-C", tmp],
            capture_output=True,
            check=False,
        )
        if extract.returncode != 0:
            sys.exit(f"tar extract failed for {name}: {extract.stderr.decode(errors='replace')}")
        staged = Path(tmp) / relpath
        if not (staged / "SKILL.md").is_file():
            sys.exit(f"{name}: git archive produced no SKILL.md")
        shutil.copytree(
            staged,
            target,
            ignore=shutil.ignore_patterns(*IGNORED_NAMES, "*.pyc", "*.pyo"),
            symlinks=True,
        )
    prune_symlinks(target)


def apply_patches(name: str, quiet: bool = False) -> list[str]:
    patch = PATCH_DIR / f"{name}.patch"
    if not patch.is_file():
        return []
    proc = subprocess.run(
        ["patch", "-p1", "--forward", "--silent", "-i", str(patch)],
        cwd=DEST,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.exit(
            f"patch for {name!r} did not apply — upstream changed?\n"
            f"{proc.stdout}\n{proc.stderr}\n"
            f"Re-read scripts/wiki-skill-patches/{name}.patch and regenerate it."
        )
    if not quiet:
        print(f"  patched {name}")
    return [str(patch.relative_to(REPO_ROOT))]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# The word "Obsidian" in the vendored suite names the markdown editor this
# vault no longer goes by. When sparknet rebrands the suite, prose naming the
# editor becomes prose naming the orchestrator. Four things are deliberately
# left alone because they are real external artifacts, not sparknet prose:
#   * `.obsidian/`            — the editor's config directory (a folder name)
#   * `Obsidian CLI`          — the external command-line tool some skills drive
#   * `https://help.obsidian.md` etc. — the editor's documentation URLs
#   * `obsidian-wiki`         — the upstream repository this suite is vendored from
# Renames are ordered: whole skill names first, then phrases, then the bare
# editor word with guards against `.obsidian`, `Obsidian CLI` and URL hosts.
DIALECT_RENAMES = (
    ("obsidian-cli", "orchestrator-cli"),
    ("obsidian-markdown", "orchestrator-markdown"),
    ("obsidian-bases", "orchestrator-bases"),
    ("Obsidian Bases", "orchestrator Bases"),
    ("Obsidian Vault", "orchestrator Vault"),
)
# Bare word rewrite. `(?<![.\w-])` kills `.obsidian` (URL host, config dir)
# and `obsidian-wiki`; `(?! CLI)` protects the external tool name.
DIALECT_WORD = re.compile(r"(?<![.\w-])Obsidian\b(?! CLI)")


def dialect_rewrite(text: str) -> str:
    """Apply the sparknet dialect to vendored skill content.

    Conservative by design: only the editor's name is rebranded. The renames
    above touch whole skill names and product phrases; the word rule rewrites
    bare "Obsidian" when it stands alone as the editor's name, with explicit
    guards for the external artifacts listed above.
    """
    for old, new in DIALECT_RENAMES:
        text = text.replace(old, new)
    return DIALECT_WORD.sub("orchestrator", text)


def dialect_rewrite_tree(root: Path) -> None:
    """Apply the dialect to every text file under `root`, in place."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in IGNORED_NAMES or path.suffix in IGNORED_SUFFIXES:
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        rewritten = dialect_rewrite(text)
        if rewritten != text:
            path.write_text(rewritten)


def source_digest(name: str, src: Path) -> str:
    """Hash a source skill: every tracked file plus its relative path."""
    parts: list[str] = []
    for path in sorted(src.rglob("*")):
        if path.is_dir() or path.is_symlink():
            continue
        if path.name in IGNORED_NAMES or path.suffix in IGNORED_SUFFIXES:
            continue
        parts.append(f"{path.relative_to(src).as_posix()}:{digest(path)}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def skill_dirs_on_disk() -> list[Path]:
    return sorted(p for p in DEST.iterdir() if p.is_dir())


def find_host_paths() -> list[str]:
    """Report vendored SKILL CONTENT that still names a host absolute path.

    Scoped to the skill directories on purpose. The provenance README at the top
    of this directory legitimately cites where the suite came from
    (`/mnt/nvme/skills/wiki`), and flagging that would make the check
    unsatisfiable — it would also hide a real hit among the noise.
    """
    hits: list[str] = []
    for skill_root in skill_dirs_on_disk():
        paths = sorted(skill_root.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            if path.name in IGNORED_NAMES or path.suffix in IGNORED_SUFFIXES:
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for marker in HOST_PATH_MARKERS:
                if marker in text:
                    hits.append(f"{path.relative_to(DEST)}: {marker}")
            for match in HOME_PATH_RE.finditer(text):
                user = match.group(1)
                if user.lower() not in HOME_PLACEHOLDERS:
                    hits.append(f"{path.relative_to(DEST)}: {match.group(0)}")
    return hits


def apply_mode() -> None:
    included = [n for n in skill_dirs() if n not in EXCLUSIONS]
    included += [n for n in GIT_SOURCES if n not in included]
    included += [n for n in LOCAL_SKILLS if n not in included]

    DEST.mkdir(parents=True, exist_ok=True)
    print(f"source : {SOURCE}")
    print(f"dest   : {DEST.relative_to(REPO_ROOT)}")
    print(f"ship   : {len(included)} skills")
    for name, reason in EXCLUSIONS.items():
        print(f"  skip {name:<22} {reason}")
    for name in sorted(LOCAL_SKILLS):
        print(f"  local {name:<22} authored in-repo, not vendored")

    state: dict[str, object] = {
        "upstream": UPSTREAM_REPO,
        "upstream_commit": UPSTREAM_COMMIT,
        "license": UPSTREAM_LICENSE,
        "source": str(SOURCE),
        "skills": {},
        "excluded": EXCLUSIONS,
        "patches": {},
    }

    for name in included:
        dest_name = RENAMES.get(name, name)
        if name in LOCAL_SKILLS:
            if not (DEST / name / "SKILL.md").is_file():
                sys.exit(f"local skill {name} missing SKILL.md at {DEST.relative_to(REPO_ROOT)}/{name}")
            state["skills"][name] = {
                "source": "local",
                "sha256": "local",
            }
            continue
        if name in GIT_SOURCES:
            repo, relpath = GIT_SOURCES[name]
            src = Path(repo) / relpath
            copy_skill_from_git(dest_name, Path(repo), relpath, DEST)
            print(f"  vendored {dest_name:<22} (git-tracked only, from {relpath})")
        else:
            src = SOURCE / name
            if not src.is_dir():
                sys.exit(f"missing source for {name}: {src}")
            copy_skill(dest_name, src, DEST)
            if dest_name != name:
                print(f"  vendored {dest_name:<22} (renamed from {name})")
            else:
                print(f"  vendored {name}")
        patches = apply_patches(dest_name)
        if patches:
            state["patches"][dest_name] = patches  # type: ignore[index]
        dialect_rewrite_tree(DEST / dest_name)
        state["skills"][dest_name] = {  # type: ignore[index]
            "source": str(src),
            "sha256": source_digest(name, src) if (src / "SKILL.md").is_file() else "git",
        }

    # Prune anything vendored previously that is no longer in the set, so a
    # removed skill cannot linger and keep registering. Compare against the
    # on-disk (post-rename) names.
    dest_names = {RENAMES.get(n, n) for n in included}
    for child in sorted(DEST.iterdir()):
        if child.is_dir() and child.name not in dest_names:
            shutil.rmtree(child)
            print(f"  pruned  {child.name}")

    SYNC_STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

    hits = find_host_paths()
    if hits:
        print("\nhost absolute paths found in vendored skills:", file=sys.stderr)
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        sys.exit(1)
    print(f"\nwrote {SYNC_STATE.relative_to(REPO_ROOT)}")


def check_mode() -> int:
    """Fail if the vendored copy drifted from its recorded source state.

    A skill source that is not on this machine is reported but is not a
    failure: the vendored copy is the committed artifact, and the farm it came
    from exists only where the farm was mounted. Failing on its absence would
    make `make ci` fail on every driverless Spark node and on any runner,
    which is the opposite of the point — the suite is vendored so that a bare
    clone works without the farm. Drift is only knowable between two trees
    that are both present, so that is what is checked and that still fails.
    """
    if not SYNC_STATE.is_file():
        print("no .sync.json — run --apply first", file=sys.stderr)
        return 1
    state = json.loads(SYNC_STATE.read_text())
    problems: list[str] = []
    unverifiable: list[str] = []

    if state.get("upstream_commit") != UPSTREAM_COMMIT:
        problems.append(f"upstream commit moved: recorded {state.get('upstream_commit')}, constant {UPSTREAM_COMMIT}")

    recorded = state.get("skills", {})
    present = {p.name for p in DEST.iterdir() if p.is_dir()}
    for missing in sorted(set(recorded) - present):
        problems.append(f"{missing}: vendored copy is gone")
    for extra in sorted(present - set(recorded)):
        problems.append(f"{extra}: vendored but not in .sync.json (prune it)")

    for name, meta in sorted(recorded.items()):  # type: ignore[union-attr]
        if not (DEST / name / "SKILL.md").is_file():
            problems.append(f"{name}: vendored copy has no SKILL.md")
            continue
        if meta.get("source") == "local":
            # Authored in-repo; nothing to compare against, presence verified above.
            continue
        if meta["sha256"] == "git":
            # Git-sourced: the working tree may be polluted, so verify the
            # commit the vendoring was pinned to instead of hashing the tree.
            repo = Path(meta["source"]).parents[1]
            if not repo.is_dir():
                unverifiable.append(f"{name}: git source {repo} not on this machine")
                continue
            head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if not head.startswith(UPSTREAM_COMMIT):
                problems.append(f"{name}: upstream is at {head}, vendored from {UPSTREAM_COMMIT}")
            continue
        src = Path(meta["source"])
        if not src.is_dir():
            unverifiable.append(f"{name}: source {src} not on this machine")
            continue
        if source_digest(name, src) != meta["sha256"]:
            problems.append(f"{name}: upstream source changed — review and re-sync")

    for name, reason in EXCLUSIONS.items():
        if (DEST / name).exists():
            problems.append(f"{name}: excluded skill is vendored ({reason})")

    for hit in find_host_paths():
        problems.append(f"host absolute path in vendored file — {hit}")

    if unverifiable:
        print(
            f"{len(unverifiable)} of {len(recorded)} sources are not on this machine; their digests were not compared:"
        )
        for note in unverifiable:
            print(f"  - {note}")
        print("(run --check on the machine hosting the skill farm for the full comparison)")

    if problems:
        print("wiki skill vendoring is stale:", file=sys.stderr)
        for problem in problems:
            print(f"  ✗ {problem}", file=sys.stderr)
        print("\nRun scripts/sync-wiki-skills.py --apply after reviewing upstream.", file=sys.stderr)
        return 1

    print(f"vendored wiki skills match source ({len(recorded)} skills, {SYNC_STATE.name} current)")
    return 0


SOURCE = Path(os.environ.get("SPARKNET_WIKI_SKILL_SOURCE", DEFAULT_SOURCE))


def main() -> int:
    global SOURCE
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="copy skills into the repo")
    group.add_argument("--check", action="store_true", help="verify the vendored copy")
    args = parser.parse_args()

    if args.apply:
        apply_mode()
        return 0
    return check_mode()


if __name__ == "__main__":
    raise SystemExit(main())

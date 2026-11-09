"""The role-local skill catalogs must stay loadable, sellable and in sync."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC = REPO_ROOT / "scripts" / "sync-role-skills.py"
PEER = REPO_ROOT / "peer-node" / ".opencode" / "skills"
MASTER = REPO_ROOT / "master-node" / ".opencode" / "skills"


def load_sync():
    return load_by_path("sync_role_skills", SYNC)


def manifest(role_dir: Path) -> dict:
    return json.loads((role_dir / ".inventory.json").read_text(encoding="utf-8"))


def test_sync_check_passes():
    result = subprocess.run(
        [sys.executable, str(SYNC), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_peer_catalog_is_the_expected_set():
    sync = load_sync()
    data = manifest(PEER)
    assert data["counts"]["skills"] == len(sync.PEER_SKILLS)
    assert set(data["skills"]) == set(sync.PEER_SKILLS)


def test_removed_skills_are_absent_from_both_catalogs():
    sync = load_sync()
    for role_dir in (PEER, MASTER):
        present = set(manifest(role_dir)["skills"])
        assert not (present & sync.REMOVED_NAMES), f"{role_dir} still ships a removed skill"


@pytest.mark.parametrize("role_dir", [PEER, MASTER], ids=["peer", "master"])
def test_every_role_skill_is_sellable(role_dir: Path):
    sync = load_sync()
    data = manifest(role_dir)
    for name, meta in data["skills"].items():
        assert meta["license"] in sync.ALLOWED_LICENSES, f"{role_dir}/{name}: {meta['license']}"
        assert meta["sellable"] is True, f"{role_dir}/{name}: not sellable"
        assert name not in sync.REMOVED_NAMES
        assert name not in sync.LOCAL_UNKNOWN_NAMES


def test_master_catalog_has_not_silently_shrunk():
    data = manifest(MASTER)
    assert data["counts"]["skills"] >= 1600, (
        f"master role-local catalog is only {data['counts']['skills']} skills; "
        "the sellable corpus should be far larger — regenerate with make role-skills"
    )


def test_master_keeps_claude_api_optional_and_not_standard():
    data = manifest(MASTER)
    claude = data["skills"]["claude-api"]
    assert claude["tier"] == "optional"
    assert claude["license"] == "Apache-2.0"
    assert "claude-api" not in manifest(PEER)["skills"]


def test_peer_backfills_are_present():
    present = set(manifest(PEER)["skills"])
    for name in (
        "skill-template",
        "writing-for-agents",
        "nano-pdf",
        "file-conversion",
        "mcp-developer",
        "grill-me",
        "handoff",
    ):
        assert name in present, f"peer is missing {name}"


def test_skill_template_is_original_dual_licensed_and_identical():
    peer = PEER / "skill-template"
    master = MASTER / "skill-template"
    for skill in (peer, master):
        assert (skill / "SKILL.md").is_file()
        assert (skill / "LICENSE-MIT").is_file()
        assert (skill / "LICENSE-APACHE").is_file()
        assert (skill / "PROVENANCE.md").is_file()
    assert (peer / "SKILL.md").read_bytes() == (master / "SKILL.md").read_bytes()
    assert "MIT OR Apache-2.0" in (peer / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("role_dir", [PEER, MASTER], ids=["peer", "master"])
def test_role_skills_have_no_nested_skill_or_symlink(role_dir: Path):
    for name in manifest(role_dir)["skills"]:
        skill = role_dir / name
        nested = [path for path in skill.rglob("SKILL.md") if path.parent != skill]
        assert not nested, f"{skill}: nested SKILL.md would be discovered: {nested}"
        assert not any(path.is_symlink() for path in skill.rglob("*")), f"{skill}: symlink present"


def test_master_does_not_shadow_the_base_suite():
    root_names = {path.parent.name for path in (REPO_ROOT / ".opencode" / "skills").rglob("SKILL.md")}
    assert not (set(manifest(MASTER)["skills"]) & root_names)


def test_bundle_verify_checks_role_manifests():
    script = (REPO_ROOT / "scripts" / "sparknet-bundle.sh").read_text(encoding="utf-8")
    assert "sync-role-skills.py" in script
    assert "--check --role" in script
    assert "role-local skills present and sellable" in script

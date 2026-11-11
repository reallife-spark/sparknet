"""The skill catalog engine and its four family adapters."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from skill_catalog import engine  # noqa: E402 - scripts/ is added by path above

pytestmark = pytest.mark.layout


ADAPTERS = {
    "wiki": SCRIPTS / "sync-wiki-skills.py",
    "mattpocock": SCRIPTS / "sync-mattpocock-skills.py",
    "understand": SCRIPTS / "sync-understand-skills.py",
    "role": SCRIPTS / "sync-role-skills.py",
}


def _write(root: Path, rel: str, text: str = "x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_all_four_adapters_use_the_engine() -> None:
    for name, path in ADAPTERS.items():
        module = load_by_path(f"skill_catalog_adapter_{name}", path)
        assert module.engine is engine, f"{name} does not use the one engine"


def test_tree_digest_is_deterministic_and_path_sensitive(tmp_path: Path) -> None:
    first = tmp_path / "first"
    _write(first, "SKILL.md", "one")
    _write(first, "references/a.md", "a")
    digest_a, files_a = engine.tree_digest(first)
    digest_b, files_b = engine.tree_digest(first)
    assert digest_a == digest_b
    assert files_a == files_b
    (first / "references" / "a.md").rename(first / "references" / "b.md")
    assert engine.tree_digest(first)[0] != digest_a


def test_source_digest_skips_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "source"
    _write(root, "SKILL.md", "one")
    os.symlink(root / "SKILL.md", root / "link.md")
    before = engine.source_digest(root)
    (root / "link.md").unlink()
    assert engine.source_digest(root) == before


def test_copy_tree_prunes_or_skips_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write(source, "SKILL.md", "one")
    _write(source, "references/a.md", "a")
    os.symlink(source / "SKILL.md", source / "link.md")
    pruned = tmp_path / "pruned"
    files, skipped = engine.copy_tree(source, pruned, prune=True)
    assert files == 3
    assert skipped == []
    assert not (pruned / "link.md").is_symlink()
    skipped_copy = tmp_path / "skipped"
    files, skipped = engine.copy_tree(source, skipped_copy, skip_symlinks=True)
    assert files == 2
    assert "link.md" in skipped


def test_host_path_guard_uses_family_policy(tmp_path: Path) -> None:
    root = tmp_path / "skill"
    _write(root, "SKILL.md", "/home/raxxar/private\n/Users/name/example\n/Users/real/example\n")
    _write(root, "references/Application/Users/GetUserQuery.cs", "// Application/Users/GetUserQuery.cs\n")
    hits = engine.host_path_hits(
        root,
        markers=("/home/raxxar",),
        home_placeholders={"name"},
        include_names={"SKILL.md"},
    )
    rendered = {(path.name, marker) for path, marker in hits}
    assert ("SKILL.md", "/home/raxxar") in rendered
    assert ("SKILL.md", "/Users/real") in rendered
    assert not any(marker == "/Users/name" for _, marker in rendered)
    assert not any(path.name == "GetUserQuery.cs" for path, _ in hits)


def test_role_adapter_copy_payload_uses_engine(tmp_path: Path) -> None:
    role = load_by_path("skill_catalog_adapter_role_copy", ADAPTERS["role"])
    source = tmp_path / "source"
    _write(source, "SKILL.md", "one")
    _write(source, "references/a.md", "a")
    _write(source, "references/nested/SKILL.md", "nested")
    os.symlink(source / "SKILL.md", source / "link.md")
    dest = tmp_path / "dest"
    files, skipped = role.copy_payload(source, dest, "source")
    assert files == 2
    assert (dest / "SKILL.md").is_file()
    assert (dest / "references" / "a.md").is_file()
    assert not (dest / "references" / "nested" / "SKILL.md").exists()
    assert not (dest / "link.md").exists()
    assert "link.md" in skipped


def test_manifest_read_write_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    engine.write_manifest(path, {"b": 2, "a": 1})
    assert engine.read_manifest(path) == {"a": 1, "b": 2}
    assert engine.read_manifest(tmp_path / "missing.json", default={}) == {}

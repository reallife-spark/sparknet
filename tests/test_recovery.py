"""The Phase 9 recovery tool: snapshot, verify, rehearse and guarded restore."""

from __future__ import annotations

import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-recovery.py"


def _load():
    return load_by_path("sparknet_recovery_test", SCRIPT)


recovery = _load()


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "00_System").mkdir(parents=True)
    (root / "00_System" / "index.md").write_text("index\n")
    (root / "01_Inbox").mkdir()
    (root / "01_Inbox" / "note.md").write_text("note\n")
    (root / "PLAN.md").write_text("plan\n")
    (root / "plans").mkdir()
    (root / "plans" / "MASTER_BUILD_PLAN.md").symlink_to("../PLAN.md")
    (root / ".state" / "keys").mkdir(parents=True)
    (root / ".state" / "keys" / "node.ed25519").write_text("secret\n")
    (root / ".state" / "qdrant").mkdir()
    (root / ".state" / "qdrant" / "huge.sqlite3").write_text("derived\n")
    (root / "note-link").symlink_to("01_Inbox/note.md")
    return root


def test_snapshot_manifest_is_private_and_excludes_derived_state(tmp_path: Path):
    root = _tree(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    manifest = recovery.snapshot(root, archive)
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    data = __import__("json").loads(manifest.read_text())
    assert "00_System/index.md" in data["files"]
    assert ".state/keys/node.ed25519" in data["files"]
    assert ".state/qdrant/huge.sqlite3" not in data["files"]
    assert recovery.verify(archive)["files"] == data["files"]


def test_verify_refuses_a_changed_archive(tmp_path: Path):
    archive = tmp_path / "backup.tar.gz"
    recovery.snapshot(_tree(tmp_path), archive)
    with archive.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(SystemExit, match="digest"):
        recovery.verify(archive)


def test_rehearse_deletes_and_restores_a_file(tmp_path: Path):
    archive = tmp_path / "backup.tar.gz"
    recovery.snapshot(_tree(tmp_path), archive)
    result = recovery.rehearse(archive, tmp_path / "work")
    assert result["ok"] is True
    assert (Path(result["work"]) / "restored" / result["sample"]).is_file()


def test_restore_needs_the_exact_phrase_and_target_guard(tmp_path: Path):
    archive = tmp_path / "backup.tar.gz"
    recovery.snapshot(_tree(tmp_path), archive)
    with pytest.raises(SystemExit, match="confirmation"):
        recovery.restore(archive, tmp_path / "target", confirm="no", live=False)
    with pytest.raises(SystemExit, match="unsafe target"):
        recovery.restore(archive, Path("/"), confirm=recovery.PHRASE, live=False)


def test_live_restore_is_windowed_and_rehearsable(tmp_path: Path):
    archive = tmp_path / "backup.tar.gz"
    recovery.snapshot(_tree(tmp_path), archive)
    target = tmp_path / "target"
    outside = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(SystemExit) as refused:
        recovery.restore(archive, target, confirm=recovery.PHRASE, live=True, now=outside)
    assert "2026-11-01T03:00" in str(refused.value)
    assert "2026-11-01T06:00" in str(refused.value)
    inside = datetime(2026, 11, 1, 3, 30, tzinfo=timezone.utc)
    recovery.restore(archive, target, confirm=recovery.PHRASE, live=True, now=inside)
    assert (target / "00_System" / "index.md").read_text() == "index\n"
    assert (target / ".sparknet-restore-receipt.json").is_file()

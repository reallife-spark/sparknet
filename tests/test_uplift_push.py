"""Uplift push must not turn its transport into an unbounded disk leak.

The snapshot sync runs every fifteen minutes. A failed push spools a payload,
and Qdrant keeps every snapshot it creates. These tests pin the retention and
orphan-sweep behaviour that stopped the peer's root disk from filling.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-uplift-push.py"


@pytest.fixture(scope="module")
def push():
    return load_by_path("sparknet_uplift_push_test", SCRIPT)


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(tmp_path))
    return tmp_path


def _outbox(state: Path) -> Path:
    path = state / "uplift" / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _age(path: Path, seconds: int) -> None:
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def test_spool_deduplicates_identical_payloads(push, state: Path) -> None:
    body = b"x" * 1024
    first = push.spool("snapshot", body, {"collection": "a"}, "http://master")
    second = push.spool("snapshot", body, {"collection": "a"}, "http://master")

    assert first == second
    outbox = _outbox(state)
    assert len(list(outbox.glob("*.json"))) == 1
    assert len(list(outbox.glob("*.bin"))) == 1


def test_send_without_spool_keeps_outbox_clean(push, state: Path, monkeypatch) -> None:
    monkeypatch.setattr(push, "post", lambda *args, **kwargs: (500, {"detail": "down"}))

    ok = push.send("snapshot", b"payload", {"collection": "a"}, spool_failures=False)

    assert ok is False
    assert list(_outbox(state).glob("*.bin")) == []


def test_drain_unlinks_payload_for_unreadable_row(push, state: Path) -> None:
    outbox = _outbox(state)
    payload = outbox / "snapshot-1-1.bin"
    payload.write_bytes(b"payload")
    job = outbox / "snapshot-1-1.json"
    job.write_text("{not json", encoding="utf-8")

    assert push.drain(endpoint="http://127.0.0.1:9") == 0
    assert not payload.exists()
    assert not job.exists()


def test_drain_retry_does_not_duplicate_a_failed_row(push, state: Path, monkeypatch) -> None:
    outbox = _outbox(state)
    payload = outbox / "snapshot-1-1.bin"
    payload.write_bytes(b"payload")
    job = outbox / "snapshot-1-1.json"
    job.write_text(
        json.dumps({"kind": "snapshot", "manifest": {}, "payload": str(payload), "sha256": "x"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(push, "send", lambda *args, **kwargs: False)

    assert push.drain(endpoint="http://127.0.0.1:9") == 0
    assert job.exists()
    assert payload.exists()
    assert len(list(outbox.glob("*.json"))) == 1
    assert len(list(outbox.glob("*.bin"))) == 1


def test_sweep_removes_stale_unreferenced_payloads(push, state: Path) -> None:
    outbox = _outbox(state)
    stale = outbox / "stale.bin"
    stale.write_bytes(b"stale")
    _age(stale, 7200)
    recent = outbox / "recent.bin"
    recent.write_bytes(b"recent")
    referenced = outbox / "referenced.bin"
    referenced.write_bytes(b"referenced")
    _age(referenced, 7200)
    (outbox / "referenced.json").write_text(
        json.dumps({"kind": "snapshot", "payload": str(referenced)}), encoding="utf-8"
    )

    assert push._sweep_orphans(outbox) == 1
    assert not stale.exists()
    assert recent.exists()
    assert referenced.exists()


def test_snapshot_guard_refuses_the_root_filesystem(push, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_QDRANT_SNAPSHOT_DIR", "/etc")
    with pytest.raises(push.PushError, match="root filesystem"):
        push.qdrant_snapshot("sparknet-peer")


def test_outbox_is_capped_to_oldest_first(push, state: Path, monkeypatch) -> None:
    monkeypatch.setattr(push, "OUTBOX_MAX_BYTES", 10)
    for index in range(3):
        push.spool("snapshot", b"x" * 8 + bytes([index]), {"n": index}, "http://master")

    outbox = _outbox(state)
    assert len(list(outbox.glob("*.json"))) == 1
    assert len(list(outbox.glob("*.bin"))) == 1


def test_prune_keeps_newest_snapshot_per_collection(push, monkeypatch) -> None:
    rows = {
        "a": [
            {"name": "a-old", "creation_time": "2026-01-01T00:00:00Z"},
            {"name": "a-new", "creation_time": "2026-01-02T00:00:00Z"},
        ],
        "b": [
            {"name": "b-old", "creation_time": "2026-01-01T00:00:00Z"},
            {"name": "b-new", "creation_time": "2026-01-02T00:00:00Z"},
        ],
    }
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(push, "qdrant_collections", lambda **kwargs: ["a", "b"])
    monkeypatch.setattr(push, "qdrant_snapshots", lambda collection, **kwargs: list(rows[collection]))
    monkeypatch.setattr(
        push,
        "delete_qdrant_snapshot",
        lambda collection, name, **kwargs: deleted.append((collection, name)) or True,
    )

    assert push.prune_qdrant_snapshots(1) == 2
    assert sorted(deleted) == [("a", "a-old"), ("b", "b-old")]


def test_student_artifact_uses_the_signed_8091_route(push, monkeypatch) -> None:
    seen: dict = {}

    def fake_post(route, body, **kwargs):
        seen.update({"route": route, "body": body, **kwargs})
        return 200, {"ok": True}

    monkeypatch.setattr(push, "post", fake_post)
    assert push.send("student", b"gguf", {"sha256": "x", "size": 4}) is True
    assert seen["route"] == "/api/v1/student-artifact"
    assert "X-Sparknet-Manifest" in seen["extra"]

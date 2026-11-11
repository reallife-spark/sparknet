"""The one shared issue module: parse, redact, store, triage and projection."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPO_ROOT / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

issue = load_by_path("sparknet_issue_module_test", SHARED / "sparknet-issue.py")
FP = "a" * 64
NODE = "sparknet-node-0002"


def _issue_file(root: Path, *, body: str = "The console returns 401.", digest: str | None = None) -> Path:
    path = root / ".scratch" / "issues" / "fix-token.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body_digest = digest or hashlib.sha256((body + "\n").encode()).hexdigest()
    path.write_text(
        "---\n"
        "schema: sparknet-issue/1\n"
        "id: fix-token\n"
        "title: Console token\n"
        "status: open\n"
        "labels: [needs-triage]\n"
        "reporter: operator\n"
        "created_at: 2026-11-10T10:00:00Z\n"
        "updated_at: 2026-11-10T10:00:00Z\n"
        "source: .\n"
        f"body_sha256: {body_digest}\n"
        "links:\n"
        "  - kind: file\n"
        "    ref: scripts/sparknet-console.py\n"
        "---\n" + body + "\n",
        encoding="utf-8",
    )
    return path


def test_parse_validate_and_build_payload(tmp_path: Path) -> None:
    document = issue.parse_issue_file(_issue_file(tmp_path))
    assert document.meta["id"] == "fix-token"
    payload = issue.build_payload(
        document.meta,
        document.body,
        authz=issue.authz,
        node=NODE,
        fingerprint=FP,
    )
    assert payload["issue_id"] == "fix-token"
    assert payload["labels"] == ["needs-triage"]
    assert payload["content_sha256"] == hashlib.sha256(document.body.encode()).hexdigest()


def test_body_digest_and_secret_are_refused(tmp_path: Path) -> None:
    with pytest.raises(issue.IssueError) as exc:
        issue.parse_issue_file(_issue_file(tmp_path, digest="0" * 64))
    assert exc.value.reason == "body_digest"
    with pytest.raises(issue.IssueError) as exc:
        issue.prepare_payload(
            _issue_file(tmp_path, body="password=supersecret12345").read_text(),
            path=tmp_path / ".scratch" / "issues" / "fix-token.md",
            node=NODE,
            fingerprint=FP,
            authz=issue.authz,
        )
    assert exc.value.reason == "secret_shaped"


def test_store_latest_view_and_duplicate(tmp_path: Path) -> None:
    store = issue.IssueStore(tmp_path / "issues.jsonl", state_dir=tmp_path / "state")
    first = {
        "node_id": NODE,
        "issue_id": "fix-token",
        "updated_at": "2026-11-10T10:00:00Z",
        "nonce": "n1",
    }
    assert store.record(first, source="10.100.0.2/32") == "recorded"
    assert store.record(first, source="10.100.0.2/32") == "duplicate"
    second = {**first, "updated_at": "2026-11-10T10:01:00Z", "nonce": "n2"}
    assert store.record(second, source="10.100.0.2/32") == "recorded"
    assert len(store.listing()) == 1
    assert store.listing()[0]["updated_at"] == "2026-11-10T10:01:00Z"
    assert store.listing()[0]["received_from"] == "10.100.0.2"


def test_triage_append_and_projection(tmp_path: Path) -> None:
    issue_path = tmp_path / "issues.jsonl"
    issue_path.write_text(
        json.dumps(
            {
                "received_at": "2026-11-10T10:00:00Z",
                "node_id": NODE,
                "issue_id": "fix-token",
                "title": "Console token",
                "body": "401",
                "status": "open",
                "labels": ["needs-triage"],
                "updated_at": "2026-11-10T10:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    triage = issue.TriageStore(tmp_path / "state")
    triage.transition(
        NODE,
        "fix-token",
        status="triaged",
        labels=["ready-for-agent"],
        actor="operator",
        note="reproduced",
        now=datetime(2026, 11, 10, 10, 5, tzinfo=timezone.utc),
    )
    assert (tmp_path / "state" / "issues" / "triage.jsonl").is_file()
    assert issue.TriageStore(tmp_path / "state").view()[f"{NODE}:fix-token"]["status"] == "triaged"
    result = issue.load_projection(issue_path, tmp_path / "state")
    assert result["issues"][0]["effective_status"] == "triaged"
    assert result["issues"][0]["effective_labels"] == ["ready-for-agent"]
    assert result["counts"]["open"] == 1
    assert result["counts"]["ready_for_agent"] == 1


def test_legacy_triage_view_is_seeded(tmp_path: Path) -> None:
    state = tmp_path / "state"
    (state / "issues").mkdir(parents=True)
    (state / "issues" / "triage.json").write_text(
        json.dumps({f"{NODE}:fix-token": {"status": "blocked", "labels": ["needs-info"]}}),
        encoding="utf-8",
    )
    view = issue.TriageStore(state).view()
    assert view[f"{NODE}:fix-token"]["status"] == "blocked"


def test_triage_refuses_empty_or_unknown_state(tmp_path: Path) -> None:
    triage = issue.TriageStore(tmp_path / "state")
    with pytest.raises(issue.IssueError):
        triage.transition(NODE, "fix-token")
    with pytest.raises(issue.IssueError):
        triage.transition(NODE, "fix-token", status="invented")
    with pytest.raises(issue.IssueError):
        triage.transition(NODE, "fix-token", labels=["invented"])

"""The issue report envelope: one builder/verifier, contract-shaped.

An issue is operational work. These tests pin the bytes and the refusals so the
peer pusher and the Master intake cannot drift into two different envelopes.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.contract


REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = json.loads((REPO_ROOT / "contracts" / "issue-schema.json").read_text())
SHARED = REPO_ROOT / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))


def _load_authz():
    return load_by_path("sparknet_issue_authz_test", SHARED / "sparknet-authz.py")


authz = _load_authz()
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
FP = "a" * 64


def report(**overrides):
    values = {
        "issue_id": "fix-console-token",
        "node_id": "sparknet-node-0002",
        "peer_fingerprint": FP,
        "title": "Console rejects a valid token",
        "body": "The token is valid but the console returns 401.",
        "status": "open",
        "labels": ["needs-triage"],
        "links": [{"kind": "file", "ref": "scripts/sparknet-console.py"}],
        "source": ".",
        "now": NOW,
        "nonce": "b" * 32,
    }
    values.update(overrides)
    return authz.build_issue_report(**values)


def test_contract_fields_match_the_implementation() -> None:
    assert tuple(CONTRACT["wire"]["fields"]) == authz.ISSUE_REPORT_FIELDS
    assert set(CONTRACT["local"]["labels"]["canonical"]) == authz.ISSUE_LABELS
    assert set(CONTRACT["local"]["frontmatter"]["fields"]["status"].split(" | ")) == authz.ISSUE_STATUSES
    assert (
        "issue-report" in json.loads((REPO_ROOT / "contracts" / "capabilities.json").read_text())["known_capabilities"]
    )


def test_local_triage_history_is_append_only() -> None:
    store = CONTRACT["store"]
    assert store["triage_ledger"].endswith("triage.jsonl")
    assert "derived" in store["triage_state"]
    assert "appends to triage.jsonl" in store["retention"]


def test_round_trip_accepts_one_report() -> None:
    value = report()
    assert value["schema"] == "sparknet-issue/1"
    assert value["content_sha256"] == authz.hashlib.sha256(value["body"].encode()).hexdigest()
    assert authz.verify_issue_report(value, expected_fingerprint=FP, now=NOW) == (True, "")


def test_wrong_peer_is_refused() -> None:
    ok, reason = authz.verify_issue_report(report(), expected_fingerprint="c" * 64, now=NOW)
    assert ok is False and reason == "wrong_peer"


def test_digest_mismatch_is_refused() -> None:
    value = report()
    value["body"] = "tampered after the digest was computed"
    ok, reason = authz.verify_issue_report(value, expected_fingerprint=FP, now=NOW)
    assert ok is False and reason == "digest_mismatch"


def test_expired_and_replayed_are_refused() -> None:
    value = report(ttl_seconds=1)
    ok, reason = authz.verify_issue_report(value, expected_fingerprint=FP, now=NOW + timedelta(seconds=10))
    assert ok is False and reason == "expired"
    ok, reason = authz.verify_issue_report(value, expected_fingerprint=FP, now=NOW, seen_nonces={value["nonce"]})
    assert ok is False and reason == "replayed_nonce"


def test_malformed_shapes_are_refused() -> None:
    value = report()
    value["extra"] = True
    assert authz.verify_issue_report(value, expected_fingerprint=FP, now=NOW)[1] == "malformed"
    value = report()
    value["status"] = "invented"
    assert authz.verify_issue_report(value, expected_fingerprint=FP, now=NOW)[1] == "malformed"
    value = report()
    value["labels"] = ["not-a-label"]
    assert authz.verify_issue_report(value, expected_fingerprint=FP, now=NOW)[1] == "malformed"


def test_builder_refuses_an_unknown_label_and_a_long_title() -> None:
    with pytest.raises(authz.AuthzError):
        report(labels=["invented"])
    with pytest.raises(authz.AuthzError):
        report(title="x" * (authz.ISSUE_MAX_TITLE + 1))
    with pytest.raises(authz.AuthzError):
        report(issue_id="Not A Slug")
